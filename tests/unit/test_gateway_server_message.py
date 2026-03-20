import json
from types import SimpleNamespace

import pytest

from core.gateway import server as gateway_server


class _Req:
    def __init__(self, data):
        self._data = data
        self.rel_url = SimpleNamespace(query={})
        self.match_info = {}
        self.headers = {}
        self.cookies = {}
        self.remote = "127.0.0.1"
        self.transport = None

    async def json(self):
        return self._data


class _Agent:
    def __init__(self, response: str = "ok"):
        self.response = response
        self.calls = []

    async def process(self, text, notify=None, attachments=None, channel="cli", metadata=None):
        self.calls.append({
            "text": text,
            "channel": channel,
            "metadata": metadata,
        })
        return self.response


class _StatusRouter:
    def get_adapter_status(self):
        return {"telegram": "connected", "slack": "degraded"}

    def get_adapter_health(self):
        return {"telegram": {"ok": True}, "slack": {"ok": False}}


class _StatusCron:
    class _Sched:
        @staticmethod
        def get_jobs():
            return [object(), object()]

    scheduler = _Sched()


@pytest.mark.asyncio
async def test_handle_external_message_wait_returns_agent_response(monkeypatch):
    monkeypatch.setattr(gateway_server, "push_activity", lambda *_a, **_k: None)

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.agent = _Agent(response="tamam")

    req = _Req({"text": "merhaba", "channel": "dashboard", "wait": True, "timeout_s": 30})
    resp = await gateway_server.ElyanGatewayServer.handle_external_message(srv, req)

    assert resp.status == 200
    payload = json.loads(resp.text)
    assert payload["status"] == "ok"
    assert payload["response"] == "tamam"
    assert srv.agent.calls and srv.agent.calls[0]["channel"] == "dashboard"


@pytest.mark.asyncio
async def test_handle_external_message_async_returns_processing(monkeypatch):
    monkeypatch.setattr(gateway_server, "push_activity", lambda *_a, **_k: None)

    created = []

    def _fake_create_task(coro):
        created.append(coro)

        class _DummyTask:
            pass

        return _DummyTask()

    monkeypatch.setattr(gateway_server.asyncio, "create_task", _fake_create_task)

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.agent = _Agent(response="tamam")

    req = _Req({"text": "test", "channel": "api", "wait": False})
    resp = await gateway_server.ElyanGatewayServer.handle_external_message(srv, req)

    assert resp.status == 200
    payload = json.loads(resp.text)
    assert payload["status"] == "processing"
    assert created

    # Ensure no dangling coroutine warning in test process.
    for coro in created:
        coro.close()


@pytest.mark.asyncio
async def test_handle_status_includes_runtime_health_and_tool_count(monkeypatch):
    monkeypatch.setattr(
        gateway_server,
        "_get_runtime_model_info",
        lambda: {"active_model": "gpt-4o", "active_provider": "openai"},
    )

    class _Health:
        status = "ok"
        issues = []
        cpu_percent = 12
        ram_percent = 34
        disk_percent = 56
        battery_percent = 88
        is_on_ac = True

    class _Mon:
        @staticmethod
        def get_health_snapshot():
            return _Health()

    import core.monitoring as monitoring
    monkeypatch.setattr(monitoring, "get_resource_monitor", lambda: _Mon())
    monkeypatch.setattr(
        gateway_server,
        "get_personalization_manager",
        lambda: SimpleNamespace(get_status=lambda: {"enabled": True, "mode": "hybrid"}),
    )
    monkeypatch.setattr(
        gateway_server,
        "get_model_runtime",
        lambda: SimpleNamespace(snapshot=lambda: {"enabled": True, "execution_mode": "local_first"}),
    )
    monkeypatch.setattr(
        gateway_server,
        "get_outcome_store",
        lambda: SimpleNamespace(stats=lambda: {"outcomes": 3, "success_rate": 0.66}),
    )
    monkeypatch.setattr(
        gateway_server,
        "get_regression_evaluator",
        lambda: SimpleNamespace(summary=lambda: {"verification_pass_rate": 0.75}),
    )

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.router = _StatusRouter()
    srv.cron = _StatusCron()
    req = SimpleNamespace()

    resp = await gateway_server.ElyanGatewayServer.handle_status(srv, req)
    payload = json.loads(resp.text)
    assert payload["tools_total"] >= 1
    assert payload["tool_count"] == payload["tools_total"]
    assert payload["runtime_health"]["tooling"]["tools_total"] == payload["tools_total"]
    assert payload["runtime"]["tools_total"] == payload["tools_total"]
    assert payload["runtime_health"]["channels"]["total"] == 2
    assert payload["personalization"]["enabled"] is True
    assert payload["ml"]["enabled"] is True
    assert payload["reliability"]["store"]["outcomes"] == 3
    assert payload["runtime"]["personalization"]["mode"] == "hybrid"
    assert payload["runtime"]["ml"]["execution_mode"] == "local_first"
    assert "orchestration_telemetry" in payload


