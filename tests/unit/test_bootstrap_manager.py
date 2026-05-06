from __future__ import annotations

import json

from elyan.bootstrap.manager import BootstrapManager


def test_bootstrap_manager_install_and_status(tmp_path, monkeypatch):
    monkeypatch.setattr("elyan.bootstrap.manager.BOOTSTRAP_BUNDLE_DIR", tmp_path / "backups")
    manager = BootstrapManager(state_path=tmp_path / "bootstrap_state.json")
    monkeypatch.setattr("elyan.bootstrap.onboard.is_setup_complete", lambda: False)
    monkeypatch.setattr("elyan.bootstrap.onboard.start_onboarding", lambda **kwargs: True)

    result = manager.install(headless=True)
    status = manager.status()

    assert result["ok"] is True
    assert status["setup_complete"] is True
    assert status["installed"] is True
    assert status["onboarded"] is True


def test_bootstrap_manager_export_bundle_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr("elyan.bootstrap.manager.BOOTSTRAP_BUNDLE_DIR", tmp_path / "backups")
    manager = BootstrapManager(state_path=tmp_path / "bootstrap_state.json")
    monkeypatch.setattr("elyan.bootstrap.manager.vault.export_bundle", lambda output_path=None: {"version": 1, "secrets": {}})
    monkeypatch.setattr("elyan.bootstrap.manager.get_knowledge_base", lambda: type("KB", (), {"list_experiences": lambda self: []})())
    monkeypatch.setattr(
        "elyan.bootstrap.manager.get_self_improvement",
        lambda: type(
            "SI",
            (),
            {
                "optimization_rules": {},
                "feedback_history": [],
                "get_summary": lambda self: {"rules": 0},
            },
        )(),
    )
    monkeypatch.setattr("elyan.bootstrap.manager.task_brain.list_all", lambda limit=1000: [])

    result = manager.export_bundle(output=str(tmp_path / "bundle.json"))

    assert result["ok"] is True
    assert (tmp_path / "bundle.json").exists()
    payload = json.loads((tmp_path / "bundle.json").read_text(encoding="utf-8"))
    assert payload["version"] == 1
