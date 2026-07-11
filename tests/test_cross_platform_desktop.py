"""Çapraz platform masaüstü yetenekleri — Windows/Linux davranış sözleşmesi.

open_app/close_app/clipboard artık darwin-only değil; bu testler platform
dallarının (cmd start / detached spawn / psutil terminate / pano araç seçimi)
gerçek süreçlere dokunmadan doğru komutları kurduğunu doğrular.
"""

from __future__ import annotations

import pytest

import actions.clipboard as clipboard
import actions.open_app as open_app_module
import runtime.capability_registry as registry


def test_windows_open_app_uses_cmd_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(open_app_module.sys, "platform", "win32")
    calls: list[list[str]] = []

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return _Result()

    monkeypatch.setattr(open_app_module.subprocess, "run", fake_run)
    monkeypatch.setattr(open_app_module, "_matching_process_count", lambda _t: 1)
    monkeypatch.setattr(open_app_module, "_wait_for_active_app", lambda _t, **_k: False)

    outcome = open_app_module.open_app("chrome")

    assert calls == [["cmd", "/c", "start", "", "chrome"]]
    assert outcome["result"]["foregroundConfirmed"] is True
    assert outcome["result"]["verificationStatus"] == "launched"


def test_windows_open_app_maps_settings_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(open_app_module.sys, "platform", "win32")
    calls: list[list[str]] = []

    class _Result:
        returncode = 0

    monkeypatch.setattr(open_app_module.subprocess, "run", lambda cmd, **k: (calls.append(list(cmd)), _Result())[1])
    monkeypatch.setattr(open_app_module, "_matching_process_count", lambda _t: 0)
    monkeypatch.setattr(open_app_module, "_wait_for_active_app", lambda _t, **_k: False)

    open_app_module.open_app("ayarlar")

    assert calls == [["cmd", "/c", "start", "", "ms-settings:"]]


def test_linux_open_app_picks_first_available_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(open_app_module.sys, "platform", "linux")
    monkeypatch.setattr(
        open_app_module.shutil,
        "which",
        lambda name: "/usr/bin/konsole" if name == "konsole" else None,
    )
    launched: list[list[str]] = []
    monkeypatch.setattr(open_app_module, "_spawn_detached", lambda cmd: launched.append(cmd))
    monkeypatch.setattr(open_app_module, "_matching_process_count", lambda _t: 1)
    monkeypatch.setattr(open_app_module, "_wait_for_active_app", lambda _t, **_k: False)

    open_app_module.open_app("terminal")

    assert launched == [["konsole"]]


def test_non_darwin_close_app_without_process_fails_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(open_app_module.sys, "platform", "linux")
    monkeypatch.setattr(open_app_module, "_terminate_matching_processes", lambda _t: 0)

    with pytest.raises(Exception) as excinfo:
        open_app_module.close_app("Safari")

    assert getattr(excinfo.value, "code", "") == "CAPABILITY_UNAVAILABLE"


def test_non_darwin_close_app_terminates_and_confirms(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(open_app_module.sys, "platform", "win32")
    monkeypatch.setattr(open_app_module, "_terminate_matching_processes", lambda _t: 2)
    monkeypatch.setattr(open_app_module, "_wait_until_closed", lambda _t, **_k: True)
    monkeypatch.setattr(open_app_module, "_matching_process_count", lambda _t: 0)

    outcome = open_app_module.close_app("chrome")

    assert outcome["result"]["closedConfirmed"] is True
    assert outcome["result"]["verificationStatus"] == "closed_confirmed"


def test_clipboard_command_selection_per_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clipboard.sys, "platform", "win32")
    read_cmd = clipboard._read_command()
    write_cmd = clipboard._write_command()
    assert read_cmd is not None and read_cmd[0] == "powershell"
    assert write_cmd is not None and write_cmd[0] == "powershell"

    monkeypatch.setattr(clipboard.sys, "platform", "linux")
    monkeypatch.setattr(
        clipboard.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in {"xclip"} else None,
    )
    assert clipboard._read_command() == ["xclip", "-selection", "clipboard", "-o"]
    assert clipboard._write_command() == ["xclip", "-selection", "clipboard", "-i"]

    # Wayland öncelik: wl-paste varsa xclip'e düşmez.
    monkeypatch.setattr(
        clipboard.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in {"wl-paste", "wl-copy", "xclip"} else None,
    )
    assert clipboard._read_command() == ["wl-paste", "--no-newline"]
    assert clipboard._write_command() == ["wl-copy"]

    # Hiç araç yoksa güvenli mesaj (exception değil).
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: None)
    assert "pano aracı yok" in clipboard.clipboard_read()
    assert "pano aracı yok" in clipboard.clipboard_write("x")


def test_desktop_core_capabilities_declared_cross_platform() -> None:
    for capability in ("open_app", "close_app", "clipboard_read", "clipboard_write"):
        meta = registry.capability_metadata(capability)
        platforms = tuple(meta.get("supportedPlatforms", ()))
        assert set(platforms) == {"darwin", "win32", "linux"}, capability


def test_resolve_app_name_strips_space_separated_turkish_suffix() -> None:
    # "Chrome'u kapat" yerine "Chrome u kapat" yazımından gelen bozuk app hint.
    assert open_app_module._resolve_app_name("Chrome u") == "Google Chrome"
    assert open_app_module._resolve_app_name("Safari yi") == "Safari"
    assert open_app_module._resolve_app_name("Spotify yi") == "Spotify"


def test_resolve_app_name_preserves_multiword_names() -> None:
    # Gerçek iki kelimeli adlar bozulmamalı.
    assert open_app_module._resolve_app_name("Visual Studio") == "Visual Studio"
    assert open_app_module._resolve_app_name("Google Chrome") == "Google Chrome"
