"""Unit tests for terminal safety checks."""

from tools.terminal_tools import SafeTerminal


def test_blocks_python_inline_execution_flag():
    terminal = SafeTerminal()
    result = terminal.analyze_safety("python -c 'print(1)'")
    assert result["safe"] is False
    assert "Inline execution flag blocked" in result["reason"]


def test_blocks_shell_control_operator():
    terminal = SafeTerminal()
    result = terminal.analyze_safety("ls; whoami")
    assert result["safe"] is False
    assert "Shell control operator detected" == result["reason"]


def test_allows_basic_whitelisted_read_command():
    terminal = SafeTerminal()
    result = terminal.analyze_safety("ls -la")
    assert result["safe"] is True
