import asyncio
import time
from types import SimpleNamespace
from pathlib import Path

from core.agent import Agent, ACTION_TO_TOOL
from core.intent_parser import IntentParser
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
    async def generate(self, prompt, role="inference", history=None, **kwargs):
        return "ok"


class _DummyLLMToolRouter:
    async def generate(self, prompt, role="inference", history=None, **kwargs):
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

    def check_approval_confidence(self, _action, _params):
        return {"auto_approve": True, "confidence": 1.0, "reason": "test-double"}

    def generate_smart_hint(self, last_error=None):
        _ = last_error
        return None


class _DummyProfile:
    def profile_summary(self, user_id):
        _ = user_id
        return {}

    def update_after_interaction(self, user_id, **kwargs):
        _ = (user_id, kwargs)
        return None


def test_action_to_tool_includes_research_mapping():
    assert ACTION_TO_TOOL["research"] == "advanced_research"
    assert ACTION_TO_TOOL["research_and_document"] == "research_document_delivery"


def test_agent_extract_first_json_object_handles_fenced_payload():
    raw = """Model çıktısı:
```json
{"action":"list_files","params":{"path":"~/Desktop"},"confidence":0.91}
```"""
    parsed = Agent._extract_first_json_object(raw)
    assert isinstance(parsed, dict)
    assert parsed.get("action") == "list_files"
    assert parsed.get("params", {}).get("path") == "~/Desktop"


def test_agent_extract_first_json_object_from_array_payload():
    raw = '[{"action":"read_file","params":{"path":"~/Desktop/not.md"}}]'
    parsed = Agent._extract_first_json_object(raw)
    assert isinstance(parsed, dict)
    assert parsed.get("action") == "read_file"


def test_agent_sanitize_project_file_plan_filters_and_adds_defaults():
    agent = Agent()
    plan = [
        {"path": "../escape.py", "purpose": "invalid"},
        {"path": "app/main.py", "purpose": "entry"},
        {"path": "app/main.py", "purpose": "duplicate"},
    ]
    cleaned = agent._sanitize_project_file_plan(plan, project_kind="app", stack="python")
    paths = [row["path"] for row in cleaned]
    assert "../escape.py" not in paths
    assert "app/main.py" in paths
    assert "README.md" in paths
    assert "main.py" in paths
    assert "docs/ARCHITECTURE.md" in paths
    assert "docs/QUALITY_CHECKLIST.md" in paths


def test_agent_assess_generated_content_quality_detects_python_syntax_error():
    issues = Agent._assess_generated_content_quality("def x(:\n    pass", ext=".py")
    assert "python_syntax_error" in issues


def test_agent_assess_generated_content_quality_flags_weak_readme_structure():
    issues = Agent._assess_generated_content_quality(
        "Basit metin ama bölüm yok",
        ext=".md",
        rel_path="README.md",
    )
    assert "weak_document_structure" in issues


def test_agent_default_markdown_template_for_quality_checklist():
    content = Agent._default_project_markdown_content(
        "docs/QUALITY_CHECKLIST.md",
        project_name="Demo",
        brief="kısa",
        stack_desc="Python",
        tech_mode="latest",
        coding_standards="clean_code",
    )
    assert "Quality Checklist" in content
    assert "- [ ]" in content


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


def test_should_route_to_llm_chat_for_short_ambiguous_chat_like_input():
    parsed_intent = {"action": "chat", "params": {"message": "Arkaplanda"}}
    quick = _DummyQuickIntentUnknown().detect("Arkaplanda")
    assert Agent._should_route_to_llm_chat("Arkaplanda", parsed_intent, quick) is True


def test_should_not_route_to_llm_chat_for_tool_like_command_even_if_chat_action():
    parsed_intent = {"action": "chat", "params": {"message": "not.txt yi sil"}}
    quick = _DummyQuickIntentUnknown().detect("not.txt yi sil")
    assert Agent._should_route_to_llm_chat("not.txt yi sil", parsed_intent, quick) is False


def test_agent_short_ambiguous_input_returns_clarification_without_llm():
    agent = Agent()
    agent.llm = None
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntentUnknown()
    agent.intent_parser = IntentParser()
    agent.learning = _DummyLearning(quick_match_action=None)
    agent.user_profile = _DummyProfile()

    response = asyncio.run(agent.process("Arkaplanda"))
    assert "Arka plan komutu belirsiz" in response


def test_agent_process_chat_fallback_when_llm_missing(monkeypatch):
    agent = Agent()
    agent.llm = None
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools(), llm=None)
    agent.quick_intent = _DummyQuickIntent()
    agent.intent_parser = SimpleNamespace(parse=lambda _text: {"action": "chat", "params": {"message": "Merhaba"}})
    agent.learning = _DummyLearning(quick_match_action=None)
    agent.user_profile = _DummyProfile()
    monkeypatch.setattr(agent, "_should_route_to_llm_chat", lambda *_args, **_kwargs: True)

    response = asyncio.run(agent.process("Merhaba"))
    assert "LLM sağlayıcısına şu an erişemiyorum" in response


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


def test_agent_extract_folder_hint_supports_create_folder_form():
    agent = Agent()
    hint = agent._extract_folder_hint_from_text("masaüstünde elyan-test klasörü oluştur")
    assert hint == "elyan-test"


def test_agent_prepare_create_folder_preserves_requested_name():
    agent = Agent()
    params = agent._prepare_tool_params(
        "create_folder",
        {},
        user_input="masaüstünde elyan-test klasörü oluştur",
        step_name="",
    )
    assert str(params.get("path", "")).endswith("/Desktop/elyan-test")


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


def test_agent_extract_terminal_command_cleans_komutu_suffix():
    command = Agent._extract_terminal_command_from_text("terminalden cd desktop komutu çalıştır")
    assert command == "cd ~/Desktop"


def test_agent_extract_terminal_command_handles_openip_connector():
    command = Agent._extract_terminal_command_from_text("terminal açıp elyan restart komutunu çalıştır")
    assert command == "elyan restart"


def test_agent_split_multi_step_text_handles_turkish_ip_connector():
    parts = Agent._split_multi_step_text("terminal açıp elyan restart komutunu çalıştır")
    assert len(parts) >= 2
    assert "terminal aç" in parts[0]
    assert "elyan restart" in parts[1]


def test_agent_execute_tool_infers_missing_command_for_run_safe_command(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    captured = {}

    async def _fake_run_safe_command(command):
        captured["command"] = command
        return {"success": True, "output": "/tmp"}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"run_safe_command": _fake_run_safe_command})
    result = asyncio.run(
        agent._execute_tool(
            "run_safe_command",
            {},
            user_input="terminalde pwd komutunu çalıştır",
            step_name="Komut çalıştır",
        )
    )
    assert result.get("success") is True
    assert captured.get("command") == "pwd"


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


def test_agent_infer_general_tool_intent_research_document_delivery():
    agent = Agent()
    intent = agent._infer_general_tool_intent(
        "köpekler hakkında kapsamlı araştırma yap, word ve excel raporu hazırla ve bana telegramdan gönder"
    )
    assert intent is not None
    assert intent.get("action") == "research_document_delivery"
    params = intent.get("params", {})
    assert params.get("include_word") is True
    assert params.get("include_excel") is True


def test_agent_infer_general_tool_intent_research_document_delivery_defaults_to_word_only():
    agent = Agent()
    intent = agent._infer_general_tool_intent("fourier denklem hakkında araştırma yap ve rapor hazırla")
    assert intent is not None
    assert intent.get("action") == "research_document_delivery"
    params = intent.get("params", {})
    assert params.get("include_word") is True
    assert params.get("include_excel") is False
    assert params.get("include_pdf") is False


def test_agent_infer_general_tool_intent_research_document_delivery_pdf_only():
    agent = Agent()
    intent = agent._infer_general_tool_intent("fourier denklem hakkında araştırma yap ve pdf rapor hazırla")
    assert intent is not None
    assert intent.get("action") == "research_document_delivery"
    params = intent.get("params", {})
    assert params.get("include_word") is False
    assert params.get("include_excel") is False
    assert params.get("include_pdf") is True


def test_agent_infer_general_tool_intent_research_document_delivery_latex_only():
    agent = Agent()
    intent = agent._infer_general_tool_intent("fourier denklem hakkında araştırma yap ve latex rapor hazırla")
    assert intent is not None
    assert intent.get("action") == "research_document_delivery"
    params = intent.get("params", {})
    assert params.get("include_word") is False
    assert params.get("include_excel") is False
    assert params.get("include_pdf") is False
    assert params.get("include_latex") is True


def test_agent_infer_general_tool_intent_summarize_document():
    agent = Agent()
    intent = agent._infer_general_tool_intent("rapor.md dosyasını madde madde özetle")
    assert intent is not None
    assert intent.get("action") == "summarize_document"
    params = intent.get("params", {})
    assert params.get("style") == "bullets"
    assert str(params.get("path", "")).endswith("rapor.md")


def test_agent_infer_general_tool_intent_shorten_document_routes_to_summary():
    agent = Agent()
    intent = agent._infer_general_tool_intent("rapor.md dosyasını kısalt")
    assert intent is not None
    assert intent.get("action") == "summarize_document"
    params = intent.get("params", {})
    assert params.get("style") == "brief"
    assert str(params.get("path", "")).endswith("rapor.md")


def test_agent_infer_general_tool_intent_edit_text_file_replace():
    agent = Agent()
    intent = agent._infer_general_tool_intent('not.md dosyasında "hata" yerine "uyari" değiştir')
    assert intent is not None
    assert intent.get("action") == "edit_text_file"
    params = intent.get("params", {})
    assert str(params.get("path", "")).endswith("not.md")
    operations = params.get("operations", [])
    assert isinstance(operations, list) and operations
    assert operations[0].get("type") == "replace"
    assert operations[0].get("find") == "hata"
    assert operations[0].get("replace") == "uyari"


def test_agent_infer_general_tool_intent_code_file_edit():
    agent = Agent()
    intent = agent._infer_general_tool_intent('app.py dosyasında "print(1)" yerine "print(2)" değiştir')
    assert intent is not None
    assert intent.get("action") == "edit_text_file"
    assert "Kod dosyası" in str(intent.get("reply", ""))
    params = intent.get("params", {})
    assert str(params.get("path", "")).endswith("app.py")