@pytest.mark.asyncio
async def test_handle_status_treats_webchat_online_and_optional_whatsapp_as_non_degraded(monkeypatch):
    monkeypatch.setattr(
        gateway_server,
        "_get_runtime_model_info",
        lambda: {"active_model": "gpt-4o", "active_provider": "openai"},
    )

    class _Health:
        status = "ok"
        issues = []
        cpu_percent = 5
        ram_percent = 12
        disk_percent = 20
        battery_percent = 100
        is_on_ac = True

    class _Mon:
        @staticmethod
        def get_health_snapshot():
            return _Health()

    import core.monitoring as monitoring
    monkeypatch.setattr(monitoring, "get_resource_monitor", lambda: _Mon())
    monkeypatch.setattr(
        gateway_server,
        "get_personalization_manager",
        lambda: SimpleNamespace(get_status=lambda: {"enabled": True}),
    )
    monkeypatch.setattr(
        gateway_server,
        "get_model_runtime",
        lambda: SimpleNamespace(snapshot=lambda: {"enabled": True}),
    )
    monkeypatch.setattr(
        gateway_server,
        "get_outcome_store",
        lambda: SimpleNamespace(stats=lambda: {"outcomes": 0}),
    )
    monkeypatch.setattr(
        gateway_server,
        "get_regression_evaluator",
        lambda: SimpleNamespace(summary=lambda: {"verification_pass_rate": 1.0}),
    )

    class _Router:
        @staticmethod
        def get_adapter_status():
            return {
                "webchat": "online (0 clients)",
                "telegram": "connected",
                "whatsapp": "disconnected",
            }

        @staticmethod
        def get_adapter_health():
            return {
                "webchat": {"status": "error", "last_error": "status=online (0 clients)"},
                "telegram": {"status": "connected"},
                "whatsapp": {"status": "error", "last_error": "Node.js bulunamadı. WhatsApp QR için önce Node.js kurun."},
            }

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.router = _Router()
    srv.cron = _StatusCron()

    resp = await gateway_server.ElyanGatewayServer.handle_status(srv, SimpleNamespace())
    payload = json.loads(resp.text)

    assert payload["runtime_health"]["status"] == "healthy"
    assert payload["runtime_health"]["channels"]["healthy"] == 2
    assert payload["runtime_health"]["channels"]["optional"] == 1
    assert payload["runtime_health"]["channels"]["degraded"] == 0
    assert payload["runtime"]["channels_optional"] == 1


@pytest.mark.asyncio
async def test_handle_status_treats_telegram_conflict_as_optional_for_core_runtime(monkeypatch):
    monkeypatch.setattr(
        gateway_server,
        "_get_runtime_model_info",
        lambda: {"active_model": "gpt-4o", "active_provider": "openai"},
    )

    class _Health:
        status = "ok"
        issues = []
        cpu_percent = 4
        ram_percent = 10
        disk_percent = 20
        battery_percent = 100
        is_on_ac = True

    class _Mon:
        @staticmethod
        def get_health_snapshot():
            return _Health()

    import core.monitoring as monitoring
    monkeypatch.setattr(monitoring, "get_resource_monitor", lambda: _Mon())
    monkeypatch.setattr(
        gateway_server,
        "get_personalization_manager",
        lambda: SimpleNamespace(get_status=lambda: {"enabled": True}),
    )
    monkeypatch.setattr(
        gateway_server,
        "get_model_runtime",
        lambda: SimpleNamespace(snapshot=lambda: {"enabled": True}),
    )
    monkeypatch.setattr(
        gateway_server,
        "get_outcome_store",
        lambda: SimpleNamespace(stats=lambda: {"outcomes": 0}),
    )
    monkeypatch.setattr(
        gateway_server,
        "get_regression_evaluator",
        lambda: SimpleNamespace(summary=lambda: {"verification_pass_rate": 1.0}),
    )

    class _Router:
        @staticmethod
        def get_adapter_status():
            return {
                "webchat": "online (0 clients)",
                "telegram": "unavailable",
            }

        @staticmethod
        def get_adapter_health():
            return {
                "webchat": {"status": "online (0 clients)"},
                "telegram": {"status": "unavailable", "last_error": "terminated by other getUpdates request"},
            }

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.router = _Router()
    srv.cron = _StatusCron()

    resp = await gateway_server.ElyanGatewayServer.handle_status(srv, SimpleNamespace())
    payload = json.loads(resp.text)

    assert payload["runtime_health"]["status"] == "healthy"
    assert payload["runtime_health"]["channels"]["optional"] == 1
    assert payload["runtime_health"]["channels"]["degraded"] == 0


@pytest.mark.asyncio
async def test_handle_privacy_delete_wipes_personalization(monkeypatch):
    pushed = {"value": False}

    monkeypatch.setattr(
        gateway_server.audit_trail,
        "delete_user_data",
        lambda user_id: {"scope": "audit", "user_id": user_id},
    )
    monkeypatch.setattr(
        gateway_server,
        "get_personalization_manager",
        lambda: SimpleNamespace(delete_user_data=lambda user_id: {"scope": "personalization", "user_id": user_id}),
    )
    monkeypatch.setattr(
        gateway_server,
        "get_outcome_store",
        lambda: SimpleNamespace(delete_user=lambda user_id: {"scope": "reliability", "user_id": user_id}),
    )
    monkeypatch.setattr(
        gateway_server,
        "push_activity",
        lambda *_a, **_k: pushed.__setitem__("value", True),
    )

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    resp = await gateway_server.ElyanGatewayServer.handle_privacy_delete(srv, _Req({"user_id": "user-42"}))
    payload = json.loads(resp.text)

    assert payload["ok"] is True
    assert payload["result"]["audit"]["scope"] == "audit"
    assert payload["result"]["personalization"]["scope"] == "personalization"
    assert payload["result"]["reliability"]["scope"] == "reliability"
    assert pushed["value"] is True


