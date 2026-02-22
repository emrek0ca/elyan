"""
Elyan Evidence Gate — Proof-Only Delivery

Tool çıktısı (dosya yolu, hash, screenshot) olmadan
teslim/delivery iddialarını response'dan siler.
"""

import re
from typing import Optional
from utils.logger import get_logger

logger = get_logger("evidence_gate")

# ── Delivery claim patterns (TR + EN) ────────────────────────

_DELIVERY_PATTERNS = [
    # Turkish
    r"✅\s*(?:teslim|oluşturuldu|hazır|tamamlandı|gönderildi|kaydedildi)",
    r"(?:dosya|site|proje|rapor)\s+(?:oluşturuldu|hazırlandı|teslim edildi|kaydedildi)",
    r"(?:başarıyla|successfully)\s+(?:oluşturuldu|created|yazıldı|written|teslim)",
    r"zip\s+(?:dosyası|arşivi)\s+(?:hazır|oluşturuldu)",
    r"(?:masaüstüne|desktop'a)\s+(?:kaydettim|kaydedildi|oluşturdum)",
    # English
    r"(?:delivered|created|saved|generated)\s+(?:successfully|the file|the project)",
    r"(?:file|project|report|website)\s+(?:has been|was)\s+(?:created|saved|delivered)",
    r"(?:you can find|check|open)\s+(?:it|the file|the project)\s+(?:at|in|on)",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _DELIVERY_PATTERNS]

# ── Path-like evidence patterns ───────────────────────────────

_EVIDENCE_PATTERNS = [
    re.compile(r"(?:/Users/|/home/|/tmp/|~/|C:\\)[^\s\"']+", re.IGNORECASE),
    re.compile(r"[a-zA-Z0-9_\-]+\.(html|css|js|py|txt|md|docx|xlsx|pdf|zip|png|jpg)", re.IGNORECASE),
]


class EvidenceGate:
    """
    Response'dan kanıtsız delivery claim'leri siler.
    
    Kullanım:
        gate = EvidenceGate()
        clean = gate.enforce(response_text, tool_results)
    """

    def __init__(self):
        self.stats = {"blocked": 0, "passed": 0}

    def has_real_evidence(self, tool_results: list) -> bool:
        """Tool sonuçlarında gerçek dosya/path kanıtı var mı?"""
        if not tool_results:
            return False

        for result in tool_results:
            if not isinstance(result, dict):
                continue
            # Başarılı tool execution
            if result.get("success") is True:
                return True
            # Path/file evidence
            if result.get("path") or result.get("file_path") or result.get("output_path"):
                return True
            # Screenshot evidence
            if result.get("screenshot") or result.get("image_path"):
                return True
            # Content evidence
            if result.get("content") and len(str(result.get("content", ""))) > 50:
                return True

        return False

    def response_has_evidence_refs(self, text: str) -> bool:
        """Response metninde gerçek dosya referansı var mı?"""
        for pat in _EVIDENCE_PATTERNS:
            if pat.search(text):
                return True
        return False

    def has_delivery_claims(self, text: str) -> bool:
        """Response'da delivery iddiası var mı?"""
        for pat in _COMPILED:
            if pat.search(text):
                return True
        return False

    def enforce(self, response_text: str, tool_results: Optional[list] = None) -> str:
        """
        Ana enforcement metodu.
        
        Kural: Delivery claim varsa AMA evidence yoksa → claim'i temizle.
        Evidence varsa veya claim yoksa → hiçbir şey yapma.
        """
        if not response_text:
            return response_text

        if not self.has_delivery_claims(response_text):
            # Delivery claim yok, dokunma
            return response_text

        real_evidence = self.has_real_evidence(tool_results or [])
        text_evidence = self.response_has_evidence_refs(response_text)

        if real_evidence or text_evidence:
            # Evidence var, claim geçerli
            self.stats["passed"] += 1
            return response_text

        # ── BLOKLA: Claim var ama evidence yok ──
        self.stats["blocked"] += 1
        logger.warning(f"Evidence Gate: delivery claim blocked (no proof)")

        cleaned = self._strip_false_claims(response_text)
        # Uyarı notu ekle
        cleaned += "\n\n⚠️ _İşlem henüz tamamlanmadı. Sonucu doğrulamam gerekiyor._"
        return cleaned

    def _strip_false_claims(self, text: str) -> str:
        """Sahte delivery iddialarını siler."""
        lines = text.split("\n")
        cleaned = []
        for line in lines:
            stripped = line
            for pat in _COMPILED:
                if pat.search(line):
                    # Bu satırı değiştir
                    stripped = pat.sub("⏳ İşlem devam ediyor", line)
                    break
            cleaned.append(stripped)
        return "\n".join(cleaned)


# Global instance
evidence_gate = EvidenceGate()
