from __future__ import annotations

from pathlib import Path

from core.workspace_contract import ensure_workspace_contract


def test_ensure_workspace_contract_creates_plain_text_files(tmp_path: Path):
    out = ensure_workspace_contract(
        tmp_path / "job1",
        role="job:file_operations",
        allowed_tools=["write_file", "read_file"],
        metadata={"user_id": "u1"},
    )
    assert set(out.keys()) == {"AGENTS.txt", "SOUL.txt", "TOOLS.txt", "MEMORY.txt"}
    for p in out.values():
        assert Path(p).exists()


def test_ensure_workspace_contract_is_idempotent(tmp_path: Path):
    first = ensure_workspace_contract(tmp_path / "job2", role="job:code_project")
    second = ensure_workspace_contract(tmp_path / "job2", role="job:code_project")
    assert first == second
