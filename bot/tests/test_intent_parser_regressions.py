from core.intent_parser import IntentParser


def test_status_prompt_routes_to_screenshot():
    parser = IntentParser()
    result = parser.parse("durum nedir")
    assert result is not None
    assert result.get("action") == "take_screenshot"


def test_system_status_does_not_route_to_screenshot():
    parser = IntentParser()
    result = parser.parse("sistem durumu nedir")
    assert result is None or result.get("action") != "take_screenshot"


def test_website_builder_routes_to_multi_task_with_html_css_js():
    parser = IntentParser()
    result = parser.parse("bana bir portfolyo websitesi yap html css js ile yap")
    assert result is not None
    assert result.get("action") == "multi_task"
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
    assert len(open_urls) >= 2
    assert any("google.com/search" in t.get("params", {}).get("url", "") for t in open_urls)
    assert any("cataas.com/cat" in t.get("params", {}).get("url", "") for t in open_urls)


def test_youtube_query_cleanup_removes_connector_words():
    parser = IntentParser()
    result = parser.parse("youtube aç ve özlem özdil şarkısı aç")
    assert result is not None
    assert result.get("action") == "open_url"
    url = result.get("params", {}).get("url", "")
    assert "youtube.com/results" in url
    assert "ozlem" in url.lower() or "%C3%B6zlem" in url
    assert "search_query=ve+" not in url.lower()


def test_random_cat_image_command_routes_to_open_url():
    parser = IntentParser()
    result = parser.parse("rastgele bir kedi resmi aç")
    assert result is not None
    assert result.get("action") == "open_url"
    assert "cataas.com/cat" in result.get("params", {}).get("url", "")


def test_power_off_command_routes_to_shutdown_system():
    parser = IntentParser()
    result = parser.parse("bilgisayarı kapat")
    assert result is not None
    assert result.get("action") == "shutdown_system"
