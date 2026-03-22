from __future__ import annotations

import sys
import time
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from pydantic import BaseModel, ConfigDict, Field


def _ts() -> float:
    return time.time()


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - convenience
        return str(self.value)


class Platform(StrEnum):
    WINDOWS = "windows"
    MACOS = "darwin"
    LINUX = "linux"
    UNKNOWN = "unknown"


class IntegrationType(StrEnum):
    DESKTOP = "desktop"
    BROWSER = "browser"
    API = "api"
    EMAIL = "email"
    SCHEDULER = "scheduler"
    SOCIAL = "social"
    UNKNOWN = "unknown"


class AuthStrategy(StrEnum):
    NONE = "none"
    OAUTH = "oauth"
    API_KEY = "api_key"
    BROWSER_SESSION = "browser_session"
    SERVICE_ACCOUNT = "service_account"
    IMAP_SMTP = "imap_smtp"
    DEVICE_CODE = "device_code"
    LOOPBACK = "loopback"
    COOKIE = "cookie"
    PERSISTENT_BROWSER = "persistent_browser"


class FallbackPolicy(StrEnum):
    AUTO = "auto"
    WEB = "web"
    NATIVE = "native"
    BLOCK = "blocked"
    PAUSE = "pause"
    RETRY = "retry"
    ESCALATE = "escalate"
    MANUAL = "manual"


class ConnectorState(StrEnum):
    MISSING = "missing"
    INSTALLING = "installing"
    READY = "ready"
    BLOCKED = "blocked"
    NEEDS_INPUT = "needs_input"
    FAILED = "failed"
    PAUSED = "paused"


def normalize_items(values: Iterable[Any] | None) -> list[str]:
    out: list[str] = []
    for value in list(values or []):
        item = str(value or "").strip()
        if item:
            out.append(item)
    return list(dict.fromkeys(out))


def normalize_platform(value: Any = None) -> Platform:
    raw = str(value or "").strip().lower()
    if raw in {"win32", "windows"}:
        return Platform.WINDOWS
    if raw in {"darwin", "mac", "macos", "osx"}:
        return Platform.MACOS
    if raw in {"linux", "gnu/linux"}:
        return Platform.LINUX
    sys_name = (sys.platform or "").lower()
    if sys_name.startswith("win"):
        return Platform.WINDOWS
    if sys_name == "darwin":
        return Platform.MACOS
    if sys_name.startswith("linux"):
        return Platform.LINUX
    return Platform.UNKNOWN


def _path_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Path):
        return str(value.expanduser())
    return str(value).strip()


class WorkflowStep(BaseModel):
    step_id: str = ""
    title: str = ""
    action: str = ""
    role: str = "builder"
    depends_on: list[str] = Field(default_factory=list)
    parallelizable: bool = False
    requires_approval: bool = False
    parameters: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow", use_enum_values=True)


class WorkflowBundle(BaseModel):
    bundle_id: str = ""
    name: str = ""
    objective: str = ""
    integration_type: IntegrationType = IntegrationType.UNKNOWN
    provider: str = ""
    roles: list[str] = Field(default_factory=list)
    steps: list[WorkflowStep] = Field(default_factory=list)
    serial_steps: list[str] = Field(default_factory=list)
    parallel_groups: list[list[str]] = Field(default_factory=list)
    multi_agent_recommended: bool = False
    approval_level: int = 0
    fallback_policy: FallbackPolicy = FallbackPolicy.AUTO
    evidence_contract: dict[str, Any] = Field(default_factory=dict)
    output_artifacts: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    source: str = "heuristic"
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    estimated_latency_level: str = "standard"

    model_config = ConfigDict(extra="allow", use_enum_values=True)


class IntegrationManifest(BaseModel):
    name: str = ""
    provider: str = ""
    version: str = "1.0.0"
    description: str = ""
    integration_type: IntegrationType = IntegrationType.UNKNOWN
    required_scopes: list[str] = Field(default_factory=list)
    auth_strategy: AuthStrategy = AuthStrategy.NONE
    fallback_policy: FallbackPolicy = FallbackPolicy.AUTO
    supported_platforms: list[Platform] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    python_dependencies: list[str] = Field(default_factory=list)
    os_dependencies: list[str] = Field(default_factory=list)
    post_install: list[str] = Field(default_factory=list)
    trust_level: str = "trusted"
    hashes: dict[str, str] = Field(default_factory=dict)
    approval_level: int = 0
    real_time: bool = False
    source: str = "builtin"
    connector_name: str = ""
    browser_urls: list[str] = Field(default_factory=list)
    api_base_urls: list[str] = Field(default_factory=list)
    desktop_apps: list[str] = Field(default_factory=list)
    workflow_bundle: WorkflowBundle = Field(default_factory=WorkflowBundle)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow", use_enum_values=True)


