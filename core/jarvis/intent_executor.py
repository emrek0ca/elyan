"""
core/jarvis/intent_executor.py
───────────────────────────────────────────────────────────────────────────────
IntentExecutor — ClassifiedIntent → gerçek sistem aksiyonu

JarvisCore._dispatch() buraya çağrı yapar. Her sub_intent için doğru
computer/system modülünü çağırır ve Türkçe bir sonuç stringi döner.

Desteklenen aksiyonlar:
  system_control / app_control    → uygulama aç/kapat
  system_control / screen_capture → ekran görüntüsü al
  system_control / terminal       → shell komutu çalıştır (güvenli liste)
  system_control / network        → wifi/ip bilgisi
  system_control / system_settings→ parlaklık, ses, dark mode
  monitoring / system_health      → CPU, RAM, disk, batarya
  information / search            → Google/tarayıcı aç
  information / weather           → hava durumu (wttr.in)
  communication / message         → macOS bildirim gönder
  conversation / *                → LLM'e ilet (fallback)
"""
from __future__ import annotations

import asyncio
import re
import shlex
import subprocess
from typing import TYPE_CHECKING

from utils.logger import get_logger

if TYPE_CHECKING:
    from core.jarvis.jarvis_core import ClassifiedIntent

logger = get_logger("intent_executor")

# ── Bilinen uygulama adları (Türkçe → macOS bundle) ──────────────────────────

_APP_ALIASES: dict[str, str] = {
    # Türkçe / yaygın takma adlar
    "safari": "Safari",
    "chrome": "Google Chrome",
    "firefox": "Firefox",
    "terminal": "Terminal",
    "iterm": "iTerm",
    "iterm2": "iTerm2",
    "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "kod": "Visual Studio Code",
    "xcode": "Xcode",
    "finder": "Finder",
    "dosya yöneticisi": "Finder",
    "mail": "Mail",
    "e-posta": "Mail",
    "takvim": "Calendar",
    "calendar": "Calendar",
    "notlar": "Notes",
    "notes": "Notes",
    "müzik": "Music",
    "music": "Music",
    "spotify": "Spotify",
    "slack": "Slack",
    "zoom": "Zoom",
    "teams": "Microsoft Teams",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
    "discord": "Discord",
    "figma": "Figma",
    "postman": "Postman",
    "docker": "Docker",
    "sistem": "System Preferences",
    "ayarlar": "System Preferences",
    "settings": "System Preferences",
    "aktivite": "Activity Monitor",
    "activity monitor": "Activity Monitor",
    "görev yöneticisi": "Activity Monitor",
}

# Güvenli terminal komutları (whitelist)
_SAFE_TERMINAL_CMDS = frozenset({
    "ls", "pwd", "echo", "date", "uptime", "whoami",
    "df", "du", "free", "top", "ps", "which",
    "cat", "head", "tail", "grep", "find", "wc",
    "ping", "curl", "wget", "git", "python3",
    "pip", "npm", "node",
})


# ── Entity Extraction ─────────────────────────────────────────────────────────

_TR_SUFFIXES = re.compile(
    r"[''](?:yi|yı|yu|yü|i|ı|u|ü|ye|ya|yu|yü|de|da|den|dan|te|ta|ten|tan"
    r"|nin|nın|nun|nün|in|ın|un|ün|e|a|le|la|yle|yla|deki|daki|ki)$",
    re.IGNORECASE,
)


def _strip_tr_suffix(word: str) -> str:
    """'Safari'yi' → 'safari', 'Zoom'u' → 'zoom'"""
    return _TR_SUFFIXES.sub("", word).strip("'").lower()


