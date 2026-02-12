"""
Enhanced Intent Patterns
Comprehensive pattern matching for Turkish/English natural language
"""

from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum
import re


class IntentCategory(Enum):
    """Intent categories"""
    FILE_OPERATION = "file_operation"
    APP_CONTROL = "app_control"
    SYSTEM_INFO = "system_info"
    SCREENSHOT = "screenshot"
    CLIPBOARD = "clipboard"
    NOTIFICATION = "notification"
    DOCUMENT = "document"
    RESEARCH = "research"
    NOTE = "note"
    TASK_PLANNING = "task_planning"
    CALENDAR = "calendar"
    EMAIL = "email"
    CODE = "code"
    MEDIA = "media"
    CHAT = "chat"
    HELP = "help"


@dataclass
class Pattern:
    """Represents a command pattern"""
    category: IntentCategory
    triggers: List[str]  # Keywords that trigger this pattern
    aliases: Dict[str, str] = None  # Parameter aliases
    min_confidence: float = 0.5
    description: str = ""

    def __post_init__(self):
        if self.aliases is None:
            self.aliases = {}

    def matches(self, text: str) -> bool:
        """Check if text matches any trigger"""
        text_lower = text.lower()
        return any(trigger in text_lower for trigger in self.triggers)


class EnhancedPatterns:
    """Comprehensive pattern database for natural language understanding"""

    def __init__(self):
        self.patterns: Dict[IntentCategory, List[Pattern]] = {}
        self._initialize_patterns()

    def _initialize_patterns(self):
        """Initialize all patterns"""
        # File Operations
        self.patterns[IntentCategory.FILE_OPERATION] = [
            Pattern(
                IntentCategory.FILE_OPERATION,
                ["listele", "list", "ne var", "göster", "içeriğini", "dosya", "neler var", "klasöründe", "dizininde", "bak", "dosyaları göster"],
                {"folder": "path"},
                description="List files in directory"
            ),
            Pattern(
                IntentCategory.FILE_OPERATION,
                ["oku", "read", "aç", "göster içeriğini", "bak", "içinde ne yazıyor", "metni göster"],
                {"file": "path"},
                description="Read file content"
            ),
            Pattern(
                IntentCategory.FILE_OPERATION,
                ["yaz", "write", "oluştur", "create", "kaydet", "ekle", "yeni dosya", "not al"],
                {"file": "path", "content": "text"},
                description="Write to file"
            ),
            Pattern(
                IntentCategory.FILE_OPERATION,
                ["sil", "delete", "kaldır", "remove", "temizle"],
                {"file": "path"},
                description="Delete file"
            ),
            Pattern(
                IntentCategory.FILE_OPERATION,
                ["taşı", "move", "kopyala", "copy", "adlandır", "rename"],
                {"source": "path", "dest": "path"},
                description="Move/Copy/Rename file"
            ),
            Pattern(
                IntentCategory.FILE_OPERATION,
                ["dosyada ara", "dosya ara", "file search", "grep", "find", "pattern"],
                {"pattern": "str", "directory": "path"},
                min_confidence=0.6,
                description="Search files"
            ),
        ]

        # App Control
        self.patterns[IntentCategory.APP_CONTROL] = [
            Pattern(
                IntentCategory.APP_CONTROL,
                ["uygulamayı aç", "uygulamayı başlat", "uygulamayı çalıştır", "open app", "launch app"],
                {"app": "str"},
                min_confidence=0.65,
                description="Open application"
            ),
            Pattern(
                IntentCategory.APP_CONTROL,
                ["uygulamayı kapat", "programı kapat", "close app", "quit app", "sonlandır"],
                {"app": "str"},
                description="Close application"
            ),
            Pattern(
                IntentCategory.APP_CONTROL,
                ["sitesine git", "sitesini aç", "web sitesi"],
                {"url": "str"},
                description="Open URL"
            ),
        ]

        # System Operations
        self.patterns[IntentCategory.SYSTEM_INFO] = [
            Pattern(
                IntentCategory.SYSTEM_INFO,
                ["sistem bilgisi", "system info", "sistem durumu", "bilgisayar bilgisi"],
                description="Get system information"
            ),
            Pattern(
                IntentCategory.SYSTEM_INFO,
                ["parlaklık", "brightness"],
                {"level": "int"},
                description="Control brightness"
            ),
            Pattern(
                IntentCategory.SYSTEM_INFO,
                ["dark mode", "karanlık mod", "light mode", "aydınlık mod"],
                description="Toggle appearance"
            ),
            Pattern(
                IntentCategory.SYSTEM_INFO,
                ["wifi durumu", "internet durumu", "ağ durumu", "bluetooth durumu"],
                description="Network status"
            ),
        ]

        # Screenshots
        self.patterns[IntentCategory.SCREENSHOT] = [
            Pattern(
                IntentCategory.SCREENSHOT,
                ["ss", "screenshot", "ekran", "görüntü", "ekranı", "screencap", "capture"],
                {"filename": "str"},
                min_confidence=0.3,  # Daha düşük threshold - daha kolay match
                description="Take screenshot"
            ),
            Pattern(
                IntentCategory.SCREENSHOT,
                ["video", "kayıt", "record", "capture", "screen record"],
                {"duration": "int"},
                description="Record screen video"
            ),
        ]

        # Clipboard
        self.patterns[IntentCategory.CLIPBOARD] = [
            Pattern(
                IntentCategory.CLIPBOARD,
                ["yapıştır", "paste", "pano", "clipboard"],
                description="Read clipboard"
            ),
            Pattern(
                IntentCategory.CLIPBOARD,
                ["kopyala", "copy", "panoya", "clipboard"],
                {"text": "str"},
                description="Copy to clipboard"
            ),
        ]

        # Documents
        self.patterns[IntentCategory.DOCUMENT] = [
            Pattern(
                IntentCategory.DOCUMENT,
                ["word", "docx", "doc", "belge", "belgeni", "oluştur", "yaz"],
                {"filename": "str", "content": "text"},
                description="Create Word document"
            ),
            Pattern(
                IntentCategory.DOCUMENT,
                ["excel", "xlsx", "xls", "tablo", "spreadsheet"],
                {"filename": "str", "data": "dict"},
                description="Create Excel spreadsheet"
            ),
            Pattern(
                IntentCategory.DOCUMENT,
                ["pdf", "birleştir", "merge", "çıkart", "extract", "özet"],
                {"files": "list"},
                description="PDF operations"
            ),
            Pattern(
                IntentCategory.DOCUMENT,
                ["özetle", "summary", "önemli", "key points", "sumar"],
                {"document": "path"},
                description="Summarize document"
            ),
        ]

        # Research
        self.patterns[IntentCategory.RESEARCH] = [
            Pattern(
                IntentCategory.RESEARCH,
                ["araştırma", "arastirma", "araştır", "arastir", "research", "inceleme"],
                {"topic": "str", "depth": "str"},
                min_confidence=0.7,
                description="Conduct research"
            ),
            Pattern(
                IntentCategory.RESEARCH,
                ["rapor oluştur", "rapor yaz", "report", "araştırma raporu", "research report"],
                {"topic": "str", "format": "str"},
                min_confidence=0.8,
                description="Generate research report"
            ),
            Pattern(
                IntentCategory.RESEARCH,
                ["kaynağı", "source", "değerlendir", "evaluate", "kontrol", "kaynak değer"],
                {"url": "str"},
                description="Evaluate source reliability"
            ),
            Pattern(
                IntentCategory.RESEARCH,
                ["bulguları", "findings", "sentez", "synthesize", "birleştir", "analiz"],
                {"findings": "list"},
                description="Synthesize findings"
            ),
        ]

        # Notes
        self.patterns[IntentCategory.NOTE] = [
            Pattern(
                IntentCategory.NOTE,
                ["not", "note", "oluştur", "create", "ekle", "yazılı"],
                {"title": "str", "content": "text"},
                description="Create note"
            ),
            Pattern(
                IntentCategory.NOTE,
                ["notlar", "notes", "listele", "list", "goster", "araştır"],
                description="List notes"
            ),
            Pattern(
                IntentCategory.NOTE,
                ["ara", "search", "bul", "find"],
                {"query": "str"},
                description="Search notes"
            ),
            Pattern(
                IntentCategory.NOTE,
                ["güncelle", "update", "düzenle", "edit"],
                {"note_id": "str", "content": "text"},
                description="Update note"
            ),
        ]

        # Task Planning
        self.patterns[IntentCategory.TASK_PLANNING] = [
            Pattern(
                IntentCategory.TASK_PLANNING,
                ["plan", "görev", "task", "oluştur", "create", "yapılacak"],
                {"name": "str", "steps": "list"},
                description="Create task plan"
            ),
            Pattern(
                IntentCategory.TASK_PLANNING,
                ["planlarım", "tasks", "listele", "list", "göster"],
                description="List plans"
            ),
            Pattern(
                IntentCategory.TASK_PLANNING,
                ["planı", "execute", "başlat", "çalıştır"],
                {"plan_id": "str"},
                description="Execute plan"
            ),
            Pattern(
                IntentCategory.TASK_PLANNING,
                ["durumu", "status", "nasıl gidiyor", "kontrol"],
                {"plan_id": "str"},
                description="Check plan status"
            ),
        ]

        # Calendar & Reminders
        self.patterns[IntentCategory.CALENDAR] = [
            Pattern(
                IntentCategory.CALENDAR,
                ["takvim", "calendar", "etkinlik", "event", "bugun", "today"],
                description="Get today's calendar"
            ),
            Pattern(
                IntentCategory.CALENDAR,
                ["etkinlik", "event", "oluştur", "create", "ekle"],
                {"title": "str", "date": "str", "time": "str"},
                description="Create calendar event"
            ),
            Pattern(
                IntentCategory.CALENDAR,
                ["hatırlatıcı", "reminder", "oluştur", "create"],
                {"title": "str", "date": "str"},
                description="Create reminder"
            ),
        ]

        # Email
        self.patterns[IntentCategory.EMAIL] = [
            Pattern(
                IntentCategory.EMAIL,
                ["mail", "e-posta", "email", "gönder", "send"],
                {"to": "str", "subject": "str", "body": "text"},
                description="Send email"
            ),
            Pattern(
                IntentCategory.EMAIL,
                ["postalarım", "emails", "kontrol", "check", "oku"],
                description="Check emails"
            ),
        ]

        # Code
        self.patterns[IntentCategory.CODE] = [
            Pattern(
                IntentCategory.CODE,
                ["kod", "code", "python", "javascript", "çalıştır", "run"],
                {"code": "str"},
                description="Execute code"
            ),
            Pattern(
                IntentCategory.CODE,
                ["debug", "hata", "error", "kontrol", "test"],
                {"code": "str"},
                description="Debug code"
            ),
        ]

        # Media
        self.patterns[IntentCategory.MEDIA] = [
            Pattern(
                IntentCategory.MEDIA,
                ["müzik", "music", "şarkı", "play", "aç", "çal"],
                {"song": "str"},
                description="Play music"
            ),
            Pattern(
                IntentCategory.MEDIA,
                ["video", "youtube", "film", "movie", "izle"],
                {"video": "str"},
                description="Play video"
            ),
            Pattern(
                IntentCategory.MEDIA,
                ["düzenleme", "edit", "resim", "image", "görsel"],
                {"file": "path"},
                description="Edit media"
            ),
        ]

        # Chat/Conversation
        self.patterns[IntentCategory.CHAT] = [
            Pattern(
                IntentCategory.CHAT,
                ["merhaba", "hello", "selam", "hi", "hey"],
                description="Greeting"
            ),
            Pattern(
                IntentCategory.CHAT,
                ["nasılsın", "how are you", "naber", "kabar"],
                description="Conversation"
            ),
            Pattern(
                IntentCategory.CHAT,
                ["teşekkür", "thanks", "sağ ol", "mersi"],
                description="Thank you"
            ),
        ]

        # Help
        self.patterns[IntentCategory.HELP] = [
            Pattern(
                IntentCategory.HELP,
                ["yardım", "help", "ne yapabilirsin", "neler"],
                description="Get help"
            ),
            Pattern(
                IntentCategory.HELP,
                ["komut", "command", "nasıl", "how to"],
                description="Learn command"
            ),
        ]

    def find_category(self, text: str) -> Optional[IntentCategory]:
        """Find best matching intent category"""
        best_match = None
        best_score = 0

        for category, patterns in self.patterns.items():
            for pattern in patterns:
                if pattern.matches(text):
                    score = self._calculate_match_score(text, pattern)
                    if score > best_score:
                        best_score = score
                        best_match = category

        if best_score >= 0.5:
            return best_match
        return None

    def find_patterns(self, text: str, category: Optional[IntentCategory] = None) -> List[Pattern]:
        """Find all matching patterns"""
        matching = []

        categories = [category] if category else self.patterns.keys()

        for cat in categories:
            patterns = self.patterns.get(cat, [])
            for pattern in patterns:
                if pattern.matches(text):
                    matching.append(pattern)

        return matching

    def _calculate_match_score(self, text: str, pattern: Pattern) -> float:
        """Calculate pattern match score (0-1) - prioritizes longer/more specific triggers"""
        text_lower = text.lower()
        if not pattern.triggers:
            return pattern.min_confidence

        # Score each trigger, prioritizing longer (more specific) triggers
        trigger_scores = []
        for trigger in pattern.triggers:
            if trigger in text_lower:
                # Longer triggers score higher (more specific)
                specificity_bonus = len(trigger) / 50.0  # Normalize to reasonable range
                trigger_scores.append(0.5 + specificity_bonus)
            else:
                trigger_scores.append(0.0)

        # Calculate average score
        avg_score = sum(trigger_scores) / len(pattern.triggers) if trigger_scores else 0
        score = min(1.0, avg_score * 1.5)
        return max(pattern.min_confidence, score)

    def extract_parameters(
        self,
        text: str,
        pattern: Pattern
    ) -> Dict[str, Any]:
        """Extract parameters from text based on pattern"""
        params = {}

        # Extract quoted strings
        quoted = re.findall(r'"([^"]*)"', text)
        if quoted:
            params["quoted_text"] = quoted

        # Extract file paths
        files = re.findall(r'[~/\w\-./]+\.[a-z0-9]+', text)
        if files:
            params["files"] = files

        # Extract URLs
        urls = re.findall(r'https?://[^\s]+', text)
        if urls:
            params["urls"] = urls

        # Extract numbers
        numbers = re.findall(r'\d+', text)
        if numbers:
            params["numbers"] = [int(n) for n in numbers]

        # Extract email addresses
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
        if emails:
            params["emails"] = emails

        # Extract app names from Turkish syntax (e.g., "Safari'yi aç", "safari a...")
        # Match: word + optional suffix + action verb
        app_match = re.search(r'(\w+)[\'"]?[ıiyuü]?[ny]?[ıiyuü]?\s*(?:aç|başlat|kapat|sonlandır|a\w*|k\w*)', text)
        if app_match:
            app_name_raw = app_match.group(1).lower()
            # Common app aliases
            app_aliases = {
                "safari": "Safari", "chrome": "Google Chrome", "firefox": "Firefox",
                "terminal": "Terminal", "finder": "Finder", "notlar": "Notes",
                "notes": "Notes", "hesapmakinesi": "Calculator", "calculator": "Calculator"
            }
            params["app_name"] = app_aliases.get(app_name_raw, app_name_raw.title())

        return params

    def get_all_triggers(self, category: Optional[IntentCategory] = None) -> List[str]:
        """Get all triggers for a category or all categories"""
        triggers = []

        categories = [category] if category else self.patterns.keys()
        for cat in categories:
            for pattern in self.patterns.get(cat, []):
                triggers.extend(pattern.triggers)

        # Language specific normalization or cleanup could go here

        return triggers

    def get_category_description(self, category: IntentCategory) -> str:
        """Get human-readable category description"""
        descriptions = {
            IntentCategory.FILE_OPERATION: "Dosya işlemleri (liste, oku, yaz, sil)",
            IntentCategory.APP_CONTROL: "Uygulama kontrol (aç, kapat, web)",
            IntentCategory.SYSTEM_INFO: "Sistem bilgisi ve kontrolü",
            IntentCategory.SCREENSHOT: "Ekran görüntüsü ve video kayıt",
            IntentCategory.CLIPBOARD: "Pano işlemleri (kopyala, yapıştır)",
            IntentCategory.DOCUMENT: "Belge işlemleri (Word, Excel, PDF)",
            IntentCategory.RESEARCH: "Araştırma ve veri toplama",
            IntentCategory.NOTE: "Not alma ve yönetim",
            IntentCategory.TASK_PLANNING: "Görev planlama",
            IntentCategory.CALENDAR: "Takvim ve hatırlatıcılar",
            IntentCategory.EMAIL: "E-posta işlemleri",
            IntentCategory.CODE: "Kod çalıştırma ve debug",
            IntentCategory.MEDIA: "Medya oynatma ve düzenleme",
            IntentCategory.CHAT: "Sohbet ve konuşma",
            IntentCategory.HELP: "Yardım ve rehberlik",
        }
        return descriptions.get(category, str(category))


# Global instance
_enhanced_patterns: Optional[EnhancedPatterns] = None


def get_enhanced_patterns() -> EnhancedPatterns:
    global _enhanced_patterns
    if _enhanced_patterns is None:
        _enhanced_patterns = EnhancedPatterns()
    return _enhanced_patterns
