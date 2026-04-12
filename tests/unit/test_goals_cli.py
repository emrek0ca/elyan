from __future__ import annotations

import json
from types import SimpleNamespace

from cli.commands import goals


def test_goals_json_output_contains_automation_candidate(capsys):
    args = SimpleNamespace(
        action="analyze",
        text=["Her", "gün", "09:00", "satış", "raporunu", "özetle"],
        json=True,
    )
    goals.run(args)
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is True
    candidate = payload["goal_graph"]["automation_candidate"]
    assert candidate["cron"] == "0 9 * * *"
    assert "satış raporunu özetle" in candidate["task"]


def test_goals_text_output_prints_stage_summary(capsys):
    args = SimpleNamespace(
        action="analyze",
        text=["ERP'den", "satışları", "çek", "ve", "sonra", "PDF", "üret", "ardından", "mail", "at"],
        json=False,
    )
    goals.run(args)
    out = capsys.readouterr().out

    assert "Goal Analysis" in out
    assert "Aşamalar" in out
    assert "objective:" in out
