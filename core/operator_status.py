from __future__ import annotations

import asyncio
from typing import Any

from config.settings_manager import SettingsPanel
from core.accuracy_speed_runtime import get_accuracy_speed_runtime
from core.computer_use_integration import get_computer_use_integration
from core.internet import get_internet_reach_runtime
from elyan.channels.mobile_dispatch import MobileDispatchBridge


async def get_operator_status() -> dict[str, Any]:
    settings = SettingsPanel()
    mobile = MobileDispatchBridge().get_dashboard_sessions()
    computer_use = await get_computer_use_integration().get_health_status()
    internet = get_internet_reach_runtime().get_health_status()
    speed = get_accuracy_speed_runtime().get_status()
    document_ingest = {
        "status": "healthy" if bool(settings.get("liteparse_enabled", True)) else "degraded",
        "liteparse_enabled": bool(settings.get("liteparse_enabled", True)),
        "vision_ocr_backend": str(settings.get("vision_ocr_backend", "auto") or "auto"),
        "vision_ocr_model": str(settings.get("vision_ocr_model", "glm-4.1v-9b-thinking") or "glm-4.1v-9b-thinking"),
        "current_lane": "verified_lane",
        "verification_state": "verified" if bool(settings.get("liteparse_enabled", True)) else "degraded",
        "average_latency_bucket": "steady",
    }
    summary = {
        "mobile_dispatch": mobile,
        "computer_use": computer_use,
        "internet_reach": internet,
        "document_ingest": document_ingest,
        "speed_runtime": speed,
    }
    overall = "healthy"
    if any(str((section or {}).get("status") or "").lower() in {"degraded", "unavailable", "failed"} for section in (computer_use, internet, document_ingest)):
        overall = "degraded"
    return {"status": overall, "summary": summary}


def get_operator_status_sync() -> dict[str, Any]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(get_operator_status())
    return {
        "status": "degraded",
        "summary": {
            "mobile_dispatch": {"status": "unknown"},
            "computer_use": {"status": "unknown"},
            "internet_reach": {"status": "unknown"},
            "document_ingest": {"status": "unknown"},
        },
    }


__all__ = ["get_operator_status", "get_operator_status_sync"]
