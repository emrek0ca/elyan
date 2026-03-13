from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from core.storage_paths import resolve_elyan_data_dir, resolve_runs_root


def _safe_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _tail_history_commands(limit: int = 120) -> list[str]:
    history_path = Path.home() / ".zsh_history"
    if not history_path.exists():
        return []
    try:
        lines = history_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-max(10, limit * 3) :]
    except Exception:
        return []
    commands: list[str] = []
    for line in lines:
        row = str(line or "").strip()
        if not row:
            continue
        if ";" in row and row.startswith(":"):
            row = row.split(";", 1)[-1].strip()
        if not row:
            continue
        commands.append(row)
    return commands[-limit:]


def _git_snapshot(workspace: Path) -> dict[str, Any]:
    if not workspace.exists() or not (workspace / ".git").exists():
        return {"branch": "", "changed_files": [], "changed_count": 0}
    branch = ""
    changed_files: list[str] = []
    try:
        proc = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2.0,
        )
        if proc.returncode == 0:
            branch = str(proc.stdout or "").strip()
    except Exception:
        branch = ""
    try:
        proc = subprocess.run(
            ["git", "-C", str(workspace), "status", "--short"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3.0,
        )
        if proc.returncode == 0:
            for row in str(proc.stdout or "").splitlines():
                line = str(row or "").strip()
                if not line:
                    continue
                # Format: "XY path"
                parts = line.split(maxsplit=1)
                if len(parts) == 2:
                    changed_files.append(parts[1].strip())
    except Exception:
        pass
    return {
        "branch": branch,
        "changed_files": changed_files[:40],
        "changed_count": len(changed_files),
    }


def _recent_run_summary(*, hours: int = 36, limit: int = 12) -> list[dict[str, Any]]:
    now = time.time()
    horizon = max(1, int(hours)) * 3600
    root = resolve_runs_root()
    if not root.exists():
        return []
    rows: list[tuple[float, Path]] = []
    for run_dir in root.iterdir():
        if not run_dir.is_dir():
            continue
        try:
            mtime = float(run_dir.stat().st_mtime)
        except Exception:
            mtime = 0.0
        if now - mtime > horizon:
            continue
        rows.append((mtime, run_dir))
    rows.sort(key=lambda item: item[0], reverse=True)

    out: list[dict[str, Any]] = []
    for mtime, run_dir in rows[: max(1, limit)]:
        task = _safe_json(run_dir / "task.json")
        evidence = _safe_json(run_dir / "evidence.json")
        task_meta = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
        user_input = str(task.get("user_input") or "").strip()
        action = str(task_meta.get("action") or "").strip()
        status = "unknown"
        ev_meta = evidence.get("metadata") if isinstance(evidence.get("metadata"), dict) else {}
        if ev_meta:
            status = str(ev_meta.get("status") or status).strip()
        out.append(
            {
                "run_id": run_dir.name,
                "updated_at": int(mtime),
                "action": action,
                "user_input": user_input[:240],
                "status": status,
            }
        )
    return out


def _desktop_state_summary() -> dict[str, Any]:
    state_path = resolve_elyan_data_dir() / "desktop_host" / "state.json"
    payload = _safe_json(state_path)
    if not payload:
        return {
            "frontmost_app": "",
            "active_window_title": "",
            "last_instruction": "",
            "last_status": "",
        }
    active_window = payload.get("active_window") if isinstance(payload.get("active_window"), dict) else {}
    return {
        "frontmost_app": str(payload.get("frontmost_app") or "").strip(),
        "active_window_title": str(active_window.get("title") or "").strip(),
        "last_instruction": str(payload.get("last_instruction") or "").strip(),
        "last_status": str(payload.get("last_status") or "").strip(),
    }


def _find_meeting_notes(workspace: Path, limit: int = 8) -> list[str]:
    patterns = ("*meeting*.md", "*toplanti*.md", "*minutes*.md", "*retrospective*.md")
    roots = [workspace, resolve_elyan_data_dir() / "notes"]
    found: list[tuple[float, str]] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for pattern in patterns:
            for path in root.rglob(pattern):
                try:
                    key = str(path.resolve())
                except Exception:
                    key = str(path)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    mtime = float(path.stat().st_mtime)
                except Exception:
                    mtime = 0.0
                found.append((mtime, key))
    found.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in found[: max(1, limit)]]


