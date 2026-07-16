from __future__ import annotations

import json
from types import SimpleNamespace

from scripts import install_extras


def test_extras_marker_is_bound_to_dependency_manifests(tmp_path, monkeypatch) -> None:
    core = tmp_path / "requirements-core.txt"
    full = tmp_path / "requirements.txt"
    marker = tmp_path / ".elyan-extras-installed"
    core.write_text("requests\n", encoding="utf-8")
    full.write_text("requests\nreportlab\n", encoding="utf-8")
    monkeypatch.setattr(install_extras, "CORE", core)
    monkeypatch.setattr(install_extras, "FULL", full)
    monkeypatch.setattr(install_extras, "DONE_MARKER", marker)

    install_extras._write_marker(failures=[])

    assert install_extras._marker_is_current() is True
    full.write_text("requests\nreportlab\npandas\n", encoding="utf-8")
    assert install_extras._marker_is_current() is False


def test_extras_installer_records_failures_and_returns_nonzero(tmp_path, monkeypatch) -> None:
    core = tmp_path / "requirements-core.txt"
    full = tmp_path / "requirements.txt"
    marker = tmp_path / ".elyan-extras-installed"
    core.write_text("requests\n", encoding="utf-8")
    full.write_text("requests\nreportlab\npandas\n", encoding="utf-8")
    monkeypatch.setattr(install_extras, "CORE", core)
    monkeypatch.setattr(install_extras, "FULL", full)
    monkeypatch.setattr(install_extras, "DONE_MARKER", marker)
    monkeypatch.setattr(
        install_extras.subprocess,
        "run",
        lambda command, **_kwargs: SimpleNamespace(returncode=1 if command[-1] == "pandas" else 0),
    )

    result = install_extras.main(force=True)
    payload = json.loads(marker.read_text(encoding="utf-8"))

    assert result == 1
    assert payload["complete"] is False
    assert payload["failedPackages"] == ["pandas"]
    assert install_extras._marker_is_current() is False


def test_extras_installer_ignores_invalid_timeout_value(tmp_path, monkeypatch) -> None:
    core = tmp_path / "requirements-core.txt"
    full = tmp_path / "requirements.txt"
    marker = tmp_path / ".elyan-extras-installed"
    core.write_text("requests\n", encoding="utf-8")
    full.write_text("requests\nreportlab\n", encoding="utf-8")
    monkeypatch.setattr(install_extras, "CORE", core)
    monkeypatch.setattr(install_extras, "FULL", full)
    monkeypatch.setattr(install_extras, "DONE_MARKER", marker)
    monkeypatch.setenv("ELYAN_EXTRAS_PACKAGE_TIMEOUT_SECONDS", "invalid")
    observed: dict[str, int] = {}

    def fake_run(_command, **kwargs):
        observed["timeout"] = kwargs["timeout"]
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(install_extras.subprocess, "run", fake_run)

    assert install_extras.main(force=True) == 0
    assert observed["timeout"] == 900
