from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests

from runtime import state_store
from runtime.backend_client import BackendClient, BackendResult
from runtime.capability_registry import capability_names

VALID_DEVICE_ID = "11111111-1111-4111-8111-111111111111"
VALID_CONNECTION_ID = "22222222-2222-4222-8222-222222222222"
VALID_DEVICE_SECRET = "device-secret-123456"


def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(state_store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(state_store, "STATE_PATH", tmp_path / "elyan_state.json")
    monkeypatch.setattr(state_store, "LEGACY_STATE_PATH", tmp_path / "legacy.json")


def test_register_runtime_stores_connection_bound_runtime_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    client = BackendClient("http://backend.example")

    client._apply_runtime_truth(
        {
            "runtime": {
                "deviceId": VALID_DEVICE_ID,
                "connectionId": VALID_CONNECTION_ID,
                "capabilities": ["quantum_run_experiment", "web_research"],
                "capabilityStates": {
                    "local_files.index": {
                        "available": True,
                        "ready": False,
                        "stats": {
                            "rootCount": 1,
                            "indexedFileCount": 0,
                            "lastScanAt": "2026-06-03T10:00:00Z",
                        },
                        "errorCode": "no_approved_roots",
                    }
                },
            },
            "tokens": {"accessToken": "runtime-token"},
        }
    )

    runtime = state_store.snapshot()["runtime"]
    assert runtime["runtimeToken"] == "runtime-token"
    assert runtime["deviceId"] == VALID_DEVICE_ID
    assert runtime["connectionId"] == VALID_CONNECTION_ID
    assert runtime["capabilities"] == ["quantum_run_experiment", "web_research"]
    assert runtime["capabilityStates"] == {
        "local_files.index": {
            "available": True,
            "ready": False,
            "stats": {
                "rootCount": 1,
                "indexedFileCount": 0,
                "lastScanAt": "2026-06-03T10:00:00Z",
            },
            "errorCode": "no_approved_roots",
        }
    }


def test_runtime_unauthorized_clears_runtime_without_user_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state_store.update_state(
        {
            "account": {"accessToken": "user-token", "refreshToken": "refresh-token"},
            "runtime": {"runtimeToken": "stale-runtime-token", "connectionId": "old-connection", "ready": True},
        }
    )
    client = BackendClient("http://backend.example")

    monkeypatch.setattr(
        client,
        "_request",
        lambda *_args, **_kwargs: BackendResult(
            ok=False,
            request_id="req_test",
            status_code=401,
            data={"error": "stale_runtime"},
            error="stale_runtime",
        ),
    )

    result = client._authorized_request("GET", "/v1/runtime/session", token_kind="runtime")

    state = state_store.snapshot()
    assert result.status_code == 401
    assert state["runtime"]["runtimeToken"] == ""
    assert state["runtime"]["connectionId"] == ""
    assert state["account"]["accessToken"] == "user-token"
    assert state["account"]["refreshToken"] == "refresh-token"


def test_auth_register_sends_required_legal_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    client = BackendClient("http://backend.example")
    captured: dict[str, Any] = {}

    def fake_request(method: str, path: str, json_body: dict[str, Any] | None = None, **_kwargs: Any) -> BackendResult:
        captured["method"] = method
        captured["path"] = path
        captured["json"] = json_body
        return BackendResult(
            ok=True,
            request_id="req_auth_register",
            status_code=200,
            data={
                "user": {"id": "user-1", "email": "user@example.com", "displayName": "User"},
                "tokens": {"accessToken": "access-token", "refreshToken": "refresh-token"},
            },
        )

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.auth_register(
        "user@example.com",
        "secret1234",
        "User",
        {"termsAccepted": True, "privacyAccepted": True},
    )

    assert result.ok is True
    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/auth/register"
    assert captured["json"]["legalAcceptance"] == {
        "termsAccepted": True,
        "privacyAccepted": True,
    }


def test_request_connection_errors_are_normalized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    client = BackendClient("http://backend.example")

    class FakeSession:
        def request(self, *_args: Any, **_kwargs: Any) -> BackendResult:
            raise requests.ConnectionError("boom")

    monkeypatch.setattr(client, "_session_for_thread", lambda: FakeSession())

    result = client.health()

    assert result.ok is False
    assert result.status_code is None
    assert result.error == "network_unreachable"


def test_request_timeouts_are_normalized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    client = BackendClient("http://backend.example")

    class FakeSession:
        def request(self, *_args: Any, **_kwargs: Any) -> BackendResult:
            raise requests.Timeout("slow")

    monkeypatch.setattr(client, "_session_for_thread", lambda: FakeSession())

    result = client.health()

    assert result.ok is False
    assert result.status_code is None
    assert result.error == "network_timeout"


def test_backend_client_prefers_non_loopback_backend_url_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_BASE_URL", "http://127.0.0.1:4000")
    monkeypatch.setenv("ELYAN_BACKEND_BASE_URL", "http://84.247.172.213:4000")
    monkeypatch.setattr(
        "runtime.backend_client.get_app_config_value",
        lambda _key, default=None: default,
    )

    client = BackendClient(None)

    assert client.base_url == "https://api.elyan.dev"


def test_backend_client_keeps_loopback_url_when_no_remote_alternative_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_BASE_URL", "http://127.0.0.1:4000")
    monkeypatch.setenv("ELYAN_BACKEND_BASE_URL", "")
    monkeypatch.setattr(
        "runtime.backend_client.get_app_config_value",
        lambda _key, default=None: default,
    )

    client = BackendClient(None)

    assert client.base_url == "http://127.0.0.1:4000"


def test_backend_client_migrates_legacy_public_ip_to_public_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "runtime.backend_client.get_app_config_value",
        lambda _key, default=None: default,
    )

    client = BackendClient("http://84.247.172.213:4000")

    assert client.base_url == "https://api.elyan.dev"


