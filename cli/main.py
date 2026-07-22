"""
`elyan` komutu — kurulum, kod ile eşleştirme ve daemon yönetimi.

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
import importlib.util
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from xml.sax.saxutils import escape as xml_escape

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from runtime import state_store  # noqa: E402
from runtime.daemon import LOG_PATH, PID_PATH, STOP_PATH, read_daemon_pid, runtime_status_summary  # noqa: E402


def _package_version() -> str:
    try:
        payload = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    except Exception:
        return "0.0.0"
    return str(payload.get("version", "") or "0.0.0")


VERSION = _package_version()
SERVICE_LABEL = "dev.elyan.daemon"
_OAUTH_AUTH_ENDPOINTS: dict[str, tuple[str, str]] = {
    "gmail": ("accounts.google.com", "/o/oauth2/v2/auth"),
    "google-drive": ("accounts.google.com", "/o/oauth2/v2/auth"),
    "google-calendar": ("accounts.google.com", "/o/oauth2/v2/auth"),
    "notion": ("api.notion.com", "/v1/oauth/authorize"),
    "linear": ("linear.app", "/oauth/authorize"),
    "github": ("github.com", "/login/oauth/authorize"),
    "slack": ("slack.com", "/oauth/v2/authorize"),
}


# ─────────────────────────────── yardımcılar ────────────────────────────────


def _python_executable() -> str:
    """Daemon'u CLI ile aynı ortamda başlat; sonra bilinen venv'lere düş."""
    home_venv = Path.home() / ".elyan" / "venv"
    candidates = (
        [
            Path(sys.executable),
            home_venv / "Scripts" / "python.exe",
            REPO_ROOT / "venv" / "Scripts" / "python.exe",
            REPO_ROOT / ".venv" / "Scripts" / "python.exe",
        ]
        if os.name == "nt"
        else [
            Path(sys.executable),
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


def _module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


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


def _backend_data_from_envelope(response: dict[str, Any]) -> dict[str, Any] | None:
    if not bool(response.get("ok", False)):
        return None
    capability_result = response.get("result")
    capability_result = capability_result if isinstance(capability_result, dict) else {}
    backend_result = capability_result.get("result")
    backend_result = backend_result if isinstance(backend_result, dict) else {}
    data = backend_result.get("data")
    return data if isinstance(data, dict) else None


def _validated_oauth_authorization_url(app_id: str, value: Any) -> str:
    normalized_app_id = str(app_id or "").strip().lower()
    trusted_endpoint = _OAUTH_AUTH_ENDPOINTS.get(normalized_app_id)
    if trusted_endpoint is None:
        return ""
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return ""
    trusted_host, trusted_path = trusted_endpoint
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != trusted_host
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.path != trusted_path
    ):
        return ""
    return raw


def _platform_name() -> str:
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt":
        return "windows"
    return "linux"


# Bağımlılıksız 5×7 nokta-matris blok font — eşleştirme kodunu terminalde iri
# gösterir. QR kaldırıldı: telefon kodu KAMERAYLA değil, ELLE okunur; bu yüzden
# kod okunması kolay, büyük ve net görünmelidir. Eski 5×5 font çok kaba kalıyor
# ve harfler birbirine karışıyordu (B/8, G/6…); 7 satırlık klasik dot-matrix
# çözünürlüğü her glifi ayrıştırır. 8 karakterlik kod 4+4 gruplanır.
_BIG_FONT: dict[str, tuple[str, ...]] = {
    "0": (" ███ ", "█   █", "█  ██", "█ █ █", "██  █", "█   █", " ███ "),
    "1": ("  █  ", " ██  ", "  █  ", "  █  ", "  █  ", "  █  ", " ███ "),
    "2": (" ███ ", "█   █", "    █", "   █ ", "  █  ", " █   ", "█████"),
    "3": ("████ ", "    █", "    █", " ███ ", "    █", "    █", "████ "),
    "4": ("   █ ", "  ██ ", " █ █ ", "█  █ ", "█████", "   █ ", "   █ "),
    "5": ("█████", "█    ", "████ ", "    █", "    █", "█   █", " ███ "),
    "6": (" ███ ", "█    ", "█    ", "████ ", "█   █", "█   █", " ███ "),
    "7": ("█████", "    █", "   █ ", "  █  ", " █   ", " █   ", " █   "),
    "8": (" ███ ", "█   █", "█   █", " ███ ", "█   █", "█   █", " ███ "),
    "9": (" ███ ", "█   █", "█   █", " ████", "    █", "    █", " ███ "),
    "A": (" ███ ", "█   █", "█   █", "█████", "█   █", "█   █", "█   █"),
    "B": ("████ ", "█   █", "█   █", "████ ", "█   █", "█   █", "████ "),
    "C": (" ███ ", "█   █", "█    ", "█    ", "█    ", "█   █", " ███ "),
    "D": ("████ ", "█   █", "█   █", "█   █", "█   █", "█   █", "████ "),
    "E": ("█████", "█    ", "█    ", "████ ", "█    ", "█    ", "█████"),
    "F": ("█████", "█    ", "█    ", "████ ", "█    ", "█    ", "█    "),
    "G": (" ███ ", "█   █", "█    ", "█ ███", "█   █", "█   █", " ████"),
    "H": ("█   █", "█   █", "█   █", "█████", "█   █", "█   █", "█   █"),
    "I": ("█████", "  █  ", "  █  ", "  █  ", "  █  ", "  █  ", "█████"),
    "J": ("  ███", "   █ ", "   █ ", "   █ ", "   █ ", "█  █ ", " ██  "),
    "K": ("█   █", "█  █ ", "█ █  ", "██   ", "█ █  ", "█  █ ", "█   █"),
    "L": ("█    ", "█    ", "█    ", "█    ", "█    ", "█    ", "█████"),
    "M": ("█   █", "██ ██", "█ █ █", "█ █ █", "█   █", "█   █", "█   █"),
    "N": ("█   █", "██  █", "██  █", "█ █ █", "█  ██", "█  ██", "█   █"),
    "O": (" ███ ", "█   █", "█   █", "█   █", "█   █", "█   █", " ███ "),
    "P": ("████ ", "█   █", "█   █", "████ ", "█    ", "█    ", "█    "),
    "Q": (" ███ ", "█   █", "█   █", "█   █", "█ █ █", "█  █ ", " ██ █"),
    "R": ("████ ", "█   █", "█   █", "████ ", "█ █  ", "█  █ ", "█   █"),
    "S": (" ████", "█    ", "█    ", " ███ ", "    █", "    █", "████ "),
    "T": ("█████", "  █  ", "  █  ", "  █  ", "  █  ", "  █  ", "  █  "),
    "U": ("█   █", "█   █", "█   █", "█   █", "█   █", "█   █", " ███ "),
    "V": ("█   █", "█   █", "█   █", "█   █", " █ █ ", " █ █ ", "  █  "),
    "W": ("█   █", "█   █", "█   █", "█ █ █", "█ █ █", "██ ██", "█   █"),
    "X": ("█   █", "█   █", " █ █ ", "  █  ", " █ █ ", "█   █", "█   █"),
    "Y": ("█   █", "█   █", " █ █ ", "  █  ", "  █  ", "  █  ", "  █  "),
    "Z": ("█████", "    █", "   █ ", "  █  ", " █   ", "█    ", "█████"),
    "-": ("     ", "     ", "     ", "█████", "     ", "     ", "     "),
    " ": ("     ", "     ", "     ", "     ", "     ", "     ", "     "),
}
_BIG_FONT_ROWS = 7


def _group_pairing_code(code: str) -> str:
    """Kodu okunabilirlik için 4'lü gruplara ayırır: 9PCWQGHB → 9PCW-QGHB."""
    code = str(code or "").strip().upper()
    if len(code) <= 4:
        return code
    return "-".join(code[i : i + 4] for i in range(0, len(code), 4))


