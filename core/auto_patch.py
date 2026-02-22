"""
Elyan Auto-Patch Engine — Autonomous Self-Healing

Hata kodlarına (Failure Clustering) göre DAG düğümlerini onarır.
Düğüm tekrar çalıştırılmadan (retry) önce parametrelerini veya prompt'unu günceller.
"""

from typing import Any, Dict, List, Optional
from core.cdg_engine import DAGNode, QAGate
from core.failure_clustering import failure_clustering, FailureCode
from utils.logger import get_logger

logger = get_logger("auto_patch")


class AutoPatchEngine:
    """Otonom onarım motoru."""

    def apply_patch(self, node: DAGNode, failed_gates: List[QAGate] = None) -> bool:
        """
        Düğümü onarmak için playbook uygular.
        Returns True if a patch was applied.
        """
        fail_code = None
        error_context = ""

        # 1. Hata kodunu belirle
        if failed_gates:
            gate = failed_gates[0]
            error_context = f"QA Gate Failed: {gate.name} ({gate.message})"
            if gate.check_type == "file_not_empty":
                fail_code = FailureCode.TOOL_WRITE_EMPTY
            elif gate.check_type == "html_valid":
                fail_code = FailureCode.HTML_BAD_STRUCTURE
            elif gate.check_type == "file_exists":
                fail_code = FailureCode.CONTRACT_ARTIFACT_MISSING
            elif gate.check_type == "content_check":
                if "kaynak" in gate.params.get("contains", "").lower() or "http" in gate.params.get("contains", "").lower():
                    fail_code = FailureCode.SOURCES_MISSING
                else:
                    fail_code = FailureCode.CONTRACT_QA_FAILED
        elif node.error:
            error_context = node.error
            fail_code = failure_clustering.detect_failure_code(node.error, node.action, str(node.result))
        else:
            return False

        if not fail_code:
            return False

        # Telemetry kaydı
        failure_clustering.record(fail_code, "auto_patch", error_context[:200])
        logger.warning(f"Auto-Patch triggered for node '{node.id}' — Code: {fail_code}")

        # 2. Playbook'u al
        playbook = failure_clustering.get_playbook(fail_code)
        if not playbook:
            logger.info(f"No playbook for {fail_code}, fallback to generic retry.")
            return self._apply_generic_patch(node, error_context)

        # 3. Stratejiyi uygula
        strategy = playbook.get("strategy")
        if strategy == "retry_with_validation" or strategy == "template_enforce":
            return self._patch_content_generation(node, fail_code, playbook)
        elif strategy == "enforce_citations":
            return self._patch_citations(node)
        elif strategy == "retry_missing_only":
            return self._patch_missing_file(node, failed_gates)
        elif strategy == "lint_and_fix":
            return self._patch_code_fix(node, error_context)

        return self._apply_generic_patch(node, error_context)

    def _patch_content_generation(self, node: DAGNode, code: str, playbook: dict) -> bool:
        """İçerik üretim hatalarını onarır (boş dosya, bozuk HTML)."""
        rules = " ".join(playbook.get("steps", []))
        patch_instruction = f"\n\n[AUTO-PATCH {code}]: Önceki deneme başarısız oldu. Lütfen şu kurallara kesinlikle uy: {rules}"
        
        # Eğer parametrelerde prompt/content varsa ona ekle
        modified = False
        for key in ("prompt", "content", "instructions", "text"):
            if key in node.params and isinstance(node.params[key], str):
                node.params[key] += patch_instruction
                modified = True
                break
        
        if not modified:
            # Fallback param inject
            node.params["_auto_patch_instruction"] = patch_instruction

        logger.info(f"Applied content generation patch to {node.id}")
        return True

    def _patch_citations(self, node: DAGNode) -> bool:
        """Kaynak eksikliği hatasını onarır."""
        patch = "\n\n[AUTO-PATCH SOURCES_MISSING]: Lütfen rapordaki her iddia için MUTLAKA [kaynak_linki] formatında veya http linki ile referans göster. Kaynaksız iddia kabul edilemez."
        if "prompt" in node.params and isinstance(node.params["prompt"], str):
            node.params["prompt"] += patch
        else:
            node.params["_auto_patch_instruction"] = patch
        return True

    def _patch_missing_file(self, node: DAGNode, failed_gates: List[QAGate]) -> bool:
        """Dosya yok hatasını onarır."""
        missing = [g.params.get("path") for g in failed_gates if g.check_type == "file_exists"]
        if missing:
            patch = f"\n\n[AUTO-PATCH ARTIFACT_MISSING]: Şu dosyanın eksiksiz oluşturulması ZORUNLUDUR: {', '.join(missing)}"
            node.params["_auto_patch_instruction"] = patch
            return True
        return False

    def _patch_code_fix(self, node: DAGNode, error: str) -> bool:
        """Kod syntax/lint hatalarını onarır."""
        patch = f"\n\n[AUTO-PATCH CODE_SYNTAX_ERROR]: Kodu derlerken syntax hatası aldık:\n{error[-300:]}\nLütfen sadece bu hatayı düzelterek kodu yeniden yaz."
        node.params["_auto_patch_instruction"] = patch
        return True

    def _apply_generic_patch(self, node: DAGNode, error: str) -> bool:
        """Özel playbook yoksa genel hata düzeltme talimatı ekler."""
        if not error:
            return False
            
        patch = f"\n\n[AUTO-PATCH GENERIC]: Önceki işlem şu hata ile başarısız oldu: '{error[-200:]}'. Lütfen hatayı giderip tekrar dene."
        node.params["_auto_patch_instruction"] = patch
        return True


# Global instance
auto_patch = AutoPatchEngine()
