from core.nl_cron import nl_cron


def test_nl_cron_parses_daily_hhmm_with_quoted_task():
    parsed = nl_cron.parse('Her gün 09:00\'da "satış raporunu özetle" otomasyonu kur.')
    assert parsed is not None
    assert parsed.get("cron") == "0 9 * * *"
    assert parsed.get("original_task") == "satış raporunu özetle"


def test_nl_cron_parses_weekly_day_and_time():
    parsed = nl_cron.parse("Her hafta pazartesi saat 14:30 yönetim özeti hazırla")
    assert parsed is not None
    assert parsed.get("cron") == "30 14 * * 1"
    assert "yönetim özeti hazırla" in parsed.get("original_task", "")


def test_nl_cron_parses_haftada_bir_pattern():
    parsed = nl_cron.parse("Haftada bir pazartesi 14:30 yönetim özeti hazırla")
    assert parsed is not None
    assert parsed.get("cron") == "30 14 * * 1"
    assert "yönetim özeti hazırla" in parsed.get("original_task", "")


def test_nl_cron_parses_weekday_pattern():
    parsed = nl_cron.parse('Her iş günü saat 09:15 "satış raporunu özetle" otomasyonu kur')
    assert parsed is not None
    assert parsed.get("cron") == "15 9 * * 1-5"
    assert parsed.get("original_task") == "satış raporunu özetle"
