"""Windows ekran + takvim arka uçlarının sözleşmesi.

Kapatılan boşluk: ekran okuma ve takvim tek bir kaynaktan besleniyordu —
macOS'a özel Swift helper'ları (`helpers/`). O klasör Windows derlemesinde
zaten siliniyor (`build_desktop_installers.copy_sources`), dolayısıyla
Windows'ta iki yetenek de hiç çalışmıyordu.

Değişmez: Windows arka uçları macOS helper'larıyla AYNI JSON sözleşmesini
üretir, böylece üst katmanlar (desktop_operator, screen_vision, calendar)
platforma göre dallanmaz. Kullanılamayan durumda uydurma değil AÇIK ret döner.
"""

from __future__ import annotations

import datetime as dt
import json

from actions import _calendar_windows, _screen_capture_windows, calendar
from actions._platform_common import require_screen_capture_platform


def test_screen_backend_refuses_cleanly_off_windows() -> None:
    """Yanlış platformda çökmez, sözleşmeye uygun ret döner."""
    payload = _screen_capture_windows.capture_active_window_payload()
    assert payload["ok"] is False
    assert payload["detail"]

    raw = _screen_capture_windows.capture_active_window_raw()
    assert json.loads(raw)["ok"] is False


def test_screen_payload_matches_the_macos_helper_contract() -> None:
    """Üst katman `_parse_capture_payload` bu alanları bekler."""
    from actions import screen_vision

    ok, detail, meta = screen_vision._parse_capture_payload(
        json.dumps(
            {
                "ok": True,
                "image_path": "/tmp/x.png",
                "owner_name": "Notepad",
                "window_title": "not.txt",
                "bounds": {"x": 0, "y": 0, "width": 800, "height": 600},
            }
        )
    )
    assert ok and meta is not None
    assert meta["image_path"] == "/tmp/x.png"
    assert meta["owner_name"] == "Notepad"
    assert meta["bounds"]["width"] == 800


def test_calendar_backend_refuses_cleanly_off_windows() -> None:
    now = dt.datetime.now()
    payload = _calendar_windows.read_events(now, now + dt.timedelta(days=1))
    assert payload["ok"] is False
    assert payload["detail"]


def test_calendar_writes_are_refused_explicitly_not_silently() -> None:
    """Yazma desteklenmiyorsa AÇIKÇA reddedilir.

    Sessiz başarısızlık ya da "eklendi" demek yasak: kullanıcı etkinliğin
    takvime girdiğini sanıp toplantıyı kaçırır.
    """
    for action in ("ekleme", "silme"):
        payload = json.loads(_calendar_windows.unsupported_write_raw(action))
        assert payload["ok"] is False
        assert action in payload["detail"]


def test_windows_calendar_ranges_cover_every_helper_mode() -> None:
    """`_normalize_query` üreten her mod somut bir aralığa çevrilebilmeli."""
    spans = {
        mode: (lambda pair: (pair[1] - pair[0]).days)(
            calendar._windows_range_for_mode(mode, None)
        )
        for mode in ("today", "tomorrow", "week", "next", "agenda", "range")
    }
    assert spans["today"] == 1
    assert spans["tomorrow"] == 1
    assert spans["week"] == 7
    assert spans["next"] == 30
    assert spans["agenda"] == 30
    # Bilinmeyen/aralık modu güvenli varsayılana düşer, patlamaz.
    assert spans["range"] == 1


def test_explicit_range_payload_wins_over_mode_default() -> None:
    start = dt.datetime(2026, 3, 1, 0, 0, 0)
    end = dt.datetime(2026, 3, 8, 0, 0, 0)
    resolved = calendar._windows_range_for_mode(
        "range", {"start_iso": start.isoformat(), "end_iso": end.isoformat()}
    )
    assert resolved == (start, end)


def test_calendar_parser_accepts_the_windows_payload_shape() -> None:
    """Windows arka ucunun ürettiği gövde mevcut ayrıştırıcıdan geçmeli."""
    start_ts = int(dt.datetime(2026, 3, 1, 10, 0).timestamp())
    raw = json.dumps(
        {
            "ok": True,
            "events": [
                {
                    "start_ts": start_ts,
                    "end_ts": start_ts + 3600,
                    "calendar": "outlook",
                    "title": "Yatırımcı Sunumu",
                    "location": "Teams",
                    "all_day": False,
                }
            ],
        }
    )
    ok, detail, events = calendar._parse_payload(raw)
    assert ok and not detail
    assert events[0]["title"] == "Yatırımcı Sunumu"
    assert events[0]["end_ts"] - events[0]["start_ts"] == 3600


def test_screen_capture_gate_allows_windows_and_macos_only() -> None:
    """Kapı Windows'u artık reddetmiyor; desteklenmeyen platform hâlâ reddediliyor."""
    import sys

    # Bu makinede (macOS ya da Windows) kapı geçmeli.
    if sys.platform in {"darwin", "win32"}:
        require_screen_capture_platform("Ekran analizi")
    else:  # pragma: no cover - CI dışı platform
        try:
            require_screen_capture_platform("Ekran analizi")
            raise AssertionError("desteklenmeyen platform reddedilmeliydi")
        except Exception as exc:
            assert getattr(exc, "code", "") == "UNSUPPORTED_PLATFORM"
