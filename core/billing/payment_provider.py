from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class BillingProfile:
    full_name: str
    email: str
    phone: str
    identity_number: str
    address_line1: str
    city: str
    zip_code: str
    country: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CheckoutRequest:
    workspace_id: str
    external_reference: str
    customer_email: str = ""
    success_url: str = ""
    cancel_url: str = ""
    callback_url: str = ""
    billing_profile: BillingProfile | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CheckoutSession:
    provider: str
    mode: str
    launch_url: str
    reference_id: str
    status: str = "pending"
    payment_page_url: str = ""
    callback_url: str = ""
    provider_token: str = ""
    provider_payment_id: str = ""
    subscription_reference_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.payment_page_url:
            self.payment_page_url = self.launch_url
        if not self.launch_url:
            self.launch_url = self.payment_page_url

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProviderCompletion:
    provider: str
    mode: str
    reference_id: str
    status: str = "pending"
    workspace_id: str = ""
    catalog_id: str = ""
    provider_token: str = ""
    provider_payment_id: str = ""
    subscription_reference_code: str = ""
    customer_reference_code: str = ""
    order_reference_code: str = ""
    event_type: str = ""
    credits: int = 0
    completed_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PaymentProvider(ABC):
    provider_name = "unknown"

    @abstractmethod
    def create_subscription_checkout(self, *, plan_id: str, request: CheckoutRequest) -> CheckoutSession:
        raise RuntimeError("subscription checkout is not supported")

    @abstractmethod
    def create_token_pack_checkout(self, *, pack_id: str, request: CheckoutRequest) -> CheckoutSession:
        raise RuntimeError("token pack checkout is not supported")

    @abstractmethod
    def retrieve_subscription_checkout(self, *, token: str, reference_id: str = "") -> ProviderCompletion:
        raise RuntimeError("subscription checkout retrieval is not supported")

    @abstractmethod
    def retrieve_token_pack_checkout(self, *, token: str, reference_id: str = "") -> ProviderCompletion:
        raise RuntimeError("token pack checkout retrieval is not supported")

    @abstractmethod
    def handle_webhook(self, *, payload: bytes, headers: dict[str, str]) -> ProviderCompletion:
        raise RuntimeError("webhooks are not supported")


__all__ = [
    "BillingProfile",
    "CheckoutRequest",
    "CheckoutSession",
    "PaymentProvider",
    "ProviderCompletion",
]
