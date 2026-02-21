"""
core/feedback.py
─────────────────────────────────────────────────────────────────────────────
Kullanıcı düzeltmelerini yakala, öğren, bir daha aynı hatayı yapma.

Akış:
  1. Kullanıcı "hayır yanlış anladın / öyle değil / bunu kastetmedim" der.
  2. FeedbackDetector bunu yakalar → correction_context üretir.
  3. Agent, önceki yanlış action + doğru intent'i FeedbackStore'a yazar.
  4. Bir sonraki benzer girişte FeedbackStore uyarı olarak context'e eklenir.
  5. Kullanıcı "mükemmel / teşekkürler / harika" derse → positive_feedback kaydedilir.
"""
from __future__ import annotations

import json
import re
import threading
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("feedback")

# ── Sabitler ─────────────────────────────────────────────────────────────────
_STORE_PATH = Path.home() / ".elyan" / "feedback.json"
_MAX_CORRECTIONS = 200
_MAX_POSITIVES   = 200

# ── Düzeltme sinyal sözlüğü (TR + EN) ───────────────────────────────────────
_CORRECTION_SIGNALS = [
    r"\bhayır\b", r"\byanlış\b", r"\byanlis\b",
    r"\böyle değil\b", r"\boyle degil\b",
    r"\bbunu kastetmedim\b", r"\bbunu demek istemedim\b",
    r"\byanlış anladın\b", r"\byanlis anladn\b",
    r"\bgalat\b", r"\bbu değildi\b", r"\bbu degil\b",
    r"\bno\b", r"\bwrong\b", r"\bthat'?s not\b", r"\bmisunderstood\b",
    r"\byeniden\b.*\byap\b", r"\btekrar\b.*\bama\b",
    r"\bonu değil\b", r"\bonu degil\b",
]
_CORRECTION_PATTERN = re.compile("|".join(_CORRECTION_SIGNALS), re.IGNORECASE)

_POSITIVE_SIGNALS = [
    r"\bteşekkür\b", r"\btesekkur\b", r"\bsağ ol\b", r"\bsag ol\b",
    r"\bharika\b", r"\bmükemmel\b", r"\bmukemmel\b", r"\bperfect\b",
    r"\bexactly\b", r"\btam istediğim\b", r"\btam bu\b",
    r"\bgüzel\b", r"\bbravo\b", r"\bsüper\b", r"\bthank\b",
    r"\beyy\b", r"\bvay\b", r"\bwow\b",
]
_POSITIVE_PATTERN = re.compile("|".join(_POSITIVE_SIGNALS), re.IGNORECASE)


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class Correction:
    user_id: int
    original_input: str
    wrong_action: str
    correction_text: str
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

@dataclass
class PositiveFeedback:
    user_id: int
    original_input: str
    action: str
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── FeedbackStore ─────────────────────────────────────────────────────────────

