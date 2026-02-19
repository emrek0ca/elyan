import asyncio
from types import SimpleNamespace

from core.agent import Agent, ACTION_TO_TOOL
from core.quick_intent import IntentCategory


class _DummyMemory:
    def get_recent_conversations(self, user_id, limit=5):
        return []

    def store_conversation(self, user_id, user_input, bot_response):
        return None


class _DummyTools:
    async def execute(self, tool_name, params):
        raise ValueError(f"not found: {tool_name}")


class _DummyLLM:
    async def generate(self, prompt, role="inference", history=None):
        return "ok"


class _DummyQuickIntent:
    def detect(self, _text):
        return SimpleNamespace(category=IntentCategory.QUESTION)


class _DummyLearning:
    def __init__(self, quick_match_action=None, prefs=None):
        self.quick_match_action = quick_match_action
        self.prefs = prefs or {}
        self.records = []

    def quick_match(self, _text):
        return self.quick_match_action

    def get_preferences(self, min_confidence=0.6):
        _ = min_confidence
        return dict(self.prefs)

    async def record_interaction(self, **kwargs):
        self.records.append(kwargs)


class _DummyProfile:
    def update_after_interaction(self, user_id, **kwargs):
        _ = (user_id, kwargs)
        return None


def test_action_to_tool_includes_research_mapping():
    assert ACTION_TO_TOOL["research"] == "advanced_research"


def test_agent_direct_intent_uses_available_tools(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntent()
    agent.intent_parser = SimpleNamespace(
        parse=lambda _text: {"action": "list_files", "params": {"path": "~/Desktop"}, "reply": "list"}
    )

    async def _fake_list_files(path="."):
        assert path == "~/Desktop"
        return {"success": True, "items": [{"name": "a.txt"}, {"name": "b.txt"}]}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"list_files": _fake_list_files})
    response = asyncio.run(agent.process("masaüstünde ne var"))
    assert "Klasör içeriği:" in response
    assert "a.txt" in response


def test_agent_execute_tool_maps_research(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    captured = {}

    async def _fake_advanced_research(topic: str, depth: str = "standard"):
        captured["topic"] = topic
        captured["depth"] = depth
        return {"success": True, "summary": "done"}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"advanced_research": _fake_advanced_research})
    result = asyncio.run(
        agent._execute_tool("research", {"topic": "iphone"}, user_input="iphone araştır", step_name="Araştır")
    )
    assert result["success"] is True
    assert captured["topic"] == "iphone"


def test_task_engine_bridge_loads_legacy_engine():
    from core.task_engine import get_task_engine

    engine = get_task_engine()
    assert hasattr(engine, "execute_task")


def test_agent_resolve_tool_name_aliases():
    agent = Agent()
    assert agent._resolve_tool_name("screenshot") == "take_screenshot"
    assert agent._resolve_tool_name("generate-image") == "create_visual_asset_pack"
    assert agent._resolve_tool_name("openapp") == "open_app"


def test_agent_prepare_tool_params_infers_app_name_from_input():
    agent = Agent()
    params = agent._prepare_tool_params(
        "open_app",
        {},
        user_input="safariyi aç ve köpekler hakkında araştırma yap",
        step_name="Uygulamayı aç",
    )
    assert params.get("app_name") == "Safari"


def test_agent_execute_tool_normalizes_openapp_appname(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    captured = {}

    async def _fake_open_app(app_name=None):
        captured["app_name"] = app_name
        return {"success": True, "message": f"{app_name} opened."}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"open_app": _fake_open_app})

    result = asyncio.run(
        agent._execute_tool(
            "openapp",
            {"appname": "Safari"},
            user_input="safariyi aç",
            step_name="Safari aç",
        )
    )

    assert result["success"] is True
    assert captured["app_name"] == "Safari"


def test_agent_extract_topic_removes_app_open_prefix():
    agent = Agent()
    topic = agent._extract_topic("safariyi aç ve köpekler hakkında araştırma yap")
    assert "safari" not in topic
    assert "köpekler" in topic


def test_agent_prepare_advanced_research_sanitizes_topic_noise():
    agent = Agent()
    params = agent._prepare_tool_params(
        "advanced_research",
        {"topic": "safariyi aç ve köpekler hakkında araştırma yap"},
        user_input="safariyi aç ve köpekler hakkında araştırma yap",
        step_name="Araştır",
    )
    assert params.get("topic") == "köpekler"


def test_agent_execute_tool_preserves_message_param_for_notification(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    captured = {}

    async def _fake_send_notification(title="Elyan", message=""):
        captured["title"] = title
        captured["message"] = message
        return {"success": True, "message": "ok"}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"send_notification": _fake_send_notification})
    result = asyncio.run(
        agent._execute_tool(
            "send_notification",
            {"title": "Hatırlatma", "message": "İlaç iç"},
            user_input="saat 22'de ilaç içmeyi hatırlat",
            step_name="Bildirim",
        )
    )
    assert result["success"] is True
    assert captured["message"] == "İlaç iç"


