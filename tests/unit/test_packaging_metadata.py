import tomllib
from pathlib import Path

from config import settings
from core.domain.models import AppConfig
from core.version import APP_VERSION


def test_runtime_version_constants_are_consistent():
    assert settings.VERSION == APP_VERSION
    assert AppConfig().version == APP_VERSION


def test_pyproject_uses_single_entrypoint_and_dynamic_version():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "elyan"
    assert "version" in data["project"].get("dynamic", [])
    assert data["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "core.version.__version__"
    assert data["project"]["scripts"]["elyan"] == "elyan_entrypoint:main"


def test_setup_entrypoint_and_version_source_match():
    content = Path("setup.py").read_text(encoding="utf-8")
    assert "version=APP_VERSION" in content
    assert "\"elyan=elyan_entrypoint:main\"" in content