def _extract_app_name(text: str) -> str:
    """Metin içinden uygulama adını çıkar (Türkçe ekleri soyarak)."""
    lower = text.lower()

    # Her kelimeyi suffix'ten arındırıp alias sözlüğüne bak
    for word in lower.split():
        stripped = _strip_tr_suffix(word)
        if stripped in _APP_ALIASES:
            return _APP_ALIASES[stripped]

    # Tam alias eşleşmesi dene (çok kelimeli takma adlar için)
    for alias, canonical in sorted(_APP_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in lower:
            return canonical

    # "X aç", "X'i aç", "X'ı kapat" pattern
    patterns = [
        r"(\w[\w\s]*?)\s+(?:aç|kapat|başlat|durdur|çalıştır|quit|open|close|launch)",
        r"(?:aç|open|launch)\s+(\w[\w\s]*?)(?:\s|$)",
    ]
    for pat in patterns:
        m = re.search(pat, lower)
        if m:
            candidate = _strip_tr_suffix(m.group(1).strip())
            if candidate in _APP_ALIASES:
                return _APP_ALIASES[candidate]
            if candidate and len(candidate) >= 2:
                return candidate.title()

    return ""


_TERMINAL_TRIGGER_WORDS = frozenset({"çalıştır", "çalıştırır", "run", "execute", "komutu", "komutunu"})


def _extract_terminal_cmd(text: str) -> str:
    """'X komutunu çalıştır', 'run X', 'terminal'de X çalıştır' pattern."""
    patterns = [
        r"(?:çalıştır|run|execute)\s+['\"]?(.+?)['\"]?$",
        r"terminal(?:de|da|'de|'da|'de|'da)?\s+(.+?)(?:\s*$)",
    ]
    for pat in patterns:
        m = re.search(pat, text.lower())
        if m:
            cmd = m.group(1).strip()
            # Strip trailing trigger words that leaked into the capture group
            words = cmd.split()
            while words and words[-1] in _TERMINAL_TRIGGER_WORDS:
                words.pop()
            return " ".join(words).strip()
    return ""


def _extract_search_query(text: str) -> str:
    """Arama sorgusunu çıkar."""
    for prefix in ["ara ", "search ", "google ", "bul ", "find "]:
        if prefix in text.lower():
            idx = text.lower().index(prefix) + len(prefix)
            return text[idx:].strip()
    return text.strip()


def _is_close_intent(text: str) -> bool:
    lower = text.lower()
    return any(w in lower for w in ["kapat", "durdur", "kapa", "quit", "close", "stop"])


# ── Executor ──────────────────────────────────────────────────────────────────

class IntentExecutor:
    """Classified intent'i gerçek sistem aksiyonuna dönüştürür."""

    async def execute(self, intent: "ClassifiedIntent") -> str:
        """Ana dispatch noktası. Her zaman Türkçe string döner."""
        cat = intent.category.value
        sub = intent.sub_intent
        text = intent.raw_text

        try:
            # ── System Control ────────────────────────────────────────────────
            if cat == "system_control":
                if sub == "app_control":
                    return await self._app_control(text)
                if sub == "screen_capture":
                    return await self._screenshot(text)
                if sub == "terminal":
                    return await self._terminal(text)
                if sub == "network":
                    return await self._network_info(text)
                if sub == "system_settings":
                    return await self._system_settings(text)
                if sub == "file_ops":
                    return await self._file_ops(text)

            # ── Monitoring ────────────────────────────────────────────────────
            if cat == "monitoring":
                if sub == "system_health":
                    return await self._system_health(text)
                if sub in ("watch", "alert"):
                    return await self._setup_monitor(text)

            # ── Information ───────────────────────────────────────────────────
            if cat == "information":
                if sub == "search":
                    return await self._web_search(text)
                if sub == "weather":
                    return await self._weather(text)

            # ── Communication ─────────────────────────────────────────────────
            if cat == "communication":
                if sub == "message":
                    return await self._notify(text)

            # ── Conversation / Fallback ───────────────────────────────────────
            return ""  # caller will handle via LLM

        except Exception as exc:
            logger.error(f"IntentExecutor error [{cat}/{sub}]: {exc}")
            return f"İşlem sırasında hata oluştu: {exc}"

    # ── Handlers ─────────────────────────────────────────────────────────────

    async def _app_control(self, text: str) -> str:
        from core.computer.macos_controller import get_macos_controller
        mc = get_macos_controller()
        app = _extract_app_name(text)

        if not app:
            # Listeyi göster
            open_apps = await mc.list_open_apps()
            if open_apps:
                return "Açık uygulamalar:\n" + "\n".join(f"• {a}" for a in open_apps[:15])
            return "Hangi uygulamayı açmamı istiyorsun?"

        if _is_close_intent(text):
            ok = await mc.quit_app(app)
            return f"✅ {app} kapatıldı." if ok else f"❌ {app} kapatılamadı (zaten kapalı olabilir)."
        else:
            ok = await mc.open_app(app)
            return f"✅ {app} açıldı." if ok else f"❌ {app} açılamadı. Kurulu olduğundan emin ol."

    async def _screenshot(self, text: str) -> str:
        from core.computer.macos_controller import get_macos_controller
        mc = get_macos_controller()
        img = await mc.take_screenshot()
        if img and len(img) > 100:
            # Dosyaya kaydet
            import time, pathlib
            path = pathlib.Path.home() / "Desktop" / f"elyan_screenshot_{int(time.time())}.png"
            path.write_bytes(img)
            return f"✅ Ekran görüntüsü alındı: {path}"
        return "❌ Ekran görüntüsü alınamadı."

    async def _terminal(self, text: str) -> str:
        cmd = _extract_terminal_cmd(text)
        if not cmd:
            return "Hangi komutu çalıştırmamı istiyorsun? Örnek: 'ls -la çalıştır'"

        # Güvenlik: sadece whitelist komutlar
        try:
            parts = shlex.split(cmd)
        except ValueError:
            return f"❌ Geçersiz komut formatı."

        base = parts[0] if parts else ""
        if base not in _SAFE_TERMINAL_CMDS:
            return (f"❌ '{base}' komutu güvenlik listesinde değil.\n"
                    f"İzin verilen komutlar: {', '.join(sorted(_SAFE_TERMINAL_CMDS))}")

        try:
            result = subprocess.run(
                parts, capture_output=True, text=True, timeout=10
            )
            out = (result.stdout or result.stderr or "").strip()
            return f"```\n{out[:1500]}\n```" if out else "✅ Komut çalıştı (çıktı yok)."
        except subprocess.TimeoutExpired:
            return "❌ Komut zaman aşımına uğradı."
        except Exception as exc:
            return f"❌ Hata: {exc}"

    async def _network_info(self, text: str) -> str:
        lower = text.lower()
        try:
            if "ip" in lower:
                r = subprocess.run(["ipconfig", "getifaddr", "en0"],
                                   capture_output=True, text=True, timeout=5)
                ip = r.stdout.strip() or "alınamadı"
                return f"📡 IP adresin: `{ip}`"
            if "wifi" in lower or "ağ" in lower:
                # networksetup daha güvenilir (tüm macOS sürümleri)
                r = subprocess.run(
                    ["networksetup", "-getairportnetwork", "en0"],
                    capture_output=True, text=True, timeout=5
                )
                out = r.stdout.strip()
                if "Current Wi-Fi Network:" in out:
                    ssid = out.split("Current Wi-Fi Network:", 1)[1].strip()
                    return f"📶 Bağlı Wi-Fi: **{ssid}**"
                # Fallback: airport
                r2 = subprocess.run(
                    ["/System/Library/PrivateFrameworks/Apple80211.framework/"
                     "Versions/Current/Resources/airport", "-I"],
                    capture_output=True, text=True, timeout=5
                )
                for line in r2.stdout.splitlines():
                    if " SSID:" in line:
                        ssid = line.split(":", 1)[1].strip()
                        return f"📶 Bağlı Wi-Fi: **{ssid}**"
                return f"📶 {out or 'Wi-Fi bilgisi alınamadı.'}"
            if "bluetooth" in lower:
                r = subprocess.run(
                    ["system_profiler", "SPBluetoothDataType"],
                    capture_output=True, text=True, timeout=8
                )
                lines = [l.strip() for l in r.stdout.splitlines() if "Connected:" in l or "Name:" in l]
                return "🔵 Bluetooth:\n" + "\n".join(lines[:10]) if lines else "Bluetooth bilgisi alınamadı."
        except Exception as exc:
            logger.warning(f"network_info error: {exc}")
        return "Ağ bilgisi alınamadı."

    async def _system_settings(self, text: str) -> str:
        lower = text.lower()
        from core.computer.macos_controller import get_macos_controller
        mc = get_macos_controller()

        # ── Ekran kilitle ───────────────────────────────────────────────────
        if any(w in lower for w in ["kilitle", "lock", "ekranı kapat", "ekranı kilitle"]):
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to keystroke "q" using {command down, control down}'],
                capture_output=True,
            )
            return "🔒 Ekran kilitlendi."

        # ── Uyku modu ───────────────────────────────────────────────────────
        if any(w in lower for w in ["uyku", "sleep", "bekle", "standby"]):
            subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to sleep'],
                capture_output=True,
            )
            return "💤 Mac uyku moduna alınıyor."

        # ── Yeniden başlat ──────────────────────────────────────────────────
        if any(w in lower for w in ["yeniden başlat", "restart", "reboot"]):
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to restart'],
                capture_output=True,
            )
            return "🔄 Mac yeniden başlatılıyor."

        # ── Kapat ──────────────────────────────────────────────────────────
        if any(w in lower for w in ["kapat bilgisayarı", "shutdown", "power off", "kapat mac"]):
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to shut down'],
                capture_output=True,
            )
            return "⏹️ Mac kapatılıyor."

        # ── Dark mode ───────────────────────────────────────────────────────
        if "dark mode" in lower or "karanlık" in lower:
            script = 'tell application "System Events" to tell appearance preferences to set dark mode to not dark mode'
            ok = await mc._run_applescript(script)
            return "✅ Dark mode değiştirildi." if ok else "❌ Dark mode değiştirilemedi."

        # ── Ses seviyesi ────────────────────────────────────────────────────
        if any(w in lower for w in ["ses", "volume", "sesi"]):
            m = re.search(r"(\d+)", text)
            vol = int(m.group(1)) if m else 50
            vol = max(0, min(100, vol))
            subprocess.run(["osascript", "-e", f"set volume output volume {vol}"],
                           capture_output=True)
            return f"🔊 Ses seviyesi {vol}% olarak ayarlandı."

        # ── Parlaklık ───────────────────────────────────────────────────────
        if any(w in lower for w in ["parlaklık", "brightness"]):
            m = re.search(r"(\d+)", text)
            pct = int(m.group(1)) if m else 50
            val = max(0.0, min(1.0, pct / 100))
            subprocess.run(
                ["osascript", "-e",
                 f'tell application "System Events" to set brightness of screen 1 to {val:.2f}'],
                capture_output=True,
            )
            return f"☀️ Parlaklık {pct}% olarak ayarlandı."

        return "Hangi ayarı değiştirmemi istiyorsun? (dark mode, ses, parlaklık, kilitle, uyku...)"

    async def _file_ops(self, text: str) -> str:
        lower = text.lower()
        import subprocess, pathlib, os

        # Klasör aç
        _FOLDER_MAP = {
            "indirmeler": "~/Downloads",
            "downloads": "~/Downloads",
            "masaüstü": "~/Desktop",
            "desktop": "~/Desktop",
            "belgeler": "~/Documents",
            "documents": "~/Documents",
            "resimler": "~/Pictures",
            "pictures": "~/Pictures",
            "müzik": "~/Music",
            "music": "~/Music",
            "videolar": "~/Movies",
            "movies": "~/Movies",
        }
        for key, folder in _FOLDER_MAP.items():
            if key in lower:
                expanded = os.path.expanduser(folder)
                subprocess.run(["open", expanded], capture_output=True)
                return f"📂 {folder} klasörü açıldı."

        # "X dosyasını aç" pattern
        m = re.search(r"['\"](.+?)['\"]", text)
        if m:
            path = os.path.expanduser(m.group(1))
            if os.path.exists(path):
                subprocess.run(["open", path], capture_output=True)
                return f"📄 {path} açıldı."
            return f"❌ Dosya bulunamadı: {path}"

        return "Hangi klasörü veya dosyayı açmamı istiyorsun?"

    async def _system_health(self, text: str) -> str:
        from core.computer.app_controller import AppController
        ac = AppController()
        lower = text.lower()
        parts: list[str] = []

        if any(w in lower for w in ["cpu", "işlemci", "processor"]):
            cpu = await ac.get_cpu_usage()
            parts.append(f"🖥️ CPU: **%{cpu:.1f}**")

        if any(w in lower for w in ["battery", "batarya", "pil", "şarj"]):
            batt = await ac.get_battery_info()
            charging = "🔌 şarj oluyor" if batt.get("charging") else "🔋"
            parts.append(f"{charging} Batarya: **%{batt.get('percent', '?')}**")

        if any(w in lower for w in ["disk", "depolama", "storage", "ssd"]):
            disk = await ac.get_disk_usage()
            parts.append(f"💾 Disk: **{disk.get('free_gb', '?'):.1f} GB** boş / {disk.get('total_gb', '?'):.1f} GB toplam")

        if any(w in lower for w in ["ram", "bellek", "memory"]):
            try:
                r = subprocess.run(
                    ["vm_stat"], capture_output=True, text=True, timeout=3
                )
                pages_free = 0
                for line in r.stdout.splitlines():
                    if "Pages free" in line:
                        pages_free = int(re.search(r"(\d+)", line).group(1))
                free_mb = pages_free * 4096 // (1024 * 1024)
                parts.append(f"🧠 RAM boş: **{free_mb} MB**")
            except Exception:
                pass

        if not parts:
            # Genel durum raporu
            cpu = await ac.get_cpu_usage()
            batt = await ac.get_battery_info()
            disk = await ac.get_disk_usage()
            charging = "🔌" if batt.get("charging") else "🔋"
            return (
                f"📊 **Sistem Durumu**\n"
                f"🖥️ CPU: %{cpu:.1f}\n"
                f"{charging} Batarya: %{batt.get('percent', '?')}\n"
                f"💾 Disk: {disk.get('free_gb', '?'):.1f} GB boş"
            )

        return "\n".join(parts)

    async def _web_search(self, text: str) -> str:
        from core.computer.app_controller import AppController
        query = _extract_search_query(text)
        if not query:
            return "Ne aramak istiyorsun?"
        import urllib.parse
        url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
        ac = AppController()
        ok = await ac.open_url(url)
        return f"🔍 Google'da aranıyor: **{query}**" if ok else f"❌ Tarayıcı açılamadı."

    async def _weather(self, text: str) -> str:
        """wttr.in üzerinden hava durumu (curl, offline-safe)."""
        # Şehir çıkar
        lower = text.lower()
        city = "Istanbul"
        for pattern in [r"(?:de|da|'de|'da|')\s*hava", r"hava\s+(\w+)", r"(\w+)\s+hava"]:
            m = re.search(pattern, lower)
            if m and m.lastindex:
                candidate = m.group(1).strip()
                if len(candidate) >= 3 and candidate not in ("durumu", "bugün", "yarın"):
                    city = candidate
                    break

        try:
            r = subprocess.run(
                ["curl", "-s", f"https://wttr.in/{city}?format=3"],
                capture_output=True, text=True, timeout=6
            )
            out = r.stdout.strip()
            if out:
                return f"🌤️ {out}"
        except Exception:
            pass

        from core.computer.app_controller import AppController
        import urllib.parse
        url = f"https://wttr.in/{urllib.parse.quote(city)}"
        await AppController().open_url(url)
        return f"🌍 {city} için hava durumu tarayıcıda açıldı."

    async def _setup_monitor(self, text: str) -> str:
        from core.proactive.system_monitor import get_system_monitor
        monitor = get_system_monitor()
        running = getattr(monitor, "running", False)
        if not running:
            await monitor.start()
            return "✅ Sistem izleme başlatıldı. CPU, disk ve batarya uyarıları aktif."
        return "✅ Sistem izleme zaten aktif."

    async def _notify(self, text: str) -> str:
        from core.computer.app_controller import AppController
        ac = AppController()
        # Mesaj içeriğini çıkar
        for prefix in ["bildir ", "notify ", "mesaj ", "notification "]:
            if prefix in text.lower():
                idx = text.lower().index(prefix) + len(prefix)
                msg = text[idx:].strip()
                ok = await ac.show_notification("Elyan", msg)
                return f"✅ Bildirim gönderildi: {msg}" if ok else "❌ Bildirim gönderilemedi."
        ok = await ac.show_notification("Elyan", text)
        return "✅ Bildirim gönderildi." if ok else "❌ Bildirim gönderilemedi."


# ── Singleton ─────────────────────────────────────────────────────────────────

_executor: IntentExecutor | None = None


def get_intent_executor() -> IntentExecutor:
    global _executor
    if _executor is None:
        _executor = IntentExecutor()
    return _executor
