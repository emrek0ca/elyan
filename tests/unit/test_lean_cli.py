from __future__ import annotations

from cli.commands.lean import _print


def test_lean_json_failure_returns_nonzero(capsys):
    exit_code = _print({"success": False, "status": "failed", "error": "boom"}, as_json=True)

    captured = capsys.readouterr()
    assert '"success": false' in captured.out
    assert exit_code == 1
