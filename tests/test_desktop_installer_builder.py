from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import build_desktop_installers as builder
from scripts import generate_release_sbom


def test_release_lock_is_hashed_and_sbom_has_locked_components() -> None:
    lock = builder.RELEASE_LOCK.read_text(encoding="utf-8")
    assert "--hash=sha256:" in lock

    sbom = generate_release_sbom.build_sbom()
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["metadata"]["component"]["version"] == builder.package_version()
    components = sbom["components"]
    assert len(components) >= 100
    assert any(component["name"] == "google-genai" for component in components)
    assert any(component["name"] == "qiskit" for component in components)


def test_copy_sources_preserves_runtime_contract_without_cache(tmp_path: Path) -> None:
    destination = tmp_path / "app"
    builder.copy_sources(destination)

    assert (destination / "cli" / "main.py").is_file()
    assert (destination / "runtime" / "bridge.py").is_file()
    assert json.loads((destination / "package.json").read_text(encoding="utf-8"))["version"]
    assert not list(destination.rglob("*.pyc"))
    assert not list(destination.rglob("__pycache__"))


def test_non_macos_payload_does_not_ship_native_apple_helpers(tmp_path: Path) -> None:
    destination = tmp_path / "app"
    builder.copy_sources(destination, target_platform="windows")
    assert not (destination / "helpers").exists()


def test_portable_python_alias_is_rewritten_as_relative(tmp_path: Path) -> None:
    python_root = tmp_path / "python"
    version = python_root / "cpython-3.11.15-macos-aarch64-none"
    version.mkdir(parents=True)
    alias = python_root / "cpython-3.11-macos-aarch64-none"
    alias.symlink_to(version.resolve(), target_is_directory=True)

    builder.normalize_portable_python_links(python_root)

    assert alias.is_symlink()
    assert alias.readlink() == Path(version.name)


def test_production_macos_build_requires_developer_id(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ELYAN_REQUIRE_SIGNING", "1")
    monkeypatch.delenv("MACOS_CODESIGN_IDENTITY", raising=False)
    with pytest.raises(RuntimeError, match="MACOS_CODESIGN_IDENTITY"):
        builder.sign_macos_app(tmp_path / "Elyan.app")


def test_production_macos_build_requires_notarization_credentials(monkeypatch) -> None:
    monkeypatch.setenv("ELYAN_REQUIRE_SIGNING", "1")
    for name in ("APPLE_ID", "APPLE_TEAM_ID", "APPLE_APP_SPECIFIC_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="required for notarization"):
        builder.macos_notary_arguments()


def test_production_windows_build_requires_authenticode_certificate(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ELYAN_REQUIRE_SIGNING", "1")
    monkeypatch.delenv("WINDOWS_CERTIFICATE_PATH", raising=False)
    with pytest.raises(RuntimeError, match="WINDOWS_CERTIFICATE_PATH"):
        builder.sign_windows_file(tmp_path / "Elyan.exe")


def test_native_launchers_are_present_and_shell_free() -> None:
    swift = (builder.ROOT / "desktop_installer" / "macos" / "ElyanLauncher.swift").read_text(encoding="utf-8")
    windows = (builder.ROOT / "desktop_installer" / "windows" / "ElyanLauncher.cs").read_text(encoding="utf-8")
    assert "NSWorkspace.shared.openApplication" in swift
    assert "ProcessStartInfo" in windows
    assert "shell=True" not in swift
    assert "shell=True" not in windows
