"""
core/memory/personality_adapter.py — Faz 7 Kişilik Adaptörü
───────────────────────────────────────────────────────────────────────────────
Kullanıcı tercihlerini öğrenir ve saklar:
  - Yanıt uzunluğu (kısa / orta / uzun)
  - Formalite seviyesi (resmi / casual)
  - Tercih edilen kanal
  - Do-Not-Disturb saatleri

EMA (Exponential Moving Average) ile ağırlıklı güncelleme yapar.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.storage_paths import resolve_elyan_data_dir
from utils.logger import get_logger

logger = get_logger("personality_adapter")

_DB_PATH: Path | None = None
_EMA_ALPHA = 0.25      # weight for new observations (0=ignore new, 1=only new)


def _db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = resolve_elyan_data_dir() / "memory" / "personality.db"
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _DB_PATH


# ── Profile dataclass ─────────────────────────────────────────────────────────

@dataclass
class UserProfile:
    user_id: str
    response_length: str = "medium"        # "short" | "medium" | "long"
    formality: str = "casual"              # "formal" | "casual"
    preferred_channel: str = "desktop"
    work_hours_start: int = 9              # 0-23
    work_hours_end: int = 22              # 0-23
    dnd_enabled: bool = False
    observation_count: int = 0
    extra: dict = field(default_factory=dict)

    def is_work_hours(self) -> bool:
        hour = time.localtime().tm_hour
        return self.work_hours_start <= hour < self.work_hours_end

    def response_style_hint(self) -> str:
        """One-line hint for LLM prompt injection."""
        parts = []
        if self.response_length == "short":
            parts.append("Yanıtları kısa tut (1-2 cümle).")
        elif self.response_length == "long":
            parts.append("Yanıtları detaylı ver.")
        if self.formality == "formal":
            parts.append("Resmi bir dil kullan.")
        else:
            parts.append("Samimi ve doğal bir dil kullan.")
        if not self.is_work_hours():
            parts.append("Mesai dışı — özet yanıtları tercih et.")
        return " ".join(parts)


# ── PersonalityAdapter ────────────────────────────────────────────────────────

class PersonalityAdapter:
    """Learns and persists per-user personality profiles."""

    def __init__(self, db: Path | None = None) -> None:
        path = db or _db_path()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._cache: dict[str, UserProfile] = {}

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                user_id           TEXT PRIMARY KEY,
                response_length   TEXT NOT NULL DEFAULT 'medium',
                formality         TEXT NOT NULL DEFAULT 'casual',
                preferred_channel TEXT NOT NULL DEFAULT 'desktop',
                work_hours_start  INTEGER NOT NULL DEFAULT 9,
                work_hours_end    INTEGER NOT NULL DEFAULT 22,
                dnd_enabled       INTEGER NOT NULL DEFAULT 0,
                observation_count INTEGER NOT NULL DEFAULT 0,
                extra             TEXT    NOT NULL DEFAULT '{}'
            );
        """)
        self._conn.commit()

    # ── Get / create ──────────────────────────────────────────────────────────

    def get_profile(self, user_id: str) -> UserProfile:
        if user_id in self._cache:
            return self._cache[user_id]

        row = self._conn.execute(
            "SELECT * FROM profiles WHERE user_id=?", (user_id,)
        ).fetchone()

        if row:
            p = UserProfile(
                user_id=user_id,
                response_length=row["response_length"],
                formality=row["formality"],
                preferred_channel=row["preferred_channel"],
                work_hours_start=row["work_hours_start"],
                work_hours_end=row["work_hours_end"],
                dnd_enabled=bool(row["dnd_enabled"]),
                observation_count=row["observation_count"],
                extra=json.loads(row["extra"] or "{}"),
            )
        else:
            p = UserProfile(user_id=user_id)
            self._save(p)

        self._cache[user_id] = p
        return p

    # ── Observe ───────────────────────────────────────────────────────────────

    def observe_response_length(self, user_id: str, char_count: int) -> None:
        """Update preferred length based on how many chars the response had."""
        p = self.get_profile(user_id)
        # Map char count to bucket
        if char_count < 150:
            bucket = "short"
        elif char_count < 600:
            bucket = "medium"
        else:
            bucket = "long"

        # Majority-vote with EMA: if bucket matches current, reinforce; else decay
        if bucket == p.response_length:
            pass  # already aligned
        else:
            # Soft switch: after enough observations in the new bucket, switch
            key = f"len_vote_{bucket}"
            p.extra[key] = p.extra.get(key, 0) + 1
            if p.extra[key] >= 3:              # 3 consecutive signals → switch
                p.response_length = bucket
                for bk in ("short", "medium", "long"):
                    p.extra.pop(f"len_vote_{bk}", None)

        p.observation_count += 1
        self._save(p)

    def observe_channel(self, user_id: str, channel: str) -> None:
        """Track which channel user uses most."""
        p = self.get_profile(user_id)
        key = f"ch_{channel}"
        p.extra[key] = p.extra.get(key, 0) + 1
        # Pick the channel with highest count
        best = max(
            (c for c in ("telegram", "whatsapp", "imessage", "desktop", "voice")),
            key=lambda c: p.extra.get(f"ch_{c}", 0),
        )
        p.preferred_channel = best
        self._save(p)

    def observe_message_time(self, user_id: str) -> None:
        """Track active hours to refine work_hours_start/end."""
        hour = time.localtime().tm_hour
        p = self.get_profile(user_id)
        key = f"hour_{hour}"
        p.extra[key] = p.extra.get(key, 0) + 1
        # Recalculate work hours as range containing 80% of activity
        counts = [(h, p.extra.get(f"hour_{h}", 0)) for h in range(24)]
        total = sum(c for _, c in counts)
        if total >= 10:                        # enough observations
            active = sorted([h for h, c in counts if c * 24 >= total], default=None)
            if active:
                p.work_hours_start = min(active)
                p.work_hours_end = max(active) + 1
        self._save(p)

    def set_dnd(self, user_id: str, enabled: bool) -> None:
        p = self.get_profile(user_id)
        p.dnd_enabled = enabled
        self._save(p)

    # ── Persist ───────────────────────────────────────────────────────────────

    def _save(self, p: UserProfile) -> None:
        try:
            self._conn.execute("""
                INSERT INTO profiles(user_id,response_length,formality,preferred_channel,
                    work_hours_start,work_hours_end,dnd_enabled,observation_count,extra)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                    response_length   = excluded.response_length,
                    formality         = excluded.formality,
                    preferred_channel = excluded.preferred_channel,
                    work_hours_start  = excluded.work_hours_start,
                    work_hours_end    = excluded.work_hours_end,
                    dnd_enabled       = excluded.dnd_enabled,
                    observation_count = excluded.observation_count,
                    extra             = excluded.extra
            """, (
                p.user_id, p.response_length, p.formality, p.preferred_channel,
                p.work_hours_start, p.work_hours_end, int(p.dnd_enabled),
                p.observation_count, json.dumps(p.extra),
            ))
            self._conn.commit()
            self._cache[p.user_id] = p
        except Exception as exc:
            logger.warning(f"PersonalityAdapter._save failed: {exc}")


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: PersonalityAdapter | None = None


def get_personality_adapter() -> PersonalityAdapter:
    global _instance
    if _instance is None:
        _instance = PersonalityAdapter()
    return _instance