@pytest.mark.asyncio
async def test_handle_product_home_aggregates_readiness_and_reports(monkeypatch):
    monkeypatch.setattr(
        gateway_server,
        "_get_runtime_model_info",
        lambda: {"active_model": "gpt-4o", "active_provider": "openai"},
    )
    monkeypatch.setattr(
        gateway_server,
        "load_latest_benchmark_summary",
        lambda: {
            "pass_count": 20,
            "total": 20,
            "average_retries": 0.1,
            "average_replans": 0.5,
            "remaining_failure_codes": [],
            "last_benchmark_timestamp": "2026-03-09 10:00:00",
            "report_root": "/tmp/bench",
        },
    )
    monkeypatch.setattr(
        gateway_server,
        "list_emre_workflow_reports",
        lambda limit=8: [
            {
                "name": "telegram_desktop_task_completion",
                "workflow_name": "Telegram-triggered desktop task completion",
                "status": "success",
                "retry_count": 1,
                "replan_count": 0,
                "failure_code": "",
                "updated_at": 10.0,
                "summary": "success",
            }
        ],
    )
    monkeypatch.setattr(
        gateway_server,
        "_check_macos_permissions",
        lambda: {"is_macos": True, "osascript_available": True, "screencapture_available": True},
    )
    monkeypatch.setattr(gateway_server, "is_setup_complete", lambda: True)
    monkeypatch.setattr(gateway_server.importlib.util, "find_spec", lambda name: object() if name == "playwright" else None)

    async def _status(_request):
        return gateway_server.web.json_response(
            {
                "status": "online",
                "runtime_health": {"status": "healthy"},
                "health_status": "ok",
                "version": "18.0.0",
                "adapters": {"telegram": "connected"},
            }
        )

    async def _tasks(_request):
        return gateway_server.web.json_response({"active": [{"task_id": "t1", "status": "running"}], "history": []})

    async def _runs(_request):
        return gateway_server.web.json_response({"runs": [{"run_id": "r1", "status": "success"}], "count": 1})

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.handle_status = _status
    srv.handle_tasks = _tasks
    srv.handle_recent_runs = _runs

    resp = await gateway_server.ElyanGatewayServer.handle_product_home(srv, SimpleNamespace())
    payload = json.loads(resp.text)
    assert payload["ok"] is True
    assert payload["readiness"]["elyan_ready"] is True
    assert payload["benchmark"]["pass_count"] == 20
    assert payload["preset_workflows"]
    assert payload["recent_workflow_reports"][0]["workflow_name"] == "Telegram-triggered desktop task completion"
    assert payload["onboarding"]["first_demo_workflow"]
    assert payload["release"]["entrypoint"] == "/dashboard"
    checks = payload["release"]["quickstart_checks"]
    assert any(item["label"] == "Dashboard start script" for item in checks)
    assert any(item["label"] == "Production benchmark gate" for item in checks)


@pytest.mark.asyncio
async def test_handle_product_health_stays_ready_without_benchmark_when_core_runtime_is_healthy(monkeypatch):
    monkeypatch.setattr(
        gateway_server,
        "_get_runtime_model_info",
        lambda: {"active_model": "gpt-4o", "active_provider": "openai"},
    )
    monkeypatch.setattr(
        gateway_server,
        "load_latest_benchmark_summary",
        lambda: {
            "pass_count": 0,
            "total": 0,
            "average_retries": 0.0,
            "average_replans": 0.0,
            "remaining_failure_codes": [],
            "last_benchmark_timestamp": "",
            "report_root": "",
        },
    )
    monkeypatch.setattr(gateway_server, "list_emre_workflow_reports", lambda limit=8: [])
    monkeypatch.setattr(
        gateway_server,
        "_check_macos_permissions",
        lambda: {"is_macos": True, "osascript_available": True, "screencapture_available": True},
    )
    monkeypatch.setattr(gateway_server, "is_setup_complete", lambda: True)
    monkeypatch.setattr(gateway_server.importlib.util, "find_spec", lambda name: object() if name == "playwright" else None)

    async def _status(_request):
        return gateway_server.web.json_response(
            {
                "status": "online",
                "runtime_health": {"status": "healthy"},
                "health_status": "ok",
                "version": "18.0.0",
                "adapters": {"telegram": "unavailable", "webchat": "online (0 clients)"},
            }
        )

    async def _tasks(_request):
        return gateway_server.web.json_response({"active": [], "history": []})

    async def _runs(_request):
        return gateway_server.web.json_response({"runs": [], "count": 0})

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv.handle_status = _status
    srv.handle_tasks = _tasks
    srv.handle_recent_runs = _runs

    resp = await gateway_server.ElyanGatewayServer.handle_product_health(srv, SimpleNamespace())
    payload = json.loads(resp.text)

    assert payload["ok"] is True
    assert payload["status"] == "ready"
    assert payload["readiness"]["elyan_ready"] is True
    assert payload["readiness"]["telegram_ready"] is False


