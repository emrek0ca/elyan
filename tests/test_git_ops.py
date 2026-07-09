from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from actions import git_ops
from runtime.capability_registry import SafeCapabilityError


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "a.txt").write_text("hello\n", encoding="utf-8")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-m", "init")


def test_git_status_clean(tmp_path) -> None:
    _init_repo(tmp_path)
    result = git_ops.git_status(str(tmp_path))
    assert result["result"]["clean"] is True
    assert result["result"]["changeCount"] == 0
    assert "temiz" in result["text"]


def test_git_status_reports_changes(tmp_path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hello world\n", encoding="utf-8")
    (tmp_path / "new.txt").write_text("fresh\n", encoding="utf-8")
    _git(tmp_path, "add", "new.txt")
    result = git_ops.git_status(str(tmp_path))
    res = result["result"]
    assert res["clean"] is False
    assert any(e["file"] == "a.txt" for e in res["unstaged"])
    assert any(e["file"] == "new.txt" for e in res["staged"])


def test_git_diff_shows_changes(tmp_path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("hello there\n", encoding="utf-8")
    result = git_ops.git_diff(str(tmp_path))
    assert result["result"]["filesChanged"] == 1
    assert "hello there" in result["text"]


def test_git_diff_staged(tmp_path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("staged change\n", encoding="utf-8")
    _git(tmp_path, "add", "a.txt")
    result = git_ops.git_diff(str(tmp_path), staged=True)
    assert result["result"]["staged"] is True
    assert "staged change" in result["text"]


def test_git_status_not_a_repo(tmp_path) -> None:
    with pytest.raises(SafeCapabilityError) as exc:
        git_ops.git_status(str(tmp_path))
    assert exc.value.code == "NOT_A_REPO"


def test_git_commit_creates_commit(tmp_path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "b.txt").write_text("new file\n", encoding="utf-8")
    result = git_ops.git_commit(str(tmp_path), message="add b", add_all=True)
    assert result["result"]["kind"] == "git_commit"
    assert result["result"]["pushed"] is False
    log = subprocess.run(["git", "-C", str(tmp_path), "log", "--oneline"], capture_output=True, text=True).stdout
    assert "add b" in log


def test_git_commit_requires_message(tmp_path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "b.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises(SafeCapabilityError) as exc:
        git_ops.git_commit(str(tmp_path), message="  ")
    assert exc.value.code == "INVALID_ARGUMENT"


def test_git_commit_nothing_to_commit(tmp_path) -> None:
    _init_repo(tmp_path)
    with pytest.raises(SafeCapabilityError) as exc:
        git_ops.git_commit(str(tmp_path), message="noop")
    assert exc.value.code == "NOTHING_TO_COMMIT"


def test_git_branch_creates_and_checks_out(tmp_path) -> None:
    _init_repo(tmp_path)
    result = git_ops.git_branch(str(tmp_path), name="feature/login", checkout=True)
    assert result["result"]["branch"] == "feature/login"
    current = subprocess.run(["git", "-C", str(tmp_path), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
    assert current == "feature/login"


def test_git_branch_rejects_invalid_name(tmp_path) -> None:
    _init_repo(tmp_path)
    with pytest.raises(SafeCapabilityError) as exc:
        git_ops.git_branch(str(tmp_path), name="bad name with spaces")
    assert exc.value.code == "INVALID_ARGUMENT"
