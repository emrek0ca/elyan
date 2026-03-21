from __future__ import annotations

import mimetypes
from html import escape
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from core.mission_control import get_mission_runtime
from core.reliability.store import OutcomeStore
from core.storage_paths import resolve_elyan_data_dir, resolve_proofs_root, resolve_runs_root


def _safe_roots() -> tuple[Path, ...]:
    return tuple(
        path.resolve()
        for path in (
            resolve_elyan_data_dir(),
            resolve_runs_root(),
            resolve_proofs_root(),
            Path.home(),
            Path("/tmp"),
            Path("/private"),
        )
    )


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _is_safe_root(path: Path) -> bool:
    resolved = path.resolve()
    return any(str(resolved).startswith(str(root)) for root in _safe_roots())


def resolve_evidence_path(raw_path: str) -> Path | None:
    raw = _clean_text(raw_path)
    if not raw:
        return None
    try:
        resolved = Path(raw).expanduser().resolve()
    except Exception:
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    if not _is_safe_root(resolved):
        return None
    return resolved


def build_evidence_file_url(raw_path: str) -> str:
    resolved = resolve_evidence_path(raw_path)
    if resolved is None:
        return ""
    return f"/api/evidence/file?path={quote(str(resolved), safe='')}"


def _media_kind(path: str) -> str:
    suffix = Path(path or "").suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}:
        return "image"
    if suffix in {".mp4", ".mov", ".webm", ".m4v", ".avi"}:
        return "video"
    if suffix in {".json", ".jsonl", ".txt", ".md", ".log", ".csv"}:
        return "text"
    return "file"


