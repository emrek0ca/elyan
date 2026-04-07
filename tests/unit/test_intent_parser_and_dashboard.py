from core.intent_parser import IntentParser
import core.intent_parser._base as parser_base
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
    assert any(t.get("action") in {"research", "web_search", "research_document_delivery"} for t in tasks)


def test_open_and_research_without_connector_still_multi_task():
    parser = IntentParser()
    result = parser.parse("safariyi aç köpekler hakkında araştırma yap")
    assert result.get("action") == "multi_task"
    tasks = result.get("tasks", [])
    assert len(tasks) >= 2
    assert tasks[0].get("action") == "open_app"
    assert tasks[1].get("action") in {"research", "web_search", "research_document_delivery"}
    topic = str(
        tasks[1].get("params", {}).get("topic", "")
        or tasks[1].get("params", {}).get("brief", "")
    )
    assert "köpekler" in topic


def test_read_file_phrase_icinde_ne_var_routes_to_read_file():
    parser = IntentParser()
    result = parser.parse("not.txt içinde ne var")
    assert result.get("action") == "read_file"
    assert result.get("params", {}).get("path", "").endswith("not.txt")


def test_read_file_phrase_without_extension_routes_to_read_file():
    parser = IntentParser()
    result = parser.parse("not dosyası içinde ne var")
    assert result.get("action") == "read_file"
    assert result.get("params", {}).get("path", "").endswith("not")


def test_delete_file_phrase_without_extension_routes_to_delete_file():
    parser = IntentParser()
    result = parser.parse("not dosyasını sil")
    assert result.get("action") == "delete_file"
    assert result.get("params", {}).get("path", "").endswith("not")


def test_delete_pronoun_routes_to_delete_file_with_context_placeholder():
    parser = IntentParser()
    result = parser.parse("bunu sil")
    assert result.get("action") == "delete_file"
    assert "path" in result.get("params", {})


def test_delete_desktop_screenshot_images_routes_to_batch_delete_pattern():
    parser = IntentParser()
    result = parser.parse("Masaüstündeki ekran resimlerini sil")
    assert result.get("action") == "delete_file"
    params = result.get("params", {})
    assert str(params.get("directory", "")).endswith("Desktop")
    patterns = params.get("patterns", [])
    assert isinstance(patterns, list) and patterns
    assert any("screenshot" in str(p).lower() or "ekran" in str(p).lower() for p in patterns)


def test_ultra_short_app_invocation_routes_to_open_app():
    parser = IntentParser()
    result = parser.parse("safari a.")
    assert result.get("action") == "open_app"
    assert result.get("params", {}).get("app_name") == "Safari"


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


def test_battery_query_routes_to_get_battery_status():
    parser = IntentParser()
    result = parser.parse("bilgisayarın şarjı kaç")
    assert result.get("action") == "get_battery_status"


def test_telegram_open_phrase_not_misclassified_as_system_info():
    parser = IntentParser()
    result = parser.parse("Telegramı aç ve bana mesaj gönder")
    assert result.get("action") != "get_system_info"
    assert result.get("action") in {"open_app", "multi_task"}


def test_word_parser_extracts_inline_content():
    parser = IntentParser()
    result = parser.parse("word belgesi oluştur içine haftalık satış özeti yaz")
    assert result.get("action") == "create_word_document"
    content = str(result.get("params", {}).get("content", ""))
    assert "haftalık satış özeti" in content


def test_excel_parser_extracts_headers_and_content():
    parser = IntentParser()
    result = parser.parse("excel dosyası oluştur kolonlar: Tarih, Tutar, Not içine günlük gelir yaz")
    assert result.get("action") == "create_excel"
    params = result.get("params", {})
    assert params.get("headers") == ["tarih", "tutar", "not"]
    assert "günlük gelir" in str(params.get("content", ""))


def test_write_file_parser_handles_desktop_note_natural_language():
    parser = IntentParser()
    result = parser.parse("masaüstüne not olarak Ahmet'e borcum var yaz")
    assert result.get("action") == "write_file"
    params = result.get("params", {})
    assert "Desktop" in str(params.get("path", ""))
    assert str(params.get("path", "")).endswith("not.txt")
    assert "Ahmet'e borcum var" in str(params.get("content", ""))


def test_multi_task_split_handles_then_connector():
    parser = IntentParser()
    result = parser.parse("safariyi aç sonra köpekler hakkında araştırma yap")
    assert result.get("action") == "multi_task"
    tasks = result.get("tasks", [])
    assert len(tasks) >= 2
    assert tasks[0].get("action") == "open_app"
    assert tasks[1].get("action") in {"research", "web_search", "research_document_delivery"}


def test_browser_target_open_routes_to_multi_task_with_wikipedia_search():
    parser = IntentParser()
    result = parser.parse("safariden wikipedia einstein aç")
    assert result.get("action") == "multi_task"
    tasks = result.get("tasks", [])
    assert len(tasks) == 2
    assert tasks[0].get("action") == "open_app"
    assert tasks[0].get("params", {}).get("app_name") == "Safari"
    assert tasks[1].get("action") == "open_url"
    assert tasks[1].get("params", {}).get("browser") == "Safari"
    assert "wikipedia.org" in str(tasks[1].get("params", {}).get("url", ""))
    assert "einstein" in str(tasks[1].get("params", {}).get("url", "")).lower()


