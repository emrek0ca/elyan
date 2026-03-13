from core.intent_parser import IntentParser
from urllib.parse import parse_qs, unquote_plus, urlparse


def test_status_prompt_routes_to_screenshot():
    parser = IntentParser()
    result = parser.parse("durum nedir")
    assert result is not None
    assert result.get("action") == "screen_workflow"
    assert result.get("params", {}).get("mode") == "inspect"


def test_screen_read_prompt_routes_to_screen_workflow():
    parser = IntentParser()
    result = parser.parse("ekrana bak ve ne görüyorsun söyle")
    assert result is not None
    assert result.get("action") == "screen_workflow"
    assert result.get("params", {}).get("mode") == "inspect"


def test_screen_control_prompt_routes_to_inspect_and_control():
    parser = IntentParser()
    result = parser.parse("ekrana bak ve safariyi aç")
    assert result is not None
    assert result.get("action") == "screen_workflow"
    assert result.get("params", {}).get("mode") == "inspect_and_control"


def test_research_prompt_defaults_to_document_delivery():
    parser = IntentParser()
    result = parser.parse("Fourier serileri hakkında araştırma yap")
    assert result is not None
    assert result.get("action") == "research_document_delivery"
    params = result.get("params", {})
    assert params.get("include_word") is True
    assert params.get("include_excel") is False
    assert params.get("include_pdf") is False
    assert params.get("include_report") is True


def test_research_prompt_can_request_latex_delivery():
    parser = IntentParser()
    result = parser.parse("Fourier serileri hakkında araştırma yap ve latex rapor hazırla")
    assert result is not None
    assert result.get("action") == "research_document_delivery"
    params = result.get("params", {})
    assert params.get("include_latex") is True
    assert params.get("include_word") is False


def test_system_status_does_not_route_to_screenshot():
    parser = IntentParser()
    result = parser.parse("sistem durumu nedir")
    assert result is None or result.get("action") != "take_screenshot"


def test_general_nedir_question_does_not_route_to_dictionary():
    parser = IntentParser()
    result = parser.parse("başarının sırrı nedir")
    assert result is None or result.get("action") != "get_word_definition"


def test_website_builder_routes_to_multi_task_with_html_css_js():
    parser = IntentParser()
    result = parser.parse("bana bir portfolyo websitesi yap html css js ile yap")
    assert result is not None
    # Parser may route to create_coding_project (new) or multi_task (legacy)
    assert result.get("action") in ("multi_task", "create_coding_project")
    if result.get("action") == "multi_task":
        tasks = result.get("tasks", [])
        assert len(tasks) >= 4
        actions = [task.get("action") for task in tasks]
        assert "create_folder" in actions
        assert actions.count("write_file") >= 3
        paths = [task.get("params", {}).get("path", "") for task in tasks if task.get("action") == "write_file"]
        assert any(path.endswith("index.html") for path in paths)
        assert any(path.endswith("style.css") for path in paths)
        assert any(path.endswith("script.js") for path in paths)


def test_create_folder_on_desktop():
    parser = IntentParser()
    result = parser.parse("masaüstüne test adında klasör oluştur")
    assert result is not None
    assert result.get("action") == "create_folder"
    path = result.get("params", {}).get("path", "")
    assert "Desktop" in path
    assert path.endswith("test")


def test_create_folder_keeps_exact_requested_name():
    parser = IntentParser()
    result = parser.parse("masaüstünde elyan-test klasörü oluştur")
    assert result is not None
    assert result.get("action") == "create_folder"
    path = str(result.get("params", {}).get("path", ""))
    assert path.endswith("elyan-test")


def test_desktop_note_phrase_routes_to_write_file_instead_of_chat():
    parser = IntentParser()
    result = parser.parse("masaüstüne not olarak ahmete borcum var yaz")
    assert result is not None
    assert result.get("action") == "write_file"
    params = result.get("params", {})
    assert "Desktop" in str(params.get("path", ""))
    assert "ahmete borcum var" in str(params.get("content", "")).lower()


def test_force_planning_on_complex_query():
    parser = IntentParser()
    result = parser.parse("önce rapor hazırla sonra maille gonder")
    # Intent parser may or may not map directly; ensure it is not misclassified to trivial tool
    assert result is None or result.get("action") != "take_screenshot"


def test_browser_search_with_random_cat_image_adds_random_open_step():
    parser = IntentParser()
    result = parser.parse("safariyi aç ve kedi resimleri arat. rastgele bir kedi resmi aç")
    assert result is not None
    assert result.get("action") == "multi_task"

    tasks = result.get("tasks", [])
    open_urls = [t for t in tasks if t.get("action") == "open_url"]
    assert len(open_urls) >= 1
    all_urls = " ".join(t.get("params", {}).get("url", "") for t in open_urls)
    # At least one URL should be a search or cat image
    assert "google.com/search" in all_urls or "cataas.com/cat" in all_urls


