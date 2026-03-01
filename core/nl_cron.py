"""
Natural Language Cron parser.
Örnek: "Her gün 09:00'da satış raporunu özetle otomasyonu kur"
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("nl_cron")


class NLCron:
    def __init__(self):
        self._day_map = {
            "pazartesi": 1,
            "salı": 2,
            "sali": 2,
            "çarşamba": 3,
            "carsamba": 3,
            "perşembe": 4,
            "persembe": 4,
            "cuma": 5,
            "cumartesi": 6,
            "pazar": 0,
            "monday": 1,
            "tuesday": 2,
            "wednesday": 3,
            "thursday": 4,
            "friday": 5,
            "saturday": 6,
            "sunday": 0,
        }

    @staticmethod
    def _clamp_time(hour: int, minute: int) -> tuple[int, int]:
        h = max(0, min(23, int(hour)))
        m = max(0, min(59, int(minute)))
        return h, m

    @staticmethod
    def _extract_task(raw_text: str, span: tuple[int, int]) -> str:
        text = str(raw_text or "").strip()
        if not text:
            return ""

        quoted_double = re.search(r"[\"“”]([^\"“”]{3,220})[\"“”]", text)
        if quoted_double:
            return str(quoted_double.group(1) or "").strip()
        quoted_single = re.search(r"'([^']{3,220})'", text)
        if quoted_single:
            return str(quoted_single.group(1) or "").strip()

        left = text[: span[0]]
        right = text[span[1] :]
        candidate = f"{left} {right}".strip()
        candidate = re.sub(r"^[\s,;:\-]+", "", candidate)
        candidate = re.sub(r"^[\s,;:\-]*(için|icin)\b", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(
            r"\b(otomasyonu?\s+kur(?:ulur)?|otomasyonu?\s+oluştur|otomasyonu?\s+ayarla|"
            r"schedule(?:\s+it)?|zamanla|planla)\b",
            " ",
            candidate,
            flags=re.IGNORECASE,
        )
        candidate = re.sub(r"^['’]?(?:de|da)\b", " ", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s+", " ", candidate).strip(" .,:;-")
        return candidate

    def _parse_weekly(self, text: str) -> Optional[Dict[str, Any]]:
        m = re.search(
            r"\b(?:her\s+(?:hafta\s+)?|haftada\s+bir\s+|weekly\s+)"
            r"(pazartesi|salı|sali|çarşamba|carsamba|perşembe|persembe|cuma|cumartesi|pazar|"
            r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
            r"(?:\s*(?:saat\s*)?(\d{1,2})(?:(?::|\.)(\d{2}))?\s*['’]?(?:de|da)?)?",
            text,
            flags=re.IGNORECASE,
        )
        if not m:
            return None

        day_key = str(m.group(1) or "").lower()
        day = self._day_map.get(day_key)
        if day is None:
            return None

        hour = int(m.group(2) or 9)
        minute = int(m.group(3) or 0)
        hour, minute = self._clamp_time(hour, minute)
        task = self._extract_task(text, m.span())
        if not task:
            return None

        return {
            "cron": f"{minute} {hour} * * {day}",
            "rrule": f"FREQ=WEEKLY;BYDAY={['SU','MO','TU','WE','TH','FR','SA'][day]};BYHOUR={hour};BYMINUTE={minute}",
            "original_task": task,
            "type": "scheduled_workflow",
        }

    def _parse_daily(self, text: str) -> Optional[Dict[str, Any]]:
        patterns = [
            r"\bher\s+(gün|gun|sabah|akşam|aksam)"
            r"(?:\s*(?:saat\s*)?(\d{1,2})(?:(?::|\.)(\d{2}))?\s*['’]?(?:de|da)?)?",
            r"\b(?:daily|every day)"
            r"(?:\s*(?:at\s*)?(\d{1,2})(?:(?::|\.)(\d{2}))?)?",
        ]
        for idx, pattern in enumerate(patterns):
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if not m:
                continue

            if idx == 0:
                period = str(m.group(1) or "").lower()
                raw_hour = m.group(2)
                raw_min = m.group(3)
                if raw_hour is None:
                    hour = 18 if period in {"akşam", "aksam"} else 9
                else:
                    hour = int(raw_hour)
                minute = int(raw_min or 0)
            else:
                hour = int(m.group(1) or 9)
                minute = int(m.group(2) or 0)

            hour, minute = self._clamp_time(hour, minute)
            task = self._extract_task(text, m.span())
            if not task:
                return None
            return {
                "cron": f"{minute} {hour} * * *",
                "rrule": f"FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR,SA,SU;BYHOUR={hour};BYMINUTE={minute}",
                "original_task": task,
                "type": "scheduled_workflow",
            }
        return None

    @staticmethod
    def _parse_weekdays(text: str) -> Optional[Dict[str, Any]]:
        m = re.search(
            r"\b(her\s+i(?:ş|s)\s+g[üu]n[üu]|iş\s+g[üu]nleri|is\s+gunleri|every\s+weekday)"
            r"(?:\s*(?:saat\s*)?(\d{1,2})(?:(?::|\.)(\d{2}))?\s*['’]?(?:de|da)?)?",
            text,
            flags=re.IGNORECASE,
        )
        if not m:
            return None

        hour = int(m.group(2) or 9)
        minute = int(m.group(3) or 0)
        hour, minute = NLCron._clamp_time(hour, minute)
        task = NLCron._extract_task(text, m.span())
        if not task:
            return None
        return {
            "cron": f"{minute} {hour} * * 1-5",
            "rrule": f"FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR={hour};BYMINUTE={minute}",
            "original_task": task,
            "type": "scheduled_workflow",
        }

    @staticmethod
    def _parse_hourly(text: str) -> Optional[Dict[str, Any]]:
        m = re.search(r"\b(saat başı|saat basi|her saat|hourly)\b", text, flags=re.IGNORECASE)
        if not m:
            return None
        task = NLCron._extract_task(text, m.span())
        if not task:
            return None
        return {
            "cron": "0 * * * *",
            "rrule": "FREQ=HOURLY;INTERVAL=1;BYMINUTE=0",
            "original_task": task,
            "type": "scheduled_workflow",
        }

    def parse(self, text: str) -> Optional[Dict[str, Any]]:
        raw = str(text or "").strip()
        if not raw:
            return None

        for parser in (self._parse_weekdays, self._parse_weekly, self._parse_daily, self._parse_hourly):
            try:
                parsed = parser(raw)
            except Exception as exc:
                logger.debug(f"nl_cron parser step failed: {exc}")
                parsed = None
            if parsed:
                return parsed
        return None


nl_cron = NLCron()
