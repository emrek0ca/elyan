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
STOP_PATH = state_store.CONFIG_DIR / "daemon.stop"


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
    try:
        STOP_PATH.unlink(missing_ok=True)
    except OSError:
        pass
    PID_PATH.write_text(str(os.getpid()))


def _remove_pidfile() -> None:
    try:
        if PID_PATH.exists() and PID_PATH.read_text().strip() == str(os.getpid()):
            PID_PATH.unlink()
    except OSError:
        pass
    try:
        STOP_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def _stop_requested() -> bool:
    """Return True only for a stop marker addressed to this daemon PID."""
    try:
        return STOP_PATH.read_text().strip() == str(os.getpid())
    except OSError:
        return False


def _mark_daemon_transport_starting() -> None:
    """Invalidate transport truth inherited from an earlier daemon process."""
    state = state_store.snapshot()
    runtime = state.get("runtime", {}) if isinstance(state.get("runtime"), dict) else {}
    paired = bool(
        str(runtime.get("runtimeToken", "") or "").strip()
        or (
            str(runtime.get("deviceId", "") or "").strip()
            and str(runtime.get("deviceSecret", "") or "").strip()
        )
    )
    state_store.update_state(
        {
            "runtime": {
                "ready": False,
                "websocketConnected": False,
                "lifecycleState": "runtime_connecting" if paired else "offline",
                "lastErrorCode": "",
            },
            "pairing": {"realtimeReady": False},
        }
    )


class ElyanDaemon:
    """RuntimeBridge'i başsız ayakta tutar; durum ve görevler STATE'ten okunur."""

    def __init__(self) -> None:
        # Geç import: bridge modülü büyük; CLI'nin hafif komutları (status,
        # tasks) bunu hiç yüklemez.
        from runtime.bridge import RuntimeBridge

        _mark_daemon_transport_starting()
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

    # 1 sn beklerken duvar-saati bu kadar atladıysa makine uyumuş/askıya
    # alınmış olabilir; uyanışta soket koptuğu için hemen yeniden bağlan.
    WAKE_GAP_SECONDS = 8.0
    # Bağlantı düşükken kademeli yeniden-deneme (düz 300 sn yerine hızlı ilk
    # denemeler + katlanan sırt): ağ kısa süre gidip geldiğinde saniyeler
    # içinde toparlanır, kalıcı kesintide gereksiz yük bindirmez.
    OFFLINE_RETRY_MIN = 5.0
    OFFLINE_RETRY_MAX = 300.0
    _CONNECTED_LIFECYCLES = frozenset({"ready", "online", "connected"})

    def _force_reconnect(self) -> None:
        reconnect = getattr(self.bridge, "force_runtime_reconnect", None)
        if callable(reconnect):
            try:
                reconnect()
                return
            except Exception:
                pass
        self.bootstrap()

    def run_forever(self) -> None:
        """Relay thread'leri (bridge içinde, daemon=True) işi yapar; burası
        süreci canlı tutar, uykudan uyanışı tespit edip düşen bağlantıyı
        kademeli olarak toparlar."""
        last_bootstrap = time.monotonic()
        last_wall = time.time()
        offline_retry = self.OFFLINE_RETRY_MIN
        while not self._stop.is_set():
            # A native tray main loop can defer Python signal handlers on
            # macOS; SIGTERM/SIGINT are therefore bridged through
            # signal.set_wakeup_fd in main().  The CLI also writes a
            # PID-scoped stop marker, which this lightweight keeper observes
            # cross-platform without depending on the UI event loop.
            self._stop.wait(1)
            if _stop_requested():
                self.stop()
            if self._stop.is_set():
                break

            now_wall = time.time()
            wall_gap = now_wall - last_wall
            last_wall = now_wall

            snapshot = state_store.snapshot().get("runtime", {})
            snapshot = snapshot if isinstance(snapshot, dict) else {}
            lifecycle = str(snapshot.get("lifecycleState", "") or "")
            connected = lifecycle in self._CONNECTED_LIFECYCLES

            # Uyku/askı tespiti: state "ready" görünse bile soket kopmuştur;
            # 5 dk döngüsünü beklemeden koşulsuz zorla yeniden bağlan.
            if wall_gap >= self.WAKE_GAP_SECONDS:
                self._force_reconnect()
                last_bootstrap = time.monotonic()
                offline_retry = self.OFFLINE_RETRY_MIN
                continue

            if connected:
                offline_retry = self.OFFLINE_RETRY_MIN
                continue

            # Bağlantı düşük: kısa aralıkla dene, başarısızlıkta sırtı uzat.
            if time.monotonic() - last_bootstrap >= offline_retry:
                self.bootstrap()
                last_bootstrap = time.monotonic()
                offline_retry = min(offline_retry * 2, self.OFFLINE_RETRY_MAX)


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
    pid = read_daemon_pid()
    # STATE is deliberately persisted across restarts, but a persisted
    # `ready` flag must never make a stopped process look connected.  The
    # daemon PID is the local liveness authority for this lightweight view;
    # backend truth is refreshed by the running bridge.
    lifecycle = str(runtime.get("lifecycleState", "") or "stopped")
    websocket_connected = bool(runtime.get("websocketConnected", False))
    if not pid:
        lifecycle = "offline"
        websocket_connected = False
    return {
        "pid": pid,
        "lifecycleState": lifecycle,
        "websocketConnected": websocket_connected,
        "lastErrorCode": str(runtime.get("lastErrorCode", "") or ""),
        "signedIn": bool(str(account.get("accessToken", "") or "").strip()),
        "email": str(account.get("email", "") or ""),
        # Eşleşme kanıtı: kayıtlı runtime token VEYA claim'den gelen cihaz
        # kimliği (deviceId+deviceSecret). Kayıt geçici olarak başarısızsa bile
        # eşleştirme yapılmıştır — CLI yeniden QR akışı başlatmamalı.
        "paired": bool(
            str(runtime.get("runtimeToken", "") or "").strip()
            or (
                str(runtime.get("deviceId", "") or "").strip()
                and str(runtime.get("deviceSecret", "") or "").strip()
            )
        ),
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

    # macOS'ta pystray'in AppKit run loop'u ana thread'i Python bytecode'undan
    # uzak tutar; Python seviyesindeki _terminate süresiz ertelenebilir ve
    # SIGTERM süreci öldüremez. set_wakeup_fd C-seviyesindeki sinyal
    # işleyicisinden yazar: sinyal numarası pipe'a anında düşer, yan thread
    # okuyup durdurmayı tetikler (tray tick thread'i _stop'u görünce
    # icon.stop() çağırır — bkz. runtime/tray.py).
    wake_read, wake_write = os.pipe()
    os.set_blocking(wake_write, False)
    signal.set_wakeup_fd(wake_write)

    def _signal_watcher() -> None:
        stop_signals = {int(signal.SIGTERM), int(signal.SIGINT)}
        while True:
            try:
                data = os.read(wake_read, 64)
            except OSError:
                return
            if not data:
                return
            if any(byte in stop_signals for byte in data):
                daemon.stop()
                return

    threading.Thread(target=_signal_watcher, name="elyan-signal-watcher", daemon=True).start()

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
