from core.intent_parser import IntentParser
from cli.commands import dashboard


def test_calendar_query_not_misclassified_as_list_files():
    parser = IntentParser()
    result = parser.parse("bugün takvimde ne var")
    assert result.get("action") != "list_files"
    assert result.get("action") == "get_calendar"


def test_visual_generation_command_routes_to_visual_pack():
    parser = IntentParser()
    result = parser.parse("görsel oluştur minimalist logo")
    assert result.get("action") == "create_visual_asset_pack"
    assert "brief" in result.get("params", {})


def test_multi_task_split_for_sequential_prompt():
    parser = IntentParser()
    result = parser.parse("google aç ve sonra ekran görüntüsü al")
    assert result.get("action") == "multi_task"
    tasks = result.get("tasks", [])
    assert len(tasks) >= 2
    assert tasks[0].get("action") in {"open_url", "open_app"}
    assert any(t.get("action") == "take_screenshot" for t in tasks)


def test_multi_task_split_for_open_and_research_with_plain_ve():
    parser = IntentParser()
    result = parser.parse("safariyi aç ve köpekler hakkında araştırma yap")
    assert result.get("action") == "multi_task"
    tasks = result.get("tasks", [])
    assert len(tasks) >= 2
    assert tasks[0].get("action") == "open_app"
    assert any(t.get("action") in {"research", "web_search"} for t in tasks)


def test_open_and_research_without_connector_still_multi_task():
    parser = IntentParser()
    result = parser.parse("safariyi aç köpekler hakkında araştırma yap")
    assert result.get("action") == "multi_task"
    tasks = result.get("tasks", [])
    assert len(tasks) >= 2
    assert tasks[0].get("action") == "open_app"
    assert tasks[1].get("action") in {"research", "web_search"}
    topic = str(tasks[1].get("params", {}).get("topic", ""))
    assert "köpekler" in topic


def test_read_file_phrase_icinde_ne_var_routes_to_read_file():
    parser = IntentParser()
    result = parser.parse("not.txt içinde ne var")
    assert result.get("action") == "read_file"
    assert result.get("params", {}).get("path", "").endswith("not.txt")


def test_reminder_sentence_with_time_routes_to_create_reminder():
    parser = IntentParser()
    result = parser.parse("Saat 22 de bana ilaç içmem gerekiyor hatırlat")
    assert result.get("action") == "create_reminder"
    params = result.get("params", {})
    assert "title" in params
    assert params.get("due_time") == "22:00"


def test_scheduled_tasks_phrase_routes_to_list_plans():
    parser = IntentParser()
    result = parser.parse("Planlanmış görevler")
    assert result.get("action") == "list_plans"


def test_running_apps_phrase_routes_to_get_running_apps():
    parser = IntentParser()
    result = parser.parse("hangi uygulamalar çalışıyor")
    assert result.get("action") == "get_running_apps"


def test_dashboard_no_browser_mode_does_not_open(monkeypatch):
    opened = []
    monkeypatch.setattr(dashboard.webbrowser, "open", lambda url: opened.append(url))
    dashboard.open_dashboard(port=18888, no_browser=True)
    assert opened == []
