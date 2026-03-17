"""
ELYAN Integration SDK - Phase 9
Base classes, webhook handling, pre-built connectors (Slack, GitHub, Jira, Notion).
"""

import hashlib
import hmac
import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class IntegrationType(Enum):
    MESSAGING = "messaging"
    DEV_TOOLS = "dev_tools"
    CLOUD = "cloud"
    DATA = "data"
    PRODUCTIVITY = "productivity"
    CUSTOM = "custom"


class EventDirection(Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    BIDIRECTIONAL = "bidirectional"


@dataclass
class IntegrationConfig:
    name: str
    integration_type: IntegrationType
    api_base_url: str = ""
    auth_token: str = ""
    webhook_secret: str = ""
    enabled: bool = True
    settings: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IntegrationEvent:
    event_id: str
    integration_name: str
    event_type: str
    direction: EventDirection
    payload: Dict[str, Any]
    timestamp: float = 0.0
    processed: bool = False
    result: Optional[Dict[str, Any]] = None


class BaseIntegration(ABC):
    """Base class for all ELYAN integrations."""

    def __init__(self, config: IntegrationConfig):
        self.config = config
        self._connected = False
        self._event_handlers: Dict[str, List[Callable]] = {}
        self._event_log: List[IntegrationEvent] = []

    @abstractmethod
    def connect(self) -> bool:
        pass

    @abstractmethod
    def disconnect(self) -> bool:
        pass

    @abstractmethod
    def send(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        pass

    def on(self, event_type: str, handler: Callable):
        self._event_handlers.setdefault(event_type, []).append(handler)

    def emit(self, event_type: str, payload: Dict[str, Any]) -> IntegrationEvent:
        event = IntegrationEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            integration_name=self.config.name,
            event_type=event_type,
            direction=EventDirection.INBOUND,
            payload=payload,
            timestamp=time.time(),
        )
        handlers = self._event_handlers.get(event_type, [])
        for handler in handlers:
            try:
                result = handler(event)
                event.result = result
            except Exception as e:
                event.result = {"error": str(e)}
        event.processed = True
        self._event_log.append(event)
        return event

    def get_event_log(self, limit: int = 50) -> List[IntegrationEvent]:
        return self._event_log[-limit:]

    @property
    def is_connected(self) -> bool:
        return self._connected


class SlackIntegration(BaseIntegration):
    """Slack workspace integration."""

    def __init__(self, config: IntegrationConfig):
        super().__init__(config)
        self._channels: Dict[str, Dict[str, Any]] = {}
        self._messages_sent = 0

    def connect(self) -> bool:
        if not self.config.auth_token:
            return False
        self._connected = True
        return True

    def disconnect(self) -> bool:
        self._connected = False
        return True

    def send(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._connected:
            return {"error": "Not connected"}
        channel = payload.get("channel", "#general")
        text = payload.get("text", "")
        message = {
            "channel": channel,
            "text": text,
            "ts": str(time.time()),
            "message_id": f"slack_{uuid.uuid4().hex[:8]}",
        }
        self._messages_sent += 1
        self.emit("message_sent", message)
        return {"ok": True, "message": message}

    def send_message(self, channel: str, text: str, **kwargs) -> Dict[str, Any]:
        return self.send("message", {"channel": channel, "text": text, **kwargs})

    def handle_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        event_type = payload.get("type", "unknown")
        if event_type == "url_verification":
            return {"challenge": payload.get("challenge", "")}
        self.emit(event_type, payload)
        return {"ok": True}

    def get_status(self) -> Dict[str, Any]:
        return {
            "integration": "slack",
            "connected": self._connected,
            "messages_sent": self._messages_sent,
            "channels": len(self._channels),
        }


class GitHubIntegration(BaseIntegration):
    """GitHub repository integration."""

    def __init__(self, config: IntegrationConfig):
        super().__init__(config)
        self._repos: Dict[str, Dict[str, Any]] = {}
        self._actions_count = 0

    def connect(self) -> bool:
        if not self.config.auth_token:
            return False
        self._connected = True
        return True

    def disconnect(self) -> bool:
        self._connected = False
        return True

    def send(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._connected:
            return {"error": "Not connected"}
        self._actions_count += 1
        result = {
            "action": event_type,
            "payload": payload,
            "timestamp": time.time(),
        }
        self.emit(event_type, result)
        return {"ok": True, "result": result}

    def create_issue(self, repo: str, title: str, body: str, labels: Optional[List[str]] = None) -> Dict[str, Any]:
        return self.send("create_issue", {
            "repo": repo, "title": title, "body": body,
            "labels": labels or [],
        })

    def create_pr(self, repo: str, title: str, body: str, head: str, base: str = "main") -> Dict[str, Any]:
        return self.send("create_pr", {
            "repo": repo, "title": title, "body": body,
            "head": head, "base": base,
        })

    def handle_webhook(self, headers: Dict[str, str], payload: Dict[str, Any]) -> Dict[str, Any]:
        signature = headers.get("X-Hub-Signature-256", "")
        if self.config.webhook_secret and signature:
            expected = "sha256=" + hmac.new(
                self.config.webhook_secret.encode(),
                json.dumps(payload, sort_keys=True).encode(),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return {"error": "Invalid signature"}
        event_type = headers.get("X-GitHub-Event", "unknown")
        self.emit(f"github.{event_type}", payload)
        return {"ok": True, "event": event_type}

    def get_status(self) -> Dict[str, Any]:
        return {
            "integration": "github",
            "connected": self._connected,
            "actions": self._actions_count,
            "repos": len(self._repos),
        }


class JiraIntegration(BaseIntegration):
    """Jira ticket management integration."""

    def __init__(self, config: IntegrationConfig):
        super().__init__(config)
        self._tickets: Dict[str, Dict[str, Any]] = {}

    def connect(self) -> bool:
        if not self.config.auth_token or not self.config.api_base_url:
            return False
        self._connected = True
        return True

    def disconnect(self) -> bool:
        self._connected = False
        return True

    def send(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._connected:
            return {"error": "Not connected"}
        self.emit(event_type, payload)
        return {"ok": True}

    def create_ticket(self, project: str, summary: str, description: str, issue_type: str = "Task") -> Dict[str, Any]:
        ticket_id = f"{project}-{len(self._tickets) + 1}"
        ticket = {
            "key": ticket_id, "project": project, "summary": summary,
            "description": description, "type": issue_type,
            "status": "To Do", "created": time.time(),
        }
        self._tickets[ticket_id] = ticket
        return self.send("create_ticket", ticket)

    def update_ticket(self, ticket_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        ticket = self._tickets.get(ticket_id)
        if ticket:
            ticket.update(updates)
            return self.send("update_ticket", ticket)
        return {"error": "Ticket not found"}

    def get_status(self) -> Dict[str, Any]:
        return {
            "integration": "jira",
            "connected": self._connected,
            "tickets": len(self._tickets),
        }


class NotionIntegration(BaseIntegration):
    """Notion database sync integration."""

    def __init__(self, config: IntegrationConfig):
        super().__init__(config)
        self._pages: Dict[str, Dict[str, Any]] = {}

    def connect(self) -> bool:
        if not self.config.auth_token:
            return False
        self._connected = True
        return True

    def disconnect(self) -> bool:
        self._connected = False
        return True

    def send(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._connected:
            return {"error": "Not connected"}
        self.emit(event_type, payload)
        return {"ok": True}

    def create_page(self, database_id: str, title: str, properties: Optional[Dict] = None) -> Dict[str, Any]:
        page_id = f"page_{uuid.uuid4().hex[:8]}"
        page = {
            "id": page_id, "database_id": database_id,
            "title": title, "properties": properties or {},
            "created": time.time(),
        }
        self._pages[page_id] = page
        return self.send("create_page", page)

    def get_status(self) -> Dict[str, Any]:
        return {
            "integration": "notion",
            "connected": self._connected,
            "pages": len(self._pages),
        }


class IntegrationHub:
    """Central hub managing all integrations."""

    REGISTRY = {
        "slack": SlackIntegration,
        "github": GitHubIntegration,
        "jira": JiraIntegration,
        "notion": NotionIntegration,
    }

    def __init__(self):
        self._integrations: Dict[str, BaseIntegration] = {}

    def add(self, name: str, config: IntegrationConfig) -> Optional[BaseIntegration]:
        cls = self.REGISTRY.get(name)
        if cls:
            integration = cls(config)
            self._integrations[name] = integration
            return integration
        return None

    def connect(self, name: str) -> bool:
        integration = self._integrations.get(name)
        if integration:
            return integration.connect()
        return False

    def disconnect(self, name: str) -> bool:
        integration = self._integrations.get(name)
        if integration:
            return integration.disconnect()
        return False

    def get(self, name: str) -> Optional[BaseIntegration]:
        return self._integrations.get(name)

    def list_available(self) -> List[str]:
        return list(self.REGISTRY.keys())

    def list_connected(self) -> List[str]:
        return [name for name, intg in self._integrations.items() if intg.is_connected]

    def get_all_status(self) -> Dict[str, Any]:
        return {
            name: intg.get_status()
            for name, intg in self._integrations.items()
        }


_integration_hub: Optional[IntegrationHub] = None


def get_integration_hub() -> IntegrationHub:
    global _integration_hub
    if _integration_hub is None:
        _integration_hub = IntegrationHub()
    return _integration_hub
