"""
core/tool_request.py
─────────────────────────────────────────────────────────────────────────────
ToolRequest / ToolResult — Standart Tool Çağrı Kaydı

Her tool çağrısı için:
  - Benzersiz request_id (nanoid-tarzı 8 karakter)
  - İstek parametreleri (secret sanitized)
  - Çıktı sonucu özeti
  - Süre (latency_ms)
  - Artifact paths (üretilen dosyalar/klasörler)
  - Contract verification durumu
  - Repair actions (doğrulama başarısızsa)

Kayıtlar:
  1. ~/.elyan/tool_requests.jsonl — JSONL persist (append-only)
  2. In-memory ring buffer (son 500 kayıt)
  3. /api/tool-requests endpoint üzerinden sorgulanabilir
"""
from __future__ import annotations

import json
import os
import random
import string
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("tool_request")

# ── Constants ─────────────────────────────────────────────────────────────────
_MAX_RING = 500          # in-memory ring buffer size
_MAX_JSONL = 10_000      # max lines in JSONL file before rotation
_ID_CHARS = string.ascii_lowercase + string.digits
_LOG_PATH = Path.home() / ".elyan" / "tool_requests.jsonl"

# ── Secret field filter ────────────────────────────────────────────────────────
_SECRET_KEYS = frozenset({
    "token", "key", "secret", "password", "passwd", "api_key",
    "access_token", "verify_token", "bridge_token", "bot_token",
})


def _sanitize_params(params: dict) -> dict:
    """Gizli alanları maskele."""
    if not isinstance(params, dict):
        return {}
    out = {}
    for k, v in params.items():
        if k.lower() in _SECRET_KEYS:
            out[k] = "***"
        elif isinstance(v, dict):
            out[k] = _sanitize_params(v)
        elif isinstance(v, str) and len(v) > 1000:
            out[k] = v[:200] + f"…({len(v)-200} chars more)"
        else:
            out[k] = v
    return out


def _extract_artifacts(result: Any) -> List[str]:
    """Sonuçtan dosya yollarını çıkar."""
    if not isinstance(result, dict):
        return []
    paths: List[str] = []
    for key in ("path", "file_path", "output_path", "filepath", "saved_to",
                "output", "outputs", "report_paths", "files_created"):
        val = result.get(key)
        if isinstance(val, str) and val:
            candidate = val.strip()
            if ("/" in candidate or "\\" in candidate) and not candidate.startswith("http"):
                paths.append(candidate)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str) and ("/" in item or "\\" in item):
                    paths.append(item)
    # dedupe
    seen: set = set()
    unique = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ToolRequest:
    request_id: str
    tool_name: str
    params: Dict[str, Any]
    source: str = "agent"          # agent | planner | test | api
    user_input_preview: str = ""   # first 120 chars of user_input
    step_name: str = ""
    started_at: str = ""
    session_id: str = ""


@dataclass
class ToolResult:
    request_id: str
    tool_name: str
    success: bool
    latency_ms: int
    artifacts: List[str] = field(default_factory=list)
    error: str = ""
    result_preview: str = ""       # first 300 chars of result text
    contract_verified: Optional[bool] = None
    repair_actions: List[Dict[str, Any]] = field(default_factory=list)
    finished_at: str = ""


@dataclass
class ToolRequestRecord:
    """Request + Result birleşik kayıt — JSONL satırı başına 1 kayıt."""
    request: ToolRequest
    result: ToolResult


# ── Registry ──────────────────────────────────────────────────────────────────

