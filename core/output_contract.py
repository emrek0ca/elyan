"""
core/output_contract.py
─────────────────────────────────────────────────────────────────────────────
Elyan Output Contract System — Plan → Execute → Verify → Repair döngüsü

Her görev çalışmadan önce bir "deliverable spec" üretilir.
Execution sonrası bu spec'e göre otomatik doğrulama yapılır.
Doğrulama başarısızsa Repair Loop tetiklenir.

Kural:
  1. Boş dosya yazmak başarı değildir (CONTENT_TOO_SHORT)
  2. Yanlış format fallback yasak (DOCX istendi → txt'ye düşme yok)
  3. Verify olmadan DONE denmez
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from utils.logger import get_logger

logger = get_logger("output_contract")


# ── Deliverable Spec ──────────────────────────────────────────────────────────

@dataclass
class ArtifactSpec:
    """Tek bir çıktı dosyası için spesifikasyon."""
    path: str = ""
    artifact_type: str = "file"   # file | docx | xlsx | html | project | code | report
    min_size_bytes: int = 0
    min_word_count: int = 0
    min_line_count: int = 0
    required_patterns: List[str] = field(default_factory=list)   # regex listesi
    forbidden_patterns: List[str] = field(default_factory=list)  # yasak içerik
    must_be_parseable: bool = False   # docx/xlsx için parse kontrolü


@dataclass
class DeliverableSpec:
    """Bir görevin tam çıktı sözleşmesi."""
    task_id: str = ""
    intent: str = ""                     # Kullanıcının asıl niyeti
    artifacts: List[ArtifactSpec] = field(default_factory=list)
    done_criteria: List[str] = field(default_factory=list)       # Metin açıklama
    minimum_content_summary: str = ""    # Beklenen içerik özeti
    created_at: float = field(default_factory=time.time)

    def add_file(
        self,
        path: str,
        artifact_type: str = "file",
        min_size_bytes: int = 200,
        min_word_count: int = 0,
        min_line_count: int = 0,
        required_patterns: List[str] | None = None,
        must_be_parseable: bool = False,
    ) -> ArtifactSpec:
        spec = ArtifactSpec(
            path=path,
            artifact_type=artifact_type,
            min_size_bytes=min_size_bytes,
            min_word_count=min_word_count,
            min_line_count=min_line_count,
            required_patterns=required_patterns or [],
            must_be_parseable=must_be_parseable,
        )
        self.artifacts.append(spec)
        return spec


# ── Verification Result ───────────────────────────────────────────────────────

@dataclass
class VerificationResult:
    passed: bool
    score: float = 0.0          # 0.0 – 1.0
    checks: List[dict] = field(default_factory=list)
    failed_checks: List[str] = field(default_factory=list)
    repair_hints: List[str] = field(default_factory=list)
    artifact_path: str = ""


# ── Contract Verifier ─────────────────────────────────────────────────────────

class ContractVerifier:
    """Deliverable spec'e göre çıktıyı doğrular."""

    def verify_artifact(self, spec: ArtifactSpec) -> VerificationResult:
        checks: list[dict] = []
        failed: list[str] = []
        hints: list[str] = []

        path = Path(spec.path).expanduser()

        # 1. Dosya var mı?
        exists = path.exists() and path.is_file()
        checks.append({"name": "file_exists", "passed": exists, "detail": str(path)})
        if not exists:
            failed.append("file_exists")
            hints.append(f"Dosya oluşturulmamış: {spec.path}")
            return VerificationResult(passed=False, checks=checks, failed_checks=failed,
                                      repair_hints=hints, artifact_path=spec.path)

        # 2. Boyut kontrolü
        size = path.stat().st_size
        size_ok = size >= max(spec.min_size_bytes, 10)
        checks.append({"name": "min_size", "passed": size_ok, "detail": f"{size} bytes >= {spec.min_size_bytes}"})
        if not size_ok:
            failed.append("min_size")
            hints.append(f"Dosya çok küçük ({size} bytes). En az {spec.min_size_bytes} bytes olmalı. İçerik çok az.")

        # 3. İçerik okuma
        content = ""
        if path.suffix.lower() in (".txt", ".md", ".html", ".css", ".js", ".py", ".json", ".csv"):
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass
        elif path.suffix.lower() == ".docx" and spec.must_be_parseable:
            try:
                import docx
                doc = docx.Document(str(path))
                content = "\n".join(p.text for p in doc.paragraphs)
            except ImportError:
                checks.append({"name": "docx_parseable", "passed": False, "detail": "python-docx yüklü değil"})
                failed.append("docx_parseable")
                hints.append("python-docx paketi eksik. 'pip install python-docx' çalıştır.")
            except Exception as e:
                checks.append({"name": "docx_parseable", "passed": False, "detail": str(e)})
                failed.append("docx_parseable")
                hints.append(f"DOCX parse edilemedi: {e}")

        # 4. Kelime sayısı
        if spec.min_word_count > 0 and content:
            word_count = len(content.split())
            wc_ok = word_count >= spec.min_word_count
            checks.append({"name": "min_word_count", "passed": wc_ok,
                          "detail": f"{word_count} words >= {spec.min_word_count}"})
            if not wc_ok:
                failed.append("min_word_count")
                hints.append(f"İçerik çok kısa ({word_count} kelime). En az {spec.min_word_count} kelime olmalı.")

        # 5. Satır sayısı
        if spec.min_line_count > 0 and content:
            line_count = len([l for l in content.splitlines() if l.strip()])
            lc_ok = line_count >= spec.min_line_count
            checks.append({"name": "min_line_count", "passed": lc_ok,
                          "detail": f"{line_count} lines >= {spec.min_line_count}"})
            if not lc_ok:
                failed.append("min_line_count")
                hints.append(f"Dosya çok az içeriyor ({line_count} satır). En az {spec.min_line_count} satır olmalı.")

        # 6. Zorunlu pattern'lar
        for pattern in spec.required_patterns:
            try:
                found = bool(re.search(pattern, content, re.IGNORECASE | re.DOTALL))
                checks.append({"name": f"pattern_{pattern[:30]}", "passed": found,
                              "detail": f"Pattern: {pattern}"})
                if not found:
                    failed.append(f"pattern_{pattern[:30]}")
                    hints.append(f"Beklenen içerik bulunamadı: {pattern}")
            except re.error:
                pass

        # 7. Yasak pattern'lar
        for pattern in spec.forbidden_patterns:
            try:
                found = bool(re.search(pattern, content, re.IGNORECASE))
                checks.append({"name": f"forbidden_{pattern[:30]}", "passed": not found,
                              "detail": f"Forbidden: {pattern}"})
                if found:
                    failed.append(f"forbidden_{pattern[:30]}")
                    hints.append(f"Yasaklı içerik bulundu: {pattern}")
            except re.error:
                pass

        passed = len(failed) == 0
        total = max(len(checks), 1)
        score = sum(1 for c in checks if c.get("passed")) / total

        return VerificationResult(
            passed=passed,
            score=score,
            checks=checks,
            failed_checks=failed,
            repair_hints=hints,
            artifact_path=spec.path,
        )

    def verify_spec(self, spec: DeliverableSpec) -> dict[str, Any]:
        """Tüm spec'i doğrular."""
        results: list[VerificationResult] = []
        for artifact in spec.artifacts:
            r = self.verify_artifact(artifact)
            results.append(r)

        all_passed = all(r.passed for r in results)
        avg_score = sum(r.score for r in results) / max(len(results), 1)
        all_hints = []
        for r in results:
            all_hints.extend(r.repair_hints)

        return {
            "passed": all_passed,
            "score": round(avg_score, 2),
            "artifact_results": [
                {
                    "path": r.artifact_path,
                    "passed": r.passed,
                    "score": r.score,
                    "failed": r.failed_checks,
                    "hints": r.repair_hints,
                }
                for r in results
            ],
            "repair_hints": all_hints[:10],
        }


