from __future__ import annotations

from types import SimpleNamespace

from core.dependencies import system_runtime as system_runtime_module
from core.dependencies.system_runtime import SystemPackageRuntimeResolver
from utils.ollama_helper import OllamaHelper


def test_system_dependency_runtime_detects_native_binaries_from_error_text(monkeypatch, tmp_path):
    config_map = {
        "dependency_runtime.system.enabled": True,
        "dependency_runtime.system.auto_install": True,
        "dependency_runtime.system.audit_path": str(tmp_path / "system_dependency_runtime.jsonl"),
        "dependency_runtime.system.state_path": str(tmp_path / "system_dependency_runtime_state.json"),
    }
    monkeypatch.setattr(system_runtime_module.elyan_config, "get", lambda key, default=None: config_map.get(key, default))

    runtime = SystemPackageRuntimeResolver()
    hits = runtime.detect_missing_from_error(
        "command not found: xdg-open; tesseract not found; scrot missing; xclip missing; "
        "xsel missing; gnome-screenshot missing; ollama not found; ffmpeg not found"
    )

    assert "xdg-open" in hits
    assert "tesseract" in hits
    assert "scrot" in hits
    assert "xclip" in hits
    assert "xsel" in hits
    assert "gnome-screenshot" in hits
    assert "ollama" in hits
    assert "ffmpeg" in hits


def test_ollama_helper_ensure_available_uses_system_runtime(monkeypatch):
    calls: list[tuple[str, tuple, dict]] = []

    class _FakeRuntime:
        def ensure_binary(self, binary, **kwargs):
            calls.append((binary, tuple(), dict(kwargs)))
            return SimpleNamespace(status="installed")

    monkeypatch.setattr("utils.ollama_helper.get_system_dependency_runtime", lambda: _FakeRuntime())
    monkeypatch.setattr(OllamaHelper, "is_running", staticmethod(lambda: False))
    monkeypatch.setattr(OllamaHelper, "_start_service", staticmethod(lambda: True))

    assert OllamaHelper.ensure_available(allow_install=True, start_service=True) is True
    assert calls and calls[0][0] == "ollama"
