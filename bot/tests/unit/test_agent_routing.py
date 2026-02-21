import asyncio
from types import SimpleNamespace
from pathlib import Path

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


class _DummyLLMToolRouter:
    async def generate(self, prompt, role="inference", history=None):
        _ = (prompt, role, history)
        return '{"action":"list_files","params":{"path":"~/Desktop"},"confidence":0.91}'


class _DummyQuickIntent:
    def detect(self, _text):
        return SimpleNamespace(category=IntentCategory.QUESTION)


class _DummyQuickIntentUnknown:
    def detect(self, _text):
        return SimpleNamespace(category=IntentCategory.UNKNOWN)


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


def test_agent_prepare_list_files_uses_desktop_fallback_for_missing_home_path(tmp_path, monkeypatch):
    agent = Agent()
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    (desktop / "Projects").mkdir()

    monkeypatch.setenv("HOME", str(tmp_path))
    params = agent._prepare_tool_params(
        "list_files",
        {"path": str(tmp_path / "Projects")},
        user_input="projects içinde ne var",
        step_name="",
    )
    assert params.get("path") == str(desktop / "Projects")


def test_agent_prepare_list_files_extracts_folder_hint_for_desktop_lookup(tmp_path, monkeypatch):
    agent = Agent()
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    (desktop / "Projects").mkdir()

    monkeypatch.setenv("HOME", str(tmp_path))
    params = agent._prepare_tool_params(
        "list_files",
        {},
        user_input="projects içinde ne var",
        step_name="",
    )
    resolved = Path(str(params.get("path") or "")).expanduser()
    assert resolved.parent.name == "Desktop"
    assert resolved.name.casefold() == "projects"


def test_agent_extract_folder_hint_supports_klasorunu_form():
    agent = Agent()
    hint = agent._extract_folder_hint_from_text("Projects klasörünü listele")
    assert hint == "Projects"


def test_agent_normalize_user_input_preserves_folder_case():
    normalized = Agent._normalize_user_input("Projects klasörünü listele")
    assert "Projects" in normalized


def test_agent_prepare_list_files_uses_last_directory_context_when_no_hint(tmp_path, monkeypatch):
    agent = Agent()
    monkeypatch.setenv("HOME", str(tmp_path))
    last_dir = tmp_path / "Desktop" / "Projects"
    last_dir.mkdir(parents=True)
    agent.file_context["last_dir"] = str(last_dir)

    params = agent._prepare_tool_params(
        "list_files",
        {},
        user_input="içindekileri göster",
        step_name="",
    )
    assert params.get("path") == str(last_dir)


def test_agent_infer_general_tool_intent_terminal_command():
    agent = Agent()
    intent = agent._infer_general_tool_intent("terminalde pwd komutunu çalıştır")
    assert intent is not None
    assert intent.get("action") == "run_safe_command"
    assert intent.get("params", {}).get("command") == "pwd"


def test_agent_infer_general_tool_intent_move_file():
    agent = Agent()
    intent = agent._infer_general_tool_intent("not.txt dosyasını Reports klasörüne taşı")
    assert intent is not None
    assert intent.get("action") == "move_file"
    assert str(intent.get("params", {}).get("source", "")).endswith("not.txt")
    assert "Reports" in str(intent.get("params", {}).get("destination", ""))


def test_agent_infer_general_tool_intent_rename_file():
    agent = Agent()
    intent = agent._infer_general_tool_intent("not.txt dosyasını rapor.txt olarak yeniden adlandır")
    assert intent is not None
    assert intent.get("action") == "rename_file"
    assert str(intent.get("params", {}).get("path", "")).endswith("not.txt")
    assert intent.get("params", {}).get("new_name") == "rapor.txt"


