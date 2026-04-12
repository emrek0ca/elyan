"""Unified status for CLI, desktop, and messaging surfaces."""
from __future__ import annotations

import json
import os
from typing import Any

from core.platforms_overview import build_platforms_payload, get_gateway_snapshot, read_local_config


def _live_channel_states(gateway_running: bool) -> dict[str, dict[str, Any]]:
    if not gateway_running:
        return {}
    try:
        from cli.commands import gateway as gateway_cmd

        payload = gateway_cmd._fetch_gateway_channels(int(os.environ.get("ELYAN_PORT", "18789") or "18789"))
        if not payload.get("ok"):
            return {}
        items = payload.get("channels", [])
        if not isinstance(items, list):
            return {}
        return {
            str(item.get("type") or "").strip().lower(): item
            for item in items
            if isinstance(item, dict) and str(item.get("type") or "").strip()
        }
    except Exception:
        return {}


def _build_payload() -> dict[str, Any]:
    gateway = get_gateway_snapshot()
    return build_platforms_payload(
        config=read_local_config(),
        gateway=gateway,
        live_channels=list(_live_channel_states(bool(gateway["running"])).values()),
    )


def run(args) -> int:
    payload = _build_payload()
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    gateway = payload["gateway"]
    summary = payload["summary"]
    print("Elyan platforms")
    print(f"Gateway: {'active' if gateway['running'] else 'inactive'}" + (f" (PID {gateway['pid']})" if gateway.get("pid") else ""))
    print(f"Surfaces: {summary['active']} active · {summary['connected_channels']} connected channels")
    print("")
    print(f"{'SURFACE':<12} {'STATUS':<16} {'DETAIL':<18} NEXT")
    print("─" * 88)
    for item in payload["surfaces"]:
        print(f"{item['label']:<12} {item['status']:<16} {str(item['detail'] or '-'):18.18} {item['next_action']}")
    return 0
