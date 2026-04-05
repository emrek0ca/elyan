from __future__ import annotations

import core.billing.reconciliation_bridge as bridge_module
from core.billing.reconciliation_bridge import activate_billing_usage_scope
from core.pricing_tracker import PricingTracker


def test_billing_reconciliation_bridge_applies_scoped_pricing_usage(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_FF_BILLING_RECONCILIATION_BRIDGE_SHADOW", "1")
    monkeypatch.setenv("ELYAN_FF_BILLING_RECONCILIATION_BRIDGE_APPLY", "1")
    calls: list[dict[str, object]] = []

    class _FakeStore:
        def reconcile_usage(self, workspace_id: str, *, usage_id: str, actual_credits: int, metadata: dict | None = None):
            payload = {
                "workspace_id": workspace_id,
                "usage_id": usage_id,
                "actual_credits": actual_credits,
                "metadata": dict(metadata or {}),
            }
            calls.append(payload)
            return {"status": "applied", "delta_credits": -2}

    monkeypatch.setattr(bridge_module, "_workspace_billing_store", lambda: _FakeStore())
    tracker = PricingTracker(db_path=tmp_path / "pricing.json")

    with activate_billing_usage_scope(
        workspace_id="workspace-a",
        usage_id="usage_bridge_1",
        metric="workflow_runs",
        run_id="run_bridge_1",
        session_id="desktop",
        metadata={"actor_id": "owner-1"},
    ):
        tracker.record_usage(
            provider="openai",
            model="gpt-4o",
            prompt_tokens=1200,
            completion_tokens=800,
            user_id="owner-1",
        )

    assert len(calls) == 1
    assert calls[0]["workspace_id"] == "workspace-a"
    assert calls[0]["usage_id"] == "usage_bridge_1"
    assert int(calls[0]["actual_credits"]) >= 2
    assert calls[0]["metadata"]["source"] == "pricing_tracker_scope"
    assert calls[0]["metadata"]["total_tokens"] == 2000
    assert calls[0]["metadata"]["providers"] == ["openai"]
    assert calls[0]["metadata"]["models"] == ["gpt-4o"]


def test_billing_reconciliation_bridge_respects_apply_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_FF_BILLING_RECONCILIATION_BRIDGE_SHADOW", "1")
    monkeypatch.setenv("ELYAN_FF_BILLING_RECONCILIATION_BRIDGE_APPLY", "0")
    calls: list[dict[str, object]] = []

    class _FakeStore:
        def reconcile_usage(self, workspace_id: str, *, usage_id: str, actual_credits: int, metadata: dict | None = None):
            calls.append(
                {
                    "workspace_id": workspace_id,
                    "usage_id": usage_id,
                    "actual_credits": actual_credits,
                    "metadata": dict(metadata or {}),
                }
            )
            return {"status": "applied"}

    monkeypatch.setattr(bridge_module, "_workspace_billing_store", lambda: _FakeStore())
    tracker = PricingTracker(db_path=tmp_path / "pricing-no-apply.json")

    with activate_billing_usage_scope(
        workspace_id="workspace-a",
        usage_id="usage_bridge_2",
        metric="cowork_turns",
    ):
        tracker.record_usage(
            provider="groq",
            model="llama-3.3-70b-versatile",
            prompt_tokens=600,
            completion_tokens=300,
            user_id="owner-1",
        )

    assert calls == []
