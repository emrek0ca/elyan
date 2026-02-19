"""Telegram routine automation commands."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

import aiohttp
from telegram import Update
from telegram.ext import ContextTypes

from config.elyan_config import elyan_config
from utils.logger import get_logger

logger = get_logger("telegram_routines")


def _gateway_port() -> int:
    return int(elyan_config.get("gateway.port", 18789))


async def _api_request(method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"http://127.0.0.1:{_gateway_port()}{path}"
    timeout = aiohttp.ClientTimeout(total=12)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if method.upper() == "GET":
                async with session.get(url) as resp:
                    data = await resp.json()
                    return {"ok": resp.status < 300, "status": resp.status, "data": data}
            if method.upper() == "POST":
                async with session.post(url, json=payload or {}) as resp:
                    data = await resp.json()
                    return {"ok": resp.status < 300, "status": resp.status, "data": data}
            if method.upper() == "DELETE":
                async with session.delete(url) as resp:
                    data = await resp.json()
                    return {"ok": resp.status < 300, "status": resp.status, "data": data}
        return {"ok": False, "status": 0, "data": {"error": "unsupported method"}}
    except Exception as e:
        return {"ok": False, "status": 0, "data": {"error": str(e)}}


def _parse_hhmm_to_cron(hhmm: str) -> Optional[str]:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(hhmm or ""))
    if not m:
        return None
    h = int(m.group(1))
    minute = int(m.group(2))
    if h < 0 or h > 23 or minute < 0 or minute > 59:
        return None
    return f"{minute} {h} * * *"


def _split_steps(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    parts = re.split(r"(?:\n|;)+", raw)
    return [p.strip() for p in parts if p.strip()]


def _split_panels(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    items = re.split(r"(?:\n|;|,)+", raw)
    out: list[str] = []
    seen = set()
    for item in items:
        url = item.strip()
        if not url:
            continue
        if not url.startswith("http://") and not url.startswith("https://"):
            if "." in url and " " not in url:
                url = "https://" + url
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


async def cmd_routine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List routines and short usage."""
    resp = await _api_request("GET", "/api/routines")
    if not resp["ok"]:
        await update.message.reply_text(f"Rutin API hatası: {resp['data'].get('error', 'unknown')}", parse_mode=None)
        return

    data = resp["data"]
    routines = data.get("routines", [])
    if not routines:
        text = (
            "Kayıtlı rutin yok.\n\n"
            "Eklemek için:\n"
            "/routine_add 09:00 Sabah Raporu | Tarayıcıyı aç; Paneli kontrol et; Excel oluştur; Özet rapor hazırla"
        )
        await update.message.reply_text(text, parse_mode=None)
        return

    text = ["Rutinler:"]
    for r in routines[:20]:
        state = "aktif" if r.get("enabled", True) else "pasif"
        text.append(f"- {r.get('id')} | {state} | {r.get('expression')} | {r.get('name')}")
    text.append("\nKomutlar:")
    text.append("/routine_run <id>")
    text.append("/routine_on <id> /routine_off <id>")
    text.append("/routine_rm <id>")
    text.append("/routine_templates")
    text.append("/routine_from <template_id> <HH:MM> [panel1,panel2]")
    await update.message.reply_text("\n".join(text), parse_mode=None)


