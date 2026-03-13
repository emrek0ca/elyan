from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from core.storage_paths import resolve_elyan_data_dir


_DISTRACTION_MARKERS = (
    "youtube.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "tiktok.com",
    "reddit.com",
    "netflix.com",
)

_WORK_MARKERS = (
    "github.com",
    "gitlab",
    "docs",
    "notion",
    "code",
    "terminal",
    "slack",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _load_events_from_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("events")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _load_default_events() -> list[dict[str, Any]]:
    candidates = [
        resolve_elyan_data_dir() / "focus" / "events.json",
        resolve_elyan_data_dir() / "time_audit" / "events.json",
        resolve_elyan_data_dir() / "desktop_host" / "events.json",
    ]
    for path in candidates:
        rows = _load_events_from_file(path)
        if rows:
            return rows
    return []


def _classify_event(row: dict[str, Any]) -> tuple[str, int]:
    app = _normalize(str(row.get("app") or row.get("name") or "")).lower()
    domain = _normalize(str(row.get("domain") or row.get("url") or "")).lower()
    duration = row.get("duration_minutes", row.get("minutes", 5))
    try:
        minutes = max(1, int(duration))
    except Exception:
        minutes = 5

    joined = f"{app} {domain}".strip()
    if any(marker in joined for marker in _DISTRACTION_MARKERS):
        return "distraction", minutes
    if any(marker in joined for marker in _WORK_MARKERS):
        return "focus", minutes
    if "mail" in joined or "calendar" in joined:
        return "admin", minutes
    return "neutral", minutes


def _build_interventions(distraction_ratio: float, top_distractions: list[str]) -> list[str]:
    actions: list[str] = []
    if distraction_ratio >= 35.0:
        actions.append("Enable strict focus mode for next 60 minutes.")
        if top_distractions:
            actions.append(f"Temporarily block: {', '.join(top_distractions[:3])}")
        actions.append("Mute non-critical notifications until deep work block ends.")
    elif distraction_ratio >= 20.0:
        actions.append("Enable soft focus mode and silence social notifications.")
        if top_distractions:
            actions.append(f"Warn before opening: {', '.join(top_distractions[:2])}")
    else:
        actions.append("Current session is healthy; keep notification profile as-is.")
    return actions


def _write_report(result: dict[str, Any]) -> str:
    report_dir = resolve_elyan_data_dir() / "reports" / "deep_work_protector"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = report_dir / f"deep_work_{stamp}.md"
    lines = [
        "# Deep Work Protector",
        "",
        f"- Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Focus score: {result.get('focus_score', 0)}",
        f"- Distraction ratio: {result.get('distraction_ratio_pct', 0)}%",
        "",
        "## Interventions",
    ]
    for row in result.get("interventions", []):
        lines.append(f"- {row}")
    out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return str(out)


async def run_deep_work_protector_module(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = payload if isinstance(payload, dict) else {}

    events = req.get("activity_events")
    if isinstance(events, list):
        rows = [row for row in events if isinstance(row, dict)]
    else:
        rows = _load_default_events()

    if not rows:
        return {
            "success": True,
            "module_id": "deep_work_protector",
            "status": "no_activity",
            "focus_score": 0,
            "distraction_ratio_pct": 0,
            "interventions": ["No activity signals found."],
        }

    minutes_by_bucket: dict[str, int] = {"focus": 0, "distraction": 0, "admin": 0, "neutral": 0}
    distraction_sources: dict[str, int] = {}

    for row in rows:
        bucket, minutes = _classify_event(row)
        minutes_by_bucket[bucket] = minutes_by_bucket.get(bucket, 0) + minutes

        if bucket == "distraction":
            source = _normalize(str(row.get("domain") or row.get("app") or "unknown")).lower()
            distraction_sources[source] = distraction_sources.get(source, 0) + minutes

    total = sum(minutes_by_bucket.values())
    distraction_ratio = (minutes_by_bucket.get("distraction", 0) / total * 100.0) if total > 0 else 0.0
    focus_ratio = (minutes_by_bucket.get("focus", 0) / total * 100.0) if total > 0 else 0.0
    focus_score = max(0.0, min(100.0, (focus_ratio * 1.2) - (distraction_ratio * 0.8) + 30.0))

    top_distractions = [k for k, _ in sorted(distraction_sources.items(), key=lambda item: item[1], reverse=True)]
    interventions = _build_interventions(distraction_ratio, top_distractions)

    result = {
        "success": True,
        "module_id": "deep_work_protector",
        "status": "ok",
        "generated_at": int(time.time()),
        "event_count": len(rows),
        "bucket_minutes": minutes_by_bucket,
        "distraction_ratio_pct": round(distraction_ratio, 2),
        "focus_ratio_pct": round(focus_ratio, 2),
        "focus_score": round(focus_score, 2),
        "top_distractions": top_distractions[:5],
        "interventions": interventions,
    }
    result["report_path"] = _write_report(result)
    return result


__all__ = ["run_deep_work_protector_module"]