def _render_big_code(code: str) -> str:
    """Eşleştirme kodunu 7 satırlık iri dot-matrix fontla döndürür
    (bağımlılıksız). 4 karakterde bir geniş grup boşluğu bırakılır."""
    code = str(code or "").strip().upper()
    if not code:
        return ""
    rows = [""] * _BIG_FONT_ROWS
    for index, ch in enumerate(code):
        glyph = _BIG_FONT.get(ch, _BIG_FONT["-"])
        gap = "    " if index and index % 4 == 0 else ("  " if index else "")
        for i in range(_BIG_FONT_ROWS):
            rows[i] += gap + glyph[i]
    return "\n".join(row.rstrip() for row in rows)


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
    try:
        state_store.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as log_handle:
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
            process = subprocess.Popen(
                [_python_executable(), "-m", "runtime.daemon"],
                **kwargs,
            )
    except OSError:
        return 0
    return process.pid


def _wait_for_daemon(timeout_seconds: float = 3.0) -> int:
    deadline = time.monotonic() + max(0.5, timeout_seconds)
    while time.monotonic() < deadline:
        running = _daemon_running()
        if running:
            return running
        time.sleep(0.1)
    return 0


def _start_daemon_and_wait(timeout_seconds: float = 3.0) -> int:
    running = _daemon_running()
    if running:
        return running
    started_pid = _start_daemon_detached()
    if not started_pid:
        return 0
    return _wait_for_daemon(timeout_seconds)


def _restore_daemon(was_running: bool) -> int:
    return _start_daemon_and_wait() if was_running else 0


# ─────────────────────────────── komutlar ───────────────────────────────────