@pytest.mark.asyncio
async def test_handle_models_get_returns_registry_and_collaboration(monkeypatch):
    values = {
        "models.default": {"provider": "openai", "model": "gpt-4o"},
        "models.fallback": {"provider": "groq", "model": "llama-3.3-70b-versatile"},
        "models.roles": {"reasoning": {"provider": "openai", "model": "gpt-4o"}},
        "models.registry": [
            {"id": "openai:gpt-4o", "provider": "openai", "model": "gpt-4o", "enabled": True, "roles": ["reasoning"]},
            {"id": "groq:llama", "provider": "groq", "model": "llama-3.3-70b-versatile", "enabled": True, "roles": ["code"]},
        ],
        "models.collaboration": {"enabled": True, "strategy": "synthesize", "max_models": 3, "roles": ["reasoning", "code"]},
        "router.enabled": True,
        "models.providers": {"openai": {"apiKey": "$OPENAI_API_KEY"}},
    }
    monkeypatch.setattr(gateway_server.elyan_config, "get", lambda key, default=None: values.get(key, default))
    monkeypatch.setattr(gateway_server, "_provider_key_status", lambda provider: {"provider": provider, "configured": provider == "openai"})
    monkeypatch.setattr(gateway_server, "_get_runtime_model_info", lambda: {"active_model": "gpt-4o", "active_provider": "openai"})

    class _FakeOrchestrator:
        @staticmethod
        def list_registered_models():
            return [{"id": "openai:gpt-4o", "provider": "openai", "model": "gpt-4o", "status": "configured"}]

    monkeypatch.setattr("core.model_orchestrator.model_orchestrator", _FakeOrchestrator())

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    resp = await gateway_server.ElyanGatewayServer.handle_models_get(srv, SimpleNamespace())
    payload = json.loads(resp.text)

    assert payload["ok"] is True
    assert payload["registry"][0]["provider"] == "openai"
    assert payload["collaboration"]["enabled"] is True
    assert payload["registered_models"][0]["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_handle_agent_profile_get_includes_nlu_model_a(monkeypatch):
    values = {
        "agent.nlu.model_a.enabled": True,
        "agent.nlu.model_a.model_path": "/tmp/model_a.json",
        "agent.nlu.model_a.min_confidence": 0.82,
        "agent.nlu.model_a.allowed_actions": ["open_app", "web_search"],
    }
    monkeypatch.setattr(gateway_server.elyan_config, "get", lambda key, default=None: values.get(key, default))
    monkeypatch.setattr(
        gateway_server,
        "get_user_profile_store",
        lambda: SimpleNamespace(profile_summary=lambda _user_id: {
            "preferred_language": "tr",
            "response_length_bias": "short",
            "top_topics": ["ai agents"],
            "top_actions": ["open_app"],
        }),
    )

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    resp = await gateway_server.ElyanGatewayServer.handle_agent_profile_get(srv, SimpleNamespace())
    payload = json.loads(resp.text)
    profile = payload.get("profile", {})
    model_a = profile.get("nlu", {}).get("model_a", {})

    assert payload.get("ok") is True
    assert model_a.get("enabled") is True
    assert model_a.get("model_path") == "/tmp/model_a.json"
    assert abs(float(model_a.get("min_confidence") or 0.0) - 0.82) < 1e-9
    assert model_a.get("allowed_actions") == ["open_app", "web_search"]
    assert profile.get("user_profile", {}).get("response_length_bias") == "short"
    assert profile.get("user_profile", {}).get("top_topics") == ["ai agents"]


@pytest.mark.asyncio
async def test_handle_agent_profile_update_persists_nlu_model_a(monkeypatch):
    store = {"agent.runtime_policy.preset": "balanced"}
    saved_profiles = {}

    def _get(key, default=None):
        return store.get(key, default)

    def _set(key, value):
        store[key] = value

    monkeypatch.setattr(gateway_server.elyan_config, "get", _get)
    monkeypatch.setattr(gateway_server.elyan_config, "set", _set)
    monkeypatch.setattr(gateway_server, "push_activity", lambda *_a, **_k: None)
    monkeypatch.setattr(
        gateway_server,
        "get_user_profile_store",
        lambda: SimpleNamespace(
            get=lambda user_id: saved_profiles.setdefault(user_id, {}),
            profile_summary=lambda user_id: saved_profiles.get(user_id, {}),
            _save=lambda: None,
        ),
    )

    req = _Req(
        {
            "runtime_policy": {"preset": "custom"},
            "user_profile": {"response_length_bias": "detailed"},
            "nlu": {
                "model_a": {
                    "enabled": True,
                    "model_path": "~/models/model_a.json",
                    "min_confidence": 0.9,
                    "allowed_actions": ["open_app", "run_safe_command"],
                }
            },
        }
    )
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    resp = await gateway_server.ElyanGatewayServer.handle_agent_profile_update(srv, req)
    payload = json.loads(resp.text)
    profile = payload.get("profile", {})
    model_a = profile.get("nlu", {}).get("model_a", {})

    assert payload.get("ok") is True
    assert store.get("agent.nlu.model_a.enabled") is True
    assert store.get("agent.nlu.model_a.model_path") == "~/models/model_a.json"
    assert abs(float(store.get("agent.nlu.model_a.min_confidence") or 0.0) - 0.9) < 1e-9
    assert store.get("agent.nlu.model_a.allowed_actions") == ["open_app", "run_safe_command"]
    assert model_a.get("enabled") is True
    assert model_a.get("allowed_actions") == ["open_app", "run_safe_command"]
    assert saved_profiles["local"]["response_length_bias"] == "detailed"
    assert saved_profiles["local"]["preferred_language"] == "tr"


@pytest.mark.asyncio
async def test_handle_recent_runs_uses_short_cache(monkeypatch, tmp_path):
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run_1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence.json").write_text(
        json.dumps({"metadata": {"status": "ok"}, "steps": [], "artifacts": []}),
        encoding="utf-8",
    )
    (run_dir / "task.json").write_text(
        json.dumps({"metadata": {"action": "health_check"}}),
        encoding="utf-8",
    )
    (run_dir / "summary.md").write_text("# ok\n", encoding="utf-8")

    monkeypatch.setattr(gateway_server, "resolve_runs_root", lambda: runs_root)
    monkeypatch.setattr(
        gateway_server,
        "_recent_runs_cache",
        {"ts": 0.0, "signature": (), "limit": 0, "items": []},
    )

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    req = SimpleNamespace(rel_url=SimpleNamespace(query={"limit": "5"}))

    first = await gateway_server.ElyanGatewayServer.handle_recent_runs(srv, req)
    first_payload = json.loads(first.text)
    assert first_payload["count"] == 1
    assert first_payload.get("cached") is None

    second = await gateway_server.ElyanGatewayServer.handle_recent_runs(srv, req)
    second_payload = json.loads(second.text)
    assert second_payload["count"] == 1
    assert second_payload.get("cached") is True


