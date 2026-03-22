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


def _infer_provider_from_app_name(app_name: str) -> str:
    low = _normalize_text(app_name)
    if not low:
        return ""
    if any(token in low for token in ("gmail", "google mail", "mail.google.com", "google workspace", "google drive", "google docs", "google sheets", "google slides", "google chat")):
        return "google"
    if any(token in low for token in ("calendar", "takvim", "schedule", "remind", "hatırlat", "hatirlat")):
        return "google"
    if any(token in low for token in ("whatsapp",)):
        return "whatsapp"
    if any(token in low for token in ("instagram",)):
        return "instagram"
    if any(token in low for token in ("x ", " x", "twitter", "tweet", "x.com")):
        return "x"
    if any(token in low for token in ("mail", "email", "posta", "outlook", "exchange")):
        return "email"
    if any(token in low for token in ("browser", "web", "website", "site", "chrome", "safari", "firefox")):
        return "browser"
    if any(token in low for token in ("vscode", "excel", "word", "finder", "desktop", "terminal", "app")):
        return "desktop"
    return ""


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
    def _provider_and_type(text: str, skill: dict[str, Any], route_domain: str) -> tuple[str, IntegrationType, AuthStrategy, FallbackPolicy, list[str], list[str], str, dict[str, Any]]:
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
        auth_resolution: dict[str, Any] = {}

        if provider in {"google"}:
            if any(token in low for token in ("gmail", "mail", "inbox")):
                integration_type = IntegrationType.EMAIL
                required_scopes = required_scopes or ["email.read", "email.send"]
                auth_strategy = auth_strategy if auth_strategy != AuthStrategy.NONE else AuthStrategy.OAUTH
                dependencies = dependencies or ["google-api-python-client", "google-auth", "google-auth-oauthlib", "httplib2"]
            elif any(token in low for token in ("docs", "document", "workspace doc", "google docs")):
                integration_type = IntegrationType.API
                required_scopes = required_scopes or ["docs.read", "docs.write"]
                auth_strategy = auth_strategy if auth_strategy != AuthStrategy.NONE else AuthStrategy.OAUTH
                dependencies = dependencies or ["google-api-python-client", "google-auth", "google-auth-oauthlib", "httplib2"]
            elif any(token in low for token in ("sheets", "spreadsheet", "table", "excel", "google sheets")):
                integration_type = IntegrationType.API
                required_scopes = required_scopes or ["sheets.read", "sheets.write"]
                auth_strategy = auth_strategy if auth_strategy != AuthStrategy.NONE else AuthStrategy.OAUTH
                dependencies = dependencies or ["google-api-python-client", "google-auth", "google-auth-oauthlib", "httplib2"]
            elif any(token in low for token in ("slides", "presentation", "sunum", "google slides")):
                integration_type = IntegrationType.API
                required_scopes = required_scopes or ["slides.read", "slides.write"]
                auth_strategy = auth_strategy if auth_strategy != AuthStrategy.NONE else AuthStrategy.OAUTH
                dependencies = dependencies or ["google-api-python-client", "google-auth", "google-auth-oauthlib", "httplib2"]
            elif any(token in low for token in ("chat", "google chat", "spaces", "space")):
                integration_type = IntegrationType.API
                required_scopes = required_scopes or ["chat.read", "chat.write"]
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
            if provider == "whatsapp":
                required_scopes = required_scopes or ["whatsapp.read", "whatsapp.write"]
            elif provider == "instagram":
                required_scopes = required_scopes or ["instagram.read", "instagram.write"]
            elif provider == "x":
                required_scopes = required_scopes or ["x.read", "x.write"]
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

        try:
            from .auth import oauth_broker

            if provider and auth_strategy not in {AuthStrategy.NONE, AuthStrategy.BROWSER_SESSION}:
                accounts = oauth_broker.list_accounts(provider)
                chosen = None
                scope_set = set(required_scopes or [])
                for account in accounts:
                    granted = set(account.granted_scopes or [])
                    if account.is_ready and (not scope_set or scope_set.issubset(granted)):
                        chosen = account
                        break
                if chosen is None and accounts:
                    chosen = accounts[0]
                if chosen is not None:
                    auth_resolution = {
                        "account_alias": chosen.account_alias,
                        "display_name": chosen.display_name,
                        "email": chosen.email,
                        "auth_state": str(chosen.status),
                        "fallback_mode": str(chosen.fallback_mode.value if hasattr(chosen.fallback_mode, "value") else chosen.fallback_mode),
                        "granted_scopes": list(chosen.granted_scopes or []),
                        "missing_scopes": sorted(list(scope_set.difference(set(chosen.granted_scopes or [])))) if scope_set else [],
                    }
                else:
                    auth_resolution = {
                        "account_alias": "default",
                        "auth_state": "needs_input",
                        "fallback_mode": str(fallback_policy.value),
                        "granted_scopes": [],
                        "missing_scopes": list(required_scopes or []),
                    }
        except Exception:
            auth_resolution = {}

        return provider, integration_type, auth_strategy, fallback_policy, required_scopes, list(dict.fromkeys([*dependencies, *python_dependencies])), connector_name, auth_resolution

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

        provider, integration_type, auth_strategy, fallback_policy, required_scopes, dependencies, connector_name, auth_resolution = self._provider_and_type(
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
            if provider == "x":
                api_base_urls = ["https://api.x.com", "https://api.twitter.com"]
            elif provider == "instagram":
                api_base_urls = ["https://graph.facebook.com", "https://graph.instagram.com"]
            elif provider == "whatsapp":
                api_base_urls = ["https://graph.facebook.com"]
            else:
                api_base_urls = ["https://api.x.com", "https://graph.facebook.com"]
        elif integration_type == IntegrationType.API:
            if provider == "google":
                if any(token in low for token in ("docs", "document", "workspace")):
                    api_base_urls = ["https://docs.googleapis.com", "https://www.googleapis.com/drive"]
                elif any(token in low for token in ("sheets", "spreadsheet", "sheet")):
                    api_base_urls = ["https://sheets.googleapis.com", "https://www.googleapis.com/drive"]
                elif any(token in low for token in ("slides", "presentation", "deck")):
                    api_base_urls = ["https://slides.googleapis.com", "https://www.googleapis.com/drive"]
                elif any(token in low for token in ("chat", "workspace chat")):
                    api_base_urls = ["https://chat.googleapis.com", "https://www.googleapis.com"]
                elif any(token in low for token in ("drive", "file", "document")):
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
                "auth_resolution": dict(auth_resolution or {}),
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
                "auth_resolution": dict(auth_resolution or {}),
            },
        )
        return capability

    def resolve_connection_plan(
        self,
        *,
        app_name: str = "",
        provider: str = "",
        scopes: list[str] | None = None,
        mode: str = "auto",
        account_alias: str = "default",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        requested_app = str(app_name or "").strip()
        requested_provider = str(provider or "").strip().lower()
        requested_scopes = normalize_items(scopes or [])
        inferred_provider = _infer_provider_from_app_name(requested_app)
        skill_context = {
            "provider": requested_provider or inferred_provider,
            "required_scopes": list(requested_scopes),
            "account_alias": account_alias,
            "mode": mode,
            "name": requested_app or requested_provider,
            **dict(extra or {}),
        }
        capability = self.resolve(requested_app or requested_provider or "", {"skill": skill_context})
        resolved_provider = requested_provider or inferred_provider or str(capability.provider or "").strip().lower()
        if resolved_provider == "gmail":
            resolved_provider = "google"
        resolved_app = requested_app or str(capability.name or capability.connector_name or resolved_provider or "integration").strip()
        resolved_scopes = list(requested_scopes or list(capability.required_scopes or []))
        auth_resolution = dict((capability.metadata or {}).get("auth_resolution") or {})
        suggested_alias = str(auth_resolution.get("account_alias") or account_alias or "default").strip() or "default"
        if suggested_alias == "default" and account_alias and account_alias != "default":
            suggested_alias = str(account_alias or "default").strip() or "default"
        return {
            "app_name": resolved_app,
            "provider": resolved_provider,
            "connector_name": str(capability.connector_name or resolved_provider or "connector").strip(),
            "integration_type": capability.integration_type,
            "required_scopes": resolved_scopes,
            "auth_strategy": capability.auth_strategy,
            "fallback_policy": capability.fallback_policy,
            "account_alias": suggested_alias,
            "multi_agent_recommended": bool(capability.multi_agent_recommended),
            "real_time": bool(capability.real_time),
            "approval_level": int(capability.approval_level or 0),
            "supported_platforms": list(capability.supported_platforms or []),
            "dependencies": list(capability.dependencies or []),
            "python_dependencies": list(capability.python_dependencies or []),
            "os_dependencies": list(capability.os_dependencies or []),
            "post_install": list(capability.post_install or []),
            "trust_level": str(capability.trust_level or "trusted"),
            "workflow_bundle": capability.workflow_bundle,
            "capability": capability,
            "auth_resolution": auth_resolution,
            "mode": mode,
            "resolved_from": {
                "input": requested_app or requested_provider,
                "provider": requested_provider,
                "scopes": list(requested_scopes),
            },
            "metadata": dict(extra or {}),
        }


integration_registry = IntegrationRegistry()