def test_agent_execute_tool_uses_last_dir_context_for_followup_read(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    base_dir = tmp_path / "Desktop" / "Projects"
    base_dir.mkdir(parents=True)

    captured = {}

    async def _fake_list_files(path="."):
        return {"success": True, "path": str(base_dir), "items": [{"name": "not.txt"}]}

    async def _fake_read_file(path):
        captured["path"] = path
        return {"success": True, "path": path, "content": "ok"}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"list_files": _fake_list_files, "read_file": _fake_read_file})

    first = asyncio.run(agent._execute_tool("list_files", {"path": str(base_dir)}, user_input="projects içinde ne var"))
    second = asyncio.run(agent._execute_tool("read_file", {}, user_input="not.txt içinde ne var"))

    assert first.get("success") is True
    assert second.get("success") is True
    assert captured.get("path") == str(base_dir / "not.txt")


def test_agent_execute_tool_prepares_move_file_paths_from_context(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    base_dir = tmp_path / "Desktop" / "Projects"
    dest_dir = tmp_path / "Desktop" / "Reports"
    base_dir.mkdir(parents=True)
    dest_dir.mkdir(parents=True)
    agent.file_context["last_dir"] = str(base_dir)
    monkeypatch.setenv("HOME", str(tmp_path))

    captured = {}

    async def _fake_move_file(source, destination):
        captured["source"] = source
        captured["destination"] = destination
        return {"success": True, "source": source, "destination": destination}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"move_file": _fake_move_file})
    result = asyncio.run(
        agent._execute_tool(
            "move_file",
            {},
            user_input="not.txt dosyasını Reports klasörüne taşı",
            step_name="Taşı",
        )
    )

    assert result.get("success") is True
    assert captured.get("source") == str(base_dir / "not.txt")
    assert captured.get("destination") == str(dest_dir)


def test_agent_execute_tool_prepares_rename_file_from_natural_text(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    base_dir = tmp_path / "Desktop" / "Projects"
    base_dir.mkdir(parents=True)
    agent.file_context["last_dir"] = str(base_dir)
    monkeypatch.setenv("HOME", str(tmp_path))

    captured = {}

    async def _fake_rename_file(path, new_name):
        captured["path"] = path
        captured["new_name"] = new_name
        return {"success": True, "path": str(Path(path).with_name(new_name))}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"rename_file": _fake_rename_file})
    result = asyncio.run(
        agent._execute_tool(
            "rename_file",
            {},
            user_input="not.txt dosyasını rapor.txt olarak yeniden adlandır",
            step_name="Yeniden adlandır",
        )
    )

    assert result.get("success") is True
    assert captured.get("path") == str(base_dir / "not.txt")
    assert captured.get("new_name") == "rapor.txt"


def test_agent_infer_general_tool_intent_uses_last_path_for_pronoun_delete(tmp_path):
    agent = Agent()
    last_file = tmp_path / "Desktop" / "Projects" / "not.txt"
    last_file.parent.mkdir(parents=True)
    agent.file_context["last_path"] = str(last_file)
    agent.file_context["last_dir"] = str(last_file.parent)

    intent = agent._infer_general_tool_intent("bunu sil")
    assert intent is not None
    assert intent.get("action") == "delete_file"
    assert intent.get("params", {}).get("path") == str(last_file)


def test_agent_infer_multi_task_intent_from_free_form_sequence(tmp_path, monkeypatch):
    agent = Agent()
    monkeypatch.setenv("HOME", str(tmp_path))
    parts = agent._split_multi_step_text("Projects klasörünü listele sonra not.txt oku ve ardından bunu sil")
    assert len(parts) >= 3

    intent = agent._infer_multi_task_intent("Projects klasörünü listele sonra not.txt oku ve ardından bunu sil")
    assert intent is not None
    assert intent.get("action") == "multi_task"
    tasks = intent.get("tasks", [])
    assert [t.get("action") for t in tasks] == ["list_files", "read_file", "delete_file"]
    read_path = str(tasks[1].get("params", {}).get("path", ""))
    delete_path = str(tasks[2].get("params", {}).get("path", ""))
    assert read_path.endswith("Desktop/Projects/not.txt")
    assert delete_path == read_path


