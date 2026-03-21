from __future__ import annotations

import signal
import time

from core.realtime_actuator.runtime import RealTimeActuator


def main() -> int:
    actuator = RealTimeActuator(process_mode=True)
    status = actuator.start()
    if not status.get("active", False):
        return 1

    stop = False

    def _shutdown(*_: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while not stop:
            current = actuator.get_status()
            if not current.get("process_alive", True):
                return 1
            time.sleep(5.0)
    finally:
        actuator.stop()
    return 0
