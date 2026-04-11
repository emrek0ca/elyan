"""CLI: morning digest runtime."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from core.briefing_manager import get_briefing_manager
from core.voice.elyan_tts import get_elyan_tts
from core.voice.runtime_profile import detect_runtime_profile


async def _generate_digest(*, weather: bool, calendar: bool, news: bool, email: bool) -> dict:
    manager = get_briefing_manager()
    return await manager.get_proactive_briefing(
        include_weather=weather,
        include_calendar=calendar,
        include_news=news,
        include_email=email,
    )


def _render_payload(result: dict, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(result.get("digest") or result, ensure_ascii=False, indent=2)
    renders = dict(result.get("renders") or {})
    return str(renders.get("terminal") or result.get("briefing") or "").strip()


def run(args) -> int:
    subcommand = str(getattr(args, "subcommand", "show") or "show").strip().lower()
    weather = bool(getattr(args, "weather", True))
    calendar = bool(getattr(args, "calendar", True))
    news = bool(getattr(args, "news", True))
    email = bool(getattr(args, "email", True))
    fmt = str(getattr(args, "format", "text") or "text").strip().lower()
    output_file = str(getattr(args, "file", "") or "").strip()

    if subcommand == "profile":
        print(json.dumps(detect_runtime_profile().to_dict(), ensure_ascii=False, indent=2))
        return 0

    try:
        result = asyncio.run(
            _generate_digest(
                weather=weather,
                calendar=calendar,
                news=news,
                email=email,
            )
        )
    except Exception as exc:
        print(f"Digest üretilemedi: {exc}")
        return 1

    if not bool(result.get("success")):
        print(f"Digest üretilemedi: {result.get('error') or 'bilinmeyen hata'}")
        return 1

    if subcommand == "speak":
        speech_text = str((result.get("renders") or {}).get("speech") or result.get("speech_script") or "").strip()
        if not speech_text:
            print("Seslendirme için metin üretilemedi.")
            return 1
        ok = asyncio.run(get_elyan_tts().speak(speech_text, interrupt=True))
        if not ok:
            print("Yerel TTS kullanılamıyor.")
            return 1
        print("✓ Günlük özet seslendirildi.")
        return 0

    payload = _render_payload(result, fmt)
    if subcommand == "export":
        if not output_file:
            print("Çıktı dosyası gerekli: elyan digest export --file /tmp/digest.txt")
            return 1
        Path(output_file).expanduser().write_text(payload, encoding="utf-8")
        print(f"✓ Günlük özet kaydedildi: {output_file}")
        return 0

    print(payload)
    return 0


__all__ = ["run"]