def cmd_pair(args: argparse.Namespace) -> int:
    """Kod ile eşleştirme: terminalde 6+ karakterlik kodu İRİ fontla göster,
    kullanıcı Elyan telefon uygulamasına ELLE girsin; CLI backend'i yoklayıp
    'claimed' görünce runtime'ı otomatik kaydeder. QR yoktur."""
    existing = runtime_status_summary()
    if existing.get("registered") and not args.force:
        device_id = str(existing.get("deviceId", "") or "")
        print(f"Bu bilgisayar zaten eşleşmiş ve kayıtlı (cihaz {device_id[:8]}…).")
        print("Durum: elyan status   ·   Koparıp yeniden bağla: elyan unpair && elyan pair")
        print("Mevcut kaydı koruyup yeni oturum zorlamak için: elyan pair --force")
        return 0
    was_running = _stop_daemon()
    try:
        bridge = _bridge()
    except Exception:
        _restore_daemon(was_running)
        print("HATA: Yerel runtime güvenli şekilde başlatılamadı. Ayrıntı için: elyan doctor")
        return 1

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
    session_id = str(data.get("sessionId") or data.get("id") or "").strip()
    pairing_code = str(data.get("pairingCode") or "").strip()
    if not response.get("ok") or not session_id or not pairing_code:
        message = str((response.get("error") or {}).get("message", "") or "Eşleştirme oturumu açılamadı.")
        print(f"HATA: {message}")
        print("İnternet bağlantını kontrol et ve tekrar dene: elyan pair")
        _restore_daemon(was_running)
        return 1

    baseline_state = state_store.snapshot()
    baseline_runtime = baseline_state.get("runtime", {}) if isinstance(baseline_state.get("runtime"), dict) else {}
    baseline_runtime_token = str(baseline_runtime.get("runtimeToken", "") or "").strip()
    baseline_device_secret = str(baseline_runtime.get("deviceSecret", "") or "").strip()

    # QR YOK. Telefon kodu ELLE girer; bu yüzden claim'in beklediği tam kod
    # (pairingCode) iri fontla, tek satırda, okunması kolay biçimde gösterilir.
    # manualEntryCode ("uuid|KOD") telefona GİRİLMEZ — telefon yalnız kodu ister.
    display_code = pairing_code.upper()

    print()
    print(_render_big_code(display_code))
    print()
    print(f"  Eşleştirme kodu:  {_group_pairing_code(display_code)}   (tireyi girmene gerek yok)")
    print("  Elyan telefon uygulamasında 'Bilgisayar Eşleştir' → bu kodu gir.")
    print("  Kod 10 dakika geçerli. Bekleniyor…")
    print()

    # Aktif yoklama: arka plan thread'ine güvenme — her turda backend'den
    # oturum durumunu çek (claimed görülünce bridge kaydı da tetikler).
    # Bekleme, backend PAIRING_TTL_MINUTES=10 ile hizalı (eski 300sn bekleme
    # kod hâlâ geçerliyken 'zaman aşımı' basıyordu).
    deadline = time.monotonic() + 570
    paired = False
    poll_error_count = 0
    try:
        while time.monotonic() < deadline:
            time.sleep(3)
            session = _request(bridge, "pairing.get_session", {"sessionId": session_id})
            session_result = session.get("result", {}) if isinstance(session.get("result"), dict) else {}
            session_data = session_result.get("data", session_result) if isinstance(session_result, dict) else {}
            status = str(session_data.get("status", "") or "").strip().lower()
            if not session.get("ok"):
                poll_error_count += 1
                if poll_error_count >= 5:
                    print("\nHATA: Sunucuya art arda ulaşılamıyor — ağını kontrol edip tekrar dene: elyan pair")
                    _restore_daemon(was_running)
                    return 1
            elif status == "claimed":
                paired = True
                break
            elif status in {"expired", "cancelled", "canceled"}:
                print(f"\nOturum {status} — yeni kod için: elyan pair")
                _restore_daemon(was_running)
                return 1
            else:
                poll_error_count = 0
            # Yalnız bu oturum sırasında değişen kimlik yerel eşleşme kanıtıdır.
            snapshot = state_store.snapshot()
            runtime = snapshot.get("runtime", {}) if isinstance(snapshot.get("runtime"), dict) else {}
            current_token = str(runtime.get("runtimeToken", "") or "").strip()
            current_secret = str(runtime.get("deviceSecret", "") or "").strip()
            if (
                (current_token and current_token != baseline_runtime_token)
                or (current_secret and current_secret != baseline_device_secret)
            ):
                paired = True
                break
            print(".", end="", flush=True)
    except KeyboardInterrupt:
        _restore_daemon(was_running)
        raise
    print()

    if not paired:
        print("Eşleştirme zaman aşımına uğradı (10 dk). Tekrar dene: elyan pair")
        _restore_daemon(was_running)
        return 1

    print("Eşleştirildi ✓ — runtime kaydediliyor…")
    boot = _request(bridge, "runtime.bootstrap")

    # Bağımsız readback: "tamam" demeden önce kayıt kanıtını STATE'ten doğrula.
    # runtimeToken yoksa cihaz backend'de kayıtlı DEĞİLDİR ve görev alamaz.
    verified = state_store.snapshot()
    verified_runtime = verified.get("runtime", {}) if isinstance(verified.get("runtime"), dict) else {}
    registered = bool(str(verified_runtime.get("runtimeToken", "") or "").strip())
    device_id = str(verified_runtime.get("deviceId", "") or "")
    if boot.get("ok") and registered:
        print(f"Kurulum doğrulandı ✓  Bu bilgisayar kayıtlı: cihaz {device_id[:8]}…")
    else:
        print("UYARI: Eşleşme alındı ama cihaz kaydı DOĞRULANAMADI — görev GELMEZ.")
        print("       Çöz: elyan doctor   sonra   elyan pair --force")
        _restore_daemon(was_running)
        return 1

    if was_running or args.start:
        pid = _start_daemon_and_wait()
        if not pid:
            print(f"Daemon başlatılamadı — log: {LOG_PATH}")
            return 1
        print(f"Daemon başlatıldı (pid {pid}). Artık mobilden görev gönderebilirsin.")
    else:
        print("Başlatmak için: elyan start   (açılışta otomatik: elyan service install)")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    """E-posta/şifre ile giriş (kodsuz, telefonsuz alternatif — self-pair)."""
    email = args.email or input("E-posta: ").strip()
    password = getpass.getpass("Şifre: ")
    if not email or not password:
        print("E-posta ve şifre gerekli.")
        return 1

    was_running = _stop_daemon()
    try:
        bridge = _bridge()
        response = _request(bridge, "backend.auth_login", {"email": email, "password": password})
        if not response.get("ok"):
            message = str((response.get("error") or {}).get("message", "") or "Giriş başarısız.")
            print(f"HATA: {message}")
            _restore_daemon(was_running)
            return 1
        print("Giriş tamam ✓ — runtime kaydediliyor (self-pairing)…")
        boot = _request(bridge, "runtime.bootstrap")
        snapshot = state_store.snapshot()
        runtime = snapshot.get("runtime", {}) if isinstance(snapshot.get("runtime"), dict) else {}
        registered = bool(str(runtime.get("runtimeToken", "") or "").strip())
        if not boot.get("ok") or not registered:
            print("Kayıt doğrulanamadı — görev alınamaz. Ayrıntı için: elyan doctor")
            _restore_daemon(was_running)
            return 1
        print("Kayıt: tamam ✓")
        if was_running:
            pid = _start_daemon_and_wait()
            if not pid:
                print(f"Daemon yeniden başlatılamadı — log: {LOG_PATH}")
                return 1
            print(f"Daemon yeniden başlatıldı (pid {pid}).")
        return 0
    except KeyboardInterrupt:
        _restore_daemon(was_running)
        raise
    except Exception:
        _restore_daemon(was_running)
        print("HATA: Giriş akışı güvenli şekilde tamamlanamadı. Ayrıntı için: elyan doctor")
        return 1


