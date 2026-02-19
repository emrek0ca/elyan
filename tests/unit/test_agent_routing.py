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