class IntegrationCapability(BaseModel):
    capability_id: str = ""
    name: str = ""
    provider: str = ""
    objective: str = ""
    integration_type: IntegrationType = IntegrationType.UNKNOWN
    required_scopes: list[str] = Field(default_factory=list)
    auth_strategy: AuthStrategy = AuthStrategy.NONE
    fallback_policy: FallbackPolicy = FallbackPolicy.AUTO
    supported_platforms: list[Platform] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    python_dependencies: list[str] = Field(default_factory=list)
    os_dependencies: list[str] = Field(default_factory=list)
    post_install: list[str] = Field(default_factory=list)
    approval_level: int = 0
    real_time: bool = False
    multi_agent_recommended: bool = False
    workflow_bundle: WorkflowBundle = Field(default_factory=WorkflowBundle)
    connector_name: str = ""
    auth_required: bool = False
    fallback_target: str = "web"
    transport_preference: str = "auto"
    latency_level: str = "standard"
    trust_level: str = "trusted"
    manifest: IntegrationManifest = Field(default_factory=IntegrationManifest)
    notes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow", use_enum_values=True)


class OAuthAccount(BaseModel):
    provider: str = ""
    account_alias: str = "default"
    display_name: str = ""
    email: str = ""
    auth_strategy: AuthStrategy = AuthStrategy.OAUTH
    fallback_mode: FallbackPolicy = FallbackPolicy.WEB
    granted_scopes: list[str] = Field(default_factory=list)
    access_token: str = ""
    refresh_token: str = ""
    token_type: str = "Bearer"
    expires_at: float = 0.0
    last_auth_at: float = 0.0
    status: ConnectorState = ConnectorState.NEEDS_INPUT
    auth_url: str = ""
    device_code: str = ""
    redirect_uri: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow", use_enum_values=True)

    @property
    def is_ready(self) -> bool:
        return str(self.status) == ConnectorState.READY.value and bool(self.access_token or self.refresh_token or self.granted_scopes)

    def public_dump(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("access_token", None)
        data.pop("refresh_token", None)
        return data


class ConnectorSnapshot(BaseModel):
    connector_name: str = ""
    provider: str = ""
    integration_type: IntegrationType = IntegrationType.UNKNOWN
    platform: Platform = Platform.UNKNOWN
    state: str = "idle"
    auth_state: ConnectorState = ConnectorState.NEEDS_INPUT
    account_alias: str = "default"
    session_id: str = ""
    target: str = ""
    url: str = ""
    title: str = ""
    elements: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    captured_at: float = Field(default_factory=_ts)

    model_config = ConfigDict(extra="allow", use_enum_values=True)


class ConnectorResult(BaseModel):
    success: bool = False
    status: str = "failed"
    connector_name: str = ""
    provider: str = ""
    integration_type: IntegrationType = IntegrationType.UNKNOWN
    platform: Platform = Platform.UNKNOWN
    auth_state: ConnectorState = ConnectorState.NEEDS_INPUT
    fallback_used: bool = False
    fallback_reason: str = ""
    latency_ms: float = 0.0
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    snapshot: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    error: str = ""
    retryable: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=_ts)

    model_config = ConfigDict(extra="allow", use_enum_values=True)


