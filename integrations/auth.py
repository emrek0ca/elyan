from __future__ import annotations

import json
import time
from typing import Any, Iterable
from urllib.parse import urlparse

import requests

from config.elyan_config import elyan_config
from core.security.secure_vault import SecureVault
from utils.logger import get_logger

from .base import AuthStrategy, ConnectorState, FallbackPolicy, OAuthAccount, normalize_items


logger = get_logger("integrations.oauth")


def _provider_key(provider: str, account_alias: str = "default") -> str:
    return f"oauth_accounts::{str(provider or '').strip().lower()}::{str(account_alias or 'default').strip().lower()}"


def _default_redirect_uri(provider: str) -> str:
    provider = str(provider or "").strip().lower()
    if provider in {"google", "gmail", "calendar", "drive", "workspace"}:
        return "http://localhost:8765/callback"
    if provider in {"x", "instagram", "whatsapp"}:
        return "http://localhost:8765/callback"
    return "http://localhost:8765/callback"


def _default_auth_url(provider: str) -> str:
    provider = str(provider or "").strip().lower()
    defaults = {
        "google": "https://accounts.google.com/signin/v2/identifier",
        "gmail": "https://accounts.google.com/signin/v2/identifier",
        "calendar": "https://accounts.google.com/signin/v2/identifier",
        "drive": "https://accounts.google.com/signin/v2/identifier",
        "workspace": "https://accounts.google.com/signin/v2/identifier",
        "x": "https://x.com/i/flow/login",
        "instagram": "https://www.instagram.com/accounts/login/",
        "whatsapp": "https://web.whatsapp.com/",
        "email": "https://mail.google.com/",
    }
    return defaults.get(provider, "")


