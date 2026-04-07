from __future__ import annotations

import hashlib
import json
import secrets
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from core.gateway.message import UnifiedMessage
from core.storage_paths import resolve_elyan_data_dir


def _now() -> float:
    return time.time()


def _hash_code(raw: str) -> str:
    return hashlib.sha256(str(raw or "").encode("utf-8")).hexdigest()


@dataclass
class PairingCode:
    pairing_id: str
    channel_type: str
    workspace_id: str
    actor_user_id: str
    code_hash: str
    deep_link: str
    expires_at: float
    state: str = "generated"
    created_at: float = field(default_factory=_now)
    delivered_at: float = 0.0
    redeemed: bool = False
    redeemed_at: float = 0.0
    bound_session_id: str = ""
    last_error: str = ""


@dataclass
class MobileDispatchRequest:
    channel_type: str
    channel_message_id: str
    actor_user_id: str
    workspace_id: str
    session_id: str
    text: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    capabilities: dict[str, Any] = field(default_factory=dict)
    capability_flags: dict[str, Any] = field(default_factory=dict)
    approval_context: dict[str, Any] = field(default_factory=dict)
    evidence_links: list[str] = field(default_factory=list)
    source_metadata: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    received_at: float = field(default_factory=_now)


@dataclass
class MobileDispatchSession:
    dispatch_session_id: str
    channel_type: str
    workspace_id: str
    actor_user_id_hash: str
    session_id: str
    pairing_status: str
    pairing_created_at: float
    pairing_redeemed_at: float = 0.0
    pairing_bound_at: float = 0.0
    latest_event: str = ""
    latest_status: str = ""
    run_id: str = ""
    channel_state: str = "connected"
    last_delivery_status: str = "received"
    approval_wait: bool = False
    evidence_summary: dict[str, Any] = field(default_factory=dict)
    recovery_hint: str = ""
    attachments_count: int = 0


def resolve_channel_support(channel_type: str) -> dict[str, Any]:
    channel = str(channel_type or "").strip().lower()
    if channel == "telegram":
        return {"available": True, "channel_type": "telegram"}
    if channel == "imessage":
        return {"available": sys.platform == "darwin", "channel_type": "imessage", "error": "" if sys.platform == "darwin" else "capability_unavailable"}
    if channel == "sms":
        return {"available": False, "channel_type": "sms", "error": "capability_unavailable"}
    return {"available": False, "channel_type": channel or "unknown", "error": "unsupported_channel"}


