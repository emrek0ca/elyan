from __future__ import annotations

import asyncio
import contextvars
import threading
import time
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path

import pytest

from runtime import bridge, state_store
from runtime import mcp_runtime
import runtime.capability_registry as registry


def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(state_store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(state_store, "STATE_PATH", tmp_path / "elyan_state.json")
    monkeypatch.setattr(state_store, "LEGACY_STATE_PATH", tmp_path / "legacy.json")
    mcp_runtime.set_remote_server_provider(None)


def test_streamable_http_config_accepts_trusted_remote_endpoint() -> None:
    config = mcp_runtime.normalize_server_config(
        {
            "id": "app_gmail",
            "name": "Gmail",
            "transport": "streamable_http",
            "url": "https://gmailmcp.googleapis.com/mcp/v1",
            "authType": "bearer",
            "accessToken": "ephemeral-token",
        }
    )

    assert config["transport"] == "streamable_http"
    assert config["url"] == "https://gmailmcp.googleapis.com/mcp/v1"
    assert config["authType"] == "bearer"


def test_planner_schema_summary_marks_required_enum_and_nested_args() -> None:
    summary = mcp_runtime._planner_schema_summary(
        {
            "properties": {
                "owner": {"type": "string", "description": "Repo sahibi"},
                "state": {"type": "string", "enum": ["open", "closed", "all"]},
                "filters": {
                    "type": "object",
                    "properties": {
                        "labels": {"type": "array"},
                        "assignee": {"type": "string"},
                    },
                },
            },
            "required": ["owner"],
        }
    )

    assert "owner!:string" in summary
    assert "state:string enum=open|closed|all" in summary
    assert "filters:object{labels,assignee}" in summary


def test_planner_prompt_context_uses_rich_mcp_schema_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = mcp_runtime.MCPRuntimeManager()
    monkeypatch.setattr(
        manager,
        "list_tools",
        lambda _state, refresh=False: {
            "tools": [
                {
                    "serverId": "app_github",
                    "name": "list_issues",
                    "description": "Repository issue listesini döndürür.",
                    "readOnly": True,
                    "inputSchema": {
                        "properties": {
                            "owner": {"type": "string"},
                            "state": {"type": "string", "enum": ["open", "closed", "all"]},
                            "filters": {"type": "object", "properties": {"labels": {"type": "array"}}},
                        },
                        "required": ["owner"],
                    },
                }
            ]
        },
    )

    context = manager.planner_prompt_context({})

    assert "serverId=app_github toolName=list_issues" in context
    assert "schema=owner!:string, state:string enum=open|closed|all, filters:object{labels}" in context


def test_user_local_streamable_http_config_remains_separate_from_control_plane_catalog() -> None:
    config = mcp_runtime.normalize_server_config(
        {
            "id": "user_remote",
            "name": "User remote",
            "transport": "streamable_http",
            "url": "https://example.com/custom-mcp",
        }
    )

    assert config["url"] == "https://example.com/custom-mcp"
    assert config.get("_controlPlaneRemote") is None


@pytest.mark.parametrize(
    "url",
    [
        "http://gmailmcp.googleapis.com/mcp/v1",
        "https://127.0.0.1/mcp/v1",
        "https://evil.example/mcp/v1",
        "https://user@gmailmcp.googleapis.com/mcp/v1",
        "https://gmailmcp.googleapis.com:444/mcp/v1",
        "https://gmailmcp.googleapis.com/mcp/v1?redirect=1",
        "https://gmailmcp.googleapis.com/mcp/v1#fragment",
    ],
)
def test_control_plane_rejects_untrusted_remote_mcp_urls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    url: str,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    mcp_runtime.set_remote_server_provider(
        lambda: {
            "servers": [
                {
                    "id": "app_gmail",
                    "appId": "gmail",
                    "provider": "google",
                    "name": "Gmail",
                    "transport": "streamable_http",
                    "url": url,
                    "authType": "bearer",
                    "accessToken": "ephemeral-token",
                }
            ],
            "revision": "malicious",
        }
    )

    status = mcp_runtime.refresh_mcp_runtime(state_store.snapshot())

    assert status["serverCount"] == 0
    assert status["degraded"] is True
    assert status["lastErrorCode"] == "MCP_CONTROL_PLANE_INVALID"


def test_control_plane_rejects_trusted_hostname_resolving_to_private_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = mcp_runtime.normalize_server_config(
        {
            "id": "app_gmail",
            "appId": "gmail",
            "provider": "google",
            "name": "Gmail",
            "transport": "streamable_http",
            "url": "https://gmailmcp.googleapis.com/mcp/v1",
            "authType": "bearer",
            "accessToken": "ephemeral-token",
        },
        source="control_plane",
    )
    monkeypatch.setattr(
        mcp_runtime.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (mcp_runtime.socket.AF_INET, mcp_runtime.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )

    with pytest.raises(registry.SafeCapabilityError) as exc_info:
        asyncio.run(mcp_runtime._validate_control_plane_resolution(server))

    assert exc_info.value.code == "MCP_SERVER_INVALID"


def test_control_plane_dns_timeout_does_not_block_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = mcp_runtime.normalize_server_config(
        {
            "id": "app_gmail",
            "appId": "gmail",
            "provider": "google",
            "name": "Gmail",
            "transport": "streamable_http",
            "url": "https://gmailmcp.googleapis.com/mcp/v1",
        },
        source="control_plane",
    )
    monkeypatch.setattr(mcp_runtime, "_CONTROL_PLANE_DNS_TIMEOUT_SECONDS", 0.05)

    def slow_resolution(*_args: object, **_kwargs: object) -> list[object]:
        time.sleep(0.3)
        return []

    monkeypatch.setattr(mcp_runtime.socket, "getaddrinfo", slow_resolution)
    started = time.monotonic()

    with pytest.raises(registry.SafeCapabilityError) as exc_info:
        asyncio.run(mcp_runtime._validate_control_plane_resolution(server))

    assert time.monotonic() - started < 0.2
    assert exc_info.value.code == "MCP_SERVER_UNAVAILABLE"


def test_control_plane_session_rejects_stale_provider_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    mcp_runtime.set_remote_server_provider(
        lambda: {
            "servers": [
                {
                    "id": "app_gmail",
                    "appId": "gmail",
                    "provider": "google",
                    "name": "Gmail",
                    "transport": "streamable_http",
                    "url": "https://gmailmcp.googleapis.com/mcp/v1",
                    "authType": "bearer",
                    "accessToken": "ephemeral-token",
                }
            ],
            "revision": "rev_a",
        }
    )
    servers, _status, _generation = mcp_runtime._remote_server_snapshot()
    assert len(servers) == 1

    mcp_runtime.set_remote_server_provider(None)

    with pytest.raises(registry.SafeCapabilityError) as exc_info:
        mcp_runtime._validate_control_plane_provider_generation(servers[0])

    assert exc_info.value.code == "MCP_CONTROL_PLANE_CHANGED"


def test_streamable_http_client_disables_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mcp_module = pytest.importorskip("mcp")
    httpx_module = pytest.importorskip("httpx")
    streamable_module = import_module("mcp.client.streamable_http")
    captured: dict[str, object] = {}

    class FakeHttpClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        async def __aenter__(self) -> "FakeHttpClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FakeSession:
        def __init__(self, *_args: object) -> None:
            pass

        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def initialize(self) -> None:
            return None

    @asynccontextmanager
    async def fake_streamable_client(_url: str, *, http_client: object):
        captured["httpClient"] = http_client
        yield object(), object(), None

    async def operation(_session: object) -> str:
        return "ok"

    monkeypatch.setattr(httpx_module, "AsyncClient", FakeHttpClient)
    monkeypatch.setattr(mcp_module, "ClientSession", FakeSession)
    monkeypatch.setattr(streamable_module, "streamable_http_client", fake_streamable_client)
    async def skip_resolution(_server: dict[str, object]) -> None:
        return None

    monkeypatch.setattr(mcp_runtime, "_validate_control_plane_resolution", skip_resolution)
    server = mcp_runtime.normalize_server_config(
        {
            "id": "app_gmail",
            "appId": "gmail",
            "provider": "google",
            "name": "Gmail",
            "transport": "streamable_http",
            "url": "https://gmailmcp.googleapis.com/mcp/v1",
            "authType": "bearer",
            "accessToken": "ephemeral-token",
        },
        source="control_plane",
    )
    server["_remoteProviderGeneration"] = mcp_runtime._remote_provider_generation()

    result = asyncio.run(mcp_runtime.MCPRuntimeManager()._with_session(server, operation))

    assert result == "ok"
    assert captured["follow_redirects"] is False


def test_remote_provider_auth_failure_is_visible_without_persisting_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    mcp_runtime.set_remote_server_provider(
        lambda: [
            {
                "id": "app_gmail",
                "appId": "gmail",
                "provider": "google",
                "name": "Gmail",
                "transport": "streamable_http",
                "url": "https://gmailmcp.googleapis.com/mcp/v1",
                "authType": "bearer",
                "accessToken": "",
                "authErrorCode": "MCP_AUTH_REQUIRED",
            }
        ]
    )

    status = mcp_runtime.refresh_mcp_runtime(state_store.snapshot())

    assert status["serverCount"] == 1
    assert status["servers"][0]["appId"] == "gmail"
    assert status["servers"][0]["lastErrorCode"] == "MCP_AUTH_REQUIRED"
    assert "accessToken" not in status["servers"][0]


def test_remote_catalog_refreshes_after_bounded_ttl(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    snapshot: dict[str, object] = {
        "servers": [
            {
                "id": "app_gmail",
                "appId": "gmail",
                "provider": "google",
                "name": "Gmail",
                "transport": "streamable_http",
                "url": "https://gmailmcp.googleapis.com/mcp/v1",
                "authType": "bearer",
                "authErrorCode": "MCP_AUTH_REQUIRED",
            }
        ],
        "revision": "rev_1",
    }
    mcp_runtime.set_remote_server_provider(lambda: snapshot)
    first = mcp_runtime.refresh_mcp_runtime(state_store.snapshot())
    assert first["serverCount"] == 1

    snapshot = {"servers": [], "revision": "rev_2"}
    monkeypatch.setattr(mcp_runtime, "_REMOTE_REFRESH_TTL_SECONDS", 0.0)
    refreshed = mcp_runtime.list_mcp_tools(state_store.snapshot(), refresh=False)

    assert refreshed["serverCount"] == 0
    assert refreshed["remoteRevision"] == "rev_2"


def test_concurrent_refresh_keeps_remote_revision_paired_with_its_inventory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    payloads = [
        {
            "servers": [
                {
                    "id": "app_gmail",
                    "appId": "gmail",
                    "provider": "google",
                    "name": "Gmail",
                    "transport": "streamable_http",
                    "url": "https://gmailmcp.googleapis.com/mcp/v1",
                    "authType": "bearer",
                    "accessToken": "token-a",
                }
            ],
            "revision": "rev_a",
        },
        {
            "servers": [
                {
                    "id": "app_google-drive",
                    "appId": "google-drive",
                    "provider": "google",
                    "name": "Google Drive",
                    "transport": "streamable_http",
                    "url": "https://drivemcp.googleapis.com/mcp/v1",
                    "authType": "bearer",
                    "accessToken": "token-b",
                }
            ],
            "revision": "rev_b",
        },
    ]
    provider_lock = threading.Lock()
    provider_calls = 0

    def provider() -> dict[str, object]:
        nonlocal provider_calls
        with provider_lock:
            index = min(provider_calls, len(payloads) - 1)
            provider_calls += 1
        return payloads[index]

    first_discovery_started = threading.Event()
    release_first_discovery = threading.Event()

    async def fake_list_tools(server: dict[str, object]) -> list[dict[str, object]]:
        if server.get("id") == "app_gmail":
            first_discovery_started.set()
            assert release_first_discovery.wait(1.0)
        return [{"serverId": server.get("id"), "name": "search", "inputSchema": {}}]

    manager = mcp_runtime.MCPRuntimeManager()
    monkeypatch.setattr(mcp_runtime, "_module_available", lambda _module_name: True)
    monkeypatch.setattr(manager, "_list_tools_for_server", fake_list_tools)
    mcp_runtime.set_remote_server_provider(provider)
    results: dict[str, dict[str, object]] = {}

    def refresh(name: str) -> None:
        results[name] = manager.refresh(state_store.snapshot())

    first = threading.Thread(target=refresh, args=("first",), daemon=True)
    second = threading.Thread(target=refresh, args=("second",), daemon=True)
    try:
        first.start()
        assert first_discovery_started.wait(1.0)
        second.start()
        time.sleep(0.05)
        release_first_discovery.set()
        first.join(2.0)
        second.join(2.0)

        assert not first.is_alive()
        assert not second.is_alive()
        assert results["first"]["servers"][0]["id"] == "app_gmail"
        assert results["first"]["remoteRevision"] == "rev_a"
        assert results["second"]["servers"][0]["id"] == "app_google-drive"
        assert results["second"]["remoteRevision"] == "rev_b"
        assert manager.status()["remoteRevision"] == "rev_b"
    finally:
        release_first_discovery.set()
        mcp_runtime.set_remote_server_provider(None)


def test_remote_control_plane_failure_is_reported_as_degraded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    mcp_runtime.set_remote_server_provider(
        lambda: {
            "servers": [],
            "errorCode": "MCP_CONTROL_PLANE_AUTH_REQUIRED",
            "errorMessage": "Masaüstü oturumunu yeniden bağla.",
            "revision": "",
        }
    )

    status = mcp_runtime.refresh_mcp_runtime(state_store.snapshot())

    assert status["degraded"] is True
    assert status["lastErrorCode"] == "MCP_CONTROL_PLANE_AUTH_REQUIRED"


def test_local_servers_do_not_consume_curated_remote_server_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    monkeypatch.setattr(mcp_runtime, "_module_available", lambda _module_name: False)
    state = state_store.snapshot()
    state["skills"]["mcpServers"] = [
        {
            "id": f"local_{index}",
            "name": f"Local {index}",
            "transport": "stdio",
            "command": "python3",
            "cwd": str(tmp_path),
            "enabled": True,
        }
        for index in range(12)
    ]
    remote_specs = [
        ("gmail", "google", "https://gmailmcp.googleapis.com/mcp/v1"),
        ("google-drive", "google", "https://drivemcp.googleapis.com/mcp/v1"),
        ("google-calendar", "google", "https://calendarmcp.googleapis.com/mcp/v1"),
        ("notion", "notion", "https://mcp.notion.com/mcp"),
        ("linear", "linear", "https://mcp.linear.app/mcp"),
        ("github", "github", "https://api.githubcopilot.com/mcp/"),
        ("slack", "slack", "https://mcp.slack.com/mcp"),
    ]
    mcp_runtime.set_remote_server_provider(
        lambda: {
            "servers": [
                {
                    "id": f"app_{app_id}",
                    "appId": app_id,
                    "provider": provider,
                    "name": app_id,
                    "transport": "streamable_http",
                    "url": url,
                    "authType": "bearer",
                    "authErrorCode": "MCP_AUTH_REQUIRED",
                }
                for app_id, provider, url in remote_specs
            ],
            "revision": "rev_all_apps",
        }
    )

    status = mcp_runtime.MCPRuntimeManager().refresh(state)
    server_ids = {str(item["id"]) for item in status["servers"]}

    assert status["serverCount"] == 19
    assert {f"local_{index}" for index in range(12)}.issubset(server_ids)
    assert {f"app_{app_id}" for app_id, _provider, _url in remote_specs}.issubset(server_ids)


def test_refresh_discovers_servers_with_bounded_concurrency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    monkeypatch.setattr(mcp_runtime, "_module_available", lambda _module_name: True)
    monkeypatch.setattr(mcp_runtime, "_REFRESH_DISCOVERY_CONCURRENCY", 4)
    state = state_store.snapshot()
    state["skills"]["mcpServers"] = [
        {
            "id": f"local_{index}",
            "name": f"Local {index}",
            "transport": "stdio",
            "command": "python3",
            "cwd": str(tmp_path),
            "enabled": True,
        }
        for index in range(8)
    ]
    active = 0
    max_active = 0

    async def fake_list_tools(server: dict[str, object]) -> list[dict[str, object]]:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        try:
            await asyncio.sleep(0.03)
            return [{"serverId": server["id"], "name": "status", "inputSchema": {}}]
        finally:
            active -= 1

    manager = mcp_runtime.MCPRuntimeManager()
    monkeypatch.setattr(manager, "_list_tools_for_server", fake_list_tools)

    status = manager.refresh(state)

    assert status["serverCount"] == 8
    assert status["toolCount"] == 8
    assert max_active == 4


def test_refresh_overall_deadline_cancels_and_unwinds_slow_discovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    monkeypatch.setattr(mcp_runtime, "_module_available", lambda _module_name: True)
    monkeypatch.setattr(mcp_runtime, "_REFRESH_DISCOVERY_CONCURRENCY", 2)
    monkeypatch.setattr(mcp_runtime, "_REFRESH_DISCOVERY_DEADLINE_SECONDS", 0.05)
    state = state_store.snapshot()
    state["skills"]["mcpServers"] = [
        {
            "id": f"slow_{index}",
            "name": f"Slow {index}",
            "transport": "stdio",
            "command": "python3",
            "cwd": str(tmp_path),
            "enabled": True,
        }
        for index in range(4)
    ]
    entered: set[str] = set()
    cleaned: set[str] = set()

    async def fake_list_tools(server: dict[str, object]) -> list[dict[str, object]]:
        server_id = str(server["id"])
        entered.add(server_id)
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.add(server_id)
        return []

    manager = mcp_runtime.MCPRuntimeManager()
    monkeypatch.setattr(manager, "_list_tools_for_server", fake_list_tools)
    started = time.monotonic()

    status = manager.refresh(state)

    assert time.monotonic() - started < 0.5
    assert entered == cleaned
    assert len(entered) == 2
    assert {item["lastErrorCode"] for item in status["servers"]} == {"MCP_TOOL_TIMEOUT"}


def test_remote_read_only_annotation_never_bypasses_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Annotations:
        readOnlyHint = True

    class Tool:
        name = "search_mail"
        description = "Search mail"
        annotations = Annotations()
        inputSchema: dict[str, object] = {}

    class Result:
        tools = [Tool()]

    async def fake_with_session(server: dict[str, object], operation: object) -> Result:
        return Result()

    manager = mcp_runtime.MCPRuntimeManager()
    monkeypatch.setattr(manager, "_with_session", fake_with_session)
    tools = asyncio.run(
        manager._list_tools_for_server(
            {
                "id": "app_gmail",
                "name": "Gmail",
                "transport": "streamable_http",
                "callTimeoutSec": 45,
            }
        )
    )

    assert tools[0]["reportedReadOnly"] is True
    assert tools[0]["readOnly"] is False


def test_remote_inventory_keeps_tools_beyond_planner_budget_addressable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)

    class Tool:
        def __init__(self, index: int) -> None:
            self.name = f"tool_{index:02d}"
            self.description = f"Remote tool {index}"
            self.annotations = None
            self.inputSchema: dict[str, object] = {}

    class Result:
        tools = [Tool(index) for index in range(30)]

    async def fake_with_session(server: dict[str, object], operation: object) -> Result:
        return Result()

    called: dict[str, object] = {}

    async def fake_call(
        server: dict[str, object],
        tool_name: str,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        called.update(server_id=server["id"], tool_name=tool_name, arguments=arguments)
        return {"output": "ok", "result": {"toolName": tool_name}, "artifacts": []}

    manager = mcp_runtime.MCPRuntimeManager()
    monkeypatch.setattr(manager, "_with_session", fake_with_session)
    monkeypatch.setattr(manager, "_call_tool_for_server", fake_call)
    monkeypatch.setattr(mcp_runtime, "_module_available", lambda _module_name: True)
    mcp_runtime.set_remote_server_provider(
        lambda: [
            {
                "id": "app_google-drive",
                "appId": "google-drive",
                "provider": "google",
                "name": "Google Drive",
                "transport": "streamable_http",
                "url": "https://drivemcp.googleapis.com/mcp/v1",
                "authType": "bearer",
                "accessToken": "ephemeral-token",
            }
        ]
    )
    try:
        state = state_store.snapshot()
        status = manager.refresh(state)

        assert status["toolCount"] == 30
        metadata = manager.tool_metadata("app_google-drive", "tool_29", state)
        assert metadata is not None
        assert metadata["name"] == "tool_29"

        result = manager.call_tool(
            "app_google-drive",
            "tool_29",
            {"query": "latest"},
            state=state,
        )

        assert result["output"] == "ok"
        assert called == {
            "server_id": "app_google-drive",
            "tool_name": "tool_29",
            "arguments": {"query": "latest"},
        }
        assert manager.planner_prompt_context(state).count("\n- serverId=") == 12
    finally:
        mcp_runtime.set_remote_server_provider(None)


def test_task_cancel_interrupts_scoped_mcp_call_and_closes_async_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state = state_store.snapshot()
    state["skills"]["mcpServers"] = [
        {
            "id": "mcp_blocked",
            "name": "blocked",
            "transport": "stdio",
            "command": "python3",
            "cwd": str(tmp_path),
            "enabled": True,
        }
    ]
    manager = mcp_runtime.MCPRuntimeManager()
    monkeypatch.setattr(mcp_runtime, "_module_available", lambda _module_name: True)
    monkeypatch.setattr(
        manager,
        "tool_metadata",
        lambda *_args, **_kwargs: {"serverId": "mcp_blocked", "name": "wait"},
    )
    entered = threading.Event()
    closed = threading.Event()
    results: list[dict[str, object]] = []
    errors: list[BaseException] = []

    @asynccontextmanager
    async def blocked_session():
        entered.set()
        try:
            yield
        finally:
            closed.set()

    async def blocked_call(
        _server: dict[str, object],
        _tool_name: str,
        _arguments: dict[str, object],
    ) -> dict[str, object]:
        async with blocked_session():
            await asyncio.Event().wait()
        return {"output": "late success", "result": {}, "artifacts": []}

    monkeypatch.setattr(manager, "_call_tool_for_server", blocked_call)
    token = mcp_runtime.begin_task_scope("task-blocked")
    context = contextvars.copy_context()

    def invoke() -> None:
        try:
            results.append(manager.call_tool("mcp_blocked", "wait", state=state))
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=lambda: context.run(invoke), daemon=True)
    try:
        worker.start()
        assert entered.wait(1.0)

        assert mcp_runtime.cancel_task("task-blocked") == 1
        worker.join(2.0)

        assert not worker.is_alive()
        assert closed.is_set()
        assert results == []
        assert len(errors) == 1
        assert isinstance(errors[0], registry.SafeCapabilityError)
        assert errors[0].code == "TASK_CANCELLED"
    finally:
        mcp_runtime.end_task_scope(token)

    assert mcp_runtime.cancel_task("task-blocked") == 0


def test_task_scope_stays_registered_until_slow_async_cleanup_finishes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state = state_store.snapshot()
    state["skills"]["mcpServers"] = [
        {
            "id": "mcp_slow_cleanup",
            "name": "slow cleanup",
            "transport": "stdio",
            "command": "python3",
            "cwd": str(tmp_path),
            "enabled": True,
        }
    ]
    manager = mcp_runtime.MCPRuntimeManager()
    monkeypatch.setattr(mcp_runtime, "_module_available", lambda _module_name: True)
    monkeypatch.setattr(
        manager,
        "tool_metadata",
        lambda *_args, **_kwargs: {"serverId": "mcp_slow_cleanup", "name": "wait"},
    )
    entered = threading.Event()
    cleanup_started = threading.Event()
    release_cleanup = threading.Event()
    cleanup_finished = threading.Event()
    errors: list[BaseException] = []

    @asynccontextmanager
    async def slow_cleanup_session():
        entered.set()
        try:
            yield
        finally:
            cleanup_started.set()
            while not release_cleanup.is_set():
                await asyncio.sleep(0.01)
            cleanup_finished.set()

    async def blocked_call(
        _server: dict[str, object],
        _tool_name: str,
        _arguments: dict[str, object],
    ) -> dict[str, object]:
        async with slow_cleanup_session():
            await asyncio.Event().wait()
        return {"output": "late", "result": {}, "artifacts": []}

    monkeypatch.setattr(manager, "_call_tool_for_server", blocked_call)
    token = mcp_runtime.begin_task_scope("task-slow-cleanup")
    context = contextvars.copy_context()

    def invoke() -> None:
        try:
            manager.call_tool("mcp_slow_cleanup", "wait", state=state)
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=lambda: context.run(invoke), daemon=True)
    owner_ended = False
    try:
        worker.start()
        assert entered.wait(1.0)
        assert mcp_runtime.cancel_task("task-slow-cleanup") == 1
        assert cleanup_started.wait(1.0)

        mcp_runtime.end_task_scope(token)
        owner_ended = True
        assert mcp_runtime.task_cancellation_reason("task-slow-cleanup") == "task_cancelled"

        release_cleanup.set()
        worker.join(2.0)
        assert not worker.is_alive()
        assert cleanup_finished.is_set()
        assert len(errors) == 1
        assert isinstance(errors[0], registry.SafeCapabilityError)
        assert errors[0].code == "TASK_CANCELLED"
        assert mcp_runtime.task_cancellation_reason("task-slow-cleanup") == ""
    finally:
        release_cleanup.set()
        if not owner_ended:
            mcp_runtime.end_task_scope(token)


def test_owner_ended_scope_is_forced_out_without_removing_new_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mcp_runtime, "_OWNER_ENDED_SCOPE_RETENTION_SECONDS", 0.05)

    class FakeTask:
        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    class FakeLoop:
        def call_soon_threadsafe(self, callback: object) -> None:
            assert callable(callback)
            callback()

    old_token = mcp_runtime.begin_task_scope("task-forced-cleanup")
    old_task = FakeTask()
    call_id = old_token.scope.register_call(FakeLoop(), old_task)  # type: ignore[arg-type]
    replacement_token: object | None = None
    try:
        assert mcp_runtime.cancel_task("task-forced-cleanup") == 1
        assert old_task.cancelled is True
        mcp_runtime.end_task_scope(old_token)

        replacement_token = mcp_runtime.begin_task_scope("task-forced-cleanup")
        deadline = time.monotonic() + 1.0
        while (
            mcp_runtime.task_cancellation_reason("task-forced-cleanup")
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)

        assert mcp_runtime.task_cancellation_reason("task-forced-cleanup") == ""
        # The old timer is object/generation fenced: the replacement remains
        # reachable even though it has the same task id.
        assert mcp_runtime.cancel_task("task-forced-cleanup") == 0
        assert mcp_runtime.task_cancellation_reason("task-forced-cleanup") == "task_cancelled"
    finally:
        if replacement_token is not None:
            mcp_runtime.end_task_scope(replacement_token)  # type: ignore[arg-type]
        if old_token.scope.unregister_call(call_id, old_task):  # type: ignore[arg-type]
            mcp_runtime._remove_task_scope(old_token.scope)


