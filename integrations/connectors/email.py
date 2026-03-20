from __future__ import annotations

import time
from typing import Any

from tools.email_tools import get_email_manager

from ..auth import oauth_broker
from ..base import BaseConnector, ConnectorResult, ConnectorSnapshot, ConnectorState


class EmailConnector(BaseConnector):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._email_manager = get_email_manager()
        self._google_fallback = None

    def _ready_via_env(self) -> bool:
        return bool(getattr(self._email_manager, "email_address", "") and getattr(self._email_manager, "email_password", ""))

    async def connect(self, app_name_or_url: str, **kwargs: Any) -> ConnectorResult:
        started = time.perf_counter()
        if self._ready_via_env():
            snapshot = await self.snapshot()
            return self._result(
                success=True,
                status="ready",
                message="email_ready",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                snapshot=snapshot,
                auth_state=ConnectorState.READY,
            )
        provider = str(getattr(self.auth_account, "provider", "") or self.provider or "").lower()
        if provider == "google":
            account = oauth_broker.authorize(
                "google",
                self.capability.required_scopes or ["email.read"],
                mode=str(kwargs.get("mode") or "auto"),
                account_alias=str(getattr(self.auth_account, "account_alias", "default") or "default"),
            )
            self.auth_account = account
            if account.is_ready:
                snapshot = await self.snapshot()
                return self._result(
                    success=True,
                    status="ready",
                    message="email_google_ready",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    snapshot=snapshot,
                    auth_state=account.status,
                )
            return self._result(
                success=False,
                status="needs_input",
                message="oauth_required",
                fallback_used=True,
                fallback_reason="oauth_required",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                auth_state=account.status,
                metadata={"auth_url": account.auth_url, "fallback_mode": account.fallback_mode.value if hasattr(account.fallback_mode, "value") else str(account.fallback_mode)},
            )
        return self._result(
            success=False,
            status="needs_input",
            message="email_credentials_required",
            fallback_used=True,
            fallback_reason="email_credentials_required",
            latency_ms=(time.perf_counter() - started) * 1000.0,
            auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
        )

    async def execute(self, action: dict[str, Any]) -> ConnectorResult:
        started = time.perf_counter()
        payload = dict(action or {})
        kind = str(payload.get("kind") or payload.get("action") or "").strip().lower()
        provider = str(getattr(self.auth_account, "provider", "") or self.provider or "").lower()
        if provider == "google" and not self._ready_via_env():
            account = oauth_broker.authorize(
                "google",
                self.capability.required_scopes or ["email.read"],
                mode=str(payload.get("mode") or "auto"),
                account_alias=str(getattr(self.auth_account, "account_alias", "default") or "default"),
            )
            self.auth_account = account
            if not account.is_ready:
                return self._result(
                    success=False,
                    status="needs_input",
                    message="oauth_required",
                    fallback_used=True,
                    fallback_reason="oauth_required",
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    auth_state=account.status,
                    metadata={"auth_url": account.auth_url, "fallback_mode": account.fallback_mode.value if hasattr(account.fallback_mode, "value") else str(account.fallback_mode)},
                )
            return await self._google_fallback_action(payload, started)

        if kind in {"send_email", "email_send", "draft_email"}:
            result = await self._email_manager.send_email(
                to=str(payload.get("to") or payload.get("recipient") or ""),
                subject=str(payload.get("subject") or ""),
                body=str(payload.get("body") or payload.get("text") or ""),
                cc=list(payload.get("cc") or []),
                bcc=list(payload.get("bcc") or []),
            )
        elif kind in {"read_email", "get_emails", "inbox"}:
            result = await self._email_manager.get_emails(
                folder=str(payload.get("folder") or "INBOX"),
                limit=int(payload.get("limit", 10) or 10),
                search_query=str(payload.get("query") or payload.get("search_query") or "") or None,
            )
        elif kind in {"search_email", "search_emails"}:
            result = await self._email_manager.search_emails(
                query=str(payload.get("query") or payload.get("text") or ""),
                folder=str(payload.get("folder") or "INBOX"),
                limit=int(payload.get("limit", 10) or 10),
            )
        elif kind in {"unread_count", "count_unread"}:
            result = await self._email_manager.get_unread_count()
        else:
            result = await self._email_manager.get_emails(limit=int(payload.get("limit", 10) or 10))

        snapshot = await self.snapshot()
        success = bool(result.get("success", result.get("status") in {"success", "ok"}))
        return self._result(
            success=success,
            status=str(result.get("status") or ("success" if success else "failed")),
            message=str(result.get("message") or ""),
            error=str(result.get("error") or ""),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            snapshot=snapshot,
            result=dict(result),
            evidence=list(result.get("artifacts") or []),
            artifacts=list(result.get("artifacts") or []),
            auth_state=ConnectorState.READY if success else (self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT),
        )

    async def _google_fallback_action(self, payload: dict[str, Any], started: float) -> ConnectorResult:
        from .google import GoogleConnector

        if self._google_fallback is None:
            self._google_fallback = GoogleConnector(
                capability=self.capability,
                auth_account=self.auth_account,
                platform=self.platform,
                provider="google",
                connector_name="google",
            )
        result = await self._google_fallback.execute(payload)
        data = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        data["fallback_used"] = True
        data["fallback_reason"] = "email_google_api_fallback"
        data["latency_ms"] = float((time.perf_counter() - started) * 1000.0)
        return ConnectorResult.model_validate({
            **data,
            "connector_name": self.connector_name,
            "provider": self.provider,
            "integration_type": self.capability.integration_type,
            "platform": self.platform,
            "auth_state": self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
            "fallback_used": True,
            "fallback_reason": "email_google_api_fallback",
            "latency_ms": float((time.perf_counter() - started) * 1000.0),
        })

    async def snapshot(self) -> ConnectorSnapshot:
        provider = str(getattr(self.auth_account, "provider", "") or self.provider or "").lower()
        ready = self._ready_via_env() or (provider == "google" and bool(self.auth_account and self.auth_account.is_ready))
        return self._snapshot(
            state="ready" if ready else "needs_input",
            metadata={
                "email_address": getattr(self._email_manager, "email_address", ""),
                "imap_server": getattr(self._email_manager, "imap_server", ""),
                "smtp_server": getattr(self._email_manager, "smtp_server", ""),
                "google_fallback": bool(provider == "google"),
            },
            auth_state=ConnectorState.READY if ready else (self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT),
        )
