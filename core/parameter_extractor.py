"""
Parameter Extractor for Turkish Commands

Normalizes paths, app names, and extracts parameters from Turkish text.
"""

import re
from typing import Dict, Any, Optional
from datetime import datetime, timedelta


# Path aliases (Turkish → English)
PATH_ALIASES = {
    "masaüstü": "~/Desktop",
    "masaustu": "~/Desktop",
    "desktop": "~/Desktop",
    
    "dökümanlar": "~/Documents",
    "dokumanlar": "~/Documents",
    "belgeler": "~/Documents",
    "documents": "~/Documents",
    
    "indirilenler": "~/Downloads",
    "downloads": "~/Downloads",
    
    "resimler": "~/Pictures",
    "pictures": "~/Pictures",
    "fotoğraflar": "~/Pictures",
    
    "müzik": "~/Music",
    "muzik": "~/Music",
    "music": "~/Music",
    
    "videolar": "~/Movies",
    "videos": "~/Movies",
    "filmler": "~/Movies",
}


# App name aliases (Turkish/informal → proper name)
APP_ALIASES = {
    "krom": "chrome",
    "google chrome": "chrome",
    
    "vscode": "visual studio code",
    "vs code": "visual studio code",
    "kod": "visual studio code",
    
    "word": "microsoft word",
    "kelime": "microsoft word",
    
    "excel": "microsoft excel",
    
    "powerpoint": "microsoft powerpoint",
    
    "not defteri": "notes",
    "notlar": "notes",
    
    "mesajlar": "messages",
    "message": "messages",
    
    "takvim": "calendar",
    
    "mail": "mail",
    "posta": "mail",
    
    "finder": "finder",
    "dosya yöneticisi": "finder",
    
    "terminal": "terminal",
    "komut satırı": "terminal",
    
    "safari": "safari",
    "tarayıcı": "safari",
}


def normalize_path(path_text: str) -> str:
    """
    Normalize Turkish path to proper path.
    
    Examples:
    "masaüstü" → "~/Desktop"
    "masaüstü/test" → "~/Desktop/test"
    "/Desktop/test" → "~/Desktop/test"
    """
    path_text = path_text.strip()
    path_lower = path_text.lower()
    
    # 1. Handle common absolute path error (/Desktop -> ~/Desktop)
    if path_lower.startswith("/desktop"):
        return "~" + path_text
    
    # 2. Check direct aliases
    if path_lower in PATH_ALIASES:
        return PATH_ALIASES[path_lower]
    
    # 3. Handle subpaths with aliases (e.g., "masaüstü/test")
    for alias, real_path in PATH_ALIASES.items():
        if path_lower.startswith(alias + "/"):
            return real_path + path_text[len(alias):]
        if path_lower.startswith(alias + " "): # Handle "masaüstü test"
            return real_path + "/" + path_text[len(alias):].strip()

    # Return as-is if already looks like a valid path
    if path_text.startswith(('~', '/')) and not path_lower.startswith('/desktop'):
        return path_text
    
    return path_text


def clean_name_string(text: str) -> str:
    """
    Remove Turkish naming filler words from extracted names.
    
    Examples:
    "test adında" -> "test"
    "rapor isimli" -> "test"
    "test klasörü" -> "test"
    """
    if not text:
        return text
    
    # Common Turkish naming markers and suffixes
    filler_patterns = [
        r"\s+adında\b",
        r"\s+isimli\b",
        r"\s+adlı\b",
        r"\s+dosyası\b",
        r"\s+klasörü\b",
        r"\s+adi\b",
        r"\s+ismini\b",
        r"\s+ismini koy\b",
        r"\b(yeni|bir)\s+",
        r"'\s*[uıiü]$",
        r"\s+[uıiü]$",
    ]
    
    cleaned = text
    for pattern in filler_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    
    return cleaned.strip()


def normalize_app_name(app_text: str) -> str:
    """
    Normalize Turkish/informal app name to proper name.
    
    Examples:
        "krom" → "chrome"
        "vscode" → "visual studio code"
    """
    app_lower = app_text.lower().strip()
    
    # Remove possessive suffix ('u, 'ı, 'i, 'ü, 'yi, 'yı, 'yu, 'yü)
    app_lower = re.sub(r"('|\s)?(y)?[uıiü]$", "", app_lower)
    
    # Check aliases
    if app_lower in APP_ALIASES:
        return APP_ALIASES[app_lower]
    
    # Return cleaned version
    return app_lower


