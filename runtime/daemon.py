"""
Elyan masaüstü daemon'u — başsız (headless) görev yürütücü.

GUI yok: süreç arka planda sessizce yaşar, sunucudan (api.elyan.dev) mobil
görevleri WebSocket + polling ile alır, masaüstünde yürütür ve sonucu geri
raporlar. Tüm ağır iş zaten `runtime/bridge.py` içindedir (WS relay, self-
pairing, heartbeat, görev yürütme); bu modül onu stdin/stdout'a bağlamadan
tek başına ayakta tutar.

Kullanım (normalde `elyan` CLI üzerinden):
    python -m runtime.daemon            # ön planda (macOS'ta menü çubuğu ikonu)
    python -m runtime.daemon --no-tray  # ikonsuz saf arka plan
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

from runtime import state_store

PID_PATH = state_store.CONFIG_DIR / "daemon.pid"
LOG_PATH = state_store.CONFIG_DIR / "daemon.log"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_daemon_pid() -> int:
    """Çalışan daemon PID'i; yoksa/ölmüşse 0."""
    try:
        pid = int(PID_PATH.read_text().strip())
    except (OSError, ValueError):
        return 0
    return pid if _pid_alive(pid) else 0


def _write_pidfile() -> None:
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()))


def _remove_pidfile() -> None:
    try:
        if PID_PATH.exists() and PID_PATH.read_text().strip() == str(os.getpid()):
            PID_PATH.unlink()
    except OSError:
        pass


class ElyanDaemon:
    """RuntimeBridge'i başsız ayakta tutar; durum ve görevler STATE'ten okunur."""

    def __init__(self) -> None:
        # Geç import: bridge modülü büyük; CLI'nin hafif komutları (status,
        # tasks) bunu hiç yüklemez.
        from runtime.bridge import RuntimeBridge

        self.bridge = RuntimeBridge()
        self._stop = threading.Event()

    # -- yaşam döngüsü -----------------------------------------------------

    def bootstrap(self) -> dict[str, Any]:
        """Kayıt + self-pairing + WS relay'i başlatan tek çağrı."""
        response = self.bridge.handle(
            {
                "id": "daemon_bootstrap",
                "taskId": "daemon_bootstrap",
                "capability": "runtime.bootstrap",
                "payload": {},
            }
        )
        return response if isinstance(response, dict) else {}

    def request(self, capability: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.bridge.handle(
            {
                "id": f"daemon_{capability.replace('.', '_')}",
                "taskId": "daemon_req",
                "capability": capability,
                "payload": payload or {},
            }
        )
        return response if isinstance(response, dict) else {}

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self) -> None:
        """Relay thread'leri (bridge içinde, daemon=True) işi yapar; burası
        süreci canlı tutar ve düşen bağlantıyı periyodik bootstrap ile toparlar."""
        last_bootstrap = time.monotonic()
        while not self._stop.is_set():
            self._stop.wait(30)
            if self._stop.is_set():
                break
            # Bağlantı düşmüşse (offline/reconnecting) 5 dakikada bir yeniden
            # bootstrap dene — ağ geri geldiğinde müdahalesiz toparlanma.
            if time.monotonic() - last_bootstrap >= 300:
                snapshot = state_store.snapshot().get("runtime", {})
                lifecycle = str(snapshot.get("lifecycleState", "") or "")
                if lifecycle not in {"ready", "online", "connected"}:
                    self.bootstrap()
                last_bootstrap = time.monotonic()


# -- durum yardımcıları (tray + CLI status paylaşır) ------------------------


def runtime_status_summary() -> dict[str, Any]:
    """STATE dosyasından hafif durum özeti (bridge yüklemeden).

    Şema: hesap `state.account` (accessToken/email), eşleştirme kanıtı
    `state.runtime.runtimeToken` (kayıtlı cihaz), görevler `state.taskInbox`.
    """
    state = state_store.snapshot()
    runtime = state.get("runtime", {}) if isinstance(state.get("runtime"), dict) else {}
    account = state.get("account", {}) if isinstance(state.get("account"), dict) else {}
    inbox = state.get("taskInbox", {}) if isinstance(state.get("taskInbox"), dict) else {}
    items = inbox.get("items", []) if isinstance(inbox.get("items"), list) else []
    active = [
        item
        for item in items
        if isinstance(item, dict)
        and str(item.get("status", "")) not in {"completed", "failed", "canceled"}
    ]
    return {
        "pid": read_daemon_pid(),
        "lifecycleState": str(runtime.get("lifecycleState", "") or "stopped"),
        "websocketConnected": bool(runtime.get("websocketConnected", False)),
        "lastErrorCode": str(runtime.get("lastErrorCode", "") or ""),
        "signedIn": bool(str(account.get("accessToken", "") or "").strip()),
        "email": str(account.get("email", "") or ""),
        "paired": bool(str(runtime.get("runtimeToken", "") or "").strip()),
        "activeTasks": active,
        "recentTasks": [item for item in items if isinstance(item, dict)][:10],
    }


# -- giriş noktası -----------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="elyan-daemon")
    parser.add_argument("--no-tray", action="store_true", help="Menü çubuğu ikonu olmadan çalış")
    args = parser.parse_args(argv)

    existing = read_daemon_pid()
    if existing and existing != os.getpid():
        print(f"Elyan daemon zaten çalışıyor (pid {existing}).", file=sys.stderr)
        return 1

    _write_pidfile()
    daemon = ElyanDaemon()

    def _terminate(_sig: int, _frame: Any) -> None:
        daemon.stop()

    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGINT, _terminate)

    print("Elyan daemon başlıyor…", flush=True)
    boot = daemon.bootstrap()
    ok = bool(boot.get("ok"))
    print(f"bootstrap: {'tamam' if ok else 'kısıtlı (giriş/eşleştirme gerekebilir)'}", flush=True)

    try:
        if args.no_tray:
            daemon.run_forever()
        else:
            # Tepsi ikonu her platformda (macOS menü çubuğu / Windows tepsi /
            # Linux göstergesi). pystray ana thread ister; bekçi döngüsü yan
            # thread'e alınır. Tray kurulamazsa (başsız oturum) saf döngüye düşer.
            from runtime.tray import run_tray

            keeper = threading.Thread(target=daemon.run_forever, name="elyan-daemon-keeper", daemon=True)
            keeper.start()
            if not run_tray(daemon):
                keeper.join()
    finally:
        daemon.stop()
        _remove_pidfile()
    print("Elyan daemon durdu.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
