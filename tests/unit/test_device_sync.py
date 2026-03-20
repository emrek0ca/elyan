from __future__ import annotations

from core.device_sync import DeviceSyncStore


def test_device_sync_tracks_requests_across_multiple_devices(tmp_path):
    store = DeviceSyncStore(storage_root=tmp_path / "sync")
    store.record_request(
        request_id="req-1",
        user_id="u1",
        channel="web",
        device_id="iphone",
        session_id="sess-a",
        request_text="dosyayi kaydet",
        request_class="direct_action",
        execution_path="fast",
        metadata={"mission_id": "m1"},
    )
    store.record_request(
        request_id="req-2",
        user_id="u1",
        channel="desktop",
        device_id="macbook",
        session_id="sess-b",
        request_text="react landing page yaz",
        request_class="coding",
        execution_path="deep",
    )
    store.record_outcome(
        request_id="req-1",
        user_id="u1",
        channel="web",
        device_id="iphone",
        session_id="sess-a",
        final_outcome="success",
        success=True,
    )

    snapshot = store.get_user_snapshot("u1")
    stats = store.stats()

    assert len(snapshot["devices"]) == 2
    assert snapshot["requests"][0]["request_id"] in {"req-1", "req-2"}
    assert any(item["outcome"] == "success" for item in snapshot["requests"])
    assert stats["sessions"] == 2
    assert stats["tracked_requests"] == 2


def test_device_sync_delete_user_cleans_sessions_and_requests(tmp_path):
    store = DeviceSyncStore(storage_root=tmp_path / "sync")
    store.record_request(
        request_id="req-1",
        user_id="u-delete",
        channel="api",
        request_text="test",
        request_class="workflow",
        execution_path="deep",
    )

    deleted = store.delete_user("u-delete")

    assert deleted["deleted_sessions"] == 1
    assert deleted["deleted_requests"] == 1
    assert store.get_user_snapshot("u-delete")["devices"] == []
