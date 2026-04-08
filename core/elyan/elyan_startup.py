"""
core/elyan/elyan_startup.py — Tüm Elyan servislerini başlatan merkezi modül
───────────────────────────────────────────────────────────────────────────────
server.start() bu modülü çağırır. Her servis bağımsız başlar; biri çökerse
diğerleri etkilenmez.

Başlatılan servisler (sırayla):
  1. OllamaDiscovery       — yerel modelleri tarar, policy'e kaydeder
  2. SystemMonitor         — CPU/disk/batarya uyarıları
  3. SchedulerAgent        — cron görevleri
  4. ContextTracker        — aktif uygulama takibi
  5. WakeWordDetector      — sesli komut tetikleyici (ses kartı gerekli)
  6. ElyanMemory          — DB başlatma (lazy init'e yedek)
  7. PersonalityAdapter    — DB başlatma
"""
from __future__ import annotations

import asyncio
from typing import Callable

from utils.logger import get_logger

logger = get_logger("elyan_startup")


# ── Broadcast helper (isteğe bağlı) ──────────────────────────────────────────

BroadcastFn = Callable[[str, dict], None] | None
_broadcast: BroadcastFn = None


def set_broadcast(fn: BroadcastFn) -> None:
    global _broadcast
    _broadcast = fn


def _push(event_type: str, payload: dict) -> None:
    if _broadcast:
        try:
            _broadcast(event_type, payload)
        except Exception:
            pass


# ── Individual service starters ───────────────────────────────────────────────

async def _start_ollama_discovery() -> None:
    try:
        from core.llm.ollama_discovery import get_ollama_discovery
        disc = get_ollama_discovery()
        await disc.start()
        models = await disc.probe_once()
        logger.info(f"OllamaDiscovery started — {len(models)} model(s) found")
    except Exception as exc:
        logger.warning(f"OllamaDiscovery start failed (non-critical): {exc}")


async def _start_system_monitor(notify_fn: BroadcastFn) -> None:
    try:
        from core.proactive.system_monitor import get_system_monitor

        monitor = get_system_monitor()

        async def _on_alert(alert) -> None:
            msg = getattr(alert, "message", str(alert))
            logger.warning(f"[SystemMonitor] {msg}")
            _push("proactive.alert.fired", {"message": msg, "rule": getattr(alert, "rule_id", "")})
            # Also notify via existing intervention manager if available
            try:
                from core.proactive.intervention import get_intervention_manager
                await get_intervention_manager().trigger(msg, source="system_monitor")
            except Exception:
                pass

        monitor.register_alert_handler(_on_alert)
        await monitor.start()
        logger.info("SystemMonitor started")
    except Exception as exc:
        logger.warning(f"SystemMonitor start failed (non-critical): {exc}")


async def _start_scheduler() -> None:
    try:
        from core.proactive.scheduler_agent import get_scheduler_agent
        await get_scheduler_agent().start()
        logger.info("SchedulerAgent started")
    except Exception as exc:
        logger.warning(f"SchedulerAgent start failed (non-critical): {exc}")


async def _start_context_tracker() -> None:
    try:
        from core.proactive.context_tracker import get_context_tracker
        await get_context_tracker().start(interval_s=5.0)
        logger.info("ContextTracker started")
    except Exception as exc:
        logger.warning(f"ContextTracker start failed (non-critical): {exc}")


