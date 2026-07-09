from __future__ import annotations

import os
from pathlib import Path

import pytest

from actions import file_write
from runtime.capability_registry import SafeCapabilityError


def test_file_write_creates_file(tmp_path) -> None:
    target = tmp_path / "new.py"
    result = file_write.file_write(str(target), "print('hi')\n")
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "print('hi')\n"
    assert result["result"]["created"] is True
    assert result["artifacts"][0]["name"] == "new.py"


def test_file_write_refuses_overwrite_without_flag(tmp_path) -> None:
    target = tmp_path / "exists.txt"
    target.write_text("old", encoding="utf-8")
    with pytest.raises(SafeCapabilityError) as exc:
        file_write.file_write(str(target), "new")
    assert exc.value.code == "FILE_EXISTS"
    assert target.read_text(encoding="utf-8") == "old"  # değişmedi


def test_file_write_overwrites_with_flag(tmp_path) -> None:
    target = tmp_path / "exists.txt"
    target.write_text("old", encoding="utf-8")
    result = file_write.file_write(str(target), "new", overwrite=True)
    assert target.read_text(encoding="utf-8") == "new"
    assert result["result"]["overwritten"] is True


def test_file_write_blocks_sensitive_path(tmp_path) -> None:
    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    with pytest.raises(SafeCapabilityError) as exc:
        file_write.file_write(str(ssh / "id_rsa"), "malicious")
    assert exc.value.code == "ACCESS_DENIED"


def test_file_write_blocks_outside_workspace_relative(monkeypatch, tmp_path) -> None:
    # Açık olmayan (relative) yol yalnız cwd altına yazabilir; başka yere kaçamaz.
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SafeCapabilityError) as exc:
        file_write.file_write("../escape.txt", "x")
    assert exc.value.code == "ACCESS_DENIED"


def test_file_patch_anchored_replace(tmp_path) -> None:
    target = tmp_path / "app.py"
    target.write_text("def f():\n    return 1\n", encoding="utf-8")
    result = file_write.file_patch(str(target), "return 1", "return 42")
    assert target.read_text(encoding="utf-8") == "def f():\n    return 42\n"
    assert result["result"]["replacements"] == 1
    assert "diffPreview" in result["result"]


def test_file_patch_missing_anchor(tmp_path) -> None:
    target = tmp_path / "app.py"
    target.write_text("hello\n", encoding="utf-8")
    with pytest.raises(SafeCapabilityError) as exc:
        file_write.file_patch(str(target), "nonexistent", "x")
    assert exc.value.code == "PATCH_ANCHOR_NOT_FOUND"


def test_file_patch_ambiguous_anchor(tmp_path) -> None:
    target = tmp_path / "app.py"
    target.write_text("x = 1\nx = 1\n", encoding="utf-8")
    with pytest.raises(SafeCapabilityError) as exc:
        file_write.file_patch(str(target), "x = 1", "x = 2")
    assert exc.value.code == "PATCH_ANCHOR_AMBIGUOUS"


def test_file_patch_replace_all(tmp_path) -> None:
    target = tmp_path / "app.py"
    target.write_text("x = 1\nx = 1\n", encoding="utf-8")
    result = file_write.file_patch(str(target), "x = 1", "x = 2", replace_all=True)
    assert target.read_text(encoding="utf-8") == "x = 2\nx = 2\n"
    assert result["result"]["replacements"] == 2


def test_file_patch_noop_rejected(tmp_path) -> None:
    target = tmp_path / "app.py"
    target.write_text("same\n", encoding="utf-8")
    with pytest.raises(SafeCapabilityError) as exc:
        file_write.file_patch(str(target), "same", "same")
    assert exc.value.code == "INVALID_ARGUMENT"


def test_file_patch_requires_existing_file(tmp_path) -> None:
    with pytest.raises(SafeCapabilityError) as exc:
        file_write.file_patch(str(tmp_path / "nope.py"), "a", "b")
    assert exc.value.code == "FILE_NOT_FOUND"