class MobileDispatchBridge:
    def __init__(self, storage_root: str | Path | None = None, *, ttl_seconds: int = 300) -> None:
        root = Path(storage_root or (resolve_elyan_data_dir() / "device_sync")).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        self.storage_root = root
        self.ttl_seconds = max(60, int(ttl_seconds or 300))
        self.pairings_path = root / "pairings.json"
        self.sessions_path = root / "mobile_sessions.json"

    def _load_rows(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            return list(json.loads(path.read_text(encoding="utf-8")) or [])
        except Exception:
            return []

    def _save_rows(self, path: Path, rows: list[dict[str, Any]]) -> None:
        path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")

    def create_pairing(self, *, channel_type: str, workspace_id: str, actor_user_id: str) -> dict[str, Any]:
        support = resolve_channel_support(channel_type)
        if not support.get("available"):
            return {"ok": False, "error": str(support.get("error") or "capability_unavailable")}
        raw_code = secrets.token_urlsafe(12)
        pairing_id = f"pair_{int(_now() * 1000)}"
        deep_link = f"elyan://pair?{urlencode({'pairing_id': pairing_id, 'code': raw_code, 'channel': channel_type})}"
        stored_link = f"elyan://pair?{urlencode({'pairing_id': pairing_id, 'channel': channel_type})}"
        row = PairingCode(
            pairing_id=pairing_id,
            channel_type=str(channel_type),
            workspace_id=str(workspace_id or "local-workspace"),
            actor_user_id=str(actor_user_id or "local-user"),
            code_hash=_hash_code(raw_code),
            deep_link=stored_link,
            expires_at=_now() + self.ttl_seconds,
        )
        pairings = self._load_rows(self.pairings_path)
        pairings.append(asdict(row))
        self._save_rows(self.pairings_path, pairings)
        return {"ok": True, "pairing_id": pairing_id, "code": raw_code, "deep_link": deep_link, "expires_at": row.expires_at}

    def mark_pairing_delivered(self, *, pairing_id: str) -> dict[str, Any]:
        updated = []
        outcome = {"ok": False, "error": "not_found"}
        for row in self._load_rows(self.pairings_path):
            if str(row.get("pairing_id") or "") != str(pairing_id or ""):
                updated.append(row)
                continue
            row["state"] = "delivered"
            row["delivered_at"] = _now()
            row["last_error"] = ""
            outcome = {"ok": True, "pairing": row}
            updated.append(row)
        self._save_rows(self.pairings_path, updated)
        return outcome

    def redeem_pairing(self, *, pairing_id: str, code: str) -> dict[str, Any]:
        updated = []
        outcome = {"ok": False, "error": "not_found"}
        for row in self._load_rows(self.pairings_path):
            if str(row.get("pairing_id") or "") != str(pairing_id or ""):
                updated.append(row)
                continue
            if bool(row.get("redeemed")):
                row["state"] = "redeemed"
                outcome = {"ok": False, "error": "already_used"}
            elif float(row.get("expires_at") or 0.0) < _now():
                row["state"] = "expired"
                row["last_error"] = "expired"
                outcome = {"ok": False, "error": "expired"}
            elif str(row.get("code_hash") or "") != _hash_code(code):
                row["state"] = "invalid"
                row["last_error"] = "invalid"
                outcome = {"ok": False, "error": "invalid"}
            else:
                row["redeemed"] = True
                row["redeemed_at"] = _now()
                row["state"] = "redeemed"
                row["last_error"] = ""
                outcome = {"ok": True, "pairing": row}
            updated.append(row)
        self._save_rows(self.pairings_path, updated)
        return outcome

    def bind_pairing(self, *, pairing_id: str, session_id: str) -> dict[str, Any]:
        updated = []
        outcome = {"ok": False, "error": "not_found"}
        for row in self._load_rows(self.pairings_path):
            if str(row.get("pairing_id") or "") != str(pairing_id or ""):
                updated.append(row)
                continue
            if not bool(row.get("redeemed")):
                row["last_error"] = "not_redeemed"
                outcome = {"ok": False, "error": "not_redeemed"}
            else:
                row["state"] = "bound"
                row["bound_session_id"] = str(session_id or "")
                row["last_error"] = ""
                outcome = {"ok": True, "pairing": row}
            updated.append(row)
        self._save_rows(self.pairings_path, updated)
        return outcome

    def normalize_request(self, request: MobileDispatchRequest) -> UnifiedMessage:
        return UnifiedMessage(
            id=str(request.channel_message_id or ""),
            channel_type=str(request.channel_type or "mobile"),
            channel_id=str(request.session_id or request.workspace_id or "mobile"),
            user_id=str(request.actor_user_id or "local-user"),
            user_name=str(request.actor_user_id or "local-user"),
            text=str(request.text or ""),
            attachments=list(request.attachments or []),
            metadata={
                "dispatch_envelope": {
                    "actor_user_id": str(request.actor_user_id or "local-user"),
                    "workspace_id": str(request.workspace_id or "local-workspace"),
                    "session_id": str(request.session_id or ""),
                    "run_id": str(request.run_id or ""),
                    "attachments": list(request.attachments or []),
                    "capability_flags": dict(request.capability_flags or request.capabilities or {}),
                    "approval_context": dict(request.approval_context or {}),
                    "evidence_links": list(request.evidence_links or []),
                },
                "workspace_id": str(request.workspace_id or "local-workspace"),
                "session_id": str(request.session_id or ""),
                "capabilities": dict(request.capabilities or {}),
                "capability_flags": dict(request.capability_flags or request.capabilities or {}),
                "approval_context": dict(request.approval_context or {}),
                "evidence_links": list(request.evidence_links or []),
                "run_id": str(request.run_id or ""),
                "source_metadata": dict(request.source_metadata or {}),
            },
        )

    def record_session(
        self,
        request: MobileDispatchRequest,
        *,
        pairing_status: str = "redeemed",
        run_id: str = "",
        channel_state: str = "connected",
        last_delivery_status: str = "received",
        approval_wait: bool = False,
        evidence_summary: dict[str, Any] | None = None,
        recovery_hint: str = "",
    ) -> dict[str, Any]:
        row = MobileDispatchSession(
            dispatch_session_id=f"dispatch_{int(_now() * 1000)}",
            channel_type=str(request.channel_type or "mobile"),
            workspace_id=str(request.workspace_id or "local-workspace"),
            actor_user_id_hash=_hash_code(request.actor_user_id)[:16],
            session_id=str(request.session_id or ""),
            pairing_status=str(pairing_status or "redeemed"),
            pairing_created_at=_now(),
            pairing_redeemed_at=_now() if pairing_status == "redeemed" else 0.0,
            pairing_bound_at=_now() if pairing_status == "bound" else 0.0,
            latest_event="mobile.dispatch.received",
            latest_status="received",
            run_id=str(run_id or request.run_id or ""),
            channel_state=str(channel_state or "connected"),
            last_delivery_status=str(last_delivery_status or "received"),
            approval_wait=bool(approval_wait),
            evidence_summary=dict(evidence_summary or {"links": list(request.evidence_links or []), "count": len(list(request.evidence_links or []))}),
            recovery_hint=str(recovery_hint or self._recovery_hint(channel_type=request.channel_type, channel_state=channel_state, delivery_status=last_delivery_status, approval_wait=approval_wait)),
            attachments_count=len(list(request.attachments or [])),
        )
        rows = self._load_rows(self.sessions_path)
        rows.append(asdict(row))
        self._save_rows(self.sessions_path, rows)
        return asdict(row)

    def get_dashboard_sessions(self) -> dict[str, Any]:
        sessions = self._load_rows(self.sessions_path)
        channels: dict[str, dict[str, Any]] = {}
        for name in ("telegram", "imessage", "sms"):
            support = resolve_channel_support(name)
            channels[name] = {
                "available": bool(support.get("available")),
                "status": "connected" if support.get("available") else "unavailable",
                "reason": str(support.get("error") or ""),
            }
        pending_approval = sum(1 for row in sessions if bool(row.get("approval_wait")))
        fallback_active = any(str(row.get("channel_state") or "") in {"degraded", "recovery"} for row in sessions)
        return {
            "sessions": sessions,
            "count": len(sessions),
            "pending_approvals": pending_approval,
            "fallback_active": fallback_active,
            "channel_availability": channels,
        }

    @staticmethod
    def _recovery_hint(*, channel_type: str, channel_state: str, delivery_status: str, approval_wait: bool) -> str:
        if approval_wait:
            return "approval_required"
        if str(delivery_status or "") in {"delivery_failed", "retrying"}:
            return "retry_last_delivery"
        if str(channel_state or "") in {"unavailable", "degraded"}:
            support = resolve_channel_support(channel_type)
            if not support.get("available"):
                return str(support.get("error") or "channel_unavailable")
            return "reconnect_channel"
        return "none"


__all__ = ["MobileDispatchBridge", "MobileDispatchRequest", "MobileDispatchSession", "PairingCode", "resolve_channel_support"]
