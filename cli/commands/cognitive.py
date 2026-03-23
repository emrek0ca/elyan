"""
Cognitive Layer CLI Commands - Phase 4 Integration

Exposes cognitive layer status and controls:
- status --cognitive: Show cognitive state and metrics
- insights [task_id]: Show cognitive trace for specific task
- diagnostics: Deep cognitive diagnostics
- mode [set FOCUSED|DIFFUSE]: View/change execution mode
- schedule-sleep [time HH:MM]: Schedule sleep consolidation
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def _read_cognitive_config() -> dict[str, Any]:
    """Read cognitive settings from config"""
    try:
        from config.settings_manager import SettingsPanel
        settings = SettingsPanel()
        return {
            "enabled": settings.get("cognitive_layer_enabled", True),
            "ceo_enabled": settings.get("ceo_simulation_enabled", True),
            "deadlock_enabled": settings.get("deadlock_detection_enabled", True),
            "mode_default": settings.get("execution_mode_default", "FOCUSED"),
            "sleep_enabled": settings.get("sleep_consolidation_enabled", False),
            "time_boxing_enabled": settings.get("time_boxed_scheduler_enabled", True),
            "budgets": {
                "simple_query": settings.get("simple_query_budget_seconds", 10),
                "file_operation": settings.get("file_operation_budget_seconds", 30),
                "api_call": settings.get("api_call_budget_seconds", 20),
                "complex_analysis": settings.get("complex_analysis_budget_seconds", 300),
            },
            "pomodoro": {
                "focus": settings.get("pomodoro_focus_duration_seconds", 300),
                "break": settings.get("pomodoro_break_duration_seconds", 5),
            }
        }
    except Exception as e:
        logger.error(f"Failed to read cognitive config: {e}")
        return {}


def _get_cognitive_state() -> dict[str, Any]:
    """Get current cognitive state from integrator"""
    try:
        from core.cognitive_layer_integrator import get_cognitive_integrator
        integrator = get_cognitive_integrator()

        return {
            "current_mode": str(integrator.state_machine.current_mode),
            "daily_errors": len(integrator.daily_errors),
            "daily_patterns": len(integrator.daily_patterns),
            "q_table_entries": len(integrator.execution_q_table),
        }
    except Exception as e:
        logger.error(f"Failed to get cognitive state: {e}")
        return {
            "current_mode": "UNKNOWN",
            "daily_errors": 0,
            "daily_patterns": 0,
            "q_table_entries": 0,
        }


def _read_cognitive_traces(limit: int = 10) -> list[dict[str, Any]]:
    """Read recent cognitive traces from log"""
    traces = []
    try:
        log_path = Path.home() / ".elyan" / "logs" / "cognitive_trace.log"
        if not log_path.exists():
            return traces

        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        # Parse JSON lines (JSONL format)
        for line in lines[-limit:]:
            if not line.strip():
                continue
            try:
                # Extract JSON from log line (format: "timestamp | logger | level | COGNITIVE_TRACE: {...}")
                if "COGNITIVE_TRACE:" in line:
                    json_start = line.index("{")
                    json_str = line[json_start:]
                    trace = json.loads(json_str)
                    traces.append(trace)
            except Exception:
                pass

        return traces
    except Exception as e:
        logger.error(f"Failed to read cognitive traces: {e}")
        return []


def _calculate_success_rate() -> float:
    """Calculate recent task success rate"""
    try:
        traces = _read_cognitive_traces(limit=20)
        if not traces:
            return 0.0

        successes = sum(1 for t in traces if t.get("execution_success"))
        return round((successes / len(traces)) * 100, 1) if traces else 0.0
    except Exception:
        return 0.0


def _get_recent_deadlocks() -> list[dict[str, Any]]:
    """Get recent deadlock detections"""
    deadlocks = []
    try:
        traces = _read_cognitive_traces(limit=50)
        for trace in traces:
            if trace.get("deadlock_detected"):
                deadlocks.append({
                    "task_id": trace.get("task_id"),
                    "action": trace.get("action"),
                    "recovery": trace.get("deadlock_recovery_action"),
                    "timestamp": trace.get("timestamp"),
                })
        return deadlocks[:10]  # Last 10 deadlocks
    except Exception:
        return []


def _get_mode_switches() -> list[dict[str, Any]]:
    """Get recent mode switches"""
    switches = []
    try:
        traces = _read_cognitive_traces(limit=50)
        for trace in traces:
            if trace.get("mode_switched"):
                switches.append({
                    "task_id": trace.get("task_id"),
                    "from": trace.get("mode_before"),
                    "to": trace.get("mode_after"),
                    "reason": trace.get("mode_switch_reason"),
                    "timestamp": trace.get("timestamp"),
                })
        return switches[:10]  # Last 10 switches
    except Exception:
        return []


def _build_cognitive_status(deep: bool = False) -> dict[str, Any]:
    """Build comprehensive cognitive status"""
    config = _read_cognitive_config()
    state = _get_cognitive_state()
    success_rate = _calculate_success_rate()

    payload: dict[str, Any] = {
        "enabled": config.get("enabled", False),
        "mode": state.get("current_mode", "UNKNOWN"),
        "success_rate_pct": success_rate,
        "components": {
            "ceo": config.get("ceo_enabled", False),
            "deadlock": config.get("deadlock_enabled", False),
            "time_boxing": config.get("time_boxing_enabled", False),
            "sleep": config.get("sleep_enabled", False),
        },
        "budgets": config.get("budgets", {}),
        "state": {
            "daily_errors": state.get("daily_errors", 0),
            "daily_patterns": state.get("daily_patterns", 0),
            "q_table_entries": state.get("q_table_entries", 0),
        },
    }

    if deep:
        deadlocks = _get_recent_deadlocks()
        switches = _get_mode_switches()
        payload["diagnostics"] = {
            "recent_deadlocks": deadlocks,
            "mode_switches": switches,
            "traces": _read_cognitive_traces(limit=5),
        }

    return payload


def _display_cognitive_status(payload: dict[str, Any], deep: bool = False) -> None:
    """Display cognitive status in human-readable format"""
    print("=" * 60)
    print("  COGNITIVE LAYER STATUS")
    print("=" * 60)

    enabled = payload.get("enabled", False)
    if not enabled:
        print("\n  Status: DISABLED")
        print("  Cognitive layer is not active. Enable via settings.")
        print("\n" + "=" * 60)
        return

    print(f"\n  Status:         ENABLED")
    print(f"  Mode:           {payload.get('mode', 'UNKNOWN')}")
    print(f"  Success Rate:   {payload.get('success_rate_pct', 0.0)}%")

    components = payload.get("components", {})
    print(f"\n  Components:")
    print(f"    CEO Planner:        {'ON' if components.get('ceo') else 'OFF'}")
    print(f"    Deadlock Detector:  {'ON' if components.get('deadlock') else 'OFF'}")
    print(f"    Time Scheduler:     {'ON' if components.get('time_boxing') else 'OFF'}")
    print(f"    Sleep Learning:     {'ON' if components.get('sleep') else 'OFF'}")

    budgets = payload.get("budgets", {})
    if budgets:
        print(f"\n  Time Budgets (seconds):")
        print(f"    Simple Query:       {budgets.get('simple_query', '?')}s")
        print(f"    File Operation:     {budgets.get('file_operation', '?')}s")
        print(f"    API Call:           {budgets.get('api_call', '?')}s")
        print(f"    Complex Analysis:   {budgets.get('complex_analysis', '?')}s")

    state = payload.get("state", {})
    print(f"\n  Daily Activity:")
    print(f"    Errors Tracked:     {state.get('daily_errors', 0)}")
    print(f"    Patterns Learned:   {state.get('daily_patterns', 0)}")
    print(f"    Q-Learning Entries: {state.get('q_table_entries', 0)}")

    if deep:
        diagnostics = payload.get("diagnostics", {})

        deadlocks = diagnostics.get("recent_deadlocks", [])
        if deadlocks:
            print(f"\n  Recent Deadlocks ({len(deadlocks)}):")
            for dl in deadlocks[:5]:
                print(f"    • {dl.get('task_id')}: {dl.get('action')} → {dl.get('recovery')}")

        switches = diagnostics.get("mode_switches", [])
        if switches:
            print(f"\n  Mode Switches ({len(switches)}):")
            for sw in switches[:5]:
                print(f"    • {sw.get('task_id')}: {sw.get('from')} → {sw.get('to')}")
                if sw.get('reason'):
                    print(f"      ({sw.get('reason')})")

        traces = diagnostics.get("traces", [])
        if traces:
            print(f"\n  Last Execution Traces ({len(traces)}):")
            for trace in traces[:3]:
                print(f"    • {trace.get('task_id')}: {trace.get('action')}")
                if trace.get('ceo_conflicts_detected'):
                    print(f"      Conflicts: {', '.join(trace.get('ceo_conflicts_detected', []))}")
                if trace.get('execution_error'):
                    print(f"      Error: {trace.get('execution_error')}")

    print("\n" + "=" * 60)


def run(args):
    """Main CLI command handler"""
    subcommand = getattr(args, "subcommand", None)

    if subcommand == "insights":
        # Show cognitive trace for specific task
        task_id = getattr(args, "task_id", None)
        if not task_id:
            print("Error: task_id required for insights command")
            print("Usage: elyan cognitive insights <task_id>")
            return

        traces = _read_cognitive_traces(limit=100)
        matching = [t for t in traces if t.get("task_id") == task_id]

        if not matching:
            print(f"No cognitive trace found for task: {task_id}")
            return

        trace = matching[0]
        if getattr(args, "json", False):
            print(json.dumps(trace, ensure_ascii=False, indent=2))
        else:
            print("=" * 60)
            print(f"  COGNITIVE INSIGHTS - {task_id}")
            print("=" * 60)
            print(f"\n  Action:       {trace.get('action')}")
            print(f"  Timestamp:    {trace.get('timestamp')}")

            print(f"\n  CEO Simulation:")
            ceo = trace.get("ceo_simulation_result", {})
            print(f"    Success:     {ceo.get('success', False)}")
            if ceo.get("conflicts_detected"):
                print(f"    Conflicts:   {', '.join(ceo.get('conflicts_detected', []))}")
            if ceo.get("error_scenarios"):
                print(f"    Errors:      {', '.join(ceo.get('error_scenarios', []))}")

            print(f"\n  Time Budget:")
            print(f"    Assigned:    {trace.get('assigned_budget_seconds')}s ({trace.get('budget_type')})")
            print(f"    Actual:      {trace.get('execution_duration_ms')}ms")

            print(f"\n  Execution:")
            print(f"    Success:     {trace.get('execution_success')}")
            if trace.get("execution_error"):
                print(f"    Error:       {trace.get('execution_error')}")

            print(f"\n  Deadlock:")
            print(f"    Detected:    {trace.get('deadlock_detected', False)}")
            if trace.get("deadlock_recovery_action"):
                print(f"    Recovery:    {trace.get('deadlock_recovery_action')}")

            print(f"\n  Mode:")
            print(f"    Before:      {trace.get('mode_before')}")
            print(f"    After:       {trace.get('mode_after')}")
            if trace.get("mode_switch_reason"):
                print(f"    Reason:      {trace.get('mode_switch_reason')}")

            print("\n" + "=" * 60)

    elif subcommand == "diagnostics":
        # Deep cognitive diagnostics
        payload = _build_cognitive_status(deep=True)

        if getattr(args, "json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _display_cognitive_status(payload, deep=True)

    elif subcommand == "mode":
        # View or change execution mode
        set_mode = getattr(args, "set_mode", None)

        if set_mode:
            # Change mode
            valid_modes = ["FOCUSED", "DIFFUSE"]
            if set_mode.upper() not in valid_modes:
                print(f"Error: Invalid mode '{set_mode}'. Valid options: {', '.join(valid_modes)}")
                return

            try:
                from core.cognitive_layer_integrator import get_cognitive_integrator
                from core.execution_modes import ExecutionMode

                integrator = get_cognitive_integrator()
                integrator.state_machine.current_mode = ExecutionMode[set_mode]
                print(f"✓ Execution mode changed to: {set_mode}")
            except Exception as e:
                print(f"Error changing mode: {e}")
        else:
            # View current mode
            state = _get_cognitive_state()
            mode = state.get("current_mode", "UNKNOWN")

            if getattr(args, "json", False):
                print(json.dumps({"mode": mode}, ensure_ascii=False, indent=2))
            else:
                print(f"Current execution mode: {mode}")

    elif subcommand == "schedule-sleep":
        # Schedule sleep consolidation
        time_str = getattr(args, "time", None)

        if not time_str:
            print("Error: time required for schedule-sleep command")
            print("Usage: elyan cognitive schedule-sleep <HH:MM>")
            return

        try:
            # Validate time format
            parts = time_str.split(":")
            if len(parts) != 2:
                raise ValueError("Invalid time format")
            hour = int(parts[0])
            minute = int(parts[1])
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError("Hour must be 0-23, minute must be 0-59")

            # Update setting
            from config.settings_manager import SettingsPanel
            settings = SettingsPanel()
            settings._settings["sleep_consolidation_enabled"] = True
            settings._settings["sleep_consolidation_time"] = time_str
            settings.save()

            print(f"✓ Sleep consolidation scheduled for {time_str}")
        except ValueError as e:
            print(f"Error: Invalid time format. Use HH:MM (e.g., 02:00)")
        except Exception as e:
            print(f"Error scheduling sleep: {e}")

    else:
        # Default: show cognitive status
        payload = _build_cognitive_status(deep=getattr(args, "deep", False))

        if getattr(args, "json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _display_cognitive_status(payload, deep=getattr(args, "deep", False))
