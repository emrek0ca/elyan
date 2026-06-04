from __future__ import annotations

import os
import shutil
import subprocess
import threading
import sys
import uuid
from pathlib import Path

from runtime import state_store
from runtime.capability_registry import SafeCapabilityError

_LOCK = threading.RLock()
_ACTIVE_PROCESS: subprocess.Popen[str] | None = None
_ACTIVE_PROVIDER = ""
_MACOS_DEFAULT_VOICE = "Yelda"


def _tts_root() -> Path:
    return state_store.CONFIG_DIR / "tts"


def _piper_binary() -> str:
    override = str(os.environ.get("ELYAN_PIPER_BINARY", "") or "").strip()
    if override:
        return override
    return shutil.which("piper") or ""


def _piper_model_path(voice: str = "") -> Path | None:
    candidate = str(os.environ.get("ELYAN_PIPER_MODEL_PATH", "") or "").strip()
    if voice.strip():
        voice_candidate = Path(voice.strip()).expanduser()
        if voice_candidate.exists() and voice_candidate.is_file():
            return voice_candidate.resolve()
    if not candidate:
        return None
    path = Path(candidate).expanduser()
    if path.exists() and path.is_file():
        return path.resolve()
    return None


def _say_available() -> bool:
    return sys.platform == "darwin" and bool(shutil.which("say"))


def _preferred_provider(voice: str = "") -> str:
    if _piper_binary() and _piper_model_path(voice) is not None:
        return "piper"
    if _say_available():
        return "say"
    return ""


def _stop_active_playback() -> None:
    global _ACTIVE_PROCESS, _ACTIVE_PROVIDER
    with _LOCK:
        process = _ACTIVE_PROCESS
        provider = _ACTIVE_PROVIDER
        _ACTIVE_PROCESS = None
        _ACTIVE_PROVIDER = ""
    if process is not None:
        try:
            process.terminate()
        except Exception:
            pass
    if provider == "winsound":
        try:
            import winsound

            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass


def _set_active_process(process: subprocess.Popen[str] | None, provider: str) -> None:
    global _ACTIVE_PROCESS, _ACTIVE_PROVIDER
    with _LOCK:
        _ACTIVE_PROCESS = process
        _ACTIVE_PROVIDER = provider


def _truncate_text(text: str, *, limit: int = 1200) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _macos_voice(language_hint: str, voice: str) -> str:
    requested = str(voice or "").strip()
    if requested:
        return requested
    if str(language_hint or "").lower().startswith("tr"):
        return _MACOS_DEFAULT_VOICE
    return "Samantha"


def _piper_playback_command(audio_path: Path) -> list[str]:
    if sys.platform == "darwin":
        player = shutil.which("afplay")
        if player:
            return [player, str(audio_path)]
    if os.name == "nt":
        return []
    player = shutil.which("aplay")
    if player:
        return [player, str(audio_path)]
    ffplay = shutil.which("ffplay")
    if ffplay:
        return [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", str(audio_path)]
    raise SafeCapabilityError("CAPABILITY_UNAVAILABLE", "Yerel ses oynatıcı bulunamadı.")


def _cleanup_old_audio_files() -> None:
    directory = _tts_root()
    if not directory.exists():
        return
    files = sorted(
        [path for path in directory.glob("*.wav") if path.is_file()],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for path in files[6:]:
        try:
            path.unlink()
        except OSError:
            pass


def _run_piper(text: str, language_hint: str, voice: str) -> str:
    del language_hint
    binary = _piper_binary()
    model_path = _piper_model_path(voice)
    if not binary or model_path is None:
        raise SafeCapabilityError("DEPENDENCY_UNAVAILABLE", "Piper TTS bu kurulumda hazır değil.")

    directory = _tts_root()
    directory.mkdir(parents=True, exist_ok=True)
    audio_path = directory / f"tts_{uuid.uuid4().hex[:10]}.wav"

    process = subprocess.Popen(
        [binary, "--model", str(model_path), "--output_file", str(audio_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    _set_active_process(process, "piper")
    try:
        process.communicate(text, timeout=120)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        raise SafeCapabilityError("TIMEOUT", "Yerel ses sentezi zaman aşımına uğradı.") from exc
    finally:
        _set_active_process(None, "")

    if process.returncode not in {0, None} or not audio_path.exists():
        raise SafeCapabilityError("CAPABILITY_UNAVAILABLE", "Yerel ses sentezi tamamlanamadı.")

    if os.name == "nt":
        try:
            import winsound

            _set_active_process(None, "winsound")
            winsound.PlaySound(str(audio_path), winsound.SND_FILENAME)
            _set_active_process(None, "")
        except Exception as exc:
            raise SafeCapabilityError("CAPABILITY_UNAVAILABLE", "Ses çıkışı başlatılamadı.") from exc
        finally:
            _cleanup_old_audio_files()
        return "piper"

    command = _piper_playback_command(audio_path)
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    _set_active_process(process, "piper")
    try:
        process.wait(timeout=120)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        raise SafeCapabilityError("TIMEOUT", "Ses oynatma zaman aşımına uğradı.") from exc
    finally:
        _set_active_process(None, "")
        _cleanup_old_audio_files()
    return "piper"


def _run_say(text: str, language_hint: str, voice: str) -> str:
    if not _say_available():
        raise SafeCapabilityError("DEPENDENCY_UNAVAILABLE", "Yerel ses okuma bu kurulumda hazır değil.")
    selected_voice = _macos_voice(language_hint, voice)
    process = subprocess.Popen(
        ["say", "-v", selected_voice, text],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    _set_active_process(process, "say")

    def _wait() -> None:
        try:
            process.wait(timeout=120)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        finally:
            _set_active_process(None, "")

    threading.Thread(target=_wait, daemon=True).start()
    return "say"


def text_to_speech(
    text: str,
    language_hint: str = "tr",
    voice: str = "",
    interrupt: bool = False,
) -> dict[str, Any]:
    payload = _truncate_text(text)
    if not payload:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Okunacak metin gerekli.")
    if interrupt:
        _stop_active_playback()

    provider = _preferred_provider(voice)
    if not provider:
        raise SafeCapabilityError("DEPENDENCY_UNAVAILABLE", "Yerel ses okuma bu kurulumda hazır değil.")

    if provider == "piper":
        def _speak() -> None:
            try:
                _run_piper(payload, language_hint, voice)
            except Exception:
                return

        threading.Thread(target=_speak, daemon=True).start()
        used_provider = "piper"
    else:
        used_provider = _run_say(payload, language_hint, voice)

    return {
        "text": "Sesli okuma başlatıldı.",
        "result": {
            "kind": "text_to_speech",
            "spoken": True,
            "provider": used_provider,
            "voice": voice.strip() or (_macos_voice(language_hint, voice) if used_provider == "say" else ""),
        },
        "artifacts": [],
    }


def speech_tts_status() -> dict[str, Any]:
    provider = _preferred_provider()
    return {
        "available": bool(provider),
        "provider": provider or "unavailable",
    }
