"""
Integration Hub for External Services
Unified framework for third-party integrations
"""

import asyncio
import aiohttp
import json
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from utils.logger import get_logger
from config.settings import HOME_DIR

logger = get_logger("integration_hub")


class IntegrationType(Enum):
    """Supported integration types"""
    SLACK = "slack"
    DISCORD = "discord"
    EMAIL = "email"
    CALENDAR = "calendar"
    CLOUD_STORAGE = "cloud_storage"
    WEBHOOK = "webhook"
    CUSTOM_API = "custom_api"


class IntegrationStatus(Enum):
    """Integration connection status"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass
class Integration:
    """Integration configuration"""
    integration_id: str
    name: str
    type: IntegrationType
    credentials: Dict[str, Any]
    config: Dict[str, Any]
    status: IntegrationStatus
    last_used: Optional[float] = None
    error: Optional[str] = None


class IntegrationHub:
    """
    Integration Hub for External Services
    - Slack messaging
    - Discord integration
    - Email sending
    - Calendar management
    - Cloud storage
    - Webhook endpoints
    - Custom API integrations
    """

    def __init__(self):
        self.integrations: Dict[str, Integration] = {}
        self.credentials_file = HOME_DIR / ".elyan" / "integrations.json"

        # Load saved integrations
        self._load_integrations()

        logger.info("Integration Hub initialized")

    def register_integration(
        self,
        name: str,
        integration_type: IntegrationType,
        credentials: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None
    ) -> str:
        """Register a new integration"""
        import uuid
        integration_id = str(uuid.uuid4())[:8]

        integration = Integration(
            integration_id=integration_id,
            name=name,
            type=integration_type,
            credentials=credentials,
            config=config or {},
            status=IntegrationStatus.DISCONNECTED
        )

        self.integrations[integration_id] = integration
        self._save_integrations()

        logger.info(f"Registered integration: {name} ({integration_type.value})")
        return integration_id

    async def send_slack_message(
        self,
        integration_id: str,
        channel: str,
        message: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Send message to Slack"""
        integration = self.integrations.get(integration_id)

        if not integration or integration.type != IntegrationType.SLACK:
            return {"success": False, "error": "Invalid Slack integration"}

        webhook_url = integration.credentials.get("webhook_url")
        if not webhook_url:
            return {"success": False, "error": "Webhook URL not configured"}

        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "channel": channel,
                    "text": message,
                    **kwargs
                }

                async with session.post(webhook_url, json=payload) as response:
                    integration.last_used = time.time()
                    integration.status = IntegrationStatus.CONNECTED

                    if response.status == 200:
                        return {"success": True, "status": "sent"}
                    else:
                        error = await response.text()
                        return {"success": False, "error": error}

        except Exception as e:
            logger.error(f"Slack message error: {e}")
            integration.status = IntegrationStatus.ERROR
            integration.error = str(e)
            return {"success": False, "error": str(e)}

    async def send_discord_message(
        self,
        integration_id: str,
        message: str,
        embed: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Send message to Discord"""
        integration = self.integrations.get(integration_id)

        if not integration or integration.type != IntegrationType.DISCORD:
            return {"success": False, "error": "Invalid Discord integration"}

        webhook_url = integration.credentials.get("webhook_url")
        if not webhook_url:
            return {"success": False, "error": "Webhook URL not configured"}

        try:
            async with aiohttp.ClientSession() as session:
                payload = {"content": message}

                if embed:
                    payload["embeds"] = [embed]

                async with session.post(webhook_url, json=payload) as response:
                    integration.last_used = time.time()
                    integration.status = IntegrationStatus.CONNECTED

                    if response.status in [200, 204]:
                        return {"success": True, "status": "sent"}
                    else:
                        error = await response.text()
                        return {"success": False, "error": error}

        except Exception as e:
            logger.error(f"Discord message error: {e}")
            integration.status = IntegrationStatus.ERROR
            integration.error = str(e)
            return {"success": False, "error": str(e)}

    async def send_email(
        self,
        integration_id: str,
        to: str,
        subject: str,
        body: str,
        html: bool = False
    ) -> Dict[str, Any]:
        """Send email"""
        integration = self.integrations.get(integration_id)

        if not integration or integration.type != IntegrationType.EMAIL:
            return {"success": False, "error": "Invalid email integration"}
        try:
            from tools.email_tools import EmailManager

            manager = EmailManager()
            manager.smtp_server = str(integration.config.get("smtp_server") or integration.credentials.get("smtp_server") or manager.smtp_server)
            manager.smtp_port = int(integration.config.get("smtp_port") or integration.credentials.get("smtp_port") or manager.smtp_port)
            manager.imap_server = str(integration.config.get("imap_server") or integration.credentials.get("imap_server") or manager.imap_server)
            manager.email_address = str(integration.credentials.get("email_address") or integration.credentials.get("username") or integration.config.get("email_address") or manager.email_address)
            manager.email_password = str(integration.credentials.get("email_password") or integration.credentials.get("password") or integration.config.get("email_password") or manager.email_password)
            return await manager.send_email(to, subject, body, html=html)
        except Exception as e:
            logger.error(f"Email sending error: {e}")
            return {"success": False, "error": str(e)}

    async def create_calendar_event(
        self,
        integration_id: str,
        title: str,
        start_time: str,
        end_time: str,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create calendar event"""
        integration = self.integrations.get(integration_id)

        if not integration or integration.type != IntegrationType.CALENDAR:
            return {"success": False, "error": "Invalid calendar integration"}
        try:
            from integrations.base import AuthStrategy, ConnectorState, FallbackPolicy, IntegrationCapability, IntegrationType as CanonicalIntegrationType, OAuthAccount
            from integrations.connectors.google import GoogleConnector

            capability = IntegrationCapability(
                name=str(integration.name or "calendar"),
                provider="google",
                integration_type=CanonicalIntegrationType.API,
                required_scopes=["calendar.read", "calendar.write"],
                auth_strategy=AuthStrategy.OAUTH,
                fallback_policy=FallbackPolicy.WEB,
                connector_name="google",
            )
            scopes = list(integration.credentials.get("scopes") or integration.config.get("scopes") or ["calendar.read", "calendar.write"])
            account = OAuthAccount(
                provider="google",
                account_alias=str(integration.credentials.get("account_alias") or integration.name or "default"),
                display_name=str(integration.credentials.get("display_name") or integration.name or "Google"),
                email=str(integration.credentials.get("email") or integration.credentials.get("email_address") or ""),
                access_token=str(integration.credentials.get("access_token") or ""),
                refresh_token=str(integration.credentials.get("refresh_token") or ""),
                granted_scopes=scopes,
                status=ConnectorState.READY if (integration.credentials.get("access_token") or integration.credentials.get("refresh_token")) else ConnectorState.NEEDS_INPUT,
                auth_strategy=AuthStrategy.OAUTH,
            )
            connector = GoogleConnector(capability=capability, auth_account=account, provider="google", connector_name="google")
            result = await connector.execute(
                {
                    "kind": "calendar_create",
                    "event": {
                        "summary": title,
                        "description": description or "",
                        "start": {"dateTime": start_time},
                        "end": {"dateTime": end_time},
                    },
                }
            )
            return result.model_dump() if hasattr(result, "model_dump") else dict(result)
        except Exception as e:
            logger.error(f"Calendar event error: {e}")
            return {"success": False, "error": str(e)}

    async def upload_to_cloud(
        self,
        integration_id: str,
        file_path: str,
        remote_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Upload file to cloud storage"""
        integration = self.integrations.get(integration_id)

        if not integration or integration.type != IntegrationType.CLOUD_STORAGE:
            return {"success": False, "error": "Invalid cloud storage integration"}
        try:
            from integrations.base import AuthStrategy, ConnectorState, FallbackPolicy, IntegrationCapability, IntegrationType as CanonicalIntegrationType, OAuthAccount
            from integrations.connectors.google import GoogleConnector

            provider = str(integration.config.get("provider") or integration.credentials.get("provider") or "google").strip().lower()
            if provider not in {"google", "drive"}:
                return {"success": False, "error": f"Unsupported cloud provider: {provider}"}
            capability = IntegrationCapability(
                name=str(integration.name or "cloud_storage"),
                provider="google",
                integration_type=CanonicalIntegrationType.API,
                required_scopes=["drive.read", "drive.write"],
                auth_strategy=AuthStrategy.OAUTH,
                fallback_policy=FallbackPolicy.WEB,
                connector_name="google",
            )
            scopes = list(integration.credentials.get("scopes") or integration.config.get("scopes") or ["drive.read", "drive.write"])
            account = OAuthAccount(
                provider="google",
                account_alias=str(integration.credentials.get("account_alias") or integration.name or "default"),
                display_name=str(integration.credentials.get("display_name") or integration.name or "Google Drive"),
                email=str(integration.credentials.get("email") or integration.credentials.get("email_address") or ""),
                access_token=str(integration.credentials.get("access_token") or ""),
                refresh_token=str(integration.credentials.get("refresh_token") or ""),
                granted_scopes=scopes,
                status=ConnectorState.READY if (integration.credentials.get("access_token") or integration.credentials.get("refresh_token")) else ConnectorState.NEEDS_INPUT,
                auth_strategy=AuthStrategy.OAUTH,
            )
            connector = GoogleConnector(capability=capability, auth_account=account, provider="google", connector_name="google")
            result = await connector.execute(
                {
                    "kind": "drive_upload",
                    "file_path": file_path,
                    "name": str(remote_path or Path(file_path).name),
                    "parent_id": str(integration.config.get("folder_id") or integration.credentials.get("folder_id") or ""),
                }
            )
            return result.model_dump() if hasattr(result, "model_dump") else dict(result)
        except Exception as e:
            logger.error(f"Cloud upload error: {e}")
            return {"success": False, "error": str(e)}

    async def trigger_webhook(
        self,
        integration_id: str,
        data: Dict[str, Any],
        method: str = "POST"
    ) -> Dict[str, Any]:
        """Trigger a webhook"""
        integration = self.integrations.get(integration_id)

        if not integration or integration.type != IntegrationType.WEBHOOK:
            return {"success": False, "error": "Invalid webhook integration"}

        url = integration.config.get("url")
        if not url:
            return {"success": False, "error": "Webhook URL not configured"}

        try:
            async with aiohttp.ClientSession() as session:
                if method.upper() == "POST":
                    async with session.post(url, json=data) as response:
                        integration.last_used = time.time()
                        result = await response.text()
                        return {
                            "success": response.status < 400,
                            "status_code": response.status,
                            "response": result
                        }
                elif method.upper() == "GET":
                    async with session.get(url, params=data) as response:
                        integration.last_used = time.time()
                        result = await response.text()
                        return {
                            "success": response.status < 400,
                            "status_code": response.status,
                            "response": result
                        }

        except Exception as e:
            logger.error(f"Webhook trigger error: {e}")
            return {"success": False, "error": str(e)}

    async def call_custom_api(
        self,
        integration_id: str,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Call custom API"""
        integration = self.integrations.get(integration_id)

        if not integration or integration.type != IntegrationType.CUSTOM_API:
            return {"success": False, "error": "Invalid custom API integration"}

        base_url = integration.config.get("base_url")
        if not base_url:
            return {"success": False, "error": "Base URL not configured"}

        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

        # Add authentication headers
        auth_type = integration.credentials.get("auth_type")
        if auth_type == "bearer":
            token = integration.credentials.get("token")
            if not headers:
                headers = {}
            headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "api_key":
            key_name = integration.credentials.get("key_name", "X-API-Key")
            key_value = integration.credentials.get("key_value")
            if not headers:
                headers = {}
            headers[key_name] = key_value

        try:
            async with aiohttp.ClientSession() as session:
                if method.upper() == "GET":
                    async with session.get(url, params=data, headers=headers) as response:
                        result = await response.json()
                        return {
                            "success": response.status < 400,
                            "status_code": response.status,
                            "data": result
                        }
                elif method.upper() == "POST":
                    async with session.post(url, json=data, headers=headers) as response:
                        result = await response.json()
                        return {
                            "success": response.status < 400,
                            "status_code": response.status,
                            "data": result
                        }
                elif method.upper() == "PUT":
                    async with session.put(url, json=data, headers=headers) as response:
                        result = await response.json()
                        return {
                            "success": response.status < 400,
                            "status_code": response.status,
                            "data": result
                        }
                elif method.upper() == "DELETE":
                    async with session.delete(url, headers=headers) as response:
                        result = await response.text()
                        return {
                            "success": response.status < 400,
                            "status_code": response.status,
                            "response": result
                        }

        except Exception as e:
            logger.error(f"Custom API call error: {e}")
            return {"success": False, "error": str(e)}

    def test_integration(self, integration_id: str) -> Dict[str, Any]:
        """Test an integration"""
        integration = self.integrations.get(integration_id)

        if not integration:
            return {"success": False, "error": "Integration not found"}

        # Perform type-specific test
        if integration.type == IntegrationType.SLACK:
            # Test Slack webhook
            webhook_url = integration.credentials.get("webhook_url")
            if webhook_url:
                return {"success": True, "status": "Webhook URL configured"}
            else:
                return {"success": False, "error": "Webhook URL missing"}

        elif integration.type == IntegrationType.DISCORD:
            # Test Discord webhook
            webhook_url = integration.credentials.get("webhook_url")
            if webhook_url:
                return {"success": True, "status": "Webhook URL configured"}
            else:
                return {"success": False, "error": "Webhook URL missing"}

        else:
            return {"success": True, "status": "Configuration looks valid"}

    def remove_integration(self, integration_id: str):
        """Remove an integration"""
        if integration_id in self.integrations:
            del self.integrations[integration_id]
            self._save_integrations()
            logger.info(f"Removed integration: {integration_id}")

    def list_integrations(
        self,
        integration_type: Optional[IntegrationType] = None
    ) -> List[Dict[str, Any]]:
        """List all integrations"""
        integrations = self.integrations.values()

        if integration_type:
            integrations = [i for i in integrations if i.type == integration_type]

        return [
            {
                "id": i.integration_id,
                "name": i.name,
                "type": i.type.value,
                "status": i.status.value,
                "last_used": i.last_used,
                "error": i.error
            }
            for i in integrations
        ]

    def _save_integrations(self):
        """Save integrations to disk"""
        try:
            self.credentials_file.parent.mkdir(parents=True, exist_ok=True)

            data = {
                integration_id: {
                    "name": i.name,
                    "type": i.type.value,
                    "credentials": i.credentials,
                    "config": i.config,
                    "status": i.status.value
                }
                for integration_id, i in self.integrations.items()
            }

            with open(self.credentials_file, "w") as f:
                json.dump(data, f, indent=2)

            logger.debug(f"Saved {len(data)} integrations")

        except Exception as e:
            logger.error(f"Failed to save integrations: {e}")

    def _load_integrations(self):
        """Load integrations from disk"""
        try:
            if not self.credentials_file.exists():
                return

            with open(self.credentials_file, "r") as f:
                data = json.load(f)

            for integration_id, config in data.items():
                integration = Integration(
                    integration_id=integration_id,
                    name=config["name"],
                    type=IntegrationType(config["type"]),
                    credentials=config["credentials"],
                    config=config.get("config", {}),
                    status=IntegrationStatus(config.get("status", "disconnected"))
                )
                self.integrations[integration_id] = integration

            logger.info(f"Loaded {len(data)} integrations")

        except Exception as e:
            logger.error(f"Failed to load integrations: {e}")

    def get_summary(self) -> Dict[str, Any]:
        """Get integration hub summary"""
        by_type = {}
        for integration in self.integrations.values():
            type_name = integration.type.value
            by_type[type_name] = by_type.get(type_name, 0) + 1

        return {
            "total_integrations": len(self.integrations),
            "by_type": by_type,
            "connected": sum(1 for i in self.integrations.values() if i.status == IntegrationStatus.CONNECTED),
            "errors": sum(1 for i in self.integrations.values() if i.status == IntegrationStatus.ERROR)
        }


# Global instance
_integration_hub: Optional[IntegrationHub] = None


def get_integration_hub() -> IntegrationHub:
    """Get or create global integration hub instance"""
    global _integration_hub
    if _integration_hub is None:
        _integration_hub = IntegrationHub()
    return _integration_hub
