"""
Integration tests for Cognitive Layer CLI Commands

Tests the Phase 5 CLI interface:
- elyan cognitive (status)
- elyan cognitive diagnostics
- elyan cognitive mode [set MODE]
- elyan cognitive insights [task_id]
- elyan cognitive schedule-sleep [HH:MM]
"""

import pytest
import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestCognitiveCLIBasic:
    """Test basic cognitive CLI functionality"""

    def test_cognitive_command_exists(self):
        """Verify cognitive command is registered"""
        from cli import main
        assert "cognitive" in main.TOP_LEVEL_COMMANDS

    def test_cognitive_command_help(self, capsys):
        """Test cognitive command help output"""
        sys.argv = ["elyan", "cognitive", "--help"]

        with pytest.raises(SystemExit):
            # argparse calls sys.exit() when --help is used
            from cli.main import main as cli_main
            cli_main()

        captured = capsys.readouterr()
        assert "cognitive" in captured.out or "cognitive" in captured.err

    def test_cognitive_status_output(self, capsys):
        """Test cognitive status command output"""
        from cli.commands import cognitive
        from argparse import Namespace

        args = Namespace(
            subcommand=None,
            deep=False,
            json=False
        )

        cognitive.run(args)
        captured = capsys.readouterr()

        assert "COGNITIVE LAYER STATUS" in captured.out
        assert "Mode:" in captured.out
        assert "Components:" in captured.out

    def test_cognitive_status_json_output(self, capsys):
        """Test cognitive status with JSON output"""
        from cli.commands import cognitive
        from argparse import Namespace

        args = Namespace(
            subcommand=None,
            deep=False,
            json=True
        )

        cognitive.run(args)
        captured = capsys.readouterr()

        # Should be valid JSON
        data = json.loads(captured.out)
        assert "enabled" in data
        assert "mode" in data
        assert "components" in data

    def test_cognitive_diagnostics_command(self, capsys):
        """Test cognitive diagnostics command"""
        from cli.commands import cognitive
        from argparse import Namespace

        args = Namespace(
            subcommand="diagnostics",
            deep=False,
            json=False
        )

        cognitive.run(args)
        captured = capsys.readouterr()

        assert "COGNITIVE LAYER STATUS" in captured.out

    def test_cognitive_diagnostics_deep(self, capsys):
        """Test cognitive diagnostics with deep flag"""
        from cli.commands import cognitive
        from argparse import Namespace

        args = Namespace(
            subcommand="diagnostics",
            deep=True,
            json=False
        )

        cognitive.run(args)
        captured = capsys.readouterr()

        assert "COGNITIVE LAYER STATUS" in captured.out

    def test_cognitive_mode_view(self, capsys):
        """Test viewing current execution mode"""
        from cli.commands import cognitive
        from argparse import Namespace

        args = Namespace(
            subcommand="mode",
            set_mode=None,
            json=False
        )

        cognitive.run(args)
        captured = capsys.readouterr()

        assert "execution mode:" in captured.out.lower()

    def test_cognitive_mode_json(self, capsys):
        """Test mode command with JSON output"""
        from cli.commands import cognitive
        from argparse import Namespace

        args = Namespace(
            subcommand="mode",
            set_mode=None,
            json=True
        )

        cognitive.run(args)
        captured = capsys.readouterr()

        data = json.loads(captured.out)
        assert "mode" in data


class TestCognitiveCLIInsights:
    """Test cognitive insights command"""

    def test_insights_no_task_id_error(self, capsys):
        """Test insights command without task_id"""
        from cli.commands import cognitive
        from argparse import Namespace

        args = Namespace(
            subcommand="insights",
            task_id=None,
            json=False
        )

        cognitive.run(args)
        captured = capsys.readouterr()

        assert "Error" in captured.out or "required" in captured.out.lower()

    def test_insights_task_not_found(self, capsys):
        """Test insights for non-existent task"""
        from cli.commands import cognitive
        from argparse import Namespace

        args = Namespace(
            subcommand="insights",
            task_id="nonexistent_task_xyz",
            json=False
        )

        cognitive.run(args)
        captured = capsys.readouterr()

        assert "not found" in captured.out.lower() or "No cognitive trace" in captured.out


