"""Unit tests for top-level CLI parsing UX."""

from cli import main as cli_main


def test_main_suggests_closest_command_for_typo(capsys):
    code = cli_main.main(["gatewat", "logs"])
    captured = capsys.readouterr()
    assert code == 2
    assert "Şunu mu demek istediniz: 'gateway'" in captured.err


def test_main_version_command(capsys):
    code = cli_main.main(["version"])
    captured = capsys.readouterr()
    assert code == 0
    assert "Elyan CLI v18.0.0" in captured.out