def test_browser_target_open_routes_youtube_query_through_requested_browser():
    parser = IntentParser()
    result = parser.parse("chrome dan youtube tarkan aç")
    assert result.get("action") == "multi_task"
    tasks = result.get("tasks", [])
    assert len(tasks) == 2
    assert tasks[0].get("action") == "open_app"
    assert tasks[0].get("params", {}).get("app_name") == "Google Chrome"
    assert tasks[1].get("action") == "open_url"
    assert tasks[1].get("params", {}).get("browser") == "Google Chrome"
    assert "youtube.com/results" in str(tasks[1].get("params", {}).get("url", ""))
    assert "tarkan" in str(tasks[1].get("params", {}).get("url", "")).lower()


def test_browser_search_and_copy_first_result_builds_four_step_plan():
    parser = IntentParser()
    result = parser.parse("chrome dan tarkan arat ve en üsttekini kopyala")
    assert result.get("action") == "multi_task"
    tasks = result.get("tasks", [])
    assert len(tasks) == 4
    assert tasks[0].get("action") == "open_app"
    assert tasks[1].get("action") == "open_url"
    assert tasks[2].get("action") == "web_search"
    assert tasks[3].get("action") == "write_clipboard"
    assert tasks[3].get("depends_on") == ["task_3"]


def test_research_parser_infers_academic_policy():
    parser = IntentParser()
    result = parser.parse("köpek sağlığı hakkında akademik kaynaklarla araştırma yap, güvenilirlik en az %80")
    assert result.get("action") == "research_document_delivery"
    params = result.get("params", {})
    assert params.get("source_policy") == "academic"
    assert params.get("min_reliability") == 0.8


def test_research_parser_strips_copy_noise_from_topic():
    parser = IntentParser()
    result = parser.parse("köpekler hakkında araştırma yap ve kopyala")
    assert result.get("action") in {"research", "research_document_delivery", "multi_task"}
    if result.get("action") in {"research", "research_document_delivery"}:
        topic = str(
            result.get("params", {}).get("topic", "")
            or result.get("params", {}).get("brief", "")
        ).lower()
        assert "kopyala" not in topic
        assert "köpekler" in topic


def test_clipboard_parser_handles_bunu_kopyala_without_inline_text():
    parser = IntentParser()
    result = parser.parse("bunu kopyala")
    assert result.get("action") == "write_clipboard"
    assert "text" in result.get("params", {})


def test_screenshot_parser_handles_ss_gonder():
    parser = IntentParser()
    result = parser.parse("ss gönder")
    assert result.get("action") == "take_screenshot"


def test_coding_project_parser_for_website_with_vscode():
    parser = IntentParser()
    result = parser.parse("AI destekli bir website yap ve vscode'da aç")
    assert result.get("action") == "create_coding_project"
    params = result.get("params", {})
    assert params.get("project_kind") == "website"
    assert params.get("ide") == "vscode"
    assert params.get("open_ide") is True
    assert "website yap" in str(params.get("brief", "")).lower()


def test_coding_project_parser_for_app_with_cursor():
    parser = IntentParser()
    result = parser.parse("Python ile uygulama geliştir ve cursor ile aç")
    assert result.get("action") == "create_coding_project"
    params = result.get("params", {})
    assert params.get("project_kind") == "app"
    assert params.get("stack") == "python"
    assert params.get("ide") == "cursor"


def test_coding_project_parser_extracts_project_name_from_prefix():
    parser = IntentParser()
    result = parser.parse("Python ile CRM uygulaması geliştir ve cursor ile aç")
    assert result.get("action") == "create_coding_project"
    params = result.get("params", {})
    assert str(params.get("project_name", "")).lower() == "crm"


def test_coding_project_parser_marks_expert_complexity_when_requested():
    parser = IntentParser()
    result = parser.parse("enterprise seviyede çok karmaşık bir website geliştir ve antigravity ile aç")
    assert result.get("action") == "create_coding_project"
    params = result.get("params", {})
    assert params.get("complexity") == "expert"
    assert params.get("ide") == "antigravity"


def test_projects_alias_prefers_desktop_folder_when_home_variant_missing(monkeypatch, tmp_path):
    desktop_projects = tmp_path / "Desktop" / "Projects"
    desktop_projects.mkdir(parents=True)
    monkeypatch.setattr(parser_base, "HOME_DIR", tmp_path)

    parser = IntentParser()
    result = parser.parse("projects içinde ne var")
    assert result.get("action") == "list_files"
    assert result.get("params", {}).get("path") == str(desktop_projects)


def test_dashboard_no_browser_mode_does_not_open(monkeypatch):
    calls = []
    monkeypatch.setattr(dashboard, "open_desktop", lambda detached=False: calls.append(detached) or 0)
    result = dashboard.open_dashboard(port=18888, no_browser=True)
    assert result == 0
    assert calls == []


def test_dashboard_default_mode_opens_desktop_alias(monkeypatch):
    calls = []
    monkeypatch.setattr(dashboard, "open_desktop", lambda detached=False: calls.append(detached) or 0)
    dashboard.open_dashboard(port=18888)
    assert calls == [True]


def test_dashboard_ops_mode_keeps_opening_desktop_alias(monkeypatch):
    calls = []
    monkeypatch.setattr(dashboard, "open_desktop", lambda detached=False: calls.append(detached) or 0)
    dashboard.open_dashboard(port=18888, ops=True)
    assert calls == [True]
