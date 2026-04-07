"""
core/proactive/system_monitor.py
───────────────────────────────────────────────────────────────────────────────
SystemMonitor — watches CPU/disk/battery, fires alerts via registered handlers.
"""
from __future__ import annotations
import asyncio, time, uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable
from utils.logger import get_logger

logger = get_logger("system_monitor")


@dataclass(slots=True)
class SystemAlert:
    alert_id: str
    category: str
    severity: str          # info | warning | critical
    title: str
    message: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MonitorRule:
    rule_id: str
    check_fn: Callable[[], Awaitable[bool]]   # returns True if alert should fire
    severity: str
    title: str
    message: str
    category: str = "system"
    cooldown_s: float = 300.0


class SystemMonitor:
    def __init__(self) -> None:
        self._rules: list[MonitorRule] = []
        self._handlers: list[Callable[[SystemAlert], Awaitable[None]]] = []
        self._last_fired: dict[str, float] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        self._register_builtin_rules()

    def _register_builtin_rules(self) -> None:
        from core.computer.app_controller import get_app_controller

        async def _cpu_high() -> bool:
            try:
                return (await get_app_controller().get_cpu_usage()) > 85.0
            except Exception:
                return False

        async def _disk_low() -> bool:
            try:
                info = await get_app_controller().get_disk_usage()
                return info.get("free_gb", 100) < 5.0
            except Exception:
                return False

        async def _battery_critical() -> bool:
            try:
                b = await get_app_controller().get_battery_info()
                return b["percent"] < 15 and not b["charging"]
            except Exception:
                return False

        async def _battery_low() -> bool:
            try:
                b = await get_app_controller().get_battery_info()
                return b["percent"] < 30 and not b["charging"]
            except Exception:
                return False

        self._rules = [
            MonitorRule("cpu_high", _cpu_high, "warning", "Yoğun İşlemci Kullanımı", "CPU %85+ kullanımda.", "cpu", 120),
            MonitorRule("disk_low", _disk_low, "warning", "Disk Dolmak Üzere", "Diskte 5GB'dan az yer kaldı.", "disk", 1800),
            MonitorRule("battery_critical", _battery_critical, "critical", "Pil Kritik Seviyede", "Pil %15 altında, şarj et.", "battery", 600),
            MonitorRule("battery_low", _battery_low, "info", "Pil Azalıyor", "Pil %30 altında.", "battery", 900),
        ]

    def register_rule(self, rule: MonitorRule) -> None:
        self._rules.append(rule)

    def register_alert_handler(self, handler: Callable[[SystemAlert], Awaitable[None]]) -> None:
        self._handlers.append(handler)

    async def _fire(self, rule: MonitorRule) -> None:
        alert = SystemAlert(
            alert_id=f"alert_{uuid.uuid4().hex[:8]}",
            category=rule.category,
            severity=rule.severity,
            title=rule.title,
            message=rule.message,
        )
        logger.info(f"Alert fired: [{rule.severity.upper()}] {rule.title}")
        for h in self._handlers:
            try:
                await h(alert)
            except Exception as exc:
                logger.debug(f"Alert handler error: {exc}")

    async def _check_once(self) -> None:
        now = time.time()
        for rule in self._rules:
            last = self._last_fired.get(rule.rule_id, 0)
            if now - last < rule.cooldown_s:
                continue
            try:
                if await rule.check_fn():
                    self._last_fired[rule.rule_id] = now
                    await self._fire(rule)
            except Exception as exc:
                logger.debug(f"Rule check error {rule.rule_id}: {exc}")

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("SystemMonitor started")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _loop(self) -> None:
        while self._running:
            await self._check_once()
            await asyncio.sleep(10)


_instance: SystemMonitor | None = None

def get_system_monitor() -> SystemMonitor:
    global _instance
    if _instance is None:
        _instance = SystemMonitor()
    return _instance

__all__ = ["SystemAlert", "MonitorRule", "SystemMonitor", "get_system_monitor"]