def cmd_logout(_args: argparse.Namespace) -> int:
    was_running = _stop_daemon()
    bridge = _bridge()
    _request(bridge, "backend.auth_logout")
    print("Oturum kapatıldı.")
    if was_running:
        print("Daemon durduruldu (oturumsuz görev alınamaz).")
    print("Not: Kod eşleşmesi hâlâ duruyor. Tamamen koparmak için: elyan unpair")
    return 0


def cmd_unpair(_args: argparse.Namespace) -> int:
    """Bağlantıyı TAM kopar: cihazı backend'den kaldır + yerel kimliği sil.

    Sıra önemli: önce sunucu tarafı (elimizde kimlik varken), sonra yerel
    temizlik. Sunucuya ulaşılamasa bile yerel kimlik silinir — cihaz artık
    görev alamaz; kalan sunucu kaydı bir dahaki pair'de self-heal düşürülür.
    """
    _stop_daemon()
    snapshot = state_store.snapshot()
    runtime = snapshot.get("runtime", {}) if isinstance(snapshot.get("runtime"), dict) else {}
    pairing = snapshot.get("pairing", {}) if isinstance(snapshot.get("pairing"), dict) else {}
    device_id = str(runtime.get("deviceId", "") or "").strip()
    had_identity = bool(
        device_id
        or str(runtime.get("deviceSecret", "") or "").strip()
        or str(runtime.get("runtimeToken", "") or "").strip()
        or str(pairing.get("pairingToken", "") or "").strip()
    )
    if not had_identity:
        print("Bağlı cihaz yok — koparılacak eşleşme bulunamadı.")
        return 0

    device_name = str(pairing.get("deviceName", "") or "") or (socket.gethostname() or "bu bilgisayar")
    print(f"Koparılıyor: cihaz {device_id[:8] + '…' if device_id else '(kaydsız eşleşme)'} ({device_name})")

    backend_removed = False
    if device_id:
        bridge = _bridge()
        response = _request(bridge, "backend.device_deactivate", {"deviceId": device_id})
        backend_removed = bool(response.get("ok"))
        if backend_removed:
            print("Sunucu kaydı kaldırıldı ✓")
        else:
            message = str((response.get("error") or {}).get("message", "") or "sunucuya ulaşılamadı")
            print(f"Sunucu kaydı kaldırılamadı ({message}) — yerel kimlik yine siliniyor.")

    state_store.update_state(
        {
            "runtime": {
                "deviceId": "",
                "deviceSecret": "",
                "runtimeToken": "",
                "connectionId": "",
                "ready": False,
                "lifecycleState": "stopped",
                "websocketConnected": False,
            },
            "pairing": {
                "pairingToken": "",
                "pairingCode": "",
                "manualEntryCode": "",
                "qrText": "",
                "qrDataUrl": "",
                "lastSessionId": "",
                "lastSessionStatus": "",
                "connectedDevices": [],
                "desktopDeviceId": "",
            },
        }
    )

    # Bağımsız readback: silindi demeden önce doğrula.
    verify = state_store.snapshot().get("runtime", {})
    verify = verify if isinstance(verify, dict) else {}
    if str(verify.get("deviceSecret", "") or "").strip() or str(verify.get("runtimeToken", "") or "").strip():
        print("HATA: Yerel kimlik silinemedi — elyan doctor ile bak.")
        return 1
    print("Yerel eşleşme kimliği silindi ✓ — bu bilgisayar artık görev alamaz.")
    if not backend_removed and device_id:
        print("Not: Sunucudaki kayıt duruyor olabilir; bir sonraki 'elyan pair' bayat cihazı otomatik düşürür.")
    print("Yeniden bağlamak için: elyan pair")
    return 0