def test_agent_infer_general_tool_intent_delete_file_without_extension():
    agent = Agent()
    intent = agent._infer_general_tool_intent("not dosyasını sil")
    assert intent is not None
    assert intent.get("action") == "delete_file"
    assert str(intent.get("params", {}).get("path", "")).endswith("not")


def test_agent_infer_general_tool_intent_read_file_without_extension():
    agent = Agent()
    intent = agent._infer_general_tool_intent("not dosyası içinde ne var")
    assert intent is not None
    assert intent.get("action") == "read_file"
    assert str(intent.get("params", {}).get("path", "")).endswith("not")


def test_agent_execute_tool_infers_email_recipient(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    captured = {}

    async def _fake_send_email(to, subject, body, cc=None, bcc=None, attachments=None):
        captured["to"] = to
        captured["subject"] = subject
        captured["body"] = body
        _ = (cc, bcc, attachments)
        return {"success": True, "message": "ok"}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"send_email": _fake_send_email})
    result = asyncio.run(
        agent._execute_tool(
            "send_email",
            {"subject": "Test", "body": "Merhaba"},
            user_input="test@example.com adresine mail gönder",
            step_name="E-posta gönder",
        )
    )
    assert result.get("success") is True
    assert captured.get("to") == "test@example.com"


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


def test_agent_execute_tool_resolves_missing_extension_for_read(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    base_dir = tmp_path / "Desktop" / "Projects"
    base_dir.mkdir(parents=True)
    file_path = base_dir / "not.txt"
    file_path.write_text("merhaba", encoding="utf-8")
    agent.file_context["last_dir"] = str(base_dir)

    captured = {}

    async def _fake_read_file(path):
        captured["path"] = path
        return {"success": True, "path": path, "content": "ok"}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"read_file": _fake_read_file})
    result = asyncio.run(
        agent._execute_tool(
            "read_file",
            {"path": str(base_dir / "not")},
            user_input="not dosyası içinde ne var",
            step_name="Oku",
        )
    )

    assert result.get("success") is True
    assert captured.get("path") == str(file_path)


def test_agent_execute_tool_maps_control_music_action(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    captured = {}

    async def _fake_control_music(action, app="Music"):
        captured["action"] = action
        captured["app"] = app
        return {"success": True, "message": f"{action} ok"}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"control_music": _fake_control_music})
    result = asyncio.run(
        agent._execute_tool(
            "control_music",
            {},
            user_input="müziği durdur",
            step_name="Müzik durdur",
        )
    )
    assert result.get("success") is True
    assert captured.get("action") == "pause"


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


def test_agent_infer_general_tool_intent_batch_delete_screenshot_images(tmp_path, monkeypatch):
    agent = Agent()
    monkeypatch.setenv("HOME", str(tmp_path))
    intent = agent._infer_general_tool_intent("Masaüstündeki ekran resimlerini sil")
    assert intent is not None
    assert intent.get("action") == "delete_file"
    params = intent.get("params", {})
    assert str(params.get("directory", "")).endswith("Desktop")
    assert isinstance(params.get("patterns"), list) and params.get("patterns")


def test_agent_runtime_normalize_user_input_applies_learned_aliases():
    agent = Agent()
    agent.learning = _DummyLearning(
        prefs={"nlu_aliases": {"ggl": "google", "chrma": "chrome a"}}
    )
    normalized = agent._runtime_normalize_user_input("chrma geç ve ggl aç")
    assert "chrome a" in normalized
    assert "google" in normalized


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


def test_agent_split_multi_step_text_numbered_steps():
    agent = Agent()
    text = (
        "Bu işi planla ve uygula: "
        "1) ~/Desktop/elyan-test/a klasörü oluştur "
        "2) not.md yaz "
        "3) içeriği doğrula "
        "4) bana artifact yollarını ver"
    )
    parts = agent._split_multi_step_text(text)
    assert len(parts) == 4
    assert parts[0].startswith("~/Desktop/elyan-test/a")
    assert "not.md" in parts[1]


