"""
core/memory/jarvis_memory.py — Faz 7 Episodik Hafıza & Tarif Öğrenme
───────────────────────────────────────────────────────────────────────────────
Her etkileşimi kaydeder. Aynı trigger 3+ kez görülünce "tarif" oluşturur.
JarvisCore, yanıt vermeden önce ilgili geçmişi buradan çeker.
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

logger = get_logger("jarvis_memory")

_DB_PATH: Path | None = None


def _db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = resolve_elyan_data_dir() / "memory" / "jarvis_memory.db"
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _DB_PATH


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class Interaction:
    user_id: str
    channel: str
    input_text: str
    output_text: str
    outcome: str = "ok"          # "ok" | "rejected" | "partial"
    latency_ms: float = 0.0
    ts: float = field(default_factory=time.time)


@dataclass
class Recipe:
    trigger_pattern: str         # normalized trigger keyword
    action_summary: str
    success_count: int = 0
    total_count: int = 0
    last_used: float = field(default_factory=time.time)


# ── JarvisMemory ─────────────────────────────────────────────────────────────

class JarvisMemory:
    """Episodic memory + recipe learning for Jarvis."""

    RECIPE_THRESHOLD = 3   # how many times a pattern must repeat to become a recipe

    def __init__(self, db: Path | None = None) -> None:
        path = db or _db_path()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    # ── Schema ───────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS interactions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT    NOT NULL,
                channel     TEXT    NOT NULL,
                input_text  TEXT    NOT NULL,
                output_text TEXT    NOT NULL,
                outcome     TEXT    NOT NULL DEFAULT 'ok',
                latency_ms  REAL    NOT NULL DEFAULT 0,
                ts          REAL    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_int_user ON interactions(user_id, ts);

            CREATE TABLE IF NOT EXISTS recipes (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       TEXT NOT NULL,
                trigger_pat   TEXT NOT NULL,
                action_sum    TEXT NOT NULL,
                success_count INTEGER NOT NULL DEFAULT 0,
                total_count   INTEGER NOT NULL DEFAULT 0,
                last_used     REAL    NOT NULL,
                UNIQUE(user_id, trigger_pat)
            );
        """)
        self._conn.commit()

    # ── Write ─────────────────────────────────────────────────────────────────

    def record(self, ix: Interaction) -> None:
        """Persist an interaction and update recipe counters."""
        try:
            self._conn.execute(
                "INSERT INTO interactions(user_id,channel,input_text,output_text,outcome,latency_ms,ts)"
                " VALUES(?,?,?,?,?,?,?)",
                (ix.user_id, ix.channel, ix.input_text[:2000], ix.output_text[:2000],
                 ix.outcome, ix.latency_ms, ix.ts),
            )
            self._conn.commit()
            self._maybe_learn_recipe(ix)
        except Exception as exc:
            logger.warning(f"JarvisMemory.record failed: {exc}")

    def _maybe_learn_recipe(self, ix: Interaction) -> None:
        """Extract trigger keywords and upsert recipe counters."""
        keywords = _extract_keywords(ix.input_text)
        success = ix.outcome == "ok"
        for kw in keywords[:3]:              # at most 3 triggers per interaction
            try:
                self._conn.execute("""
                    INSERT INTO recipes(user_id, trigger_pat, action_sum, success_count, total_count, last_used)
                    VALUES(?,?,?,?,1,?)
                    ON CONFLICT(user_id, trigger_pat) DO UPDATE SET
                        success_count = success_count + ?,
                        total_count   = total_count + 1,
                        action_sum    = excluded.action_sum,
                        last_used     = excluded.last_used
                """, (
                    ix.user_id, kw, ix.output_text[:200], int(success), ix.ts,
                    int(success),
                ))
            except Exception:
                pass
        self._conn.commit()

    # ── Read ──────────────────────────────────────────────────────────────────

    def recent(self, user_id: str, limit: int = 5) -> list[dict]:
        """Return last N interactions for a user."""
        rows = self._conn.execute(
            "SELECT channel,input_text,output_text,outcome,ts FROM interactions"
            " WHERE user_id=? ORDER BY ts DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def relevant_recipes(self, user_id: str, input_text: str, limit: int = 3) -> list[dict]:
        """Return recipes whose trigger matches keywords in input_text."""
        keywords = _extract_keywords(input_text)
        results: list[dict] = []
        seen: set[str] = set()
        for kw in keywords:
            if len(results) >= limit:
                break
            rows = self._conn.execute(
                "SELECT trigger_pat,action_sum,success_count,total_count FROM recipes"
                " WHERE user_id=? AND trigger_pat=? AND total_count>=?",
                (user_id, kw, self.RECIPE_THRESHOLD),
            ).fetchall()
            for r in rows:
                if r["trigger_pat"] not in seen:
                    seen.add(r["trigger_pat"])
                    results.append(dict(r))
        return results

    def build_context_hint(self, user_id: str, input_text: str) -> str:
        """Build a short context hint string for JarvisCore prompt injection."""
        recipes = self.relevant_recipes(user_id, input_text)
        recent  = self.recent(user_id, limit=3)
        parts: list[str] = []
        if recipes:
            parts.append("Bilinen tarifler: " + "; ".join(
                f"'{r['trigger_pat']}' → {r['action_sum'][:80]}" for r in recipes
            ))
        if recent:
            parts.append("Son etkileşim: " + recent[0]["input_text"][:120])
        return "\n".join(parts)


# ── Helpers ───────────────────────────────────────────────────────────────────

_STOP = {"ve", "bir", "bu", "şu", "da", "de", "için", "ile", "to", "the", "a", "an", "is", "in"}

def _extract_keywords(text: str) -> list[str]:
    """Simple whitespace tokenizer → lowercase unique non-stop words (≥4 chars)."""
    words = [w.strip(".,!?;:'\"()[]{}").lower() for w in text.split()]
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        if len(w) >= 4 and w not in _STOP and w not in seen:
            seen.add(w)
            out.append(w)
    return out[:10]


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: JarvisMemory | None = None


def get_jarvis_memory() -> JarvisMemory:
    global _instance
    if _instance is None:
        _instance = JarvisMemory()
    return _instance