def test_pairing_poll_sends_pairing_token_and_stores_runtime_auth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state_store.update_state(
        {
            "pairing": {"pairingToken": "pair-token"},
            "runtime": {
                "deviceId": VALID_DEVICE_ID,
                "deviceSecret": VALID_DEVICE_SECRET,
            },
        }
    )
    client = BackendClient("http://backend.example")
    captured: dict[str, Any] = {}

    def fake_request(*_args: Any, **kwargs: Any) -> BackendResult:
        captured["headers"] = kwargs.get("headers")
        return BackendResult(
            ok=True,
            request_id="req_test",
            status_code=200,
            data={
                "sessionId": "session-1",
                "desktopDeviceId": VALID_DEVICE_ID,
                "status": "claimed",
                "expiresAt": "2030-05-22T15:30:00Z",
                "runtimeAuth": {
                    "deviceId": VALID_DEVICE_ID,
                    "deviceSecret": "derived-device-secret",
                },
            },
        )

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.pairing_get_session("session-1")

    state = state_store.snapshot()
    assert result.ok is True
    assert captured["headers"] == {"x-pairing-token": "pair-token"}
    assert state["pairing"]["lastSessionId"] == "session-1"
    assert state["pairing"]["desktopDeviceId"] == VALID_DEVICE_ID
    assert state["pairing"]["lastSessionStatus"] == "claimed"
    assert state["pairing"]["expiresAt"] == "2030-05-22T15:30:00Z"
    assert state["pairing"]["lastErrorCode"] == ""
    assert state["runtime"]["deviceId"] == VALID_DEVICE_ID
    assert state["runtime"]["deviceSecret"] == "derived-device-secret"


def test_pairing_create_session_hydrates_canonical_qr_truth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state_store.update_state({"pairing": {"externalDeviceId": "desktop-ext-1"}})
    client = BackendClient("http://backend.example")
    external_device_id = state_store.snapshot()["pairing"]["externalDeviceId"]
    captured: dict[str, Any] = {}

    def fake_authorized_request(_method: str, _path: str, json_body: dict[str, Any] | None = None, **_kwargs: Any) -> BackendResult:
        captured["payload"] = dict(json_body or {})
        return BackendResult(
            ok=True,
            request_id="req_pair",
            status_code=200,
            data={
                "sessionId": "23894d77-cc67-4155-8edd-f4daf43a5e2d",
                "desktopDevice": {"id": VALID_DEVICE_ID},
                "status": "pending",
                "pairingToken": "pair-token",
                "pairingCode": "PWGSFB5B",
                "qrText": "elyan://pair?sessionId=23894d77-cc67-4155-8edd-f4daf43a5e2d&pairingCode=PWGSFB5B",
                "expiresAt": "2030-05-22T15:30:00Z",
            },
            x_request_id="req-server-pair",
        )

    monkeypatch.setattr(client, "_authorized_request", fake_authorized_request)

    result = client.pairing_create_session({"deviceLabel": "Elyan", "platform": "macos"})

    state = state_store.snapshot()
    assert result.ok is True
    assert captured["payload"]["externalDeviceId"] == external_device_id
    assert state["pairing"]["lastSessionId"] == "23894d77-cc67-4155-8edd-f4daf43a5e2d"
    assert state["pairing"]["desktopDeviceId"] == VALID_DEVICE_ID
    assert state["pairing"]["pairingToken"] == "pair-token"
    assert state["pairing"]["pairingCode"] == "PWGSFB5B"
    assert state["pairing"]["qrText"] == "elyan://pair?sessionId=23894d77-cc67-4155-8edd-f4daf43a5e2d&pairingCode=PWGSFB5B"
    assert state["pairing"]["expiresAt"] == "2030-05-22T15:30:00Z"
    assert state["pairing"]["lastSessionStatus"] == "pending"
    assert state["pairing"]["lastErrorCode"] == ""
    assert state["runtime"]["lifecycleState"] == "waiting_claim"


