from __future__ import annotations

from flask import Blueprint, jsonify, request

from core.learning import get_tiered_hub
from core.learning_control import get_learning_control_plane
from core.privacy import get_privacy_engine


def create_privacy_blueprint() -> Blueprint:
    blueprint = Blueprint("privacy_api", __name__)

    def _workspace_id() -> str:
        payload = request.get_json(silent=True) or {}
        return str(payload.get("workspace_id") or request.args.get("workspace_id") or "local-workspace").strip()

    @blueprint.get("/api/v1/privacy/consent/<user_id>")
    def get_consent(user_id: str):
        scope = str(request.args.get("scope") or "learning").strip()
        return jsonify({"ok": True, "consent": get_privacy_engine().get_consent(user_id, workspace_id=_workspace_id(), scope=scope)})

    @blueprint.post("/api/v1/privacy/consent/<user_id>")
    def set_consent(user_id: str):
        payload = request.get_json(silent=True) or {}
        metadata = dict(payload.get("metadata") or {})
        for key in (
            "allow_personal_data_learning",
            "allow_workspace_data_learning",
            "allow_operational_data_learning",
            "allow_public_data_learning",
            "allow_global_aggregate",
            "allow_global_aggregation",
            "paused",
            "opt_out",
        ):
            if key in payload:
                metadata[key] = payload.get(key)
        consent = get_privacy_engine().set_consent(
            user_id,
            workspace_id=_workspace_id(),
            scope=str(payload.get("scope") or "learning").strip(),
            granted=bool(payload.get("granted", False)),
            source=str(payload.get("source") or "privacy_api").strip(),
            expires_at=float(payload.get("expires_at") or 0.0),
            metadata=metadata,
        )
        return jsonify({"ok": True, "consent": consent})

    @blueprint.delete("/api/v1/privacy/data/<user_id>")
    def delete_data(user_id: str):
        workspace_id = _workspace_id()
        return jsonify(
            {
                "ok": True,
                "privacy": get_privacy_engine().delete_user_data(user_id, workspace_id=workspace_id),
                "learning": get_learning_control_plane().delete_user_data(user_id),
                "tiered": get_tiered_hub().delete_user_data(user_id),
            }
        )

    @blueprint.get("/api/v1/privacy/export/<user_id>")
    def export_data(user_id: str):
        workspace_id = _workspace_id()
        return jsonify(
            {
                "ok": True,
                "export": {
                    "privacy": get_privacy_engine().export_user_data(user_id, workspace_id=workspace_id),
                    "learning": get_learning_control_plane().export_privacy_bundle(user_id, workspace_id=workspace_id),
                    "tiered": get_tiered_hub().stats(),
                },
            }
        )

    @blueprint.get("/api/v1/privacy/learning/stats")
    def learning_stats():
        return jsonify({"ok": True, "stats": get_tiered_hub().stats()})

    @blueprint.get("/api/v1/privacy/learning/global")
    def learning_global():
        return jsonify({"ok": True, "global": get_tiered_hub().global_summary()})

    @blueprint.post("/api/v1/privacy/learning/pause/<user_id>")
    def pause_learning(user_id: str):
        return jsonify({"ok": True, "policy": get_learning_control_plane().set_learning_paused(True, user_id=user_id)})

    @blueprint.post("/api/v1/privacy/learning/resume/<user_id>")
    def resume_learning(user_id: str):
        return jsonify({"ok": True, "policy": get_learning_control_plane().set_learning_paused(False, user_id=user_id)})

    @blueprint.post("/api/v1/privacy/learning/optout/<user_id>")
    def optout_learning(user_id: str):
        return jsonify({"ok": True, "policy": get_learning_control_plane().set_learning_opt_out(user_id, True)})

    return blueprint


__all__ = ["create_privacy_blueprint"]