# ── Contract Repairer ─────────────────────────────────────────────────────────

class ContractRepairer:
    """Doğrulama başarısızsa otomatik onarım stratejileri üretir."""

    def build_repair_prompt(
        self,
        spec: DeliverableSpec,
        verification: dict[str, Any],
        original_user_input: str,
    ) -> str:
        """LLM için repair prompt üretir."""
        hints = "\n".join(f"- {h}" for h in verification.get("repair_hints", []))
        artifacts = "\n".join(
            f"  • {a['path']}: {'✓' if a['passed'] else '✗ BAŞARISIZ'} (score={a['score']:.0%})"
            for a in verification.get("artifact_results", [])
        )
        return (
            f"Görev: {original_user_input}\n"
            f"Beklenen çıktı: {spec.minimum_content_summary or spec.intent}\n\n"
            f"Artifact durumu:\n{artifacts}\n\n"
            f"Başarısızlık nedenleri:\n{hints}\n\n"
            "Lütfen başarısız olan artifact'ları tekrar üret. "
            "Minimum içerik gereksinimlerini karşıla. Boş dosya üretme."
        )

    def suggest_repair_actions(
        self,
        spec: DeliverableSpec,
        verification: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Repair için action listesi önerir."""
        actions: list[dict[str, Any]] = []

        for art_result in verification.get("artifact_results", []):
            if art_result.get("passed"):
                continue
            path = art_result.get("path", "")
            ext = Path(path).suffix.lower() if path else ""
            failed = art_result.get("failed", [])
            hints = art_result.get("hints", [])

            if "file_exists" in failed:
                # Dosya yok → yeniden yaz
                if ext in (".docx", ".doc"):
                    actions.append({"action": "write_word", "params": {"path": path}, "reason": "file_missing"})
                elif ext in (".xlsx", ".xls"):
                    actions.append({"action": "write_excel", "params": {"path": path}, "reason": "file_missing"})
                else:
                    actions.append({"action": "write_file", "params": {"path": path}, "reason": "file_missing"})

            elif "min_size" in failed or "min_word_count" in failed or "min_line_count" in failed:
                # İçerik çok az → zenginleştir
                if ext in (".docx", ".doc"):
                    actions.append({"action": "write_word", "params": {"path": path, "_repair": True}, "reason": "content_too_short", "hints": hints})
                elif ext in (".html",):
                    actions.append({"action": "write_file", "params": {"path": path, "_repair": True}, "reason": "content_too_short", "hints": hints})
                else:
                    actions.append({"action": "write_file", "params": {"path": path, "_repair": True}, "reason": "content_too_short", "hints": hints})

        return actions


# ── Contract Factory ──────────────────────────────────────────────────────────

class ContractFactory:
    """Görev tipine göre otomatik DeliverableSpec üretir."""

    DESKTOP = str(Path.home() / "Desktop")

    def from_action(
        self,
        action: str,
        params: dict,
        user_input: str = "",
    ) -> Optional[DeliverableSpec]:
        """Action + params'tan deliverable spec üretir."""
        spec = DeliverableSpec(
            task_id=f"task_{int(time.time())}",
            intent=user_input or action,
        )

        if action == "write_file":
            path = params.get("path") or params.get("file_path") or f"{self.DESKTOP}/output.txt"
            spec.minimum_content_summary = "Dosya içeriği"
            spec.add_file(path, min_size_bytes=50, min_word_count=5)
            spec.done_criteria.append("Dosya oluşturuldu ve içerik yazıldı.")
            return spec

        if action in ("write_word", "create_word_document"):
            path = params.get("path") or params.get("file_path") or f"{self.DESKTOP}/belge.docx"
            spec.minimum_content_summary = "Word belgesi — başlık + kapsamlı içerik + kaynaklar"
            spec.add_file(path, artifact_type="docx", min_size_bytes=5000,
                         min_word_count=200, must_be_parseable=False)
            spec.done_criteria.extend([
                "Dosya .docx uzantılı ve gerçek bir Word dosyası",
                "En az 200 kelime içeriyor",
                "Başlık, giriş, detaylar ve kaynaklar bölümleri var",
            ])
            return spec

        if action in ("write_excel", "create_excel"):
            path = params.get("path") or params.get("file_path") or f"{self.DESKTOP}/tablo.xlsx"
            spec.minimum_content_summary = "Excel tablosu — başlık satırı + yapılandırılmış veri"
            spec.add_file(path, artifact_type="xlsx", min_size_bytes=2000)
            spec.done_criteria.extend(["Excel dosyası oluşturuldu", "Veri yapısı tutarlı"])
            return spec

        if action in ("create_web_project_scaffold", "create_website"):
            out_dir = params.get("output_dir") or params.get("project_path") or f"{self.DESKTOP}/website"
            project_name = params.get("project_name") or "website"
            base = f"{out_dir}/{project_name}" if not str(out_dir).endswith(project_name) else out_dir
            spec.minimum_content_summary = "Web projesi — index.html + styles.css + app.js (profesyonel yapı)"
            spec.add_file(f"{base}/index.html", artifact_type="html",
                         min_size_bytes=2500, min_line_count=40,
                         required_patterns=[
                             r"<html", r"<body", r"<head", 
                             r"rel=\"stylesheet\"", r"<script.*src=", 
                             r"<nav", r"<section", r"<footer"
                         ])
            spec.add_file(f"{base}/styles.css", artifact_type="file",
                         min_size_bytes=1000, min_line_count=30,
                         required_patterns=[r"margin", r"padding", r"display", r"@media"])
            spec.add_file(f"{base}/app.js", artifact_type="file",
                         min_size_bytes=500, min_line_count=20,
                         required_patterns=[r"addEventListener", r"DOMContentLoaded"])
            spec.done_criteria.extend([
                "index.html tam iskelete sahip (nav, sections, footer)",
                "Stylesheet ve script bağlantıları yapılmış",
                "CSS responsive kurallar içeriyor",
                "JS event listener içeriyor",
            ])
            return spec

        if action in ("execute_python_code", "run_python"):
            spec.minimum_content_summary = "Python kodu çalıştırıldı ve çıktı üretildi"
            spec.done_criteria.append("Python kodu hatasız çalıştı ve çıktı üretildi.")
            return spec

        if action == "advanced_research":
            topic = params.get("topic") or user_input or "konu"
            safe_topic = re.sub(r'[^\w\s-]', '', topic).strip()[:40].replace(" ", "_")
            date_str = datetime.now().strftime("%Y%m%d")
            path = f"{self.DESKTOP}/{safe_topic}_{date_str}.md"
            spec.minimum_content_summary = "Araştırma raporu — başlık + bulgular + kaynaklar"
            spec.add_file(path, min_size_bytes=1000, min_word_count=200,
                         required_patterns=[r"##|#\s"])
            spec.done_criteria.extend([
                "Araştırma raporu oluşturuldu",
                "En az 200 kelime içeriyor",
                "Başlık bölümleri var",
            ])
            return spec

        if action in ("research_document_delivery",):
            spec.minimum_content_summary = "Araştırma + belge paketi"
            spec.done_criteria.append("Araştırma tamamlandı ve belgeler üretildi.")
            return spec

        return None


# ── Engine ────────────────────────────────────────────────────────────────────

class OutputContractEngine:
    """
    Merkezi kontrol noktası.

    Kullanım:
        engine = OutputContractEngine()
        spec = engine.factory.from_action(action, params, user_input)
        # ... execute ...
        result = engine.verify(spec)
        if not result["passed"]:
            repairs = engine.repairer.suggest_repair_actions(spec, result)
    """

    def __init__(self):
        self.factory = ContractFactory()
        self.verifier = ContractVerifier()
        self.repairer = ContractRepairer()
        self._results: list[dict] = []

    def create_spec(self, action: str, params: dict, user_input: str = "") -> Optional[DeliverableSpec]:
        return self.factory.from_action(action, params, user_input)

    def verify(self, spec: DeliverableSpec) -> dict[str, Any]:
        result = self.verifier.verify_spec(spec)
        self._results.append({"spec": spec.intent, "result": result, "ts": time.time()})
        return result

    def needs_repair(self, verification: dict[str, Any]) -> bool:
        return not verification.get("passed", True)

    def repair_actions(self, spec: DeliverableSpec, verification: dict[str, Any]) -> list[dict]:
        return self.repairer.suggest_repair_actions(spec, verification)

    def repair_prompt(self, spec: DeliverableSpec, verification: dict[str, Any], user_input: str) -> str:
        return self.repairer.build_repair_prompt(spec, verification, user_input)

    def last_results(self, n: int = 10) -> list[dict]:
        return self._results[-n:]


# ── Singleton ─────────────────────────────────────────────────────────────────
_engine_instance: Optional[OutputContractEngine] = None


def get_contract_engine() -> OutputContractEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = OutputContractEngine()
    return _engine_instance