def _summarize_yesterday_work(runs: list[dict[str, Any]], git: dict[str, Any], commands: list[str]) -> list[str]:
    bullets: list[str] = []
    seen: set[str] = set()

    for row in runs[:6]:
        action = str(row.get("action") or "").strip()
        user_input = str(row.get("user_input") or "").strip()
        status = str(row.get("status") or "").strip()
        text = action or user_input
        if not text:
            continue
        if len(text) > 120:
            text = text[:117] + "..."
        line = f"{text} [{status or 'unknown'}]"
        if line not in seen:
            seen.add(line)
            bullets.append(line)

    branch = str(git.get("branch") or "").strip()
    changed_count = int(git.get("changed_count") or 0)
    if branch:
        line = f"Git branch: {branch} ({changed_count} changed file)"
        if changed_count != 1:
            line += "s"
        if line not in seen:
            seen.add(line)
            bullets.append(line)

    interesting = []
    for cmd in commands[-80:]:
        low = cmd.lower()
        if any(token in low for token in ("pytest", "git ", "python", "uv ", "docker", "npm ", "pnpm ", "node ")):
            interesting.append(cmd)
    if interesting:
        sample = " | ".join(interesting[-3:])
        line = f"Terminal focus: {sample[:180]}"
        if line not in seen:
            seen.add(line)
            bullets.append(line)

    return bullets[:8]


def _write_recovery_report(payload: dict[str, Any]) -> str:
    report_dir = resolve_elyan_data_dir() / "reports" / "context_recovery"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = report_dir / f"context_recovery_{stamp}.md"
    lines = [
        "# Context Recovery Dashboard",
        "",
        f"- Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Workspace: {payload.get('workspace', '')}",
        "",
        "## Dun Yaptiklarin",
    ]
    for row in payload.get("yesterday_summary", []):
        lines.append(f"- {row}")

    lines.extend(["", "## Next Focus", ""])
    for row in payload.get("next_focus", []):
        lines.append(f"- {row}")

    lines.extend(["", "## Signals", ""])
    desktop = payload.get("desktop_state", {}) if isinstance(payload.get("desktop_state"), dict) else {}
    lines.append(f"- Frontmost app: {desktop.get('frontmost_app', '')}")
    lines.append(f"- Active window: {desktop.get('active_window_title', '')}")
    lines.append(f"- Last instruction: {desktop.get('last_instruction', '')}")
    lines.append(f"- Last status: {desktop.get('last_status', '')}")
    lines.append(f"- Recent runs: {len(payload.get('recent_runs', []))}")
    lines.append(f"- Meeting notes found: {len(payload.get('meeting_notes', []))}")
    out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return str(out)


async def run_context_recovery_module(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = payload if isinstance(payload, dict) else {}
    workspace = Path(str(req.get("workspace") or Path.cwd())).expanduser().resolve()
    history_limit = int(req.get("history_limit") or 120)
    run_hours = int(req.get("run_hours") or 36)
    run_limit = int(req.get("run_limit") or 12)

    git = _git_snapshot(workspace)
    runs = _recent_run_summary(hours=run_hours, limit=run_limit)
    desktop = _desktop_state_summary()
    commands = _tail_history_commands(limit=history_limit)
    meeting_notes = _find_meeting_notes(workspace, limit=8)
    yesterday_summary = _summarize_yesterday_work(runs, git, commands)

    next_focus: list[str] = []
    if git.get("changed_count", 0):
        next_focus.append("Uncommitted git changes exist: finalize or stash critical edits.")
    if runs:
        last = runs[0]
        next_focus.append(
            f"Resume latest run {last.get('run_id')} ({last.get('status') or 'unknown'}) for action '{last.get('action') or last.get('user_input') or 'n/a'}'."
        )
    if meeting_notes:
        next_focus.append("Review latest meeting note and extract action items before coding.")
    if not next_focus:
        next_focus.append("No strong recovery signal found; start with top-priority backlog item.")

    result = {
        "success": True,
        "module_id": "context_recovery",
        "workspace": str(workspace),
        "git": git,
        "recent_runs": runs,
        "desktop_state": desktop,
        "terminal_signals": commands[-25:],
        "meeting_notes": meeting_notes,
        "yesterday_summary": yesterday_summary,
        "next_focus": next_focus[:5],
    }
    result["report_path"] = _write_recovery_report(result)
    return result


__all__ = ["run_context_recovery_module"]