class OAuthBroker:
    """
    Provider-agnostic OAuth broker with encrypted persistence.

    It prefers stored refresh/access tokens, falls back to web/device login,
    and keeps the token payload out of prompts by only exposing public dumps.
    """

    def __init__(self, vault: SecureVault | None = None) -> None:
        self.vault = vault or SecureVault()
        try:
            self.vault.unlock()
        except Exception:
            # Locked vault still allows pure read/write in tests only if unlocked later.
            pass

    def provider_config(self, provider: str) -> dict[str, Any]:
        raw = elyan_config.get(f"oauth.providers.{str(provider or '').strip().lower()}", {})
        return dict(raw or {}) if isinstance(raw, dict) else {}

    def _load_account(self, provider: str, account_alias: str = "default") -> OAuthAccount | None:
        key = _provider_key(provider, account_alias)
        try:
            raw = self.vault.get_secret(key, "")
        except Exception:
            raw = ""
        if not raw:
            return None
        try:
            return OAuthAccount.model_validate(json.loads(raw))
        except Exception:
            return None

    def _save_account(self, account: OAuthAccount) -> OAuthAccount:
        key = _provider_key(account.provider, account.account_alias)
        payload = json.dumps(account.model_dump(), ensure_ascii=False)
        try:
            self.vault.store_secret(key, payload)
        except Exception as exc:
                logger.warning("oauth_account_persistence_failed", extra={"provider": account.provider, "alias": account.account_alias, "error": str(exc)})
        try:
            from core.integration_trace import get_integration_trace_store

            get_integration_trace_store().record_trace(
                operation="oauth_store",
                provider=account.provider,
                connector_name=f"{account.provider}_oauth",
                integration_type="api" if account.provider else "",
                status=str(account.status),
                success=account.is_ready,
                auth_state=str(account.status),
                auth_strategy=str(account.auth_strategy),
                account_alias=account.account_alias,
                fallback_used=account.fallback_mode != FallbackPolicy.AUTO,
                fallback_reason=str(account.fallback_mode.value if hasattr(account.fallback_mode, "value") else account.fallback_mode),
                metadata={
                    "email": account.email,
                    "display_name": account.display_name,
                    "granted_scopes": list(account.granted_scopes or []),
                },
            )
        except Exception:
            pass
        return account

    def delete_account(self, provider: str, account_alias: str = "default") -> bool:
        key = _provider_key(provider, account_alias)
        try:
            self.vault.delete_secret(key)
            try:
                from core.integration_trace import get_integration_trace_store

                get_integration_trace_store().record_trace(
                    operation="oauth_revoke",
                    provider=str(provider or "").strip().lower(),
                    connector_name=f"{str(provider or '').strip().lower()}_oauth",
                    integration_type="api" if str(provider or "").strip() else "",
                    status="revoked",
                    success=True,
                    auth_state="revoked",
                    account_alias=str(account_alias or "default"),
                    metadata={"revoke": True},
                )
            except Exception:
                pass
            return True
        except Exception:
            return False

    def list_accounts(self, provider: str | None = None) -> list[OAuthAccount]:
        prefix = f"oauth_accounts::{str(provider or '').strip().lower()}::" if provider else "oauth_accounts::"
        accounts: list[OAuthAccount] = []
        try:
            for key in self.vault.list_keys():
                if not str(key or "").startswith(prefix):
                    continue
                raw = self.vault.get_secret(key, "")
                if not raw:
                    continue
                try:
                    accounts.append(OAuthAccount.model_validate(json.loads(raw)))
                except Exception:
                    continue
        except Exception:
            return []
        return accounts

    def _can_refresh(self, config: dict[str, Any]) -> bool:
        return bool(config.get("client_id") and config.get("client_secret") and config.get("token_url"))

    def _refresh_account(self, account: OAuthAccount, config: dict[str, Any]) -> OAuthAccount | None:
        if not account.refresh_token or not self._can_refresh(config):
            return None
        try:
            resp = requests.post(
                str(config.get("token_url") or ""),
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": account.refresh_token,
                    "client_id": config.get("client_id"),
                    "client_secret": config.get("client_secret"),
                    "scope": " ".join(account.granted_scopes),
                },
                timeout=float(config.get("timeout_s", 15) or 15),
            )
            if resp.status_code >= 400:
                return None
            token = resp.json()
        except Exception:
            return None
        account.access_token = str(token.get("access_token") or account.access_token or "")
        account.refresh_token = str(token.get("refresh_token") or account.refresh_token or "")
        account.token_type = str(token.get("token_type") or account.token_type or "Bearer")
        expires_in = token.get("expires_in")
        if isinstance(expires_in, (int, float)):
            account.expires_at = time.time() + float(expires_in)
        account.last_auth_at = time.time()
        account.status = ConnectorState.READY
        return self._save_account(account)

    def _exchange_code(
        self,
        provider: str,
        config: dict[str, Any],
        *,
        scopes: list[str],
        account_alias: str,
        authorization_code: str,
        redirect_uri: str = "",
        extra: dict[str, Any] | None = None,
    ) -> OAuthAccount | None:
        if not authorization_code or not self._can_refresh(config):
            return None
        try:
            resp = requests.post(
                str(config.get("token_url") or ""),
                data={
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": redirect_uri or config.get("redirect_uri") or _default_redirect_uri(provider),
                    "client_id": config.get("client_id"),
                    "client_secret": config.get("client_secret"),
                },
                timeout=float(config.get("timeout_s", 15) or 15),
            )
            if resp.status_code >= 400:
                return None
            token = resp.json()
        except Exception:
            return None
        account = OAuthAccount(
            provider=provider,
            account_alias=account_alias,
            display_name=str((extra or {}).get("display_name") or config.get("display_name") or provider).strip(),
            email=str((extra or {}).get("email") or config.get("email") or "").strip(),
            auth_strategy=AuthStrategy.OAUTH,
            fallback_mode=FallbackPolicy.WEB if str(config.get("fallback_policy") or "web").lower() == "web" else FallbackPolicy.AUTO,
            granted_scopes=normalize_items(scopes),
            access_token=str(token.get("access_token") or ""),
            refresh_token=str(token.get("refresh_token") or ""),
            token_type=str(token.get("token_type") or "Bearer"),
            expires_at=time.time() + float(token.get("expires_in") or 3600),
            last_auth_at=time.time(),
            status=ConnectorState.READY,
            auth_url=str(config.get("auth_url") or ""),
            redirect_uri=str(redirect_uri or config.get("redirect_uri") or ""),
            metadata=dict(extra or {}),
        )
        return self._save_account(account)

    def _build_needs_input_account(
        self,
        provider: str,
        *,
        scopes: list[str],
        account_alias: str,
        config: dict[str, Any],
        mode: str,
        extra: dict[str, Any] | None = None,
    ) -> OAuthAccount:
        auth_url = str(config.get("auth_url") or "").strip()
        if not auth_url and provider:
            auth_url = _default_auth_url(provider) or f"https://{provider}.com/"
        redirect_uri = str(config.get("redirect_uri") or _default_redirect_uri(provider) or "").strip()
        return OAuthAccount(
            provider=provider,
            account_alias=account_alias,
            display_name=str((extra or {}).get("display_name") or config.get("display_name") or provider).strip(),
            email=str((extra or {}).get("email") or config.get("email") or "").strip(),
            auth_strategy=AuthStrategy(str(config.get("auth_strategy") or "oauth").strip().lower() or "oauth"),
            fallback_mode=FallbackPolicy(str(config.get("fallback_policy") or mode or "web").strip().lower() or "web"),
            granted_scopes=normalize_items(scopes),
            auth_url=auth_url,
            redirect_uri=redirect_uri,
            status=ConnectorState.NEEDS_INPUT,
            metadata={
                **dict(extra or {}),
                "mode": mode,
                "needs_input": True,
            },
        )

    def authorize(
        self,
        provider: str,
        scopes: Iterable[str] | None = None,
        mode: str = "auto",
        *,
        account_alias: str = "default",
        authorization_code: str = "",
        redirect_uri: str = "",
        extra: dict[str, Any] | None = None,
    ) -> OAuthAccount:
        provider = str(provider or "").strip().lower()
        scope_list = normalize_items(scopes or [])
        config = self.provider_config(provider)
        existing = self._load_account(provider, account_alias=account_alias)
        if existing and existing.is_ready:
            granted = set(existing.granted_scopes or [])
            if not scope_list or set(scope_list).issubset(granted):
                if existing.expires_at and existing.expires_at <= time.time() and existing.refresh_token:
                    refreshed = self._refresh_account(existing, config)
                    if refreshed:
                        return refreshed
                return existing

        if authorization_code:
            exchanged = self._exchange_code(
                provider,
                config,
                scopes=scope_list,
                account_alias=account_alias,
                authorization_code=authorization_code,
                redirect_uri=redirect_uri,
                extra=extra,
            )
            if exchanged:
                return exchanged

        if existing and existing.refresh_token:
            refreshed = self._refresh_account(existing, config)
            if refreshed:
                return refreshed

        account = self._build_needs_input_account(
            provider,
            scopes=scope_list,
            account_alias=account_alias,
            config=config,
            mode=mode,
            extra=extra,
        )
        if str(config.get("fallback_policy") or "").strip().lower() == "web":
            account.fallback_mode = FallbackPolicy.WEB
        elif str(config.get("fallback_policy") or "").strip().lower() == "native":
            account.fallback_mode = FallbackPolicy.NATIVE
        try:
            from core.integration_trace import get_integration_trace_store

            get_integration_trace_store().record_trace(
                operation="oauth_needs_input",
                provider=provider,
                connector_name=f"{provider}_oauth",
                integration_type="api" if provider else "",
                status=str(account.status),
                success=False,
                auth_state=str(account.status),
                auth_strategy=str(account.auth_strategy),
                account_alias=account_alias,
                fallback_used=True,
                fallback_reason=str(account.fallback_mode.value if hasattr(account.fallback_mode, "value") else account.fallback_mode),
                metadata={
                    "auth_url": account.auth_url,
                    "redirect_uri": account.redirect_uri,
                    "granted_scopes": list(account.granted_scopes or []),
                    "needs_input": True,
                },
            )
        except Exception:
            pass
        return self._save_account(account)


oauth_broker = OAuthBroker()