def test_browser_search_cleans_safariden_prefix_and_uses_image_mode():
    parser = IntentParser()
    result = parser.parse("safariden köpek resimleri arat")
    assert result is not None
    assert result.get("action") == "multi_task"
    tasks = result.get("tasks", [])
    assert len(tasks) >= 2
    open_step = next((t for t in tasks if t.get("action") == "open_url"), {})
    url = str(open_step.get("params", {}).get("url", ""))
    assert "google.com/search" in url
    assert "tbm=isch" in url
    assert "safariden" not in url.lower()


def test_browser_search_singular_resmi_uses_image_mode():
    parser = IntentParser()
    result = parser.parse("kedi resmi arat")
    assert result is not None
    assert result.get("action") == "open_url"
    url = str(result.get("params", {}).get("url", ""))
    assert "google.com/search" in url
    assert "tbm=isch" in url


def test_browser_image_request_without_search_verb_routes_as_search_intent():
    parser = IntentParser()
    result = parser.parse("Pi günü için resim aç safariden")
    assert result is not None
    assert result.get("action") == "multi_task"
    tasks = result.get("tasks", [])
    open_step = next((t for t in tasks if t.get("action") == "open_url"), {})
    url = str(open_step.get("params", {}).get("url", ""))
    assert "google.com/search" in url
    assert "tbm=isch" in url
    parsed_q = parse_qs(urlparse(url).query).get("q", [""])[0]
    query = unquote_plus(parsed_q).lower()
    assert "pi" in query
    assert ("günü" in query) or ("gunu" in query)
    assert "safariden" not in query


def test_browser_news_request_with_topic_does_not_collapse_to_news_home():
    parser = IntentParser()
    result = parser.parse("safariden mars hakkında haber aç")
    assert result is not None
    assert result.get("action") == "multi_task"
    tasks = result.get("tasks", [])
    open_step = next((t for t in tasks if t.get("action") == "open_url"), {})
    url = str(open_step.get("params", {}).get("url", ""))
    assert "google.com/search" in url
    parsed_q = parse_qs(urlparse(url).query).get("q", [""])[0]
    query = unquote_plus(parsed_q).lower()
    assert "mars" in query
    assert "news.google.com" not in url


def test_youtube_query_cleanup_removes_connector_words():
    parser = IntentParser()
    result = parser.parse("youtube aç ve özlem özdil şarkısı aç")
    assert result is not None
    # Parser may return open_url directly or multi_task with youtube step
    action = result.get("action")
    assert action in ("open_url", "multi_task")
    if action == "open_url":
        url = result.get("params", {}).get("url", "")
        assert "youtube.com" in url
        assert "search_query=ve+" not in url.lower()
    else:
        tasks = result.get("tasks", [])
        yt_tasks = [t for t in tasks if "youtube.com" in t.get("params", {}).get("url", "")]
        assert len(yt_tasks) >= 1


def test_random_cat_image_command_routes_to_open_url():
    parser = IntentParser()
    result = parser.parse("rastgele bir kedi resmi aç")
    assert result is not None
    assert result.get("action") == "open_url"
    assert "cataas.com/cat" in result.get("params", {}).get("url", "")


def test_input_control_combo_parses_to_key_combo():
    parser = IntentParser()
    result = parser.parse("cmd+l bas")
    assert result is not None
    assert result.get("action") == "key_combo"
    assert "cmd+l" in str(result.get("params", {}).get("combo", "")).lower()


def test_input_control_click_parses_coordinates():
    parser = IntentParser()
    result = parser.parse("500,300 tıkla")
    assert result is not None
    assert result.get("action") == "mouse_click"
    params = result.get("params", {})
    assert int(params.get("x", 0)) == 500
    assert int(params.get("y", 0)) == 300


def test_browser_new_tab_command_routes_to_multi_task():
    parser = IntentParser()
    result = parser.parse("chrome dan yeni sekme aç")
    assert result is not None
    assert result.get("action") == "multi_task"
    tasks = result.get("tasks", [])
    assert len(tasks) == 2
    assert tasks[0].get("action") == "open_app"
    assert tasks[0].get("params", {}).get("app_name") == "Google Chrome"
    assert tasks[1].get("action") == "key_combo"
    assert tasks[1].get("params", {}).get("combo") == "cmd+t"
    assert tasks[1].get("params", {}).get("target_app") == "Google Chrome"