def test_agent_infer_multi_task_intent_dense_without_connectors():
    agent = Agent()
    intent = agent._infer_multi_task_intent("Safari aç köpekler araştır masaüstüne kaydet")
    assert intent is not None
    assert intent.get("action") == "multi_task"
    actions = [t.get("action") for t in intent.get("tasks", [])]
    assert "open_app" in actions
    assert "research" in actions
    assert "write_file" in actions


def test_agent_execute_tool_move_uses_last_path_when_user_says_bunu(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    base_dir = tmp_path / "Desktop" / "Projects"
    dest_dir = tmp_path / "Desktop" / "Reports"
    base_dir.mkdir(parents=True)
    dest_dir.mkdir(parents=True)
    agent.file_context["last_path"] = str(base_dir / "not.txt")
    agent.file_context["last_dir"] = str(base_dir)
    monkeypatch.setenv("HOME", str(tmp_path))

    captured = {}

    async def _fake_move_file(source, destination):
        captured["source"] = source
        captured["destination"] = destination
        return {"success": True, "source": source, "destination": destination}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"move_file": _fake_move_file})
    result = asyncio.run(
        agent._execute_tool(
            "move_file",
            {},
            user_input="bunu Reports klasörüne taşı",
            step_name="Taşı",
        )
    )

    assert result.get("success") is True
    assert captured.get("source") == str(base_dir / "not.txt")
    assert captured.get("destination") == str(dest_dir)


def test_agent_execute_tool_rename_uses_last_path_when_user_says_bunu(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    base_dir = tmp_path / "Desktop" / "Projects"
    base_dir.mkdir(parents=True)
    agent.file_context["last_path"] = str(base_dir / "not.txt")
    agent.file_context["last_dir"] = str(base_dir)
    monkeypatch.setenv("HOME", str(tmp_path))

    captured = {}

    async def _fake_rename_file(path, new_name):
        captured["path"] = path
        captured["new_name"] = new_name
        return {"success": True, "path": str(Path(path).with_name(new_name))}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"rename_file": _fake_rename_file})
    result = asyncio.run(
        agent._execute_tool(
            "rename_file",
            {},
            user_input="bunu rapor.txt olarak yeniden adlandır",
            step_name="Yeniden adlandır",
        )
    )

    assert result.get("success") is True
    assert captured.get("path") == str(base_dir / "not.txt")
    assert captured.get("new_name") == "rapor.txt"


