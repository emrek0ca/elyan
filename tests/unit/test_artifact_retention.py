from __future__ import annotations

import os
import time
from pathlib import Path

from core import artifact_retention


def _touch(path: Path, *, age_days: int = 0, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    ts = time.time() - (age_days * 86400)
    os.utime(path, (ts, ts))
    os.utime(path.parent, (ts, ts))


def test_prune_elyan_artifacts_removes_old_runs_reports_and_jobs(monkeypatch, tmp_path: Path):
    base = tmp_path / ".elyan"
    runs = base / "runs"
    jobs = base / "jobs"
    reports = base / "reports" / "research" / "20250101"
    monkeypatch.setenv("ELYAN_DATA_DIR", str(base))
    monkeypatch.setenv("ELYAN_RUNS_DIR", str(runs))

    old_run = runs / "old-run"
    new_run = runs / "new-run"
    _touch(old_run / "summary.txt", age_days=40)
    _touch(new_run / "summary.txt", age_days=1)
    old_job = jobs / "old-job"
    _touch(old_job / "summary.txt", age_days=25)
    old_report = reports / "report.txt"
    _touch(old_report, age_days=45)

    values = {
        "maintenance.runsRetentionDays": 14,
        "maintenance.reportsRetentionDays": 14,
        "maintenance.jobsRetentionDays": 14,
        "maintenance.keepRecentRuns": 0,
        "maintenance.keepRecentJobs": 0,
    }
    monkeypatch.setattr(artifact_retention.elyan_config, "get", lambda key, default=None: values.get(key, default))

    result = artifact_retention.prune_elyan_artifacts()

    assert result["success"] is True
    assert not old_run.exists()
    assert new_run.exists()
    assert not old_job.exists()
    assert not old_report.exists()
    assert result["removed"] >= 3


def test_maybe_prune_elyan_artifacts_respects_cooldown(monkeypatch, tmp_path: Path):
    base = tmp_path / ".elyan"
    runs = base / "runs"
    monkeypatch.setenv("ELYAN_DATA_DIR", str(base))
    monkeypatch.setenv("ELYAN_RUNS_DIR", str(runs))
    values = {
        "maintenance.artifactRetentionEnabled": True,
        "maintenance.runsRetentionDays": 14,
        "maintenance.reportsRetentionDays": 14,
        "maintenance.jobsRetentionDays": 14,
        "maintenance.keepRecentRuns": 0,
        "maintenance.keepRecentJobs": 0,
    }
    monkeypatch.setattr(artifact_retention.elyan_config, "get", lambda key, default=None: values.get(key, default))

    first = artifact_retention.maybe_prune_elyan_artifacts(min_interval_hours=6)
    second = artifact_retention.maybe_prune_elyan_artifacts(min_interval_hours=6)

    assert first["success"] is True
    assert second["skipped"] is True
    assert second["reason"] == "cooldown"
