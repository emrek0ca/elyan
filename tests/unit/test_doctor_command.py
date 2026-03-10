from __future__ import annotations

from types import SimpleNamespace

from cli.commands import doctor


def test_doctor_vision_check_does_not_raise_when_ollama_exists(monkeypatch):
    monkeypatch.setattr(doctor, "_check_port", lambda port, host="127.0.0.1": (True, "Available"))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/local/bin/ollama" if name in {"ollama", "docker", "ffmpeg"} else None)
    monkeypatch.setattr(doctor.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="llava:7b\n", stderr=""))
    monkeypatch.setattr(doctor.keychain, "is_available", lambda: True)
    monkeypatch.setattr(doctor.keychain, "audit_env_plaintext", lambda path: {"findings": []})
    monkeypatch.setattr(doctor.keychain, "audit_config_plaintext", lambda path: {"findings": []})
    monkeypatch.setattr(doctor.elyan_config, "get", lambda key, default=None: [] if key == "channels" else ("openai" if key == "models.default.provider" else default))

    issues = doctor.run_doctor(fix=False)
    assert isinstance(issues, int)
