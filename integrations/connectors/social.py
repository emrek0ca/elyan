from __future__ import annotations

import time
from typing import Any

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

    async def connect(self, app_name_or_url: str, **kwargs: Any) -> ConnectorResult:
        started = time.perf_counter()
        target = str(app_name_or_url or self._target_url or "").strip()
        if not target:
            target = self._target_url
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
        browser = self._browser_connector()
        payload = dict(action or {})
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
        browser = self._browser_connector()
        snap = await browser.snapshot()
        payload = snap.model_dump() if hasattr(snap, "model_dump") else dict(snap)
        payload.setdefault("metadata", {})
        payload["metadata"]["social_provider"] = self.provider
        return ConnectorSnapshot.model_validate(payload)