def cmd_start(_args: argparse.Namespace) -> int:
    if _daemon_running():
        print(f"Daemon zaten çalışıyor (pid {_daemon_running()}).")
        return 0
    pid = _start_daemon_and_wait()
    if pid:
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
    paired = bool(summary.get("paired"))
    registered = bool(summary.get("registered"))
    device_id = str(summary.get("deviceId", "") or "")
    device_name = str(summary.get("deviceName", "") or "")

    # "Eşleşti" ≠ "kurulu": görev alabilmek için cihazın backend'de KAYITLI
    # olması gerekir. İki durumu ayrı ve dürüst göster.
    if paired and registered:
        pairing_line = "tamam ✓ (cihaz kayıtlı, görev alabilir)"
    elif paired:
        pairing_line = "eşleşti ama cihaz kaydı YOK — görev ALAMAZ. Çöz: elyan pair --force"
    else:
        pairing_line = "yok — elyan pair"

    rows = [
        ("Daemon", f"çalışıyor (pid {pid})" if pid else "durdu"),
        ("Bağlantı", str(lifecycle)),
        ("WebSocket", "açık" if summary.get("websocketConnected") else "kapalı"),
        (
            "Hesap",
            summary.get("email")
            or ("kod eşleşmesi (telefon hesabı)" if paired else "giriş yok"),
        ),
        ("Eşleştirme", pairing_line),
    ]
    if paired and device_id:
        label = f"{device_id[:8]}…"
        if device_name:
            label += f" ({device_name})"
        rows.append(("Bu cihaz", label))
    phones = [
        item.get("name") or item.get("platform") or "telefon"
        for item in summary.get("connectedDevices", [])
        if isinstance(item, dict)
    ]
    if phones:
        rows.append(("Bağlı telefon", ", ".join(str(p) for p in phones[:3])))
    if summary.get("pairedAt"):
        rows.append(("Eşleşme zamanı", str(summary["pairedAt"])[:19].replace("T", " ")))
    rows.append(("Aktif görev", str(len(summary.get("activeTasks", [])))))
    if summary.get("lastErrorCode"):
        rows.append(("Son hata", str(summary["lastErrorCode"])))
    print("Elyan durum:")
    _print_kv(rows)
    if not pid:
        print("\nBaşlat: elyan start   ·   Açılışta otomatik: elyan service install")
    if paired:
        print("Bağlantıyı koparmak için: elyan unpair")
    return 0


def cmd_tasks(_args: argparse.Namespace) -> int:
    summary = runtime_status_summary()
    tasks = summary.get("recentTasks", [])
    if not tasks:
        print("Görev yok. Mobilden bir görev gönderdiğinde burada görünür.")
        return 0
    if bool(getattr(_args, "report", False)):
        return _print_failure_report()
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