def test_agent_prepare_write_file_uses_recent_assistant_text_when_needed():
    agent = Agent()
    agent.current_user_id = 42

    class _Mem:
        def get_recent_conversations(self, user_id, limit=8):
            assert user_id == 42
            return [
                {
                    "user_message": "köpekler hakkında araştırma yap",
                    "bot_response": '{"message":"Köpekler hakkında kısa özet"}',
                }
            ]

    agent.kernel = SimpleNamespace(memory=_Mem(), tools=_DummyTools())
    params = agent._prepare_tool_params(
        "write_file",
        {"path": "~/Desktop/not.txt", "content": ""},
        user_input="Bunu masaüstüne dosya olarak kaydet",
        step_name="Kaydet",
    )
    assert "Köpekler hakkında kısa özet" in params.get("content", "")


def test_agent_prepare_set_volume_supports_mute_intent():
    agent = Agent()
    params = agent._prepare_tool_params(
        "set_volume",
        {"mute": True},
        user_input="sesi kapat",
        step_name="Ses",
    )
    assert params.get("mute") is True


def test_agent_prepare_get_process_info_defaults_without_query():
    agent = Agent()
    params = agent._prepare_tool_params(
        "get_process_info",
        {},
        user_input="hangi uygulamalar çalışıyor",
        step_name="Process",
    )
    assert "process_name" in params
    assert params["process_name"] == ""


def test_agent_execute_tool_handles_unavailable_resolved_tool(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    # Simulate a resolution that points to an unavailable tool function.
    monkeypatch.setattr(agent, "_resolve_tool_name", lambda _name: "write_excel")
    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"write_excel": None})

    result = asyncio.run(
        agent._execute_tool(
            "create_excel",
            {"filename": "x.xlsx"},
            user_input="excel oluştur",
            step_name="Excel",
        )
    )
    assert result.get("success") is False
    assert "unavailable" in str(result.get("error", "")).lower()


def test_agent_runs_multi_task_intent_directly(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntent()
    agent.intent_parser = SimpleNamespace(
        parse=lambda _text: {
            "action": "multi_task",
            "tasks": [
                {"id": "task_1", "action": "list_files", "params": {"path": "~/Desktop"}, "description": "Listele"},
                {"id": "task_2", "action": "take_screenshot", "params": {"filename": "elyan_test"}, "description": "Ekran"},
            ],
        }
    )

    async def _fake_list_files(path="."):
        return {"success": True, "items": [{"name": "a.txt"}]}

    async def _fake_screenshot(filename=None):
        return {"success": True, "path": f"/tmp/{filename or 'shot'}.png"}

    monkeypatch.setattr(
        "core.agent.AVAILABLE_TOOLS",
        {"list_files": _fake_list_files, "take_screenshot": _fake_screenshot},
    )
    response = asyncio.run(agent.process("google aç ve sonra ekran görüntüsü al"))
    assert "[1] Listele" in response
    assert "a.txt" in response
    assert "/tmp/elyan_test.png" in response


def test_agent_uses_learning_quick_match_for_safe_action(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntent()
    agent.intent_parser = SimpleNamespace(parse=lambda _text: {"action": "chat", "params": {}})
    agent.learning = _DummyLearning(quick_match_action="take_screenshot")
    agent.user_profile = _DummyProfile()

    async def _fake_screenshot(filename=None):
        _ = filename
        return {"success": True, "path": "/tmp/learned.png"}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"take_screenshot": _fake_screenshot})
    response = asyncio.run(agent.process("ss al"))
    assert "/tmp/learned.png" in response
    assert agent.learning.records
    assert agent.learning.records[-1].get("action") == "take_screenshot"


def test_agent_skill_fallback_routes_research_when_parser_returns_chat(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntent()
    agent.intent_parser = SimpleNamespace(parse=lambda _text: {"action": "chat", "params": {}})
    agent.learning = _DummyLearning(quick_match_action=None)
    agent.user_profile = _DummyProfile()

    monkeypatch.setattr(
        "core.agent.skill_manager.list_skills",
        lambda available=False, enabled_only=True: [{"name": "research", "enabled": True}],
    )
    monkeypatch.setattr(
        "core.agent.skill_registry.get_skill_for_command",
        lambda token: {"name": "research"} if token in {"araştır", "arastir", "research"} else None,
    )

    captured = {}

    async def _fake_advanced_research(topic: str, depth: str = "standard"):
        captured["topic"] = topic
        captured["depth"] = depth
        return {"success": True, "summary": "Araştırma tamamlandı"}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"advanced_research": _fake_advanced_research})
    response = asyncio.run(agent.process("köpekler araştır"))
    assert "Araştırma tamamlandı" in response
    assert "köpekler" in captured.get("topic", "")


def test_agent_prepare_research_params_uses_learned_response_length():
    agent = Agent()
    agent.learning = _DummyLearning(prefs={"response_length": "short"})
    params = agent._prepare_tool_params(
        "advanced_research",
        {"topic": "köpekler"},
        user_input="köpekler araştır",
        step_name="",
    )
    assert params.get("depth") == "quick"
