from __future__ import annotations

import time
from typing import Any

import requests

from ..auth import oauth_broker
from ..base import BaseConnector, ConnectorResult, ConnectorSnapshot, ConnectorState


_SOCIAL_START_URLS = {
    "x": "https://x.com/home",
    "twitter": "https://x.com/home",
    "instagram": "https://www.instagram.com/",
    "whatsapp": "https://web.whatsapp.com/",
}


class SocialConnector(BaseConnector):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._browser = None
        self._target_url = _SOCIAL_START_URLS.get(self.provider, "")

    def _browser_connector(self):
        if self._browser is None:
            from .browser import BrowserConnector

            self._browser = BrowserConnector(
                capability=self.capability,
                auth_account=self.auth_account,
                platform=self.platform,
                provider=self.provider or "browser",
                connector_name=self.connector_name or "browser",
                metadata={"profile_id": f"{self.provider or 'social'}-default"},
            )
        return self._browser

    def _api_base_url(self) -> str:
        cfg = oauth_broker.provider_config(self.provider)
        for key in ("api_base_url", "api_url", "base_url"):
            value = str(cfg.get(key) or "").strip()
            if value:
                return value.rstrip("/")
        return ""

    def _api_headers(self) -> dict[str, str]:
        token = str(getattr(self.auth_account, "access_token", "") or "").strip()
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _api_execute(self, payload: dict[str, Any], started: float) -> ConnectorResult | None:
        if not (self.auth_account and self.auth_account.is_ready):
            return None
        base_url = self._api_base_url()
        if not base_url:
            return None
        endpoint = str(payload.get("endpoint") or payload.get("path") or "").strip()
        if not endpoint:
            return None
        url = f"{base_url}/{endpoint.lstrip('/')}"
        method = str(payload.get("method") or "GET").strip().upper()
        try:
            response = requests.request(
                method,
                url,
                json=payload.get("json") or payload.get("body"),
                data=payload.get("data"),
                params=payload.get("params") or {},
                headers=self._api_headers(),
                timeout=float(payload.get("timeout", 20) or 20),
            )
            response.raise_for_status()
            try:
                data = response.json()
            except Exception:
                data = {"text": response.text}
        except Exception as exc:
            return self._result(
                success=False,
                status="failed",
                error=str(exc),
                message=str(exc),
                retryable=True,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                metadata={"api_base_url": base_url, "endpoint": endpoint},
            )
        try:
            snapshot = await self.snapshot()
        except Exception:
            snapshot = self._snapshot(
                state="ready",
                target=endpoint,
                url=base_url,
                metadata={"api_base_url": base_url, "endpoint": endpoint},
            )
        return self._result(
            success=True,
            status="success",
            message="social_api_success",
            latency_ms=(time.perf_counter() - started) * 1000.0,
            snapshot=snapshot,
            result=data if isinstance(data, dict) else {"data": data},
            evidence=[{"kind": "social_api", "endpoint": endpoint, "method": method}],
            auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
            metadata={"api_base_url": base_url, "endpoint": endpoint},
        )

    async def connect(self, app_name_or_url: str, **kwargs: Any) -> ConnectorResult:
        started = time.perf_counter()
        target = str(app_name_or_url or self._target_url or "").strip()
        if not target:
            target = self._target_url
        provider = str(self.provider or "").strip().lower()
        if provider:
            account = oauth_broker.authorize(
                provider,
                self.capability.required_scopes or [f"{provider}.read", f"{provider}.write"],
                mode=str(kwargs.get("mode") or "auto"),
                account_alias=str(getattr(self.auth_account, "account_alias", "default") or "default"),
            )
            self.auth_account = account
            if account.is_ready and self._api_base_url():
                try:
                    snapshot = await self.snapshot()
                except Exception:
                    snapshot = self._snapshot(
                        state="ready",
                        target=target,
                        url=self._api_base_url(),
                        metadata={"api_base_url": self._api_base_url()},
                    )
                return self._result(
                    success=True,
                    status="ready",
                    message=f"{provider}_api_ready",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    snapshot=snapshot,
                    auth_state=account.status,
                )
        browser = self._browser_connector()
        result = await browser.connect(target, **kwargs)
        data = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        data["fallback_used"] = True
        data["fallback_reason"] = "social_web_fallback"
        data["latency_ms"] = float((time.perf_counter() - started) * 1000.0)
        return ConnectorResult.model_validate({
            **data,
            "connector_name": self.connector_name,
            "provider": self.provider,
            "integration_type": self.capability.integration_type,
            "platform": self.platform,
            "auth_state": self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
            "fallback_used": True,
            "fallback_reason": "social_web_fallback",
            "latency_ms": float((time.perf_counter() - started) * 1000.0),
        })

    async def execute(self, action: dict[str, Any]) -> ConnectorResult:
        started = time.perf_counter()
        payload = dict(action or {})
        api_result = await self._api_execute(payload, started)
        if api_result is not None and api_result.success:
            return api_result
        browser = self._browser_connector()
        result = await browser.execute(payload)
        data = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        data["fallback_used"] = True
        data["fallback_reason"] = "social_web_fallback"
        data["latency_ms"] = float((time.perf_counter() - started) * 1000.0)
        return ConnectorResult.model_validate({
            **data,
            "connector_name": self.connector_name,
            "provider": self.provider,
            "integration_type": self.capability.integration_type,
            "platform": self.platform,
            "auth_state": self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
            "fallback_used": True,
            "fallback_reason": "social_web_fallback",
            "latency_ms": float((time.perf_counter() - started) * 1000.0),
        })

    async def snapshot(self) -> ConnectorSnapshot:
        if self.auth_account and self.auth_account.is_ready and self._api_base_url():
            return self._snapshot(
                state="ready",
                target=self._target_url,
                url=self._api_base_url(),
                metadata={
                    "social_provider": self.provider,
                    "api_base_url": self._api_base_url(),
                    "auth_state": str(self.auth_account.status),
                },
            )
        browser = self._browser_connector()
        snap = await browser.snapshot()
        payload = snap.model_dump() if hasattr(snap, "model_dump") else dict(snap)
        payload.setdefault("metadata", {})
        payload["metadata"]["social_provider"] = self.provider
        payload["metadata"]["api_base_url"] = self._api_base_url()
        return ConnectorSnapshot.model_validate(payload)