def _print_failure_report() -> int:
    """Öğrenme döngüsünün ilk halkası: son başarısız görevleri hata koduna
    göre toplar — hangi görev tipi patlıyorsa oraya tool/skill/MCP yatırımı.
    Tüm gelen kutusunu okur (recentTasks 10 ile sınırlı, rapor değil)."""
    snapshot = state_store.snapshot()
    inbox = snapshot.get("taskInbox", {}) if isinstance(snapshot.get("taskInbox"), dict) else {}
    items = inbox.get("items", []) if isinstance(inbox.get("items"), list) else []
    failures: dict[str, list[dict[str, Any]]] = {}
    total = 0
    for item in items:
        if not isinstance(item, dict) or str(item.get("status", "")) != "failed":
            continue
        total += 1
        code = str(item.get("error", "") or "").strip() or "(kodsuz)"
        failures.setdefault(code, []).append(item)
    if not failures:
        print("Kayıtlı başarısız görev yok — zincir temiz görünüyor.")
        return 0
    print(f"Başarısız görev raporu ({total} görev, {len(failures)} hata sınıfı):\n")
    for code, group in sorted(failures.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(group):>3}×  {code}")
        for sample in group[:2]:
            title = str(sample.get("title", "") or "Görev")[:56]
            summary_text = str(sample.get("summary", "") or "")[:80]
            print(f"        · {title}" + (f" — {summary_text}" if summary_text else ""))
    print(
        "\nYatırım rehberi: aynı hata sınıfı tekrar ediyorsa eksik olan\n"
        "  - yetenekse   → runtime/capability_spec.py'a spec ekle\n"
        "  - tarif ise   → runtime/skill_catalog.py'a skill tarifi yaz\n"
        "  - dış araçsa  → elyan mcp add ile sunucu tak"
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool, str]] = []

    version_ok = (3, 10) <= sys.version_info[:2] < (3, 14)
    checks.append(("Python 3.10–3.13", version_ok, platform.python_version()))

    core_modules = {
        "requests": "requests",
        "httpx": "httpx",
        "websocket": "websocket-client",
        "psutil": "psutil",
        "PIL": "pillow",
        "openpyxl": "openpyxl",
        "litellm": "litellm",
        "langgraph": "langgraph",
        "google.genai": "google-genai",
    }
    missing_core = [
        label
        for module, label in core_modules.items()
        if not _module_available(module)
    ]
    deps_ok = not missing_core
    deps_note = "çekirdek hazır" if deps_ok else f"eksik: {', '.join(missing_core)}"
    checks.append(("Bağımlılıklar", deps_ok, deps_note))

    dependency_blocked: list[str] = []
    try:
        from runtime.capability_registry import capability_names, capability_readiness

        runtime_state = state_store.snapshot()
        capability_set = sorted(capability_names())
        for capability in capability_set:
            readiness = capability_readiness(capability, state=runtime_state)
            if str(readiness.get("errorCode", "") or "") == "DEPENDENCY_UNAVAILABLE":
                dependency_blocked.append(capability)
        capability_note = f"{len(capability_set)} kayıtlı"
        if dependency_blocked:
            capability_note += f", {len(dependency_blocked)} bağımlılık bekliyor"
        else:
            capability_note += ", bağımlılık engeli yok"
        capabilities_ok = not dependency_blocked
    except Exception as exc:
        capabilities_ok = False
        capability_note = f"durum okunamadı: {str(exc)[:48]}"
    checks.append(("Yetenek motoru", capabilities_ok, capability_note))

    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401

        checks.append(("Tepsi ikonu", True, "pystray + pillow"))
    except Exception:
        checks.append(("Tepsi ikonu", False, "pystray/pillow eksik (daemon yine çalışır)"))

    backend_ok, backend_note = False, ""
    try:
        import requests as _requests

        response = _requests.get("https://api.elyan.dev/healthz", timeout=8)
        backend_ok = 200 <= response.status_code < 300
        backend_note = f"HTTP {response.status_code}"
    except Exception as exc:
        backend_note = str(exc)[:60]
    checks.append(("server_brain erişimi", backend_ok, backend_note))

    summary = runtime_status_summary()
    account_ready = bool(summary.get("signedIn") or summary.get("paired"))
    account_note = summary.get("email") or ("telefon hesabı ile eşleşti" if summary.get("paired") else "elyan pair ile bağlan")
    checks.append(("Hesap", account_ready, account_note))
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

    repair_daemon_was_running = bool(_daemon_running())
    repair_daemon_stopped = False
    repair_daemon_restarted = False
    if dependency_blocked:
        extras = REPO_ROOT / "scripts" / "install_extras.py"
        if repair_daemon_was_running:
            repair_daemon_stopped = _stop_daemon()
        if repair_daemon_was_running and not repair_daemon_stopped:
            install_result = None
            manual.append("Daemon durdurulamadığı için paket onarımı uygulanmadı.")
        else:
            try:
                install_result = subprocess.run(
                    [sys.executable, str(extras), "--force"],
                    cwd=str(REPO_ROOT),
                    timeout=1800,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                install_result = None
            if install_result is not None and install_result.returncode == 0:
                repaired.append("Eksik yetenek paketleri kuruldu.")
            else:
                manual.append(
                    "Yetenek paketleri tamamlanamadı; `elyan doctor --fix` ile tekrar dene."
                )
        if repair_daemon_stopped:
            pid = _start_daemon_detached()
            time.sleep(1.5)
            if _daemon_running():
                repair_daemon_restarted = True
                repaired.append(
                    f"Daemon güncel paketlerle yeniden başlatıldı (pid {pid})."
                )
            else:
                manual.append(f"Daemon yeniden başlatılamadı — log: {LOG_PATH}")

    summary = runtime_status_summary()

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
    elif not repair_daemon_restarted:
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
    python = xml_escape(_python_executable())
    working_directory = xml_escape(str(REPO_ROOT))
    log_path = xml_escape(str(LOG_PATH))
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
    <key>WorkingDirectory</key><string>{working_directory}</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
    <key>StandardOutPath</key><string>{log_path}</string>
    <key>StandardErrorPath</key><string>{log_path}</string>
</dict>
</plist>
"""


def _systemd_unit() -> str:
    def quote(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    python = quote(_python_executable())
    working_directory = quote(str(REPO_ROOT))
    return f"""[Unit]
Description=Elyan masaüstü ajanı
After=network-online.target

[Service]
ExecStart={python} -m runtime.daemon
WorkingDirectory={working_directory}
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
            was_running = _stop_daemon()
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_text(_launchd_plist(), encoding="utf-8")
            try:
                subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
                result = subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True, text=True)
            except OSError:
                _restore_daemon(was_running)
                print("launchctl çalıştırılamadı; servis kurulmadı.")
                return 1
            if result.returncode != 0:
                _restore_daemon(was_running)
                print(f"launchctl hatası: {result.stderr.strip()}")
                return 1
            pid = _wait_for_daemon(5.0)
            if not pid:
                subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
                _restore_daemon(was_running)
                print(f"Servis kaydedildi ancak daemon başlamadı — log: {LOG_PATH}")
                return 1
            print(f"Servis kuruldu ✓ ({plist_path}) — daemon pid {pid}, açılışta otomatik başlar.")
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
            was_running = _stop_daemon()
            unit_path.parent.mkdir(parents=True, exist_ok=True)
            unit_path.write_text(_systemd_unit(), encoding="utf-8")
            for command in (
                ["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", "--now", "elyan.service"],
            ):
                try:
                    result = subprocess.run(command, capture_output=True, text=True)
                except OSError:
                    _restore_daemon(was_running)
                    print("systemctl çalıştırılamadı; servis kurulmadı.")
                    return 1
                if result.returncode != 0:
                    _restore_daemon(was_running)
                    print(f"systemctl hatası: {result.stderr.strip()}")
                    return 1
            pid = _wait_for_daemon(5.0)
            if not pid:
                subprocess.run(["systemctl", "--user", "disable", "--now", "elyan.service"], capture_output=True)
                _restore_daemon(was_running)
                print(f"Servis kaydedildi ancak daemon başlamadı — log: {LOG_PATH}")
                return 1
            print(f"Servis kuruldu ✓ ({unit_path}) — daemon pid {pid}, açılışta otomatik başlar.")
            return 0
        if action == "uninstall":
            subprocess.run(["systemctl", "--user", "disable", "--now", "elyan.service"], capture_output=True)
            unit_path.unlink(missing_ok=True)
            print("Servis kaldırıldı.")
            return 0

    elif system == "windows":
        task_name = "ElyanDaemon"
        if action == "install":
            was_running = _stop_daemon()
            bootstrap_code = (
                "import runpy,sys;"
                f"sys.path.insert(0,{str(REPO_ROOT)!r});"
                "runpy.run_module('runtime.daemon',run_name='__main__')"
            )
            command = subprocess.list2cmdline(
                [_python_executable(), "-c", bootstrap_code]
            )
            try:
                result = subprocess.run(
                    ["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", task_name, "/TR", command],
                    capture_output=True,
                    text=True,
                )
            except OSError:
                _restore_daemon(was_running)
                print("schtasks çalıştırılamadı; servis kurulmadı.")
                return 1
            if result.returncode != 0:
                _restore_daemon(was_running)
                print(f"schtasks hatası: {result.stderr.strip()}")
                return 1
            run_result = subprocess.run(["schtasks", "/Run", "/TN", task_name], capture_output=True)
            pid = _wait_for_daemon(5.0) if run_result.returncode == 0 else 0
            if not pid:
                subprocess.run(["schtasks", "/Delete", "/F", "/TN", task_name], capture_output=True)
                _restore_daemon(was_running)
                print(f"Zamanlanmış görev kaydedildi ancak daemon başlamadı — log: {LOG_PATH}")
                return 1
            print(f"Servis kuruldu ✓ (Zamanlanmış Görev: ElyanDaemon) — daemon pid {pid}.")
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

    1. Eşleşme yoksa → kod eşleştirmeyi hemen başlat, bitince servisi kur.
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