class FeedbackStore:

    def __init__(self):
        self._lock = threading.Lock()
        self._corrections: List[Correction] = []
        self._positives: List[PositiveFeedback] = []
        # user_id → {wrong_action → count}
        self._action_errors: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._load()

    # ── Write ──────────────────────────────────────────────────────────────────

    def record_correction(self, user_id: int, original_input: str, wrong_action: str, correction_text: str):
        c = Correction(user_id=user_id, original_input=original_input,
                       wrong_action=wrong_action, correction_text=correction_text)
        with self._lock:
            self._corrections.append(c)
            if len(self._corrections) > _MAX_CORRECTIONS:
                self._corrections = self._corrections[-_MAX_CORRECTIONS:]
            self._action_errors[user_id][wrong_action] += 1
        logger.info(f"[feedback] Correction recorded: user={user_id} wrong_action={wrong_action!r}")
        self._save()

    def record_positive(self, user_id: int, original_input: str, action: str):
        p = PositiveFeedback(user_id=user_id, original_input=original_input, action=action)
        with self._lock:
            self._positives.append(p)
            if len(self._positives) > _MAX_POSITIVES:
                self._positives = self._positives[-_MAX_POSITIVES:]
        self._save()

    # ── Read ───────────────────────────────────────────────────────────────────

    def get_user_corrections(self, user_id: int, limit: int = 10) -> List[Correction]:
        with self._lock:
            return [c for c in reversed(self._corrections) if c.user_id == user_id][:limit]

    def get_error_count(self, user_id: int, action: str) -> int:
        with self._lock:
            return self._action_errors[user_id].get(action, 0)

    def build_correction_hint(self, user_id: int, candidate_action: str) -> str:
        """
        Eğer bu kullanıcı bu action için daha önce düzeltme yaptıysa,
        agent'a eklenecek hint metni üret.
        """
        corrections = self.get_user_corrections(user_id, limit=5)
        related = [c for c in corrections if c.wrong_action == candidate_action]
        if not related:
            return ""
        examples = "; ".join(f'"{c.original_input}" → yanlış: {c.wrong_action}' for c in related[:3])
        return (
            f"[ÖĞRENME NOTU] Bu kullanıcı daha önce bu tür isteği yanlış anlaman nedeniyle "
            f"seni düzeltti. Örnek: {examples}. Bu sefer dikkatli analiz et."
        )

    def get_stats(self, user_id: int) -> dict:
        with self._lock:
            corrections = [c for c in self._corrections if c.user_id == user_id]
            positives = [p for p in self._positives if p.user_id == user_id]
        error_rate = len(corrections) / max(1, len(corrections) + len(positives))
        return {
            "corrections": len(corrections),
            "positives": len(positives),
            "error_rate_pct": round(error_rate * 100, 1),
            "top_wrong_actions": sorted(
                self._action_errors[user_id].items(), key=lambda x: x[1], reverse=True
            )[:5],
        }

    # ── Persist ────────────────────────────────────────────────────────────────

    def _load(self):
        try:
            if _STORE_PATH.exists():
                data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
                self._corrections = [Correction(**c) for c in data.get("corrections", [])]
                self._positives = [PositiveFeedback(**p) for p in data.get("positives", [])]
                for c in self._corrections:
                    self._action_errors[c.user_id][c.wrong_action] += 1
        except Exception as exc:
            logger.debug(f"[feedback] Load failed: {exc}")

    def _save(self):
        try:
            _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "corrections": [asdict(c) for c in self._corrections],
                "positives": [asdict(p) for p in self._positives],
            }
            _STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug(f"[feedback] Save failed: {exc}")


# ── FeedbackDetector ──────────────────────────────────────────────────────────

class FeedbackDetector:
    """Giriş metninin düzeltme / olumlu geri bildirim olup olmadığını tespit eder."""

    @staticmethod
    def is_correction(text: str) -> bool:
        return bool(_CORRECTION_PATTERN.search(text))

    @staticmethod
    def is_positive(text: str) -> bool:
        return bool(_POSITIVE_PATTERN.search(text))

    @staticmethod
    def extract_correction_intent(text: str) -> Tuple[bool, str]:
        """
        (is_correction, cleaned_intent)
        Düzeltme sinyallerini temizleyip gerçek isteği döner.
        Örn: "hayır bunu kastetmedim, ekran görüntüsü al" → (True, "ekran görüntüsü al")
        """
        if not FeedbackDetector.is_correction(text):
            return False, text
        cleaned = _CORRECTION_PATTERN.sub("", text)
        # Bağlaçları temizle
        cleaned = re.sub(r"^\s*[,;.!]+\s*", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,;!")
        return True, cleaned if len(cleaned) > 2 else text


# ── Singleton ─────────────────────────────────────────────────────────────────
_store: FeedbackStore | None = None
_store_lock = threading.Lock()


def get_feedback_store() -> FeedbackStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = FeedbackStore()
    return _store


def get_feedback_detector() -> FeedbackDetector:
    return FeedbackDetector()
