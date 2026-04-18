from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest

import core.billing.workspace_billing as workspace_billing_module
from core.billing.workspace_billing import get_workspace_billing_store
from core.persistence import get_runtime_database


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


def test_workspace_billing_weekly_reset_is_idempotent_and_rolls_forward(monkeypatch):
    store = get_workspace_billing_store()
    period_state = {
        "period": "weekly:2026-04-13:Europe/Istanbul",
        "reset_at": 1_713_000_000.0,
    }

    def fake_period_info(plan_id: str, *, ts: float | None = None):  # noqa: ARG001
        return {
            "cycle": "weekly",
            "period": period_state["period"],
            "period_start": 0.0,
            "reset_at": period_state["reset_at"],
            "timezone": "Europe/Istanbul",
            "anchor_weekday": 0,
            "anchor_day": 1,
        }

    monkeypatch.setattr(workspace_billing_module, "_billing_period_info", fake_period_info)

    first = store.get_credit_balance("workspace-team")
    second = store.get_credit_balance("workspace-team")
    ledger = store.get_credit_ledger("workspace-team")
    included_grants = [
        item for item in ledger["items"]
        if item.get("bucket") == "included" and item.get("entry_type") == "grant"
    ]

    assert int(first["included"]) == int(second["included"])
    assert len(included_grants) == 1

    period_state["period"] = "weekly:2026-04-20:Europe/Istanbul"
    period_state["reset_at"] = 1_713_604_800.0
    third = store.get_credit_balance("workspace-team")
    ledger = store.get_credit_ledger("workspace-team")
    included_grants = [
        item for item in ledger["items"]
        if item.get("bucket") == "included" and item.get("entry_type") == "grant"
    ]
    included_expires = [
        item for item in ledger["items"]
        if item.get("bucket") == "included" and item.get("entry_type") == "expire"
    ]

    assert int(third["included"]) == int(first["included"])
    assert len(included_grants) == 2
    assert len(included_expires) == 1


def test_workspace_billing_duplicate_grant_reference_is_idempotent():
    store = get_workspace_billing_store()
    before = store.get_credit_balance("workspace-team")

    store.record_credit_grant(
        "workspace-team",
        250,
        bucket="purchased",
        reference_id="pack_ref_1",
        metadata={"source": "cli"},
    )
    balance_after_first = store.get_credit_balance("workspace-team")
    store.record_credit_grant(
        "workspace-team",
        250,
        bucket="purchased",
        reference_id="pack_ref_1",
        metadata={"source": "cli"},
    )
    balance_after_second = store.get_credit_balance("workspace-team")
    ledger = store.get_credit_ledger("workspace-team")
    matching_grants = [
        item for item in ledger["items"]
        if item.get("reference_id") == "pack_ref_1" and item.get("entry_type") == "grant"
    ]

    assert int(balance_after_first["total"]) == int(before["total"]) + 250
    assert int(balance_after_second["total"]) == int(balance_after_first["total"])
    assert len(matching_grants) == 1


def test_workspace_billing_included_grants_are_scoped_by_plan_and_period():
    store = get_workspace_billing_store()
    first = store.record_credit_grant(
        "workspace-team",
        100,
        bucket="included",
        reference_id="checkout_pro_a",
        metadata={
            "plan_id": "pro",
            "period": "monthly:2026-04-01:Europe/Istanbul",
            "source": "iyzico",
        },
    )
    second = store.record_credit_grant(
        "workspace-team",
        100,
        bucket="included",
        reference_id="checkout_pro_b",
        metadata={
            "plan_id": "pro",
            "period": "monthly:2026-04-01:Europe/Istanbul",
            "source": "iyzico",
        },
    )
    third = store.record_credit_grant(
        "workspace-team",
        200,
        bucket="included",
        reference_id="checkout_team_a",
        metadata={
            "plan_id": "team",
            "period": "monthly:2026-04-01:Europe/Istanbul",
            "source": "iyzico",
        },
    )

    balance = store.get_credit_balance("workspace-team")
    ledger = store.get_credit_ledger("workspace-team")["items"]
    included_entries = [
        item for item in ledger if item.get("bucket") == "included" and item.get("entry_type") == "grant"
    ]
    pro_entries = [
        item
        for item in included_entries
        if item.get("reference_id") == "pro:monthly:2026-04-01:Europe/Istanbul"
    ]
    team_entries = [
        item
        for item in included_entries
        if item.get("reference_id") == "team:monthly:2026-04-01:Europe/Istanbul"
    ]

    assert int(first["credits"]) == 100
    assert int(second["credits"]) == 100
    assert int(third["credits"]) == 200
    assert len(pro_entries) == 1
    assert len(team_entries) == 1


