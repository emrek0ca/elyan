from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FeatureFlagDefinition:
    name: str
    default: bool
    description: str = ""
    owner: str = "platform"
    stage: str = "runtime"


_DEFAULT_FEATURE_FLAGS: dict[str, FeatureFlagDefinition] = {
    "gateway_request_tracing": FeatureFlagDefinition(
        name="gateway_request_tracing",
        default=True,
        description="Attach canonical request and trace IDs to gateway request context and responses.",
    ),
    "structured_log_trace_enrichment": FeatureFlagDefinition(
        name="structured_log_trace_enrichment",
        default=True,
        description="Enrich structured logs with active trace context when available.",
    ),
    "execution_guard_shadow": FeatureFlagDefinition(
        name="execution_guard_shadow",
        default=False,
        description="Shadow-mode execution guard for side-effectful actions.",
    ),
    "model_route_policy_shadow": FeatureFlagDefinition(
        name="model_route_policy_shadow",
        default=False,
        description="Shadow-mode canonical model routing policy.",
    ),
    "ui_observation_shadow": FeatureFlagDefinition(
        name="ui_observation_shadow",
        default=False,
        description="Shadow-mode multimodal UI observation bundle.",
    ),
    "context_assembly_shadow": FeatureFlagDefinition(
        name="context_assembly_shadow",
        default=False,
        description="Shadow-mode freshness-aware context assembly.",
    ),
    "billing_reconciliation_bridge_shadow": FeatureFlagDefinition(
        name="billing_reconciliation_bridge_shadow",
        default=True,
        description="Observe scoped runtime token/cost aggregation for post-run billing reconciliation.",
    ),
    "billing_reconciliation_bridge_apply": FeatureFlagDefinition(
        name="billing_reconciliation_bridge_apply",
        default=True,
        description="Apply automatic scoped billing reconciliation from aggregated runtime token/cost usage.",
    ),
}


def _normalize_name(name: str) -> str:
    return str(name or "").strip().lower().replace("-", "_")


def _env_key(name: str) -> str:
    return f"ELYAN_FF_{_normalize_name(name).upper()}"


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw in {"1", "true", "on", "yes", "enabled"}:
        return True
    if raw in {"0", "false", "off", "no", "disabled"}:
        return False
    return None


class FeatureFlagRegistry:
    def __init__(self) -> None:
        self._definitions = dict(_DEFAULT_FEATURE_FLAGS)

    def register(self, definition: FeatureFlagDefinition) -> None:
        self._definitions[_normalize_name(definition.name)] = definition

    def get_definition(self, name: str) -> FeatureFlagDefinition:
        normalized = _normalize_name(name)
        definition = self._definitions.get(normalized)
        if definition is not None:
            return definition
        return FeatureFlagDefinition(name=normalized, default=False)

    def list_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "name": item.name,
                "default": item.default,
                "description": item.description,
                "owner": item.owner,
                "stage": item.stage,
            }
            for item in sorted(self._definitions.values(), key=lambda item: item.name)
        ]

    @staticmethod
    def _resolve_runtime_policy(runtime_policy: Any, name: str) -> tuple[bool | None, str]:
        normalized = _normalize_name(name)
        if not isinstance(runtime_policy, dict):
            return None, ""
        for key in ("feature_flags", "flags"):
            section = runtime_policy.get(key)
            if not isinstance(section, dict):
                continue
            value = section.get(normalized)
            parsed = _parse_bool(value)
            if parsed is not None:
                return parsed, f"runtime_policy.{key}"
        return None, ""

    @staticmethod
    def _resolve_config_manager(name: str, *, user_id: str = "", context: dict[str, Any] | None = None) -> tuple[bool | None, str]:
        try:
            from core.config_manager import get_config_manager

            manager = get_config_manager()
            flags = manager.get_feature_flags()
            normalized = _normalize_name(name)
            if normalized not in flags:
                return None, ""
            return bool(manager.is_feature_enabled(normalized, user_id=user_id or None, context=context or None)), "config_manager"
        except Exception:
            return None, ""

    @staticmethod
    def _resolve_elyan_config(name: str) -> tuple[bool | None, str]:
        try:
            from config.elyan_config import elyan_config

            normalized = _normalize_name(name)
            value = elyan_config.get(f"agent.flags.{normalized}", None)
            parsed = _parse_bool(value)
            if parsed is not None:
                return parsed, "elyan_config.agent.flags"
        except Exception:
            return None, ""
        return None, ""

    def resolve(
        self,
        name: str,
        *,
        runtime_policy: dict[str, Any] | None = None,
        user_id: str = "",
        context: dict[str, Any] | None = None,
        default: bool | None = None,
    ) -> dict[str, Any]:
        definition = self.get_definition(name)
        normalized = _normalize_name(name)

        resolved, source = self._resolve_runtime_policy(runtime_policy, normalized)
        if resolved is not None:
            return {"name": normalized, "enabled": resolved, "source": source, "default": definition.default}

        env_value = _parse_bool(os.getenv(_env_key(normalized), ""))
        if env_value is not None:
            return {"name": normalized, "enabled": env_value, "source": "env", "default": definition.default}

        resolved, source = self._resolve_config_manager(normalized, user_id=user_id, context=context)
        if resolved is not None:
            return {"name": normalized, "enabled": resolved, "source": source, "default": definition.default}

        resolved, source = self._resolve_elyan_config(normalized)
        if resolved is not None:
            return {"name": normalized, "enabled": resolved, "source": source, "default": definition.default}

        fallback = definition.default if default is None else bool(default)
        return {"name": normalized, "enabled": fallback, "source": "default", "default": definition.default}

    def is_enabled(
        self,
        name: str,
        *,
        runtime_policy: dict[str, Any] | None = None,
        user_id: str = "",
        context: dict[str, Any] | None = None,
        default: bool | None = None,
    ) -> bool:
        return bool(
            self.resolve(
                name,
                runtime_policy=runtime_policy,
                user_id=user_id,
                context=context,
                default=default,
            ).get("enabled", False)
        )


_feature_flag_registry: FeatureFlagRegistry | None = None


def get_feature_flag_registry() -> FeatureFlagRegistry:
    global _feature_flag_registry
    if _feature_flag_registry is None:
        _feature_flag_registry = FeatureFlagRegistry()
    return _feature_flag_registry