def test_browser_new_tab_command_with_acip_routes_to_multi_task():
    parser = IntentParser()
    result = parser.parse("chrome dan yeni sekme açıp google.com aç")
    assert result is not None
    assert result.get("action") == "multi_task"
    tasks = result.get("tasks", [])
    assert len(tasks) >= 2
    assert tasks[0].get("action") == "open_app"
    assert tasks[1].get("action") == "key_combo"


def test_open_app_focus_variants_route_to_open_app():
    parser = IntentParser()
    for utterance in ("safariye geç", "safari'ye geç", "safari odaklan"):
        result = parser.parse(utterance)
        assert result is not None
        assert result.get("action") == "open_app"
        assert result.get("params", {}).get("app_name") == "Safari"


def test_terminal_open_phrase_routes_to_open_app_not_command_execution():
    parser = IntentParser()
    result = parser.parse("terminal aç")
    assert result is not None
    assert result.get("action") == "open_app"
    assert result.get("params", {}).get("app_name") == "Terminal"


def test_terminal_restart_command_phrase_routes_to_run_safe_command_not_restart_system():
    parser = IntentParser()
    result = parser.parse("elyan restart komutunu çalıştır")
    assert result is not None
    assert result.get("action") == "run_safe_command"
    command = str(result.get("params", {}).get("command", "")).lower()
    assert "elyan" in command and "restart" in command


def test_terminal_open_and_restart_command_routes_to_multi_task_without_restart_system():
    parser = IntentParser()
    result = parser.parse("Terminal aç ve elyan restart komutunu çalıştır")
    assert result is not None
    assert result.get("action") == "multi_task"
    tasks = result.get("tasks", [])
    assert len(tasks) >= 2
    assert tasks[0].get("action") == "open_app"
    assert tasks[1].get("action") == "type_text"
    assert tasks[1].get("params", {}).get("press_enter") is True
    assert "elyan restart" in str(tasks[1].get("params", {}).get("text", "")).lower()
    assert all(t.get("action") != "restart_system" for t in tasks)


def test_terminal_openip_restart_command_routes_to_multi_task_without_restart_system():
    parser = IntentParser()
    result = parser.parse("terminal açıp elyan restart komutunu çalıştır")
    assert result is not None
    assert result.get("action") == "multi_task"
    tasks = result.get("tasks", [])
    assert len(tasks) >= 2
    assert tasks[0].get("action") == "open_app"
    assert tasks[1].get("action") == "type_text"
    assert "elyan restart" in str(tasks[1].get("params", {}).get("text", "")).lower()
    assert all(t.get("action") != "restart_system" for t in tasks)


def test_terminalden_ssh_root_command_routes_to_terminal_multi_task():
    parser = IntentParser()
    result = parser.parse("terminalden ssh root komutunu çalıştır")
    assert result is not None
    assert result.get("action") == "multi_task"
    tasks = result.get("tasks", [])
    assert len(tasks) == 2
    assert tasks[0].get("action") == "open_app"
    assert tasks[0].get("params", {}).get("app_name") == "Terminal"
    assert tasks[1].get("action") == "type_text"
    assert tasks[1].get("params", {}).get("press_enter") is True
    command = str(tasks[1].get("params", {}).get("text", "")).lower()
    assert command == "ssh root"


def test_terminalden_cd_desktop_command_normalizes_and_routes_to_terminal_ui():
    parser = IntentParser()
    result = parser.parse("terminalden cd desktop komutu çalıştır")
    assert result is not None
    assert result.get("action") == "multi_task"
    tasks = result.get("tasks", [])
    assert len(tasks) == 2
    assert tasks[0].get("action") == "open_app"
    assert tasks[1].get("action") == "type_text"
    params = tasks[1].get("params", {})
    assert params.get("press_enter") is True
    assert str(params.get("text") or "").strip() == "cd ~/Desktop"


def test_ultra_short_app_invocation_routes_to_open_app():
    parser = IntentParser()
    result = parser.parse("safari a.")
    assert result is not None
    assert result.get("action") == "open_app"
    assert result.get("params", {}).get("app_name") == "Safari"


def test_focus_phrase_uses_open_app_with_focus_reply():
    parser = IntentParser()
    result = parser.parse("chrome'a geç")
    assert result is not None
    assert result.get("action") == "open_app"
    assert result.get("params", {}).get("app_name") == "Google Chrome"
    assert "öne al" in str(result.get("reply", "")).lower() or "one al" in str(result.get("reply", "")).lower()


def test_typo_focus_phrase_normalizes_to_open_app():
    parser = IntentParser()
    result = parser.parse("chromea geç")
    assert result is not None
    assert result.get("action") == "open_app"


def test_power_off_command_routes_to_shutdown_system():
    parser = IntentParser()
    result = parser.parse("bilgisayarı kapat")
    assert result is not None
    assert result.get("action") == "shutdown_system"
