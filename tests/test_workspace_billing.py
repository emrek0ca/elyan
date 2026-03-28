from __future__ import annotations

import json
import sys
from types import SimpleNamespace

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


def test_workspace_billing_checkout_requires_price_id(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    store = get_workspace_billing_store()

    class _FakeStripe:
        class checkout:
            class Session:
                @staticmethod
                def create(**_kwargs):
                    return SimpleNamespace(id="cs_test", url="https://billing.local/checkout")

    monkeypatch.setattr(store, "_stripe_client", lambda: _FakeStripe())

    with pytest.raises(RuntimeError, match="stripe_price_missing"):
        store.create_checkout_session(
            workspace_id="workspace-team",
            plan_id="pro",
            success_url="https://tauri.localhost/billing/success",
            cancel_url="https://tauri.localhost/billing/cancel",
        )


def test_workspace_billing_past_due_degrades_entitlements(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_123")

    class _FakeWebhook:
        @staticmethod
        def construct_event(*, payload, sig_header, secret):
            assert sig_header == "sig_test"
            assert secret == "whsec_test_123"
            return json.loads(payload.decode("utf-8"))

    monkeypatch.setitem(sys.modules, "stripe", SimpleNamespace(Webhook=_FakeWebhook()))

    store = get_workspace_billing_store()
    payload = {
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "metadata": {
                    "workspace_id": "workspace-team",
                    "plan_id": "team",
                },
                "customer": "cus_team",
            }
        },
    }

    result = store.handle_webhook(json.dumps(payload).encode("utf-8"), "sig_test")
    entitlements = store.get_entitlements("workspace-team")

    assert result["status"] == "past_due"
    assert result["effective_plan_id"] == "free"
    assert entitlements["plan_id"] == "free"
    assert entitlements["degraded"] is True
    assert entitlements["degraded_reason"] == "subscription_past_due"
