"""
Fuzzy Intent Matcher v19.0
Konusma dilini anlayan, 77 tool'a fuzzy matching yapan modul.

Akis:
  User Input -> normalize_turkish() -> fuzzy_match() -> (tool, params, confidence)

Ornek:
  "bi ss atsana"         -> take_screenshot, {}, 0.90
  "abi sesi bi kis ya"   -> set_volume, {level: 30}, 0.88
  "chrome'u kapat"       -> close_app, {app_name: Google Chrome}, 0.92
"""

import re
import time
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from pathlib import Path
from config.settings import HOME_DIR
from core.nlu_normalizer import normalize_turkish_text
from utils.logger import get_logger

logger = get_logger("fuzzy_intent")


@dataclass
class FuzzyResult:
    tool: str
    params: Dict[str, Any]
    confidence: float
    matched_trigger: str
    normalized_input: str


# ============================================================
# 1. TURKCE NORMALIZER
# ============================================================

# Dolgu / bağlaç kelimeleri (konuşma dilinde sık kullanılır)
_FILLER_WORDS = {
    "bi", "bir", "ya", "abi", "be", "lan", "la", "abi", "abicim",
    "bakayım", "bakalım", "bakam", "baksana", "baksanıza",
    "atsana", "yapsana", "etsene", "görsene", "versene", "söylesene",
    "açsana", "kapatsana", "göndersene",
    "şu", "şunu", "şunları", "bu", "bunu", "bunları", "o", "onu", "onları",
    "bana", "benim", "bize", "bizim", "sana", "size",
    "lütfen", "rica", "ederim",
    "acaba", "artık", "hemen", "hadi", "haydi",
    "bence", "galiba", "sanırım", "heralde", "herhalde",
    "biraz", "birazdan", "şimdi", "şimdilik",
    "ama", "fakat", "lakin", "ancak", "yani", "mesela",
    "aslında", "zaten", "bile",
    "de", "da", "mi", "mı", "mu", "mü",
}

# -sAnA / -sEnE eki ile biten fiilleri normalleştir
_VERB_SUFFIXES = {
    "atsana": "al", "atsanıza": "al",
    "yapsana": "yap", "yapsanıza": "yap",
    "görsene": "gör", "görsanıza": "gör",
    "etsene": "et", "etsanıza": "et",
    "versene": "ver", "versanıza": "ver",
    "açsana": "aç", "açsanıza": "aç",
    "kapatsana": "kapat", "kapatsanıza": "kapat",
    "göndersene": "gönder",
    "söylesene": "söyle",
    "göstersene": "göster",
    "baksana": "bak", "baksanıza": "bak",
    "yollasana": "gönder",
}

# Kısaltma / argo -> standart
_INFORMAL_MAP = {
    "tmm": "tamam", "tamamdır": "tamam",
    "tşk": "teşekkür", "eyw": "teşekkür",
    "naber": "nasılsın", "nbr": "nasılsın",
    "slm": "selam", "mrb": "merhaba",
    "idk": "bilmiyorum",
    "btw": "bu arada",
    "pls": "lütfen", "plz": "lütfen",
    "thx": "teşekkür",
    "brb": "birazdan dönerim",
}


def _normalize_tr(text: str) -> str:
    """ASCII normalize: çğıöşü -> cgiosu"""
    tr_map = str.maketrans('çğıöşüÇĞİÖŞÜ', 'cgiosuCGIOSU')
    return text.translate(tr_map)


# ASCII-normalized verb suffixes (pre-computed)
_VERB_SUFFIXES_ASCII = {_normalize_tr(k): v for k, v in _VERB_SUFFIXES.items()}
# ASCII-normalized filler words
_FILLER_WORDS_ASCII = {_normalize_tr(w) for w in _FILLER_WORDS}

# BUG-PERF-002/003: Pre-compile module-level regexes (never recompile per call)
_RE_APOSTROPHE = re.compile(r"[''`]([a-zçğıöşü]{1,4})\b")
_RE_TR_SUFFIX = re.compile(
    r'\b(\w{2,})\s+([aeuüiı]|[yns][uüiıeaıo]|[td][aeiıoöuü]n?|l[aeiıoöuü]r[iıuü]?)\b'
)
_RE_WHITESPACE = re.compile(r"\s+")
_TR_SUFFIX_STOP = frozenset({'ne', 'bu', 'şu', 'su', 'de', 'da'})