@pytest.mark.asyncio
async def test_handle_models_update_persists_registry_and_collaboration(monkeypatch):
    stored = {
        "models.default": {"provider": "openai", "model": "gpt-4o"},
        "models.fallback": {"provider": "groq", "model": "llama-3.3-70b-versatile"},
        "models.roles": {},
        "models.registry": [],
        "models.collaboration": {},
        "router.enabled": True,
        "models.local.model": "llama3.1:8b",
        "models.providers": {},
    }
    captured = {}

    def _fake_get(key, default=None):
        return stored.get(key, default)

    def _fake_set(key, value):
        captured[key] = value
        stored[key] = value

    monkeypatch.setattr(gateway_server.elyan_config, "get", _fake_get)
    monkeypatch.setattr(gateway_server.elyan_config, "set", _fake_set)
    monkeypatch.setattr(gateway_server, "_provider_key_status", lambda provider: {"provider": provider, "configured": True})
    monkeypatch.setattr(gateway_server, "_get_runtime_model_info", lambda: {"active_model": "gpt-4o", "active_provider": "openai"})
    monkeypatch.setattr(gateway_server, "push_activity", lambda *_a, **_k: None)

    class _FakeOrchestrator:
        def _load_providers(self):
            return None

        @staticmethod
        def list_registered_models():
            return [{"id": "groq:llama-3.3-70b-versatile", "provider": "groq", "model": "llama-3.3-70b-versatile"}]

    monkeypatch.setattr("core.model_orchestrator.model_orchestrator", _FakeOrchestrator())

    req = _Req(
        {
            "registry": [
                {
                    "id": "groq:llama-3.3-70b-versatile",
                    "provider": "groq",
                    "model": "llama-3.3-70b-versatile",
                    "enabled": True,
                    "roles": ["code", "qa"],
                }
            ],
            "collaboration": {
                "enabled": True,
                "strategy": "synthesize",
                "max_models": 3,
                "roles": ["reasoning", "code", "qa"],
            },
            "provider": "openai",
            "model": "gpt-4o",
            "fallback_provider": "groq",
            "fallback_model": "llama-3.3-70b-versatile",
            "sync_roles": False,
            "roles": {"reasoning": {"provider": "openai", "model": "gpt-4o"}},
        }
    )

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    resp = await gateway_server.ElyanGatewayServer.handle_models_update(srv, req)
    payload = json.loads(resp.text)

    assert captured["models.registry"][0]["provider"] == "groq"
    assert captured["models.collaboration"]["enabled"] is True
    assert payload["collaboration"]["strategy"] == "synthesize"
    assert payload["registry"][0]["roles"] == ["code", "qa"]


@pytest.mark.asyncio
async def test_handle_product_workflow_run_returns_report(monkeypatch):
    monkeypatch.setattr(gateway_server, "push_activity", lambda *_a, **_k: None)

    async def _run(name, clear_live_state=True):
        assert name == "telegram_desktop_task_completion"
        assert clear_live_state is True
        return {
            "success": True,
            "status": "completed",
            "workflow": {
                "name": name,
                "workflow_name": "Telegram-triggered desktop task completion",
                "status": "completed",
                "completed_steps": 3,
                "planned_steps": 3,
                "retry_count": 0,
                "replan_count": 0,
                "failure_code": "",
                "artifacts": [],
                "screenshots": [],
                "summary": "completed",
            },
        }

    monkeypatch.setattr(gateway_server, "run_emre_workflow_preset", _run)
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    req = _Req({"name": "telegram_desktop_task_completion", "clear_live_state": True})
    resp = await gateway_server.ElyanGatewayServer.handle_product_workflow_run(srv, req)
    payload = json.loads(resp.text)
    assert payload["ok"] is True
    assert payload["workflow"]["workflow_name"] == "Telegram-triggered desktop task completion"


