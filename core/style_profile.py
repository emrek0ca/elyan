"""
Elyan Style Profile — Kullanıcı Tarz Profili Sistemi

Ustalığın yarısı kalite, yarısı tarz uyumu.
Her job başında 5-7 satır olarak prompt'a girer.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from utils.logger import get_logger

logger = get_logger("style_profile")

_DEFAULT_PROFILE = {
    "language": "tr",
    "tone": "profesyonel ama anlaşılır",
    "format": "kısa paragraflar, az markdown",
    "preference": "snippet değil, tam dosya",
    "never": [
        "jQuery kullanma",
        "Gereksiz emoji koyma",
        "Kanıtsız teslim iddiası",
        "Kullanıcıya soru bombardımanı yapma",
    ],
}

_PROFILE_PATH = Path.home() / ".elyan" / "style_profile.json"


class StyleProfile:
    """
    Kullanıcı tarz profili.
    
    Her job başında prompt'a enjekte edilir.
    Öğrenme motorundan gelen sinyallerle güncellenir.
    """

    def __init__(self):
        self._profile: Dict[str, Any] = dict(_DEFAULT_PROFILE)
        self._load()

    def _load(self):
        """Disk'ten profili yükle."""
        try:
            if _PROFILE_PATH.exists():
                with open(_PROFILE_PATH, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                self._profile.update(stored)
                logger.info(f"Style profile loaded: {_PROFILE_PATH}")
        except Exception as e:
            logger.debug(f"Style profile load failed: {e}")

    def _save(self):
        """Profili diske kaydet."""
        try:
            _PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_PROFILE_PATH, "w", encoding="utf-8") as f:
                json.dump(self._profile, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Style profile save failed: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self._profile.get(key, default)

    def set(self, key: str, value: Any):
        self._profile[key] = value
        self._save()

    def update_from_feedback(self, key: str, value: Any):
        """Kullanıcı geri bildiriminden tarz güncelle."""
        if key == "tone" and value in ("formal", "friendly", "concise", "detailed"):
            tone_map = {
                "formal": "kurumsal ve resmi",
                "friendly": "samimi ve sıcak",
                "concise": "kısa ve öz",
                "detailed": "detaylı ve kapsamlı",
            }
            self._profile["tone"] = tone_map[value]
        elif key == "language" and value in ("tr", "en"):
            self._profile["language"] = value
        elif key == "never" and isinstance(value, str):
            nevers = self._profile.get("never", [])
            if value not in nevers:
                nevers.append(value)
                self._profile["never"] = nevers
        else:
            self._profile[key] = value
        self._save()

    def to_prompt_lines(self) -> str:
        """
        Prompt'a enjekte edilecek 5-7 satırlık Style Card.
        Her job başında system prompt'a eklenir.
        """
        lines = []
        lines.append(f"Dil: {self._profile.get('language', 'tr')}")
        lines.append(f"Ton: {self._profile.get('tone', 'profesyonel')}")
        lines.append(f"Format: {self._profile.get('format', 'kısa paragraflar')}")
        lines.append(f"Tercih: {self._profile.get('preference', 'tam dosya')}")

        nevers = self._profile.get("never", [])
        if nevers:
            lines.append("ASLA: " + " | ".join(nevers[:5]))

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._profile)


# Global instance
style_profile = StyleProfile()
