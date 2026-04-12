from __future__ import annotations

from types import SimpleNamespace

from cli.commands import cron


class _FakeEngine:
    def __init__(self):
        self.added = []
        self.enabled = []
        self.disabled = []
        self.removed = []
        self.run_calls = []
        self.running = True

    def list_jobs(self):
        return [{"id": "job1", "expression": "0 9 * * *", "enabled": True, "prompt": "Sabah özeti"}]

    def add_job(self, payload):
        self.added.append(payload)
        return "job_new"

    def enable_job(self, job_id):
        self.enabled.append(job_id)
        return True

    def disable_job(self, job_id):
        self.disabled.append(job_id)
        return True

    def remove_job(self, job_id):
        self.removed.append(job_id)
        return True

    def get_history(self, job_id=None):
        return [{"time": "2026-04-12 09:00", "status": "ok", "message": "done"}]

    async def run_job(self, job_id):
        self.run_calls.append(job_id)
        return {"success": True, "job_id": job_id}


def test_cron_add_uses_engine_payload_shape(monkeypatch, capsys):
    engine = _FakeEngine()
    monkeypatch.setattr(cron, "_get_engine", lambda: engine)

    cron.run(SimpleNamespace(subcommand="add", expression="0 9 * * *", prompt="Sabah özeti", channel=None, user_id="admin"))
    out = capsys.readouterr().out

    assert "job_new" in out
    assert engine.added[0]["expression"] == "0 9 * * *"
    assert engine.added[0]["prompt"] == "Sabah özeti"
    assert engine.added[0]["job_type"] == "prompt"


def test_cron_run_now_awaits_async_engine(monkeypatch, capsys):
    engine = _FakeEngine()
    monkeypatch.setattr(cron, "_get_engine", lambda: engine)

    cron.run(SimpleNamespace(subcommand="run", job_id="job1"))
    out = capsys.readouterr().out

    assert "Tamamlandı" in out
    assert engine.run_calls == ["job1"]


def test_cron_toggle_uses_engine(monkeypatch, capsys):
    engine = _FakeEngine()
    monkeypatch.setattr(cron, "_get_engine", lambda: engine)

    cron.run(SimpleNamespace(subcommand="disable", job_id="job1"))
    cron.run(SimpleNamespace(subcommand="enable", job_id="job1"))

    out = capsys.readouterr().out
    assert "job1" in out
    assert engine.disabled == ["job1"]
    assert engine.enabled == ["job1"]