@pytest.mark.asyncio
async def test_handle_product_health_exposes_release_ready_summary(monkeypatch):
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)

    async def _build():
        return {
            "ok": True,
            "readiness": {"elyan_ready": True, "desktop_operator_ready": True},
            "benchmark": {
                "pass_count": 20,
                "total": 20,
                "average_retries": 0.1,
                "average_replans": 0.5,
                "remaining_failure_codes": [],
            },
            "release": {"version": "18.0.0", "health_status": "ok", "entrypoint": "/dashboard"},
        }

    srv._build_product_home_payload = _build
    resp = await gateway_server.ElyanGatewayServer.handle_product_health(srv, SimpleNamespace())
    payload = json.loads(resp.text)
    assert payload["ok"] is True
    assert payload["status"] == "ready"
    assert payload["entrypoint"] == "/dashboard"


@pytest.mark.asyncio
async def test_handle_recent_runs_extracts_error_code_and_duration(monkeypatch, tmp_path):
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "run_1"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.md").write_text("# summary\n", encoding="utf-8")
    (run_dir / "task.json").write_text(json.dumps({"metadata": {"action": "write_excel"}}), encoding="utf-8")
    (run_dir / "evidence.json").write_text(
        json.dumps(
            {
                "metadata": {
                    "status": "failed",
                    "errors": [{"error_code": "WRITE_POSTCHECK_FAILED"}],
                    "workflow_profile": "superpowers_lite",
                    "workflow_phase": "executing",
                    "execution_route": "micro_orchestration",
                    "autonomy_mode": "yari_otonom",
                    "autonomy_policy": "balanced",
                    "orchestration_decision_path": ["intent_parsed", "direct_intent", "simple_browser_or_app"],
                    "approval_status": "review_blocked",
                    "plan_progress": "2/3",
                    "review_status": "blocked",
                    "workspace_mode": "git_worktree_recommended",
                    "design_artifact_path": "/tmp/design.md",
                    "plan_artifact_path": "/tmp/implementation_plan.md",
                    "review_artifact_path": "/tmp/review_report.md",
                    "finish_branch_report_path": "/tmp/finish_branch_report.md",
                    "claim_coverage": 1.0,
                    "critical_claim_coverage": 0.5,
                    "uncertainty_count": 2,
                    "conflict_count": 1,
                    "manual_review_claim_count": 3,
                    "claim_map_path": "/tmp/claim_map.json",
                    "revision_summary_path": "/tmp/revision_summary.txt",
                    "team_quality_avg": 0.82,
                    "team_parallel_waves": 2,
                    "team_max_wave_size": 2,
                    "team_parallelizable_packets": 2,
                    "team_serial_packets": 1,
                    "team_ownership_conflicts": 1,
                    "team_research_claim_coverage": 1.0,
                    "team_research_critical_claim_coverage": 0.5,
                    "team_research_uncertainty_count": 2,
                    "quality_status": "partial",
                },
                "steps": [{"duration_ms": 120}, {"duration_ms": 80}],
                "artifacts": [{"path": "/tmp/a"}],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(gateway_server, "resolve_runs_root", lambda: runs_root)
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    req = SimpleNamespace(rel_url=SimpleNamespace(query={"limit": "5"}))

    resp = await gateway_server.ElyanGatewayServer.handle_recent_runs(srv, req)
    payload = json.loads(resp.text)
    assert payload["count"] == 1
    run = payload["runs"][0]
    assert run["error_code"] == "WRITE_POSTCHECK_FAILED"
    assert run["duration_ms"] == 200
    assert run["action"] == "write_excel"
    assert run["claim_coverage"] == 1.0
    assert run["critical_claim_coverage"] == 0.5
    assert run["uncertainty_count"] == 2
    assert run["conflict_count"] == 1
    assert run["manual_review_claim_count"] == 3
    assert run["claim_map_path"] == "/tmp/claim_map.json"
    assert run["revision_summary_path"] == "/tmp/revision_summary.txt"
    assert run["team_quality_avg"] == 0.82
    assert run["team_research_claim_coverage"] == 1.0
    assert run["team_research_critical_claim_coverage"] == 0.5
    assert run["team_research_uncertainty_count"] == 2
    assert run["quality_status"] == "partial"
    assert run["workflow_profile"] == "superpowers_lite"
    assert run["workflow_phase"] == "executing"
    assert run["execution_route"] == "micro_orchestration"
    assert run["autonomy_mode"] == "yari_otonom"
    assert run["autonomy_policy"] == "balanced"
    assert run["orchestration_decision_path"] == ["intent_parsed", "direct_intent", "simple_browser_or_app"]
    assert run["approval_status"] == "review_blocked"
    assert run["plan_progress"] == "2/3"
    assert run["review_status"] == "blocked"
    assert run["workspace_mode"] == "git_worktree_recommended"
    assert run["design_artifact_path"] == "/tmp/design.md"
    assert run["plan_artifact_path"] == "/tmp/implementation_plan.md"
    assert run["review_artifact_path"] == "/tmp/review_report.md"
    assert run["finish_branch_report_path"] == "/tmp/finish_branch_report.md"
    assert run["team_parallel_waves"] == 2
    assert run["team_max_wave_size"] == 2
    assert run["team_parallelizable_packets"] == 2
    assert run["team_serial_packets"] == 1
    assert run["team_ownership_conflicts"] == 1


@pytest.mark.asyncio
async def test_handle_tool_events_returns_recent_stream(monkeypatch):
    gateway_server._tool_event_log.clear()
    gateway_server.push_tool_event("start", "write_file", step="s1", request_id="r1", payload={"path": "/tmp/a.txt"})
    gateway_server.push_tool_event("end", "write_file", step="s1", request_id="r1", success=True, latency_ms=12, payload={"text": "ok"})

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    req = SimpleNamespace(rel_url=SimpleNamespace(query={"limit": "10"}))
    resp = await gateway_server.ElyanGatewayServer.handle_tool_events(srv, req)
    payload = json.loads(resp.text)
    assert payload["ok"] is True
    assert payload["count"] >= 2
    assert payload["events"][0]["stage"] in {"end", "start"}


def test_push_tool_event_sanitizes_large_payload():
    gateway_server._tool_event_log.clear()
    big = "x" * 1200
    gateway_server.push_tool_event("update", "analyze_screen", payload={"image_data": "data:image/png;base64,AAAA", "text": big})
    row = gateway_server._tool_event_log[-1]
    assert row["payload"]["image_data"] == "<omitted>"
    assert isinstance(row["payload"]["text"], str)
    assert len(row["payload"]["text"]) < 700


@pytest.mark.asyncio
async def test_handle_admin_overview_aggregates_users_and_tasks(monkeypatch):
    class _Task:
        def __init__(self, payload):
            self._payload = payload

        def to_dict(self):
            return dict(self._payload)

    class _TaskBrain:
        @staticmethod
        def list_all():
            return [
                _Task(
                    {
                        "task_id": "task_fg_1",
                        "objective": "Rapor hazirla",
                        "state": "executing",
                        "created_at": 10.0,
                        "updated_at": 15.0,
                        "history": [{"state": "planning", "ts": 11.0}],
                        "subtasks": [{"title": "Brief al"}],
                        "artifacts": [{"path": "/tmp/doc.md", "type": "file"}],
                        "context": {"user_id": "u-admin", "channel": "telegram", "workflow_id": "research_workflow"},
                    }
                )
            ]

    class _AwayTaskRegistry:
        @staticmethod
        def list_all():
            return [
                SimpleNamespace(
                    to_dict=lambda: {
                        "task_id": "away_1",
                        "user_input": "Durum kontrol",
                        "user_id": "u-admin",
                        "channel": "dashboard",
                        "mode": "background",
                        "capability_domain": "screen_operator",
                        "workflow_id": "screen_operator_workflow",
                        "state": "queued",
                        "created_at": 12.0,
                        "updated_at": 18.0,
                        "result_summary": "",
                        "error": "",
                        "retry_count": 0,
                        "max_retries": 2,
                        "next_retry_at": 0.0,
                        "attachments": [],
                    }
                )
            ]

    class _Quota:
        _usage = {"u-admin": {"last_active": 20}}

        @staticmethod
        def get_user_stats(user_id):
            _ = user_id
            return {
                "tier": "pro",
                "daily_messages": 12,
                "daily_limit": 500,
                "monthly_tokens": 1200,
                "monthly_limit": 10000,
                "lifetime_messages": 80,
                "lifetime_tokens": 24000,
            }

        @staticmethod
        def check_quota(user_id):
            _ = user_id
            return {"allowed": False, "reason": "daily_message_limit_reached"}

    class _Subscription:
        _users = {"u-admin": {"tier": "pro"}}

        @staticmethod
        def get_subscription_summary(user_id):
            return {"user_id": user_id, "tier": "pro", "expiry_at": 0, "status": "active"}

    monkeypatch.setattr(gateway_server, "task_brain", _TaskBrain())
    monkeypatch.setattr(gateway_server, "away_task_registry", _AwayTaskRegistry())
    monkeypatch.setattr(gateway_server, "quota_manager", _Quota())
    monkeypatch.setattr(gateway_server, "subscription_manager", _Subscription())
    monkeypatch.setattr(gateway_server, "_ensure_admin_access_token", lambda: "token-1")

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    req = SimpleNamespace(
        headers={},
        cookies={"elyan_admin_session": "token-1"},
        query={},
        remote="127.0.0.1",
        transport=None,
    )
    resp = await gateway_server.ElyanGatewayServer.handle_admin_overview(srv, req)
    payload = json.loads(resp.text)

    assert payload["ok"] is True
    assert payload["users_total"] == 1
    assert payload["tasks_total"] == 2
    assert payload["quota_blocked_users"] == 1


@pytest.mark.asyncio
async def test_handle_admin_user_subscription_updates_tier(monkeypatch):
    calls = []

    class _Subscription:
        @staticmethod
        def set_user_tier(user_id, tier, expiry_days=None):
            calls.append((user_id, tier.value, expiry_days))

        @staticmethod
        def get_subscription_summary(user_id):
            return {"user_id": user_id, "tier": "pro", "expiry_at": 0, "status": "active"}

    class _Quota:
        @staticmethod
        def get_user_stats(user_id):
            _ = user_id
            return {"tier": "pro", "daily_messages": 0, "daily_limit": 500, "monthly_tokens": 0, "monthly_limit": 1000}

    monkeypatch.setattr(gateway_server, "subscription_manager", _Subscription())
    monkeypatch.setattr(gateway_server, "quota_manager", _Quota())
    monkeypatch.setattr(gateway_server, "_ensure_admin_access_token", lambda: "token-1")

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    req = _Req({"tier": "pro", "expiry_days": 30})
    req.match_info = {"user_id": "u-pro"}
    req.cookies = {"elyan_admin_session": "token-1"}

    resp = await gateway_server.ElyanGatewayServer.handle_admin_user_subscription(srv, req)
    payload = json.loads(resp.text)

    assert resp.status == 200
    assert payload["ok"] is True
    assert calls == [("u-pro", "pro", 30)]


@pytest.mark.asyncio
async def test_handle_admin_overview_rejects_non_local_without_token(monkeypatch):
    monkeypatch.setattr(gateway_server, "_ensure_admin_access_token", lambda: "token-1")
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    req = SimpleNamespace(headers={}, cookies={}, query={}, remote="10.0.0.5", transport=None)

    resp = await gateway_server.ElyanGatewayServer.handle_admin_overview(srv, req)
    payload = json.loads(resp.text)

    assert resp.status == 403
    assert payload["ok"] is False


@pytest.mark.asyncio
async def test_handle_module_automations_action_remove_missing_returns_404(monkeypatch):
    class _FakeRegistry:
        @staticmethod
        def unregister(task_id):
            _ = task_id
            return False

        @staticmethod
        def get_module_health(limit=12):
            _ = limit
            return {"summary": {"active_modules": 0, "healthy": 0, "failing": 0, "unknown": 0, "circuit_open": 0}, "modules": []}

        @staticmethod
        def list_module_tasks(include_inactive=True, limit=100):
            _ = (include_inactive, limit)
            return []

    monkeypatch.setattr("core.automation_registry.automation_registry", _FakeRegistry())

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv._require_admin_access = lambda request: (True, "")
    req = _Req({"action": "remove", "task_id": "__missing__"})

    resp = await gateway_server.ElyanGatewayServer.handle_module_automations_action(srv, req)
    payload = json.loads(resp.text)

    assert resp.status == 404
    assert payload["ok"] is False
    assert "task not found" in str(payload.get("error") or "")


@pytest.mark.asyncio
async def test_handle_module_automations_action_bulk_partial_success(monkeypatch):
    class _FakeRegistry:
        @staticmethod
        def set_status(task_id, status):
            _ = status
            return task_id == "t_ok"

        @staticmethod
        def get_module_health(limit=12):
            _ = limit
            return {"summary": {"active_modules": 1, "healthy": 1, "failing": 0, "unknown": 0, "circuit_open": 0}, "modules": []}

        @staticmethod
        def list_module_tasks(include_inactive=True, limit=100):
            _ = (include_inactive, limit)
            return [{"task_id": "t_ok", "module_id": "context_recovery", "status": "active", "health": "healthy"}]

    monkeypatch.setattr("core.automation_registry.automation_registry", _FakeRegistry())
    monkeypatch.setattr(gateway_server, "push_activity", lambda *_a, **_k: None)

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv._require_admin_access = lambda request: (True, "")
    req = _Req({"action": "pause", "task_ids": ["t_ok", "t_missing"]})

    resp = await gateway_server.ElyanGatewayServer.handle_module_automations_action(srv, req)
    payload = json.loads(resp.text)

    assert resp.status == 200
    assert payload["ok"] is False
    assert payload["succeeded"] == 1
    assert payload["failed"] == 1


@pytest.mark.asyncio
async def test_handle_module_automations_update_success(monkeypatch):
    class _FakeRegistry:
        @staticmethod
        def update_module_task(task_id, **kwargs):
            _ = kwargs
            if task_id != "t1":
                return None
            return {"id": "t1", "module_id": "context_recovery", "interval_seconds": 1200}

        @staticmethod
        def get_module_health(limit=12):
            _ = limit
            return {"summary": {"active_modules": 1, "healthy": 1, "failing": 0, "unknown": 0, "circuit_open": 0}, "modules": []}

        @staticmethod
        def list_module_tasks(include_inactive=True, limit=100):
            _ = (include_inactive, limit)
            return [{"task_id": "t1", "module_id": "context_recovery", "status": "active", "health": "healthy"}]

    monkeypatch.setattr("core.automation_registry.automation_registry", _FakeRegistry())

    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    srv._require_admin_access = lambda request: (True, "")
    req = _Req({"task_id": "t1", "interval_seconds": 1200, "timeout_seconds": 80, "status": "paused"})

    resp = await gateway_server.ElyanGatewayServer.handle_module_automations_update(srv, req)
    payload = json.loads(resp.text)

    assert resp.status == 200
    assert payload["ok"] is True
    assert payload["task"]["id"] == "t1"
