from __future__ import annotations

import re
import time
import uuid
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from aiohttp import web


_TRACE_CONTEXT: ContextVar["TraceContext | None"] = ContextVar("elyan_trace_context", default=None)
_SAFE_ID_CHARS = re.compile(r"[^a-zA-Z0-9._:-]+")


def _sanitize_identifier(value: Any, *, prefix: str, length: int) -> str:
    raw = str(value or "").strip()
    if raw:
        raw = _SAFE_ID_CHARS.sub("-", raw).strip("-._:")
    if not raw:
        raw = f"{prefix}_{uuid.uuid4().hex[:length]}"
    return raw[: max(8, int(length))]


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    request_id: str
    session_id: str = ""
    workspace_id: str = ""
    source: str = ""
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_headers(self) -> dict[str, str]:
        headers = {
            "X-Elyan-Trace-Id": self.trace_id,
            "X-Elyan-Request-Id": self.request_id,
        }
        if self.session_id:
            headers["X-Elyan-Session-Id"] = self.session_id
        if self.workspace_id:
            headers["X-Elyan-Workspace-Id"] = self.workspace_id
        return headers


def build_trace_context(
    *,
    method: str = "",
    path: str = "",
    headers: Mapping[str, Any] | None = None,
    query: Mapping[str, Any] | None = None,
    cookies: Mapping[str, Any] | None = None,
    trace_id: str = "",
    request_id: str = "",
    session_id: str = "",
    workspace_id: str = "",
) -> TraceContext:
    header_map = headers or {}
    query_map = query or {}
    cookie_map = cookies or {}
    resolved_trace = (
        trace_id
        or header_map.get("X-Elyan-Trace-Id")
        or header_map.get("X-Trace-Id")
        or header_map.get("X-Request-ID")
        or ""
    )
    resolved_request = (
        request_id
        or header_map.get("X-Elyan-Request-Id")
        or header_map.get("X-Request-ID")
        or ""
    )
    resolved_session = (
        session_id
        or header_map.get("X-Elyan-Session-Id")
        or query_map.get("session_id")
        or ""
    )
    resolved_workspace = (
        workspace_id
        or header_map.get("X-Elyan-Workspace-Id")
        or query_map.get("workspace_id")
        or cookie_map.get("elyan_workspace_id")
        or ""
    )
    source = f"{str(method or '').upper()} {str(path or '').strip()}".strip()
    return TraceContext(
        trace_id=_sanitize_identifier(resolved_trace, prefix="trace", length=32),
        request_id=_sanitize_identifier(resolved_request, prefix="req", length=24),
        session_id=str(resolved_session or "").strip(),
        workspace_id=str(resolved_workspace or "").strip(),
        source=source,
    )


def activate_trace_context(context: TraceContext) -> Token:
    return _TRACE_CONTEXT.set(context)


def reset_trace_context(token: Token) -> None:
    _TRACE_CONTEXT.reset(token)


def get_trace_context() -> TraceContext | None:
    return _TRACE_CONTEXT.get()


def apply_trace_headers(response: web.StreamResponse, context: TraceContext) -> web.StreamResponse:
    if response is None:
        return response
    for key, value in context.to_headers().items():
        response.headers[key] = value
    return response