def _write_fixture_server(tmp_path: Path) -> Path:
    server_path = tmp_path / "fixture_mcp_server.py"
    server_path.write_text(
        """
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

mcp = FastMCP("Fixture Server")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def echo_readonly(text: str) -> dict[str, str]:
    return {"echo": text}


@mcp.tool()
def write_note(path: str, text: str) -> dict[str, str]:
    target = Path(path)
    target.write_text(text, encoding="utf-8")
    return {"outputPath": str(target), "result": "written"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
        """.strip(),
        encoding="utf-8",
    )
    return server_path


def _configured_state(tmp_path: Path, server_path: Path) -> dict[str, object]:
    state = state_store.snapshot()
    state["skills"]["mcpServers"] = [
        {
            "id": "mcp_fixture",
            "name": "fixture",
            "transport": "stdio",
            "command": "python3",
            "args": [str(server_path)],
            "cwd": str(tmp_path),
            "enabled": True,
            "startupTimeoutSec": 15,
            "callTimeoutSec": 30,
        }
    ]
    return state_store.save_state(state)


def test_mcp_refresh_lists_stdio_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    server_path = _write_fixture_server(tmp_path)
    saved = _configured_state(tmp_path, server_path)

    status = mcp_runtime.refresh_mcp_runtime(saved)

    assert status["sdkAvailable"] is True
    assert status["toolCount"] == 2
    assert any(tool["name"] == "echo_readonly" for tool in status["tools"])
    assert any(tool["name"] == "write_note" for tool in status["tools"])
    assert status["servers"][0]["connected"] is True
    assert status["serverCount"] == 1
    assert status["tools"][0]["available"] is True
    assert "serverName" in status["tools"][0]


