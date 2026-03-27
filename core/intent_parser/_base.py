"""
_base.py — IntentParser temel sınıfı, alias tabloları ve yardımcı metodlar
BUG-FUNC-004: intent_parser.py modüllere bölündü
"""
import re
from pathlib import Path
from typing import Any
from config.settings import HOME_DIR
from core.nlu_normalizer import normalize_turkish_ascii
from utils.logger import get_logger

logger = get_logger("intent_parser")

# ── Module-level compiled regex (BUG-PERF-002) ──────────────────────────────
_RE_BROWSER_SEARCH_VERB = re.compile(r"\b(arat|ara|search)\b", re.IGNORECASE)
_RE_SEARCH_BEFORE      = re.compile(r'(.+?)\s+(?:arat|ara|search)\b', re.IGNORECASE)
_RE_SEARCH_AFTER       = re.compile(r'(?:arat|ara|search)\s+(.+)', re.IGNORECASE)
_RE_YOUTUBE_QUERY      = re.compile(r"youtube.*?(?:aç|ac|çal|cal|play)\s+(.+)", re.IGNORECASE)
_RE_YOUTUBE_FALLBACK   = re.compile(r"(?:youtube|yt)\s+(.+)", re.IGNORECASE)
_RE_YOUTUBE_CLEANUP1   = re.compile(r"^(ve|ile)\s+", re.IGNORECASE)
_RE_YOUTUBE_CLEANUP2   = re.compile(r"\b(aç|ac|çal|cal|play)\b$", re.IGNORECASE)
_RE_SCREENSHOT_NAME    = re.compile(r'adı\s*[:\s]*(\w+)|ismi\s*[:\s]*(\w+)|olarak\s+(\w+)')
_RE_FOLDER_NAME_PATTERNS = [
    re.compile(r"([\w\-]+)\s+(?:adında|adli|isimli|named)\s+klas[öo]r", re.IGNORECASE),
    re.compile(r"(?:adında|adli|isimli|named)\s+([\w\-]+)\s+klas[öo]r", re.IGNORECASE),
    re.compile(r"klas[öo]r\s+(?:adında|adli|isimli|named)\s+([\w\-]+)", re.IGNORECASE),
    re.compile(r"([\w\-]+)\s+klas[öo]r", re.IGNORECASE),
    re.compile(r"klas[öo]r\s+([\w\-]+)", re.IGNORECASE),
]
_RE_WEBSITE_DIRECT_TOPIC = re.compile(
    r'(?:bana\s+)?(.+?)\s+(?:website|web sitesi|site)\s+(?:yap|oluştur|olustur|hazırla|hazirla)',
    re.IGNORECASE)
_RE_WEBSITE_TOPIC  = re.compile(
    r'(?:hakkında|hakkinda|konulu|tema|temalı|temali)\s+(.+?)(?:\s+(?:website|site|web sitesi)|$)',
    re.IGNORECASE)
_RE_WEBSITE_ALT    = re.compile(r'(?:website|site|web sitesi)\s+(.+)', re.IGNORECASE)
_RE_WEBSITE_CLEAN  = re.compile(
    r'\b(yap|oluştur|olustur|hazırla|hazirla|bana|bir|web sitesi|website|site)\b', re.IGNORECASE)
_RE_WEBSITE_FILENAME = re.compile(r'([\w\-]+\.html)', re.IGNORECASE)
_RE_WEBSITE_FOLDER   = re.compile(
    r"(?:klasor|klasör|folder)\s+(?:adiyla|adli|adında|adinda|named)?\s*([a-zA-Z0-9\-_]+)",
    re.IGNORECASE)
_RE_WEBSITE_SLUGIFY  = re.compile(r"[^a-z0-9]+")
_RE_RESEARCH_TOPICS  = [
    re.compile(r'(.+?)\s+hakkında\s+(?:\w+\s+)*(?:araştırma|araştır|inceleme)', re.IGNORECASE),
    re.compile(r'(.+?)\s+inceleme\s+(?:yapılsın|yap\b)?', re.IGNORECASE),
    re.compile(r'(.+?)\s+(?:araştırma|research)(?:\s+yap\w*)?$', re.IGNORECASE),
    re.compile(r'(?:araştırma|inceleme|araştır)\s+yap\w*\s+(.+)', re.IGNORECASE),
]
_RE_RESEARCH_CLEAN1 = re.compile(r'\b(araştırma|arastirma|araştır|arastir|research|inceleme)\b', re.IGNORECASE)
_RE_RESEARCH_CLEAN2 = re.compile(r'\s+hakkında\s+')
_RE_RESEARCH_CLEAN3 = re.compile(r'\b(detaylı|kısa|kapsamlı|hızlı|derin)\b', re.IGNORECASE)
_RE_RESEARCH_CLEAN4 = re.compile(r'\byap\w*\b', re.IGNORECASE)


