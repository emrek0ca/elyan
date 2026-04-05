from __future__ import annotations

import base64
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest

import core.billing.iyzico_provider as iyzico_provider_module
import core.billing.workspace_billing as workspace_billing_module
from core.billing.iyzico_provider import IyzicoProvider
from core.billing.payment_provider import ProviderCompletion
from core.billing.workspace_billing import get_workspace_billing_store
from core.gateway import server as gateway_server


@pytest.fixture(autouse=True)
def isolated_billing_cutover(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_DATA_DIR", str(tmp_path / "elyan"))
    monkeypatch.delenv("IYZICO_REAL_API_ENABLED", raising=False)
    monkeypatch.delenv("IYZICO_API_KEY", raising=False)
    monkeypatch.delenv("IYZICO_SECRET_KEY", raising=False)
    monkeypatch.delenv("IYZICO_MERCHANT_ID", raising=False)
    monkeypatch.delenv("IYZICO_BASE_URL", raising=False)
    monkeypatch.delenv("IYZICO_PUBLIC_CALLBACK_BASE_URL", raising=False)
    monkeypatch.delenv("IYZICO_SUBSCRIPTION_PLAN_REF_PRO", raising=False)
    workspace_billing_module._workspace_billing_store = None
    yield
    workspace_billing_module._workspace_billing_store = None


class _Req:
    def __init__(
        self,
        data: dict | None = None,
        *,
        match_info: dict | None = None,
        method: str = "GET",
        headers: dict | None = None,
        query: dict | None = None,
        auth: dict | None = None,
        body: bytes | None = None,
    ):
        self._data = data or {}
        self._auth = auth or {}
        self._body = body if body is not None else json.dumps(self._data).encode("utf-8")
        self.method = method
        self.match_info = match_info or {}
        self.headers = headers or {}
        self.cookies = {}
        self.remote = "127.0.0.1"
        self.transport = None
        self.rel_url = SimpleNamespace(query=query or {})

    async def json(self):
        return self._data

    async def read(self):
        return self._body

    def get(self, key, default=None):
        if key == "elyan_auth":
            return self._auth
        return default


def test_iyzico_auth_headers_follow_v2_signature(monkeypatch):
    monkeypatch.setenv("IYZICO_API_KEY", "api-key")
    monkeypatch.setenv("IYZICO_SECRET_KEY", "secret-key")
    monkeypatch.setattr(iyzico_provider_module.time, "time", lambda: 1700000000.123)
    monkeypatch.setattr(iyzico_provider_module.secrets, "token_hex", lambda _: "feedbeefcafe")

    provider = IyzicoProvider()
    body = {"locale": "tr", "token": "tok_1"}
    path = "/payment/iyzipos/checkoutform/auth/ecom/detail"

    headers = provider._auth_headers(path=path, body=body)

    expected_random_key = "1700000000123feedbeefcafe"
    expected_signature = hmac.new(
        b"secret-key",
        f"{expected_random_key}{path}{json.dumps(body, ensure_ascii=False, separators=(',', ':'))}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    expected_auth = base64.b64encode(
        f"apiKey:api-key&randomKey:{expected_random_key}&signature:{expected_signature}".encode("utf-8")
    ).decode("utf-8")

    assert headers["Authorization"] == f"IYZWSv2 {expected_auth}"
    assert headers["x-iyzi-rnd"] == expected_random_key


def test_iyzico_webhook_v3_validation_for_hpp(monkeypatch):
    monkeypatch.setenv("IYZICO_REAL_API_ENABLED", "1")
    monkeypatch.setenv("IYZICO_SECRET_KEY", "merchant-secret")

    body = {
        "paymentConversationId": "conv_123",
        "status": "SUCCESS",
        "token": "tok_123",
        "iyziEventType": "CHECKOUT_FORM_AUTH",
        "iyziPaymentId": "pay_456",
    }
    message = "merchant-secretCHECKOUT_FORM_AUTHpay_456tok_123conv_123SUCCESS"
    signature = hmac.new(b"merchant-secret", message.encode("utf-8"), hashlib.sha256).hexdigest()

    provider = IyzicoProvider()
    completion = provider.handle_webhook(
        payload=json.dumps(body).encode("utf-8"),
        headers={"X-IYZ-SIGNATURE-V3": signature},
    )

    assert completion.provider == "iyzico"
    assert completion.mode == "token_pack"
    assert completion.reference_id == "conv_123"
    assert completion.provider_payment_id == "pay_456"
    assert completion.status == "success"


def test_workspace_billing_real_checkout_requires_complete_profile(monkeypatch):
    monkeypatch.setenv("IYZICO_REAL_API_ENABLED", "1")
    store = get_workspace_billing_store()

    with pytest.raises(RuntimeError, match="billing_profile_incomplete"):
        store.create_checkout_session(
            workspace_id="workspace-team",
            plan_id="pro",
            success_url="https://tauri.localhost/billing/success",
            cancel_url="https://tauri.localhost/billing/cancel",
        )


def test_workspace_billing_callback_retrieve_is_idempotent_for_token_pack(monkeypatch):
    store = get_workspace_billing_store()
    record = store._workspace("workspace-team")
    record.metadata["pending_token_pack_id"] = "growth_100k"
    record.metadata["pending_reference_id"] = "pack_ref_cutover"
    record.updated_at = 1.0
    store._save()
    store._repository.upsert_checkout_session(
        {
            "reference_id": "pack_ref_cutover",
            "workspace_id": "workspace-team",
            "mode": "token_pack",
            "catalog_id": "growth_100k",
            "provider": "iyzico",
            "provider_token": "tok_cutover",
            "status": "pending",
            "payment_page_url": "https://billing.local/checkout",
            "callback_url": "https://callback.example/iyzico",
            "raw_last_payload": {"token": "tok_cutover"},
        }
    )

    def _fake_retrieve(*, token: str, reference_id: str = "") -> ProviderCompletion:
        return ProviderCompletion(
            provider="iyzico",
            mode="token_pack",
            reference_id=reference_id,
            status="paid",
            provider_token=token,
            provider_payment_id="pay_cutover",
            credits=105000,
            raw={"token": token, "paymentStatus": "SUCCESS"},
        )

    monkeypatch.setattr(store._provider, "retrieve_token_pack_checkout", _fake_retrieve)

    before = store.get_credit_balance("workspace-team")
    first = store.complete_checkout_callback(token="tok_cutover", reference_id="pack_ref_cutover", mode="token_pack")
    middle = store.get_credit_balance("workspace-team")
    second = store.complete_checkout_callback(token="tok_cutover", reference_id="pack_ref_cutover", mode="token_pack")
    after = store.get_credit_balance("workspace-team")

    assert first["checkout"]["status"] == "completed"
    assert second["checkout"]["status"] == "completed"
    assert int(middle["purchased"]) - int(before["purchased"]) == 105000
    assert int(after["purchased"]) == int(middle["purchased"])


@pytest.mark.asyncio
async def test_handle_v1_billing_checkout_detail_returns_payload():
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    req = _Req(match_info={"reference_id": "chk_123"})

    class _FakeStore:
        def get_checkout_session(self, workspace_id: str, reference_id: str, *, refresh: bool = True):
            assert workspace_id == "workspace-a"
            assert reference_id == "chk_123"
            assert refresh is True
            return {
                "reference_id": reference_id,
                "workspace_id": workspace_id,
                "mode": "subscription",
                "status": "pending",
                "launch_url": "https://billing.local/chk_123",
            }

    srv._workspace_id = lambda request, payload=None: "workspace-a"
    srv._workspace_billing = lambda: _FakeStore()

    resp = await gateway_server.ElyanGatewayServer.handle_v1_billing_checkout_detail(srv, req)
    payload = json.loads(resp.text)

    assert payload["success"] is True
    assert payload["checkout"]["reference_id"] == "chk_123"
    assert payload["checkout"]["mode"] == "subscription"


@pytest.mark.asyncio
async def test_handle_v1_billing_profile_put_returns_payload():
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    req = _Req(
        {
            "full_name": "Ada Lovelace",
            "email": "ada@example.com",
            "phone": "+905555555555",
            "identity_number": "12345678901",
            "address_line1": "Istanbul",
            "city": "Istanbul",
            "zip_code": "34000",
            "country": "Turkey",
        },
        method="PUT",
    )

    class _FakeStore:
        def update_billing_profile(self, workspace_id: str, payload: dict[str, str]):
            return {
                "workspace_id": workspace_id,
                "profile": payload,
                "is_complete": True,
                "missing_fields": [],
            }

    srv._workspace_id = lambda request, payload=None: "workspace-a"
    srv._require_billing_write_role = lambda request, payload=None: (True, "")
    srv._auth_context = lambda request: {"email": "ada@example.com"}
    srv._workspace_billing = lambda: _FakeStore()

    resp = await gateway_server.ElyanGatewayServer.handle_v1_billing_profile(srv, req)
    payload = json.loads(resp.text)

    assert payload["success"] is True
    assert payload["profile"]["is_complete"] is True
    assert payload["profile"]["profile"]["full_name"] == "Ada Lovelace"


@pytest.mark.asyncio
async def test_billing_checkout_endpoints_reject_viewer_role():
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    auth = {
        "workspace_id": "workspace-a",
        "user_id": "viewer-1",
        "role": "viewer",
        "email": "viewer@example.com",
    }

    class _ForbiddenStore:
        def create_checkout_session(self, *args, **kwargs):  # pragma: no cover - must not be called
            raise AssertionError("create_checkout_session should not be called")

        def purchase_token_pack(self, *args, **kwargs):  # pragma: no cover - must not be called
            raise AssertionError("purchase_token_pack should not be called")

    srv._workspace_billing = lambda: _ForbiddenStore()

    checkout_req = _Req({"plan_id": "pro"}, method="POST", auth=auth)
    checkout_resp = await gateway_server.ElyanGatewayServer.handle_v1_billing_checkout_init(srv, checkout_req)
    checkout_payload = json.loads(checkout_resp.text)

    purchase_req = _Req({"pack_id": "growth_100k"}, method="POST", auth=auth)
    purchase_resp = await gateway_server.ElyanGatewayServer.handle_v1_billing_token_pack_purchase(srv, purchase_req)
    purchase_payload = json.loads(purchase_resp.text)

    assert checkout_resp.status == 403
    assert checkout_payload["error"] == "owner or billing_admin role required"
    assert purchase_resp.status == 403
    assert purchase_payload["error"] == "owner or billing_admin role required"


def test_subscription_webhook_without_resolvable_session_raises(monkeypatch):
    monkeypatch.setenv("IYZICO_REAL_API_ENABLED", "1")
    monkeypatch.setenv("IYZICO_SECRET_KEY", "merchant-secret")
    monkeypatch.setenv("IYZICO_MERCHANT_ID", "merchant-123")
    store = get_workspace_billing_store()
    before = dict(store._repository.load_workspace_records())

    body = {
        "merchantId": "merchant-123",
        "iyziEventType": "subscription.activated",
        "subscriptionReferenceCode": "sub_ref_missing",
    }
    message = "merchant-secretmerchant-123subscription.activatedsub_ref_missing"
    signature = hmac.new(b"merchant-secret", message.encode("utf-8"), hashlib.sha256).hexdigest()

    with pytest.raises(RuntimeError, match="webhook_unresolvable_workspace:ref=:sub_ref=sub_ref_missing"):
        store.handle_webhook(
            json.dumps(body).encode("utf-8"),
            {"X-IYZ-SIGNATURE-V3": signature},
            provider="iyzico",
        )
    after = store._repository.load_workspace_records()

    assert after == before
    assert "local-workspace" not in after


def test_store_handle_webhook_requires_fallback_secret(monkeypatch):
    monkeypatch.delenv("IYZICO_REAL_API_ENABLED", raising=False)
    monkeypatch.delenv("IYZICO_WEBHOOK_SECRET", raising=False)
    store = get_workspace_billing_store()

    with pytest.raises(RuntimeError, match="iyzico_webhook_secret_required"):
        store.handle_webhook(
            json.dumps(
                {
                    "event_type": "payment.updated",
                    "workspace_id": "workspace-team",
                    "token_pack_id": "starter_25k",
                    "status": "paid",
                    "reference_id": "pack_ref_1",
                }
            ).encode("utf-8"),
            {},
            provider="iyzico",
        )


@pytest.mark.asyncio
async def test_handle_v1_billing_webhook_requires_fallback_secret(monkeypatch):
    monkeypatch.delenv("IYZICO_REAL_API_ENABLED", raising=False)
    monkeypatch.delenv("IYZICO_WEBHOOK_SECRET", raising=False)
    srv = gateway_server.ElyanGatewayServer.__new__(gateway_server.ElyanGatewayServer)
    req = _Req(
        body=json.dumps(
            {
                "event_type": "payment.updated",
                "workspace_id": "workspace-team",
                "token_pack_id": "starter_25k",
                "status": "paid",
                "reference_id": "pack_ref_1",
            }
        ).encode("utf-8"),
        method="POST",
        headers={},
    )
    srv._workspace_billing = lambda: get_workspace_billing_store()

    resp = await gateway_server.ElyanGatewayServer.handle_v1_billing_webhook_iyzico(srv, req)
    payload = json.loads(resp.text)

    assert resp.status != 200
    assert payload["success"] is False
    assert payload["error"] == "iyzico_webhook_secret_required"