class TestCognitiveCLIScheduleSleep:
    """Test cognitive schedule-sleep command"""

    def test_schedule_sleep_no_time_error(self, capsys):
        """Test schedule-sleep without time parameter"""
        from cli.commands import cognitive
        from argparse import Namespace

        args = Namespace(
            subcommand="schedule-sleep",
            time=None
        )

        cognitive.run(args)
        captured = capsys.readouterr()

        assert "Error" in captured.out or "required" in captured.out.lower()

    def test_schedule_sleep_invalid_format(self, capsys):
        """Test schedule-sleep with invalid time format"""
        from cli.commands import cognitive
        from argparse import Namespace

        args = Namespace(
            subcommand="schedule-sleep",
            time="25:00"  # Invalid hour
        )

        cognitive.run(args)
        captured = capsys.readouterr()

        assert "Error" in captured.out or "Invalid" in captured.out

    def test_schedule_sleep_valid(self, capsys):
        """Test schedule-sleep with valid time"""
        from cli.commands import cognitive
        from argparse import Namespace

        args = Namespace(
            subcommand="schedule-sleep",
            time="02:00"
        )

        with patch('config.settings_manager.SettingsPanel') as mock_settings:
            mock_instance = MagicMock()
            mock_instance._settings = {}
            mock_instance.save = MagicMock()
            mock_settings.return_value = mock_instance

            cognitive.run(args)
            captured = capsys.readouterr()

            assert "scheduled" in captured.out.lower() or "02:00" in captured.out


class TestCognitiveCLIHelpers:
    """Test CLI helper functions"""

    def test_read_cognitive_config(self):
        """Test reading cognitive configuration"""
        from cli.commands import cognitive

        config = cognitive._read_cognitive_config()

        assert isinstance(config, dict)
        assert "enabled" in config
        assert "budgets" in config

    def test_get_cognitive_state(self):
        """Test getting cognitive state"""
        from cli.commands import cognitive

        state = cognitive._get_cognitive_state()

        assert isinstance(state, dict)
        assert "current_mode" in state
        assert "daily_errors" in state

    def test_calculate_success_rate(self):
        """Test success rate calculation"""
        from cli.commands import cognitive

        rate = cognitive._calculate_success_rate()

        assert isinstance(rate, float)
        assert 0.0 <= rate <= 100.0

    def test_get_recent_deadlocks(self):
        """Test getting recent deadlocks"""
        from cli.commands import cognitive

        deadlocks = cognitive._get_recent_deadlocks()

        assert isinstance(deadlocks, list)
        # Should be empty initially
        assert len(deadlocks) == 0

    def test_get_mode_switches(self):
        """Test getting mode switches"""
        from cli.commands import cognitive

        switches = cognitive._get_mode_switches()

        assert isinstance(switches, list)
        # Should be empty initially
        assert len(switches) == 0


class TestCognitiveCLIDisplay:
    """Test display functions"""

    def test_display_cognitive_status_disabled(self, capsys):
        """Test displaying status when cognitive is disabled"""
        from cli.commands import cognitive

        payload = {"enabled": False}
        cognitive._display_cognitive_status(payload)

        captured = capsys.readouterr()
        assert "DISABLED" in captured.out or "DISABLED" in captured.out.lower()

    def test_display_cognitive_status_enabled(self, capsys):
        """Test displaying status when cognitive is enabled"""
        from cli.commands import cognitive

        payload = {
            "enabled": True,
            "mode": "FOCUSED",
            "success_rate_pct": 85.5,
            "components": {
                "ceo": True,
                "deadlock": True,
                "time_boxing": True,
                "sleep": False,
            },
            "budgets": {
                "simple_query": 10,
                "file_operation": 30,
                "api_call": 20,
                "complex_analysis": 300,
            },
            "state": {
                "daily_errors": 5,
                "daily_patterns": 3,
                "q_table_entries": 42,
            },
        }

        cognitive._display_cognitive_status(payload)
        captured = capsys.readouterr()

        assert "ENABLED" in captured.out
        assert "FOCUSED" in captured.out
        assert "85.5" in captured.out


class TestCognitiveCLIIntegration:
    """Integration tests for entire CLI flow"""

    def test_cognitive_full_workflow(self, capsys):
        """Test complete cognitive CLI workflow"""
        from cli.commands import cognitive
        from argparse import Namespace

        # Test status
        args = Namespace(subcommand=None, deep=False, json=False)
        cognitive.run(args)
        captured = capsys.readouterr()
        assert "COGNITIVE LAYER STATUS" in captured.out

        # Test JSON output
        args = Namespace(subcommand=None, deep=False, json=True)
        cognitive.run(args)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["enabled"] is not None

    def test_cognitive_backward_compatibility(self):
        """Verify cognitive CLI doesn't break existing commands"""
        from cli import main

        # Verify cognitive is added to command list
        assert "cognitive" in main.TOP_LEVEL_COMMANDS

        # Verify other commands still exist
        assert "status" in main.TOP_LEVEL_COMMANDS
        assert "config" in main.TOP_LEVEL_COMMANDS
        assert "gateway" in main.TOP_LEVEL_COMMANDS


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
