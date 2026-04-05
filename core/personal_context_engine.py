"""
core/personal_context_engine.py
──────────────────────────────────────────────────────────────────────────────
Personal Context Engine — Layer 2 of Elyan's intelligence stack.

Captures the user's REAL current OS context (active app, frontmost document,
recent clipboard, active browser URL) via macOS APIs — without screenshots.
Updates on a background timer and exposes a lightweight snapshot that the
agent injects into every task prompt.

This is the "Ben söylemeden bağlamı anlaması" layer.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Deque, Dict, Optional

from core.observability.logger import get_structured_logger
from core.storage_paths import resolve_elyan_data_dir

slog = get_structured_logger("personal_context_engine")

_POLL_INTERVAL_SECONDS = 30
_SNAPSHOT_RING_SIZE = 20  # per user
_PERSIST_PATH = resolve_elyan_data_dir() / "personal_context.json"


@dataclass
class OSContextSnapshot:
    """Single point-in-time OS context snapshot."""
    captured_at: float = field(default_factory=time.time)
    active_app: str = ""
    active_window_title: str = ""
    active_document: str = ""          # file path if inferable
    active_url: str = ""               # browser URL if browser is frontmost
    recent_apps: list[str] = field(default_factory=list)
    clipboard_type: str = ""           # "text", "image", "file", "" — not content
    idle_seconds: float = 0.0
    frontmost_process: str = ""

    def age_seconds(self) -> float:
        return time.time() - self.captured_at

    def is_fresh(self, max_age: float = 120.0) -> bool:
        return self.age_seconds() < max_age

    def to_prompt_fragment(self) -> str:
        """Returns a compact context string suitable for LLM injection."""
        parts: list[str] = []
        if self.active_app:
            parts.append(f"Şu an açık uygulama: {self.active_app}")
        if self.active_window_title:
            parts.append(f"Pencere başlığı: {self.active_window_title}")
        if self.active_document:
            parts.append(f"Aktif dosya: {self.active_document}")
        if self.active_url:
            parts.append(f"Aktif URL: {self.active_url}")
        if self.recent_apps:
            parts.append(f"Son kullanılan uygulamalar: {', '.join(self.recent_apps[:4])}")
        return " | ".join(parts) if parts else ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def empty(cls) -> "OSContextSnapshot":
        return cls()


def _run_applescript(script: str, timeout: float = 3.0) -> str:
    """Execute an AppleScript snippet, return stdout or empty string on error."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout
        )
        return (result.stdout or "").strip()
    except Exception:
        return ""


def _capture_os_snapshot() -> OSContextSnapshot:
    """
    Capture the current macOS context using fast AppleScript queries.
    All queries are read-only and don't require special permissions beyond
    Accessibility (already granted for Elyan desktop).
    """
    snap = OSContextSnapshot()

    # 1. Frontmost application
    app_name = _run_applescript(
        'tell application "System Events" to return name of first application process whose frontmost is true'
    )
    snap.active_app = app_name
    snap.frontmost_process = app_name

    # 2. Active window title
    window_title = _run_applescript(
        'tell application "System Events" to return name of first window of '
        '(first application process whose frontmost is true)'
    )
    snap.active_window_title = window_title

    # 3. Browser URL (Safari / Chrome)
    if "Safari" in app_name:
        url = _run_applescript(
            'tell application "Safari" to return URL of current tab of front window'
        )
        snap.active_url = url
    elif "Chrome" in app_name or "Chromium" in app_name:
        url = _run_applescript(
            'tell application "Google Chrome" to return URL of active tab of front window'
        )
        snap.active_url = url

    # 4. Active document path (for text editors / IDEs)
    _editor_apps = {"TextEdit", "Xcode", "Visual Studio Code", "Cursor", "Sublime Text", "BBEdit"}
    if any(ed in app_name for ed in _editor_apps):
        doc_path = _run_applescript(
            f'tell application "{app_name}" to return path of front document'
        )
        snap.active_document = doc_path

    # 5. Recent applications (last 4 from Dock recent items)
    recent_raw = _run_applescript(
        'tell application "System Events" to return (name of every application process '
        'whose visible is true) as string'
    )
    if recent_raw:
        apps = [a.strip() for a in recent_raw.split(",") if a.strip()]
        snap.recent_apps = [a for a in apps if a != app_name][:5]

    # 6. Clipboard type (non-invasive — just type, not content)
    clipboard_info = _run_applescript(
        "return (class of (the clipboard)) as string"
    )
    if "text" in clipboard_info.lower():
        snap.clipboard_type = "text"
    elif "picture" in clipboard_info.lower() or "image" in clipboard_info.lower():
        snap.clipboard_type = "image"
    elif "file" in clipboard_info.lower():
        snap.clipboard_type = "file"

    snap.captured_at = time.time()
    return snap


