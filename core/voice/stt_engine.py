"""
core/voice/stt_engine.py — Elyan STT Engine
───────────────────────────────────────────────────────────────────────────────
Öncelik sırası:
  1. faster-whisper (4x daha hızlı, ffmpeg gerektirmez, ctranslate2 tabanlı)
  2. openai-whisper  (mevcut local_stt fallback)
  3. boş string döner (graceful degradation)

İlk çağrıda model otomatik indirilir (~40 MB tiny model).
"""
from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Literal

from utils.logger import get_logger

logger = get_logger("stt_engine")

ModelSize = Literal["tiny", "base", "small", "medium"]
_DEFAULT_MODEL: ModelSize = "tiny"   # ~40 MB, Türkçe için yeterli


class _FasterWhisperSTT:
    """faster-whisper backend — en hızlı, önerilen."""

    def __init__(self, model_size: ModelSize = _DEFAULT_MODEL) -> None:
        self._model_size = model_size
        self._model = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> bool:
        if self._model is not None:
            return True
        with self._lock:
            if self._model is not None:
                return True
            try:
                from faster_whisper import WhisperModel  # type: ignore
                logger.info(f"faster-whisper yükleniyor ({self._model_size})…")
                self._model = WhisperModel(
                    self._model_size,
                    device="cpu",
                    compute_type="int8",  # CPU için optimize
                )
                logger.info("faster-whisper hazır")
                return True
            except ImportError:
                logger.debug("faster-whisper kurulu değil, yükleniyor…")
                return self._auto_install()
            except Exception as exc:
                logger.warning(f"faster-whisper yüklenemedi: {exc}")
                return False

    def _auto_install(self) -> bool:
        import subprocess, sys
        try:
            logger.info("faster-whisper kuruluyor…")
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "faster-whisper", "-q"],
                capture_output=True, timeout=120,
            )
            if r.returncode == 0:
                from faster_whisper import WhisperModel  # type: ignore
                self._model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
                logger.info("faster-whisper kuruldu ve hazır")
                return True
        except Exception as exc:
            logger.warning(f"faster-whisper auto-install başarısız: {exc}")
        return False

    def transcribe(self, wav_path: str, language: str = "tr") -> str:
        if not self._ensure_loaded() or self._model is None:
            return ""
        if not os.path.exists(wav_path):
            return ""
        try:
            segments, info = self._model.transcribe(
                wav_path,
                language=language,
                beam_size=1,         # hız için
                vad_filter=True,     # boş sessiz kısımları atla
            )
            text = " ".join(s.text for s in segments).strip()
            logger.debug(f"STT: '{text[:80]}' (lang={info.language}, dur={info.duration:.1f}s)")
            return text
        except Exception as exc:
            logger.warning(f"faster-whisper transcribe hatası: {exc}")
            return ""


class _OpenAIWhisperSTT:
    """openai-whisper fallback backend."""

    def transcribe(self, wav_path: str, language: str = "tr") -> str:
        try:
            from tools.voice.local_stt import stt_engine as _legacy
            # legacy is sync
            result = _legacy.transcribe(wav_path)
            return str(result or "").strip()
        except Exception as exc:
            logger.debug(f"openai-whisper fallback hatası: {exc}")
            return ""


class ElyanSTT:
    """Unified STT — faster-whisper preferred, openai-whisper fallback."""

    def __init__(self) -> None:
        self._primary = _FasterWhisperSTT()
        self._fallback = _OpenAIWhisperSTT()

    async def transcribe_async(self, wav_path: str, language: str = "tr") -> str:
        """Non-blocking transcription (runs in executor)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._transcribe_sync, wav_path, language)

    def _transcribe_sync(self, wav_path: str, language: str) -> str:
        result = self._primary.transcribe(wav_path, language)
        if result:
            return result
        logger.debug("Primary STT boş döndü, fallback deneniyor")
        return self._fallback.transcribe(wav_path, language)

    def warmup(self) -> None:
        """Modeli önceden yükle (startup'ta çağrılır, ilk komutu hızlandırır)."""
        threading.Thread(target=self._primary._ensure_loaded, daemon=True).start()


# ── Singleton ──────────────────────────────────────────────────────────────────

_instance: ElyanSTT | None = None


def get_stt_engine() -> ElyanSTT:
    global _instance
    if _instance is None:
        _instance = ElyanSTT()
    return _instance