def test_agent_process_executes_free_form_multi_step_sequence(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntentUnknown()
    agent.intent_parser = SimpleNamespace(parse=lambda _text: {"action": "chat", "params": {}})
    agent.learning = _DummyLearning(quick_match_action=None)
    agent.user_profile = _DummyProfile()
    monkeypatch.setattr("core.agent.skill_manager.list_skills", lambda available=False, enabled_only=True: [])
    monkeypatch.setenv("HOME", str(tmp_path))

    base_dir = tmp_path / "Desktop" / "Projects"
    base_dir.mkdir(parents=True)
    captured = {"read": "", "delete": ""}

    async def _fake_list_files(path="."):
        return {"success": True, "path": str(base_dir), "items": [{"name": "not.txt"}]}

    async def _fake_read_file(path):
        captured["read"] = path
        return {"success": True, "path": path, "content": "merhaba"}

    async def _fake_delete_file(path, force=False):
        _ = force
        captured["delete"] = path
        return {"success": True, "path": path, "message": f"silindi: {Path(path).name}"}

    monkeypatch.setattr(
        "core.agent.AVAILABLE_TOOLS",
        {"list_files": _fake_list_files, "read_file": _fake_read_file, "delete_file": _fake_delete_file},
    )

    response = asyncio.run(agent.process("Projects klasörünü listele sonra not.txt oku ve ardından bunu sil"))
    assert "[1]" in response and "[2]" in response and "[3]" in response
    assert captured["read"].endswith("Desktop/Projects/not.txt")
    assert captured["delete"] == captured["read"]


def test_agent_process_executes_dense_multi_step_sequence(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntentUnknown()
    agent.intent_parser = SimpleNamespace(parse=lambda _text: {"action": "chat", "params": {}})
    agent.learning = _DummyLearning(quick_match_action=None)
    agent.user_profile = _DummyProfile()
    monkeypatch.setattr("core.agent.skill_manager.list_skills", lambda available=False, enabled_only=True: [])
    monkeypatch.setenv("HOME", str(tmp_path))

    captured = {"app": "", "saved_content": ""}

    async def _fake_open_app(app_name=None):
        captured["app"] = app_name or ""
        return {"success": True, "message": f"{app_name} açıldı"}

    async def _fake_research(topic: str, depth: str = "standard"):
        _ = (topic, depth)
        return {"success": True, "summary": "Köpekler hakkında kısa araştırma özeti"}

    async def _fake_write_file(path, content):
        captured["saved_content"] = content
        return {"success": True, "path": path}

    monkeypatch.setattr(
        "core.agent.AVAILABLE_TOOLS",
        {"open_app": _fake_open_app, "advanced_research": _fake_research, "write_file": _fake_write_file},
    )

    response = asyncio.run(agent.process("Safari aç köpekler araştır masaüstüne kaydet"))
    assert "[1]" in response and "[2]" in response and "[3]" in response
    assert captured["app"] == "Safari"
    assert "araştırma özeti" in captured["saved_content"].lower()


def test_agent_process_uses_chat_fallback_when_plan_not_safe_for_information_question(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntentUnknown()
    agent.intent_parser = SimpleNamespace(parse=lambda _text: {"action": "chat", "params": {}})
    agent.learning = _DummyLearning(quick_match_action=None)
    agent.user_profile = _DummyProfile()
    monkeypatch.setattr(agent, "_is_likely_chat_message", lambda _text: True)
    monkeypatch.setattr(agent, "_should_route_to_llm_chat", lambda *_args, **_kwargs: False)

    class _UnsafePlanner:
        async def create_plan(self, _user_input, _ctx):
            return SimpleNamespace(subtasks=[])

        def evaluate_plan_quality(self, _subtasks, _user_input):
            return {"safe_to_run": False}

    agent.planner = _UnsafePlanner()
    response = asyncio.run(agent.process("fatih sultan kimdir"))
    assert response == "ok"


def test_agent_process_keeps_rejection_for_non_information_unsafe_plan(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntentUnknown()
    agent.intent_parser = SimpleNamespace(parse=lambda _text: {"action": "chat", "params": {}})
    agent.learning = _DummyLearning(quick_match_action=None)
    agent.user_profile = _DummyProfile()
    monkeypatch.setattr(agent, "_is_likely_chat_message", lambda _text: True)
    monkeypatch.setattr(agent, "_should_route_to_llm_chat", lambda *_args, **_kwargs: False)

    class _UnsafePlanner:
        async def create_plan(self, _user_input, _ctx):
            return SimpleNamespace(subtasks=[])

        def evaluate_plan_quality(self, _subtasks, _user_input):
            return {"safe_to_run": False}

    agent.planner = _UnsafePlanner()
    response = asyncio.run(agent.process("masaüstündeki dosyaları sil"))
    assert "güvenli bir şekilde planlayamadım" in response.lower()


def test_agent_process_uses_llm_tool_fallback_when_parser_returns_chat(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLMToolRouter()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntentUnknown()
    agent.intent_parser = SimpleNamespace(parse=lambda _text: {"action": "chat", "params": {}})
    agent.learning = _DummyLearning(quick_match_action=None)
    agent.user_profile = _DummyProfile()
    monkeypatch.setattr("core.agent.skill_manager.list_skills", lambda available=False, enabled_only=True: [])

    async def _fake_list_files(path="."):
        _ = path
        return {"success": True, "items": [{"name": "a.txt"}, {"name": "b.txt"}]}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"list_files": _fake_list_files})
    response = asyncio.run(agent.process("dosyaları bir kontrol eder misin"))
    assert "Klasör içeriği:" in response
    assert "a.txt" in response


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


def test_agent_execute_tool_infers_delete_path_from_user_text(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    captured = {}

    async def _fake_delete_file(path, force=False):
        captured["path"] = path
        captured["force"] = force
        return {"success": True, "path": path}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"delete_file": _fake_delete_file})
    result = asyncio.run(
        agent._execute_tool(
            "delete_file",
            {},
            user_input="SS_1771495518.png yi sil",
            step_name="Dosyayı sil",
        )
    )

    assert result["success"] is True
    assert captured.get("path", "").endswith("SS_1771495518.png")


def test_agent_execute_tool_retries_on_missing_required_argument(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    calls = []

    async def _legacy_custom(**kwargs):
        calls.append(dict(kwargs))
        if "message" not in kwargs:
            raise TypeError("custom_tool() missing 1 required positional argument: 'message'")
        return {"success": True, "message": kwargs["message"]}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"custom_tool": _legacy_custom})
    result = asyncio.run(agent._execute_tool("custom_tool", {}, user_input="yarın raporu hatırlat", step_name="Bildirim"))
    assert result["success"] is True
    assert len(calls) == 2
    assert calls[-1].get("message")


def test_agent_execute_tool_repairs_not_found_path_with_context(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    base_dir = tmp_path / "Desktop" / "Projects"
    base_dir.mkdir(parents=True)
    target = base_dir / "Not.txt"
    target.write_text("hello")
    monkeypatch.setenv("HOME", str(tmp_path))
    agent.file_context["last_dir"] = str(base_dir)

    attempts = []

    async def _read_file(path):
        attempts.append(path)
        if not Path(path).exists():
            raise FileNotFoundError(f"Path does not exist: {path}")
        return {"success": True, "path": path, "content": "ok"}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"read_file": _read_file})
    wrong_path = str(tmp_path / "Desktop" / "archive" / "not.txt")
    result = asyncio.run(
        agent._execute_tool(
            "read_file",
            {"path": wrong_path},
            user_input="not.txt içinde ne var",
            step_name="Oku",
        )
    )
    assert result["success"] is True
    assert len(attempts) >= 2
    assert attempts[-1] == str(target)


