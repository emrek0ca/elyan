from __future__ import annotations

from pathlib import Path

from elyan.bootstrap import onboard as onboarding


def test_onboard_enables_skills_without_invalid_quiet_flag(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    monkeypatch.setattr(onboarding, "_ensure_full_autonomy_defaults", lambda: None)
    monkeypatch.setattr(onboarding, "init_workspace", lambda *args, **kwargs: None)
    monkeypatch.setattr(onboarding, "_upsert_channel", lambda *args, **kwargs: None)
    monkeypatch.setattr(onboarding, "mark_setup_complete", lambda *args, **kwargs: None)
    monkeypatch.setattr(onboarding, "render_install_to_ui_guide", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        onboarding,
        "_run_elyan",
        lambda args: calls.append(list(args)) or 0,
    )

    result = onboarding.onboard(
        workspace=tmp_path,
        dry_run=False,
        open_dashboard=False,
        skip_dependencies=True,
        install_daemon=False,
        headless=True,
    )

    assert result is True
    assert calls == [["skills", "enable", "browser", "desktop", "calendar"]]


def test_onboard_installs_daemon_when_requested(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    monkeypatch.setattr(onboarding, "_ensure_full_autonomy_defaults", lambda: None)
    monkeypatch.setattr(onboarding, "init_workspace", lambda *args, **kwargs: None)
    monkeypatch.setattr(onboarding, "_upsert_channel", lambda *args, **kwargs: None)
    monkeypatch.setattr(onboarding, "mark_setup_complete", lambda *args, **kwargs: None)
    monkeypatch.setattr(onboarding, "render_install_to_ui_guide", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        onboarding,
        "_run_elyan",
        lambda args: calls.append(list(args)) or 0,
    )

    result = onboarding.onboard(
        workspace=Path(tmp_path),
        dry_run=False,
        open_dashboard=False,
        skip_dependencies=True,
        install_daemon=True,
        headless=True,
    )

    assert result is True
    assert calls == [
        ["skills", "enable", "browser", "desktop", "calendar"],
        ["service", "install"],
    ]