def extract_number(text: str) -> Optional[int]:
    """
    Extract number from text.
    
    Examples:
        "ses 50 yap" → 50
        "parlaklık 80" → 80
    """
    match = re.search(r'\b(\d+)\b', text)
    if match:
        return int(match.group(1))
    return None


def parse_turkish_time(time_text: str) -> Optional[str]:
    """
    Parse Turkish time expressions.
    
    Examples:
        "yarın saat 9" → "tomorrow 09:00"
        "bugün 14:30" → "today 14:30"
        "10 dakika sonra" → "+10 minutes"
    """
    time_lower = time_text.lower()
    
    # Tomorrow
    if "yarın" in time_lower:
        hour_match = re.search(r'saat\s*(\d+)', time_lower)
        if hour_match:
            hour = hour_match.group(1)
            return f"tomorrow {hour}:00"
        return "tomorrow"
    
    # Today
    if "bugün" in time_lower:
        time_match = re.search(r'(\d{1,2}):?(\d{2})?', time_lower)
        if time_match:
            hour = time_match.group(1)
            minute = time_match.group(2) or "00"
            return f"today {hour}:{minute}"
        return "today"
    
    # In X minutes
    minute_match = re.search(r'(\d+)\s*dakika\s*sonra', time_lower)
    if minute_match:
        minutes = minute_match.group(1)
        return f"+{minutes} minutes"
    
    # In X hours
    hour_match = re.search(r'(\d+)\s*saat\s*sonra', time_lower)
    if hour_match:
        hours = hour_match.group(1)
        return f"+{hours} hours"
    
    return None


def extract_file_pattern(text: str) -> Optional[str]:
    """
    Extract file pattern from text.
    
    Examples:
        "pdf'leri göster" → "*.pdf"
        "fotoğrafları listele" → "*.{jpg,png,jpeg}"
    """
    text_lower = text.lower()
    
    # Photos
    if any(word in text_lower for word in ["fotoğraf", "resim", "foto", "image", "görsel"]):
        return "*.{jpg,png,jpeg,gif,heic}"
    
    # Documents
    if any(word in text_lower for word in ["döküman", "belge", "doküman", "metin"]):
        return "*.{pdf,doc,docx,txt}"
    
    # PDFs
    if "pdf" in text_lower:
        return "*.pdf"
    
    # Videos
    if "video" in text_lower or "film" in text_lower:
        return "*.{mp4,mov,avi,mkv}"
    
    # Music
    if any(word in text_lower for word in ["müzik", "şarkı", "parça", "ses"]):
        return "*.{mp3,m4a,wav,flac}"
    
    return None


class ParameterExtractor:
    """Extract and normalize parameters from Turkish text"""
    
    @staticmethod
    def extract(text: str, action: str) -> Dict[str, Any]:
        """Extract parameters based on action type"""
        params = {}
        
        if action == "open_app":
            # Extract app name
            match = re.search(r"([\w\s]+)'?[uıiü]?\s+(aç|başlat|open)", text, re.IGNORECASE)
            if match:
                app_raw = match.group(1).strip()
                params["app_name"] = normalize_app_name(app_raw)
        
        elif action == "list_files":
            # Extract path
            for alias in PATH_ALIASES.keys():
                if alias in text.lower():
                    params["path"] = PATH_ALIASES[alias]
                    break
            
            # Extract file pattern
            pattern = extract_file_pattern(text)
            if pattern:
                params["pattern"] = pattern
        
        elif action in ["set_volume", "set_brightness"]:
            # Extract number
            number = extract_number(text)
            if number is not None:
                params["level"] = number
        
        elif action == "web_search":
            # Extract search query
            match = re.search(r"(.+?)\s+(ara|search)", text, re.IGNORECASE)
            if match:
                params["query"] = match.group(1).strip()
        
        elif action == "create_reminder":
            # Extract title and time
            match = re.search(r"(.+?)\s+hatırlat", text, re.IGNORECASE)
            if match:
                reminder_text = match.group(1).strip()
                params["title"] = reminder_text
                
                # Parse time if present
                time_str = parse_turkish_time(text)
                if time_str:
                    params["time"] = time_str
        
        return params


# Singleton
_extractor = ParameterExtractor()


def extract_parameters(text: str, action: str) -> Dict[str, Any]:
    """Extract parameters from text for given action"""
    return _extractor.extract(text, action)
