from __future__ import annotations

import json
import sys
from pathlib import Path

from core.compliance import audit_engine as compliance_audit_engine
from core.compliance import audit_trail as compliance_audit_trail
from core.gateway import server as gateway_server
from core.llm import token_budget as llm_token_budget
from core.memory import episodic as memory_episodic
from core.reporting import engine as reporting_engine
from core.runtime import benchmarks as runtime_benchmarks
from core.runtime import emre_workflows as runtime_emre_workflows
from core.runtime import scenarios as runtime_scenarios
from core.runtime import task_sessions as runtime_task_sessions
from core.runtime.hosts import desktop_host as runtime_desktop_host
from core.scheduler import cron_engine as scheduler_cron_engine
from core.scheduler import routine_engine as scheduler_routine_engine


def test_runtime_default_roots_use_resolved_data_dir(monkeypatch, tmp_path: Path):
    data_root = (tmp_path / "elyan_data").resolve()
    monkeypatch.setattr(runtime_benchmarks, "resolve_elyan_data_dir", lambda: data_root)
    monkeypatch.setattr(runtime_task_sessions, "resolve_elyan_data_dir", lambda: data_root)
    monkeypatch.setattr(runtime_scenarios, "resolve_elyan_data_dir", lambda: data_root)
    monkeypatch.setattr(runtime_desktop_host, "resolve_elyan_data_dir", lambda: data_root)

    assert runtime_benchmarks._default_reports_root() == data_root / "runtime_benchmarks"
    assert runtime_task_sessions._default_tasks_root() == data_root / "operator_tasks"
    assert runtime_desktop_host._default_state_path() == data_root / "desktop_host" / "state.json"

    scenario_root = runtime_scenarios._scenario_root("resolver-root-check")
    expected_scenario_base = (data_root / "operator_scenarios").resolve()
    assert scenario_root.exists()
    assert str(scenario_root.resolve()).startswith(str(expected_scenario_base))


def test_emre_workflows_loads_default_benchmark_root_from_resolver(monkeypatch, tmp_path: Path):
    data_root = (tmp_path / "elyan_data").resolve()
    benchmark_run = data_root / "runtime_benchmarks" / "123456"
    benchmark_run.mkdir(parents=True, exist_ok=True)
    (benchmark_run / "summary.json").write_text(
        json.dumps(
            {
                "pass_count": 7,
                "total": 7,
                "average_retries": 0.0,
                "average_replans": 0.0,
                "failure_reasons": {},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(runtime_emre_workflows, "resolve_elyan_data_dir", lambda: data_root)
    monkeypatch.setattr(runtime_emre_workflows, "_repo_root", lambda: tmp_path / "repo_root")

    summary = runtime_emre_workflows.load_latest_benchmark_summary()
    assert summary["pass_count"] == 7
    assert summary["total"] == 7
    assert Path(str(summary["report_root"])).resolve() == benchmark_run.resolve()


def test_non_runtime_storage_defaults_use_resolved_data_dir(monkeypatch, tmp_path: Path):
    data_root = (tmp_path / "elyan_data").resolve()
    core_memory_legacy = sys.modules.get("core._memory_legacy")
    assert core_memory_legacy is not None

    monkeypatch.setattr(reporting_engine, "resolve_elyan_data_dir", lambda: data_root)
    monkeypatch.setattr(core_memory_legacy, "resolve_elyan_data_dir", lambda: data_root)
    monkeypatch.setattr(memory_episodic, "resolve_elyan_data_dir", lambda: data_root)
    monkeypatch.setattr(compliance_audit_trail, "resolve_elyan_data_dir", lambda: data_root)
    monkeypatch.setattr(compliance_audit_engine, "resolve_elyan_data_dir", lambda: data_root)
    monkeypatch.setattr(llm_token_budget, "resolve_elyan_data_dir", lambda: data_root)
    monkeypatch.setattr(scheduler_routine_engine, "resolve_elyan_data_dir", lambda: data_root)
    monkeypatch.setattr(scheduler_cron_engine, "resolve_elyan_data_dir", lambda: data_root)
    monkeypatch.setattr(gateway_server, "resolve_elyan_data_dir", lambda: data_root)

    assert reporting_engine._default_report_dir() == data_root / "reports"
    assert core_memory_legacy._default_memory_dir() == data_root / "memory"
    assert core_memory_legacy._default_elyan_config_path() == data_root / "elyan.json"
    assert memory_episodic._default_episodic_db_path() == data_root / "memory" / "episodic.db"
    assert compliance_audit_trail._default_audit_db_path() == data_root / "compliance" / "audit.db"
    assert compliance_audit_engine._default_audit_dir() == data_root / "audit"
    assert llm_token_budget._default_usage_db_path() == data_root / "compliance" / "usage.db"
    assert scheduler_routine_engine._default_routine_persist_path() == data_root / "routines.json"
    assert scheduler_routine_engine._default_routine_report_dir() == data_root / "reports" / "routines"
    assert scheduler_cron_engine._default_cron_persist_path() == data_root / "cron_jobs.json"

    read_probe = gateway_server.ElyanGatewayServer._tool_probe_params("read_file")
    assert isinstance(read_probe, dict)
    assert Path(str(read_probe["path"])).resolve().parent == (data_root / "tmp").resolve()
