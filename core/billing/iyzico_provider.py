from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from core.billing.commercial_types import get_plan, get_token_pack
from core.billing.payment_provider import BillingProfile, CheckoutRequest, CheckoutSession, PaymentProvider, ProviderCompletion


def _compact_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class IyzicoProvider(PaymentProvider):
    provider_name = "iyzico"

    @staticmethod
    def _plan_env(plan_id: str) -> str:
        return f"IYZICO_PLAN_{str(plan_id or '').strip().upper()}_CHECKOUT_URL"

    @staticmethod
    def _token_pack_env(pack_id: str) -> str:
        return f"IYZICO_TOKEN_PACK_{str(pack_id or '').strip().upper()}_CHECKOUT_URL"

    @staticmethod
    def _webhook_secret() -> str:
        return str(os.getenv("IYZICO_WEBHOOK_SECRET", "") or "").strip()

    @staticmethod
    def _checkout_url_from_env(env_name: str) -> str:
        return str(os.getenv(env_name, "") or "").strip()

    @staticmethod
    def _append_query(base_url: str, payload: dict[str, Any]) -> str:
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}{urlencode({k: v for k, v in payload.items() if str(v or '').strip()})}"

    @staticmethod
    def _normalize_status(value: str) -> str:
        return str(value or "").strip().lower()

    @staticmethod
    def _name_parts(full_name: str) -> tuple[str, str]:
        parts = [part for part in str(full_name or "").strip().split() if part]
        if not parts:
            return ("Elyan", "Customer")
        if len(parts) == 1:
            return (parts[0], "Customer")
        return (parts[0], " ".join(parts[1:]))

    @staticmethod
    def _identity_number(profile: BillingProfile | None) -> str:
        digits = "".join(ch for ch in str((profile.identity_number if profile else "") or "") if ch.isdigit())
        return digits

    @staticmethod
    def _locale() -> str:
        return str(os.getenv("IYZICO_LOCALE", "tr") or "tr").strip() or "tr"

    @staticmethod
    def _currency() -> str:
        return str(os.getenv("IYZICO_CURRENCY", "TRY") or "TRY").strip() or "TRY"

    @staticmethod
    def _real_api_enabled() -> bool:
        value = str(os.getenv("IYZICO_REAL_API_ENABLED", "0") or "0").strip().lower()
        return value in {"1", "true", "yes", "on"}

    @staticmethod
    def _api_key() -> str:
        return str(os.getenv("IYZICO_API_KEY", "") or "").strip()

    @staticmethod
    def _secret_key() -> str:
        return str(os.getenv("IYZICO_SECRET_KEY", "") or "").strip()

    @staticmethod
    def _merchant_id() -> str:
        return str(os.getenv("IYZICO_MERCHANT_ID", "") or "").strip()

    @staticmethod
    def _base_url() -> str:
        return str(os.getenv("IYZICO_BASE_URL", "https://api.iyzipay.com") or "https://api.iyzipay.com").strip().rstrip("/")

    @staticmethod
    def _public_callback_base_url() -> str:
        return str(os.getenv("IYZICO_PUBLIC_CALLBACK_BASE_URL", "") or "").strip().rstrip("/")

    @classmethod
    def _subscription_plan_reference_code(cls, plan_id: str) -> str:
        normalized = str(plan_id or "").strip().lower()
        env_name = f"IYZICO_SUBSCRIPTION_PLAN_REF_{normalized.upper()}"
        return str(os.getenv(env_name, "") or "").strip()

    @classmethod
    def _require_real_api_config(cls) -> None:
        missing = []
        if not cls._api_key():
            missing.append("IYZICO_API_KEY")
        if not cls._secret_key():
            missing.append("IYZICO_SECRET_KEY")
        if not cls._merchant_id():
            missing.append("IYZICO_MERCHANT_ID")
        if not cls._base_url():
            missing.append("IYZICO_BASE_URL")
        if not cls._public_callback_base_url():
            missing.append("IYZICO_PUBLIC_CALLBACK_BASE_URL")
        if missing:
            raise RuntimeError(f"iyzico_config_missing:{','.join(missing)}")

    def _auth_headers(self, *, path: str, body: dict[str, Any] | None = None) -> dict[str, str]:
        body_payload = body or {}
        random_key = f"{int(time.time() * 1000)}{secrets.token_hex(6)}"
        body_text = _compact_json(body_payload) if body_payload else ""
        signature_payload = f"{random_key}{path}{body_text}"
        signature = hmac.new(
            self._secret_key().encode("utf-8"),
            signature_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        auth_value = base64.b64encode(
            f"apiKey:{self._api_key()}&randomKey:{random_key}&signature:{signature}".encode("utf-8")
        ).decode("utf-8")
        return {
            "Authorization": f"IYZWSv2 {auth_value}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-iyzi-rnd": random_key,
            "x-iyzi-client-version": "elyan-billing/1.0",
        }

    def _request(self, method: str, path: str, *, body: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_real_api_config()
        url = f"{self._base_url()}{path}"
        request_body = body or {}
        response = httpx.request(
            method.upper(),
            url,
            headers=self._auth_headers(path=path, body=request_body if method.upper() != "GET" else None),
            content=_compact_json(request_body).encode("utf-8") if method.upper() != "GET" and request_body else None,
            timeout=25.0,
        )
        try:
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(f"iyzico_invalid_response:{response.status_code}:{exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"iyzico_invalid_payload:{response.status_code}")
        status = self._normalize_status(payload.get("status"))
        if response.status_code >= 400 or status == "failure":
            error_code = str(payload.get("errorCode") or payload.get("error_code") or response.status_code)
            error_message = str(payload.get("errorMessage") or payload.get("error_message") or response.text or "iyzico_request_failed").strip()
            raise RuntimeError(f"iyzico_request_failed:{error_code}:{error_message}")
        return payload

    @classmethod
    def _launch_route(cls, reference_id: str) -> str:
        return f"{cls._public_callback_base_url()}/api/v1/billing/checkouts/{quote(str(reference_id or '').strip(), safe='')}/launch"

    def _buyer_payload(self, request: CheckoutRequest) -> tuple[dict[str, Any], dict[str, Any]]:
        profile = request.billing_profile
        if profile is None:
            raise RuntimeError("billing_profile_required")
        first_name, surname = self._name_parts(profile.full_name)
        billing_address = {
            "address": str(profile.address_line1 or "").strip(),
            "zipCode": str(profile.zip_code or "").strip(),
            "contactName": str(profile.full_name or "").strip(),
            "city": str(profile.city or "").strip(),
            "country": str(profile.country or "").strip(),
        }
        buyer = {
            "id": str(request.workspace_id or "").strip(),
            "name": first_name,
            "surname": surname,
            "identityNumber": self._identity_number(profile),
            "email": str(profile.email or request.customer_email or "").strip(),
            "gsmNumber": str(profile.phone or "").strip(),
            "registrationAddress": str(profile.address_line1 or "").strip(),
            "city": str(profile.city or "").strip(),
            "country": str(profile.country or "").strip(),
            "zipCode": str(profile.zip_code or "").strip(),
            "ip": str((request.metadata or {}).get("ip") or "127.0.0.1"),
        }
        return buyer, billing_address

    def _customer_payload(self, request: CheckoutRequest) -> dict[str, Any]:
        profile = request.billing_profile
        if profile is None:
            raise RuntimeError("billing_profile_required")
        first_name, surname = self._name_parts(profile.full_name)
        address_payload = {
            "address": str(profile.address_line1 or "").strip(),
            "zipCode": str(profile.zip_code or "").strip(),
            "contactName": str(profile.full_name or "").strip(),
            "city": str(profile.city or "").strip(),
            "country": str(profile.country or "").strip(),
        }
        return {
            "name": first_name,
            "surname": surname,
            "email": str(profile.email or request.customer_email or "").strip(),
            "gsmNumber": str(profile.phone or "").strip(),
            "identityNumber": self._identity_number(profile),
            "billingAddress": dict(address_payload),
            "shippingAddress": dict(address_payload),
        }

    def create_subscription_checkout(self, *, plan_id: str, request: CheckoutRequest) -> CheckoutSession:
        plan = get_plan(plan_id)
        if not self._real_api_enabled():
            launch_url = self._checkout_url_from_env(self._plan_env(plan.plan_id))
            if not launch_url:
                raise RuntimeError(f"iyzico_plan_checkout_missing:{plan.plan_id}")
            enriched_url = self._append_query(
                launch_url,
                {
                    "workspace_id": request.workspace_id,
                    "reference_id": request.external_reference,
                    "plan_id": plan.plan_id,
                    "success_url": request.success_url,
                    "cancel_url": request.cancel_url,
                    "email": request.customer_email,
                },
            )
            return CheckoutSession(
                provider=self.provider_name,
                mode="subscription",
                launch_url=enriched_url,
                reference_id=request.external_reference,
                metadata={"plan": plan.to_dict(), "workspace_id": request.workspace_id},
            )

        pricing_plan_reference_code = self._subscription_plan_reference_code(plan.plan_id)
        if not pricing_plan_reference_code:
            raise RuntimeError(f"iyzico_subscription_plan_reference_missing:{plan.plan_id}")
        payload = {
            "locale": self._locale(),
            "conversationId": request.external_reference,
            "pricingPlanReferenceCode": pricing_plan_reference_code,
            "callbackUrl": str(request.callback_url or "").strip(),
            "subscriptionInitialStatus": "ACTIVE",
            "customer": self._customer_payload(request),
        }
        response = self._request("POST", "/v2/subscription/checkoutform/initialize", body=payload)
        token = str(response.get("token") or "").strip()
        launch_url = self._launch_route(request.external_reference)
        return CheckoutSession(
            provider=self.provider_name,
            mode="subscription",
            launch_url=launch_url,
            payment_page_url=launch_url,
            callback_url=str(request.callback_url or "").strip(),
            reference_id=request.external_reference,
            status=self._normalize_status(response.get("status")) or "pending",
            provider_token=token,
            metadata={
                "plan": plan.to_dict(),
                "workspace_id": request.workspace_id,
                "pricing_plan_reference_code": pricing_plan_reference_code,
                "checkout_form_content": str(response.get("checkoutFormContent") or ""),
                "raw": response,
            },
        )

    def create_token_pack_checkout(self, *, pack_id: str, request: CheckoutRequest) -> CheckoutSession:
        token_pack = get_token_pack(pack_id)
        if not self._real_api_enabled():
            launch_url = self._checkout_url_from_env(self._token_pack_env(token_pack.pack_id))
            if not launch_url:
                raise RuntimeError(f"iyzico_token_pack_checkout_missing:{token_pack.pack_id}")
            enriched_url = self._append_query(
                launch_url,
                {
                    "workspace_id": request.workspace_id,
                    "reference_id": request.external_reference,
                    "token_pack_id": token_pack.pack_id,
                    "success_url": request.success_url,
                    "cancel_url": request.cancel_url,
                    "email": request.customer_email,
                },
            )
            return CheckoutSession(
                provider=self.provider_name,
                mode="token_pack",
                launch_url=enriched_url,
                reference_id=request.external_reference,
                metadata={"token_pack": token_pack.to_dict(), "workspace_id": request.workspace_id},
            )

        buyer, address_payload = self._buyer_payload(request)
        payload = {
            "locale": self._locale(),
            "conversationId": request.external_reference,
            "price": float(token_pack.price_try),
            "paidPrice": float(token_pack.price_try),
            "currency": self._currency(),
            "basketId": request.external_reference,
            "paymentGroup": "PRODUCT",
            "callbackUrl": str(request.callback_url or "").strip(),
            "buyer": buyer,
            "shippingAddress": dict(address_payload),
            "billingAddress": dict(address_payload),
            "basketItems": [
                {
                    "id": token_pack.pack_id,
                    "price": float(token_pack.price_try),
                    "name": token_pack.label,
                    "category1": "Elyan Credits",
                    "category2": token_pack.pack_id,
                    "itemType": "VIRTUAL",
                }
            ],
        }
        response = self._request("POST", "/payment/iyzipos/checkoutform/initialize/auth/ecom", body=payload)
        return CheckoutSession(
            provider=self.provider_name,
            mode="token_pack",
            launch_url=str(response.get("paymentPageUrl") or "").strip(),
            payment_page_url=str(response.get("paymentPageUrl") or "").strip(),
            callback_url=str(request.callback_url or "").strip(),
            reference_id=request.external_reference,
            status=self._normalize_status(response.get("status")) or "pending",
            provider_token=str(response.get("token") or "").strip(),
            metadata={
                "token_pack": token_pack.to_dict(),
                "workspace_id": request.workspace_id,
                "checkout_form_content": str(response.get("checkoutFormContent") or ""),
                "raw": response,
            },
        )

    def retrieve_subscription_checkout(self, *, token: str, reference_id: str = "") -> ProviderCompletion:
        normalized_token = str(token or "").strip()
        if not normalized_token:
            raise RuntimeError("iyzico_checkout_token_required")
        if not self._real_api_enabled():
            return ProviderCompletion(
                provider=self.provider_name,
                mode="subscription",
                reference_id=str(reference_id or "").strip(),
                status="pending",
                provider_token=normalized_token,
                raw={"token": normalized_token},
            )
        response = self._request("GET", f"/v2/subscription/checkoutform/{quote(normalized_token, safe='')}")
        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        status = self._normalize_status(data.get("subscriptionStatus") or response.get("status"))
        completed_at = float(data.get("createdDate") or data.get("startDate") or 0.0) / 1000 if data else 0.0
        return ProviderCompletion(
            provider=self.provider_name,
            mode="subscription",
            reference_id=str(reference_id or response.get("conversationId") or "").strip(),
            status=status or "pending",
            provider_token=normalized_token,
            provider_payment_id=str(data.get("parentReferenceCode") or "").strip(),
            subscription_reference_code=str(data.get("referenceCode") or "").strip(),
            customer_reference_code=str(data.get("customerReferenceCode") or "").strip(),
            event_type="checkout.retrieve",
            completed_at=completed_at,
            metadata={
                "pricing_plan_reference_code": str(data.get("pricingPlanReferenceCode") or "").strip(),
                "start_date": float(data.get("startDate") or 0.0),
                "end_date": float(data.get("endDate") or 0.0),
                "trial_start_date": float(data.get("trialStartDate") or 0.0),
                "trial_end_date": float(data.get("trialEndDate") or 0.0),
            },
            raw=response,
        )

    def retrieve_token_pack_checkout(self, *, token: str, reference_id: str = "") -> ProviderCompletion:
        normalized_token = str(token or "").strip()
        if not normalized_token:
            raise RuntimeError("iyzico_checkout_token_required")
        if not self._real_api_enabled():
            return ProviderCompletion(
                provider=self.provider_name,
                mode="token_pack",
                reference_id=str(reference_id or "").strip(),
                status="pending",
                provider_token=normalized_token,
                raw={"token": normalized_token},
            )
        payload = {
            "locale": self._locale(),
            "token": normalized_token,
        }
        if str(reference_id or "").strip():
            payload["conversationId"] = str(reference_id or "").strip()
        response = self._request("POST", "/payment/iyzipos/checkoutform/auth/ecom/detail", body=payload)
        payment_status = self._normalize_status(response.get("paymentStatus") or response.get("status"))
        completed_at = float(response.get("systemTime") or 0.0) / 1000 if response.get("systemTime") else 0.0
        return ProviderCompletion(
            provider=self.provider_name,
            mode="token_pack",
            reference_id=str(reference_id or response.get("conversationId") or "").strip(),
            status=payment_status or "pending",
            provider_token=str(response.get("token") or normalized_token).strip(),
            provider_payment_id=str(response.get("paymentId") or "").strip(),
            event_type="checkout.retrieve",
            completed_at=completed_at,
            metadata={
                "price": float(response.get("price") or 0.0),
                "paid_price": float(response.get("paidPrice") or 0.0),
                "currency": str(response.get("currency") or self._currency()).strip(),
                "payment_status": str(response.get("paymentStatus") or "").strip(),
                "fraud_status": int(response.get("fraudStatus") or 0),
            },
            raw=response,
        )

    def _validate_fallback_webhook(self, payload: bytes, headers: dict[str, str], body: dict[str, Any]) -> ProviderCompletion:
        secret = self._webhook_secret()
        signature = str(headers.get("x-iyzico-signature") or headers.get("x-iyzi-signature") or "").strip()
        if secret:
            digest = hmac.HMAC(
                key=secret.encode("utf-8"),
                msg=payload,
                digestmod=hashlib.sha256,
            ).hexdigest()
            if not signature or not hmac.compare_digest(signature, digest):
                raise RuntimeError("iyzico_webhook_signature_invalid")
        event_type = str(body.get("event_type") or body.get("type") or "payment.updated").strip().lower()
        metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
        workspace_id = str(body.get("workspace_id") or metadata.get("workspace_id") or "local-workspace").strip() or "local-workspace"
        plan_id = str(body.get("plan_id") or metadata.get("plan_id") or "").strip().lower()
        token_pack_id = str(body.get("token_pack_id") or metadata.get("token_pack_id") or "").strip().lower()
        status = str(body.get("status") or body.get("payment_status") or "pending").strip().lower()
        credits = int(body.get("credits") or metadata.get("credits") or 0)
        return ProviderCompletion(
            provider=self.provider_name,
            mode="subscription" if plan_id else "token_pack" if token_pack_id else "unknown",
            reference_id=str(body.get("reference_id") or metadata.get("reference_id") or ""),
            workspace_id=workspace_id,
            catalog_id=plan_id or token_pack_id,
            status=status,
            credits=max(0, credits),
            event_type=event_type,
            raw=body,
        )

    def _validate_webhook_signature_v3(self, body: dict[str, Any], signature: str) -> None:
        expected = self._webhook_signature_v3(body)
        if not signature or not hmac.compare_digest(signature.strip().lower(), expected.lower()):
            raise RuntimeError("iyzico_webhook_signature_invalid")

    def _webhook_signature_v3(self, body: dict[str, Any]) -> str:
        secret = self._secret_key()
        if not secret:
            raise RuntimeError("iyzico_config_missing:IYZICO_SECRET_KEY")
        if body.get("subscriptionReferenceCode") or str(body.get("iyziEventType") or "").strip().lower().startswith("subscription."):
            message = (
                f"{secret}"
                f"{str(body.get('merchantId') or self._merchant_id()).strip()}"
                f"{str(body.get('iyziEventType') or '').strip()}"
                f"{str(body.get('subscriptionReferenceCode') or '').strip()}"
                f"{str(body.get('orderReferenceCode') or '').strip()}"
                f"{str(body.get('customerReferenceCode') or '').strip()}"
            )
        elif body.get("token") is not None:
            message = (
                f"{secret}"
                f"{str(body.get('iyziEventType') or '').strip()}"
                f"{str(body.get('iyziPaymentId') or '').strip()}"
                f"{str(body.get('token') or '').strip()}"
                f"{str(body.get('paymentConversationId') or '').strip()}"
                f"{str(body.get('status') or '').strip()}"
            )
        else:
            message = (
                f"{secret}"
                f"{str(body.get('iyziEventType') or '').strip()}"
                f"{str(body.get('paymentId') or body.get('iyziPaymentId') or '').strip()}"
                f"{str(body.get('paymentConversationId') or '').strip()}"
                f"{str(body.get('status') or '').strip()}"
            )
        return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()

    def handle_webhook(self, *, payload: bytes, headers: dict[str, str]) -> ProviderCompletion:
        body = json.loads(payload.decode("utf-8") or "{}")
        if not isinstance(body, dict):
            raise RuntimeError("iyzico_webhook_invalid_payload")
        normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
        if not self._real_api_enabled():
            return self._validate_fallback_webhook(payload, normalized_headers, body)

        signature = str(normalized_headers.get("x-iyz-signature-v3") or normalized_headers.get("x-iyz-signature") or "").strip()
        self._validate_webhook_signature_v3(body, signature)

        iyzi_event_type = str(body.get("iyziEventType") or body.get("eventType") or "").strip().lower()
        if body.get("subscriptionReferenceCode") or iyzi_event_type.startswith("subscription."):
            return ProviderCompletion(
                provider=self.provider_name,
                mode="subscription",
                reference_id="",
                status=iyzi_event_type.split(".")[-1] if iyzi_event_type else "pending",
                provider_payment_id=str(body.get("orderReferenceCode") or body.get("iyziReferenceCode") or "").strip(),
                subscription_reference_code=str(body.get("subscriptionReferenceCode") or "").strip(),
                customer_reference_code=str(body.get("customerReferenceCode") or "").strip(),
                order_reference_code=str(body.get("orderReferenceCode") or "").strip(),
                event_type=iyzi_event_type or "subscription.updated",
                completed_at=float(body.get("iyziEventTime") or 0.0) / 1000 if body.get("iyziEventTime") else 0.0,
                raw=body,
            )

        return ProviderCompletion(
            provider=self.provider_name,
            mode="token_pack",
            reference_id=str(body.get("paymentConversationId") or "").strip(),
            status=self._normalize_status(body.get("status")) or "pending",
            provider_token=str(body.get("token") or "").strip(),
            provider_payment_id=str(body.get("iyziPaymentId") or body.get("paymentId") or "").strip(),
            event_type=iyzi_event_type or "payment.updated",
            completed_at=float(body.get("iyziEventTime") or 0.0) / 1000 if body.get("iyziEventTime") else 0.0,
            raw=body,
        )


__all__ = ["IyzicoProvider"]