class BaseConnector(ABC):
    def __init__(
        self,
        *,
        capability: IntegrationCapability | dict[str, Any] | None = None,
        auth_account: OAuthAccount | dict[str, Any] | None = None,
        platform: Platform | str | None = None,
        provider: str = "",
        connector_name: str = "",
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.capability = self._coerce_capability(capability)
        self.auth_account = self._coerce_account(auth_account)
        self.platform = normalize_platform(platform)
        self.provider = str(provider or getattr(self.capability, "provider", "") or "").strip().lower()
        self.connector_name = str(connector_name or getattr(self.capability, "connector_name", "") or self.__class__.__name__).strip() or self.__class__.__name__
        self.session_id = str(session_id or "").strip()
        self.metadata = dict(metadata or {})

    @staticmethod
    def _coerce_capability(capability: IntegrationCapability | dict[str, Any] | None) -> IntegrationCapability:
        if isinstance(capability, IntegrationCapability):
            return capability
        if isinstance(capability, dict):
            return IntegrationCapability.model_validate(capability)
        return IntegrationCapability()

    @staticmethod
    def _coerce_account(account: OAuthAccount | dict[str, Any] | None) -> OAuthAccount:
        if isinstance(account, OAuthAccount):
            return account
        if isinstance(account, dict):
            return OAuthAccount.model_validate(account)
        return OAuthAccount()

    def _snapshot(
        self,
        *,
        state: str = "idle",
        target: str = "",
        url: str = "",
        title: str = "",
        elements: list[dict[str, Any]] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        auth_state: ConnectorState | str | None = None,
    ) -> ConnectorSnapshot:
        return ConnectorSnapshot(
            connector_name=self.connector_name,
            provider=self.provider,
            integration_type=self.capability.integration_type,
            platform=self.platform,
            state=state,
            auth_state=auth_state or (self.auth_account.status if isinstance(self.auth_account, OAuthAccount) else ConnectorState.NEEDS_INPUT),
            account_alias=str(getattr(self.auth_account, "account_alias", "default") or "default"),
            session_id=self.session_id,
            target=target,
            url=url,
            title=title,
            elements=list(elements or []),
            artifacts=list(artifacts or []),
            metadata=dict(metadata or {}),
        )

    def _result(
        self,
        *,
        success: bool,
        status: str,
        message: str = "",
        error: str = "",
        fallback_used: bool = False,
        fallback_reason: str = "",
        latency_ms: float = 0.0,
        evidence: list[dict[str, Any]] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        snapshot: ConnectorSnapshot | dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        retryable: bool = False,
        metadata: dict[str, Any] | None = None,
        auth_state: ConnectorState | str | None = None,
    ) -> ConnectorResult:
        snap = snapshot.model_dump() if isinstance(snapshot, ConnectorSnapshot) else dict(snapshot or {})
        result_obj = ConnectorResult(
            success=bool(success),
            status=str(status or ("success" if success else "failed")),
            connector_name=self.connector_name,
            provider=self.provider,
            integration_type=self.capability.integration_type,
            platform=self.platform,
            auth_state=auth_state or (self.auth_account.status if isinstance(self.auth_account, OAuthAccount) else ConnectorState.NEEDS_INPUT),
            fallback_used=bool(fallback_used),
            fallback_reason=str(fallback_reason or ""),
            latency_ms=float(latency_ms or 0.0),
            evidence=list(evidence or []),
            artifacts=list(artifacts or []),
            snapshot=snap,
            result=dict(result or {}),
            message=str(message or ""),
            error=str(error or ""),
            retryable=bool(retryable),
            metadata=dict(metadata or {}),
        )
        try:
            from core.integration_trace import get_integration_trace_store

            trace_meta = dict(metadata or {})
            trace_store = get_integration_trace_store()
            trace_store.record_trace(
                request_id=str(trace_meta.get("request_id") or trace_meta.get("trace_id") or self.session_id or ""),
                user_id=str(trace_meta.get("user_id") or ""),
                session_id=str(trace_meta.get("session_id") or self.session_id or ""),
                channel=str(trace_meta.get("channel") or ""),
                provider=self.provider,
                connector_name=self.connector_name,
                integration_type=str(self.capability.integration_type.value if hasattr(self.capability.integration_type, "value") else self.capability.integration_type),
                operation=str(trace_meta.get("operation") or "connector"),
                status=str(result_obj.status or ""),
                success=bool(result_obj.success),
                auth_state=str(result_obj.auth_state.value if hasattr(result_obj.auth_state, "value") else result_obj.auth_state),
                auth_strategy=str(self.capability.auth_strategy.value if hasattr(self.capability.auth_strategy, "value") else self.capability.auth_strategy),
                account_alias=str(getattr(self.auth_account, "account_alias", "default") or "default"),
                fallback_used=bool(result_obj.fallback_used),
                fallback_reason=str(result_obj.fallback_reason or ""),
                install_state=str(trace_meta.get("install_state") or ""),
                retry_count=int(trace_meta.get("retry_count") or 0),
                latency_ms=float(result_obj.latency_ms or 0.0),
                evidence=list(result_obj.evidence or []),
                artifacts=list(result_obj.artifacts or []),
                verification=dict(trace_meta.get("verification") or {}),
                metadata={
                    **trace_meta,
                    "snapshot": snap,
                    "result": dict(result_obj.result or {}),
                },
            )
        except Exception:
            pass
        return result_obj

    async def connect(self, app_name_or_url: str, **kwargs: Any) -> ConnectorResult:
        raise NotImplementedError

    async def execute(self, action: dict[str, Any]) -> ConnectorResult:
        raise NotImplementedError

    async def snapshot(self) -> ConnectorSnapshot:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {
            "connector_name": self.connector_name,
            "provider": self.provider,
            "platform": str(self.platform.value if isinstance(self.platform, Platform) else self.platform),
            "integration_type": str(self.capability.integration_type.value if hasattr(self.capability.integration_type, "value") else self.capability.integration_type),
            "auth_state": str(self.auth_account.status.value if isinstance(self.auth_account, OAuthAccount) else ConnectorState.NEEDS_INPUT.value),
            "capability": self.capability.model_dump(),
            "auth_account": self.auth_account.public_dump() if isinstance(self.auth_account, OAuthAccount) else {},
            "metadata": dict(self.metadata or {}),
        }


def path_str(value: Any) -> str:
    return _path_str(value)
