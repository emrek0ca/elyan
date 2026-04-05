from __future__ import annotations

import hashlib
import hmac
import json

import pytest

import core.billing.workspace_billing as workspace_billing_module
from core.billing.workspace_billing import get_workspace_billing_store


@pytest.fixture(autouse=True)
def isolated_workspace_billing(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_DATA_DIR", str(tmp_path / "elyan"))
    monkeypatch.delenv("IYZICO_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("IYZICO_PLAN_PRO_CHECKOUT_URL", raising=False)
    monkeypatch.delenv("IYZICO_PLAN_TEAM_CHECKOUT_URL", raising=False)
    monkeypatch.delenv("IYZICO_TOKEN_PACK_STARTER_25K_CHECKOUT_URL", raising=False)
    workspace_billing_module._workspace_billing_store = None
    yield
    workspace_billing_module._workspace_billing_store = None


def test_workspace_billing_defaults_and_usage_persist():
    store = get_workspace_billing_store()

    summary = store.get_workspace_summary("workspace-team")
    assert summary["workspace_id"] == "workspace-team"
    assert summary["plan"]["id"] == "free"
    assert summary["entitlements"]["max_connectors"] == 2
    assert int(summary["credit_balance"]["included"]) > 0

    store.record_usage("workspace-team", "connectors", 1, metadata={"connector": "github"})
    store.record_usage("workspace-team", "artifact_exports", 3, metadata={"kind": "document"})
    usage = store.get_usage("workspace-team")

    assert usage["totals"]["connectors"] == 1
    assert usage["totals"]["artifact_exports"] == 3

    blocked = store.enforce_limit("workspace-team", metric="max_connectors", current_value=2)
    assert blocked["allowed"] is False
    assert blocked["reason"] == "max_connectors_limit_reached"


def test_workspace_billing_checkout_requires_iyzico_checkout_url():
    store = get_workspace_billing_store()

    with pytest.raises(RuntimeError, match="iyzico_plan_checkout_missing:pro"):
        store.create_checkout_session(
            workspace_id="workspace-team",
            plan_id="pro",
            success_url="https://tauri.localhost/billing/success",
            cancel_url="https://tauri.localhost/billing/cancel",
        )


def test_workspace_billing_checkout_uses_iyzico_checkout_url(monkeypatch):
    monkeypatch.setenv("IYZICO_PLAN_PRO_CHECKOUT_URL", "https://billing.local/checkout")

    store = get_workspace_billing_store()
    payload = store.create_checkout_session(
        workspace_id="workspace-team",
        plan_id="pro",
        success_url="https://tauri.localhost/billing/success",
        cancel_url="https://tauri.localhost/billing/cancel",
        customer_email="team@example.com",
    )

    assert payload["provider"] == "iyzico"
    assert payload["plan_id"] == "pro"
    assert payload["url"].startswith("https://billing.local/checkout?")
    assert "workspace_id=workspace-team" in payload["url"]
    assert "plan_id=pro" in payload["url"]


def test_workspace_billing_token_pack_webhook_is_idempotent():
    secret = "test-webhook-secret"
    store = get_workspace_billing_store()
    payload = {
        "event_type": "payment.updated",
        "workspace_id": "workspace-team",
        "token_pack_id": "starter_25k",
        "status": "paid",
        "reference_id": "pack_ref_1",
    }
    encoded = json.dumps(payload).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), encoded, hashlib.sha256).hexdigest()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("IYZICO_WEBHOOK_SECRET", secret)
        first = store.handle_webhook(encoded, {"x-iyzico-signature": signature}, provider="iyzico")
        first_balance = store.get_credit_balance("workspace-team")
        second = store.handle_webhook(encoded, {"x-iyzico-signature": signature}, provider="iyzico")
        second_balance = store.get_credit_balance("workspace-team")

    assert first["provider"] == "iyzico"
    assert second["provider"] == "iyzico"
    assert first_balance["purchased"] == second_balance["purchased"]


def test_workspace_billing_failed_payment_degrades_entitlements():
    secret = "test-webhook-secret"
    store = get_workspace_billing_store()
    payload = {
        "event_type": "payment.updated",
        "workspace_id": "workspace-team",
        "plan_id": "team",
        "status": "overdue",
        "reference_id": "plan_ref_1",
    }
    encoded = json.dumps(payload).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), encoded, hashlib.sha256).hexdigest()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("IYZICO_WEBHOOK_SECRET", secret)
        result = store.handle_webhook(encoded, {"x-iyzico-signature": signature}, provider="iyzico")
    entitlements = store.get_entitlements("workspace-team")

    assert result["status"] == "past_due"
    assert result["effective_plan_id"] == "free"
    assert entitlements["plan_id"] == "free"
    assert entitlements["degraded"] is True
    assert entitlements["degraded_reason"] == "subscription_past_due"


def test_workspace_billing_authorize_usage_estimates_runtime_costs():
    store = get_workspace_billing_store()

    decision = store.authorize_usage(
        "workspace-team",
        "cowork_threads",
        metadata={
            "mode": "website",
            "prompt_length": 1800,
            "routing_profile": "quality_first",
            "review_strictness": "strict",
        },
    )

    assert decision["allowed"] is True
    assert int(decision["estimated_credits"]) >= 8
    assert int(decision["available_credits"]) >= int(decision["estimated_credits"])


def test_workspace_billing_record_usage_auto_debits_runtime_estimate():
    store = get_workspace_billing_store()
    before = store.get_credit_balance("workspace-team")

    store.record_usage(
        "workspace-team",
        "cowork_turns",
        1,
        metadata={
            "mode": "document",
            "prompt_length": 1200,
        },
    )

    after = store.get_credit_balance("workspace-team")
    assert int(after["total"]) < int(before["total"])