class PersonalContextEngine:
    """
    Background engine that maintains per-user OS context rings.

    Polling is lazy — it starts only when the first snapshot is requested
    and runs in a background thread.
    """

    def __init__(self, ring_size: int = _SNAPSHOT_RING_SIZE) -> None:
        self._ring_size = ring_size
        self._lock = RLock()
        # user_id → deque of OSContextSnapshot
        self._rings: Dict[str, Deque[OSContextSnapshot]] = {}
        # Global (single-user desktop) current snapshot
        self._current: OSContextSnapshot = OSContextSnapshot.empty()
        self._polling = False
        self._last_poll: float = 0.0
        self._persist_path = _PERSIST_PATH
        self._load()

    # ─── Public API ────────────────────────────────────────────────────────

    def get_current_context(self, user_id: str = "local") -> OSContextSnapshot:
        """Return the most recent context snapshot for the user."""
        with self._lock:
            ring = self._rings.get(user_id)
            if ring:
                return ring[-1]
            return self._current

    def get_context_history(self, user_id: str = "local", n: int = 5) -> list[OSContextSnapshot]:
        """Return the last n context snapshots for the user."""
        with self._lock:
            ring = self._rings.get(user_id, deque())
            return list(ring)[-n:]

    def get_dominant_app(self, user_id: str = "local", window: int = 10) -> str:
        """Return the most frequently seen app over the last `window` snapshots."""
        with self._lock:
            ring = list(self._rings.get(user_id, deque()))[-window:]
        if not ring:
            return ""
        app_counts: Dict[str, int] = {}
        for snap in ring:
            if snap.active_app:
                app_counts[snap.active_app] = app_counts.get(snap.active_app, 0) + 1
        return max(app_counts, key=lambda k: app_counts[k]) if app_counts else ""

    def get_context_summary(self, user_id: str = "local") -> dict[str, Any]:
        """Returns a rich summary dict suitable for injection into agent context."""
        snap = self.get_current_context(user_id)
        dominant = self.get_dominant_app(user_id)
        history = self.get_context_history(user_id, n=5)
        recent_urls = [s.active_url for s in history if s.active_url][:3]
        recent_docs = [s.active_document for s in history if s.active_document][:3]

        return {
            "active_app": snap.active_app,
            "active_window": snap.active_window_title,
            "active_document": snap.active_document,
            "active_url": snap.active_url,
            "recent_apps": snap.recent_apps[:4],
            "dominant_app": dominant,
            "recent_urls": recent_urls,
            "recent_docs": recent_docs,
            "clipboard_type": snap.clipboard_type,
            "snapshot_age_seconds": int(snap.age_seconds()),
            "prompt_fragment": snap.to_prompt_fragment(),
        }

    def force_poll(self, user_id: str = "local") -> OSContextSnapshot:
        """Capture a fresh snapshot immediately and store it."""
        try:
            snap = _capture_os_snapshot()
        except Exception as exc:
            slog.log_event("context_poll_error", {"error": str(exc)})
            snap = OSContextSnapshot.empty()
        self._push(user_id, snap)
        return snap

    def start_background_polling(self, user_id: str = "local") -> None:
        """Start async background polling (idempotent)."""
        if self._polling:
            return
        self._polling = True
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(self._poll_loop(user_id))
        except RuntimeError:
            pass  # No event loop available — polling will be on-demand

    # ─── Internal ──────────────────────────────────────────────────────────

    def _push(self, user_id: str, snap: OSContextSnapshot) -> None:
        with self._lock:
            if user_id not in self._rings:
                self._rings[user_id] = deque(maxlen=self._ring_size)
            self._rings[user_id].append(snap)
            self._current = snap
            self._last_poll = time.time()
        self._persist()

    async def _poll_loop(self, user_id: str) -> None:
        while self._polling:
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            try:
                snap = _capture_os_snapshot()
                self._push(user_id, snap)
                slog.log_event("context_polled", {
                    "user_id": user_id,
                    "active_app": snap.active_app,
                    "age": int(snap.age_seconds()),
                })
            except Exception as exc:
                slog.log_event("context_poll_error", {"error": str(exc)})

    def _persist(self) -> None:
        """Persist context rings to disk for cross-session continuity."""
        try:
            data: dict[str, Any] = {}
            with self._lock:
                for uid, ring in self._rings.items():
                    data[uid] = [s.to_dict() for s in list(ring)[-5:]]
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._persist_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def _load(self) -> None:
        """Restore last known context from disk on startup."""
        try:
            if not self._persist_path.exists():
                return
            raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
            with self._lock:
                for uid, snaps in raw.items():
                    if not isinstance(snaps, list):
                        continue
                    ring: Deque[OSContextSnapshot] = deque(maxlen=self._ring_size)
                    for s in snaps:
                        if isinstance(s, dict):
                            ring.append(OSContextSnapshot(**{
                                k: v for k, v in s.items()
                                if k in OSContextSnapshot.__dataclass_fields__
                            }))
                    if ring:
                        self._rings[uid] = ring
                        self._current = ring[-1]
        except Exception:
            pass


# ─── Singleton ────────────────────────────────────────────────────────────────

_engine: Optional[PersonalContextEngine] = None


def get_personal_context_engine() -> PersonalContextEngine:
    global _engine
    if _engine is None:
        _engine = PersonalContextEngine()
    return _engine


__all__ = [
    "OSContextSnapshot",
    "PersonalContextEngine",
    "get_personal_context_engine",
]
