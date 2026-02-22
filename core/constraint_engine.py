"""
Elyan Constraint Engine — Sert Kural Enforcement

LLM'den bağımsız, kod seviyesinde zorunlu kurallar.
Evidence Gate'in üstünde çalışır; daha geniş kapsamlı.
"""

import os
import re
from typing import Any, Dict, List, Optional, Tuple
from utils.logger import get_logger

logger = get_logger("constraint_engine")


class ConstraintViolation:
    """Tek bir kural ihlali."""
    def __init__(self, rule: str, message: str, severity: str = "error"):
        self.rule = rule
        self.message = message
        self.severity = severity  # error, warning, info

    def __repr__(self):
        return f"[{self.severity.upper()}] {self.rule}: {self.message}"


class ConstraintEngine:
    """
    Sert kural enforcement motoru.
    
    Kurallar:
    1. Dosya yazdıysan tool kanıtı göster
    2. Claim varsa kaynak göster
    3. Kod varsa test çalıştır (uyarı)
    4. Contract check geçmediyse teslim etme
    5. Style profile'a uy ("never" listesi)
    """

    def __init__(self):
        self._custom_rules: List[Dict[str, Any]] = []

    def check_response(
        self,
        response: str,
        tool_results: List[Dict] = None,
        job_type: str = "communication",
        contract_passed: bool = True,
    ) -> List[ConstraintViolation]:
        """Tüm constraint'leri kontrol et."""
        violations = []
        tool_results = tool_results or []

        # 1. File claim without evidence
        violations.extend(self._check_file_claim(response, tool_results))

        # 2. Source claims without references
        violations.extend(self._check_source_claims(response))

        # 3. Code without test (warning)
        if job_type in ("code_project", "web_project"):
            violations.extend(self._check_code_test(response, tool_results))

        # 4. Contract not passed
        if not contract_passed and job_type not in ("communication",):
            violations.append(ConstraintViolation(
                "CONTRACT_FAILED",
                "Contract check geçmedi, teslim edilemez",
                "error"
            ))

        # 5. Style profile "never" rules
        violations.extend(self._check_style_nevers(response))

        return violations

    def _check_file_claim(self, response: str, tool_results: List[Dict]) -> List[ConstraintViolation]:
        """Dosya yazdım iddiası var ama tool result'ta dosya yok."""
        violations = []
        file_claim_patterns = [
            r"dosya\s+(?:oluşturuldu|yazıldı|kaydedildi)",
            r"(?:created|saved|written)\s+(?:the\s+)?file",
            r"✅\s*(?:teslim|oluşturuldu|hazır)",
        ]

        has_claim = any(
            re.search(p, response, re.IGNORECASE) for p in file_claim_patterns
        )

        if has_claim:
            has_file_evidence = any(
                isinstance(r, dict) and (r.get("path") or r.get("file_path") or r.get("success"))
                for r in tool_results
            )
            if not has_file_evidence:
                violations.append(ConstraintViolation(
                    "FILE_CLAIM_NO_EVIDENCE",
                    "Dosya oluşturma iddiası var ama tool kanıtı yok",
                    "error"
                ))
        return violations

    def _check_source_claims(self, response: str) -> List[ConstraintViolation]:
        """Bilgi iddiası var ama kaynak yok."""
        violations = []
        claim_patterns = [
            r"(?:araştırmalara|istatistiklere|verilere)\s+göre",
            r"(?:studies|research|data)\s+(?:show|suggest|indicate)",
            r"%\d+",  # Yüzde içeren iddia
        ]
        source_patterns = [
            r"https?://",
            r"\[kaynak\]",
            r"\(source\)",
            r"referans",
        ]

        has_claim = any(re.search(p, response, re.IGNORECASE) for p in claim_patterns)
        has_source = any(re.search(p, response, re.IGNORECASE) for p in source_patterns)

        if has_claim and not has_source:
            violations.append(ConstraintViolation(
                "CLAIM_NO_SOURCE",
                "Bilgi/istatistik iddiası var ama kaynak referansı yok",
                "warning"
            ))
        return violations

    def _check_code_test(self, response: str, tool_results: List[Dict]) -> List[ConstraintViolation]:
        """Kod üretildi ama test çalıştırılmadı."""
        violations = []
        code_written = any(
            isinstance(r, dict) and r.get("success") and
            any(ext in str(r.get("path", "")) for ext in (".py", ".js", ".ts", ".jsx", ".tsx"))
            for r in tool_results
        )
        test_ran = any(
            isinstance(r, dict) and
            str(r.get("action", "")).lower() in ("execute_python", "execute_code", "terminal_command")
            for r in tool_results
        )

        if code_written and not test_ran:
            violations.append(ConstraintViolation(
                "CODE_NO_TEST",
                "Kod yazıldı ama test/lint çalıştırılmadı",
                "warning"
            ))
        return violations

    def _check_style_nevers(self, response: str) -> List[ConstraintViolation]:
        """Style profile "never" kurallarını kontrol et."""
        violations = []
        try:
            from core.style_profile import style_profile
            nevers = style_profile.get("never", [])
            low_response = response.lower()
            for never in nevers:
                # "jQuery kullanma" → "jquery" ara
                check_word = never.lower().replace("kullanma", "").replace("koyma", "").strip()
                if check_word and check_word in low_response:
                    violations.append(ConstraintViolation(
                        "STYLE_NEVER",
                        f"Style profile ihlali: '{never}'",
                        "warning"
                    ))
        except Exception:
            pass
        return violations

    def enforce(self, response: str, tool_results: List[Dict] = None,
                job_type: str = "communication", contract_passed: bool = True) -> Tuple[str, List[ConstraintViolation]]:
        """
        Constraint'leri kontrol et ve response'u düzelt.
        
        Returns: (cleaned_response, violations)
        """
        violations = self.check_response(response, tool_results, job_type, contract_passed)

        errors = [v for v in violations if v.severity == "error"]
        warnings = [v for v in violations if v.severity == "warning"]

        if errors:
            # Evidence gate zaten temizliyor; biz sadece uyarı ekliyoruz
            warning_text = "\n".join(f"⚠️ {v.message}" for v in errors)
            response = response + f"\n\n{warning_text}"
            logger.warning(f"Constraint violations: {len(errors)} errors, {len(warnings)} warnings")

        return response, violations


# Global instance
constraint_engine = ConstraintEngine()
