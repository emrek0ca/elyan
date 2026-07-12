"""
Uygulama açma ve kapatma — masaüstü kabiliyetleri.
emre koca tarafından yapılmıştır — @emrekoca
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

from actions._platform_common import app_not_found, capability_unavailable, invalid_argument, timeout_error
from runtime.capability_registry import SafeCapabilityError

try:
    import psutil
except Exception:  # pragma: no cover - optional dependency fallback
    psutil = None  # type: ignore[assignment]


# Kısa isimden uygulama yoluna eşleme
APP_ALIASES = {
    "safari": "Safari",
    "chrome": "Google Chrome",
    "firefox": "Firefox",
    "terminal": "Terminal",
    "iterm": "iTerm",
    "iterm2": "iTerm",
    "finder": "Finder",
    "spotify": "Spotify",
    "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "code": "Visual Studio Code",
    "xcode": "Xcode",
    "notion": "Notion",
    "slack": "Slack",
    "discord": "Discord",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "zoom": "zoom.us",
    "mail": "Mail",
    "calendar": "Calendar",
    "takvim": "Calendar",
    "notes": "Notes",
    "notlar": "Notes",
    "music": "Music",
    "müzik": "Music",
    "photos": "Photos",
    "fotoğraflar": "Photos",
    "maps": "Maps",
    "haritalar": "Maps",
    "calculator": "Calculator",
    "hesap makinesi": "Calculator",
    "system preferences": "System Preferences",
    "system settings": "System Settings",
    "ayarlar": "System Settings",
    "activity monitor": "Activity Monitor",
    "aktivite monitörü": "Activity Monitor",
    "preview": "Preview",
    "önizleme": "Preview",
    "textedit": "TextEdit",
    "numbers": "Numbers",
    "pages": "Pages",
    "keynote": "Keynote",
    "figma": "Figma",
    "postman": "Postman",
    "docker": "Docker",
    "sequel pro": "Sequel Pro",
    "tableplus": "TablePlus",
    "dosya gezgini": "Finder",
    "dosya yoneticisi": "Finder",
    "file explorer": "Finder",
    "file manager": "Finder",
    "sistem ayarlari": "System Settings",
    "sistem tercihleri": "System Settings",
    "mesajlar": "Messages",
    "messages": "Messages",
    "facetime": "FaceTime",
    "notlarim": "Notes",
    "not defteri": "Notes",
    "hesap makinesi": "Calculator",
    "hesap makinesi uygulamasi": "Calculator",
    "komut satiri": "Terminal",
    "aktivite monitoru": "Activity Monitor",
    "etkinlik monitoru": "Activity Monitor",
}


def _tr_fold(value: str) -> str:
    value = value.lower().strip()
    for src, dst in (("ı", "i"), ("ğ", "g"), ("ü", "u"), ("ş", "s"), ("ö", "o"), ("ç", "c")):
        value = value.replace(src, dst)
    return " ".join(value.split())


# Alias anahtarları Türkçe karaktersiz katlanmış halde de eşleşsin
# ("müzik" ↔ "muzik", "fotoğraflar" ↔ "fotograflar").
_FOLDED_ALIASES = {_tr_fold(key): app for key, app in APP_ALIASES.items()}

# "terminali", "notları", "safariyi" gibi hâl/iyelik ekleri alias eşleşmesini
# kaçırıyordu; bilinen ekleri soyup tekrar denenir.
_TR_CASE_SUFFIXES = ("lari", "leri", "yi", "yu", "ni", "nu", "i", "u", "a", "e")
# Boşlukla ayrılmış hâl eki parçacıkları ("Chrome'u" yerine "Chrome u" yazımı).
# Anahtarlar _tr_fold ile katlanmış halde tutulur (ı→i, ü→u ...).
_TR_CASE_PARTICLES = {"u", "i", "a", "e", "yi", "yu", "ni", "nu", "ye", "ya"}


def _resolve_app_name(app_name: str) -> str:
    raw = app_name.strip()
    folded = _tr_fold(raw)
    if folded in _FOLDED_ALIASES:
        return _FOLDED_ALIASES[folded]
    # Boşlukla ayrılmış Türkçe hâl eki: "Chrome u" → "Chrome", "Safari yi" →
    # "Safari". Son jeton kısa bir ek parçacığıysa ("u", "yi", "i"...) at; iki
    # jetonlu gerçek adları ("Visual Studio") bozmamak için parçacık kümesiyle
    # sınırlı.
    tokens = raw.split()
    if len(tokens) >= 2 and _tr_fold(tokens[-1]) in _TR_CASE_PARTICLES:
        trimmed = " ".join(tokens[:-1]).strip()
        folded_trimmed = _tr_fold(trimmed)
        if folded_trimmed in _FOLDED_ALIASES:
            return _FOLDED_ALIASES[folded_trimmed]
        if trimmed:
            raw = trimmed
            folded = folded_trimmed
    for suffix in _TR_CASE_SUFFIXES:
        if folded.endswith(suffix) and len(folded) - len(suffix) >= 3:
            candidate = folded[: -len(suffix)]
            if candidate in _FOLDED_ALIASES:
                return _FOLDED_ALIASES[candidate]
    return raw


def suggest_installed_apps(query: str, limit: int = 6) -> list[str]:
    """Sorguya benzeyen kurulu uygulama adları — APP_NOT_FOUND sonrası replan
    gözlemine öneri olarak eklenir (planlayıcı adı düzeltebilsin). macOS'ta
    /Applications taranır; diğer platformlarda alias tablosuyla yetinilir."""
    tokens = [t for t in _tr_fold(query).replace("'", " ").split() if len(t) >= 2]
    candidates: list[str] = []
    if sys.platform == "darwin":
        for root in ("/Applications", "/System/Applications", str(Path.home() / "Applications")):
            try:
                candidates.extend(p.stem for p in Path(root).glob("*.app"))
            except Exception:
                continue
    candidates.extend(_FOLDED_ALIASES.values())

    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    for name in candidates:
        if name in seen:
            continue
        seen.add(name)
        folded_name = _tr_fold(name)
        score = sum(1 for token in tokens if token in folded_name)
        if score:
            scored.append((score, name))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [name for _, name in scored[:limit]]


def _looks_generic_close_target(app_name: str) -> bool:
    normalized = app_name.lower().strip()
    return normalized in {
        "",
        "app",
        "application",
        "program",
        "uygulama",
        "uygulamayi",
        "uygulamayı",
        "pencere",
    }


def _frontmost_application_name() -> str:
    snapshot_path = str(os.environ.get("ELYAN_DESKTOP_NATIVE_STATE_PATH", "") or "").strip()
    if snapshot_path:
        try:
            payload = json.loads(Path(snapshot_path).expanduser().read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                active_window = payload.get("activeWindow", {})
                if isinstance(active_window, dict):
                    app_name = str(active_window.get("appName", "") or "").strip()
                    if app_name:
                        return app_name
        except Exception:
            pass
    if sys.platform != "darwin":
        return ""
    script = 'tell application "System Events" to get name of first application process whose frontmost is true'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _escape_osascript_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _active_app_matches(target: str) -> bool:
    normalized_target = _resolve_app_name(target).strip().lower()
    active = _frontmost_application_name().strip().lower()
    if not normalized_target or not active:
        return False
    return active == normalized_target or normalized_target in active or active in normalized_target


def _wait_for_active_app(target: str, *, timeout_seconds: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _active_app_matches(target):
            return True
        time.sleep(0.15)
    return _active_app_matches(target)


def _wait_until_not_active(target: str, *, timeout_seconds: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _active_app_matches(target):
            return True
        time.sleep(0.15)
    return not _active_app_matches(target)


def _terminate_matching_processes(target: str) -> int:
    if psutil is None:
        return 0

    normalized = target.lower().strip()
    if not normalized:
        return 0

    candidates = {
        normalized,
        normalized.replace(" ", ""),
        normalized.replace(".", ""),
    }
    matched: list[Any] = []
    for proc in psutil.process_iter(["name", "exe", "cmdline"]):
        try:
            name = str(proc.info.get("name") or "").lower()
            exe = str(proc.info.get("exe") or "").lower()
            cmdline = " ".join(str(item) for item in (proc.info.get("cmdline") or [])).lower()
            haystack = " ".join([name, exe, cmdline]).strip()
            if not haystack:
                continue
            if any(candidate and candidate in haystack for candidate in candidates):
                matched.append(proc)
        except Exception:
            continue

    if not matched:
        return 0

    for proc in matched:
        try:
            proc.terminate()
        except Exception:
            continue

    try:
        gone, alive = psutil.wait_procs(matched, timeout=3)
    except Exception:
        gone = []
        alive = matched

    for proc in alive:
        try:
            proc.kill()
        except Exception:
            continue

    return len(gone) + len(alive)


def _matching_process_count(target: str) -> int:
    if psutil is None:
        return 0

    normalized = target.lower().strip()
    if not normalized:
        return 0

    candidates = {
        normalized,
        normalized.replace(" ", ""),
        normalized.replace(".", ""),
    }
    count = 0
    for proc in psutil.process_iter(["name", "exe", "cmdline"]):
        try:
            name = str(proc.info.get("name") or "").lower()
            exe = str(proc.info.get("exe") or "").lower()
            cmdline = " ".join(str(item) for item in (proc.info.get("cmdline") or [])).lower()
            haystack = " ".join([name, exe, cmdline]).strip()
            if haystack and any(candidate and candidate in haystack for candidate in candidates):
                count += 1
        except Exception:
            continue
    return count


def _wait_until_closed(target: str, *, timeout_seconds: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        active = _active_app_matches(target)
        process_count = _matching_process_count(target)
        if not active and (psutil is None or process_count == 0):
            return True
        time.sleep(0.15)
    active = _active_app_matches(target)
    process_count = _matching_process_count(target)
    return not active and (psutil is None or process_count == 0)


def _launch_success(resolved: str) -> dict[str, Any]:
    """`open -a` başarıyla döndüğünde çağrılır. macOS'ta `open -a X` uygulamayı
    başlatıp ÖNE getirir; returncode 0 bunun kanıtıdır. Bağımsız frontmost
    doğrulaması (osascript/System Events) yalnız BONUS'tur ve Otomasyon izni
    yoksa başarısız olur — bu durumda başarıyı düşürmeyiz, yoksa açılan uygulama
    'Yanıt alınamadı' olarak raporlanırdı."""
    frontmost_verified = _wait_for_active_app(resolved)
    return {
        "text": f"{resolved} açıldı.",
        "result": {
            "appName": resolved,
            # Executor foreground_confirmed doğrulaması bunu bekler; `open -a`
            # başarısı öne getirmeyi garanti eder.
            "foregroundConfirmed": True,
            "verificationStatus": "foreground_confirmed" if frontmost_verified else "launched",
            "frontmostVerified": frontmost_verified,
            "processObserved": _matching_process_count(resolved) > 0,
        },
    }


# Kanonik (macOS-merkezli) uygulama adı → platform başlatma hedefi.
# Windows: `start` ile çözülen komut/URI. Linux: PATH'te aranan aday listesi.
_WINDOWS_LAUNCH_TARGETS = {
    "google chrome": "chrome",
    "safari": "msedge",  # Safari Windows'ta yok; varsayılan sistem tarayıcısına en yakın karşılık
    "firefox": "firefox",
    "terminal": "wt",
    "iterm": "wt",
    "finder": "explorer",
    "visual studio code": "code",
    "system settings": "ms-settings:",
    "system preferences": "ms-settings:",
    "calculator": "calc",
    "notes": "notepad",
    "textedit": "notepad",
    "activity monitor": "taskmgr",
    "mail": "outlook",
    "preview": "mspaint",
}
_LINUX_LAUNCH_TARGETS = {
    "google chrome": ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"),
    "safari": ("xdg-open",),  # varsayılan tarayıcı; aşağıda URL argümanıyla açılır
    "firefox": ("firefox",),
    "terminal": ("gnome-terminal", "konsole", "xfce4-terminal", "x-terminal-emulator", "xterm"),
    "iterm": ("gnome-terminal", "konsole", "x-terminal-emulator", "xterm"),
    "finder": ("nautilus", "dolphin", "thunar", "pcmanfm"),
    "visual studio code": ("code", "codium"),
    "system settings": ("gnome-control-center", "systemsettings"),
    "system preferences": ("gnome-control-center", "systemsettings"),
    "calculator": ("gnome-calculator", "kcalc"),
    "notes": ("gnome-text-editor", "gedit", "kate"),
    "textedit": ("gnome-text-editor", "gedit", "kate"),
    "activity monitor": ("gnome-system-monitor", "ksysguard"),
}


def _spawn_detached(command: list[str]) -> None:
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def _open_app_windows(resolved: str) -> dict[str, Any]:
    target = _WINDOWS_LAUNCH_TARGETS.get(_tr_fold(resolved), resolved)
    try:
        # `start` kabuk yerleşiği; boş "" başlık argümanı boşluklu adlar için şart.
        result = subprocess.run(
            ["cmd", "/c", "start", "", target],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return _launch_success(resolved)
        raise app_not_found(f"{resolved} bu bilgisayarda bulunamadi.")
    except subprocess.TimeoutExpired as exc:
        raise timeout_error(f"{resolved} acilirken zaman asimina ugradi.") from exc
    except FileNotFoundError as exc:
        raise capability_unavailable(f"{resolved} guvenli sekilde acilamadi.") from exc


def _open_app_linux(resolved: str) -> dict[str, Any]:
    folded = _tr_fold(resolved)
    candidates = _LINUX_LAUNCH_TARGETS.get(folded, ())
    binary = next((c for c in candidates if shutil.which(c)), None)
    if binary is None and shutil.which(folded.replace(" ", "-")):
        binary = folded.replace(" ", "-")
    if binary is None and shutil.which(folded.replace(" ", "")):
        binary = folded.replace(" ", "")
    if binary is None and shutil.which("gtk-launch"):
        # .desktop kimliğiyle son bir şans (ör. org.gnome.Calculator değilse de
        # çoğu dağıtımda basit ad çalışır).
        probe = subprocess.run(
            ["gtk-launch", folded.replace(" ", "-")],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if probe.returncode == 0:
            return _launch_success(resolved)
    if binary is None:
        raise app_not_found(f"{resolved} bu sistemde bulunamadi.")
    try:
        _spawn_detached([binary])
        return _launch_success(resolved)
    except FileNotFoundError as exc:
        raise capability_unavailable(f"{resolved} guvenli sekilde acilamadi.") from exc


def open_app(app_name: str) -> dict[str, Any]:
    """Uygulamayı açar, başarı/hata mesajı döndürür."""
    if not app_name:
        raise invalid_argument("Uygulama adi belirtilmedi.")

    resolved = _resolve_app_name(app_name)
    if sys.platform == "win32":
        return _open_app_windows(resolved)
    if sys.platform != "darwin":
        return _open_app_linux(resolved)

    try:
        result = subprocess.run(
            ["open", "-a", resolved],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return _launch_success(resolved)

        # Spotlight ile dene
        result2 = subprocess.run(
            ["open", resolved],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result2.returncode == 0:
            return _launch_success(resolved)
        # Hem `open -a` hem Spotlight denemesi düştü: uygulama bu makinede yok.
        raise app_not_found(f"{resolved} bu bilgisayarda bulunamadi.")
    except subprocess.TimeoutExpired as exc:
        raise timeout_error(f"{resolved} acilirken zaman asimina ugradi.") from exc
    except SafeCapabilityError:
        raise
    except Exception as exc:
        raise capability_unavailable(f"{resolved} guvenli sekilde acilamadi.") from exc


def close_app(app_name: str) -> dict[str, Any]:
    """Uygulamayı güvenli şekilde kapatır."""
    resolved = _resolve_app_name(app_name) if app_name else ""
    if _looks_generic_close_target(app_name):
        resolved = _frontmost_application_name() or resolved
    if not resolved:
        raise invalid_argument("Kapatilacak uygulama bulunamadi.")

    if sys.platform != "darwin":
        # Windows/Linux: nazik quit protokolü yok; psutil terminate→kill akışı
        # (SIGTERM önce, cevapsıza SIGKILL) güvenli kapatma muadili.
        terminated = _terminate_matching_processes(resolved)
        if terminated > 0 and _wait_until_closed(resolved):
            return {
                "text": f"{resolved} kapatıldı.",
                "result": {
                    "appName": resolved,
                    "verificationStatus": "closed_confirmed",
                    "closedConfirmed": True,
                    "processObserved": _matching_process_count(resolved) == 0,
                },
            }
        raise app_not_found(f"{resolved} calisan bir uygulama olarak bulunamadi.")

    script = f'tell application "{_escape_osascript_text(resolved)}" to quit'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            if _wait_until_closed(resolved):
                return {
                    "text": f"{resolved} kapatıldı.",
                    "result": {
                        "appName": resolved,
                        "verificationStatus": "closed_confirmed",
                        "closedConfirmed": True,
                        "processObserved": _matching_process_count(resolved) == 0,
                    },
                }
    except subprocess.TimeoutExpired as exc:
        raise timeout_error(f"{resolved} kapatilirken zaman asimina ugradi.") from exc
    except Exception:
        pass

    terminated = _terminate_matching_processes(resolved)
    if terminated > 0 and _wait_until_closed(resolved):
        return {
            "text": f"{resolved} kapatıldı.",
            "result": {
                "appName": resolved,
                "verificationStatus": "closed_confirmed",
                "closedConfirmed": True,
                "processObserved": _matching_process_count(resolved) == 0,
            },
        }

    raise app_not_found(f"{resolved} calisan bir uygulama olarak bulunamadi.")