async def _start_morning_brief() -> None:
    """Her sabah 09:00'da takvim + hava + sistem özeti."""
    import datetime, asyncio

    async def _deliver_brief() -> None:
        try:
            from core.elyan.elyan_core import get_elyan_core
            from core.integrations.calendar import get_today_events

            jc = get_elyan_core()

            # 1. Takvim etkinlikleri
            events = get_today_events()
            cal_text = events if events.strip() else "Bugün takvimde etkinlik yok."

            # 2. Sistem sağlığı
            from core.computer.app_controller import AppController
            ac = AppController()
            cpu  = await ac.get_cpu_usage()
            batt = await ac.get_battery_info()
            disk = await ac.get_disk_usage()
            charging = "🔌" if batt.get("charging") else "🔋"

            brief = (
                f"☀️ **Günaydın! Sabah özeti:**\n\n"
                f"📅 **Bugünün Etkinlikleri:**\n{cal_text}\n\n"
                f"📊 **Sistem:**\n"
                f"🖥️ CPU: %{cpu:.1f}  {charging} Batarya: %{batt.get('percent', '?')}  "
                f"💾 Disk: {disk.get('free_gb', 0):.1f} GB boş"
            )

            _push("elyan.morning_brief", {"text": brief})
            logger.info("Morning brief delivered")
        except Exception as exc:
            logger.warning(f"Morning brief delivery failed: {exc}")

    async def _schedule_loop() -> None:
        while True:
            now = datetime.datetime.now()
            # Bugün 09:00 henüz geçmemişse bugün, geçmişse yarın
            target = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)
            wait_s = (target - now).total_seconds()
            logger.debug(f"Morning brief scheduled in {wait_s/3600:.1f}h")
            await asyncio.sleep(wait_s)
            await _deliver_brief()

    try:
        asyncio.ensure_future(_schedule_loop())
        logger.info("MorningBrief scheduler registered (fires at 09:00 daily)")
    except Exception as exc:
        logger.warning(f"MorningBrief scheduler failed (non-critical): {exc}")


async def _start_wake_word(notify_fn: BroadcastFn) -> None:
    try:
        from core.voice.wake_word import get_wake_word_detector
        detector = get_wake_word_detector()

        async def _on_wake() -> None:
            logger.info("Wake word detected — triggering voice pipeline")
            _push("voice.wake_detected", {})
            try:
                from core.voice.voice_pipeline import get_voice_pipeline
                await get_voice_pipeline().trigger()
            except Exception as exc:
                logger.warning(f"Voice pipeline trigger failed: {exc}")

        detector.set_callback(_on_wake)
        await detector.start()
        logger.info(f"WakeWordDetector started (backend: {detector.backend})")
    except Exception as exc:
        logger.warning(f"WakeWordDetector start failed (non-critical): {exc}")


def _init_memory() -> None:
    """Pre-initialize memory DBs so first request is instant."""
    try:
        from core.memory.elyan_memory import get_elyan_memory
        get_elyan_memory()
        logger.debug("ElyanMemory initialized")
    except Exception:
        pass
    try:
        from core.memory.personality_adapter import get_personality_adapter
        get_personality_adapter()
        logger.debug("PersonalityAdapter initialized")
    except Exception:
        pass
    # Warmup STT model in background thread
    try:
        from core.voice.stt_engine import get_stt_engine
        get_stt_engine().warmup()
        logger.debug("STT warmup started")
    except Exception:
        pass


# ── Main startup entry ────────────────────────────────────────────────────────

async def start_elyan_services(broadcast: BroadcastFn = None) -> None:
    """Start all Elyan background services concurrently."""
    set_broadcast(broadcast)
    _init_memory()   # sync — fast DB open

    results = await asyncio.gather(
        _start_ollama_discovery(),
        _start_system_monitor(broadcast),
        _start_scheduler(),
        _start_context_tracker(),
        _start_wake_word(broadcast),
        _start_morning_brief(),
        return_exceptions=True,
    )

    failed = [r for r in results if isinstance(r, BaseException)]
    if failed:
        logger.warning(f"Elyan startup: {len(failed)} service(s) failed (non-critical)")
    else:
        logger.info("All Elyan services started successfully")


async def stop_elyan_services() -> None:
    """Graceful shutdown of all Elyan background services."""
    for name, stopper in [
        ("WakeWordDetector",  _stop("core.voice.wake_word",         "get_wake_word_detector")),
        ("ContextTracker",    _stop("core.proactive.context_tracker", "get_context_tracker")),
        ("SchedulerAgent",    _stop("core.proactive.scheduler_agent", "get_scheduler_agent")),
        ("SystemMonitor",     _stop("core.proactive.system_monitor",  "get_system_monitor")),
        ("OllamaDiscovery",   _stop("core.llm.ollama_discovery",      "get_ollama_discovery")),
    ]:
        try:
            await stopper
            logger.debug(f"{name} stopped")
        except Exception as exc:
            logger.debug(f"{name} stop error: {exc}")


async def _stop(module: str, getter: str):
    import importlib
    mod = importlib.import_module(module)
    obj = getattr(mod, getter)()
    stop = getattr(obj, "stop", None)
    if callable(stop):
        await stop()
