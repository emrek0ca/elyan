"""browser_session + file_move/make_directory kayıt ve politika sözleşmeleri."""

from __future__ import annotations

from pathlib import Path

import pytest

from actions.file_write import file_move, make_directory
from runtime import capability_registry as cr
from runtime import safety_policy
from runtime.capability_registry import SafeCapabilityError

_FULL_ACCESS_STATE = {"runtime": {"access": {"fullAccessSession": {"enabled": True}}}}


def test_browser_session_capabilities_registered() -> None:
    names = cr.capability_names()
    for cap in (
        "browser_session.goto",
        "browser_session.click",
        "browser_session.type",
        "browser_session.extract",
        "browser_session.snapshot",
        "browser_session.download",
        "browser_session.close",
        "make_directory",
        "file_move",
    ):
        assert cap in names, cap
        readiness = cr.capability_readiness(cap)
        assert readiness.get("name") == cap

    assert cr.capability_readiness("browser_session.download")["verificationMode"] == "artifact_exists"
    assert cr.capability_readiness("file_move")["verificationMode"] == "artifact_exists"


def test_browser_session_policy_gated_by_browser_permission() -> None:
    # İzin yokken kapalı; tam yetki oturumunda açık; close her zaman serbest.
    denied = safety_policy.evaluate_tool("browser_session.goto", {}, {})
    assert not denied.allowed and denied.code == "PERMISSION_REQUIRED"
    allowed = safety_policy.evaluate_tool("browser_session.goto", {}, _FULL_ACCESS_STATE)
    assert allowed.allowed
    assert safety_policy.evaluate_tool("browser_session.close", {}, {}).allowed


def test_fs_mutations_require_confirmation() -> None:
    denied = safety_policy.evaluate_tool("file_move", {}, _FULL_ACCESS_STATE)
    assert not denied.allowed and denied.code == "PERMISSION_REQUIRED"
    assert safety_policy.evaluate_tool("file_move", {"_confirmed": True}, {}).allowed
    assert safety_policy.evaluate_tool("make_directory", {"_confirmed": True}, {}).allowed


def test_make_directory_and_file_move_roundtrip(tmp_path: Path) -> None:
    target_dir = tmp_path / "youtube-transkript"
    created = make_directory(str(target_dir))
    assert target_dir.is_dir()
    assert created["result"]["path"] == str(target_dir)

    source = tmp_path / "transcript.txt"
    source.write_text("merhaba", encoding="utf-8")
    moved = file_move(str(source), str(target_dir))
    destination = target_dir / "transcript.txt"
    assert destination.exists() and not source.exists()
    assert moved["result"]["outputPath"] == str(destination)

    # Üzerine yazma açıkça istenmedikçe reddedilir.
    source.write_text("yeni", encoding="utf-8")
    with pytest.raises(SafeCapabilityError) as excinfo:
        file_move(str(source), str(destination))
    assert excinfo.value.code == "DESTINATION_EXISTS"
    file_move(str(source), str(destination), overwrite=True)
    assert destination.read_text(encoding="utf-8") == "yeni"
