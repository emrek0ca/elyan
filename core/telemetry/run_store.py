from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from core.storage_paths import resolve_runs_root
from .events import TelemetryEvent


class TelemetryRunStore:
    """Persists additive runtime-v3 observability files under ~/.elyan/runs/<run_id>/."""

    def __init__(self, run_id: str, *, base_dir: Path | None = None):
        self.run_id = str(run_id or "").strip() or f"run_{int(time.time())}"
        self.base_dir = Path(base_dir).expanduser() if base_dir is not None else (resolve_runs_root() / self.run_id).expanduser()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        self.trace_path = self.base_dir / "trace.jsonl"
        self.summary_path = self.base_dir / "summary.json"
        self.verification_path = self.base_dir / "verification.json"
        self.delivery_path = self.base_dir / "delivery.json"
        self.manifest_path = self.base_dir / "artifacts" / "manifest.json"

    @staticmethod
    def _safe(value: Any) -> Any:
        try:
            json.dumps(value, ensure_ascii=False, default=str)
            return value
        except Exception:
            return str(value)

    def record_event(self, event: TelemetryEvent | str, **kwargs: Any) -> str:
        payload = event if isinstance(event, TelemetryEvent) else TelemetryEvent(event=str(event), request_id=self.run_id, **kwargs)
        line = json.dumps(payload.to_dict(), ensure_ascii=False, default=str)
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return str(self.trace_path)

    def write_summary(self, payload: dict[str, Any]) -> str:
        body = {"run_id": self.run_id, "written_at": time.time(), **self._safe(dict(payload or {}))}
        self.summary_path.write_text(json.dumps(body, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return str(self.summary_path)

    def write_verification(self, payload: dict[str, Any]) -> str:
        body = {"run_id": self.run_id, "written_at": time.time(), **self._safe(dict(payload or {}))}
        self.verification_path.write_text(json.dumps(body, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return str(self.verification_path)

    def write_delivery(self, payload: dict[str, Any]) -> str:
        body = {"run_id": self.run_id, "written_at": time.time(), **self._safe(dict(payload or {}))}
        self.delivery_path.write_text(json.dumps(body, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return str(self.delivery_path)

    def write_artifact_manifest(self, artifacts: list[dict[str, Any]]) -> str:
        body = {"run_id": self.run_id, "written_at": time.time(), "artifacts": self._safe(list(artifacts or []))}
        self.manifest_path.write_text(json.dumps(body, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return str(self.manifest_path)


__all__ = ["TelemetryRunStore"]