def test_agent_infer_multi_task_intent_numbered_file_flow(tmp_path, monkeypatch):
    agent = Agent()
    monkeypatch.setenv("ELYAN_AGENTIC_V2", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Desktop").mkdir(parents=True, exist_ok=True)

    text = (
        "Bu işi planla ve uygula: "
        "1) ~/Desktop/elyan-test/a klasörü oluştur "
        "2) not.md yaz "
        "3) içeriği doğrula "
        "4) bana artifact yollarını ver"
    )
    intent = agent._infer_multi_task_intent(text)

    assert intent is not None
    assert intent.get("action") == "multi_task"
    tasks = intent.get("tasks", [])
    assert [t.get("action") for t in tasks] == ["create_folder", "write_file", "read_file", "list_files"]
    assert str(tasks[0].get("params", {}).get("path", "")).endswith("/Desktop/elyan-test/a")
    assert str(tasks[1].get("params", {}).get("path", "")).endswith("/Desktop/elyan-test/a/not.md")
    assert str(tasks[2].get("params", {}).get("path", "")) == str(tasks[1].get("params", {}).get("path", ""))
    assert str(tasks[3].get("params", {}).get("path", "")).endswith("/Desktop/elyan-test/a")
    task_spec = intent.get("task_spec")
    assert isinstance(task_spec, dict)
    assert task_spec.get("intent") == "filesystem_batch"
    assert task_spec.get("goal")
    assert isinstance(task_spec.get("constraints"), dict)
    assert isinstance(task_spec.get("context_assumptions"), list)
    assert isinstance(task_spec.get("artifacts_expected"), list)
    assert isinstance(task_spec.get("artifacts"), list)
    assert isinstance(task_spec.get("checks"), list)
    assert isinstance(task_spec.get("timeouts"), dict)
    assert isinstance(task_spec.get("retries"), dict)
    assert isinstance(task_spec.get("required_tools"), list)
    assert "write_file" in task_spec.get("required_tools", [])
    assert task_spec.get("risk_level") == "low"
    spec_steps = task_spec.get("steps", [])
    assert [s.get("action") for s in spec_steps] == ["mkdir", "write_file", "verify_file", "report_artifacts"]
    assert str(spec_steps[1].get("content", "")).strip()
    assert len(str(spec_steps[1].get("content", "")).strip()) >= 50


def test_agent_infer_multi_task_intent_tolerates_unparsable_step(monkeypatch, tmp_path):
    agent = Agent()
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Desktop").mkdir(parents=True, exist_ok=True)

    text = "1) ~/Desktop/elyan-test/a klasörü oluştur 2) anlamsız adım xyz 3) not.md yaz"
    intent = agent._infer_multi_task_intent(text)

    assert intent is not None
    assert intent.get("action") == "multi_task"
    tasks = intent.get("tasks", [])
    assert len(tasks) >= 2
    assert tasks[0].get("action") == "create_folder"
    assert tasks[1].get("action") == "write_file"


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


def test_agent_prepare_open_project_in_ide_infers_default_project_path(tmp_path, monkeypatch):
    agent = Agent()
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Desktop").mkdir(exist_ok=True)

    params = agent._prepare_tool_params(
        "open_project_in_ide",
        {
            "project_name": "AI Panel",
            "project_kind": "website",
            "output_dir": "~/Desktop",
            "ide": "vscode",
        },
        user_input="website yap ve vscode ile aç",
        step_name="Projeyi aç",
    )
    assert params.get("ide") == "vscode"
    assert params.get("project_path") == str((tmp_path / "Desktop" / "ai-panel"))


def test_agent_run_direct_create_coding_project_website_and_open_ide(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Desktop").mkdir(exist_ok=True)

    captured = {}

    async def _fake_create_web_project_scaffold(project_name, stack="vanilla", theme="professional", output_dir="~/Desktop"):
        captured["create"] = {
            "project_name": project_name,
            "stack": stack,
            "theme": theme,
            "output_dir": output_dir,
        }
        return {
            "success": True,
            "project_dir": str(tmp_path / "Desktop" / "ai-panel"),
            "message": "Web scaffold hazır",
        }

    async def _fake_open_project_in_ide(project_path, ide="vscode"):
        captured["ide"] = {"project_path": project_path, "ide": ide}
        return {"success": True, "message": "IDE açıldı"}

    async def _fake_create_coding_delivery_plan(
        project_path,
        project_name="",
        project_kind="website",
        stack="vanilla",
        complexity="advanced",
        brief="",
    ):
        captured["plan"] = {
            "project_path": project_path,
            "project_name": project_name,
            "project_kind": project_kind,
            "stack": stack,
            "complexity": complexity,
            "brief": brief,
        }
        return {"success": True, "message": "Teslimat planı hazır"}

    async def _fake_create_coding_verification_report(
        project_path,
        project_name="",
        project_kind="website",
        stack="vanilla",
        strict=False,
    ):
        captured["verify"] = {
            "project_path": project_path,
            "project_name": project_name,
            "project_kind": project_kind,
            "stack": stack,
            "strict": strict,
        }
        return {"success": True, "message": "Doğrulama raporu hazır"}

    monkeypatch.setattr(
        "core.agent.AVAILABLE_TOOLS",
        {
            "create_web_project_scaffold": _fake_create_web_project_scaffold,
            "create_coding_delivery_plan": _fake_create_coding_delivery_plan,
            "create_coding_verification_report": _fake_create_coding_verification_report,
            "open_project_in_ide": _fake_open_project_in_ide,
        },
    )

    intent = {
        "action": "create_coding_project",
        "params": {
            "project_kind": "website",
            "project_name": "AI Panel",
            "stack": "react",
            "theme": "professional",
            "open_ide": True,
            "ide": "vscode",
            "output_dir": "~/Desktop",
        },
    }
    out = asyncio.run(agent._run_direct_intent(intent, "AI panel website yap", "inference", []))
    assert "Web scaffold hazır" in out
    assert "Teslimat planı hazır" in out
    assert "Doğrulama raporu hazır" in out
    assert "IDE açıldı" in out
    assert captured.get("create", {}).get("stack") == "react"
    assert captured.get("plan", {}).get("complexity") == "advanced"
    assert captured.get("verify", {}).get("project_kind") == "website"
    assert captured.get("ide", {}).get("project_path", "").endswith("ai-panel")


def test_agent_process_executes_free_form_multi_step_sequence(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.learning = _DummyLearning()
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
        async def create_plan(self, _user_input, _ctx, **kwargs):
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
    agent.intent_parser = SimpleNamespace(parse=lambda _text: {"action": "delete_file", "params": {}})
    agent.learning = _DummyLearning(quick_match_action=None)
    agent.user_profile = _DummyProfile()
    monkeypatch.setattr(agent, "_is_likely_chat_message", lambda _text: False)
    monkeypatch.setattr(agent, "_should_route_to_llm_chat", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(agent, "_should_run_direct_intent", lambda *_args, **_kwargs: False)

    class _UnsafePlanner:
        async def create_plan(self, _user_input, _ctx, **kwargs):
            return SimpleNamespace(subtasks=[])

        def evaluate_plan_quality(self, _subtasks, _user_input):
            return {"safe_to_run": False}

    agent.planner = _UnsafePlanner()

    import core.pipeline as _pipeline_mod
    from core.pipeline import PipelineContext

    async def _fake_pipeline_run(ctx, agent):
        plan = await agent.planner.create_plan(ctx.user_input, {})
        quality = agent.planner.evaluate_plan_quality(plan.subtasks, ctx.user_input)
        if not quality.get("safe_to_run"):
            ctx.final_response = "Bu işlemi güvenli şekilde çalıştırmak için plan güvenli değil."
        return ctx

    monkeypatch.setattr(_pipeline_mod, "pipeline_runner", SimpleNamespace(run=_fake_pipeline_run))
    response = asyncio.run(agent.process("masaüstündeki dosyaları sil"))
    assert "güvenli şekilde çalıştırmak için" in response.lower()


def test_agent_process_returns_battery_status_with_percent(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntentUnknown()
    agent.intent_parser = IntentParser()
    agent.learning = _DummyLearning(quick_match_action=None)
    agent.user_profile = _DummyProfile()
    monkeypatch.setattr(agent, "_should_route_to_llm_chat", lambda *_args, **_kwargs: False)

    async def _fake_battery():
        return {"success": True, "percent": 77, "is_charging": False}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"get_battery_status": _fake_battery})
    response = asyncio.run(agent.process("bilgisayarın şarjı kaç"))
    assert "Pil: %77" in response


def test_agent_process_revises_unsafe_plan_once_then_executes(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntentUnknown()
    agent.intent_parser = SimpleNamespace(parse=lambda _text: {"action": "complex_task", "params": {}})
    agent.learning = _DummyLearning(quick_match_action=None)
    agent.user_profile = _DummyProfile()
    monkeypatch.setattr(agent, "_should_route_to_llm_chat", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(agent, "_should_run_direct_intent", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(agent, "_is_likely_chat_message", lambda _text: False)

    class _Planner:
        def __init__(self):
            self.revise_calls = 0
            self.eval_calls = 0

        async def create_plan(self, _user_input, _ctx, **kwargs):
            return SimpleNamespace(
                subtasks=[SimpleNamespace(task_id="s1", name="Sohbet", action="chat", params={}, dependencies=[])]
            )

        def evaluate_plan_quality(self, _subtasks, _user_input):
            self.eval_calls += 1
            return {"safe_to_run": self.eval_calls >= 2, "issues": ["all_chat_actions"]}

        async def revise_plan(self, *_args, **_kwargs):
            self.revise_calls += 1
            return [
                SimpleNamespace(
                    task_id="s1",
                    name="Masaüstünü listele",
                    action="list_files",
                    params={"path": "~/Desktop"},
                    dependencies=[],
                )
            ]

    planner = _Planner()
    agent.planner = planner

    async def _fake_list_files(path="."):
        _ = path
        return {"success": True, "items": [{"name": "a.txt"}]}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"list_files": _fake_list_files})

    import core.pipeline as _pipeline_mod
    from core.pipeline import PipelineContext

    async def _fake_pipeline_run(ctx, agent):
        from core.agent import AVAILABLE_TOOLS
        plan = await agent.planner.create_plan(ctx.user_input, {})
        quality = agent.planner.evaluate_plan_quality(plan.subtasks, ctx.user_input)
        steps = plan.subtasks
        if not quality.get("safe_to_run"):
            steps = await agent.planner.revise_plan(steps, quality.get("issues", []), ctx.user_input)
            quality = agent.planner.evaluate_plan_quality(steps, ctx.user_input)
        for step in (steps or []):
            fn = AVAILABLE_TOOLS.get(step.action)
            if fn:
                res = await fn(**step.params)
                if res.get("items"):
                    ctx.final_response = "\n".join(i["name"] for i in res["items"])
        return ctx

    monkeypatch.setattr(_pipeline_mod, "pipeline_runner", SimpleNamespace(run=_fake_pipeline_run))
    response = asyncio.run(agent.process("karmaşık görevi tamamla"))
    assert "a.txt" in response
    assert planner.revise_calls == 1


def test_agent_process_dependency_deadlock_rescues_and_runs_step(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntentUnknown()
    agent.intent_parser = SimpleNamespace(parse=lambda _text: {"action": "complex_task", "params": {}})
    agent.learning = _DummyLearning(quick_match_action=None)
    agent.user_profile = _DummyProfile()
    monkeypatch.setattr(agent, "_should_route_to_llm_chat", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(agent, "_should_run_direct_intent", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(agent, "_is_likely_chat_message", lambda _text: False)

    step = SimpleNamespace(
        task_id="s1",
        name="Masaüstünü listele",
        action="list_files",
        params={"path": "~/Desktop"},
        dependencies=["missing_step"],
        max_retries=1,
    )

    class _Planner:
        async def create_plan(self, _user_input, _ctx, **kwargs):
            return SimpleNamespace(subtasks=[step])

        def evaluate_plan_quality(self, _subtasks, _user_input):
            return {"safe_to_run": True}

    agent.planner = _Planner()

    async def _fake_list_files(path="."):
        _ = path
        return {"success": True, "items": [{"name": "a.txt"}]}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"list_files": _fake_list_files})

    import core.pipeline as _pipeline_mod

    async def _fake_pipeline_run(ctx, agent):
        from core.agent import AVAILABLE_TOOLS
        plan = await agent.planner.create_plan(ctx.user_input, {})
        quality = agent.planner.evaluate_plan_quality(plan.subtasks, ctx.user_input)
        executed: set = set()
        for step in (plan.subtasks or []):
            # Rescue deadlocked steps by running them regardless of missing deps
            fn = AVAILABLE_TOOLS.get(step.action)
            if fn:
                res = await fn(**step.params)
                if res.get("items"):
                    ctx.final_response = "\n".join(i["name"] for i in res["items"])
            executed.add(step.task_id)
        return ctx

    monkeypatch.setattr(_pipeline_mod, "pipeline_runner", SimpleNamespace(run=_fake_pipeline_run))
    response = asyncio.run(agent.process("masaüstünü listele"))
    assert "a.txt" in response


def test_agent_process_recovers_failed_planner_step_with_general_intent(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntentUnknown()
    agent.intent_parser = SimpleNamespace(parse=lambda _text: {"action": "complex_task", "params": {}})
    agent.learning = _DummyLearning(quick_match_action=None)
    agent.user_profile = _DummyProfile()
    monkeypatch.setattr(agent, "_should_route_to_llm_chat", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(agent, "_should_run_direct_intent", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(agent, "_is_likely_chat_message", lambda _text: False)

    class _Planner:
        async def create_plan(self, _user_input, _ctx, **kwargs):
            return SimpleNamespace(
                subtasks=[
                    SimpleNamespace(
                        task_id="s1",
                        name="Klasörü kontrol et",
                        action="unknown_planner_action",
                        params={},
                        dependencies=[],
                        max_retries=2,
                    )
                ]
            )

        def evaluate_plan_quality(self, _subtasks, _user_input):
            return {"safe_to_run": True}

    agent.planner = _Planner()
    monkeypatch.setattr(
        agent,
        "_infer_general_tool_intent",
        lambda _text: {"action": "list_files", "params": {"path": "~/Desktop"}},
    )

    async def _fake_list_files(path="."):
        _ = path
        return {"success": True, "items": [{"name": "a.txt"}]}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"list_files": _fake_list_files})

    import core.pipeline as _pipeline_mod

    async def _fake_pipeline_run(ctx, agent):
        from core.agent import AVAILABLE_TOOLS
        plan = await agent.planner.create_plan(ctx.user_input, {})
        for step in (plan.subtasks or []):
            fn = AVAILABLE_TOOLS.get(step.action)
            if fn:
                res = await fn(**step.params)
                if res.get("items"):
                    ctx.final_response = "\n".join(i["name"] for i in res["items"])
            else:
                # General intent fallback for unknown planner actions
                inferred = agent._infer_general_tool_intent(ctx.user_input)
                if inferred:
                    fn2 = AVAILABLE_TOOLS.get(inferred["action"])
                    if fn2:
                        res = await fn2(**inferred.get("params", {}))
                        if res.get("items"):
                            ctx.final_response = "\n".join(i["name"] for i in res["items"])
        return ctx

    monkeypatch.setattr(_pipeline_mod, "pipeline_runner", SimpleNamespace(run=_fake_pipeline_run))
    response = asyncio.run(agent.process("dosyaları kontrol et"))
    assert "a.txt" in response


def test_agent_infer_general_tool_intent_detects_coding_project_request():
    agent = Agent()
    intent = agent._infer_general_tool_intent("bir website yap ortasında sayaç butonu olacak html css js kullan")
    assert intent is not None
    assert intent.get("action") == "create_coding_project"
    params = intent.get("params", {})
    assert params.get("project_kind") == "website"
    assert params.get("stack") == "vanilla"


def test_agent_infer_general_tool_intent_detects_academic_search_request():
    agent = Agent()
    intent = agent._infer_general_tool_intent("iklim değişikliği için akademik makale araştır")
    assert intent is not None
    assert intent.get("action") == "search_academic_papers"
    params = intent.get("params", {})
    assert params.get("query")
    assert int(params.get("limit", 0)) >= 5


def test_agent_infer_coding_project_intent_sets_latest_clean_code_profile():
    agent = Agent()
    intent = agent._infer_coding_project_intent(
        "en son teknolojilerle temiz kod prensiplerine uygun react dashboard yap"
    )
    assert intent is not None
    params = intent.get("params", {})
    assert params.get("tech_mode") == "latest"
    assert params.get("coding_standards") == "clean_code"
    gates = params.get("quality_gates", {})
    assert gates.get("tests") is True
    assert gates.get("lint") is True


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


def test_agent_prepare_advanced_research_strips_copy_noise():
    agent = Agent()
    params = agent._prepare_tool_params(
        "advanced_research",
        {"topic": "köpekler hakkında araştırma yap ve kopyala"},
        user_input="köpekler hakkında araştırma yap ve kopyala",
        step_name="Araştır",
    )
    assert "kopyala" not in str(params.get("topic", "")).lower()
    assert "köpekler" in str(params.get("topic", "")).lower()


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
    agent.learning = _DummyLearning(quick_match_action=None)

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
    assert len(attempts) >= 1
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


def test_agent_postprocess_network_marks_verified_for_2xx():
    agent = Agent()
    result = agent._postprocess_tool_result(
        "http_request",
        {"url": "https://example.com"},
        {"success": True, "status_code": 200, "url": "https://example.com"},
        user_input="",
    )
    assert result.get("verified") is True
    assert result.get("verification_warning", "") == ""


def test_agent_postprocess_network_marks_warning_for_5xx():
    agent = Agent()
    result = agent._postprocess_tool_result(
        "http_request",
        {"url": "https://example.com"},
        {"success": True, "status_code": 503, "url": "https://example.com"},
        user_input="",
    )
    assert result.get("verified") is False
    assert "http_status:503" in str(result.get("verification_warning") or "")


def test_agent_should_share_manifest_only_when_requested_or_required():
    agent = Agent()
    ctx = SimpleNamespace(action="set_wallpaper", requires_evidence=False, runtime_policy={})
    assert agent._should_share_manifest("duvar kağıdı yap", ctx) is False
    assert agent._should_share_manifest("kanıt ve manifest paylaş", ctx) is True
    ctx.requires_evidence = True
    assert agent._should_share_manifest("duvar kağıdı yap", ctx) is True


def test_agent_should_share_attachments_requires_explicit_request():
    agent = Agent()
    ctx = SimpleNamespace(requires_evidence=False, runtime_policy={})
    artifacts = [{"path": "/tmp/result.txt"}]
    assert agent._should_share_attachments("raporu hazırla", ctx, artifacts) is False
    assert agent._should_share_attachments("dosyayı gönder", ctx, artifacts) is True


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


def test_agent_missing_delete_path_error_is_user_friendly():
    agent = Agent()
    message = agent._friendly_missing_argument_error(
        "delete_file() missing 1 required positional argument: 'path'",
        tool_name="delete_file",
    )
    assert "dosya adı" in message.lower() or "yol" in message.lower()


def test_agent_execute_tool_fills_default_notification_message(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    captured = {}

    async def _legacy_notify(title, message):
        captured["title"] = title
        captured["message"] = message
        return {"success": True, "message": "ok"}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"send_notification": _legacy_notify})
    result = asyncio.run(
        agent._execute_tool(
            "send_notification",
            {"title": "Hatırlatma"},
            user_input="",
            step_name="Bildirim",
        )
    )
    assert result["success"] is True
    assert str(captured.get("message", "")).strip() != ""


def test_agent_infer_missing_project_name_and_path_defaults(tmp_path, monkeypatch):
    agent = Agent()
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Desktop").mkdir(exist_ok=True)

    project_name = agent._infer_missing_param_value(
        "project_name",
        "create_web_project_scaffold",
        current={},
        original={},
        user_input="bir website yap ortasında sayaç butonu olacak",
        step_name="Website oluştur",
    )
    assert isinstance(project_name, str)
    assert project_name.strip() != ""

    project_path = agent._infer_missing_param_value(
        "project_path",
        "create_coding_delivery_plan",
        current={"project_name": "Counter Demo", "project_kind": "website", "output_dir": "~/Desktop"},
        original={},
        user_input="delivery plan oluştur",
        step_name="Plan",
    )
    assert isinstance(project_path, str)
    assert project_path.endswith("Desktop/counter-demo")


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


def test_agent_prepare_write_clipboard_uses_recent_assistant_text_when_missing():
    agent = Agent()
    agent.current_user_id = 42

    class _Mem:
        def get_recent_conversations(self, user_id, limit=8):
            assert user_id == 42
            _ = limit
            return [
                {
                    "user_message": "köpekler hakkında araştırma yap",
                    "bot_response": '{"message":"Köpekler hakkında kısa özet"}',
                }
            ]

    agent.kernel = SimpleNamespace(memory=_Mem(), tools=_DummyTools())
    params = agent._prepare_tool_params(
        "write_clipboard",
        {"text": ""},
        user_input="bunu kopyala",
        step_name="Kopyala",
    )
    assert "Köpekler hakkında kısa özet" in params.get("text", "")


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
    agent.user_profile = _DummyProfile()
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


def test_agent_run_direct_intent_multi_task_fail_fast_on_dependency(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    calls = []

    async def _fake_open_app(app_name=None):
        calls.append(("open_app", app_name))
        return {"success": True, "app_name": app_name or "Safari", "message": "Safari opened."}

    async def _fake_key_combo(combo=None, target_app=None):
        calls.append(("key_combo", combo, target_app))
        return {"success": False, "error": "hedef uygulama doğrulanamadı", "combo": combo, "target_app": target_app}

    async def _fake_open_url(url=None):
        calls.append(("open_url", url))
        return {"success": True, "url": url}

    monkeypatch.setattr(
        "core.agent.AVAILABLE_TOOLS",
        {"open_app": _fake_open_app, "key_combo": _fake_key_combo, "open_url": _fake_open_url},
    )

    intent = {
        "action": "multi_task",
        "tasks": [
            {"id": "task_1", "action": "open_app", "params": {"app_name": "Safari"}, "description": "Safari aç"},
            {"id": "task_2", "action": "key_combo", "params": {"combo": "cmd+t", "target_app": "Safari"}, "depends_on": ["task_1"], "description": "Yeni sekme"},
            {"id": "task_3", "action": "open_url", "params": {"url": "https://example.com"}, "depends_on": ["task_2"], "description": "Sayfayı aç"},
        ],
    }

    out = asyncio.run(agent._run_direct_intent(intent, "safari aç sonra yeni sekme", "inference", []))
    assert "hedef uygulama" in out.lower()
    assert len(calls) >= 3
    assert calls[0][0] == "open_app"
    assert sum(1 for row in calls if row[0] == "key_combo") == 2
    assert all(row[0] != "open_url" for row in calls)
    payload = agent._last_direct_intent_payload if isinstance(agent._last_direct_intent_payload, dict) else {}
    assert payload.get("success") is False
    assert payload.get("completed_steps") == 1
    assert payload.get("total_steps") == 3
    assert payload.get("failure_class") in {"state_mismatch", "tool_failure", "unknown_failure"}


def test_agent_run_direct_intent_policy_block_fail_fast_no_blind_retry(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    calls = {"count": 0}

    async def _fake_run_safe_command(command=None):
        _ = command
        calls["count"] += 1
        return {"success": False, "error": "Security policy blocked this action."}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"run_safe_command": _fake_run_safe_command})

    intent = {
        "action": "multi_task",
        "tasks": [
            {
                "id": "task_1",
                "action": "run_safe_command",
                "params": {"command": "echo ok"},
                "description": "Komut calistir",
            }
        ],
    }

    out = asyncio.run(agent._run_direct_intent(intent, "komutu çalıştır", "inference", []))
    assert "başarısız" in out.lower() or "basarisiz" in out.lower() or "hata" in out.lower()
    assert calls["count"] == 1
    payload = agent._last_direct_intent_payload if isinstance(agent._last_direct_intent_payload, dict) else {}
    failed = payload.get("failed_step", {}) if isinstance(payload.get("failed_step"), dict) else {}
    assert str(failed.get("failure_class") or "") == "policy_block"


def test_agent_run_direct_intent_state_mismatch_refocuses_before_retry(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    calls: list[tuple] = []
    key_combo_calls = {"count": 0}

    async def _fake_open_app(app_name=None):
        calls.append(("open_app", app_name))
        return {"success": True, "app_name": app_name or "Safari", "verified": True}

    async def _fake_key_combo(combo=None, target_app=None):
        key_combo_calls["count"] += 1
        calls.append(("key_combo", combo, target_app))
        if key_combo_calls["count"] == 1:
            return {
                "success": False,
                "error": "hedef uygulama doğrulanamadı",
                "combo": combo,
                "target_app": target_app,
                "frontmost_app": "Finder",
            }
        return {"success": True, "combo": combo, "target_app": target_app, "verified": True, "message": "ok"}

    monkeypatch.setattr("core.agent.AVAILABLE_TOOLS", {"open_app": _fake_open_app, "key_combo": _fake_key_combo})

    intent = {
        "action": "multi_task",
        "tasks": [
            {
                "id": "task_1",
                "action": "key_combo",
                "params": {"combo": "cmd+t", "target_app": "Safari"},
                "description": "Yeni sekme",
            }
        ],
    }

    out = asyncio.run(agent._run_direct_intent(intent, "yeni sekme aç", "inference", []))
    assert "ok" in out.lower() or "başarı" in out.lower() or "basari" in out.lower()
    assert key_combo_calls["count"] == 2
    assert ("open_app", "Safari") in calls
    payload = agent._last_direct_intent_payload if isinstance(agent._last_direct_intent_payload, dict) else {}
    assert payload.get("success") is True
    rows = payload.get("steps", []) if isinstance(payload.get("steps"), list) else []
    assert rows and isinstance(rows[0], dict)
    recovery_notes = rows[0].get("recovery_notes", []) if isinstance(rows[0].get("recovery_notes"), list) else []
    assert any("refocus_app:Safari" in str(note) for note in recovery_notes)


def test_agent_run_direct_intent_compacts_multi_task_output_when_policy_enabled(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    monkeypatch.setattr(
        Agent,
        "_current_runtime_policy",
        staticmethod(lambda: {"response": {"compact_actions": True}}),
    )

    async def _fake_open_app(app_name=None):
        return {"success": True, "app_name": app_name or "Safari", "message": "Safari opened.", "verified": True}

    async def _fake_key_combo(combo=None, target_app=None):
        _ = combo
        return {"success": True, "target_app": target_app, "combo": "cmd+t", "message": "Yeni sekme açıldı.", "verified": True}

    monkeypatch.setattr(
        "core.agent.AVAILABLE_TOOLS",
        {"open_app": _fake_open_app, "key_combo": _fake_key_combo},
    )

    intent = {
        "action": "multi_task",
        "tasks": [
            {"id": "task_1", "action": "open_app", "params": {"app_name": "Safari"}, "description": "Safari aç"},
            {"id": "task_2", "action": "key_combo", "params": {"combo": "cmd+t", "target_app": "Safari"}, "depends_on": ["task_1"], "description": "Yeni sekme aç"},
        ],
    }
    response = asyncio.run(agent._run_direct_intent(intent, "safari aç sonra yeni sekme aç", "inference", []))
    assert response.startswith("✅ 2 adım tamamlandı")
    assert "[1]" not in response


def test_agent_process_executes_numbered_plan_steps(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ELYAN_AGENTIC_V2", "1")
    (tmp_path / "Desktop").mkdir(parents=True, exist_ok=True)

    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.quick_intent = _DummyQuickIntentUnknown()
    agent.intent_parser = SimpleNamespace(parse=lambda _text: {"action": "chat", "params": {}})

    executed = []
    written_content = {"value": ""}

    async def _fake_create_folder(path):
        p = Path(path).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        executed.append(("create_folder", str(p)))
        return {"success": True, "path": str(p)}

    async def _fake_write_file(path, content):
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        written_content["value"] = content
        executed.append(("write_file", str(p)))
        return {"success": True, "path": str(p), "content": content}

    async def _fake_read_file(path):
        p = Path(path).expanduser()
        executed.append(("read_file", str(p)))
        return {"success": True, "path": str(p), "content": p.read_text(encoding="utf-8")}

    async def _fake_list_files(path="."):
        p = Path(path).expanduser()
        executed.append(("list_files", str(p)))
        items = [{"name": child.name} for child in sorted(p.iterdir())]
        return {"success": True, "path": str(p), "items": items}

    monkeypatch.setattr(
        "core.agent.AVAILABLE_TOOLS",
        {
            "create_folder": _fake_create_folder,
            "write_file": _fake_write_file,
            "read_file": _fake_read_file,
            "list_files": _fake_list_files,
        },
    )

    cmd = (
        "Bu işi planla ve uygula: "
        "1) ~/Desktop/elyan-test/a klasörü oluştur "
        "2) not.md yaz "
        "3) içeriği doğrula "
        "4) bana artifact yollarını ver."
    )
    response = asyncio.run(agent.process(cmd))

    target = tmp_path / "Desktop" / "elyan-test" / "a" / "not.md"
    assert target.exists()
    action_order = [x[0] for x in executed]
    assert action_order[:2] == ["create_folder", "write_file"]
    assert action_order[-1] == "list_files"
    assert action_order.count("read_file") >= 1
    assert written_content["value"].strip()
    assert len(written_content["value"].strip()) >= 50
    assert cmd.strip() not in written_content["value"]
    assert "not.md" in response
    assert "elyan-test/a" in response.replace("\\", "/")
    assert "Kanıt özeti" in response


def test_agent_multi_task_reorders_research_before_empty_word_write(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    agent.user_profile = _DummyProfile()
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


def test_agent_prepare_research_params_infers_academic_policy():
    agent = Agent()
    params = agent._prepare_tool_params(
        "advanced_research",
        {"topic": "köpek sağlığı"},
        user_input="köpek sağlığı hakkında akademik ve hakemli kaynaklarla araştırma yap",
        step_name="Araştır",
    )
    assert params.get("source_policy") == "academic"
    assert params.get("min_reliability", 0) >= 0.78
    assert params.get("citation_style") == "apa7"
    assert params.get("include_bibliography") is True


def test_agent_prepare_research_params_infers_reliability_percent():
    agent = Agent()
    params = agent._prepare_tool_params(
        "advanced_research",
        {"topic": "köpek beslenmesi"},
        user_input="köpek beslenmesi araştırması yap, güvenilirlik en az %80 olsun",
        step_name="Araştır",
    )
    assert params.get("min_reliability") == 0.8


def test_agent_prepare_research_document_delivery_academic_defaults():
    agent = Agent()
    params = agent._prepare_tool_params(
        "research_document_delivery",
        {"topic": "LLM güvenliği", "brief": "akademik rapor"},
        user_input="akademik literatür taraması yap, atıflı rapor üret",
        step_name="Araştırma paketini hazırla",
    )
    assert params.get("source_policy") == "academic"
    assert params.get("min_reliability", 0) >= 0.78
    assert params.get("citation_style") == "apa7"
    assert params.get("include_bibliography") is True
    assert params.get("include_excel") is False
    assert params.get("include_pdf") is False
    assert params.get("include_latex") is False


def test_agent_prepare_generate_document_pack_prefers_pdf_when_requested():
    agent = Agent()
    params = agent._prepare_tool_params(
        "generate_document_pack",
        {"topic": "Fourier Denklem"},
        user_input="fourier denklem için pdf belge hazırla",
        step_name="Belge oluştur",
    )
    assert params.get("preferred_formats") == ["pdf"]


def test_agent_prepare_edit_text_file_infers_operations():
    agent = Agent()
    params = agent._prepare_tool_params(
        "edit_text_file",
        {"path": "~/Desktop/not.md"},
        user_input='not.md dosyasında "hata" yerine "uyari" değiştir',
        step_name="Belgeyi düzenle",
    )
    operations = params.get("operations", [])
    assert isinstance(operations, list) and operations
    assert operations[0].get("type") == "replace"
    assert operations[0].get("find") == "hata"
    assert operations[0].get("replace") == "uyari"


def test_agent_prepare_summarize_document_uses_last_path_and_style():
    agent = Agent()
    agent.file_context["last_path"] = str(Path.home() / "Desktop" / "rapor.docx")
    params = agent._prepare_tool_params(
        "summarize_document",
        {},
        user_input="bunu detaylı özetle",
        step_name="Belge özeti",
    )
    assert str(params.get("path", "")).endswith("rapor.docx")
    assert params.get("style") == "detailed"


def test_agent_prepare_web_project_scaffold_maps_topic_to_project_name():
    agent = Agent()
    params = agent._prepare_tool_params(
        "create_web_project_scaffold",
        {"topic": "sayaç demo", "output_dir": "~/Desktop"},
        user_input="bir website yap ortasında sayaç butonu olacak. html css js kullanarak yap",
        step_name="Website scaffold oluştur",
    )
    assert params.get("project_name") == "sayaç demo"
    assert params.get("stack") == "vanilla"
    assert "sayaç butonu" in str(params.get("brief", "")).lower()


def test_agent_infer_save_intent_routes_to_write_file():
    agent = Agent()
    intent = agent._infer_save_intent("Bunu masaüstüne dosya olarak kaydet")
    assert intent is not None
    assert intent.get("action") == "write_file"
    assert str(intent.get("params", {}).get("path", "")).endswith("not.txt")


def test_agent_prepare_write_file_preserves_short_note_content_for_note_request():
    agent = Agent()
    params = agent._prepare_tool_params(
        "write_file",
        {"path": "~/Desktop/not.txt", "content": "sen kimsin"},
        user_input="masaüstüne not olarak sen kimsin yaz",
        step_name="",
    )
    assert params.get("allow_short_content") is True
    assert params.get("content") == "sen kimsin"


def test_agent_infer_save_intent_skips_numbered_multi_step_request():
    agent = Agent()
    intent = agent._infer_save_intent(
        "Bu işi planla ve uygula: 1) ~/Desktop/a klasörü oluştur 2) not.md yaz 3) doğrula 4) kaydet"
    )
    assert intent is None


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


def test_agent_infer_conversational_followup_word_save_uses_recent_context(monkeypatch):
    agent = Agent()
    agent.file_context["last_path"] = str(Path.home() / "Desktop" / "llm.txt")
    monkeypatch.setattr(agent, "_get_recent_user_text", lambda *_args, **_kwargs: "LLM güvenliği hakkında bilgi ver")
    monkeypatch.setattr(agent, "_get_recent_assistant_text", lambda *_args, **_kwargs: "LLM güvenliği için kısa özet")
    monkeypatch.setattr(agent, "_get_recent_research_text", lambda *_args, **_kwargs: "")

    intent = agent._infer_general_tool_intent("bunu word olarak kaydet")
    assert intent is not None
    assert intent.get("action") == "create_word_document"
    params = intent.get("params", {})
    assert str(params.get("path", "")).endswith("llm.docx")
    assert params.get("content") == "LLM güvenliği için kısa özet"


def test_agent_infer_conversational_followup_summary_uses_recent_text(monkeypatch):
    agent = Agent()
    monkeypatch.setattr(agent, "_get_recent_user_text", lambda *_args, **_kwargs: "LLM güvenliği hakkında bilgi ver")
    monkeypatch.setattr(agent, "_get_recent_assistant_text", lambda *_args, **_kwargs: "Uzun bir açıklama metni")
    monkeypatch.setattr(agent, "_get_recent_research_text", lambda *_args, **_kwargs: "")

    intent = agent._infer_general_tool_intent("bunu daha kısa özetle")
    assert intent is not None
    assert intent.get("action") == "summarize_document"
    params = intent.get("params", {})
    assert params.get("content") == "Uzun bir açıklama metni"
    assert params.get("style") == "brief"


def test_agent_infer_conversational_followup_research_document_uses_recent_user_topic(monkeypatch):
    agent = Agent()
    monkeypatch.setattr(
        agent,
        "_get_recent_user_text",
        lambda *_args, **_kwargs: "Avrupa Birliği yapay zeka yasasının şirketlere etkisi nedir",
    )
    monkeypatch.setattr(agent, "_get_recent_assistant_text", lambda *_args, **_kwargs: "Kısa cevap")
    monkeypatch.setattr(agent, "_get_recent_research_text", lambda *_args, **_kwargs: "")

    intent = agent._infer_general_tool_intent("bunu araştırıp profesyonel rapor yap")
    assert intent is not None
    assert intent.get("action") == "research_document_delivery"
    params = intent.get("params", {})
    assert "yapay zeka" in str(params.get("topic", "")).lower()
    assert params.get("include_word") is True
    assert params.get("include_excel") is False
    assert params.get("audience") == "executive"


def test_agent_infer_conversational_followup_professionalizes_previous_context(monkeypatch):
    agent = Agent()
    monkeypatch.setattr(
        agent,
        "_get_recent_user_text",
        lambda *_args, **_kwargs: "müşteri onboarding sürecini anlat",
    )
    monkeypatch.setattr(
        agent,
        "_get_recent_assistant_text",
        lambda *_args, **_kwargs: "Onboarding süreci üç adımdan oluşur.",
    )
    monkeypatch.setattr(agent, "_get_recent_research_text", lambda *_args, **_kwargs: "")

    intent = agent._infer_general_tool_intent("bunu daha profesyonel yap")
    assert intent is not None
    assert intent.get("action") == "generate_document_pack"
    params = intent.get("params", {})
    assert "onboarding" in str(params.get("topic", "")).lower()
    assert "üç adımdan oluşur" in str(params.get("brief", "")).lower()


def test_agent_followup_does_not_treat_image_search_as_professional_doc(monkeypatch):
    agent = Agent()
    monkeypatch.setattr(agent, "_get_recent_user_text", lambda *_args, **_kwargs: "kedi resmi arat")
    monkeypatch.setattr(
        agent,
        "_get_recent_assistant_text",
        lambda *_args, **_kwargs: "İşlem tamamlandı: https://www.google.com/search?q=kedi+resmi",
    )
    monkeypatch.setattr(agent, "_get_recent_research_text", lambda *_args, **_kwargs: "")

    intent = agent._infer_general_tool_intent("kedi resmi arat")
    assert intent is None or intent.get("action") != "generate_document_pack"


def test_agent_infer_conversational_followup_retry_failed_turn():
    agent = Agent()
    agent._last_turn_context = {
        "user_input": "chrome dan yeni sekme aç",
        "response_text": "Görev başarısız",
        "action": "open_app",
        "success": False,
        "ts": 1.0,
    }

    intent = agent._infer_general_tool_intent("bunu düzelt ve tekrar dene")
    assert intent is not None
    assert intent.get("action") == "failure_replay"


def test_agent_finalize_turn_stores_last_turn_context():
    agent = Agent()
    asyncio.run(
        agent._finalize_turn(
            user_input="not al",
            response_text="tamam",
            action="write_file",
            success=True,
            started_at=time.perf_counter(),
            context={},
        )
    )
    assert agent._last_turn_context.get("user_input") == "not al"
    assert agent._last_turn_context.get("action") == "write_file"
    assert agent._last_turn_context.get("success") is True


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


def test_agent_infer_general_tool_intent_api_health_get_save():
    agent = Agent()
    intent = agent._infer_general_tool_intent(
        "https://httpbin.org/get için health check yap, sonra GET at, sonucu "
        "~/Desktop/elyan-test/api/result.json ve summary.md kaydet."
    )
    assert intent is not None
    assert intent.get("action") == "api_health_get_save"
    params = intent.get("params", {})
    assert params.get("url") == "https://httpbin.org/get"
    assert str(params.get("result_path", "")).endswith("result.json")
    assert str(params.get("summary_path", "")).endswith("summary.md")


def test_agent_infer_general_tool_intent_wallpaper_uses_last_attachment_for_pronoun(tmp_path):
    agent = Agent()
    image = tmp_path / "dog.png"
    image.write_bytes(b"img")
    agent.file_context["last_attachment"] = str(image)

    intent = agent._infer_general_tool_intent("bunu duvar kağıdı yap")
    assert intent is not None
    assert intent.get("action") == "set_wallpaper"
    assert intent.get("params", {}).get("image_path") == str(image)


def test_agent_run_direct_intent_api_health_get_save_executes_chain(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    result_path = tmp_path / "result.json"
    summary_path = tmp_path / "summary.md"
    calls = []

    async def _fake_execute_tool(tool_name, params, **kwargs):
        _ = kwargs
        calls.append((tool_name, dict(params or {})))
        if tool_name == "api_health_check":
            return {
                "success": True,
                "results": {"https://httpbin.org/get": {"healthy": True, "status_code": 200}},
            }
        if tool_name == "http_request":
            return {
                "success": True,
                "status_code": 200,
                "duration_ms": 42,
                "body": {"url": "https://httpbin.org/get"},
                "url": "https://httpbin.org/get",
            }
        if tool_name == "write_file":
            path = Path(str(params.get("path"))).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(params.get("content", "")), encoding="utf-8")
            return {"success": True, "path": str(path)}
        return {"success": True}

    monkeypatch.setattr(agent, "_execute_tool", _fake_execute_tool)

    text = asyncio.run(
        agent._run_direct_intent(
            {
                "action": "api_health_get_save",
                "params": {
                    "url": "https://httpbin.org/get",
                    "result_path": str(result_path),
                    "summary_path": str(summary_path),
                    "method": "GET",
                },
            },
            user_input="api test",
            role="inference",
            history=[],
            user_id="test-user",
        )
    )

    assert "kayıt tamamlandı" in text.lower()
    assert result_path.exists()
    assert summary_path.exists()
    assert [c[0] for c in calls] == ["api_health_check", "http_request", "write_file", "write_file"]


def test_agent_run_direct_intent_uses_runtime_task_spec_when_available(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    result_path = tmp_path / "result.json"
    summary_path = tmp_path / "summary.md"
    calls = []

    async def _fake_execute_tool(tool_name, params, **kwargs):
        _ = kwargs
        calls.append((tool_name, dict(params or {})))
        if tool_name == "api_health_check":
            return {"success": True, "status_code": 200}
        if tool_name == "http_request":
            return {"success": True, "status_code": 200, "body": {"ok": True}}
        if tool_name == "write_file":
            path = Path(str(params.get("path"))).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(params.get("content", "")), encoding="utf-8")
            return {"success": True, "path": str(path)}
        return {"success": True}

    monkeypatch.setattr(agent, "_execute_tool", _fake_execute_tool)
    monkeypatch.setattr(agent, "_validate_runtime_task_spec", lambda _spec: (True, []))

    task_spec = {
        "intent": "api_batch",
        "version": "1.0",
        "goal": "api görevini çalıştır",
        "constraints": {},
        "context_assumptions": [],
        "artifacts_expected": [],
        "checks": [],
        "rollback": [],
        "required_tools": ["api_health_check", "http_request", "write_file"],
        "risk_level": "low",
        "timeouts": {"step_timeout_s": 60, "run_timeout_s": 300},
        "retries": {"max_attempts": 1},
        "steps": [
            {
                "id": "step_1",
                "action": "api_health_check",
                "params": {"url": "https://httpbin.org/get"},
                "checks": [{"type": "http_status", "expected": 200}],
            },
            {
                "id": "step_2",
                "action": "http_request",
                "params": {"url": "https://httpbin.org/get", "method": "GET"},
                "checks": [{"type": "response_present"}],
            },
            {
                "id": "step_3",
                "action": "write_file",
                "path": str(result_path),
                "content": "ok",
                "checks": [{"type": "file_exists"}, {"type": "file_not_empty"}],
            },
            {
                "id": "step_4",
                "action": "write_file",
                "path": str(summary_path),
                "content": "summary",
                "checks": [{"type": "file_exists"}, {"type": "file_not_empty"}],
            },
        ],
    }

    text = asyncio.run(
        agent._run_direct_intent(
            {
                "action": "api_health_get_save",
                "params": {"url": "https://httpbin.org/get"},
                "task_spec": task_spec,
            },
            user_input="api test",
            role="inference",
            history=[],
            user_id="test-user",
        )
    )

    assert "Artifact yolları" in text
    assert result_path.exists()
    assert summary_path.exists()
    assert [c[0] for c in calls] == ["api_health_check", "http_request", "write_file", "write_file"]


def test_agent_run_runtime_task_spec_resolves_out_of_order_dependencies(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    base = tmp_path / "elyan-test" / "a"
    target = base / "not.md"
    calls = []

    async def _fake_execute_tool(tool_name, params, **kwargs):
        _ = kwargs
        calls.append((tool_name, dict(params or {})))
        if tool_name == "create_folder":
            p = Path(str(params.get("path"))).expanduser()
            p.mkdir(parents=True, exist_ok=True)
            return {"success": True, "path": str(p)}
        if tool_name == "write_file":
            p = Path(str(params.get("path"))).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(params.get("content", "")), encoding="utf-8")
            return {"success": True, "path": str(p)}
        return {"success": True}

    monkeypatch.setattr(agent, "_execute_tool", _fake_execute_tool)
    monkeypatch.setattr(agent, "_validate_runtime_task_spec", lambda _spec: (True, []))

    task_spec = {
        "intent": "filesystem_batch",
        "version": "1.0",
        "goal": "dependency order test",
        "constraints": {},
        "context_assumptions": [],
        "artifacts_expected": [],
        "checks": [],
        "rollback": [],
        "required_tools": ["create_folder", "write_file"],
        "risk_level": "low",
        "timeouts": {"step_timeout_s": 60, "run_timeout_s": 300},
        "retries": {"max_attempts": 1},
        "steps": [
            {
                "id": "step_2",
                "action": "write_file",
                "path": str(target),
                "content": "icerik",
                "depends_on": ["step_1"],
                "checks": [{"type": "file_exists"}, {"type": "file_not_empty"}],
            },
            {
                "id": "step_1",
                "action": "mkdir",
                "path": str(base),
                "checks": [{"type": "path_exists"}],
            },
        ],
    }

    out = asyncio.run(agent._run_runtime_task_spec(task_spec, user_input="test"))
    assert "Artifact yolları" in out
    assert target.exists()
    assert [c[0] for c in calls] == ["create_folder", "write_file"]


def test_agent_run_runtime_task_spec_retries_failed_validation(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    target = tmp_path / "retry.md"
    write_count = {"n": 0}

    async def _fake_execute_tool(tool_name, params, **kwargs):
        _ = kwargs
        if tool_name == "write_file":
            write_count["n"] += 1
            p = Path(str(params.get("path"))).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            if write_count["n"] == 1:
                p.write_text("", encoding="utf-8")
            else:
                p.write_text("dogru icerik", encoding="utf-8")
            return {"success": True, "path": str(p)}
        return {"success": True}

    monkeypatch.setattr(agent, "_execute_tool", _fake_execute_tool)
    monkeypatch.setattr(agent, "_validate_runtime_task_spec", lambda _spec: (True, []))

    task_spec = {
        "intent": "filesystem_batch",
        "version": "1.0",
        "goal": "retry test",
        "constraints": {},
        "context_assumptions": [],
        "artifacts_expected": [],
        "checks": [],
        "rollback": [],
        "required_tools": ["write_file"],
        "risk_level": "low",
        "timeouts": {"step_timeout_s": 60, "run_timeout_s": 300},
        "retries": {"max_attempts": 2},
        "steps": [
            {
                "id": "step_1",
                "action": "write_file",
                "path": str(target),
                "content": "dogru icerik",
                "checks": [{"type": "file_exists"}, {"type": "file_not_empty"}],
            }
        ],
    }

    out = asyncio.run(agent._run_runtime_task_spec(task_spec, user_input="test"))
    assert "Tekrar deneme" in out
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "dogru icerik"
    assert write_count["n"] == 2


def test_agent_run_runtime_task_spec_policy_block_fail_fast_without_retry(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    call_count = {"n": 0}

    async def _fake_execute_tool(tool_name, params, **kwargs):
        _ = (tool_name, params, kwargs)
        call_count["n"] += 1
        return {"success": False, "error": "Security policy blocked this action."}

    monkeypatch.setattr(agent, "_execute_tool", _fake_execute_tool)
    monkeypatch.setattr(agent, "_validate_runtime_task_spec", lambda _spec: (True, []))

    task_spec = {
        "intent": "automation_batch",
        "version": "1.0",
        "goal": "policy block test",
        "constraints": {},
        "context_assumptions": [],
        "artifacts_expected": [],
        "checks": [],
        "rollback": [],
        "required_tools": ["run_safe_command"],
        "risk_level": "low",
        "timeouts": {"step_timeout_s": 60, "run_timeout_s": 300},
        "retries": {"max_attempts": 3},
        "steps": [
            {
                "id": "step_1",
                "action": "run_safe_command",
                "params": {"command": "echo ok"},
                "checks": [{"type": "tool_success"}],
            }
        ],
    }

    out = asyncio.run(agent._run_runtime_task_spec(task_spec, user_input="test"))
    assert "Hata kodu:" in out
    assert call_count["n"] == 1


def test_agent_run_runtime_task_spec_enforces_exit_code_check(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    async def _fake_execute_tool(tool_name, params, **kwargs):
        _ = (tool_name, params, kwargs)
        return {"success": True, "returncode": 2, "stdout": "", "stderr": "failed"}

    monkeypatch.setattr(agent, "_execute_tool", _fake_execute_tool)
    monkeypatch.setattr(agent, "_validate_runtime_task_spec", lambda _spec: (True, []))

    task_spec = {
        "intent": "automation_batch",
        "version": "1.0",
        "goal": "exit code test",
        "constraints": {},
        "context_assumptions": [],
        "artifacts_expected": [],
        "checks": [],
        "rollback": [],
        "required_tools": ["run_safe_command"],
        "risk_level": "low",
        "timeouts": {"step_timeout_s": 60, "run_timeout_s": 300},
        "retries": {"max_attempts": 1},
        "steps": [
            {
                "id": "step_1",
                "action": "run_safe_command",
                "params": {"command": "echo hi"},
                "checks": [{"type": "exit_code", "expected": 0}],
            }
        ],
    }

    out = asyncio.run(agent._run_runtime_task_spec(task_spec, user_input="test"))
    assert "Hata kodu: VALIDATION_ERROR" in out
    assert "exit_code_mismatch" in out


def test_agent_run_runtime_task_spec_step_timeout(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())

    async def _slow_execute_tool(tool_name, params, **kwargs):
        _ = (tool_name, params, kwargs)
        await asyncio.sleep(0.2)
        return {"success": True}

    monkeypatch.setattr(agent, "_execute_tool", _slow_execute_tool)
    monkeypatch.setattr(agent, "_validate_runtime_task_spec", lambda _spec: (True, []))

    task_spec = {
        "intent": "automation_batch",
        "version": "1.0",
        "goal": "timeout test",
        "constraints": {},
        "context_assumptions": [],
        "artifacts_expected": [],
        "checks": [],
        "rollback": [],
        "required_tools": ["run_safe_command"],
        "risk_level": "low",
        "timeouts": {"step_timeout_s": 0.1, "run_timeout_s": 5},
        "retries": {"max_attempts": 1},
        "steps": [
            {
                "id": "step_1",
                "action": "run_safe_command",
                "params": {"command": "echo hi"},
                "checks": [{"type": "tool_success"}],
            }
        ],
    }

    out = asyncio.run(agent._run_runtime_task_spec(task_spec, user_input="test"))
    assert "Hata kodu: ENV_ERROR" in out
    assert "step_timeout" in out


def test_agent_build_task_spec_for_run_safe_command_includes_exit_code_check():
    agent = Agent()
    spec = agent._build_task_spec_from_intent(
        "terminalde pwd komutunu çalıştır",
        {"action": "run_safe_command", "params": {"command": "pwd"}},
        "system_automation",
    )
    assert isinstance(spec, dict)
    step = spec.get("steps", [])[0]
    checks = step.get("checks", [])
    assert any(c.get("type") == "exit_code" and c.get("expected") == 0 for c in checks if isinstance(c, dict))


def test_agent_build_task_spec_for_edit_text_file_uses_office_batch():
    agent = Agent()
    spec = agent._build_task_spec_from_intent(
        "not.md dosyasında hata yerine uyarı değiştir",
        {
            "action": "edit_text_file",
            "params": {
                "path": "~/Desktop/not.md",
                "operations": [{"type": "replace", "find": "hata", "replace": "uyari", "all": True}],
            },
        },
        "communication",
    )
    assert isinstance(spec, dict)
    assert spec.get("intent") == "office_batch"
    assert "edit_text_file" in spec.get("required_tools", [])


def test_agent_run_runtime_task_spec_parallel_wave_when_flag_enabled(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    monkeypatch.setenv("ELYAN_DAG_EXEC", "1")
    monkeypatch.setattr(agent, "_validate_runtime_task_spec", lambda _spec: (True, []))

    active = {"count": 0, "max": 0}

    async def _fake_execute_tool(tool_name, params, **kwargs):
        _ = (tool_name, params, kwargs)
        active["count"] += 1
        active["max"] = max(active["max"], active["count"])
        await asyncio.sleep(0.1)
        active["count"] -= 1
        return {"success": True, "output": "ok"}

    monkeypatch.setattr(agent, "_execute_tool", _fake_execute_tool)

    task_spec = {
        "intent": "general_batch",
        "version": "1.0",
        "goal": "parallel wave test",
        "constraints": {},
        "context_assumptions": [],
        "artifacts_expected": [],
        "checks": [],
        "rollback": [],
        "required_tools": ["summarize_text"],
        "risk_level": "low",
        "timeouts": {"step_timeout_s": 5, "run_timeout_s": 10},
        "retries": {"max_attempts": 1},
        "steps": [
            {
                "id": "step_1",
                "action": "summarize_text",
                "params": {"text": "a"},
                "checks": [{"type": "tool_success"}],
            },
            {
                "id": "step_2",
                "action": "summarize_text",
                "params": {"text": "b"},
                "checks": [{"type": "tool_success"}],
            },
        ],
    }

    out = asyncio.run(agent._run_runtime_task_spec(task_spec, user_input="test"))
    assert "[1]" in out and "[2]" in out
    assert active["max"] >= 2


def test_agent_run_runtime_task_spec_runs_rollback_on_failure(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    monkeypatch.setattr(agent, "_validate_runtime_task_spec", lambda _spec: (True, []))

    rollback_file = tmp_path / "rollback.txt"
    called = {"rollback": 0}

    async def _fake_execute_tool(tool_name, params, **kwargs):
        step_name = str(kwargs.get("step_name") or "")
        if step_name.startswith("rollback_"):
            called["rollback"] += 1
            p = Path(str(params.get("path"))).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(params.get("content", "rollback-ok")), encoding="utf-8")
            return {"success": True, "path": str(p)}
        _ = (tool_name, params)
        return {"success": False, "error": "forced_fail"}

    monkeypatch.setattr(agent, "_execute_tool", _fake_execute_tool)

    task_spec = {
        "intent": "automation_batch",
        "version": "1.0",
        "goal": "rollback test",
        "constraints": {},
        "context_assumptions": [],
        "artifacts_expected": [],
        "checks": [],
        "rollback": [
            {
                "action": "write_file",
                "path": str(rollback_file),
                "content": "rollback-ok",
            }
        ],
        "required_tools": ["run_safe_command", "write_file"],
        "risk_level": "low",
        "timeouts": {"step_timeout_s": 5, "run_timeout_s": 10},
        "retries": {"max_attempts": 1},
        "steps": [
            {
                "id": "step_1",
                "action": "run_safe_command",
                "params": {"command": "false"},
                "checks": [{"type": "tool_success"}],
            }
        ],
    }

    out = asyncio.run(agent._run_runtime_task_spec(task_spec, user_input="test"))
    assert "Rollback başlatıldı" in out
    assert called["rollback"] == 1
    assert rollback_file.exists()


def test_agent_feature_flag_enabled_reads_runtime_policy_flags(monkeypatch):
    agent = Agent()
    monkeypatch.delenv("ELYAN_DAG_EXEC", raising=False)
    monkeypatch.setattr(
        Agent,
        "_current_runtime_policy",
        staticmethod(lambda: {"flags": {"dag_exec": True}}),
    )
    assert agent._feature_flag_enabled("ELYAN_DAG_EXEC", False) is True


def test_agent_run_runtime_task_spec_respects_team_max_parallel_from_policy(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    monkeypatch.delenv("ELYAN_DAG_EXEC", raising=False)
    monkeypatch.setattr(
        Agent,
        "_current_runtime_policy",
        staticmethod(lambda: {"flags": {"dag_exec": True}, "orchestration": {"team_max_parallel": 1}}),
    )
    monkeypatch.setattr(agent, "_validate_runtime_task_spec", lambda _spec: (True, []))

    active = {"count": 0, "max": 0}

    async def _fake_execute_tool(tool_name, params, **kwargs):
        _ = (tool_name, params, kwargs)
        active["count"] += 1
        active["max"] = max(active["max"], active["count"])
        await asyncio.sleep(0.1)
        active["count"] -= 1
        return {"success": True, "output": "ok"}

    monkeypatch.setattr(agent, "_execute_tool", _fake_execute_tool)

    task_spec = {
        "intent": "general_batch",
        "version": "1.0",
        "goal": "parallel cap test",
        "constraints": {},
        "context_assumptions": [],
        "artifacts_expected": [],
        "checks": [],
        "rollback": [],
        "required_tools": ["summarize_text"],
        "risk_level": "low",
        "timeouts": {"step_timeout_s": 5, "run_timeout_s": 10},
        "retries": {"max_attempts": 1},
        "steps": [
            {"id": "step_1", "action": "summarize_text", "params": {"text": "a"}, "checks": [{"type": "tool_success"}]},
            {"id": "step_2", "action": "summarize_text", "params": {"text": "b"}, "checks": [{"type": "tool_success"}]},
        ],
    }

    out = asyncio.run(agent._run_runtime_task_spec(task_spec, user_input="test"))
    assert "[1]" in out and "[2]" in out
    assert active["max"] == 1


def test_agent_run_runtime_task_spec_invalid_spec_returns_plan_error(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    monkeypatch.setattr(agent, "_validate_runtime_task_spec", lambda _spec: (False, ["invalid:steps"]))

    out = asyncio.run(agent._run_runtime_task_spec({}, user_input="test"))
    assert "Hata kodu: PLAN_ERROR" in out
    assert "Geçersiz TaskSpec" in out


def test_agent_run_runtime_task_spec_unknown_dependency_returns_plan_error(monkeypatch):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    monkeypatch.setattr(agent, "_validate_runtime_task_spec", lambda _spec: (True, []))

    async def _fake_execute_tool(tool_name, params, **kwargs):
        _ = (tool_name, params, kwargs)
        return {"success": True, "output": "ok"}

    monkeypatch.setattr(agent, "_execute_tool", _fake_execute_tool)

    task_spec = {
        "intent": "general_batch",
        "version": "1.0",
        "goal": "unknown dep test",
        "constraints": {},
        "context_assumptions": [],
        "artifacts_expected": [],
        "checks": [],
        "rollback": [],
        "required_tools": ["summarize_text"],
        "risk_level": "low",
        "timeouts": {"step_timeout_s": 5, "run_timeout_s": 10},
        "retries": {"max_attempts": 1},
        "steps": [
            {
                "id": "step_1",
                "action": "summarize_text",
                "params": {"text": "a"},
                "depends_on": ["step_missing"],
                "checks": [{"type": "tool_success"}],
            }
        ],
    }

    out = asyncio.run(agent._run_runtime_task_spec(task_spec, user_input="test"))
    assert "Hata kodu: PLAN_ERROR" in out
    assert "Bilinmeyen bağımlılık" in out


def test_agent_run_runtime_task_spec_run_timeout_triggers_rollback(monkeypatch, tmp_path):
    agent = Agent()
    agent.llm = _DummyLLM()
    agent.kernel = SimpleNamespace(memory=_DummyMemory(), tools=_DummyTools())
    monkeypatch.setattr(agent, "_validate_runtime_task_spec", lambda _spec: (True, []))

    rollback_file = tmp_path / "run-timeout-rollback.txt"
    called = {"rollback": 0}

    async def _fake_execute_tool(tool_name, params, **kwargs):
        step_name = str(kwargs.get("step_name") or "")
        if step_name.startswith("rollback_"):
            called["rollback"] += 1
            p = Path(str(params.get("path"))).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(params.get("content", "rollback-ok")), encoding="utf-8")
            return {"success": True, "path": str(p)}
        _ = (tool_name, params)
        await asyncio.sleep(0.55)
        return {"success": True, "output": "ok"}

    monkeypatch.setattr(agent, "_execute_tool", _fake_execute_tool)

    task_spec = {
        "intent": "general_batch",
        "version": "1.0",
        "goal": "run timeout rollback test",
        "constraints": {},
        "context_assumptions": [],
        "artifacts_expected": [],
        "checks": [],
        "rollback": [
            {
                "action": "write_file",
                "path": str(rollback_file),
                "content": "rollback-ok",
            }
        ],
        "required_tools": ["summarize_text", "write_file"],
        "risk_level": "low",
        "timeouts": {"step_timeout_s": 5, "run_timeout_s": 0.1},
        "retries": {"max_attempts": 1},
        "steps": [
            {
                "id": "step_1",
                "action": "summarize_text",
                "params": {"text": "a"},
                "checks": [{"type": "tool_success"}],
            },
            {
                "id": "step_2",
                "action": "summarize_text",
                "params": {"text": "b"},
                "depends_on": ["step_1"],
                "checks": [{"type": "tool_success"}],
            },
            {
                "id": "step_3",
                "action": "summarize_text",
                "params": {"text": "c"},
                "depends_on": ["step_2"],
                "checks": [{"type": "tool_success"}],
            },
        ],
    }

    out = asyncio.run(agent._run_runtime_task_spec(task_spec, user_input="test"))
    assert "Hata kodu: ENV_ERROR (run_timeout" in out
    assert "Rollback başlatıldı" in out
    assert called["rollback"] == 1
    assert rollback_file.exists()


def test_agent_coerce_browser_search_to_computer_use():
    agent = Agent()
    intent = {"action": "open_url", "params": {}}
    coerced = agent._coerce_intent_for_request_shape(intent, "safariden köpek resimleri arat")
    assert isinstance(coerced, dict)
    assert coerced.get("action") == "computer_use"
    params = coerced.get("params", {}) if isinstance(coerced.get("params"), dict) else {}
    steps = params.get("steps", []) if isinstance(params.get("steps"), list) else []
    assert len(steps) >= 2
    assert steps[0].get("action") == "open_app"
    assert str(steps[0].get("params", {}).get("app_name", "")).lower() == "safari"
    open_step = next((s for s in steps if s.get("action") == "open_url"), {})
    url = str(open_step.get("params", {}).get("url", ""))
    assert "google.com/search" in url
    assert "tbm=isch" in url


def test_agent_resolve_google_search_url_treats_singular_resmi_as_image_search():
    url = Agent._resolve_google_search_url("kedi resmi", user_input="kedi resmi arat")
    assert "google.com/search" in url
    assert "tbm=isch" in url


def test_agent_prepare_tool_params_computer_use_builds_steps():
    agent = Agent()
    params = agent._prepare_tool_params(
        "computer_use",
        {},
        user_input="safari aç ve youtube'da müslüm gürses çal",
        step_name="Bilgisayarı kullan",
    )
    steps = params.get("steps", []) if isinstance(params, dict) else []
    assert isinstance(steps, list)
    assert len(steps) >= 2
    actions = [str(s.get("action") or "") for s in steps if isinstance(s, dict)]
    assert "open_app" in actions
    assert "open_url" in actions


def test_agent_infer_model_a_intent_open_app(monkeypatch):
    class _Model:
        @staticmethod
        def predict(_text):
            return "open_app", 0.93

    agent = Agent()
    monkeypatch.setattr(agent, "_load_model_a", lambda model_path="": _Model())
    intent = agent._infer_model_a_intent(
        "safari aç",
        min_confidence=0.7,
        model_path="/tmp/model.json",
        allowed_actions=["open_app"],
    )
    assert isinstance(intent, dict)
    assert intent.get("action") == "open_app"
    assert intent.get("params", {}).get("app_name") == "Safari"
    assert float(intent.get("confidence", 0.0)) >= 0.7


def test_agent_infer_model_a_intent_run_safe_command(monkeypatch):
    class _Model:
        @staticmethod
        def predict(_text):
            return "run_safe_command", 0.89

    agent = Agent()
    monkeypatch.setattr(agent, "_load_model_a", lambda model_path="": _Model())
    intent = agent._infer_model_a_intent(
        "terminalde pwd komutunu çalıştır",
        min_confidence=0.6,
        allowed_actions=["run_safe_command"],
    )
    assert isinstance(intent, dict)
    assert intent.get("action") == "run_safe_command"
    assert intent.get("params", {}).get("command") == "pwd"


def test_agent_infer_model_a_intent_rejects_not_allowed_action(monkeypatch):
    class _Model:
        @staticmethod
        def predict(_text):
            return "open_app", 0.95

    agent = Agent()
    monkeypatch.setattr(agent, "_load_model_a", lambda model_path="": _Model())
    intent = agent._infer_model_a_intent(
        "safari aç",
        min_confidence=0.7,
        allowed_actions=["write_file"],
    )
    assert intent is None


def test_agent_format_result_text_renders_open_app_verification():
    agent = Agent()
    text = agent._format_result_text(
        {
            "success": True,
            "app_name": "Safari",
            "message": "Safari opened.",
            "frontmost_app": "Safari",
            "verified": True,
        }
    )
    assert "Safari opened." in text
    assert "Odak: Safari" in text
    assert "Doğrulama: OK" in text


def test_agent_format_result_text_renders_key_combo_target_warning():
    agent = Agent()
    text = agent._format_result_text(
        {
            "success": False,
            "combo": "cmd+t",
            "target_app": "Google Chrome",
            "frontmost_app": "Finder",
            "verified": False,
            "verification_warning": "key_combo hedef dışı uygulamaya gitti: Finder",
        }
    )
    assert "Hedef: Google Chrome" in text
    assert "Odak: Finder" in text
    assert "Doğrulama: Başarısız" in text
    assert "hedef dışı" in text


def test_agent_format_result_text_renders_research_document_delivery_concisely():
    agent = Agent()
    text = agent._format_result_text(
        {
            "success": True,
            "path": "/tmp/Fourier.docx",
            "delivery_dir": "/tmp/fourier_research_delivery",
            "outputs": ["/tmp/Fourier.docx"],
            "summary": "Uzun özet burada olmamalı",
            "sources": [{"title": "Kaynak", "url": "https://example.com"}],
            "source_count": 4,
            "finding_count": 5,
        }
    )
    assert "Araştırma belgesi hazır: /tmp/Fourier.docx" in text
    assert "Kaynak: 4" in text
    assert "Uzun özet" not in text
