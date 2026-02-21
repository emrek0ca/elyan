from core.intent_parser import IntentParser


def test_power_shutdown_does_not_map_to_close_app():
    parser = IntentParser()
    result = parser.parse("bilgisayarı kapat")
    assert result is not None
    assert result.get("action") == "shutdown_system"


def test_power_restart_mapping():
    parser = IntentParser()
    result = parser.parse("sistemi yeniden başlat")
    assert result is not None
    assert result.get("action") == "restart_system"


def test_lock_screen_mapping_variants():
    parser = IntentParser()
    r1 = parser.parse("ekranı kilitle")
    r2 = parser.parse("sistemi kilitle")
    assert r1 is not None and r1.get("action") == "lock_screen"
    assert r2 is not None and r2.get("action") == "lock_screen"


def test_close_app_still_works_for_real_app():
    parser = IntentParser()
    result = parser.parse("safari kapat")
    assert result is not None
    assert result.get("action") == "close_app"
    assert result.get("params", {}).get("app_name") == "Safari"
