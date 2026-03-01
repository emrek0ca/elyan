from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

from config.settings import ELYAN_DIR


class RunStore:
    """Writes run-scoped observability files under ~/.elyan/runs/<run_id>/."""

    def __init__(self, run_id: str):
        self.run_id = str(run_id or "").strip() or f"run_{int(time.time())}"
        self.base_dir = (ELYAN_DIR / "runs" / self.run_id).expanduser()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_json(value: Any) -> Any:
        try:
            json.dumps(value, ensure_ascii=False, default=str)
            return value
        except Exception:
            return str(value)

    def write_task(self, task_spec: Dict[str, Any] | None, *, user_input: str = "", metadata: Dict[str, Any] | None = None) -> str:
        payload = {
            "run_id": self.run_id,
            "user_input": str(user_input or ""),
            "task_spec": self._safe_json(task_spec or {}),
            "metadata": self._safe_json(metadata or {}),
            "written_at": time.time(),
        }
        out = self.base_dir / "task.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(out)

    def write_evidence(
        self,
        *,
        manifest_path: str = "",
        steps: List[Dict[str, Any]] | None = None,
        artifacts: List[Dict[str, Any]] | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> str:
        payload = {
            "run_id": self.run_id,
            "manifest_path": str(manifest_path or ""),
            "steps": self._safe_json(list(steps or [])),
            "artifacts": self._safe_json(list(artifacts or [])),
            "metadata": self._safe_json(metadata or {}),
            "written_at": time.time(),
        }
        out = self.base_dir / "evidence.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(out)

    def write_summary(
        self,
        *,
        status: str,
        response_text: str,
        error: str = "",
        artifacts: List[Dict[str, Any]] | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> str:
        lines = [
            f"# Run Summary ({self.run_id})",
            "",
            f"- Status: {status}",
            f"- Error: {error or '-'}",
            "",
            "## Response",
            "",
            str(response_text or "").strip() or "-",
            "",
            "## Artifacts",
        ]
        for art in list(artifacts or []):
            if not isinstance(art, dict):
                continue
            path = str(art.get("path") or "").strip()
            sha = str(art.get("sha256") or "").strip()
            if not path:
                continue
            row = f"- {path}"
            if sha:
                row += f" (sha256: {sha})"
            lines.append(row)

        meta = metadata or {}
        if meta:
            lines.extend(["", "## Metadata", "", "```json", json.dumps(meta, ensure_ascii=False, indent=2, default=str), "```"])

        out = self.base_dir / "summary.md"
        out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        return str(out)

    def write_logs(self, lines: List[str] | None = None) -> str:
        out = self.base_dir / "logs.txt"
        payload = "\n".join(str(x) for x in (lines or []) if str(x).strip())
        out.write_text(payload + ("\n" if payload else ""), encoding="utf-8")
        return str(out)

    @staticmethod
    def list_recent_run_dirs(limit: int = 20) -> List[Path]:
        root = (ELYAN_DIR / "runs").expanduser()
        if not root.exists():
            return []
        candidates: list[tuple[float, Path]] = []
        for p in root.iterdir():
            if not p.is_dir():
                continue
            try:
                mtime = float(p.stat().st_mtime)
            except Exception:
                mtime = 0.0
            candidates.append((mtime, p))
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in candidates[: max(1, int(limit))]]

    @staticmethod
    def load_task_from_run(run_dir: Path) -> Dict[str, Any]:
        task_path = Path(run_dir) / "task.json"
        if not task_path.exists():
            return {}
        try:
            payload = json.loads(task_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
        return {}

    @classmethod
    def find_latest_failed_task(cls, limit: int = 30) -> Dict[str, Any]:
        for run_dir in cls.list_recent_run_dirs(limit=limit):
            summary = run_dir / "summary.md"
            if not summary.exists():
                continue
            try:
                content = summary.read_text(encoding="utf-8").lower()
            except Exception:
                continue
            if "- status: failed" not in content:
                continue
            task_payload = cls.load_task_from_run(run_dir)
            if task_payload:
                task_payload["_run_dir"] = str(run_dir)
                return task_payload
        return {}
