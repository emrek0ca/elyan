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
