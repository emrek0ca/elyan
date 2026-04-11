from __future__ import annotations

import importlib.util
import platform
import shutil
from dataclasses import dataclass

from config.elyan_config import elyan_config
from core.model_catalog import QWEN_LIGHT_OLLAMA_MODEL, default_model_for_provider
from utils.ollama_helper import OllamaHelper


@dataclass(slots=True)
class RuntimeProfile:
    platform_name: str
    machine: str
    apple_silicon: bool
    ollama_available: bool
    tts_backend: str
    stt_backend: str
    recommended_provider: str
    recommended_model: str
    concurrency_profile: str
    local_audio_only: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "platform": self.platform_name,
            "machine": self.machine,
            "apple_silicon": self.apple_silicon,
            "ollama_available": self.ollama_available,
            "tts_backend": self.tts_backend,
            "stt_backend": self.stt_backend,
            "recommended_provider": self.recommended_provider,
            "recommended_model": self.recommended_model,
            "concurrency_profile": self.concurrency_profile,
            "local_audio_only": self.local_audio_only,
        }


def detect_runtime_profile() -> RuntimeProfile:
    platform_name = str(platform.system() or "").lower() or "unknown"
    machine = str(platform.machine() or "").lower()
    apple_silicon = platform_name == "darwin" and machine in {"arm64", "aarch64"}
    ollama_available = False
    try:
        ollama_available = bool(OllamaHelper.is_running() or OllamaHelper.is_installed())
    except Exception:
        ollama_available = False

    if shutil.which("say"):
        tts_backend = "macos_say"
    elif importlib.util.find_spec("pyttsx3") is not None:
        tts_backend = "pyttsx3"
    else:
        tts_backend = "unavailable"

    stt_backend = "whisper" if importlib.util.find_spec("whisper") is not None else "unavailable"

    default_provider = str(elyan_config.get("models.default.provider", "ollama") or "ollama").strip().lower()
    default_model = str(elyan_config.get("models.default.model", "") or "").strip()
    local_model = str(elyan_config.get("models.local.model", "") or "").strip()

    if ollama_available and apple_silicon:
        recommended_provider = "ollama"
        recommended_model = local_model or default_model_for_provider("ollama")
        concurrency_profile = "balanced"
    elif ollama_available:
        recommended_provider = "ollama"
        recommended_model = local_model or QWEN_LIGHT_OLLAMA_MODEL
        concurrency_profile = "light"
    else:
        recommended_provider = default_provider or "openai"
        recommended_model = default_model or default_model_for_provider(recommended_provider)
        concurrency_profile = "light"

    return RuntimeProfile(
        platform_name=platform_name,
        machine=machine,
        apple_silicon=apple_silicon,
        ollama_available=ollama_available,
        tts_backend=tts_backend,
        stt_backend=stt_backend,
        recommended_provider=recommended_provider,
        recommended_model=recommended_model,
        concurrency_profile=concurrency_profile,
    )


__all__ = ["RuntimeProfile", "detect_runtime_profile"]
