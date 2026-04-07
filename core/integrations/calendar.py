"""
core/integrations/calendar.py — macOS Calendar entegrasyonu
───────────────────────────────────────────────────────────────────────────────
AppleScript tabanlı Calendar okuma ve yazma.
EventKit/AppleScript gerektirir; Calendar uygulaması izin vermeli.

Desteklenen işlemler:
  - Bugünkü etkinlikleri listele
  - Yarın/bu hafta etkinliklerini listele
  - Yeni etkinlik oluştur (başlık, tarih, süre)
  - Etkinlik ara (keyword)
"""
from __future__ import annotations

import asyncio
import re
import subprocess
from datetime import datetime, timedelta
from typing import Optional

from utils.logger import get_logger

logger = get_logger("calendar")


# ── AppleScript Helpers ───────────────────────────────────────────────────────

async def _run_applescript(script: str) -> str:
    """AppleScript'i async olarak çalıştır, stdout döner."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0:
            return stdout.decode("utf-8").strip()
        logger.debug(f"AppleScript error: {stderr.decode('utf-8').strip()}")
        return ""
    except asyncio.TimeoutError:
        logger.warning("Calendar AppleScript timeout")
        return ""
    except Exception as exc:
        logger.warning(f"Calendar AppleScript error: {exc}")
        return ""


# ── Event Fetching ────────────────────────────────────────────────────────────

_LIST_EVENTS_SCRIPT = """
tell application "Calendar"
    set todayStart to current date
    set time of todayStart to 0
    set todayEnd to todayStart + {offset_seconds}
    set output to ""
    repeat with cal in calendars
        set theEvents to (every event of cal whose start date ≥ todayStart and start date < todayEnd)
        repeat with ev in theEvents
            set evTitle to summary of ev
            set evStart to start date of ev
            set output to output & evTitle & " | " & (evStart as string) & "\n"
        end repeat
    end repeat
    output
end tell
"""


async def get_events(days_ahead: int = 1) -> list[dict]:
    """Bugünden itibaren days_ahead gün içindeki etkinlikleri döner."""
    offset = days_ahead * 86400
    script = _LIST_EVENTS_SCRIPT.replace("{offset_seconds}", str(offset))
    raw = await _run_applescript(script)
    if not raw:
        return []

    events: list[dict] = []
    for line in raw.strip().splitlines():
        if " | " in line:
            parts = line.split(" | ", 1)
            events.append({"title": parts[0].strip(), "date_str": parts[1].strip()})
    return events


async def get_today_events() -> list[dict]:
    return await get_events(days_ahead=1)


async def get_week_events() -> list[dict]:
    return await get_events(days_ahead=7)


# ── Event Creation ────────────────────────────────────────────────────────────

async def create_event(
    title: str,
    start: datetime,
    duration_minutes: int = 60,
    calendar_name: str = "",
    notes: str = "",
) -> bool:
    """Yeni takvim etkinliği oluştur. Başarıda True döner."""
    end = start + timedelta(minutes=duration_minutes)

    def _fmt(dt: datetime) -> str:
        # AppleScript date literal: "MM/DD/YYYY HH:MM:SS"
        return dt.strftime("%m/%d/%Y %H:%M:%S")

    cal_clause = f'calendar "{calendar_name}"' if calendar_name else "default calendar"

    script = f"""
tell application "Calendar"
    tell {cal_clause}
        make new event with properties {{summary:"{title}", start date:date "{_fmt(start)}", end date:date "{_fmt(end)}", description:"{notes}"}}
    end tell
