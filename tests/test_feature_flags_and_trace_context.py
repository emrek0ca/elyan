from __future__ import annotations

import json

from core.feature_flags import FeatureFlagRegistry
from core.observability.logger import StructuredLogger
from core.observability.trace_context import (
    activate_trace_context,
    build_trace_context,
    get_trace_context,
    reset_trace_context,
)


def test_feature_flag_runtime_policy_precedence_over_defaults() -> None:
    registry = FeatureFlagRegistry()
    enabled = registry.is_enabled(
        "execution_guard_shadow",
        runtime_policy={"feature_flags": {"execution_guard_shadow": True}},
    )
    assert enabled is True


def test_feature_flag_env_override(monkeypatch) -> None:
    monkeypatch.setenv("ELYAN_FF_MODEL_ROUTE_POLICY_SHADOW", "true")
    registry = FeatureFlagRegistry()
    resolved = registry.resolve("model_route_policy_shadow")
    assert resolved["enabled"] is True
    assert resolved["source"] == "env"


def test_build_trace_context_sanitizes_and_binds_ids() -> None:
    context = build_trace_context(
        method="POST",
        path="/api/v1/inbox/events?workspace_id=ws_123",
        headers={"X-Request-ID": "req with spaces"},
        query={"workspace_id": "ws_123"},
    )
    token = activate_trace_context(context)
    try:
        current = get_trace_context()
        assert current is not None
        assert current.request_id.startswith("req-with-spaces")
        assert current.workspace_id == "ws_123"
    finally:
        reset_trace_context(token)


def test_structured_logger_enriches_with_active_trace_context() -> None:
    context = build_trace_context(
        method="GET",
        path="/api/v1/test",
        headers={"X-Elyan-Trace-Id": "trace_demo", "X-Elyan-Request-Id": "req_demo"},
        workspace_id="workspace-alpha",
    )
    captured: list[str] = []
    token = activate_trace_context(context)
    try:
        logger = StructuredLogger("test_component")
        logger._logger.info = captured.append
        logger.log_event("test.event", {"ok": True})
    finally:
        reset_trace_context(token)

    assert captured
    payload = json.loads(captured[0])
    assert payload["trace_id"] == "trace_demo"
    assert payload["request_id"] == "req_demo"
    assert payload["workspace_id"] == "workspace-alpha"
