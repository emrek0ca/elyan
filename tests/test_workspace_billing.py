from __future__ import annotations

import pytest

import core.billing.workspace_billing as workspace_billing_module
from core.billing.workspace_billing import get_workspace_billing_store


@pytest.fixture(autouse=True)
def isolated_workspace_billing(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_DATA_DIR", str(tmp_path / "elyan"))
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    workspace_billing_module._workspace_billing_store = None
    yield
    workspace_billing_module._workspace_billing_store = None


def test_workspace_billing_defaults_and_usage_persist():
    store = get_workspace_billing_store()

    summary = store.get_workspace_summary("workspace-team")
    assert summary["workspace_id"] == "workspace-team"
    assert summary["plan"]["id"] == "free"
    assert summary["entitlements"]["max_connectors"] == 2

    store.record_usage("workspace-team", "connectors", 1, metadata={"connector": "github"})
    store.record_usage("workspace-team", "artifact_exports", 3, metadata={"kind": "document"})
    usage = store.get_usage("workspace-team")

    assert usage["totals"]["connectors"] == 1
    assert usage["totals"]["artifact_exports"] == 3

    blocked = store.enforce_limit("workspace-team", metric="max_connectors", current_value=2)
    assert blocked["allowed"] is False
    assert blocked["reason"] == "max_connectors_limit_reached"


def test_workspace_billing_checkout_requires_stripe_configuration():
    store = get_workspace_billing_store()

    with pytest.raises(RuntimeError, match="stripe_not_configured"):
        store.create_checkout_session(
            workspace_id="workspace-team",
            plan_id="pro",
            success_url="https://tauri.localhost/billing/success",
            cancel_url="https://tauri.localhost/billing/cancel",
        )