def test_agent_postprocess_marks_verification_warning_when_output_missing(tmp_path):
    agent = Agent()
    agent.file_context["last_dir"] = str(tmp_path)
    result = agent._postprocess_tool_result(
        "write_file",
        {"path": str(tmp_path / "missing.txt")},
        {"success": True, "path": str(tmp_path / "missing.txt")},
        user_input="",
    )
    assert result.get("success") is True
    assert result.get("verified") is False
    assert "verification_warning" in result


def test_agent_postprocess_marks_verified_for_existing_output(tmp_path):
    agent = Agent()
    file_path = tmp_path / "ok.txt"
    file_path.write_text("hello")
    result = agent._postprocess_tool_result(
        "write_file",
        {"path": str(file_path)},
        {"success": True, "path": str(file_path)},
        user_input="",
    )
    assert result.get("verified") is True
    assert result.get("size_bytes", 0) > 0


def test_agent_execute_tool_adapts_legacy_openapp_signature(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    captured = {}

    async def _legacy_openapp(appname):
        captured["appname"] = appname
        return {"success": True, "message": f"{appname} opened."}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"open_app": _legacy_openapp})
    result = asyncio.run(
        agent._execute_tool(
            "open_app",
            {"app_name": "Safari"},
            user_input="safariyi aç",
            step_name="Safari aç",
        )
    )
    assert result["success"] is True
    assert captured.get("appname") == "Safari"


def test_agent_execute_tool_adapts_legacy_notification_body_signature(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    captured = {}

    async def _legacy_notify(title, body):
        captured["title"] = title
        captured["body"] = body
        return {"success": True, "message": "ok"}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"send_notification": _legacy_notify})
    result = asyncio.run(
        agent._execute_tool(
            "send_notification",
            {"title": "Hatırlatma", "message": "İlaç iç"},
            user_input="saat 22 de ilaç içmem gerekiyor hatırlat",
            step_name="Bildirim",
        )
    )
    assert result["success"] is True
    assert captured.get("body") == "İlaç iç"


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