def test_mcp_refresh_keeps_invalid_server_truth_visible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    state = state_store.snapshot()
    state["skills"]["mcpServers"] = [
        {
            "id": "mcp_invalid",
            "name": "broken",
            "transport": "stdio",
            "command": "",
            "args": [],
            "cwd": str(tmp_path),
            "enabled": True,
        }
    ]
    saved = state_store.save_state(state)

    status = mcp_runtime.refresh_mcp_runtime(saved)

    assert status["serverCount"] == 1
    assert status["toolCount"] == 0
    assert status["lastErrorCode"] == "MCP_SERVER_INVALID"
    assert status["servers"][0]["lastErrorCode"] == "MCP_SERVER_INVALID"
    assert status["servers"][0]["sdkAvailable"] in {True, False}


def test_mcp_read_only_tool_executes_without_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    server_path = _write_fixture_server(tmp_path)
    saved = _configured_state(tmp_path, server_path)

    status = mcp_runtime.refresh_mcp_runtime(saved)
    metadata = next(tool for tool in status["tools"] if tool["name"] == "echo_readonly")

    result = registry.run_capability(
        "mcp_call_tool",
        {
            "serverId": "mcp_fixture",
            "toolName": "echo_readonly",
            "arguments": {"text": "merhaba"},
            "_readOnlyHint": metadata["readOnly"],
        },
        state_store.snapshot(),
    )

    assert result["ok"] is True
    assert result["result"]["kind"] == "mcp_call_tool"
    assert result["result"]["toolName"] == "echo_readonly"
    assert "merhaba" in result["output"]