def cmd_apps(_args: argparse.Namespace) -> int:
    response = _request(_bridge(), "backend.integrations.apps")
    data = _backend_data_from_envelope(response)
    if data is None:
        print("Uygulama kataloğu alınamadı. Önce `elyan login` ile giriş yap.")
        return 1
    apps = data.get("apps", [])
    if not isinstance(apps, list) or not apps:
        print("Bağlanabilir uygulama bulunamadı.")
        return 0
    print("Elyan Uygulamaları:")
    for item in apps:
        if not isinstance(item, dict):
            continue
        if bool(item.get("connected", False)):
            status = "Bağlı ✓"
        elif bool(item.get("available", False)):
            status = "Bağlanabilir"
        else:
            status = "Hazırlanıyor"
        print(f"  [{status}] {item.get('id')} — {item.get('displayName')}")
    print("Bağlamak için: elyan connect gmail")
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    app_id = str(getattr(args, "app_id", "") or "").strip().lower()
    response = _request(
        _bridge(),
        "backend.integrations.oauth_start",
        {"appId": app_id},
    )
    data = _backend_data_from_envelope(response)
    if data is None:
        print("Bağlantı başlatılamadı. Önce `elyan login` ile giriş yap ve uygulamanın hazır olduğunu kontrol et.")
        return 1
    auth_url = _validated_oauth_authorization_url(app_id, data.get("authUrl"))
    if not auth_url:
        print("OAuth adresi güvenlik doğrulamasından geçmedi; tarayıcı açılmadı.")
        return 1
    try:
        opened = webbrowser.open(auth_url, new=2)
    except Exception:
        opened = False
    print(f"{app_id} için güvenli giriş ekranı {'açıldı' if opened else 'hazır'}.")
    if not opened:
        print(auth_url)
    print("Hesabına giriş yaptığında bağlantı otomatik tamamlanacak.")
    return 0