def test_agent_multi_task_reorders_research_before_empty_word_write(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntent()
    agent.intent_parser = SimpleNamespace(
        parse=lambda _text: {
            "action": "multi_task",
            "tasks": [
                {
                    "id": "task_1",
                    "action": "create_word_document",
                    "params": {"filename": "rapor.docx", "content": "", "path": "~/Desktop/rapor.docx"},
                    "description": "Word dosyası oluştur",
                },
                {
                    "id": "task_2",
                    "action": "research",
                    "params": {"topic": "köpekler", "depth": "standard"},
                    "description": "Köpekler hakkında araştır",
                },
            ],
        }
    )

    captured = {}

    async def _fake_advanced_research(topic: str, depth: str = "standard"):
        _ = (topic, depth)
        return {"success": True, "summary": "Köpekler hakkında araştırma özeti"}

    async def _fake_write_word(path=None, content="", title=None, paragraphs=None):
        captured["path"] = path
        captured["content"] = content
        _ = (title, paragraphs)
        return {"success": True, "path": path or "~/Desktop/rapor.docx"}

    monkeypatch.setattr(
        "core.agent.AVAILABLE_TOOLS",
        {"advanced_research": _fake_advanced_research, "write_word": _fake_write_word},
    )

    response = asyncio.run(agent.process("word dosyası oluştur ve içine köpek araştırmasını yaz"))
    assert "araştırma özeti" in str(captured.get("content", "")).lower()
    assert "Köpekler hakkında araştırma özeti" in response


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


def test_agent_infer_save_intent_routes_to_write_file():
    agent = Agent()
    intent = agent._infer_save_intent("Bunu masaüstüne dosya olarak kaydet")
    assert intent is not None
    assert intent.get("action") == "write_file"
    assert str(intent.get("params", {}).get("path", "")).endswith("not.txt")


def test_agent_prepare_write_word_prefers_last_research_cache(monkeypatch):
    agent = Agent()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    monkeypatch.setattr(
        Agent,
        "_get_recent_research_text",
        staticmethod(lambda: "Köpekler hakkında güncel araştırma özeti\n- Beslenme düzeni önemli\n- Aşı takibi gerekli"),
    )

    params = agent._prepare_tool_params(
        "write_word",
        {"path": "~/Desktop/rapor.docx", "content": ""},
        user_input="bunu word olarak kaydet",
        step_name="Rapor kaydet",
    )
    content = str(params.get("content", ""))
    assert "Köpekler hakkında güncel araştırma özeti" in content
    assert "Beslenme düzeni önemli" in content


def test_agent_information_question_bypasses_planner_when_parser_is_chat():
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntentUnknown()
    agent.intent_parser = SimpleNamespace(parse=lambda _text: {"action": "chat", "params": {}})
    agent.learning = _DummyLearning()
    agent.user_profile = _DummyProfile()

    async def _unexpected_plan(*_args, **_kwargs):
        raise AssertionError("planner must not run for simple informational questions")

    agent.planner = SimpleNamespace(
        create_plan=_unexpected_plan,
        evaluate_plan_quality=lambda *_args, **_kwargs: {"safe_to_run": True},
    )

    response = asyncio.run(agent.process("fatih sultan kimdir"))
    assert response.strip() == "ok"


def test_task_needs_previous_output_detects_placeholder_content():
    agent = Agent()
    needs = agent._task_needs_previous_output(
        {
            "action": "create_word_document",
            "params": {"content": "İçerik belirtilmedi."},
        }
    )
    assert needs is True

    ready = agent._task_needs_previous_output(
        {
            "action": "create_word_document",
            "params": {"content": "Gerçek rapor içeriği"},
        }
    )
    assert ready is False