def normalize_turkish(text: str) -> str:
    """Gunluk Turkce konusma dilini standart forma cevirir."""
    original = text
    text = normalize_turkish_text(text)
    if not text:
        return ""

    # 1. Turkce tirnak/apostrof ekleri cikar: chrome'u, safari'yi, dosyanın
    text = _RE_APOSTROPHE.sub("", text)

    # 1b. Boslukluyapisan Turkce ekleri cikar: "chrome u", "safari yi"
    text = _RE_TR_SUFFIX.sub(
        lambda m: m.group(1) if m.group(1) not in _TR_SUFFIX_STOP else m.group(0),
        text,
    )

    # 2. Informal kısaltmaları değiştir
    words = text.split()
    words = [_INFORMAL_MAP.get(w, w) for w in words]

    # 3. Fiil son ekleri normalize et (-sana, -sene) - hem Turkce hem ASCII
    normalized_words = []
    for w in words:
        if w in _VERB_SUFFIXES:
            normalized_words.append(_VERB_SUFFIXES[w])
        elif _normalize_tr(w) in _VERB_SUFFIXES_ASCII:
            normalized_words.append(_VERB_SUFFIXES_ASCII[_normalize_tr(w)])
        else:
            normalized_words.append(w)
    words = normalized_words

    # 4. Dolgu kelimelerini kaldır - hem Turkce hem ASCII
    words = [w for w in words if w not in _FILLER_WORDS and _normalize_tr(w) not in _FILLER_WORDS_ASCII]

    text = " ".join(words)

    # 5. Çoklu boşluk temizle
    text = _RE_WHITESPACE.sub(" ", text).strip()

    if text != original.lower().strip():
        logger.debug(f"Normalized: '{original}' -> '{text}'")

    return text


# ============================================================
# 2. TOOL PATTERN VERITABANI
# ============================================================

# Aliases (intent_parser.py'den aynen alınıyor)
_PATH_ALIASES = {
    "masaüstü": "Desktop", "masaustu": "Desktop", "desktop": "Desktop",
    "masa üstü": "Desktop", "masaustunde": "Desktop", "masaüstünde": "Desktop",
    "belgeler": "Documents", "dökümanlar": "Documents", "dokumanlar": "Documents",
    "documents": "Documents", "dokümanlarda": "Documents",
    "indirilenler": "Downloads", "downloads": "Downloads", "indirilen": "Downloads",
    "indirilenlerde": "Downloads",
    "resimler": "Pictures", "pictures": "Pictures", "fotoğraflar": "Pictures",
    "müzik": "Music", "muzik": "Music", "music": "Music",
    "filmler": "Movies", "movies": "Movies", "videolar": "Movies",
    "projeler": "Projects", "projects": "Projects", "projelerde": "Projects",
    "kod": "Code", "code": "Code",
    "ana klasör": "", "home": "", "ev dizini": "",
}

_APP_ALIASES = {
    "safari": "Safari", "chrome": "Google Chrome", "google chrome": "Google Chrome",
    "firefox": "Firefox", "finder": "Finder", "dosyalar": "Finder",
    "terminal": "Terminal", "konsol": "Terminal",
    "notlar": "Notes", "notes": "Notes", "not defteri": "Notes",
    "hesap makinesi": "Calculator", "hesapmakinesi": "Calculator", "calculator": "Calculator",
    "apple music": "Music", "spotify": "Spotify", "müzik çalar": "Music",
    "vscode": "Visual Studio Code", "vs code": "Visual Studio Code",
    "visual studio code": "Visual Studio Code",
    "discord": "Discord", "slack": "Slack", "whatsapp": "WhatsApp",
    "telegram": "Telegram", "zoom": "zoom.us", "teams": "Microsoft Teams",
    "word": "Microsoft Word", "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "takvim": "Calendar", "calendar": "Calendar",
    "mail": "Mail", "eposta": "Mail", "e-posta": "Mail",
    "mesajlar": "Messages", "messages": "Messages",
    "photos": "Photos", "fotoğraflar": "Photos",
    "ayarlar": "System Preferences", "sistem tercihleri": "System Preferences",
    "preview": "Preview", "textedit": "TextEdit",
    "activity monitor": "Activity Monitor", "görev yöneticisi": "Activity Monitor",
    "müzik": "Music", "music": "Music",
}

