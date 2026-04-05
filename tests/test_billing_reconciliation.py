from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import core.billing.workspace_billing as workspace_billing_module
from core.billing.workspace_billing import get_workspace_billing_store
from core.gateway import server as gateway_server


@pytest.fixture(autouse=True)
def isolated_workspace_billing(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_DATA_DIR", str(tmp_path / "elyan"))
    workspace_billing_module._workspace_billing_store = None
    yield
    workspace_billing_module._workspace_billing_store = None


def test_workspace_billing_reconcile_usage_refunds_and_is_idempotent():
    store = get_workspace_billing_store()
    before = store.get_credit_balance("workspace-team")
    usage = store.record_usage(
        "workspace-team",
        "workflow_runs",
        1,
        metadata={"estimated_credits": 8, "run_id": "run_reconcile_1"},
    )
    after_debit = store.get_credit_balance("workspace-team")

    result = store.reconcile_usage(
        "workspace-team",
        usage_id=str(usage["usage_id"]),
        actual_credits=5,
        metadata={"provider": "openai", "model": "gpt-4.1"},
    )
    after_reconcile = store.get_credit_balance("workspace-team")
    second = store.reconcile_usage(
        "workspace-team",
        usage_id=str(usage["usage_id"]),
        actual_credits=5,
    )

    assert int(after_debit["total"]) == int(before["total"]) - 8
    assert result["status"] == "applied"
    assert result["delta_credits"] == -3
    assert int(after_reconcile["total"]) == int(after_debit["total"]) + 3
    assert second["idempotent"] is True
    updated = store.get_usage_entry("workspace-team", str(usage["usage_id"]))
    assert str((((updated or {}).get("metadata") or {}).get("reconciliation") or {}).get("status") or "") == "applied"


def test_workspace_billing_reconcile_usage_reports_shortfall():
    store = get_workspace_billing_store()
    usage = store.record_usage(
        "workspace-team",
        "cowork_turns",
        1,
        metadata={"estimated_credits": 2, "thread_id": "thread_shortfall"},
    )

    result = store.reconcile_usage(
        "workspace-team",
        usage_id=str(usage["usage_id"]),
        actual_credits=20000,
        metadata={"provider": "anthropic"},
    )

    assert result["status"] == "insufficient_credits"
    assert result["reconciled"] is False
    updated = store.get_usage_entry("workspace-team", str(usage["usage_id"]))
    assert str((((updated or {}).get("metadata") or {}).get("reconciliation") or {}).get("status") or "") == "insufficient_credits"


class _Req:
    def __init__(self, data: dict):
        self._data = data
        self.rel_url = SimpleNamespace(query={})
        self.match_info = {}
        self.headers = {}
        self.cookies = {}
        self.remote = "127.0.0.1"
        self.transport = None

    async def json(self):
        return self._data


@pytest.mark.asyncio
async def test_handle_v1_billing_reconcile_usage_returns_payload():
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    req = _Req({"usage_id": "usage_123", "actual_credits": 7, "actual_cost_usd": 0.12, "total_tokens": 2048})

    class _FakeStore:
        def reconcile_usage(self, workspace_id: str, *, usage_id: str, actual_credits: int, metadata: dict | None = None):
            return {
                "workspace_id": workspace_id,
                "usage_id": usage_id,
                "actual_credits": actual_credits,
                "status": "applied",
                "metadata": dict(metadata or {}),
            }

    srv._require_billing_write_role = lambda request, payload=None: (True, "")
    srv._workspace_id = lambda request, payload=None: "workspace-a"
    srv._actor_id = lambda request, payload=None: "owner-1"
    srv._workspace_billing = lambda: _FakeStore()

    resp = await gateway_server.ElyanGatewayServer.handle_v1_billing_reconcile_usage(srv, req)
    payload = json.loads(resp.text)

    assert payload["success"] is True
    assert payload["reconciliation"]["workspace_id"] == "workspace-a"
    assert payload["reconciliation"]["usage_id"] == "usage_123"
    assert payload["reconciliation"]["actual_credits"] == 7
    assert payload["reconciliation"]["metadata"]["reconciled_by"] == "owner-1"


@pytest.mark.asyncio
async def test_handle_v1_billing_events_returns_payload():
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    req = _Req({})

    class _FakeStore:
        def get_billing_events(self, workspace_id: str, *, limit: int = 100):
            return {
                "workspace_id": workspace_id,
                "items": [
                    {
                        "event_id": "evt_1",
                        "workspace_id": workspace_id,
                        "event_type": "billing.usage.reconciled",
                        "status": "applied",
                    }
                ],
            }

    srv._workspace_id = lambda request, payload=None: "workspace-a"
    srv._workspace_billing = lambda: _FakeStore()

    resp = await gateway_server.ElyanGatewayServer.handle_v1_billing_events(srv, req)
    payload = json.loads(resp.text)

    assert payload["success"] is True
    assert payload["events"]["workspace_id"] == "workspace-a"
    assert payload["events"]["items"][0]["event_type"] == "billing.usage.reconciled"


@pytest.mark.asyncio
async def test_handle_v1_start_workflow_refunds_provisional_usage_on_dispatch_failure(monkeypatch):
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    req = _Req({"task_type": "document", "brief": "Quarterly summary"})
    calls: dict[str, dict] = {}

    class _FakeStore:
        def record_usage(self, workspace_id: str, metric: str, amount: int = 1, *, metadata: dict | None = None):
            calls["record"] = {
                "workspace_id": workspace_id,
                "metric": metric,
                "amount": amount,
                "metadata": dict(metadata or {}),
            }
            return {"usage_id": "usage_workflow_1", "metadata": dict(metadata or {})}

        def reconcile_usage(self, workspace_id: str, *, usage_id: str, actual_credits: int, metadata: dict | None = None):
            calls["reconcile"] = {
                "workspace_id": workspace_id,
                "usage_id": usage_id,
                "actual_credits": actual_credits,
                "metadata": dict(metadata or {}),
            }
            return {"status": "applied"}

    class _FakeRunner:
        async def start_workflow(self, **kwargs):
            raise ValueError("workflow brief required")

    srv._require_execution_seat = lambda request, payload=None: (True, "")
    srv._observe_execution_guard = lambda *args, **kwargs: None
    srv._usage_credit_decision = lambda request, metric, payload=None, amount=1, metadata=None: {
        "allowed": True,
        "estimated_credits": 8,
    }
    srv._workspace_id = lambda request, payload=None: "workspace-a"
    srv._actor_id = lambda request, payload=None: "owner-1"
    srv._workspace_billing = lambda: _FakeStore()

    monkeypatch.setattr("core.workflow.vertical_runner.get_vertical_workflow_runner", lambda: _FakeRunner())

    resp = await gateway_server.ElyanGatewayServer.handle_v1_start_workflow(srv, req)
    payload = json.loads(resp.text)

    assert resp.status == 400
    assert payload["success"] is False
    assert calls["record"]["metric"] == "workflow_runs"
    assert calls["reconcile"]["usage_id"] == "usage_workflow_1"
    assert calls["reconcile"]["actual_credits"] == 0
    assert calls["reconcile"]["metadata"]["dispatch_failed"] is True
    assert calls["reconcile"]["metadata"]["failure_class"] == "validation_error"
