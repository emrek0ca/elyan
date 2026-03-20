from __future__ import annotations

import re
from typing import Any, Iterable

from core.capability_router import CapabilityRouter

from .base import (
    AuthStrategy,
    FallbackPolicy,
    IntegrationCapability,
    IntegrationManifest,
    IntegrationType,
    Platform,
    WorkflowBundle,
    normalize_items,
)
from .workflows import build_workflow_bundle, split_compound_text


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").lower().strip().split())


def _contains(text: str, *candidates: str) -> bool:
    low = _normalize_text(text)
    return any(str(candidate).lower().strip() in low for candidate in candidates if str(candidate).strip())


def _safe_integration_type(value: Any, default: IntegrationType = IntegrationType.DESKTOP) -> IntegrationType:
    raw = str(value or "").strip().lower()
    try:
        return IntegrationType(raw or default.value)
    except Exception:
        return default


def _safe_auth_strategy(value: Any, default: AuthStrategy = AuthStrategy.NONE) -> AuthStrategy:
    raw = str(value or "").strip().lower()
    try:
        return AuthStrategy(raw or default.value)
    except Exception:
        return default


def _safe_fallback_policy(value: Any, default: FallbackPolicy = FallbackPolicy.AUTO) -> FallbackPolicy:
    raw = str(value or "").strip().lower()
    try:
        return FallbackPolicy(raw or default.value)
    except Exception:
        return default


