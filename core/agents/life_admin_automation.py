from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from core.storage_paths import resolve_elyan_data_dir


_TASK_MARKERS: dict[str, tuple[str, ...]] = {
    "subscription_renewal": ("subscription", "renew", "yenile", "plan", "membership"),
    "appointment": ("appointment", "randevu", "doctor", "dentist", "meeting booking"),
    "bill_payment": ("invoice", "bill", "fatura", "payment due", "odeme"),
    "form_fill": ("form", "application", "basvuru", "submit", "evrak"),
}

_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _collect_inbox_files(workspace: Path, max_files: int = 25) -> list[Path]:
    roots = [workspace, resolve_elyan_data_dir() / "inbox", resolve_elyan_data_dir() / "notes"]
    patterns = ("*inbox*.md", "*mail*.txt", "*email*.txt", "*todo*.md", "*.eml")
    found: list[tuple[float, Path]] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for pattern in patterns:
            for path in root.rglob(pattern):
                if not path.is_file():
                    continue
                key = str(path.resolve())
                if key in seen:
                    continue
                seen.add(key)
                try:
                    mtime = float(path.stat().st_mtime)
                except Exception:
                    mtime = 0.0
                found.append((mtime, path))
    found.sort(key=lambda item: item[0], reverse=True)
    return [row[1] for row in found[: max(1, max_files)]]


def _detect_task(line: str) -> tuple[str, float] | None:
    low = line.lower()
    best_key = ""
    best_score = 0.0
    for key, markers in _TASK_MARKERS.items():
        score = 0.0
        for marker in markers:
            if marker in low:
                score += 1.0
        if score > best_score:
            best_key = key
            best_score = score
    if not best_key or best_score <= 0:
        return None
    confidence = min(0.98, 0.45 + (best_score * 0.15))
    return best_key, confidence


def _extract_due_hint(line: str) -> str:
    m = _DATE_RE.search(line)
    if m:
        return m.group(1)
    low = line.lower()
    if "today" in low or "bugun" in low:
        return "today"
    if "tomorrow" in low or "yarin" in low:
        return "tomorrow"
    if "this week" in low or "bu hafta" in low:
        return "this_week"
    return ""


def _build_workflow(task_type: str, due_hint: str) -> dict[str, Any]:
    if task_type == "bill_payment":
        action = "verify invoice and execute payment flow"
    elif task_type == "subscription_renewal":
        action = "check renewal policy and renew if still needed"
    elif task_type == "appointment":
        action = "confirm slot and add calendar reminder"
    else:
        action = "prepare required fields and submit form"

    return {
        "task_type": task_type,
        "action": action,
        "due_hint": due_hint,
        "priority": "high" if due_hint in {"today", "tomorrow"} else "normal",
    }


def _write_report(result: dict[str, Any]) -> str:
    report_dir = resolve_elyan_data_dir() / "reports" / "life_admin_automation"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = report_dir / f"life_admin_{stamp}.md"
    lines = [
        "# Life Admin Automation",
        "",
        f"- Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Signals analyzed: {result.get('signal_count', 0)}",
        f"- Tasks detected: {result.get('task_count', 0)}",
        "",
        "## Detected Tasks",
    ]
    for row in result.get("detected_tasks", []):
        if not isinstance(row, dict):
            continue
        lines.append(
            f"- {row.get('task_type')} (confidence={row.get('confidence')}, due={row.get('due_hint') or '-'}) :: {row.get('source_line')}"
        )

    lines.extend(["", "## Suggested Workflows", ""])
    for row in result.get("suggested_workflows", []):
        if not isinstance(row, dict):
            continue
        lines.append(f"- {row.get('task_type')}: {row.get('action')} [{row.get('priority')}]")

    out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return str(out)


async def run_life_admin_automation_module(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = payload if isinstance(payload, dict) else {}
    workspace = Path(str(req.get("workspace") or Path.cwd())).expanduser().resolve()

    raw_items = req.get("inbox_items", [])
    lines: list[str] = []
    if isinstance(raw_items, str):
        raw_items = [raw_items]
    if isinstance(raw_items, list):
        lines.extend([_normalize(str(row)) for row in raw_items if _normalize(str(row))])

    files_used: list[str] = []
    if not lines:
        files = _collect_inbox_files(workspace, max_files=int(req.get("max_files", 25) or 25))
        for path in files:
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            chunk = [_normalize(row) for row in content.splitlines() if _normalize(row)]
            if chunk:
                lines.extend(chunk[:40])
                files_used.append(str(path))

    if not lines:
        return {
            "success": True,
            "module_id": "life_admin_automation",
            "status": "no_signals",
            "signal_count": 0,
            "task_count": 0,
            "detected_tasks": [],
            "suggested_workflows": [],
            "files_used": [],
        }

    detected: list[dict[str, Any]] = []
    for line in lines:
        detected_task = _detect_task(line)
        if not detected_task:
            continue
        task_type, confidence = detected_task
        due_hint = _extract_due_hint(line)
        detected.append(
            {
                "task_type": task_type,
                "confidence": round(confidence, 2),
                "due_hint": due_hint,
                "source_line": line[:220],
            }
        )

    workflows = []
    for row in detected[:30]:
        workflow = _build_workflow(str(row.get("task_type") or ""), str(row.get("due_hint") or ""))
        workflows.append(workflow)

    result = {
        "success": True,
        "module_id": "life_admin_automation",
        "status": "ok" if detected else "no_tasks",
        "generated_at": int(time.time()),
        "signal_count": len(lines),
        "task_count": len(detected),
        "detected_tasks": detected[:30],
        "suggested_workflows": workflows,
        "summary_lines": [
            f"Detected {len(detected)} admin tasks from {len(lines)} signals.",
            f"Auto-workflows created: {len(workflows)}",
        ],
        "files_used": files_used,
    }
    result["report_path"] = _write_report(result)
    return result


__all__ = ["run_life_admin_automation_module"]
