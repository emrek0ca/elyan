from __future__ import annotations

import os


def resolve_workspace_database_url(explicit_url: str = "") -> str:
    if explicit_url and str(explicit_url).strip():
        return str(explicit_url).strip()
    for key in (
        "ELYAN_SUPABASE_DATABASE_URL",
        "ELYAN_WORKSPACE_DATABASE_URL",
        "SUPABASE_DB_URL",
        "DATABASE_URL",
    ):
        value = str(os.getenv(key, "") or "").strip()
        if value:
            return value
    return ""


def resolve_workspace_auth_backend() -> str:
    backend = str(os.getenv("ELYAN_AUTH_BACKEND", "") or "").strip().lower()
    if backend in {"workspace", "supabase", "remote"}:
        return "workspace"
    return "local"


def resolve_workspace_database_mode(database_url: str = "") -> str:
    url = resolve_workspace_database_url(database_url).lower()
    if not url:
        return "disabled"
    if url.startswith("postgresql") or url.startswith("postgres"):
        return "supabase"
    if url.startswith("sqlite"):
        return "sqlite"
    return "generic"


def is_workspace_database_enabled(database_url: str = "") -> bool:
    return bool(resolve_workspace_database_url(database_url))


__all__ = [
    "is_workspace_database_enabled",
    "resolve_workspace_auth_backend",
    "resolve_workspace_database_mode",
    "resolve_workspace_database_url",
]