class IntegrationRegistry:
    def __init__(self) -> None:
        self._router = CapabilityRouter()

    @staticmethod
    def _provider_and_type(text: str, skill: dict[str, Any], route_domain: str) -> tuple[str, IntegrationType, AuthStrategy, FallbackPolicy, list[str], list[str], str]:
        low = _normalize_text(text)
        skill_type = _safe_integration_type(skill.get("integration_type"), IntegrationType.UNKNOWN)

        provider = str(skill.get("provider") or "").strip().lower()
        connector_name = str(skill.get("connector_name") or "").strip().lower()
        if not provider:
            if any(token in low for token in ("gmail", "google mail", "inbox", "mail.google.com")):
                provider = "google"
            elif any(token in low for token in ("calendar", "takvim", "reminder", "hatırlat", "hatirlat")):
                provider = "google"
            elif any(token in low for token in ("drive", "docs", "sheets", "slides", "workspace")):
                provider = "google"
            elif any(token in low for token in ("whatsapp",)):
                provider = "whatsapp"
            elif any(token in low for token in ("instagram",)):
                provider = "instagram"
            elif any(token in low for token in ("x.com", "twitter", "tweet", "tweetle")):
                provider = "x"
            elif any(token in low for token in ("mail", "email", "posta")):
                provider = "email"
            elif any(token in low for token in ("safari", "chrome", "firefox", "browser", "web", "site", "website", "www.")):
                provider = "browser"
            elif any(token in low for token in ("vscode", "excel", "word", "finder", "terminal", "desktop", "app")):
                provider = "desktop"
            elif any(token in low for token in ("schedule", "cron", "remind", "hatırlat", "hatirlat")):
                provider = "scheduler"
            else:
                provider = route_domain or "desktop"

        if not connector_name:
            connector_name = provider or route_domain or "desktop"

        required_scopes: list[str] = list(skill.get("required_scopes") or [])
        dependencies: list[str] = list(skill.get("dependencies") or [])
        python_dependencies: list[str] = list(skill.get("python_dependencies") or [])
        os_dependencies: list[str] = list(skill.get("os_dependencies") or [])
        fallback_policy = _safe_fallback_policy(skill.get("fallback_policy"), FallbackPolicy.AUTO)
        auth_strategy = _safe_auth_strategy(skill.get("auth_strategy"), AuthStrategy.NONE)
        integration_type = skill_type

        if provider in {"google"}:
            if any(token in low for token in ("gmail", "mail", "inbox")):
                integration_type = IntegrationType.EMAIL
                required_scopes = required_scopes or ["email.read", "email.send"]
                auth_strategy = auth_strategy if auth_strategy != AuthStrategy.NONE else AuthStrategy.OAUTH
                dependencies = dependencies or ["google-api-python-client", "google-auth", "google-auth-oauthlib", "httplib2"]
            elif any(token in low for token in ("calendar", "takvim", "event", "remind", "hatırlat", "hatirlat")):
                integration_type = IntegrationType.API
                required_scopes = required_scopes or ["calendar.read", "calendar.write"]
                auth_strategy = auth_strategy if auth_strategy != AuthStrategy.NONE else AuthStrategy.OAUTH
                dependencies = dependencies or ["google-api-python-client", "google-auth", "google-auth-oauthlib", "httplib2"]
            else:
                integration_type = IntegrationType.API
                required_scopes = required_scopes or ["google.read"]
                auth_strategy = auth_strategy if auth_strategy != AuthStrategy.NONE else AuthStrategy.OAUTH
                dependencies = dependencies or ["google-api-python-client", "google-auth", "google-auth-oauthlib", "httplib2"]
            fallback_policy = fallback_policy if fallback_policy != FallbackPolicy.AUTO else FallbackPolicy.WEB
        elif provider in {"whatsapp", "instagram", "x"}:
            integration_type = IntegrationType.SOCIAL
            required_scopes = required_scopes or [f"{provider}.read", f"{provider}.write"]
            auth_strategy = auth_strategy if auth_strategy != AuthStrategy.NONE else AuthStrategy.OAUTH
            dependencies = dependencies or ["playwright", "playwright-stealth"]
            fallback_policy = fallback_policy if fallback_policy != FallbackPolicy.AUTO else FallbackPolicy.WEB
        elif provider in {"email"}:
            integration_type = IntegrationType.EMAIL
            required_scopes = required_scopes or ["email.read", "email.send"]
            auth_strategy = auth_strategy if auth_strategy != AuthStrategy.NONE else AuthStrategy.IMAP_SMTP
            fallback_policy = fallback_policy if fallback_policy != FallbackPolicy.AUTO else FallbackPolicy.WEB
        elif provider in {"scheduler"}:
            integration_type = IntegrationType.SCHEDULER
            required_scopes = required_scopes or ["calendar.read", "calendar.write"]
            auth_strategy = auth_strategy if auth_strategy != AuthStrategy.NONE else AuthStrategy.OAUTH
            dependencies = dependencies or ["apscheduler"]
            fallback_policy = fallback_policy if fallback_policy != FallbackPolicy.AUTO else FallbackPolicy.WEB
        elif provider in {"browser", "website"}:
            integration_type = IntegrationType.BROWSER
            auth_strategy = auth_strategy if auth_strategy != AuthStrategy.NONE else AuthStrategy.BROWSER_SESSION
            dependencies = dependencies or ["playwright", "playwright-stealth"]
            fallback_policy = fallback_policy if fallback_policy != FallbackPolicy.AUTO else FallbackPolicy.WEB
        else:
            integration_type = integration_type if integration_type != IntegrationType.UNKNOWN else IntegrationType.DESKTOP
            auth_strategy = auth_strategy if auth_strategy != AuthStrategy.NONE else AuthStrategy.NONE
            fallback_policy = fallback_policy if fallback_policy != FallbackPolicy.AUTO else FallbackPolicy.NATIVE
            dependencies = dependencies or ["pyautogui", "mss", "numpy", "opencv-python", "Pillow"]

        if integration_type == IntegrationType.DESKTOP and not os_dependencies:
            os_dependencies = []

        return provider, integration_type, auth_strategy, fallback_policy, required_scopes, list(dict.fromkeys([*dependencies, *python_dependencies])), connector_name

    def resolve(self, intent: Any, request_context: dict[str, Any] | None = None) -> IntegrationCapability:
        context = dict(request_context or {})
        if isinstance(intent, dict):
            text = str(intent.get("text") or intent.get("input_text") or intent.get("user_input") or intent.get("request") or "").strip()
        else:
            text = str(intent or "").strip()
        low = _normalize_text(text)
        route = self._router.route(text)
        skill = dict(context.get("skill") or {})
        workflow = dict(context.get("workflow") or {})
        route_domain = str((context.get("route") or {}).get("domain") if isinstance(context.get("route"), dict) else getattr(route, "domain", "")).strip().lower()
        if not route_domain:
            route_domain = str(getattr(route, "domain", "") or "").strip().lower()

        provider, integration_type, auth_strategy, fallback_policy, required_scopes, dependencies, connector_name = self._provider_and_type(
            text,
            skill,
            route_domain,
        )

        objective = str(
            skill.get("objective")
            or getattr(route, "objective", "")
            or text
        ).strip()
        bundle = build_workflow_bundle(
            text,
            integration_type=integration_type,
            provider=provider,
            name=str(skill.get("name") or workflow.get("name") or connector_name or route_domain or "integration"),
            approval_level=int(skill.get("approval_level") or workflow.get("approval_level") or 0),
            fallback_policy=fallback_policy,
            source=str(skill.get("source") or workflow.get("source") or "heuristic"),
            tags=list(skill.get("commands") or []) + list(workflow.get("trigger_markers") or []),
            objective=objective,
        )
        multi_agent_recommended = bool(bundle.multi_agent_recommended or bundle.approval_level >= 2 or len(bundle.steps) >= 2)
        approval_level = int(skill.get("approval_level") or workflow.get("approval_level") or (2 if any(token in _normalize_text(text) for token in ("delete", "remove", "send", "post", "publish", "share")) else 0))
        real_time = bool(skill.get("real_time", False) or bundle.estimated_latency_level == "real_time" or integration_type in {IntegrationType.DESKTOP, IntegrationType.BROWSER, IntegrationType.SOCIAL})
        supported_platforms = list(skill.get("supported_platforms") or [Platform.WINDOWS.value, Platform.MACOS.value, Platform.LINUX.value])

        browser_urls: list[str] = []
        api_base_urls: list[str] = []
        desktop_apps: list[str] = []
        if integration_type == IntegrationType.BROWSER:
            browser_urls = ["https://www.google.com", "https://example.com"]
        elif integration_type == IntegrationType.EMAIL:
            browser_urls = ["https://mail.google.com", "https://outlook.office.com/mail/"]
            api_base_urls = ["https://gmail.googleapis.com", "https://graph.microsoft.com/v1.0"]
        elif integration_type == IntegrationType.SOCIAL:
            browser_urls = ["https://x.com", "https://www.instagram.com", "https://web.whatsapp.com"]
            api_base_urls = ["https://api.x.com", "https://graph.facebook.com"]
        elif integration_type == IntegrationType.API:
            if provider == "google":
                if any(token in low for token in ("drive", "docs", "sheets", "slides", "workspace", "file", "document")):
                    api_base_urls = ["https://www.googleapis.com/drive", "https://docs.googleapis.com", "https://sheets.googleapis.com"]
                elif any(token in low for token in ("calendar", "takvim", "event", "remind", "hatırlat", "hatirlat")):
                    api_base_urls = ["https://www.googleapis.com/calendar"]
                else:
                    api_base_urls = ["https://gmail.googleapis.com", "https://www.googleapis.com"]
            else:
                api_base_urls = [f"https://api.{provider}.com"] if provider else []
        elif integration_type == IntegrationType.SCHEDULER:
            api_base_urls = ["https://www.googleapis.com/calendar", "https://graph.microsoft.com/v1.0"]
        else:
            desktop_apps = normalize_items(skill.get("commands") or [])

        manifest = IntegrationManifest(
            name=str(skill.get("name") or bundle.name or connector_name or route_domain or "integration"),
            provider=provider,
            version=str(skill.get("version") or workflow.get("version") or "1.0.0"),
            description=str(skill.get("description") or workflow.get("description") or getattr(route, "preview", "") or text),
            integration_type=integration_type,
            required_scopes=list(required_scopes),
            auth_strategy=auth_strategy,
            fallback_policy=fallback_policy,
            supported_platforms=[Platform(str(p)) if str(p) in {Platform.WINDOWS.value, Platform.MACOS.value, Platform.LINUX.value, Platform.UNKNOWN.value} else Platform.UNKNOWN for p in supported_platforms],
            dependencies=list(dependencies),
            python_dependencies=list(skill.get("python_dependencies") or []),
            os_dependencies=list(skill.get("os_dependencies") or []),
            post_install=list(skill.get("post_install") or []),
            trust_level=str(skill.get("trust_level") or "trusted"),
            hashes=dict(skill.get("hashes") or {}),
            approval_level=approval_level,
            real_time=real_time,
            source=str(skill.get("source") or workflow.get("source") or "builtin"),
            connector_name=connector_name,
            browser_urls=browser_urls,
            api_base_urls=api_base_urls,
            desktop_apps=desktop_apps,
            workflow_bundle=bundle,
            metadata={
                "route_domain": route_domain,
                "workflow_id": str(workflow.get("id") or getattr(route, "workflow_id", "") or ""),
                "multi_agent_recommended": multi_agent_recommended,
            },
        )

        capability = IntegrationCapability(
            capability_id=str(skill.get("name") or workflow.get("id") or connector_name or route_domain or "integration"),
            name=str(skill.get("name") or workflow.get("name") or connector_name or route_domain or "integration"),
            provider=provider,
            objective=objective,
            integration_type=integration_type,
            required_scopes=list(required_scopes),
            auth_strategy=auth_strategy,
            fallback_policy=fallback_policy,
            supported_platforms=[Platform(str(p)) if str(p) in {Platform.WINDOWS.value, Platform.MACOS.value, Platform.LINUX.value, Platform.UNKNOWN.value} else Platform.UNKNOWN for p in supported_platforms],
            dependencies=list(dependencies),
            python_dependencies=list(skill.get("python_dependencies") or []),
            os_dependencies=list(skill.get("os_dependencies") or []),
            post_install=list(skill.get("post_install") or []),
            approval_level=approval_level,
            real_time=real_time,
            multi_agent_recommended=multi_agent_recommended,
            workflow_bundle=bundle,
            connector_name=connector_name,
            auth_required=auth_strategy not in {AuthStrategy.NONE},
            fallback_target="web" if fallback_policy == FallbackPolicy.WEB else "native",
            transport_preference="realtime" if real_time else "auto",
            latency_level=str(skill.get("latency_level") or bundle.estimated_latency_level or "standard"),
            trust_level=str(skill.get("trust_level") or "trusted"),
            manifest=manifest,
            notes=[
                f"route_domain:{route_domain}",
                f"provider:{provider}",
                f"fallback:{fallback_policy.value}",
            ],
            metadata={
                "text": text,
                "skill_category": str(skill.get("category") or ""),
                "workflow": workflow,
                "route": route.model_dump() if hasattr(route, "model_dump") else {},
                "multi_agent_recommended": multi_agent_recommended,
            },
        )
        return capability


integration_registry = IntegrationRegistry()