def test_mcp_side_effect_tool_requires_confirmation_then_runs_in_confirmed_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    server_path = _write_fixture_server(tmp_path)
    saved = _configured_state(tmp_path, server_path)
    mcp_runtime.refresh_mcp_runtime(saved)

    denied = registry.run_capability(
        "mcp_call_tool",
        {
            "serverId": "mcp_fixture",
            "toolName": "write_note",
            "arguments": {"path": str(tmp_path / "note.txt"), "text": "elyan"},
            "_readOnlyHint": False,
        },
        state_store.snapshot(),
    )

    assert denied["ok"] is False
    assert denied["error"]["code"] == "PERMISSION_REQUIRED"

    runtime = bridge.RuntimeBridge()
    conversation = state_store.create_conversation("MCP")
    plan = state_store.save_pending_plan(
        {
            "id": "plan_mcp_write",
            "conversationId": conversation["id"],
            "query": "mcp ile not yaz",
            "intent": "mcp_call_tool",
            "capability": "mcp_call_tool",
            "confidence": 0.88,
            "privacyClass": "local_private",
            "steps": [
                {
                    "capability": "mcp_call_tool",
                    "args": {
                        "serverId": "mcp_fixture",
                        "toolName": "write_note",
                        "arguments": {"path": str(tmp_path / "note.txt"), "text": "elyan"},
                        "_readOnlyHint": False,
                    },
                    "description": "MCP ile not yaz",
                }
            ],
            "planPreview": {
                "summary": "MCP aracı write_note çalıştırılacak.",
                "steps": [{"capability": "mcp_call_tool"}],
            },
        }
    )

    result = runtime.confirm_conversation_plan(str(conversation["id"]), str(plan["id"]), True)

    assert result["chatOk"] is True
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "elyan"
    assert result["structuredResult"]["toolName"] == "write_note"


def test_runtime_status_exposes_mcp_truth_surface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    server_path = _write_fixture_server(tmp_path)
    saved = _configured_state(tmp_path, server_path)
    mcp_runtime.refresh_mcp_runtime(saved)

    runtime = bridge.RuntimeBridge()
    status = runtime.status()

    assert "mcpStatus" in status
    assert status["dependencyStatus"]["mcp"]["label"] == "MCP Python SDK"
    assert status["mcpStatus"]["toolCount"] == 2
    assert status["mcpStatus"]["serverCount"] == 1
