"""
`elyan` komutu — kurulum, QR ile eşleştirme ve daemon yönetimi.

Tasarım ilkeleri:
- GUI yok. Kurulum ve eşleştirme CLI'dan yapılır; sonrası sessiz daemon +
  tepsi ikonu (macOS menü çubuğu / Windows tepsisi / Linux göstergesi).
- Hafif komutlar (status, tasks) yalnız STATE dosyasını okur — motoru yüklemez.
- Ağır komutlar (pair, login) motoru süreç-içi kullanır; çifte-bridge token
  yarışını önlemek için çalışan daemon önce durdurulur, iş bitince geri açılır.
- Sunucu beyniyle (server_brain) tüm konuşma JSON zarflarıyladır; bu CLI hiçbir
  düz-metin bağlam taşımaz.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime import state_store  # noqa: E402
from runtime.daemon import LOG_PATH, PID_PATH, STOP_PATH, read_daemon_pid, runtime_status_summary  # noqa: E402

VERSION = "1.0.0"
SERVICE_LABEL = "dev.elyan.daemon"


# ─────────────────────────────── yardımcılar ────────────────────────────────


def _python_executable() -> str:
    """Daemon'u başlatacak yorumlayıcı — venv öncelikli (~/.elyan sonra repo)."""
    home_venv = Path.home() / ".elyan" / "venv"
    candidates = (
        [
            home_venv / "Scripts" / "python.exe",
            REPO_ROOT / "venv" / "Scripts" / "python.exe",
            REPO_ROOT / ".venv" / "Scripts" / "python.exe",
        ]
        if os.name == "nt"
        else [
            home_venv / "bin" / "python3",
            REPO_ROOT / "venv" / "bin" / "python3",
            REPO_ROOT / ".venv" / "bin" / "python3",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _print_kv(rows: list[tuple[str, str]]) -> None:
    width = max(len(key) for key, _ in rows) if rows else 0
    for key, value in rows:
        print(f"  {key.ljust(width)}  {value}")


def _bridge():
    """Süreç-içi motor örneği (yalnız ağır komutlar)."""
    from runtime.bridge import RuntimeBridge

    return RuntimeBridge()


def _request(bridge: Any, capability: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    response = bridge.handle(
        {
            "id": f"cli_{capability.replace('.', '_')}_{int(time.time() * 1000)}",
            "taskId": "cli",
            "capability": capability,
            "payload": payload or {},
        }
    )
    return response if isinstance(response, dict) else {}


def _platform_name() -> str:
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt":
        return "windows"
    return "linux"


def _render_qr(text: str) -> str:
    """Terminale unicode-blok QR çizer (iOS uygulaması kameryla okur)."""
    try:
        import qrcode
    except Exception:
        return "(qrcode paketi yok — kodu elle gir)"
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    lines: list[str] = []
    # İki satırı tek karakter satırına sıkıştır (▀ ▄ █) — terminalde kare kalır.
    for y in range(0, len(matrix), 2):
        row_top = matrix[y]
        row_bottom = matrix[y + 1] if y + 1 < len(matrix) else [False] * len(row_top)
        line = ""
        for top, bottom in zip(row_top, row_bottom):
            if top and bottom:
                line += "█"
            elif top:
                line += "▀"
            elif bottom:
                line += "▄"
            else:
                line += " "
        lines.append(line)
    return "\n".join(lines)


def _daemon_running() -> int:
    return read_daemon_pid()


def _stop_daemon(quiet: bool = False) -> bool:
    pid = _daemon_running()
    if not pid:
        return False
    if not quiet:
        print(f"Daemon duraklatılıyor (pid {pid})…")
    try:
        STOP_PATH.parent.mkdir(parents=True, exist_ok=True)
        STOP_PATH.write_text(str(pid))
    except OSError:
        pass
    try:
        os.kill(pid, 15)
    except OSError:
        return False
    for _ in range(40):
        if not _daemon_running():
            return True
        time.sleep(0.25)
    if not quiet:
        print("Daemon nazikçe durmadı; zorla kapatılıyor.")
    try:
        os.kill(pid, 9)
    except OSError:
        pass
    # SIGKILL sonrası süreç tablosu/pidfile birkaç an bayat kalabilir. Restart
    # aynı komut içinde devam ettiği için sınırlı biçimde gerçek çıkışı bekle.
    for _ in range(40):
        if not _daemon_running():
            return True
        time.sleep(0.05)
    try:
        if PID_PATH.exists() and PID_PATH.read_text().strip() == str(pid):
            PID_PATH.unlink()
    except OSError:
        pass
    try:
        STOP_PATH.unlink(missing_ok=True)
    except OSError:
        pass
    return True


def _start_daemon_detached() -> int:
    state_store.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = open(LOG_PATH, "a", encoding="utf-8")
    kwargs: dict[str, Any] = {
        "stdout": log_handle,
        "stderr": log_handle,
        "stdin": subprocess.DEVNULL,
        "cwd": str(REPO_ROOT),
    }
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen([_python_executable(), "-m", "runtime.daemon"], **kwargs)
    return process.pid


# ─────────────────────────────── komutlar ───────────────────────────────────


def cmd_pair(args: argparse.Namespace) -> int:
    """QR ile eşleştirme: terminalde QR göster, iOS uygulaması okusun,
    bridge claim'i otomatik uygulasın, ardından runtime kaydolsun."""
    was_running = _stop_daemon()
    bridge = _bridge()

    print("Eşleştirme oturumu oluşturuluyor…")
    response = _request(
        bridge,
        "pairing.create_session",
        {
            "deviceLabel": socket.gethostname() or "Elyan Desktop",
            "platform": _platform_name(),
            "runtimeVersion": VERSION,
            "forceNew": bool(args.force),
        },
    )
    result = response.get("result", {})
    result = result.get("result", result) if isinstance(result, dict) else {}
    data = result.get("data", result) if isinstance(result, dict) else {}
    code = str(data.get("manualEntryCode") or data.get("pairingCode") or "").strip()
    qr_text = str(data.get("qrText") or code or "").strip()
    if not response.get("ok") or not code:
        message = str((response.get("error") or {}).get("message", "") or "Eşleştirme oturumu açılamadı.")
        print(f"HATA: {message}")
        print("İnternet bağlantını kontrol et ve tekrar dene: elyan pair")
        return 1

    print()
    print(_render_qr(qr_text))
    print()
    print(f"  Kod: {code}")
    print("  Elyan iOS uygulamasında 'Bilgisayar Eşleştir'i açıp bu QR'ı okut")
    print("  (ya da kodu elle gir). Bekleniyor…")
    print()

    # Bridge'in kendi claim-poll thread'i claim'i uygular; biz STATE'i izleriz.
    deadline = time.monotonic() + 300
    paired = False
    while time.monotonic() < deadline:
        time.sleep(2)
        snapshot = state_store.snapshot()
        pairing = snapshot.get("pairing", {}) if isinstance(snapshot.get("pairing"), dict) else {}
        runtime = snapshot.get("runtime", {}) if isinstance(snapshot.get("runtime"), dict) else {}
        claimed = str(pairing.get("lastSessionStatus", "") or "").strip().lower() == "claimed"
        has_runtime_identity = bool(
            str(runtime.get("deviceSecret", "") or "").strip() or str(runtime.get("runtimeToken", "") or "").strip()
        )
        if claimed or has_runtime_identity:
            paired = True
            break
        print(".", end="", flush=True)
    print()

    if not paired:
        print("Eşleştirme zaman aşımına uğradı (5 dk). Tekrar dene: elyan pair")
        return 1

    print("Eşleştirildi ✓ — runtime kaydediliyor…")
    boot = _request(bridge, "runtime.bootstrap")
    print("Kayıt:", "tamam ✓" if boot.get("ok") else "kısıtlı (elyan doctor ile bak)")

    if was_running or args.start:
        pid = _start_daemon_detached()
        print(f"Daemon başlatıldı (pid {pid}). Artık mobilden görev gönderebilirsin.")
    else:
        print("Başlatmak için: elyan start   (açılışta otomatik: elyan service install)")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    """E-posta/şifre ile giriş (QR'sız alternatif)."""
    email = args.email or input("E-posta: ").strip()
    password = getpass.getpass("Şifre: ")
    if not email or not password:
        print("E-posta ve şifre gerekli.")
        return 1

    was_running = _stop_daemon()
    bridge = _bridge()
    response = _request(bridge, "backend.auth_login", {"email": email, "password": password})
    if not response.get("ok"):
        message = str((response.get("error") or {}).get("message", "") or "Giriş başarısız.")
        print(f"HATA: {message}")
        return 1
    print("Giriş tamam ✓ — runtime kaydediliyor (self-pairing)…")
    boot = _request(bridge, "runtime.bootstrap")
    print("Kayıt:", "tamam ✓" if boot.get("ok") else "kısıtlı (elyan doctor ile bak)")
    if was_running:
        pid = _start_daemon_detached()
        print(f"Daemon yeniden başlatıldı (pid {pid}).")
    return 0


def cmd_logout(_args: argparse.Namespace) -> int:
    was_running = _stop_daemon()
    bridge = _bridge()
    _request(bridge, "backend.auth_logout")
    print("Oturum kapatıldı.")
    if was_running:
        print("Daemon durduruldu (oturumsuz görev alınamaz).")
    return 0


def cmd_start(_args: argparse.Namespace) -> int:
    if _daemon_running():
        print(f"Daemon zaten çalışıyor (pid {_daemon_running()}).")
        return 0
    pid = _start_daemon_detached()
    time.sleep(1.5)
    if _daemon_running():
        print(f"Daemon başladı (pid {pid}). Log: {LOG_PATH}")
        return 0
    print(f"Daemon başlatılamadı — log'a bak: {LOG_PATH}")
    return 1


def cmd_stop(_args: argparse.Namespace) -> int:
    if _stop_daemon():
        print("Daemon durduruldu.")
        return 0
    print("Çalışan daemon yok.")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    _stop_daemon()
    return cmd_start(args)


def cmd_run(_args: argparse.Namespace) -> int:
    """Ön planda çalıştır (hata ayıklama için; Ctrl+C ile durur)."""
    if _daemon_running():
        print(f"Önce çalışan daemon'u durdur: elyan stop (pid {_daemon_running()})")
        return 1
    from runtime.daemon import main as daemon_main

    return daemon_main([])


def cmd_status(_args: argparse.Namespace) -> int:
    summary = runtime_status_summary()
    pid = summary.get("pid", 0)
    lifecycle = summary.get("lifecycleState", "stopped")
    rows = [
        ("Daemon", f"çalışıyor (pid {pid})" if pid else "durdu"),
        ("Bağlantı", str(lifecycle)),
        ("WebSocket", "açık" if summary.get("websocketConnected") else "kapalı"),
        (
            "Hesap",
            summary.get("email")
            or ("QR eşleşmesi (telefon hesabı)" if summary.get("paired") else "giriş yok"),
        ),
        ("Eşleştirme", "tamam" if summary.get("paired") else "yok — elyan pair"),
        ("Aktif görev", str(len(summary.get("activeTasks", [])))),
    ]
    if summary.get("lastErrorCode"):
        rows.append(("Son hata", str(summary["lastErrorCode"])))
    print("Elyan durum:")
    _print_kv(rows)
    if not pid:
        print("\nBaşlat: elyan start   ·   Açılışta otomatik: elyan service install")
    return 0


def cmd_tasks(_args: argparse.Namespace) -> int:
    summary = runtime_status_summary()
    tasks = summary.get("recentTasks", [])
    if not tasks:
        print("Görev yok. Mobilden bir görev gönderdiğinde burada görünür.")
        return 0
    print("Son görevler:")
    for task in tasks:
        title = str(task.get("title", "") or "Görev")[:60]
        status = str(task.get("status", "") or "?")
        updated = str(task.get("updatedAt", "") or "")[:19].replace("T", " ")
        line = f"  [{status:>16}] {title}"
        if updated:
            line += f"  ({updated})"
        print(line)
        error = str(task.get("error", "") or "")
        if error:
            print(f"                     ↳ {error[:100]}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool, str]] = []

    version_ok = sys.version_info >= (3, 10)
    checks.append(("Python ≥ 3.10", version_ok, platform.python_version()))

    try:
        import requests  # noqa: F401
        import websocket  # noqa: F401

        deps_ok, deps_note = True, "requests + websocket"
    except Exception as exc:
        deps_ok, deps_note = False, f"eksik: {exc}"
    checks.append(("Bağımlılıklar", deps_ok, deps_note))

    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401

        checks.append(("Tepsi ikonu", True, "pystray + pillow"))
    except Exception:
        checks.append(("Tepsi ikonu", False, "pystray/pillow eksik (daemon yine çalışır)"))

    backend_ok, backend_note = False, ""
    try:
        import requests as _requests

        response = _requests.get("https://api.elyan.dev/health", timeout=8)
        backend_ok = response.status_code < 500
        backend_note = f"HTTP {response.status_code}"
    except Exception as exc:
        backend_note = str(exc)[:60]
    checks.append(("server_brain erişimi", backend_ok, backend_note))

    summary = runtime_status_summary()
    checks.append(("Hesap", bool(summary.get("signedIn")), summary.get("email") or "elyan pair ile bağlan"))
    checks.append(("Eşleştirme", bool(summary.get("paired")), "runtime kayıtlı" if summary.get("paired") else "elyan pair"))
    checks.append(("Daemon", bool(summary.get("pid")), f"pid {summary.get('pid')}" if summary.get("pid") else "elyan start"))

    print("Elyan doktor:")
    failures = 0
    for name, ok, note in checks:
        mark = "✓" if ok else "✗"
        if not ok:
            failures += 1
        print(f"  {mark} {name.ljust(20)} {note}")
    print()

    if not getattr(args, "fix", False):
        if failures:
            print(f"{failures} sorun bulundu. Otomatik onar: elyan doctor --fix")
        else:
            print("Her şey yolunda.")
        return 0 if failures == 0 else 1

    # --fix: güvenle otomatik düzeltilebilecekleri onar; gerisi için yönlendir.
    print("Onarım deneniyor…")
    repaired: list[str] = []
    manual: list[str] = []

    if not deps_ok:
        manual.append("Bağımlılıklar eksik — yeniden kur: npm install -g elyan")

    if not summary.get("signedIn") and not summary.get("paired"):
        manual.append("Eşleştirme yok — telefonla bağla: elyan pair")
    elif str(summary.get("lastErrorCode") or "") == "desktop_runtime_device_not_found":
        manual.append(
            "Cihaz kaydı backend'de bulunamadı — telefondan yeniden eşleştir: elyan pair"
        )

    if not _daemon_running():
        if summary.get("paired") or summary.get("signedIn"):
            pid = _start_daemon_detached()
            time.sleep(1.5)
            if _daemon_running():
                repaired.append(f"Daemon başlatıldı (pid {pid}).")
            else:
                manual.append(f"Daemon başlatılamadı — log: {LOG_PATH}")
    else:
        # Daemon çalışıyor ama bağlantı düşükse yeniden başlatarak taze
        # kayıt + WS bağlantısı zorla (uyanış/askı sonrası takılmayı çözer).
        lifecycle = str(summary.get("lifecycleState") or "")
        connected = bool(summary.get("websocketConnected")) or lifecycle in {"ready", "online", "connected"}
        if summary.get("paired") and not connected:
            _stop_daemon()
            pid = _start_daemon_detached()
            time.sleep(1.5)
            if _daemon_running():
                repaired.append("Daemon yeniden başlatıldı (bağlantı tazelendi).")
            else:
                manual.append(f"Daemon yeniden başlatılamadı — log: {LOG_PATH}")

    for line in repaired:
        print(f"  ✓ {line}")
    for line in manual:
        print(f"  → {line}")
    if not repaired and not manual:
        print("  Onarılacak bir şey yok.")
    return 0 if not manual else 1


# ── açılışta otomatik başlatma (servis) ─────────────────────────────────────


def _launchd_plist() -> str:
    python = _python_executable()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{SERVICE_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-m</string>
        <string>runtime.daemon</string>
    </array>
    <key>WorkingDirectory</key><string>{REPO_ROOT}</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
    <key>StandardOutPath</key><string>{LOG_PATH}</string>
    <key>StandardErrorPath</key><string>{LOG_PATH}</string>
</dict>
</plist>
"""


def _systemd_unit() -> str:
    python = _python_executable()
    return f"""[Unit]
Description=Elyan masaüstü ajanı
After=network-online.target

[Service]
ExecStart={python} -m runtime.daemon
WorkingDirectory={REPO_ROOT}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def cmd_service(args: argparse.Namespace) -> int:
    action = args.action
    system = _platform_name()

    if system == "macos":
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"
        if action == "install":
            _stop_daemon()
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_text(_launchd_plist())
            subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
            result = subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"launchctl hatası: {result.stderr.strip()}")
                return 1
            print(f"Servis kuruldu ✓ ({plist_path}) — açılışta otomatik başlar.")
            return 0
        if action == "uninstall":
            subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
            plist_path.unlink(missing_ok=True)
            _stop_daemon(quiet=True)
            print("Servis kaldırıldı.")
            return 0

    elif system == "linux":
        unit_path = Path.home() / ".config" / "systemd" / "user" / "elyan.service"
        if action == "install":
            _stop_daemon()
            unit_path.parent.mkdir(parents=True, exist_ok=True)
            unit_path.write_text(_systemd_unit())
            for command in (
                ["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", "--now", "elyan.service"],
            ):
                result = subprocess.run(command, capture_output=True, text=True)
                if result.returncode != 0:
                    print(f"systemctl hatası: {result.stderr.strip()}")
                    return 1
            print(f"Servis kuruldu ✓ ({unit_path}) — açılışta otomatik başlar.")
            return 0
        if action == "uninstall":
            subprocess.run(["systemctl", "--user", "disable", "--now", "elyan.service"], capture_output=True)
            unit_path.unlink(missing_ok=True)
            print("Servis kaldırıldı.")
            return 0

    elif system == "windows":
        task_name = "ElyanDaemon"
        if action == "install":
            _stop_daemon()
            command = f'"{_python_executable()}" -m runtime.daemon'
            result = subprocess.run(
                ["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", task_name, "/TR", command],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(f"schtasks hatası: {result.stderr.strip()}")
                return 1
            subprocess.run(["schtasks", "/Run", "/TN", task_name], capture_output=True)
            print("Servis kuruldu ✓ (Zamanlanmış Görev: ElyanDaemon) — oturum açılışında başlar.")
            return 0
        if action == "uninstall":
            subprocess.run(["schtasks", "/Delete", "/F", "/TN", task_name], capture_output=True)
            _stop_daemon(quiet=True)
            print("Servis kaldırıldı.")
            return 0

    print(f"Desteklenmeyen platform/eylem: {system}/{action}")
    return 1


def cmd_auto(_args: argparse.Namespace) -> int:
    """`elyan` (argümansız) — durumu anla, kullanıcıyı kendisi yönlendir.

    1. Eşleşme yoksa → QR eşleştirmeyi hemen başlat, bitince servisi kur.
    2. Eşleşme var ama daemon kapalıysa → başlat (servis yoksa kur).
    3. Her şey çalışıyorsa → kısa durum özeti göster.
    """
    summary = runtime_status_summary()
    paired = bool(summary.get("paired")) or bool(summary.get("signedIn"))

    if not paired:
        print("Elyan'a hoş geldin! 👋")
        print("Telefonunla eşleştirme yapılmamış — şimdi başlatılıyor.")
        print()
        code = cmd_pair(argparse.Namespace(force=False, start=False))
        if code != 0:
            return code
        # Açılışta otomatik başlasın; servis kurulumu daemon'u da başlatır.
        service_code = cmd_service(argparse.Namespace(action="install"))
        if service_code != 0:
            print("Servis kurulamadı — daemon elle başlatılıyor.")
            return cmd_start(argparse.Namespace())
        print()
        print("Hazır ✓ — artık telefondan görev gönderebilirsin.")
        return 0

    if not summary.get("pid"):
        print("Eşleşme tamam ama Elyan çalışmıyor — başlatılıyor…")
        return cmd_start(argparse.Namespace())

    return cmd_status(_args)


def _mcp_servers_from_state() -> list[dict[str, Any]]:
    snapshot = state_store.snapshot()
    skills = snapshot.get("skills", {}) if isinstance(snapshot.get("skills"), dict) else {}
    servers = skills.get("mcpServers", [])
    return [dict(item) for item in servers if isinstance(item, dict)] if isinstance(servers, list) else []


def _save_mcp_servers(servers: list[dict[str, Any]]) -> None:
    state_store.update_state({"skills": {"mcpServers": servers}})


def cmd_mcp(args: argparse.Namespace) -> int:
    """MCP sunucu yönetimi — büyüme kanalı: hazır araç ekosistemini tak.

    Sunucular state'te yaşar (skills.mcpServers); daemon araç kataloğunu her
    planlamada state'ten okur, yeniden başlatma gerekmez.
    """
    from runtime import mcp_runtime  # ağır import'u komuta kadar ertele

    action = str(getattr(args, "mcp_action", "") or "list")

    if action == "list":
        servers = _mcp_servers_from_state()
        if not servers:
            print("Kayıtlı MCP sunucusu yok.")
            print("Eklemek için: elyan mcp add <ad> --command npx --args -y,@modelcontextprotocol/server-filesystem,/tmp")
            return 0
        print("MCP sunucuları:")
        for item in servers:
            flag = "açık " if bool(item.get("enabled", True)) else "kapalı"
            command_line = " ".join([str(item.get("command", "") or ""), *[str(a) for a in (item.get("args") or [])]])
            print(f"  [{flag}] {item.get('id')}  {item.get('name')}  →  {command_line}")
        return 0

    if action == "add":
        raw_args = [part for chunk in (getattr(args, "args", None) or []) for part in str(chunk).split(",") if part]
        candidate = {
            "name": str(getattr(args, "name", "") or ""),
            "command": str(getattr(args, "command", "") or ""),
            "args": raw_args,
            "cwd": str(getattr(args, "cwd", "") or ""),
            "enabled": True,
        }
        config = mcp_runtime.normalize_server_config(candidate)
        servers = _mcp_servers_from_state()
        servers.append(config)
        _save_mcp_servers(servers)
        print(f"Eklendi: {config['id']} ({config['name']})")
        print("Araçları görmek için: elyan mcp tools")
        return 0

    if action == "remove":
        target = str(getattr(args, "server_id", "") or "").strip()
        servers = _mcp_servers_from_state()
        remaining = [item for item in servers if str(item.get("id", "")) != target]
        if len(remaining) == len(servers):
            print(f"Bulunamadı: {target}")
            return 1
        _save_mcp_servers(remaining)
        print(f"Kaldırıldı: {target}")
        return 0

    if action == "enable" or action == "disable":
        target = str(getattr(args, "server_id", "") or "").strip()
        servers = _mcp_servers_from_state()
        found = False
        for item in servers:
            if str(item.get("id", "")) == target:
                item["enabled"] = action == "enable"
                found = True
        if not found:
            print(f"Bulunamadı: {target}")
            return 1
        _save_mcp_servers(servers)
        print(f"{'Açıldı' if action == 'enable' else 'Kapatıldı'}: {target}")
        return 0

    if action == "tools":
        status = mcp_runtime.list_mcp_tools(refresh=True)
        tools = status.get("tools", []) if isinstance(status.get("tools"), list) else []
        if not tools:
            print("Keşfedilen MCP aracı yok. Sunucu ekle: elyan mcp add ...")
            return 0
        print(f"{len(tools)} MCP aracı:")
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            read_only = "salt-okur" if bool(tool.get("readOnly", False)) else "yan-etkili"
            print(f"  [{read_only}] {tool.get('serverId')}::{tool.get('name')} — {str(tool.get('description', '') or '')[:80]}")
        return 0

    print(f"Bilinmeyen mcp komutu: {action}")
    return 1


def cmd_version(_args: argparse.Namespace) -> int:
    print(f"elyan {VERSION} ({_platform_name()}, python {platform.python_version()})")
    return 0


# ─────────────────────────────── girdi noktası ──────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="elyan",
        description="Elyan masaüstü ajanı — mobilden gelen görevleri bilgisayarında yürütür.",
        epilog="Hızlı başlangıç: sadece `elyan` yaz — eşleştirme ve kurulum kendiliğinden yapılır.",
    )
    sub = parser.add_subparsers(dest="command", required=False)

    pair = sub.add_parser("pair", help="QR ile telefonuna bağla (kurulumun tamamı)")
    pair.add_argument("--force", action="store_true", help="Yeni eşleştirme oturumu zorla")
    pair.add_argument("--start", action="store_true", help="Eşleşince daemon'u hemen başlat")
    pair.set_defaults(func=cmd_pair)

    login = sub.add_parser("login", help="E-posta/şifre ile giriş (QR'sız alternatif)")
    login.add_argument("--email", default="", help="E-posta (verilmezse sorulur)")
    login.set_defaults(func=cmd_login)

    sub.add_parser("logout", help="Oturumu kapat").set_defaults(func=cmd_logout)
    sub.add_parser("start", help="Daemon'u arka planda başlat").set_defaults(func=cmd_start)
    sub.add_parser("stop", help="Daemon'u durdur").set_defaults(func=cmd_stop)
    sub.add_parser("restart", help="Daemon'u yeniden başlat").set_defaults(func=cmd_restart)
    sub.add_parser("run", help="Ön planda çalıştır (hata ayıklama)").set_defaults(func=cmd_run)
    sub.add_parser("status", help="Bağlantı ve görev durumu").set_defaults(func=cmd_status)
    sub.add_parser("tasks", help="Son görevleri listele").set_defaults(func=cmd_tasks)
    doctor = sub.add_parser("doctor", help="Kurulum sağlık kontrolü")
    doctor.add_argument("--fix", action="store_true", help="Bulunan sorunları otomatik onarmayı dene")
    doctor.set_defaults(func=cmd_doctor)

    service = sub.add_parser("service", help="Açılışta otomatik başlatma")
    service.add_argument("action", choices=["install", "uninstall"])
    service.set_defaults(func=cmd_service)

    mcp = sub.add_parser("mcp", help="MCP sunucu yönetimi (araç ekosistemi)")
    mcp_sub = mcp.add_subparsers(dest="mcp_action")
    mcp_sub.add_parser("list", help="Kayıtlı sunucuları listele")
    mcp_add = mcp_sub.add_parser("add", help="stdio MCP sunucusu ekle")
    mcp_add.add_argument("name", help="Sunucu adı")
    mcp_add.add_argument("--command", required=True, help="Çalıştırılacak komut (ör. npx)")
    mcp_add.add_argument("--args", action="append", default=[], help="Argümanlar (virgülle ya da tekrarla)")
    mcp_add.add_argument("--cwd", default="", help="Çalışma dizini (opsiyonel)")
    mcp_remove = mcp_sub.add_parser("remove", help="Sunucuyu kaldır")
    mcp_remove.add_argument("server_id")
    mcp_enable = mcp_sub.add_parser("enable", help="Sunucuyu aç")
    mcp_enable.add_argument("server_id")
    mcp_disable = mcp_sub.add_parser("disable", help="Sunucuyu kapat")
    mcp_disable.add_argument("server_id")
    mcp_sub.add_parser("tools", help="Keşfedilen araçları listele (sunucuları başlatır)")
    mcp.set_defaults(func=cmd_mcp, mcp_action="list")

    sub.add_parser("version", help="Sürüm bilgisi").set_defaults(func=cmd_version)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", cmd_auto)  # argümansız `elyan` → akıllı akış
    try:
        return int(func(args))
    except KeyboardInterrupt:
        print("\nİptal edildi.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