async def cmd_routine_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Add routine by HH:MM syntax:
    /routine_add 09:00 Sabah Kontrol | step1; step2; step3
    """
    raw = " ".join(context.args or []).strip()
    if not raw:
        await update.message.reply_text(
            "Kullanım:\n/routine_add 09:00 Sabah Raporu | Tarayıcıyı aç; Paneli kontrol et; Excel oluştur; Özet rapor hazırla",
            parse_mode=None,
        )
        return

    m = re.match(r"^(\d{1,2}:\d{2})\s+(.+)$", raw)
    if not m:
        await update.message.reply_text("Hatalı format. İlk alan saat olmalı (HH:MM).", parse_mode=None)
        return

    hhmm = m.group(1)
    rest = m.group(2).strip()
    if "|" not in rest:
        await update.message.reply_text("Formatta '|' eksik. Örn: Ad | adım1; adım2 || panel1,panel2", parse_mode=None)
        return
    # Optional panels block: Name | step1;step2 || panel1,panel2
    if "||" in rest:
        left, panel_raw = [x.strip() for x in rest.split("||", 1)]
    else:
        left, panel_raw = rest, ""
    name, steps_text = [x.strip() for x in left.split("|", 1)]
    expression = _parse_hhmm_to_cron(hhmm)
    if not expression:
        await update.message.reply_text("Saat formatı geçersiz (HH:MM).", parse_mode=None)
        return

    steps = _split_steps(steps_text)
    if not name or not steps:
        await update.message.reply_text("Rutin adı ve en az bir adım gerekli.", parse_mode=None)
        return

    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    payload = {
        "name": name,
        "expression": expression,
        "steps": steps,
        "report_channel": "telegram",
        "report_chat_id": chat_id,
        "enabled": True,
        "created_by": str(update.effective_user.id if update.effective_user else "telegram"),
        "panels": _split_panels(panel_raw),
    }
    resp = await _api_request("POST", "/api/routines", payload=payload)
    if not resp["ok"]:
        await update.message.reply_text(f"Rutin eklenemedi: {resp['data'].get('error', 'unknown')}", parse_mode=None)
        return

    item = resp["data"].get("routine", {})
    await update.message.reply_text(
        f"Rutin eklendi:\nID: {item.get('id')}\nAd: {item.get('name')}\nSaat: {hhmm}\nAdım: {len(item.get('steps', []))}",
        parse_mode=None,
    )


async def cmd_routine_templates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    resp = await _api_request("GET", "/api/routines/templates")
    if not resp["ok"]:
        await update.message.reply_text(f"Template API hatası: {resp['data'].get('error', 'unknown')}", parse_mode=None)
        return
    templates = resp["data"].get("templates", [])
    if not templates:
        await update.message.reply_text("Template bulunamadı.", parse_mode=None)
        return
    lines = ["Mevcut rutin template'leri:"]
    for t in templates:
        lines.append(f"- {t.get('id')} | {t.get('name')} ({len(t.get('steps', []))} adım)")
    lines.append("\nKullanım: /routine_from <template_id> <HH:MM> [panel1,panel2]")
    await update.message.reply_text("\n".join(lines), parse_mode=None)


async def cmd_routine_from(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Create routine from template:
    /routine_from ecommerce-daily 09:00 seller.example.com,mail.example.com
    """
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Kullanım:\n/routine_from <template_id> <HH:MM> [panel1,panel2]\nÖrn: /routine_from ecommerce-daily 09:00 seller.example.com,mail.example.com",
            parse_mode=None,
        )
        return

    template_id = context.args[0].strip()
    hhmm = context.args[1].strip()
    expression = _parse_hhmm_to_cron(hhmm)
    if not expression:
        await update.message.reply_text("Saat formatı geçersiz (HH:MM).", parse_mode=None)
        return

    panel_raw = " ".join(context.args[2:]).strip()
    chat_id = str(update.effective_chat.id) if update.effective_chat else ""
    payload = {
        "template_id": template_id,
        "expression": expression,
        "report_channel": "telegram",
        "report_chat_id": chat_id,
        "enabled": True,
        "created_by": str(update.effective_user.id if update.effective_user else "telegram"),
        "panels": _split_panels(panel_raw),
    }
    resp = await _api_request("POST", "/api/routines/from-template", payload=payload)
    if not resp["ok"]:
        await update.message.reply_text(f"Template rutin eklenemedi: {resp['data'].get('error', 'unknown')}", parse_mode=None)
        return
    item = resp["data"].get("routine", {})
    await update.message.reply_text(
        f"Template rutin eklendi:\nID: {item.get('id')}\nAd: {item.get('name')}\nSaat: {hhmm}",
        parse_mode=None,
    )


async def cmd_routine_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rid = (context.args[0] if context.args else "").strip()
    if not rid:
        await update.message.reply_text("Kullanım: /routine_run <id>", parse_mode=None)
        return
    await update.message.reply_text("Rutin çalıştırılıyor...", parse_mode=None)
    resp = await _api_request("POST", "/api/routines/run", payload={"id": rid})
    if not resp["ok"]:
        await update.message.reply_text(f"Çalıştırılamadı: {resp['data'].get('error', 'unknown')}", parse_mode=None)
        return
    result = resp["data"].get("result", {})
    report = str(result.get("report", "") or "")
    head = f"{'OK' if result.get('success') else 'FAIL'} | {rid} | {result.get('duration_s', '?')}s"
    msg = f"{head}\n\n{report[:3000]}".strip()
    await update.message.reply_text(msg, parse_mode=None)


async def cmd_routine_rm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rid = (context.args[0] if context.args else "").strip()
    if not rid:
        await update.message.reply_text("Kullanım: /routine_rm <id>", parse_mode=None)
        return
    resp = await _api_request("DELETE", f"/api/routines/{rid}")
    if not resp["ok"]:
        await update.message.reply_text(f"Kaldırılamadı: {resp['data'].get('error', 'unknown')}", parse_mode=None)
        return
    await update.message.reply_text(f"Rutin kaldırıldı: {rid}", parse_mode=None)


async def cmd_routine_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rid = (context.args[0] if context.args else "").strip()
    if not rid:
        await update.message.reply_text("Kullanım: /routine_on <id>", parse_mode=None)
        return
    resp = await _api_request("POST", "/api/routines/toggle", payload={"id": rid, "enabled": True})
    if not resp["ok"]:
        await update.message.reply_text(f"Güncellenemedi: {resp['data'].get('error', 'unknown')}", parse_mode=None)
        return
    await update.message.reply_text(f"Rutin aktif: {rid}", parse_mode=None)


async def cmd_routine_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rid = (context.args[0] if context.args else "").strip()
    if not rid:
        await update.message.reply_text("Kullanım: /routine_off <id>", parse_mode=None)
        return
    resp = await _api_request("POST", "/api/routines/toggle", payload={"id": rid, "enabled": False})
    if not resp["ok"]:
        await update.message.reply_text(f"Güncellenemedi: {resp['data'].get('error', 'unknown')}", parse_mode=None)
        return
    await update.message.reply_text(f"Rutin pasif: {rid}", parse_mode=None)