class ToolRequestLog:
    """In-memory ring buffer + JSONL persist."""

    def __init__(self):
        self._lock = threading.Lock()
        self._ring: deque[ToolRequestRecord] = deque(maxlen=_MAX_RING)
        self._log_path = _LOG_PATH
        self._session_id = _make_id(6)
        self._jsonl_enabled = True
        self._line_count = 0
        self._ensure_dir()

    # ── Public API ────────────────────────────────────────────────────────────

    def start_request(
        self,
        tool_name: str,
        params: dict,
        *,
        source: str = "agent",
        user_input: str = "",
        step_name: str = "",
    ) -> ToolRequest:
        """Yeni bir ToolRequest oluştur ve döndür (henüz kayıt yok)."""
        return ToolRequest(
            request_id=_make_id(8),
            tool_name=tool_name,
            params=_sanitize_params(params),
            source=source,
            user_input_preview=user_input[:120],
            step_name=step_name,
            started_at=_now_iso(),
            session_id=self._session_id,
        )

    def finish_request(
        self,
        request: ToolRequest,
        result: Any,
        *,
        latency_ms: int,
        success: bool,
        error: str = "",
    ) -> ToolResult:
        """ToolResult oluştur, ring buffer'a ekle ve JSONL'e yaz."""
        artifacts = _extract_artifacts(result)
        result_preview = ""
        contract_verified = None
        repair_actions: List[Dict[str, Any]] = []

        if isinstance(result, dict):
            # Contract meta
            contract_verified = result.get("_contract_verified")
            repair_actions = result.get("_repair_actions") or []
            # Preview üret
            if result.get("summary"):
                result_preview = str(result["summary"])[:300]
            elif result.get("message"):
                result_preview = str(result["message"])[:300]
            elif result.get("content"):
                result_preview = str(result["content"])[:300]
            elif result.get("error"):
                result_preview = f"ERROR: {result['error'][:300]}"
        elif isinstance(result, str):
            result_preview = result[:300]

        tool_result = ToolResult(
            request_id=request.request_id,
            tool_name=request.tool_name,
            success=success,
            latency_ms=latency_ms,
            artifacts=artifacts,
            error=error[:300] if error else "",
            result_preview=result_preview,
            contract_verified=contract_verified,
            repair_actions=repair_actions,
            finished_at=_now_iso(),
        )

        record = ToolRequestRecord(request=request, result=tool_result)
        with self._lock:
            self._ring.append(record)
        self._write_jsonl(record)
        return tool_result

    def get_recent(self, limit: int = 100, tool_name: str = "", success_only: bool = False) -> List[dict]:
        """Son N kaydı filtreli getir."""
        with self._lock:
            records = list(self._ring)
        records = records[::-1]  # newest first
        if tool_name:
            records = [r for r in records if r.request.tool_name == tool_name]
        if success_only:
            records = [r for r in records if r.result.success]
        records = records[:limit]
        return [_record_to_dict(r) for r in records]

    def get_stats(self) -> Dict[str, Any]:
        """Özet istatistikler."""
        with self._lock:
            records = list(self._ring)

        total = len(records)
        if total == 0:
            return {"total": 0, "success": 0, "failure": 0,
                    "avg_latency_ms": 0.0, "top_tools": [],
                    "last_artifact": "", "session_id": self._session_id}

        successes = sum(1 for r in records if r.result.success)
        latencies = [r.result.latency_ms for r in records]
        avg_lat = sum(latencies) / len(latencies)

        # Top tools
        tool_counts: Dict[str, int] = {}
        for r in records:
            tool_counts[r.request.tool_name] = tool_counts.get(r.request.tool_name, 0) + 1
        top_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        # Last artifact
        last_artifact = ""
        for r in reversed(records):
            if r.result.artifacts:
                last_artifact = r.result.artifacts[0]
                break

        # Contract stats
        verified = sum(1 for r in records if r.result.contract_verified is True)
        failed_contract = sum(1 for r in records if r.result.contract_verified is False)

        return {
            "total": total,
            "success": successes,
            "failure": total - successes,
            "success_rate_pct": round(successes / total * 100, 1),
            "avg_latency_ms": round(avg_lat, 1),
            "top_tools": [{"tool": k, "calls": v} for k, v in top_tools],
            "last_artifact": last_artifact,
            "contract_verified": verified,
            "contract_failed": failed_contract,
            "session_id": self._session_id,
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _ensure_dir(self):
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            self._jsonl_enabled = False

    def _write_jsonl(self, record: ToolRequestRecord):
        if not self._jsonl_enabled:
            return
        try:
            line = json.dumps(_record_to_dict(record), ensure_ascii=False) + "\n"
            with self._lock:
                # Rotation check (approximate)
                self._line_count += 1
                if self._line_count > _MAX_JSONL:
                    self._rotate_log()
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(line)
        except Exception as exc:
            logger.debug(f"[tool_request] JSONL write failed: {exc}")

    def _rotate_log(self):
        """Eski logu .bak olarak yeniden adlandır, yenisini başlat."""
        try:
            bak = self._log_path.with_suffix(".jsonl.bak")
            if self._log_path.exists():
                self._log_path.rename(bak)
            self._line_count = 0
        except Exception:
            pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_id(length: int = 8) -> str:
    return "".join(random.choices(_ID_CHARS, k=length))


def _now_iso() -> str:
    from datetime import timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_to_dict(r: ToolRequestRecord) -> dict:
    return {
        "request_id": r.request.request_id,
        "tool": r.request.tool_name,
        "source": r.request.source,
        "step": r.request.step_name,
        "params": r.request.params,
        "user_input_preview": r.request.user_input_preview,
        "session_id": r.request.session_id,
        "started_at": r.request.started_at,
        "success": r.result.success,
        "latency_ms": r.result.latency_ms,
        "artifacts": r.result.artifacts,
        "error": r.result.error,
        "result_preview": r.result.result_preview,
        "contract_verified": r.result.contract_verified,
        "repair_actions": r.result.repair_actions,
        "finished_at": r.result.finished_at,
    }


# ── Singleton ─────────────────────────────────────────────────────────────────
_log: ToolRequestLog | None = None
_log_lock = threading.Lock()


def get_tool_request_log() -> ToolRequestLog:
    global _log
    if _log is None:
        with _log_lock:
            if _log is None:
                _log = ToolRequestLog()
    return _log
