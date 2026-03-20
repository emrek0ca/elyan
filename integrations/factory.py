from __future__ import annotations

from typing import Any

from .base import AuthStrategy, BaseConnector, IntegrationCapability, IntegrationType, OAuthAccount, Platform, normalize_platform


class ConnectorFactory:
    def get(
        self,
        integration_type: IntegrationType | str,
        platform: Platform | str | None = None,
        auth_state: dict[str, Any] | OAuthAccount | None = None,
    ) -> BaseConnector:
        itype = integration_type if isinstance(integration_type, IntegrationType) else IntegrationType(str(integration_type or "unknown").strip().lower() or "unknown")
        auth_payload = auth_state.model_dump() if isinstance(auth_state, OAuthAccount) else dict(auth_state or {})
        capability = auth_payload.get("capability")
        if isinstance(capability, dict):
            cap = IntegrationCapability.model_validate(capability)
        elif isinstance(capability, IntegrationCapability):
            cap = capability
        else:
            cap = IntegrationCapability()
        account = auth_payload.get("auth_account") or auth_payload.get("oauth_account")
        if isinstance(account, dict):
            oauth_account = OAuthAccount.model_validate(account)
        elif isinstance(account, OAuthAccount):
            oauth_account = account
        else:
            oauth_account = OAuthAccount()
        provider = str(auth_payload.get("provider") or cap.provider or oauth_account.provider or "").strip().lower()
        connector_name = str(auth_payload.get("connector_name") or cap.connector_name or provider or itype.value).strip().lower()
        platform_value = normalize_platform(platform)

        if itype == IntegrationType.DESKTOP:
            from .connectors.desktop import DesktopConnector

            return DesktopConnector(capability=cap, auth_account=oauth_account, platform=platform_value, provider=provider, connector_name=connector_name)
        if itype == IntegrationType.BROWSER:
            from .connectors.browser import BrowserConnector

            return BrowserConnector(capability=cap, auth_account=oauth_account, platform=platform_value, provider=provider, connector_name=connector_name)
        if itype == IntegrationType.EMAIL:
            from .connectors.email import EmailConnector

            return EmailConnector(capability=cap, auth_account=oauth_account, platform=platform_value, provider=provider, connector_name=connector_name)
        if itype == IntegrationType.SOCIAL:
            from .connectors.social import SocialConnector

            return SocialConnector(capability=cap, auth_account=oauth_account, platform=platform_value, provider=provider, connector_name=connector_name)
        if itype == IntegrationType.SCHEDULER:
            from .connectors.scheduler import SchedulerConnector

            return SchedulerConnector(capability=cap, auth_account=oauth_account, platform=platform_value, provider=provider, connector_name=connector_name)
        if itype == IntegrationType.API:
            if provider in {"google", "gmail", "calendar", "drive", "workspace"}:
                from .connectors.google import GoogleConnector

                return GoogleConnector(capability=cap, auth_account=oauth_account, platform=platform_value, provider=provider or "google", connector_name=connector_name or "google")
            from .connectors.browser import BrowserConnector

            return BrowserConnector(capability=cap, auth_account=oauth_account, platform=platform_value, provider=provider or "web", connector_name=connector_name or "browser")

        from .connectors.browser import BrowserConnector

        return BrowserConnector(capability=cap, auth_account=oauth_account, platform=platform_value, provider=provider or "browser", connector_name=connector_name or "browser")


connector_factory = ConnectorFactory()