def test_workspace_billing_bulk_backfill_is_deterministic_and_idempotent():
    runtime_db = get_runtime_database()
    runtime_db.access.ensure_workspace("workspace-zeta", display_name="Zeta")
    runtime_db.billing.upsert_workspace(
        {
            "workspace_id": "workspace-alpha",
            "plan_id": "pro",
            "status": "active",
            "billing_customer": "ws_alpha",
            "seats": 3,
            "metadata": {"workspace_owned": True},
            "updated_at": 5.0,
        }
    )

    store = get_workspace_billing_store()
    first = store.backfill_workspaces()
    second = store.backfill_workspaces()

    assert first["workspace_ids"] == ["workspace-alpha", "workspace-zeta"]
    assert second["workspace_ids"] == ["workspace-alpha", "workspace-zeta"]
    assert first["count"] == 2
    assert second["count"] == 2

    for workspace_id in first["workspace_ids"]:
        ledger = store.get_credit_ledger(workspace_id)["items"]
        included_grants = [
            item for item in ledger if item.get("bucket") == "included" and item.get("entry_type") == "grant"
        ]
        assert len(included_grants) == 1


def test_workspace_billing_record_usage_captures_trace_context(monkeypatch):
    store = get_workspace_billing_store()
    monkeypatch.setattr(
        workspace_billing_module,
        "get_trace_context",
        lambda: SimpleNamespace(
            trace_id="trace-abc",
            request_id="req-123",
            session_id="sess-456",
            workspace_id="workspace-team",
            source="POST /api/v1/test",
        ),
    )

    store.record_usage(
        "workspace-team",
        "connectors",
        1,
        metadata={"actor_id": "user-1", "source_type": "channel"},
    )
    event = store._repository.list_usage_events("workspace-team", limit=1)[0]

    assert event["actor_id"] == "user-1"
    assert event["metadata"]["trace_id"] == "trace-abc"
    assert event["metadata"]["request_id"] == "req-123"
    assert event["metadata"]["session_id"] == "sess-456"
    assert event["metadata"]["trace_source"] == "POST /api/v1/test"


def test_workspace_billing_entitlement_gate_blocks_voice_features():
    store = get_workspace_billing_store()

    access = store.check_feature_access("workspace-team", "voice_features")

    assert access["allowed"] is False
    assert access["feature"] == "voice_features"
    assert access["upgrade_hint"]


def test_workspace_billing_authorize_usage_blocks_on_quota_caps(monkeypatch):
    store = get_workspace_billing_store()
    monkeypatch.setattr(
        store,
        "_rate_limit_snapshot",
        lambda context, entitlements: {
            "request_limit": 1,
            "credit_limit": 0,
            "period_limit": 0,
            "soft_period_limit": 0,
            "request_count": 1,
            "hour_spend": 0,
            "period_spend": 0,
            "period": "weekly:2026-04-13:Europe/Istanbul",
            "reset_at": 1_713_000_000.0,
            "request_key": "workspace-team:minute",
            "credit_key": "workspace-team:hour",
            "period_key": "workspace-team:period",
        },
    )

    decision = store.authorize_usage("workspace-team", "cowork_threads", metadata={"mode": "document"})

    assert decision["allowed"] is False
    assert decision["reason"] == "requests_per_minute_limit_reached"
    assert int(decision["status_code"]) == 429


def test_workspace_billing_authorize_usage_blocks_on_hour_spend_cap(monkeypatch):
    store = get_workspace_billing_store()
    monkeypatch.setattr(
        store,
        "_rate_limit_snapshot",
        lambda context, entitlements: {
            "request_limit": 0,
            "credit_limit": 5,
            "period_limit": 0,
            "soft_period_limit": 0,
            "request_count": 0,
            "hour_spend": 5,
            "period_spend": 0,
            "period": "weekly:2026-04-13:Europe/Istanbul",
            "reset_at": 1_713_000_000.0,
            "request_key": "workspace-team:minute",
            "credit_key": "workspace-team:hour",
            "period_key": "workspace-team:period",
        },
    )

    decision = store.authorize_usage("workspace-team", "cowork_threads", metadata={"mode": "document", "prompt_length": 800})

    assert decision["allowed"] is False
    assert decision["reason"] == "credit_spend_cap_per_hour_reached"
    assert int(decision["status_code"]) == 429


def test_workspace_billing_summary_exposes_visibility_surface():
    store = get_workspace_billing_store()
    store.record_usage("workspace-team", "cowork_turns", 1, metadata={"estimated_credits": 4500, "provider": "openai", "model_name": "gpt-4o"})

    summary = store.get_workspace_summary("workspace-team")

    assert summary["feature_access"]["web_tools"] is True
    assert summary["usage_summary"]["period"]["reset_at"] > 0
    assert summary["top_cost_sources"]
    assert isinstance(summary["triggered_limits"], list)
    assert summary["upgrade_hint"] is not None
