from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from core.storage_paths import resolve_elyan_data_dir


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _classify_signal(text: str) -> str:
    low = text.lower()
    if any(token in low for token in ("pytest", "coding", "code", "commit", "refactor", "bugfix")):
        return "coding"
    if any(token in low for token in ("research", "article", "youtube", "read", "study")):
        return "learning"
    if any(token in low for token in ("mail", "calendar", "meeting", "invoice", "admin")):
        return "admin"
    if any(token in low for token in ("youtube.com", "instagram", "x.com", "twitter", "reddit", "tiktok")):
        return "distraction"
    return "other"


def _load_history_events(limit: int = 200) -> list[dict[str, Any]]:
    history_path = Path.home() / ".zsh_history"
    if not history_path.exists():
        return []
    try:
        lines = history_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-max(20, limit):]
    except Exception:
        return []

    events: list[dict[str, Any]] = []
    for line in lines:
        row = _normalize(line)
        if not row:
            continue
        if ";" in row and row.startswith(":"):
            row = row.split(";", 1)[-1].strip()
        if not row:
            continue
        events.append({"signal": row, "duration_minutes": 5})
    return events


def _write_report(result: dict[str, Any]) -> str:
    report_dir = resolve_elyan_data_dir() / "reports" / "digital_time_auditor"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = report_dir / f"time_audit_{stamp}.md"
    lines = [
        "# Digital Time Auditor",
        "",
        f"- Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Total tracked minutes: {result.get('total_minutes', 0)}",
        f"- Distraction ratio: {result.get('distraction_ratio_pct', 0)}%",
        "",
        "## Time Allocation",
    ]
    for row in result.get("allocation", []):
        lines.append(f"- {row.get('category')}: {row.get('minutes')} min ({row.get('hours')} h)")
    out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return str(out)


async def run_digital_time_auditor_module(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = payload if isinstance(payload, dict) else {}

    raw_blocks = req.get("activity_blocks")
    events: list[dict[str, Any]] = []
    if isinstance(raw_blocks, list):
        for row in raw_blocks:
            if not isinstance(row, dict):
                continue
            events.append(
                {
                    "signal": _normalize(str(row.get("signal") or row.get("category") or row.get("name") or "")),
                    "duration_minutes": row.get("duration_minutes", row.get("minutes", 15)),
                }
            )
    if not events:
        events = _load_history_events(limit=int(req.get("history_limit", 200) or 200))

    if not events:
        return {
            "success": True,
            "module_id": "digital_time_auditor",
            "status": "no_activity",
            "total_minutes": 0,
            "allocation": [],
            "distraction_ratio_pct": 0,
            "summary_lines": ["No time signals found."],
        }

    bucket_minutes: dict[str, int] = {"coding": 0, "learning": 0, "admin": 0, "distraction": 0, "other": 0}
    for event in events:
        category = _classify_signal(str(event.get("signal") or ""))
        duration = event.get("duration_minutes", 10)
        try:
            minutes = max(1, int(duration))
        except Exception:
            minutes = 10
        bucket_minutes[category] = bucket_minutes.get(category, 0) + minutes

    total_minutes = sum(bucket_minutes.values())
    allocation = []
    for category, minutes in sorted(bucket_minutes.items(), key=lambda item: item[1], reverse=True):
        if minutes <= 0:
            continue
        allocation.append(
            {
                "category": category,
                "minutes": minutes,
                "hours": round(minutes / 60.0, 2),
            }
        )

    distraction_ratio = (bucket_minutes.get("distraction", 0) / total_minutes * 100.0) if total_minutes > 0 else 0.0
    result = {
        "success": True,
        "module_id": "digital_time_auditor",
        "status": "ok",
        "generated_at": int(time.time()),
        "event_count": len(events),
        "total_minutes": total_minutes,
        "allocation": allocation,
        "distraction_ratio_pct": round(distraction_ratio, 2),
        "summary_lines": [
            f"Coding: {bucket_minutes.get('coding', 0)} min",
            f"Learning: {bucket_minutes.get('learning', 0)} min",
            f"Distraction: {bucket_minutes.get('distraction', 0)} min",
        ],
    }
    result["report_path"] = _write_report(result)
    return result


__all__ = ["run_digital_time_auditor_module"]