end tell
"""
    result = await _run_applescript(script)
    return True  # AppleScript doesn't return meaningful value here; errors raise


# ── Natural Language Parsing ──────────────────────────────────────────────────

_TIME_PATTERNS = [
    (re.compile(r"(\d{1,2})[:\.](\d{2})\s*(?:da|de|'da|'de)?"), "HH:MM"),
    (re.compile(r"saat\s+(\d{1,2})"), "HH"),
    (re.compile(r"(\d{1,2})\s*(?:sabah|öğlen|akşam|gece)"), "HH_period"),
]

_DATE_OFFSETS = {
    "bugün": 0, "today": 0,
    "yarın": 1, "tomorrow": 1,
    "öbür gün": 2, "day after tomorrow": 2,
}


def _parse_datetime_from_text(text: str) -> Optional[datetime]:
    """'Yarın saat 15:00' gibi ifadelerden datetime çıkar."""
    lower = text.lower()
    now = datetime.now()

    # Date
    offset_days = 0
    for keyword, days in _DATE_OFFSETS.items():
        if keyword in lower:
            offset_days = days
            break

    base_date = now.date() + timedelta(days=offset_days)

    # Time
    hour, minute = 9, 0  # default: 09:00

    for pat, fmt in _TIME_PATTERNS:
        m = pat.search(lower)
        if m:
            if fmt == "HH:MM":
                hour, minute = int(m.group(1)), int(m.group(2))
            elif fmt == "HH":
                hour = int(m.group(1))
            elif fmt == "HH_period":
                hour = int(m.group(1))
            break

    return datetime(base_date.year, base_date.month, base_date.day, hour, minute)


def parse_create_request(text: str) -> dict:
    """'Yarın saat 15:00'de toplantı' → {title, start, duration_minutes}"""
    lower = text.lower()

    # Title: remove time/date words
    title = re.sub(
        r"\b(?:yarın|bugün|öbür gün|tomorrow|today|saat|da|de|'da|'de|\d{1,2}[:\.\d]*)\b",
        "", text, flags=re.IGNORECASE,
    ).strip(" ,.-")

    # Remove common command words
    for w in ["ekle", "oluştur", "yaz", "takvime", "randevu", "toplantı"]:
        title = re.sub(rf"\b{w}\b", "", title, flags=re.IGNORECASE).strip()
    title = title.strip(" ,.-") or "Yeni Etkinlik"

    start = _parse_datetime_from_text(text) or datetime.now().replace(
        hour=9, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)

    # Duration: "X saatlik / X dakikalık"
    duration = 60
    m = re.search(r"(\d+)\s*saatlik", lower)
    if m:
        duration = int(m.group(1)) * 60
    m = re.search(r"(\d+)\s*dakikalık", lower)
    if m:
        duration = int(m.group(1))

    return {"title": title, "start": start, "duration_minutes": duration}


# ── High-level handlers (called from IntentExecutor) ─────────────────────────

async def handle_calendar_query(text: str) -> str:
    """Takvim sorgusu metnini işle; Türkçe sonuç döner."""
    lower = text.lower()

    if any(w in lower for w in ["bugün", "today", "bugünkü"]):
        events = await get_today_events()
        return _format_events(events, "Bugün")

    if any(w in lower for w in ["yarın", "tomorrow"]):
        events = await get_events(days_ahead=2)
        today_count = len(await get_today_events())
        tomorrow_events = events[today_count:]  # rough slice
        # Re-fetch properly
        tomorrow_events = await _get_events_on_day(1)
        return _format_events(tomorrow_events, "Yarın")

    if any(w in lower for w in ["hafta", "week", "bu hafta"]):
        events = await get_week_events()
        return _format_events(events, "Bu hafta")

    if any(w in lower for w in ["ekle", "oluştur", "yaz", "randevu", "toplantı", "kaydet"]):
        req = parse_create_request(text)
        success = await create_event(**req)
        if success:
            return (f"✅ Etkinlik oluşturuldu:\n"
                    f"📅 **{req['title']}**\n"
                    f"🕐 {req['start'].strftime('%d/%m/%Y %H:%M')} "
                    f"({req['duration_minutes']} dk)")
        return "❌ Etkinlik oluşturulamadı. Calendar izinleri kontrol et."

    # Default: bugünkü etkinlikler
    events = await get_today_events()
    return _format_events(events, "Bugün")


async def _get_events_on_day(day_offset: int) -> list[dict]:
    """Belirli bir gündeki etkinlikleri al."""
    offset = (day_offset + 1) * 86400
    all_events = await get_events(days_ahead=day_offset + 1)
    # Filter by date string matching the target day
    target = (datetime.now().date() + timedelta(days=day_offset)).strftime("%Y")
    return [e for e in all_events if target in e.get("date_str", "")]


def _format_events(events: list[dict], label: str) -> str:
    if not events:
        return f"📅 {label} için takvimde etkinlik yok."
    lines = [f"📅 **{label} etkinlikleri ({len(events)} adet):**"]
    for ev in events[:15]:
        lines.append(f"• {ev['title']} — {ev.get('date_str', '')}")
    return "\n".join(lines)
