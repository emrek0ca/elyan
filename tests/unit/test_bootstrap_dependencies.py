from __future__ import annotations

from subprocess import CompletedProcess, TimeoutExpired

from elyan.bootstrap.dependencies import DependencyManager


def test_ensure_ollama_uses_starter_model_and_handles_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    manager = DependencyManager(workspace=tmp_path)

    monkeypatch.setattr(
        "elyan.bootstrap.dependencies.shutil.which",
        lambda name: "/usr/local/bin/ollama" if name == "ollama" else None,
    )
    monkeypatch.setattr(manager, "_http_ready", lambda url: False)
    monkeypatch.setattr(manager, "_wait_for_http", lambda url, timeout_s=30.0: True)
    monkeypatch.setattr(manager, "_popen_background", lambda *args, **kwargs: object())

    calls: list[tuple[tuple[str, ...], float | None]] = []

    def fake_run(cmd, **kwargs):
        calls.append((tuple(cmd), kwargs.get("timeout")))
        if tuple(cmd[:2]) == ("ollama", "pull"):
            raise TimeoutExpired(cmd, kwargs.get("timeout"))
        return CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(manager, "_run", fake_run)

    result = manager.ensure_ollama()

    assert result["ok"] is True
    assert result["pulls"][0]["model"] == "llama3.2:3b"
    assert result["pulls"][0]["timed_out"] is True
    assert calls[0][0] == ("ollama", "pull", "llama3.2:3b")
    assert calls[0][1] == manager.ollama_pull_timeout_s