def cmd_disconnect(args: argparse.Namespace) -> int:
    app_id = str(getattr(args, "app_id", "") or "").strip().lower()
    response = _request(
        _bridge(),
        "backend.integrations.disconnect",
        {"appId": app_id, "_confirmed": True},
    )
    if not response.get("ok"):
        print(f"Bağlantı kaldırılamadı: {app_id}")
        return 1
    print(f"Bağlantı kaldırıldı: {app_id}")
    return 0


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

    pair = sub.add_parser("pair", help="Kod ile telefonuna bağla (kurulumun tamamı)")
    pair.add_argument("--force", action="store_true", help="Yeni eşleştirme oturumu zorla")
    pair.add_argument("--start", action="store_true", help="Eşleşince daemon'u hemen başlat")
    pair.set_defaults(func=cmd_pair)

    login = sub.add_parser("login", help="E-posta/şifre ile giriş (kodsuz, telefonsuz alternatif)")
    login.add_argument("--email", default="", help="E-posta (verilmezse sorulur)")
    login.set_defaults(func=cmd_login)

    sub.add_parser("logout", help="Oturumu kapat").set_defaults(func=cmd_logout)
    sub.add_parser("unpair", help="Bağlantıyı tam kopar (sunucu kaydı + yerel kimlik)").set_defaults(func=cmd_unpair)
    sub.add_parser("start", help="Daemon'u arka planda başlat").set_defaults(func=cmd_start)
    sub.add_parser("stop", help="Daemon'u durdur").set_defaults(func=cmd_stop)
    sub.add_parser("restart", help="Daemon'u yeniden başlat").set_defaults(func=cmd_restart)
    sub.add_parser("run", help="Ön planda çalıştır (hata ayıklama)").set_defaults(func=cmd_run)
    sub.add_parser("status", help="Bağlantı ve görev durumu").set_defaults(func=cmd_status)
    tasks_cmd = sub.add_parser("tasks", help="Son görevleri listele")
    tasks_cmd.add_argument("--report", action="store_true", help="Başarısız görevleri hata sınıfına göre topla")
    tasks_cmd.set_defaults(func=cmd_tasks)
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

    sub.add_parser("apps", help="Hazır uygulamaları ve bağlantı durumunu listele").set_defaults(func=cmd_apps)
    connect = sub.add_parser("connect", help="Bir uygulamayı tek adımda OAuth ile bağla")
    connect.add_argument("app_id", help="Uygulama kimliği (ör. gmail, notion, linear)")
    connect.set_defaults(func=cmd_connect)
    disconnect = sub.add_parser("disconnect", help="Uygulama bağlantısını kaldır")
    disconnect.add_argument("app_id", help="Uygulama kimliği")
    disconnect.set_defaults(func=cmd_disconnect)

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