def test_pairing_terminal_error_clears_active_qr_truth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state_store.update_state(
        {
            "pairing": {
                "lastSessionId": "session-1",
                "desktopDeviceId": VALID_DEVICE_ID,
                "pairingToken": "pair-token",
                "pairingCode": "PWGSFB5B",
                "qrText": "elyan://pair?sessionId=session-1&pairingCode=PWGSFB5B",
                "expiresAt": "2030-05-22T15:30:00Z",
            }
        }
    )
    client = BackendClient("http://backend.example")

    monkeypatch.setattr(
        client,
        "_request",
        lambda *_args, **_kwargs: BackendResult(
            ok=False,
            request_id="req_expired",
            status_code=409,
            data={"error": "Pair session has expired"},
            error="Pair session has expired",
        ),
    )

    result = client.pairing_get_session("session-1")

    state = state_store.snapshot()
    assert result.ok is False
    assert state["pairing"]["lastSessionId"] == ""
    assert state["pairing"]["desktopDeviceId"] == ""
    assert state["pairing"]["pairingToken"] == ""
    assert state["pairing"]["pairingCode"] == ""
    assert state["pairing"]["qrText"] == ""
    assert state["pairing"]["expiresAt"] == ""
    assert state["pairing"]["lastSessionStatus"] == ""
    assert state["pairing"]["lastErrorCode"] == "PAIRING_SESSION_EXPIRED"
    assert state["runtime"]["lifecycleState"] == "waiting_claim"
    assert state["runtime"]["ready"] is False


def test_heartbeat_failure_marks_runtime_reconnecting_without_clearing_user_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state_store.update_state(
        {
            "account": {"accessToken": "user-token", "refreshToken": "refresh-token"},
            "runtime": {
                "runtimeToken": "runtime-token",
                "deviceId": VALID_DEVICE_ID,
                "deviceSecret": VALID_DEVICE_SECRET,
                "ready": True,
                "lifecycleState": "ready",
                "websocketConnected": True,
            },
            "pairing": {"realtimeReady": True},
        }
    )
    client = BackendClient("http://backend.example")

    monkeypatch.setattr(
        client,
        "_authorized_request",
        lambda *_args, **_kwargs: BackendResult(
            ok=False,
            request_id="req_heartbeat_failed",
            status_code=503,
            data={"error": "runtime heartbeat unavailable"},
            error="runtime heartbeat unavailable",
        ),
    )

    result = client.heartbeat({"status": "online"})

    state = state_store.snapshot()
    assert result.ok is False
    assert state["runtime"]["lifecycleState"] == "reconnecting"
    assert state["runtime"]["ready"] is False
    assert state["runtime"]["websocketConnected"] is False
    assert state["pairing"]["realtimeReady"] is False
    assert state["account"]["accessToken"] == "user-token"


def test_heartbeat_fills_missing_capabilities_with_registry_truth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state_store.update_state(
        {
            "runtime": {
                "runtimeToken": "runtime-token",
                "deviceId": VALID_DEVICE_ID,
                "deviceSecret": VALID_DEVICE_SECRET,
                "ready": False,
                "lifecycleState": "runtime_connecting",
                "websocketConnected": False,
            }
        }
    )
    client = BackendClient("http://backend.example")
    captured: dict[str, Any] = {}

    def fake_authorized_request(
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        *,
        token_kind: str = "user",
        refresh_on_401: bool = False,
    ) -> BackendResult:
        captured["method"] = method
        captured["path"] = path
        captured["json"] = dict(json_body or {})
        captured["token_kind"] = token_kind
        captured["refresh_on_401"] = refresh_on_401
        return BackendResult(ok=True, request_id="req_heartbeat", status_code=200, data={"ok": True})

    monkeypatch.setattr(client, "_authorized_request", fake_authorized_request)

    result = client.heartbeat(
        {"status": "online", "currentTaskId": "task-123"}
    )

    assert result.ok is True
    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/runtime/heartbeat"
    assert captured["token_kind"] == "runtime"
    assert captured["refresh_on_401"] is False
    assert captured["json"]["status"] == "online"
    assert captured["json"]["currentTaskId"] == "task-123"
    assert captured["json"]["capabilities"] == sorted(capability_names())
    assert state_store.snapshot()["runtime"]["currentTaskId"] == "task-123"
    assert state_store.snapshot()["runtime"]["capabilities"] == sorted(capability_names())


