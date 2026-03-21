from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .policy import SandboxConfig, merge_sandbox_config


@dataclass(frozen=True)
class IsolationProfile:
    network_mode: str = "none"
    read_only: bool = True
    user: str = "nobody"
    cap_drop: tuple[str, ...] = ("ALL",)
    security_opt: tuple[str, ...] = ("no-new-privileges",)
    tmpfs: tuple[str, ...] = ("/tmp",)
    pids_limit: int = 64


_SAFE_VOLUME_ROOTS = (
    Path.home().expanduser(),
    Path("/tmp"),
    Path("/private"),
    Path("/var/tmp"),
)


def _safe_host_path(raw: str) -> str | None:
    path = str(raw or "").strip()
    if not path:
        return None
    try:
        resolved = Path(path).expanduser().resolve()
    except Exception:
        return None
    if not resolved.exists():
        return None
    if not any(str(resolved).startswith(str(root.resolve())) for root in _SAFE_VOLUME_ROOTS):
        return None
    return str(resolved)


def zero_permission_profile(config: SandboxConfig | dict[str, Any] | None = None) -> IsolationProfile:
    payload = merge_sandbox_config(config) if config is not None else SandboxConfig()
    return IsolationProfile(
        network_mode="bridge" if payload.network else "none",
        read_only=bool(payload.read_only),
        user=str(payload.user or "nobody"),
        cap_drop=tuple(payload.cap_drop or ["ALL"]),
        security_opt=tuple(payload.security_opt or ["no-new-privileges"]),
        tmpfs=tuple(payload.tmpfs or ["/tmp"]),
        pids_limit=max(16, int(payload.pids_limit or 64)),
    )


def sanitized_volumes(config: SandboxConfig | dict[str, Any] | None = None) -> dict[str, str]:
    payload = merge_sandbox_config(config) if config is not None else SandboxConfig()
    out: dict[str, str] = {}
    for host_path, container_path in dict(payload.volumes or {}).items():
        safe_host = _safe_host_path(host_path)
        safe_container = str(container_path or "").strip()
        if not safe_host or not safe_container:
            continue
        out[safe_host] = safe_container
    return out

