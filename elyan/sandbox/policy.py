from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _default_image(language: str) -> str:
    lang = str(language or "").strip().lower()
    if lang in {"javascript", "node", "js"}:
        return "node:20-slim"
    if lang in {"shell", "sh", "bash"}:
        return "alpine:3.19"
    return "python:3.12-slim"


class SandboxConfig(BaseModel):
    image: str = "python:3.12-slim"
    language: str = "shell"
    command: str = ""
    memory_limit: str = "512m"
    cpu_limit: float = 0.5
    pids_limit: int = 64
    network: bool = False
    read_only: bool = True
    user: str = "nobody"
    working_dir: str = "/workspace"
    env: dict[str, str] = Field(default_factory=dict)
    volumes: dict[str, str] = Field(default_factory=dict)
    tmpfs: list[str] = Field(default_factory=lambda: ["/tmp"])
    cap_drop: list[str] = Field(default_factory=lambda: ["ALL"])
    security_opt: list[str] = Field(default_factory=lambda: ["no-new-privileges"])
    timeout: int = 30
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


def default_sandbox_config(
    *,
    language: str = "shell",
    image: str = "",
    command: str = "",
    network: bool = False,
    read_only: bool = True,
    timeout: int = 30,
    volumes: dict[str, str] | None = None,
    env: dict[str, str] | None = None,
    working_dir: str = "/workspace",
    metadata: dict[str, Any] | None = None,
) -> SandboxConfig:
    payload = {
        "image": str(image or _default_image(language)),
        "language": str(language or "shell").strip().lower() or "shell",
        "command": str(command or ""),
        "network": bool(network),
        "read_only": bool(read_only),
        "timeout": max(1, int(timeout or 30)),
        "volumes": dict(volumes or {}),
        "env": dict(env or {}),
        "working_dir": str(working_dir or "/workspace"),
        "metadata": dict(metadata or {}),
    }
    return SandboxConfig.model_validate(payload)


def merge_sandbox_config(*configs: Any) -> SandboxConfig:
    payload: dict[str, Any] = {}
    for config in configs:
        if config is None:
            continue
        if isinstance(config, SandboxConfig):
            payload.update(config.model_dump())
            continue
        if hasattr(config, "model_dump"):
            try:
                payload.update(dict(config.model_dump()))
                continue
            except Exception:
                pass
        if isinstance(config, dict):
            payload.update(config)
    return SandboxConfig.model_validate(payload or {})


def sandbox_config_for_action(
    action: dict[str, Any] | None = None,
    *,
    skill_name: str = "",
    default_language: str = "shell",
) -> SandboxConfig:
    payload = dict(action or {})
    language = str(payload.get("language") or default_language or "shell").strip().lower() or "shell"
    image = str(payload.get("image") or "").strip()
    command = str(payload.get("command") or payload.get("code") or payload.get("script") or "").strip()
    network = bool(payload.get("needs_network", payload.get("network", False)))
    read_only = bool(payload.get("read_only", True))
    workspace_dir = str(payload.get("workspace_dir") or payload.get("workspace") or "").strip()
    volumes = dict(payload.get("volumes") or {})
    if workspace_dir:
        volumes[str(Path(workspace_dir).expanduser().resolve())] = "/workspace"
    metadata = dict(payload.get("metadata") or {})
    metadata.setdefault("skill_name", str(skill_name or ""))
    metadata.setdefault("action_type", str(payload.get("type") or payload.get("action") or ""))
    return default_sandbox_config(
        language=language,
        image=image,
        command=command,
        network=network,
        read_only=read_only,
        timeout=int(payload.get("timeout") or payload.get("sandbox_timeout") or 30),
        volumes=volumes,
        env=dict(payload.get("env") or {}),
        working_dir=str(payload.get("working_dir") or "/workspace"),
        metadata=metadata,
    )