def test_heartbeat_uses_dependency_aware_capability_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state_store.update_state(
        {
            "runtime": {
                "runtimeToken": "runtime-token",
                "deviceId": VALID_DEVICE_ID,
                "deviceSecret": VALID_DEVICE_SECRET,
            }
        }
    )
    client = BackendClient(
        "http://backend.example",
        capabilities_provider=lambda: [
            "runtime.status",
            "email_draft",
            "runtime.status",
        ],
    )
    captured: dict[str, Any] = {}

    def fake_authorized_request(
        _method: str,
        _path: str,
        json_body: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> BackendResult:
        captured["json"] = dict(json_body or {})
        return BackendResult(ok=True, request_id="req_heartbeat", status_code=200, data={"ok": True})

    monkeypatch.setattr(client, "_authorized_request", fake_authorized_request)

    result = client.heartbeat({"status": "online"})

    assert result.ok is True
    assert captured["json"]["capabilities"] == ["email_draft", "runtime.status"]
    assert state_store.snapshot()["runtime"]["capabilities"] == ["email_draft", "runtime.status"]


def test_runtime_session_normalizes_backend_readiness_truth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state_store.update_state(
        {
            "runtime": {
                "runtimeToken": "runtime-token",
                "deviceId": VALID_DEVICE_ID,
                "deviceSecret": VALID_DEVICE_SECRET,
                "ready": False,
                "lifecycleState": "runtime_connecting",
                "websocketConnected": False,
            }
        }
    )
    client = BackendClient("http://backend.example")

    monkeypatch.setattr(
        client,
        "_authorized_request",
        lambda *_args, **_kwargs: BackendResult(
            ok=True,
            request_id="req_runtime_session",
            status_code=200,
            data={
                "readiness": {
                    "targetStatus": "ready",
                    "canReceiveTasks": True,
                    "capabilities": ["email_draft", "web_research"],
                    "runtime": {"lastHeartbeatAt": "2030-05-22T15:30:00Z"},
                },
                "connection": {
                    "status": "online",
                    "currentTaskId": "task-runtime-42",
                    "lastHeartbeatAt": "2030-05-22T15:30:00Z",
                    "capabilityStates": {
                        "local_models.api": {
                            "available": True,
                            "ready": True,
                            "stats": {"defaultLocalModel": "llama3.1:8b"},
                        }
                    },
                },
                "capabilitySummary": {
                    "total": 2,
                    "categories": {"runtime": 0, "task": 0, "browser": 0, "computer": 0, "file": 0, "document": 0, "model": 0, "quantum": 0, "automation": 0, "connector": 0, "other": 2},
                },
            },
            x_request_id="req-server-runtime-session",
        ),
    )

    result = client.runtime_session()

    state = state_store.snapshot()
    assert result.ok is True
    assert state["runtime"]["ready"] is True
    assert state["runtime"]["lifecycleState"] == "ready"
    assert state["runtime"]["websocketConnected"] is True
    assert state["runtime"]["currentTaskId"] == "task-runtime-42"
    assert state["runtime"]["capabilities"] == ["email_draft", "web_research"]
    assert state["runtime"]["capabilityStates"] == {
        "local_models.api": {
            "available": True,
            "ready": True,
            "stats": {"defaultLocalModel": "llama3.1:8b"},
        }
    }
    assert state["pairing"]["realtimeReady"] is True
    assert state["pairing"]["lastHeartbeatAt"] == "2030-05-22T15:30:00Z"
    assert state["controlPlane"]["runtimeSession"]["readiness"]["targetStatus"] == "ready"
    assert state["controlPlane"]["runtimeSession"]["readiness"]["canReceiveTasks"] is True


def test_runtime_session_failure_marks_runtime_reconnecting_without_clearing_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state_store.update_state(
        {
            "runtime": {
                "runtimeToken": "runtime-token",
                "deviceId": VALID_DEVICE_ID,
                "deviceSecret": VALID_DEVICE_SECRET,
                "connectionId": VALID_CONNECTION_ID,
                "ready": True,
                "lifecycleState": "ready",
                "websocketConnected": True,
            },
            "pairing": {"realtimeReady": True, "lastHeartbeatAt": "2030-05-22T15:30:00Z"},
        }
    )
    client = BackendClient("http://backend.example")

    monkeypatch.setattr(
        client,
        "_authorized_request",
        lambda *_args, **_kwargs: BackendResult(
            ok=False,
            request_id="req_runtime_session_failed",
            status_code=503,
            data={"error": "runtime session unavailable"},
            error="runtime session unavailable",
        ),
    )

    result = client.runtime_session()

    state = state_store.snapshot()
    assert result.ok is False
    assert state["runtime"]["runtimeToken"] == "runtime-token"
    assert state["runtime"]["deviceId"] == VALID_DEVICE_ID
    assert state["runtime"]["deviceSecret"] == VALID_DEVICE_SECRET
    assert state["runtime"]["lifecycleState"] == "reconnecting"
    assert state["runtime"]["ready"] is False
    assert state["runtime"]["websocketConnected"] is False
    assert state["runtime"]["lastErrorCode"] == "runtime_session_unavailable"
    assert state["pairing"]["realtimeReady"] is False
    assert state["pairing"]["lastHeartbeatAt"] == ""


def test_runtime_tasks_assigned_unauthorized_clears_runtime_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state_store.update_state(
        {
            "runtime": {
                "runtimeToken": "runtime-token",
                "deviceId": VALID_DEVICE_ID,
                "deviceSecret": VALID_DEVICE_SECRET,
                "connectionId": VALID_CONNECTION_ID,
                "ready": True,
                "lifecycleState": "ready",
                "websocketConnected": True,
            },
            "pairing": {"realtimeReady": True, "lastHeartbeatAt": "2030-05-22T15:30:00Z"},
        }
    )
    client = BackendClient("http://backend.example")

    monkeypatch.setattr(
        client,
        "_authorized_request",
        lambda *_args, **_kwargs: BackendResult(
            ok=False,
            request_id="req_runtime_tasks",
            status_code=401,
            data={"error": "stale_runtime"},
            error="stale_runtime",
        ),
    )

    result = client.runtime_tasks_assigned()

    state = state_store.snapshot()
    assert result.ok is False
    assert result.status_code == 401
    assert state["runtime"]["runtimeToken"] == ""
    assert state["runtime"]["connectionId"] == ""
    assert state["runtime"]["lastErrorCode"] == "runtime_unauthorized"
    assert state["pairing"]["realtimeReady"] is False


def test_logout_preserves_paired_runtime_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state_store.update_state({"pairing": {"externalDeviceId": "desktop-ext-logout"}})
    external_device_id = state_store.snapshot()["pairing"]["externalDeviceId"]
    state_store.update_state(
        {
            "account": {
                "accessToken": "user-token",
                "refreshToken": "refresh-token",
                "email": "user@example.com",
            },
            "runtime": {
                "runtimeToken": "runtime-token",
                "deviceId": VALID_DEVICE_ID,
                "deviceSecret": VALID_DEVICE_SECRET,
                "connectionId": VALID_CONNECTION_ID,
                "ready": True,
            },
            "pairing": {
                "lastSessionId": "session-1",
                "desktopDeviceId": VALID_DEVICE_ID,
                "pairingToken": "pair-token",
                "pairingCode": "PWGSFB5B",
                "qrText": "elyan://pair?sessionId=session-1&pairingCode=PWGSFB5B",
                "expiresAt": "2030-05-22T15:30:00Z",
                "lastSessionStatus": "pending",
                "lastErrorCode": "PAIRING_SESSION_EXPIRED",
            },
        }
    )
    client = BackendClient("http://backend.example")

    monkeypatch.setattr(
        client,
        "_authorized_request",
        lambda *_args, **_kwargs: BackendResult(
            ok=True,
            request_id="req_logout",
            status_code=200,
            data={"ok": True},
        ),
    )

    result = client.auth_logout()

    state = state_store.snapshot()
    assert result.ok is True
    assert state["account"]["accessToken"] == ""
    assert state["account"]["refreshToken"] == ""
    assert state["runtime"]["runtimeToken"] == ""
    assert state["runtime"]["deviceId"] == VALID_DEVICE_ID
    assert state["runtime"]["deviceSecret"] == VALID_DEVICE_SECRET
    assert state["runtime"]["ready"] is False
    assert state["pairing"]["lastSessionId"] == ""
    assert state["pairing"]["desktopDeviceId"] == ""
    assert state["pairing"]["pairingToken"] == ""
    assert state["pairing"]["pairingCode"] == ""
    assert state["pairing"]["externalDeviceId"] == external_device_id
    assert state["pairing"]["qrText"] == ""
    assert state["pairing"]["expiresAt"] == ""
    assert state["pairing"]["lastSessionStatus"] == ""
    assert state["pairing"]["lastErrorCode"] == ""


def test_register_runtime_uses_device_secret_payload_without_user_bearer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state_store.update_state(
        {
            "account": {"accessToken": "user-token"},
            "runtime": {
                "deviceId": VALID_DEVICE_ID,
                "deviceSecret": VALID_DEVICE_SECRET,
            },
        }
    )
    client = BackendClient("http://backend.example")
    captured: dict[str, Any] = {}

    def fake_request(method: str, path: str, json_body: dict[str, Any] | None = None, **kwargs: Any) -> BackendResult:
        captured["method"] = method
        captured["path"] = path
        captured["json"] = json_body
        captured["headers"] = kwargs.get("headers")
        return BackendResult(
            ok=True,
            request_id="req_register",
            status_code=200,
            data={
                "runtime": {"deviceId": VALID_DEVICE_ID, "connectionId": VALID_CONNECTION_ID},
                "tokens": {"accessToken": "runtime-token"},
            },
            x_request_id="req-server-register",
        )

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.register_runtime(
        {
            "deviceId": VALID_DEVICE_ID,
            "deviceSecret": VALID_DEVICE_SECRET,
            "capabilities": [],
        }
    )

    state = state_store.snapshot()
    assert result.ok is True
    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/runtime/register"
    assert captured["headers"] is None
    assert captured["json"]["deviceId"] == VALID_DEVICE_ID
    assert captured["json"]["deviceSecret"] == VALID_DEVICE_SECRET
    assert isinstance(captured["json"]["capabilities"], list)
    assert captured["json"]["capabilities"] == sorted(capability_names())
    assert state["runtime"]["runtimeToken"] == "runtime-token"
    assert state["runtime"]["lastXRequestId"] == "req-server-register"
    assert state["runtime"]["capabilities"] == sorted(capability_names())


def test_register_runtime_rejects_invalid_identity_before_backend_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state_store.update_state(
        {
            "runtime": {
                "deviceId": "desktop-ext-stale",
                "deviceSecret": "short-secret",
            },
            "pairing": {
                "lastSessionId": "session-1",
                "desktopDeviceId": VALID_DEVICE_ID,
                "lastSessionStatus": "claimed",
            },
        }
    )
    client = BackendClient("http://backend.example")

    def fake_request(*_args: Any, **_kwargs: Any) -> BackendResult:
        raise AssertionError("register_runtime should not call backend when identity is invalid")

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.register_runtime(
        {
            "deviceId": VALID_DEVICE_ID,
            "deviceSecret": VALID_DEVICE_SECRET,
            "capabilities": [],
        }
    )

    state = state_store.snapshot()
    assert result.ok is False
    assert result.error == "runtime_register_invalid_identity"
    assert state["runtime"]["runtimeToken"] == ""
    assert state["runtime"]["deviceId"] == ""
    assert state["runtime"]["deviceSecret"] == ""
    assert state["runtime"]["lifecycleState"] == "offline"
    assert state["runtime"]["lastErrorCode"] == "runtime_register_invalid_identity"
    assert state["pairing"]["lastSessionId"] == ""
    assert state["pairing"]["desktopDeviceId"] == ""
    assert state["pairing"]["lastErrorCode"] == "runtime_register_invalid_identity"


def test_runtime_register_identity_error_rejects_non_uuid_or_mismatched_pairing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    client = BackendClient("http://backend.example")

    state_store.update_state(
        {
            "pairing": {"desktopDeviceId": "11111111-1111-4111-8111-111111111111"},
            "runtime": {
                "deviceId": "desktop-ext-1",
                "deviceSecret": "short-secret",
            },
        }
    )

    error = client.runtime_register_identity_error()

    assert error == {
        "code": "RUNTIME_REGISTER_INVALID_IDENTITY",
        "message": "Runtime kimliği geçersiz.",
    }


def test_repair_invalid_runtime_identity_clears_stale_runtime_and_pairing_truth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state_store.update_state(
        {
            "pairing": {
                "lastSessionId": "session-1",
                "desktopDeviceId": VALID_DEVICE_ID,
                "pairingToken": "pair-token",
                "pairingCode": "PWGSFB5B",
                "qrText": "elyan://pair?sessionId=session-1&pairingCode=PWGSFB5B",
                "expiresAt": "2030-05-22T15:30:00Z",
                "lastSessionStatus": "claimed",
                "realtimeReady": True,
                "lastHeartbeatAt": "2030-05-22T15:30:00Z",
            },
            "runtime": {
                "runtimeToken": "runtime-token",
                "deviceId": "device-1",
                "deviceSecret": "short",
                "connectionId": "connection-1",
                "ready": True,
                "lifecycleState": "ready",
                "websocketConnected": True,
            },
        }
    )
    client = BackendClient("http://backend.example")

    client.repair_invalid_runtime_identity("RUNTIME_REGISTER_INVALID_IDENTITY")

    state = state_store.snapshot()
    assert state["runtime"]["runtimeToken"] == ""
    assert state["runtime"]["deviceId"] == ""
    assert state["runtime"]["deviceSecret"] == ""
    assert state["runtime"]["connectionId"] == ""
    assert state["runtime"]["ready"] is False
    assert state["runtime"]["lifecycleState"] == "offline"
    assert state["runtime"]["lastErrorCode"] == "runtime_register_invalid_identity"
    assert state["pairing"]["lastSessionId"] == ""
    assert state["pairing"]["desktopDeviceId"] == ""
    assert state["pairing"]["qrText"] == ""
    assert state["pairing"]["realtimeReady"] is False
    assert state["pairing"]["lastErrorCode"] == "runtime_register_invalid_identity"


def test_tasks_list_uses_user_auth_surface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    client = BackendClient("http://backend.example")
    captured: dict[str, Any] = {}

    def fake_authorized_request(
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        *,
        token_kind: str = "user",
        refresh_on_401: bool = False,
    ) -> BackendResult:
        captured["method"] = method
        captured["path"] = path
        captured["json"] = json_body
        captured["token_kind"] = token_kind
        captured["refresh_on_401"] = refresh_on_401
        return BackendResult(ok=True, request_id="req_tasks", status_code=200, data={"tasks": []})

    monkeypatch.setattr(client, "_authorized_request", fake_authorized_request)

    result = client.tasks_list(limit=12, status="queued,waiting_approval")

    assert result.ok is True
    assert captured["method"] == "GET"
    assert captured["path"] == "/v1/tasks?limit=12&status=queued,waiting_approval"
    assert captured["json"] is None
    assert captured["token_kind"] == "user"
    assert captured["refresh_on_401"] is True


def test_task_detail_and_approval_use_existing_user_routes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    client = BackendClient("http://backend.example")
    captured: list[tuple[str, str, dict[str, Any] | None, str, bool]] = []

    def fake_authorized_request(
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        *,
        token_kind: str = "user",
        refresh_on_401: bool = False,
    ) -> BackendResult:
        captured.append((method, path, json_body, token_kind, refresh_on_401))
        return BackendResult(ok=True, request_id="req_task", status_code=200, data={"ok": True})

    monkeypatch.setattr(client, "_authorized_request", fake_authorized_request)

    detail = client.task_detail("task-123")
    approval = client.task_approval("task-123", True, "Tamam")

    assert detail.ok is True
    assert approval.ok is True
    assert captured == [
        ("GET", "/v1/tasks/task-123", None, "user", True),
        ("POST", "/v1/tasks/task-123/approval", {"approved": True, "notes": "Tamam"}, "user", True),
    ]


def test_brain_profile_uses_user_auth_surface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    client = BackendClient("http://backend.example")
    captured: dict[str, Any] = {}

    def fake_authorized_request(
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        *,
        token_kind: str = "user",
        refresh_on_401: bool = False,
    ) -> BackendResult:
        captured["method"] = method
        captured["path"] = path
        captured["json"] = json_body
        captured["token_kind"] = token_kind
        captured["refresh_on_401"] = refresh_on_401
        return BackendResult(ok=True, request_id="req_brain", status_code=200, data={"chat": {}})

    monkeypatch.setattr(client, "_authorized_request", fake_authorized_request)

    result = client.brain_profile()

    assert result.ok is True
    assert captured == {
        "method": "GET",
        "path": "/v1/brain/profile",
        "json": None,
        "token_kind": "user",
        "refresh_on_401": True,
    }


def test_health_truth_is_cached_into_control_plane_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    client = BackendClient("http://backend.example")

    client._apply_health_truth(
        {
            "ok": True,
            "database": {
                "status": "up",
                "reachability": {"host": "db.example", "port": 5432},
            },
            "network": {"externalClientsCanReachAdvertisedBaseUrl": True},
            "agent": {"chatReady": True, "serverBrainReady": True},
            "dependencies": {
                "billing": {
                    "status": "ready",
                    "checkoutEnabled": True,
                }
            },
        }
    )

    state = state_store.snapshot()
    assert state["billing"]["iyzicoStatus"] == "ready"
    assert state["billing"]["checkoutEnabled"] is True
    assert state["controlPlane"]["health"]["database"]["status"] == "up"
    assert state["controlPlane"]["health"]["agent"]["serverBrainReady"] is True


def test_brain_profile_truth_is_cached_into_control_plane_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state_store.update_state({"account": {"accessToken": "user-token"}})
    client = BackendClient("http://backend.example")

    def fake_authorized_request(
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        *,
        token_kind: str = "user",
        refresh_on_401: bool = False,
    ) -> BackendResult:
        assert method == "GET"
        assert path == "/v1/brain/profile"
        assert json_body is None
        assert token_kind == "user"
        assert refresh_on_401 is True
        return BackendResult(
            ok=True,
            request_id="req_brain",
            status_code=200,
            data={
                "chat": {
                    "serverBrainName": "Elyan",
                    "isChatUsable": True,
                }
            },
        )

    monkeypatch.setattr(client, "_authorized_request", fake_authorized_request)

    result = client.brain_profile()

    assert result.ok is True
    state = state_store.snapshot()
    assert state["controlPlane"]["brainProfile"]["chat"]["serverBrainName"] == "Elyan"


def test_subscription_truth_preserves_brain_profile_and_plan_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    client = BackendClient("http://backend.example")

    client._apply_subscription_truth(
        {
            "subscription": {
                "planCode": "pro",
                "status": "active",
                "aiCreditsMonthly": 2500,
                "taskLimitMonthly": 250,
                "periodEndsAt": "2026-07-01T00:00:00Z",
                "brainProfile": {
                    "chat": {
                        "reasoningMultiplier": 5,
                        "tier": "premium",
                    }
                },
                "billingProvider": "apple_store",
                "subscriptionSource": "store",
            }
        }
    )

    state = state_store.snapshot()
    assert state["billing"]["planCode"] == "pro"
    assert state["billing"]["status"] == "active"
    assert state["billing"]["brainProfile"]["chat"]["reasoningMultiplier"] == 5
    assert state["account"]["subscription"]["billingProvider"] == "apple_store"
    assert state["account"]["subscription"]["subscriptionSource"] == "store"


def test_auth_oauth_login_posts_to_provider_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    client = BackendClient("http://backend.example")
    captured: dict[str, Any] = {}

    def fake_request(
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
        request_id: str | None = None,
    ) -> BackendResult:
        captured["method"] = method
        captured["path"] = path
        captured["json_body"] = json_body
        captured["request_id"] = request_id
        return BackendResult(
            ok=True,
            request_id=request_id or "req_oauth",
            status_code=200,
            data={
                "user": {"email": "user@example.com", "displayName": "Emre"},
                "subscription": {
                    "planCode": "solo",
                    "status": "active",
                    "aiCreditsMonthly": 1000,
                    "taskLimitMonthly": 100,
                    "periodEndsAt": "2026-07-01T00:00:00Z",
                    "brainProfile": {"chat": {"tier": "standard"}},
                },
                "tokens": {"accessToken": "user-token", "refreshToken": "refresh-token"},
            },
        )

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.auth_oauth_login(
        "google",
        "google-id-token",
        email="user@example.com",
        display_name="Emre",
        authorization_code="auth-code",
    )

    assert result.ok is True
    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/auth/oauth/google"
    assert captured["json_body"] == {
        "idToken": "google-id-token",
        "email": "user@example.com",
        "displayName": "Emre",
        "authorizationCode": "auth-code",
    }
    state = state_store.snapshot()
    assert state["account"]["accessToken"] == "user-token"
    assert state["account"]["subscription"]["planCode"] == "solo"


def test_chat_messages_uses_user_auth_surface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    client = BackendClient("http://backend.example")
    captured: dict[str, Any] = {}

    def fake_authorized_request(
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        *,
        token_kind: str = "user",
        refresh_on_401: bool = False,
    ) -> BackendResult:
        captured["method"] = method
        captured["path"] = path
        captured["json_body"] = json_body
        captured["token_kind"] = token_kind
        captured["refresh_on_401"] = refresh_on_401
        return BackendResult(
            ok=True,
            request_id="req_chat",
            status_code=200,
            data={
                "assistantMessage": {"role": "assistant", "content": "Merhaba"},
                "brain": {"serverBrainReady": True, "provider": "server_brain"},
            },
        )

    monkeypatch.setattr(client, "_authorized_request", fake_authorized_request)

    result = client.chat_messages(
        {
            "title": "Selam",
            "content": "Selam",
            "source": "desktop",
            "requestedCapabilities": [],
        }
    )

    assert result.ok is True
    assert captured == {
        "method": "POST",
        "path": "/v1/chat/messages",
        "json_body": {
            "title": "Selam",
            "content": "Selam",
            "source": "desktop",
            "requestedCapabilities": [],
        },
        "token_kind": "user",
        "refresh_on_401": True,
    }


def test_brain_retrieval_search_uses_user_auth_surface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    client = BackendClient("http://backend.example")
    captured: dict[str, Any] = {}

    def fake_authorized_request(
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        *,
        token_kind: str = "user",
        refresh_on_401: bool = False,
    ) -> BackendResult:
        captured["method"] = method
        captured["path"] = path
        captured["json"] = json_body
        captured["token_kind"] = token_kind
        captured["refresh_on_401"] = refresh_on_401
        return BackendResult(ok=False, request_id="req_brain_search", status_code=503, data={"error": "unavailable"}, error="unavailable")

    monkeypatch.setattr(client, "_authorized_request", fake_authorized_request)

    result = client.brain_retrieval_search({"query": "elyan", "limit": 4})

    assert result.ok is False
    assert result.status_code == 503
    assert captured == {
        "method": "POST",
        "path": "/v1/brain/retrieval/search",
        "json": {"query": "elyan", "limit": 4},
        "token_kind": "user",
        "refresh_on_401": True,
    }


def test_brain_knowledge_document_uses_user_auth_surface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    client = BackendClient("http://backend.example")
    captured: dict[str, Any] = {}

    def fake_authorized_request(
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        *,
        token_kind: str = "user",
        refresh_on_401: bool = False,
    ) -> BackendResult:
        captured["method"] = method
        captured["path"] = path
        captured["json"] = json_body
        captured["token_kind"] = token_kind
        captured["refresh_on_401"] = refresh_on_401
        return BackendResult(ok=False, request_id="req_publish", status_code=401, data={"error": "expired"}, error="expired")

    monkeypatch.setattr(client, "_authorized_request", fake_authorized_request)

    result = client.brain_knowledge_document({"title": "Doc", "content": "hello"})

    assert result.ok is False
    assert result.status_code == 401
    assert captured == {
        "method": "POST",
        "path": "/v1/brain/knowledge/documents",
        "json": {"title": "Doc", "content": "hello"},
        "token_kind": "user",
        "refresh_on_401": True,
    }


def test_brain_profile_network_errors_are_normalized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state_store.update_state({"account": {"accessToken": "user-token"}})
    client = BackendClient("http://backend.example")

    class FakeSession:
        def request(self, *_args: Any, **_kwargs: Any) -> BackendResult:
            raise requests.ConnectionError("boom")

    monkeypatch.setattr(client, "_session_for_thread", lambda: FakeSession())

    result = client.brain_profile()

    assert result.ok is False
    assert result.status_code is None
    assert result.error == "network_unreachable"
