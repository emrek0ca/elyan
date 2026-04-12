"""schedule.py — natural-language routine creation shortcut."""

from __future__ import annotations

import json
from typing import Any, Dict

from core.scheduler.routine_engine import routine_engine

from . import routines


def _emit_json(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _joined_text(args) -> str:
    parts = list(getattr(args, "text", []) or [])
    return " ".join(str(part or "").strip() for part in parts if str(part or "").strip()).strip()


def _build_payload(args, text: str) -> dict[str, Any]:
    return {
        "text": text,
        "name": str(getattr(args, "name", "") or "").strip(),
        "expression": str(getattr(args, "expression", "") or "").strip(),
        "report_channel": str(getattr(args, "report_channel", "telegram") or "telegram").strip() or "telegram",
        "report_chat_id": str(getattr(args, "report_chat_id", "") or "").strip(),
        "enabled": not bool(getattr(args, "disabled", False)),
        "created_by": "cli-schedule",
        "panels": routines._parse_panels(getattr(args, "panels", "")),
    }


def run(args):
    text = _joined_text(args)
    as_json = bool(getattr(args, "json", False))
    if not text:
        message = "Metin gerekli. Örnek: elyan schedule Her gün saat 09:00 günlük özet gönder"
        if as_json:
            _emit_json({"ok": False, "error": message})
            return
        print(message)
        return

    payload = _build_payload(args, text)
    port = routines._port(args)
    response = routines._api_request("POST", "/api/routines/from-text", payload=payload, port=port)

    if response["ok"]:
        routine = response["data"].get("routine", {})
        if as_json:
            _emit_json({"ok": True, "mode": "gateway", "routine": routine})
            return
        print(f"✅  Zamanlandı: {routine.get('id')} — {routine.get('name')}")
        return

    if response["status"] != 0:
        error = response["data"].get("error", "unknown")
        if as_json:
            _emit_json({"ok": False, "mode": "gateway", "error": error, "status": response["status"]})
            return
        print(f"❌  Rutin oluşturulamadı: {error}")
        return

    routine = routine_engine.create_from_text(
        text=text,
        enabled=payload["enabled"],
        created_by=str(payload["created_by"]),
        report_chat_id=str(payload["report_chat_id"]),
        report_channel=str(payload["report_channel"]),
        expression=str(payload["expression"]),
        name=str(payload["name"]),
        panels=payload["panels"],
    )
    if as_json:
        _emit_json({"ok": True, "mode": "local", "routine": routine})
        return
    print(f"✅  Yerel zamanlandı: {routine.get('id')} — {routine.get('name')}")
