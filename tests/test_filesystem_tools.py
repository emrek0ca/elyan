from __future__ import annotations

import os
from pathlib import Path

import pytest

from actions import filesystem
from runtime.capability_registry import SafeCapabilityError


def _seed_project(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("import os\n\ndef handler():\n    return 'needle-value'\n", encoding="utf-8")
    (root / "src" / "util.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (root / "README.md").write_text("# Title\nneedle-value in docs\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "junk.js").write_text("needle-value should be ignored\n", encoding="utf-8")


def test_file_read_returns_numbered_lines(tmp_path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    result = filesystem.file_read(str(target))
    assert result["result"]["kind"] == "file_read"
    assert result["result"]["totalLines"] == 3
    assert "1\talpha" in result["text"]
    assert "3\tgamma" in result["text"]


def test_file_read_line_range(tmp_path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("l1\nl2\nl3\nl4\nl5\n", encoding="utf-8")
    result = filesystem.file_read(str(target), start_line=2, end_line=4)
    assert result["result"]["returnedLines"] == 3
    assert "2\tl2" in result["text"]
    assert "4\tl4" in result["text"]
    assert "l1" not in result["text"]
    assert "l5" not in result["text"]


def test_file_read_rejects_binary(tmp_path) -> None:
    target = tmp_path / "blob.bin"
    target.write_bytes(b"\x00\x01\x02\x03binarypayload\x00")
    with pytest.raises(SafeCapabilityError) as exc:
        filesystem.file_read(str(target))
    assert exc.value.code == "UNSUPPORTED_FORMAT"


def test_file_read_blocks_sensitive_path(tmp_path) -> None:
    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    key = ssh / "id_rsa"
    key.write_text("PRIVATE KEY", encoding="utf-8")
    with pytest.raises(SafeCapabilityError) as exc:
        filesystem.file_read(str(key))
    assert exc.value.code == "ACCESS_DENIED"


def test_file_read_missing_file(tmp_path) -> None:
    with pytest.raises(SafeCapabilityError) as exc:
        filesystem.file_read(str(tmp_path / "nope.txt"))
    assert exc.value.code == "FILE_NOT_FOUND"


def test_file_search_finds_matches_and_skips_ignored(tmp_path, monkeypatch) -> None:
    _seed_project(tmp_path)
    # ripgrep'i devre dışı bırak → saf Python yolunu deterministik test et.
    monkeypatch.setattr(filesystem.shutil, "which", lambda name: None)
    result = filesystem.file_search("needle-value", path=str(tmp_path))
    assert result["result"]["engine"] == "python"
    paths = {Path(m["path"]).name for m in result["result"]["matches"]}
    assert "app.py" in paths
    assert "README.md" in paths
    # node_modules atlanmalı.
    assert "junk.js" not in paths


def test_file_search_regex(tmp_path, monkeypatch) -> None:
    _seed_project(tmp_path)
    monkeypatch.setattr(filesystem.shutil, "which", lambda name: None)
    result = filesystem.file_search(r"def \w+\(", path=str(tmp_path), regex=True)
    assert result["result"]["matchCount"] >= 2


def test_file_search_requires_query(tmp_path) -> None:
    with pytest.raises(SafeCapabilityError) as exc:
        filesystem.file_search("  ", path=str(tmp_path))
    assert exc.value.code == "INVALID_ARGUMENT"


def test_directory_tree_skips_noise_and_caps(tmp_path) -> None:
    _seed_project(tmp_path)
    result = filesystem.directory_tree(str(tmp_path), max_depth=3, max_entries=100)
    text = result["text"]
    assert "src/" in text
    assert "app.py" in text
    assert "node_modules" not in text  # gürültü klasörü atlanır
    assert result["result"]["kind"] == "directory_tree"


def test_directory_tree_rejects_file_path(tmp_path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(SafeCapabilityError) as exc:
        filesystem.directory_tree(str(target))
    assert exc.value.code == "INVALID_ARGUMENT"
