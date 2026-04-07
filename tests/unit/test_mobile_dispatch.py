import json

from elyan.channels.mobile_dispatch import MobileDispatchBridge, MobileDispatchRequest, resolve_channel_support


def test_mobile_dispatch_pairing_is_one_time_and_hashed(tmp_path):
    bridge = MobileDispatchBridge(storage_root=tmp_path, ttl_seconds=300)
    pairing = bridge.create_pairing(channel_type="telegram", workspace_id="ws-1", actor_user_id="user-1")
    assert pairing["ok"] is True
    stored = json.loads((tmp_path / "pairings.json").read_text(encoding="utf-8"))
    assert pairing["code"] not in json.dumps(stored)
    first = bridge.redeem_pairing(pairing_id=pairing["pairing_id"], code=pairing["code"])
    second = bridge.redeem_pairing(pairing_id=pairing["pairing_id"], code=pairing["code"])
    assert first["ok"] is True
    assert second["error"] == "already_used"


def test_mobile_dispatch_normalizes_request(tmp_path):
    bridge = MobileDispatchBridge(storage_root=tmp_path)
    request = MobileDispatchRequest(
        channel_type="telegram",
        channel_message_id="msg-1",
        actor_user_id="user-1",
        workspace_id="ws-1",
        session_id="session-1",
        text="hello",
    )
    message = bridge.normalize_request(request)
    session = bridge.record_session(request, run_id="run-1")
    assert message.channel_type == "telegram"
    assert session["run_id"] == "run-1"
    assert message.metadata["dispatch_envelope"]["workspace_id"] == "ws-1"


def test_mobile_dispatch_tracks_delivery_binding_and_dashboard_projection(tmp_path):
    bridge = MobileDispatchBridge(storage_root=tmp_path)
    pairing = bridge.create_pairing(channel_type="telegram", workspace_id="ws-1", actor_user_id="user-1")
    delivered = bridge.mark_pairing_delivered(pairing_id=pairing["pairing_id"])
    redeemed = bridge.redeem_pairing(pairing_id=pairing["pairing_id"], code=pairing["code"])
    bound = bridge.bind_pairing(pairing_id=pairing["pairing_id"], session_id="session-1")
    request = MobileDispatchRequest(
        channel_type="telegram",
        channel_message_id="msg-1",
        actor_user_id="user-1",
        workspace_id="ws-1",
        session_id="session-1",
        text="hello",
        evidence_links=["trace://1"],
    )
    bridge.record_session(request, pairing_status="bound", last_delivery_status="retrying", channel_state="degraded")
    dashboard = bridge.get_dashboard_sessions()
    assert delivered["ok"] is True
    assert redeemed["ok"] is True
    assert bound["ok"] is True
    assert dashboard["count"] == 1
    assert dashboard["fallback_active"] is True
    assert dashboard["sessions"][0]["recovery_hint"] == "retry_last_delivery"


def test_channel_support_gates_imessage_and_sms():
    sms = resolve_channel_support("sms")
    assert sms["available"] is False
    assert sms["error"] == "capability_unavailable"