class BaseParser:
    """Alias tabloları ve yardımcı metodlar"""

    def __init__(self):
        self.path_aliases = {
            "masaüstü": "Desktop", "masaustu": "Desktop", "desktop": "Desktop",
            "masa üstü": "Desktop", "masaustunde": "Desktop", "masaüstünde": "Desktop",
            "belgeler": "Documents", "dökümanlar": "Documents", "dokumanlar": "Documents",
            "documents": "Documents", "dokümanlarda": "Documents", "belgelere": "Documents",
            "indirilenler": "Downloads", "downloads": "Downloads", "indirilen": "Downloads",
            "indirilenlerde": "Downloads", "download": "Downloads",
            "resimler": "Pictures", "pictures": "Pictures", "fotoğraflar": "Pictures",
            "müzik": "Music", "muzik": "Music", "music": "Music",
            "filmler": "Movies", "movies": "Movies", "videolar": "Movies",
            "projeler": "Projects", "projects": "Projects", "projelerde": "Projects",
            "kod": "Code", "code": "Code", "kodlar": "Code",
            "ana klasör": "", "home": "", "ev dizini": "", "kullanıcı": "",
        }

        self.app_aliases = {
            "safari": "Safari", "chrome": "Google Chrome", "google chrome": "Google Chrome",
            "krom": "Google Chrome", "tarayıcı": "Safari",
            "firefox": "Firefox", "finder": "Finder", "dosyalar": "Finder",
            "terminal": "Terminal", "konsol": "Terminal", "iterm": "iTerm",
            "notlar": "Notes", "notes": "Notes", "not defteri": "Notes", "not": "Notes",
            "hesap makinesi": "Calculator", "hesapmakinesi": "Calculator", "calculator": "Calculator",
            "apple music": "Music", "spotify": "Spotify", "müzik": "Music",
            "vscode": "Visual Studio Code", "vs code": "Visual Studio Code",
            "visual studio code": "Visual Studio Code", "code": "Visual Studio Code",
            "cursor": "Cursor", "windsurf": "Windsurf", "codeium windsurf": "Windsurf",
            "antigravity": "Antigravity", "anti gravity": "Antigravity", "gravity": "Antigravity",
            "discord": "Discord", "slack": "Slack", "whatsapp": "WhatsApp",
            "telegram": "Telegram", "zoom": "zoom.us", "teams": "Microsoft Teams",
            "word": "Microsoft Word", "excel": "Microsoft Excel", "powerpoint": "Microsoft PowerPoint",
            "takvim": "Calendar", "calendar": "Calendar",
            "mail": "Mail", "eposta": "Mail", "e-posta": "Mail", "posta": "Mail",
            "mesajlar": "Messages", "messages": "Messages", "mesaj": "Messages",
            "photos": "Photos", "fotoğraflar": "Photos", "foto": "Photos",
            "kamera": "Photo Booth", "camera": "Photo Booth", "webcam": "Photo Booth",
            "ayarlar": "System Settings", "sistem tercihleri": "System Settings",
            "preview": "Preview", "önizleme": "Preview", "textedit": "TextEdit",
            "activity monitor": "Activity Monitor", "görev yöneticisi": "Activity Monitor",
        }

        self.url_aliases = {
            "google": "https://google.com", "youtube": "https://youtube.com",
            "twitter": "https://twitter.com", "x": "https://x.com",
            "facebook": "https://facebook.com", "instagram": "https://instagram.com",
            "linkedin": "https://linkedin.com", "github": "https://github.com",
            "reddit": "https://reddit.com", "amazon": "https://amazon.com",
            "netflix": "https://netflix.com", "chatgpt": "https://chat.openai.com",
            "claude": "https://claude.ai", "gmail": "https://mail.google.com",
            "drive": "https://drive.google.com", "maps": "https://maps.google.com",
            "harita": "https://maps.google.com", "haber": "https://news.google.com",
            "translate": "https://translate.google.com", "çeviri": "https://translate.google.com",
        }

        self.greetings = {
            "merhaba", "selam", "selamlar", "hey", "hi", "hello", "mrb", "slm",
            "günaydın", "iyi akşamlar", "iyi günler", "naber", "nasılsın",
            "selamün aleyküm", "as", "sa", "aleyküm selam"
        }

    def _normalize(self, text: str) -> str:
        """Türkçe typo/argo + ascii normalize katmanı"""
        return normalize_turkish_ascii(text)

    def _resolve_alias_folder_path(self, folder: str) -> str:
        """
        Resolve alias folder paths with a Desktop fallback.

        Some users keep folders like "Projects" under Desktop instead of HOME.
        """
        folder = str(folder or "").strip()
        if not folder:
            return str(HOME_DIR)

        primary = HOME_DIR / folder
        if primary.exists():
            return str(primary)

        desktop_alt = HOME_DIR / "Desktop" / folder
        if desktop_alt.exists():
            return str(desktop_alt)

        return str(primary)

    def _extract_path(self, text: str) -> str | None:
        text_norm = self._normalize(text)
        for alias, folder in self.path_aliases.items():
            alias_norm = self._normalize(alias)
            if alias_norm in text_norm or alias in text:
                return self._resolve_alias_folder_path(folder)
        path_match = re.search(r'[~/][a-zA-Z0-9_/\-\.]+', text)
        if path_match:
            path = path_match.group()
            if path.startswith("~"):
                path = str(HOME_DIR) + path[1:]
            return path
        return None

    def _extract_execution_preferences(self, text: str) -> dict[str, Any]:
        low = self._normalize(str(text or "").lower())
        if not low:
            return {}

        prefs: dict[str, Any] = {}
        if any(
            phrase in low
            for phrase in (
                "once planla",
                "once planini cikar",
                "planini cikar",
                "plan cikar",
                "ilk once planla",
                "before acting plan",
                "plan first",
            )
        ):
            prefs["requires_plan"] = True
        if any(
            phrase in low
            for phrase in (
                "once taslak",
                "taslak hazirla",
                "taslak cikar",
                "draft first",
                "prepare draft",
            )
        ):
            prefs["draft_first"] = True
            prefs["requires_plan"] = True
        if any(
            phrase in low
            for phrase in (
                "sorarak ilerle",
                "bana sor",
                "tek tek onay",
                "onay almadan yapma",
                "ask before acting",
                "confirm each step",
            )
        ):
            prefs["approval_mode"] = "per_step"
            prefs["autonomy_mode"] = "confirmed"
        if any(
            phrase in low
            for phrase in (
                "sadece incele",
                "sadece analiz et",
                "sadece gozlemle",
                "observe only",
                "read only",
                "salt okunur",
                "degisiklik yapma",
                "dokunma",
            )
        ):
            prefs["observe_only"] = True
            prefs["dry_run"] = True
            prefs["autonomy_mode"] = "observe_only"
        if any(
            phrase in low
            for phrase in (
                "dry run",
                "simule et",
                "simulate et",
                "simulasyon",
                "taslak olarak goster",
            )
        ):
            prefs["dry_run"] = True
        if any(phrase in low for phrase in ("dogrula", "teyit et", "strict verify", "verify")):
            prefs["verification_mode"] = "strict"
        if prefs.get("draft_first") and "autonomy_mode" not in prefs and not prefs.get("observe_only"):
            prefs["autonomy_mode"] = "draft_first"
        return prefs

    def _apply_execution_preferences(self, result: dict[str, Any] | None, original: str) -> dict[str, Any] | None:
        if not isinstance(result, dict):
            return result
        prefs = self._extract_execution_preferences(original)
        if not prefs:
            return result

        params = result.get("params")
        if not isinstance(params, dict):
            params = {}
            result["params"] = params

        merged = dict(params.get("execution_preferences") or {})
        merged.update(prefs)
        params["execution_preferences"] = merged
        if merged.get("dry_run"):
            params.setdefault("dry_run", True)
        if merged.get("observe_only"):
            params.setdefault("read_only", True)

        for key in ("autonomy_mode", "approval_mode", "verification_mode"):
            value = merged.get(key)
            if value and not result.get(key):
                result[key] = value
        for key in ("requires_plan", "draft_first", "observe_only"):
            if merged.get(key):
                result[key] = True

        if str(result.get("action") or "").strip() == "multi_task":
            for task in list(result.get("tasks") or []):
                if not isinstance(task, dict):
                    continue
                task_params = task.get("params")
                if not isinstance(task_params, dict):
                    task_params = {}
                    task["params"] = task_params
                task_params.setdefault("execution_preferences", dict(merged))
                if merged.get("dry_run"):
                    task_params.setdefault("dry_run", True)
                if merged.get("observe_only"):
                    task["read_only"] = True
                if merged.get("approval_mode") == "per_step":
                    task["approval_required"] = True
        return result
