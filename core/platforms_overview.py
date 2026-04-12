"""Shared platform readiness snapshot for CLI, gateway, and desktop surfaces."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


KNOWN_CHANNELS = ("telegram", "discord", "whatsapp", "slack", "signal", "sms", "webchat")


def read_local_config() -> dict[str, Any]:
    config_file = Path.home() / ".elyan" / "elyan.json"
    if not config_file.exists():
        return {}
    try:
        payload = json.loads(config_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def get_gateway_snapshot() -> dict[str, Any]:
    pid_file = Path.home() / ".elyan" / "gateway.pid"
    running = False
    pid = None
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            running = True
        except (ValueError, ProcessLookupError, PermissionError):
            running = False
    return {"running": running, "pid": pid}


def desktop_available() -> bool:
    repo_root = Path(__file__).resolve().parents[1]
    return (repo_root / "apps" / "desktop").exists()


def normalize_channel_entries(config: dict[str, Any]) -> list[dict[str, Any]]:
    rows = config.get("channels", [])
    if not isinstance(rows, list):
        return []
    items: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        items.append(
            {
                "type": str(row.get("type") or "").strip().lower(),
                "id": str(row.get("id") or row.get("type") or "").strip(),
                "enabled": bool(row.get("enabled", False)),
                "mode": str(row.get("mode") or "").strip(),
            }
        )
    return items


def normalize_live_channels(rows: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        return {}
    items: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        channel_type = str(row.get("type") or "").strip().lower()
        if not channel_type:
            continue
        items[channel_type] = row
    return items


def build_platforms_payload(
    *,
    config: dict[str, Any] | None = None,
    gateway: dict[str, Any] | None = None,
    live_channels: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved_config = config if isinstance(config, dict) else read_local_config()
    resolved_gateway = gateway if isinstance(gateway, dict) else get_gateway_snapshot()
    channels = normalize_channel_entries(resolved_config)
    channel_by_type = {row["type"]: row for row in channels if row.get("type")}
    live_channel_map = normalize_live_channels(live_channels)

    surfaces = [
        {
            "name": "cli",
            "label": "CLI",
            "configured": True,
            "active": True,
            "status": "ready",
            "detail": "Local terminal surface",
            "next_action": "elyan chat",
        },
        {
            "name": "desktop",
            "label": "Desktop",
            "configured": desktop_available(),
            "active": bool(resolved_gateway.get("running")),
            "status": (
                "ready"
                if desktop_available() and resolved_gateway.get("running")
                else ("available" if desktop_available() else "missing")
            ),
            "detail": "Desktop app + operator UI",
            "next_action": "elyan desktop",
        },
    ]

    for channel_name in KNOWN_CHANNELS:
        row = channel_by_type.get(channel_name)
        live = live_channel_map.get(channel_name) or {}
        configured = row is not None
        enabled = bool(row.get("enabled")) if row else False
        live_status = str(live.get("status") or "").strip().lower()
        active = enabled and bool(resolved_gateway.get("running")) and live_status not in {
            "",
            "disabled",
            "disconnected",
            "offline",
            "failed",
        }
        status = (
            live_status
            if live_status
            else (
                "connected"
                if enabled and bool(resolved_gateway.get("running"))
                else ("configured" if enabled else ("disabled" if configured else "not_configured"))
            )
        )
        detail = str(live.get("detail") or "").strip() or ((row.get("mode") or row.get("id") or "-") if row else "-")
        surfaces.append(
            {
                "name": channel_name,
                "label": channel_name.capitalize(),
                "configured": configured,
                "active": active,
                "status": status,
                "detail": detail,
                "next_action": (
                    f"elyan channels add --type {channel_name}"
                    if not configured
                    else f"elyan channels {'enable' if not enabled else 'status'} {channel_name}"
                ),
            }
        )

    connected_channels = [item for item in surfaces if item["name"] in KNOWN_CHANNELS and item["active"]]
    configured_channels = [item for item in surfaces if item["name"] in KNOWN_CHANNELS and item["configured"]]

    return {
        "gateway": resolved_gateway,
        "surfaces": surfaces,
        "summary": {
            "active": sum(1 for item in surfaces if item["active"]),
            "configured_channels": len(configured_channels),
            "connected_channels": len(connected_channels),
            "connected_labels": [str(item["label"]) for item in connected_channels],
        },
    }