def _timeline_events(mission: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for event in list(getattr(mission, "events", []) or []):
        try:
            row = event.to_dict() if hasattr(event, "to_dict") else dict(event)
        except Exception:
            continue
        if isinstance(row, dict):
            row.setdefault("kind", row.get("event_type") or row.get("type") or "event")
            events.append(row)
    return events


def _mission_payload(task_id: str, runtime: Any | None = None) -> dict[str, Any]:
    runtime = runtime or get_mission_runtime()
    mission = runtime.get_mission(task_id)
    if mission is None:
        return {
            "ok": False,
            "task_id": str(task_id or ""),
            "mission_id": str(task_id or ""),
            "status": "missing",
            "goal": "",
            "skill_name": "",
            "summary": {},
            "control": {},
            "graph": {},
            "decision_trace": {},
            "timeline": [],
            "evidence": [],
            "approvals": [],
            "attachments": [],
            "live_events": [],
            "decisions": [],
            "outcomes": [],
        }

    control = mission.control_summary()
    summary = mission.preview_summary()
    decision_trace = dict(
        mission.metadata.get("decision_trace")
        or mission.metadata.get("operator_trace")
        or mission.metadata.get("execution_trace")
        or {}
    )
    if not decision_trace:
        decision_trace = {
            "graph": mission.graph.to_dict(),
            "control_summary": control,
        }
    timeline = _timeline_events(mission)
    evidence = get_evidence_gallery(mission.mission_id)
    store = OutcomeStore()
    decisions = [row for row in store.decisions_for_request(mission.mission_id) if isinstance(row, dict)]
    outcomes = [
        row
        for row in store.recent_outcomes(limit=20)
        if isinstance(row, dict) and str(row.get("request_id") or "") == mission.mission_id
    ]
    live_events = (timeline[-8:] if timeline else []) + [
        {
            "type": "decision",
            "label": row.get("kind") or row.get("selected") or "decision",
            "status": row.get("outcome_status") or row.get("success_label"),
            "detail": row,
        }
        for row in decisions[-4:]
    ]
    live_events.extend(
        {
            "type": "outcome",
            "label": row.get("action") or row.get("final_outcome") or "outcome",
            "status": "success" if row.get("success") else "failed",
            "detail": row,
        }
        for row in outcomes[-4:]
    )
    return {
        "ok": True,
        "task_id": mission.mission_id,
        "mission_id": mission.mission_id,
        "skill_name": str(mission.metadata.get("skill_name") or mission.route_mode or mission.goal[:64]),
        "goal": mission.goal,
        "status": mission.status,
        "mode": mission.mode,
        "route_mode": mission.route_mode,
        "risk_profile": mission.risk_profile,
        "summary": summary,
        "control": control,
        "graph": mission.graph.to_dict(),
        "decision_trace": decision_trace,
        "timeline": timeline,
        "evidence": evidence,
        "approvals": [item.to_dict() for item in mission.approvals],
        "attachments": list(mission.attachments),
        "metadata": dict(mission.metadata or {}),
        "deliverable": mission.deliverable,
        "live_events": live_events,
        "decisions": decisions,
        "outcomes": outcomes,
    }


def get_execution_history(task_id: str, *, limit: int = 20, runtime: Any | None = None) -> dict[str, Any]:
    bundle = _mission_payload(str(task_id or ""), runtime=runtime)
    if bundle.get("ok"):
        return bundle

    store = OutcomeStore()
    request_id = str(task_id or "").strip()
    decisions = [row for row in store.decisions_for_request(request_id) if isinstance(row, dict)]
    outcomes = [
        row
        for row in store.recent_outcomes(limit=max(1, int(limit or 20)) * 2)
        if isinstance(row, dict) and str(row.get("request_id") or "") == request_id
    ]
    return {
        "ok": bool(decisions or outcomes),
        "task_id": request_id,
        "mission_id": request_id,
        "skill_name": "",
        "goal": "",
        "status": "missing",
        "mode": "",
        "route_mode": "",
        "risk_profile": "",
        "summary": {},
        "control": {},
        "graph": {},
        "decision_trace": {
            "decisions": decisions,
            "outcomes": outcomes,
        },
        "timeline": [],
        "evidence": [],
        "approvals": [],
        "attachments": [],
        "metadata": {},
        "deliverable": "",
        "live_events": decisions[-4:] + outcomes[-4:],
        "decisions": decisions,
        "outcomes": outcomes,
    }


def get_evidence_gallery(task_id: str, runtime: Any | None = None) -> list[dict[str, Any]]:
    runtime = runtime or get_mission_runtime()
    mission = runtime.get_mission(str(task_id or ""))
    if mission is None:
        return []

    items: list[dict[str, Any]] = []
    for record in list(mission.evidence or []):
        raw_path = str(record.path or "").strip()
        resolved = resolve_evidence_path(raw_path) if raw_path else None
        mime_type, _ = mimetypes.guess_type(str(resolved or raw_path))
        media_kind = _media_kind(str(resolved or raw_path or record.summary or ""))
        item = {
            "id": str(getattr(record, "evidence_id", "") or getattr(record, "id", "") or ""),
            "mission_id": mission.mission_id,
            "node_id": str(getattr(record, "node_id", "") or ""),
            "kind": str(getattr(record, "kind", "") or "evidence"),
            "label": str(getattr(record, "label", "") or getattr(record, "kind", "") or "Evidence"),
            "summary": str(getattr(record, "summary", "") or ""),
            "path": str(resolved or raw_path or ""),
            "display_path": str(resolved or raw_path or ""),
            "url": build_evidence_file_url(str(resolved or raw_path or "")),
            "mime_type": str(mime_type or ""),
            "media_kind": media_kind,
            "exists": bool(resolved),
            "size_bytes": int(resolved.stat().st_size) if resolved else 0,
            "created_at": float(getattr(record, "created_at", 0.0) or 0.0),
            "metadata": dict(getattr(record, "metadata", {}) or {}),
        }
        items.append(item)

    for raw_path in list(mission.attachments or []):
        resolved = resolve_evidence_path(raw_path)
        if resolved is None:
            continue
        mime_type, _ = mimetypes.guess_type(str(resolved))
        items.append(
            {
                "id": f"attachment:{resolved.name}",
                "mission_id": mission.mission_id,
                "node_id": "",
                "kind": "attachment",
                "label": resolved.name,
                "summary": resolved.name,
                "path": str(resolved),
                "display_path": str(resolved),
                "url": build_evidence_file_url(str(resolved)),
                "mime_type": str(mime_type or ""),
                "media_kind": _media_kind(str(resolved)),
                "exists": True,
                "size_bytes": int(resolved.stat().st_size),
                "created_at": 0.0,
                "metadata": {},
            }
        )

    items.sort(key=lambda row: (float(row.get("created_at") or 0.0), str(row.get("label") or "")), reverse=True)
    return items


def build_trace_bundle(task_id: str, runtime: Any | None = None) -> dict[str, Any]:
    history = get_execution_history(task_id, runtime=runtime)
    evidence = get_evidence_gallery(task_id, runtime=runtime)
    history.setdefault("evidence", evidence)
    history.setdefault("evidence_count", len(evidence))
    return {
        "ok": bool(history.get("ok", False)),
        "task_id": str(task_id or ""),
        "history": history,
        "evidence": evidence,
        "title": str(history.get("goal") or history.get("mission_id") or task_id or "Trace"),
    }


def trace_debug_json(task_id: str) -> str:
    return json.dumps(build_trace_bundle(task_id), ensure_ascii=False, indent=2)


def trace_history_html(task_id: str) -> str:
    payload = build_trace_bundle(task_id)
    return escape(json.dumps(payload, ensure_ascii=False, indent=2))