_URL_ALIASES = {
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


# ============================================================
# Tool pattern tanımları
# Her trigger listesi en spesifikten en genele sıralanmalı
# ============================================================

TOOL_PATTERNS: Dict[str, Dict[str, Any]] = {
    # ===== EKRAN GORUNTUSU =====
    "take_screenshot": {
        "triggers": [
            "ekran görüntüsü al", "ekran görüntüsü", "screenshot al", "screenshot",
            "ekranı yakala", "ekranı kaydet", "ss al", "ss", "bi ss atsana",
            "ekranın resmini çek", "ekran yakala", "görüntü al", "ekran al",
        ],
        "extract": None,
    },

    # ===== SES KONTROLU =====
    "set_volume": {
        "triggers": [
            "sessize al", "sessiz yap", "sesi kapat", "ses kapat", "mute",
            "sesi aç", "ses aç", "unmute",
            "sesi kıs", "ses kıs", "sesi azalt", "sesi düşür",
            "sesi yükselt", "sesi artır", "sesi arttır", "ses yükselt", "ses artir",
            "ses seviyesi", "volume", "sesi bi kıs", "sesi biraz aç",
        ],
        "extract": "_extract_volume",
    },

    # ===== PARLAKLIK =====
    "set_brightness": {
        "triggers": [
            "parlaklığı artır", "parlaklık artır", "parlaklığı yükselt",
            "parlaklığı azalt", "parlaklık azalt", "parlaklığı düşür", "parlaklığı kıs",
            "parlaklığı aç", "parlaklık aç",
            "parlaklığı kapat", "parlaklık kapat",
            "ekran parlaklığı", "brightness", "ekranı karart", "ışığı aç",
        ],
        "extract": "_extract_brightness",
    },
    "get_brightness": {
        "triggers": ["parlaklık kaç", "parlaklık seviyesi", "parlaklık ne"],
        "extract": None,
    },

    # ===== UYGULAMA KONTROLU =====
    "close_app": {
        "triggers": [
            "uygulamayı kapat", "programı kapat",
            "kapat", "kapa", "close", "quit", "sonlandır",
        ],
        "extract": "_extract_app_name",
    },
    "open_app": {
        "triggers": [
            "uygulamayı aç", "programı aç",
            "aç", "başlat", "çalıştır", "open", "launch", "bi açsana",
        ],
        "extract": "_extract_app_name",
    },
    "get_running_apps": {
        "triggers": [
            "çalışan uygulamalar", "açık uygulamalar", "running apps",
            "ne çalışıyor", "neler çalışıyor", "hangi uygulamalar açık",
        ],
        "extract": None,
    },
    "kill_process": {
        "triggers": ["zorla kapat", "process öldür", "kill process", "kill"],
        "extract": "_extract_app_name",
    },
    "get_process_info": {
        "triggers": ["process bilgisi", "processler", "çalışan processler", "process listesi"],
        "extract": None,
    },

    # ===== DOSYA ISLEMLERI =====
    "list_files": {
        "triggers": [
            "dosyaları göster", "dosyaları listele", "dosyalar",
            "klasörde ne var", "klasördeki dosyalar", "içindekiler",
            "ne var", "neler var", "listele", "göster", "ls",
        ],
        "extract": "_extract_path",
    },
    "read_file": {
        "triggers": [
            "dosyayı oku", "dosya oku", "dosya içeriği",
            "içeriğini göster", "ne yazıyor", "dosyayı göster",
        ],
        "extract": "_extract_path",
    },
    "write_file": {
        "triggers": [
            "dosya yaz", "dosya oluştur", "dosyaya kaydet",
            "yeni dosya", "metin kaydet",
        ],
        "extract": "_extract_write_params",
    },
    "delete_file": {
        "triggers": ["dosyayı sil", "dosya sil", "sil"],
        "extract": "_extract_path",
    },
    "move_file": {
        "triggers": ["dosyayı taşı", "taşı", "move"],
        "extract": "_extract_path",
    },
    "copy_file": {
        "triggers": ["dosyayı kopyala", "kopyala", "copy"],
        "extract": "_extract_path",
    },
    "rename_file": {
        "triggers": ["adını değiştir", "yeniden adlandır", "rename"],
        "extract": "_extract_path",
    },
    "create_folder": {
        "triggers": ["klasör oluştur", "yeni klasör", "mkdir"],
        "extract": "_extract_path",
    },
    "search_files": {
        "triggers": [
            "dosya ara", "dosyada ara", "dosyalarda ara",
            "ara şunu", "grep", "find",
        ],
        "extract": "_extract_query",
    },

    # ===== SISTEM =====
    "get_system_info": {
        "triggers": [
            "sistem bilgisi", "sistem durumu", "bilgisayar bilgisi",
            "cpu kullanımı", "ram durumu", "disk durumu",
            "pil durumu", "batarya", "system info",
        ],
        "extract": None,
    },
    "open_url": {
        "triggers": [
            "siteyi aç", "sayfayı aç", "sitesine git",
            "url aç", "web aç",
        ],
        "extract": "_extract_url",
    },
    "read_clipboard": {
        "triggers": [
            "panoda ne var", "pano içeriği", "clipboard",
            "kopyalanan ne", "panodaki",
        ],
        "extract": None,
    },
    "write_clipboard": {
        "triggers": ["panoya kopyala", "panoya yaz"],
        "extract": "_extract_content",
    },
    "send_notification": {
        "triggers": [
            "bildirim gönder", "bildirim at", "notification",
            "uyarı gönder",
        ],
        "extract": "_extract_notification",
    },
    "run_safe_command": {
        "triggers": [
            "terminal komutu çalıştır", "komut çalıştır",
            "terminalde çalıştır", "shell komutu",
        ],
        "extract": "_extract_command",
    },

    # ===== macOS =====
    "toggle_dark_mode": {
        "triggers": [
            "karanlık mod", "karanlık modu aç", "karanlık modu kapat",
            "dark mode", "koyu tema", "aydınlık mod", "light mode",
        ],
        "extract": None,
    },
    "get_appearance": {
        "triggers": ["tema ne", "mod ne", "karanlık mı", "aydınlık mı"],
        "extract": None,
    },
    "wifi_status": {
        "triggers": [
            "wifi durumu", "wifi ne durumda",
            "internet var mı", "internet durumu", "bağlantı durumu",
            "ağ durumu", "network status",
        ],
        "extract": None,
    },
    "wifi_toggle": {
        "triggers": [
            "wifi aç", "wifi kapat", "wifi toggle",
            "interneti aç", "interneti kapat",
        ],
        "extract": None,
    },
    "bluetooth_status": {
        "triggers": ["bluetooth durumu", "bluetooth ne durumda", "bluetooth status"],
        "extract": None,
    },
    "get_today_events": {
        "triggers": [
            "bugünkü etkinlikler", "bugün ne var", "bugün etkinlik var mı",
            "takvimde ne var", "takvimi göster", "etkinlikler",
            "today events", "calendar",
        ],
        "extract": None,
    },
    "create_event": {
        "triggers": [
            "etkinlik oluştur", "etkinlik ekle", "takvime ekle",
            "yeni etkinlik", "create event",
        ],
        "extract": "_extract_event",
    },
    "get_reminders": {
        "triggers": [
            "hatırlatıcılar", "hatırlatıcıları göster", "hatırlatıcılarım",
            "reminders", "remind listesi",
        ],
        "extract": None,
    },
    "create_reminder": {
        "triggers": [
            "hatırlatıcı ekle", "hatırlatıcı oluştur", "hatırlat",
            "beni hatırlat", "remind", "yeni hatırlatıcı",
        ],
        "extract": "_extract_reminder",
    },
    "spotlight_search": {
        "triggers": [
            "spotlight ara", "bilgisayarda ara", "sistemde ara",
            "spotlight", "mdfind",
        ],
        "extract": "_extract_query",
    },
    "get_system_preferences": {
        "triggers": ["sistem tercihleri", "sistem ayarları", "preferences"],
        "extract": None,
    },

    # ===== OFFICE =====
    "read_word": {
        "triggers": ["word oku", "word dosyası oku", "docx oku", "belgeyi oku"],
        "extract": "_extract_path",
    },
    "write_word": {
        "triggers": ["word yaz", "word oluştur", "belge oluştur", "docx oluştur"],
        "extract": "_extract_write_params",
    },
    "read_excel": {
        "triggers": ["excel oku", "tablo oku", "xlsx oku", "spreadsheet oku"],
        "extract": "_extract_path",
    },
    "write_excel": {
        "triggers": ["excel yaz", "excel oluştur", "tablo oluştur", "xlsx oluştur"],
        "extract": "_extract_write_params",
    },
    "read_pdf": {
        "triggers": ["pdf oku", "pdf göster", "pdf aç"],
        "extract": "_extract_path",
    },
    "get_pdf_info": {
        "triggers": ["pdf bilgisi", "pdf info", "kaç sayfa"],
        "extract": "_extract_path",
    },
    "summarize_document": {
        "triggers": [
            "özetle", "belgeyi özetle", "dokümanı özetle",
            "özet çıkar", "kısa özet", "summarize", "bi özet geç", "özetlesene",
        ],
        "extract": "_extract_path",
    },

    # ===== WEB / ARASTIRMA =====
    "web_search": {
        "triggers": [
            "internette ara", "internette şunu ara",
            "web ara", "web search", "google ara",
            "arama yap", "şunu ara",
        ],
        "extract": "_extract_query",
    },
    "fetch_page": {
        "triggers": ["sayfayı getir", "sayfa içeriği", "web sayfası getir"],
        "extract": "_extract_url",
    },
    "advanced_research": {
        "triggers": [
            "detaylı araştırma yap", "araştırma yap", "araştır",
            "incele", "research",
        ],
        "extract": "_extract_topic",
    },
    "quick_research": {
        "triggers": ["hızlı araştır", "kısa araştır", "quick research"],
        "extract": "_extract_topic",
    },
    "deep_research": {
        "triggers": [
            "derin araştırma", "akademik araştırma", "kapsamlı araştırma",
            "deep research",
        ],
        "extract": "_extract_topic",
    },

    # ===== NOT =====
    "create_note": {
        "triggers": ["not oluştur", "not yaz", "yeni not", "not al", "create note"],
        "extract": "_extract_note",
    },
    "list_notes": {
        "triggers": ["notlarım", "notları göster", "notlar ne", "notlar", "list notes"],
        "extract": None,
    },
    "search_notes": {
        "triggers": ["notlarda ara", "not ara", "notlarda bul"],
        "extract": "_extract_query",
    },
    "delete_note": {
        "triggers": ["notu sil", "not sil", "delete note"],
        "extract": "_extract_query",
    },

    # ===== PLAN =====
    "create_plan": {
        "triggers": ["plan oluştur", "plan yap", "yeni plan", "create plan"],
        "extract": "_extract_title",
    },
    "list_plans": {
        "triggers": ["planlarım", "planları göster", "planlar", "list plans"],
        "extract": None,
    },
    "get_plan_status": {
        "triggers": ["plan durumu", "plan nasıl gidiyor", "plan status"],
        "extract": None,
    },

    # ===== EMAIL =====
    "send_email": {
        "triggers": ["mail gönder", "e-posta gönder", "email gönder", "email at"],
        "extract": "_extract_email_params",
    },
    "get_emails": {
        "triggers": ["mailler", "e-postalar", "gelen kutusu", "inbox", "mailleri göster"],
        "extract": None,
    },
    "get_unread_emails": {
        "triggers": [
            "okunmamış mail", "yeni mail", "yeni e-posta",
            "mail gelmiş mi", "mail var mı",
            "okunmamış e-posta",
        ],
        "extract": None,
    },
    "search_emails": {
        "triggers": ["maillerde ara", "mail ara", "e-posta ara", "email search"],
        "extract": "_extract_query",
    },

    # ===== KOD =====
    "execute_python_code": {
        "triggers": [
            "python çalıştır", "python kodu çalıştır", "python kodu",
            "py çalıştır", "python run",
        ],
        "extract": "_extract_code",
    },
    "execute_javascript_code": {
        "triggers": [
            "javascript çalıştır", "js çalıştır", "node çalıştır",
            "javascript kodu", "js kodu",
        ],
        "extract": "_extract_code",
    },
    "execute_shell_command": {
        "triggers": ["shell komutu", "bash çalıştır", "bash komutu"],
        "extract": "_extract_command",
    },
    "debug_code": {
        "triggers": ["kodu debug et", "debug yap", "hata bul", "debug"],
        "extract": "_extract_code",
    },

    # ===== BELGE ISLEME =====
    "edit_text_file": {
        "triggers": ["dosyayı düzenle", "metin düzenle", "dosyayı edit et", "text edit"],
        "extract": "_extract_path",
    },
    "merge_pdfs": {
        "triggers": ["pdf birleştir", "pdfleri birleştir", "merge pdf"],
        "extract": None,
    },
    "merge_word_documents": {
        "triggers": ["word birleştir", "belgeleri birleştir", "merge word"],
        "extract": None,
    },

    # ===== GORSELLESTIRME =====
    "create_chart": {
        "triggers": ["grafik oluştur", "chart yap", "grafik çiz", "tablo çiz", "chart oluştur"],
        "extract": None,
    },

    # ===== GELISMIS =====
    "analyze_document": {
        "triggers": ["belgeyi analiz et", "doküman analizi", "dosyayı analiz et", "dosyayı incele"],
        "extract": "_extract_path",
    },
    "analyze_image": {
        "triggers": [
            "resmi analiz et", "görseli incele", "fotoğrafı analiz et",
            "resimde ne var", "görselde ne var", "image analyze",
        ],
        "extract": "_extract_path",
    },
    "generate_report": {
        "triggers": ["rapor oluştur", "rapor yaz", "rapor hazırla", "report generate"],
        "extract": "_extract_topic",
    },
    "generate_research_document": {
        "triggers": [
            "araştırma belgesi oluştur", "araştırma dokümanı",
            "araştırma raporu oluştur",
        ],
        "extract": "_extract_topic",
    },
    "smart_summarize": {
        "triggers": ["akıllı özet", "ai özet", "smart summary", "smart özetle"],
        "extract": "_extract_content",
    },
    "create_smart_file": {
        "triggers": ["akıllı dosya oluştur", "smart file", "ai dosya"],
        "extract": "_extract_write_params",
    },
}


# ============================================================
# 3. FUZZY MATCHER
# ============================================================

class FuzzyIntentMatcher:

    def __init__(self):
        # Pre-compile: her trigger'i tool'a eşleyen reverse index
        self._trigger_index: List[Tuple[str, str, Optional[str]]] = []
        for tool_name, spec in TOOL_PATTERNS.items():
            extract_fn = spec.get("extract")
            for trigger in spec["triggers"]:
                self._trigger_index.append((trigger, tool_name, extract_fn))
        # Uzun trigger'lar once denenir (daha spesifik = daha iyi match)
        self._trigger_index.sort(key=lambda x: -len(x[0]))
        logger.info(f"FuzzyIntentMatcher initialized: {len(TOOL_PATTERNS)} tools, {len(self._trigger_index)} triggers")

    def match(self, raw_input: str) -> Optional[FuzzyResult]:
        """Kullanici girdisini normalize edip en iyi tool'u bul."""
        start = time.time()
        normalized = normalize_turkish(raw_input)

        if not normalized:
            return None

        best: Optional[FuzzyResult] = None
        best_score = 0.0

        for trigger, tool_name, extract_fn in self._trigger_index:
            score = self._score(normalized, trigger)
            if score > best_score:
                best_score = score
                params = {}
                if extract_fn:
                    extractor = getattr(self, extract_fn, None)
                    if extractor:
                        params = extractor(normalized, raw_input, trigger)
                best = FuzzyResult(
                    tool=tool_name,
                    params=params,
                    confidence=score,
                    matched_trigger=trigger,
                    normalized_input=normalized,
                )

        elapsed = (time.time() - start) * 1000
        if best and best.confidence >= 0.60:
            logger.info(
                f"Fuzzy match: '{raw_input}' -> {best.tool} "
                f"(conf={best.confidence:.2f}, trigger='{best.matched_trigger}', "
                f"time={elapsed:.1f}ms)"
            )
            return best

        logger.debug(f"Fuzzy no match: '{raw_input}' (best={best_score:.2f}, time={elapsed:.1f}ms)")
        return None

    # ----- Scoring -----

    def _score(self, text: str, trigger: str) -> float:
        """Metinle trigger arasindaki benzerlik skoru (0-1)."""
        # 1. Tam eslesme
        if trigger == text:
            return 1.0

        # 2. Trigger metinde substring olarak geciyor
        if trigger in text:
            # Daha uzun trigger = daha yuksek skor
            coverage = len(trigger) / max(len(text), 1)
            return 0.70 + coverage * 0.25  # 0.70 - 0.95

        # 3. Tum trigger kelimeleri metinde var (sira onemli degil)
        trigger_words = set(trigger.split())
        text_words = set(text.split())
        if trigger_words and trigger_words.issubset(text_words):
            coverage = len(trigger_words) / max(len(text_words), 1)
            return 0.65 + coverage * 0.20  # 0.65 - 0.85

        # 4. Cogunluk kelime eslesmesi (>= %60)
        if trigger_words:
            overlap = len(trigger_words & text_words)
            ratio = overlap / len(trigger_words)
            if ratio >= 0.6:
                return 0.50 + ratio * 0.20  # 0.50 - 0.70

        return 0.0

    # ----- Parameter Extractors -----

    def _extract_volume(self, normalized: str, raw: str, trigger: str) -> dict:
        """Ses parametrelerini cikar."""
        text = normalized
        # Mute
        if any(w in text for w in ["kapat", "sessiz", "sessize", "mute"]):
            return {"mute": True}
        if any(w in text for w in ["unmute"]) or (text.startswith("sesi aç") or text.startswith("ses aç")):
            return {"mute": False}
        # Seviye
        level_match = re.search(r"(\d+)", text)
        if level_match:
            return {"level": min(100, max(0, int(level_match.group(1))))}
        # Azalt / artır
        if any(w in text for w in ["kıs", "azalt", "düşür"]):
            return {"level": 30}
        if any(w in text for w in ["yükselt", "artır", "arttır"]):
            return {"level": 70}
        return {}

    def _extract_brightness(self, normalized: str, raw: str, trigger: str) -> dict:
        level_match = re.search(r"(\d+)", normalized)
        if level_match:
            return {"level": min(100, max(0, int(level_match.group(1))))}
        if any(w in normalized for w in ["artır", "yükselt", "aç"]):
            return {"level": 75}
        if any(w in normalized for w in ["azalt", "düşür", "kıs", "kapat"]):
            return {"level": 10}
        return {}

    def _extract_app_name(self, normalized: str, raw: str, trigger: str) -> dict:
        """Uygulama adini cikar."""
        text = normalized

        # Trigger'i cikart, kalan kisimda app adi ara
        remaining = text
        for t_word in trigger.split():
            remaining = remaining.replace(t_word, "", 1)
        remaining = remaining.strip()

        # App aliases'da ara
        for alias, real_name in sorted(_APP_ALIASES.items(), key=lambda x: -len(x[0])):
            if alias in remaining or alias in text:
                return {"app_name": real_name}

        # Kalan text'i app adı olarak kullan
        if remaining and len(remaining) > 1:
            return {"app_name": remaining.strip().title()}
        return {}

    def _extract_path(self, normalized: str, raw: str, trigger: str) -> dict:
        """Dosya yolu cikar."""
        text = raw.lower()
        # Explicit path
        path_match = re.search(r"[~/][\w\-./]+", text)
        if path_match:
            return {"path": path_match.group(0)}
        # Path alias
        for alias, folder in _PATH_ALIASES.items():
            if alias in text:
                return {"path": str(Path(HOME_DIR) / folder) if folder else str(HOME_DIR)}
        return {"path": str(Path(HOME_DIR) / "Desktop")}

    def _extract_write_params(self, normalized: str, raw: str, trigger: str) -> dict:
        """Dosya yazma parametreleri."""
        params = self._extract_path(normalized, raw, trigger)
        # İçerik: ":" sonrası veya trigger sonrası metin
        content_match = re.search(r":\s*(.+)$", raw)
        if content_match:
            params["content"] = content_match.group(1).strip()
        return params

    def _extract_url(self, normalized: str, raw: str, trigger: str) -> dict:
        url_match = re.search(r"https?://\S+", raw)
        if url_match:
            return {"url": url_match.group(0)}
        # URL alias
        for alias, url in _URL_ALIASES.items():
            if alias in normalized:
                return {"url": url}
        return {}

    def _extract_query(self, normalized: str, raw: str, trigger: str) -> dict:
        """Arama sorgusu cikar: trigger sonrası metin."""
        text = normalized
        # ":" sonrası
        colon_match = re.search(r":\s*(.+)$", text)
        if colon_match:
            return {"query": colon_match.group(1).strip()}
        # Trigger'i cikar, kalan = query
        for t in TOOL_PATTERNS.get("web_search", {}).get("triggers", []):
            if t in text:
                remaining = text.replace(t, "", 1).strip()
                if remaining:
                    return {"query": remaining}
        # Son care: trigger'i cikar
        remaining = text
        for word in trigger.split():
            remaining = remaining.replace(word, "", 1)
        remaining = remaining.strip()
        if remaining:
            return {"query": remaining}
        return {}

    def _extract_topic(self, normalized: str, raw: str, trigger: str) -> dict:
        """Arastirma konusu cikar."""
        text = raw.lower()
        # "hakkında" pattern
        hakkinda_match = re.search(r"(.+?)\s+hakkında", text)
        if hakkinda_match:
            topic = hakkinda_match.group(1).strip()
            topic = normalize_turkish(topic)
            if topic and len(topic) > 2:
                return {"topic": topic}
        # ":" sonrası
        colon_match = re.search(r":\s*(.+)$", text)
        if colon_match:
            return {"topic": colon_match.group(1).strip()}
        # Trigger'i cikar, kalan = topic
        remaining = normalize_turkish(text)
        for word in trigger.split():
            remaining = remaining.replace(word, "", 1)
        remaining = re.sub(r"\byap\w*\b", "", remaining)
        remaining = re.sub(r"\b(detaylı|kapsamlı|kısa|hızlı|derin|akademik)\b", "", remaining)
        remaining = " ".join(remaining.split()).strip()
        if remaining and len(remaining) > 2:
            return {"topic": remaining}
        return {}

    def _extract_content(self, normalized: str, raw: str, trigger: str) -> dict:
        colon_match = re.search(r":\s*(.+)$", raw)
        if colon_match:
            return {"content": colon_match.group(1).strip()}
        remaining = normalized
        for word in trigger.split():
            remaining = remaining.replace(word, "", 1)
        remaining = remaining.strip()
        if remaining:
            return {"content": remaining}
        return {}

    def _extract_notification(self, normalized: str, raw: str, trigger: str) -> dict:
        remaining = normalized
        for word in trigger.split():
            remaining = remaining.replace(word, "", 1)
        remaining = remaining.strip()
        if remaining:
            return {"title": "Bildirim", "message": remaining}
        return {"title": "Bildirim", "message": ""}

    def _extract_command(self, normalized: str, raw: str, trigger: str) -> dict:
        colon_match = re.search(r":\s*(.+)$", raw)
        if colon_match:
            return {"command": colon_match.group(1).strip()}
        remaining = raw.lower()
        for word in trigger.split():
            remaining = remaining.replace(word, "", 1)
        remaining = remaining.strip()
        if remaining:
            return {"command": remaining}
        return {}

    def _extract_code(self, normalized: str, raw: str, trigger: str) -> dict:
        colon_match = re.search(r":\s*(.+)$", raw, re.DOTALL)
        if colon_match:
            return {"code": colon_match.group(1).strip()}
        # Backtick code block
        code_match = re.search(r"`(.+?)`", raw, re.DOTALL)
        if code_match:
            return {"code": code_match.group(1).strip()}
        return {}

    def _extract_event(self, normalized: str, raw: str, trigger: str) -> dict:
        remaining = normalized
        for word in trigger.split():
            remaining = remaining.replace(word, "", 1)
        remaining = remaining.strip()
        params = {}
        if remaining:
            params["title"] = remaining
        # Basit tarih/saat
        time_match = re.search(r"(\d{1,2})[:.:](\d{2})", raw)
        if time_match:
            params["time"] = f"{time_match.group(1)}:{time_match.group(2)}"
        date_keywords = {
            "bugün": "today", "yarın": "tomorrow",
            "pazartesi": "monday", "salı": "tuesday",
            "çarşamba": "wednesday", "perşembe": "thursday",
            "cuma": "friday", "cumartesi": "saturday", "pazar": "sunday",
        }
        for kw, val in date_keywords.items():
            if kw in normalized:
                params["date"] = val
                break
        return params

    def _extract_reminder(self, normalized: str, raw: str, trigger: str) -> dict:
        params = self._extract_event(normalized, raw, trigger)
        if "title" not in params:
            remaining = normalized
            for word in trigger.split():
                remaining = remaining.replace(word, "", 1)
            remaining = remaining.strip()
            if remaining:
                params["title"] = remaining
        return params

    def _extract_note(self, normalized: str, raw: str, trigger: str) -> dict:
        remaining = normalized
        for word in trigger.split():
            remaining = remaining.replace(word, "", 1)
        remaining = remaining.strip()
        params = {}
        colon_match = re.search(r":\s*(.+)$", remaining)
        if colon_match:
            params["content"] = colon_match.group(1).strip()
            remaining = remaining[:remaining.index(":")].strip()
        if remaining:
            params["title"] = remaining
        return params

    def _extract_title(self, normalized: str, raw: str, trigger: str) -> dict:
        remaining = normalized
        for word in trigger.split():
            remaining = remaining.replace(word, "", 1)
        remaining = remaining.strip()
        if remaining:
            return {"name": remaining}
        return {}

    def _extract_email_params(self, normalized: str, raw: str, trigger: str) -> dict:
        params = {}
        email_match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", raw)
        if email_match:
            params["to"] = email_match.group(0)
        colon_match = re.search(r":\s*(.+)$", raw)
        if colon_match:
            params["body"] = colon_match.group(1).strip()
        return params


# ============================================================
# 4. GLOBAL INSTANCE
# ============================================================

_instance: Optional[FuzzyIntentMatcher] = None


def get_fuzzy_matcher() -> FuzzyIntentMatcher:
    global _instance
    if _instance is None:
        _instance = FuzzyIntentMatcher()
    return _instance
