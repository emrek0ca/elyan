from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from actions._read_only_common import ensure_allowed_path, is_explicit_path_value, workspace_root
from runtime import state_store
from runtime.capability_registry import SafeCapabilityError

_SAMPLE_RATE = 16_000
_CHANNELS = 1
_MAX_DURATION_SECONDS = 45
_DEFAULT_LANGUAGE = "tr"
_DEFAULT_MODEL = "base"
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_OPENAI_BASE_URL = "https://api.openai.com/v1"
_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".mp4", ".mpeg", ".webm"}
_MAX_CAPTURE_HISTORY = 12


def _speech_root() -> Path:
    return state_store.CONFIG_DIR / "speech"


def _capture_dir() -> Path:
    return _speech_root() / "captures"


def _workspace_root() -> Path:
    return workspace_root()


def _config_root() -> Path:
    return state_store.CONFIG_DIR.resolve()


def _is_under_config_root(path: Path) -> bool:
    try:
        path.resolve().relative_to(_config_root())
        return True
    except Exception:
        return False


def _sounddevice_module() -> Any:
    import sounddevice  # type: ignore[reportMissingImports]

    return sounddevice


def _soundfile_module() -> Any:
    import soundfile  # type: ignore[reportMissingImports]

    return soundfile


def _stt_model_name() -> str:
    return str(os.environ.get("ELYAN_FASTER_WHISPER_MODEL", _DEFAULT_MODEL) or _DEFAULT_MODEL)


def _cloud_speech_enabled(explicit: bool = False) -> bool:
    value = str(os.environ.get("ELYAN_CLOUD_SPEECH_ENABLED", "") or "").strip().lower()
    return explicit or value in {"1", "true", "yes", "on"}


def _provider_family(provider: str) -> str:
    normalized = str(provider or "local").strip().lower().replace("_", "-")
    if normalized in {"groq", "groq-fast", "groq-accurate"}:
        return "groq"
    if normalized in {"openai", "openai-diarize", "diarize"}:
        return "openai"
    return "local"


def _cloud_model(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized == "groq-accurate":
        return str(os.environ.get("GROQ_TRANSCRIBE_ACCURATE_MODEL", "whisper-large-v3") or "whisper-large-v3")
    if normalized.startswith("groq"):
        return str(os.environ.get("GROQ_TRANSCRIBE_FAST_MODEL", "whisper-large-v3-turbo") or "whisper-large-v3-turbo")
    if normalized in {"openai-diarize", "diarize"}:
        return str(os.environ.get("OPENAI_TRANSCRIBE_DIARIZE_MODEL", "gpt-4o-transcribe-diarize") or "gpt-4o-transcribe-diarize")
    return str(os.environ.get("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-transcribe") or "gpt-4o-transcribe")


def _cloud_base_url(provider_family: str) -> str:
    if provider_family == "groq":
        return str(os.environ.get("GROQ_BASE_URL", _GROQ_BASE_URL) or _GROQ_BASE_URL).rstrip("/")
    return str(os.environ.get("OPENAI_BASE_URL", _OPENAI_BASE_URL) or _OPENAI_BASE_URL).rstrip("/")


def _cloud_api_key(provider_family: str) -> str:
    name = "GROQ_API_KEY" if provider_family == "groq" else "OPENAI_API_KEY"
    return str(os.environ.get(name, "") or "").split(",")[0].strip()


@lru_cache(maxsize=1)
def _whisper_model() -> Any:
    from faster_whisper import WhisperModel  # type: ignore[reportMissingImports]

    model_name = _stt_model_name()
    device = str(os.environ.get("ELYAN_FASTER_WHISPER_DEVICE", "cpu") or "cpu")
    compute_type = str(os.environ.get("ELYAN_FASTER_WHISPER_COMPUTE_TYPE", "int8") or "int8")
    return WhisperModel(model_name, device=device, compute_type=compute_type)


@dataclass
class _CaptureState:
    session_id: str
    audio_path: Path
    writer: Any
    stream: Any
    started_at: float
    max_duration_hit: bool = False


_LOCK = threading.RLock()
_ACTIVE_CAPTURE: _CaptureState | None = None
_CAPTURE_HISTORY: dict[str, dict[str, Any]] = {}
_LAST_ERROR_CODE = ""


def _set_last_error(code: str) -> None:
    global _LAST_ERROR_CODE
    _LAST_ERROR_CODE = str(code or "").strip()


def _capture_dependencies_available() -> bool:
    return find_spec("sounddevice") is not None and find_spec("soundfile") is not None


def _stt_dependencies_available() -> bool:
    return find_spec("faster_whisper") is not None


def _record_capture_history(session_id: str, audio_path: Path, duration_ms: int) -> None:
    _CAPTURE_HISTORY[session_id] = {
        "audioPath": str(audio_path),
        "durationMs": int(duration_ms),
        "updatedAt": time.time(),
    }
    ordered = sorted(
        _CAPTURE_HISTORY.items(),
        key=lambda item: float(item[1].get("updatedAt", 0.0) or 0.0),
        reverse=True,
    )
    keep = ordered[:_MAX_CAPTURE_HISTORY]
    keep_ids = {item[0] for item in keep}
    for session_key, metadata in ordered[_MAX_CAPTURE_HISTORY:]:
        path = Path(str(metadata.get("audioPath", "") or ""))
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
        _CAPTURE_HISTORY.pop(session_key, None)
    for path in _capture_dir().glob("*.wav"):
        if path.stem not in keep_ids and (_ACTIVE_CAPTURE is None or path != _ACTIVE_CAPTURE.audio_path):
            try:
                path.unlink()
            except OSError:
                pass


def _capture_payload(session_id: str, status: str, audio_path: str, duration_ms: int) -> dict[str, Any]:
    return {
        "kind": "speech_capture",
        "sessionId": session_id,
        "status": status,
        "audioPath": audio_path,
        "durationMs": int(max(0, duration_ms)),
    }


def _capture_status_payload() -> dict[str, Any]:
    with _LOCK:
        capture = _ACTIVE_CAPTURE
        if capture is None:
            return _capture_payload("", "idle", "", 0)
        duration_ms = int((time.perf_counter() - capture.started_at) * 1000)
        return _capture_payload(capture.session_id, "recording", str(capture.audio_path), duration_ms)


def _close_capture(capture: _CaptureState | None, *, delete_audio: bool) -> tuple[str, str, int]:
    if capture is None:
        raise SafeCapabilityError("NO_ACTIVE_CAPTURE", "Aktif bir ses kaydı yok.")

    try:
        capture.stream.stop()
    except Exception:
        pass
    try:
        capture.stream.close()
    except Exception:
        pass
    try:
        capture.writer.close()
    except Exception:
        pass

    duration_ms = int((time.perf_counter() - capture.started_at) * 1000)
    duration_ms = max(0, min(duration_ms, _MAX_DURATION_SECONDS * 1000))
    if delete_audio:
        try:
            if capture.audio_path.exists():
                capture.audio_path.unlink()
        except OSError:
            pass
        _CAPTURE_HISTORY.pop(capture.session_id, None)
        return capture.session_id, "", duration_ms

    _record_capture_history(capture.session_id, capture.audio_path, duration_ms)
    return capture.session_id, str(capture.audio_path), duration_ms


def _start_capture() -> dict[str, Any]:
    sd = _sounddevice_module()
    sf = _soundfile_module()

    capture_dir = _capture_dir()
    capture_dir.mkdir(parents=True, exist_ok=True)
    session_id = f"speech_{uuid.uuid4().hex[:10]}"
    audio_path = capture_dir / f"{session_id}.wav"
    writer = sf.SoundFile(
        str(audio_path),
        mode="w",
        samplerate=_SAMPLE_RATE,
        channels=_CHANNELS,
        subtype="PCM_16",
    )

    state = _CaptureState(
        session_id=session_id,
        audio_path=audio_path,
        writer=writer,
        stream=None,
        started_at=time.perf_counter(),
    )

    def callback(indata: Any, _frames: int, _time_info: Any, _status: Any) -> None:
        try:
            state.writer.write(indata.copy())
        except Exception:
            raise sd.CallbackStop()
        if time.perf_counter() - state.started_at >= _MAX_DURATION_SECONDS:
            state.max_duration_hit = True
            raise sd.CallbackStop()

    try:
        stream = sd.InputStream(
            samplerate=_SAMPLE_RATE,
            channels=_CHANNELS,
            dtype="float32",
            callback=callback,
        )
        state.stream = stream
        stream.start()
    except Exception as exc:
        try:
            writer.close()
        except Exception:
            pass
        try:
            if audio_path.exists():
                audio_path.unlink()
        except OSError:
            pass
        _set_last_error("MICROPHONE_UNAVAILABLE")
        raise SafeCapabilityError("MICROPHONE_UNAVAILABLE", "Mikrofon erişimi başlatılamadı.") from exc

    with _LOCK:
        global _ACTIVE_CAPTURE
        if _ACTIVE_CAPTURE is not None:
            try:
                _close_capture(_ACTIVE_CAPTURE, delete_audio=True)
            except Exception:
                pass
        _ACTIVE_CAPTURE = state
        _set_last_error("")
    return {
        "text": "Ses kaydı başladı.",
        "result": _capture_payload(session_id, "recording", str(audio_path), 0),
        "artifacts": [],
    }


def speech_capture(action: str, _uiGesture: bool = False) -> dict[str, Any]:
    global _ACTIVE_CAPTURE
    normalized = str(action or "status").strip().lower() or "status"
    if normalized == "status":
        payload = _capture_status_payload()
        return {"text": "Ses kaydı durumu hazır.", "result": payload, "artifacts": []}
    if normalized == "start":
        return _start_capture()
    if normalized == "stop":
        with _LOCK:
            capture = _ACTIVE_CAPTURE
            _ACTIVE_CAPTURE = None
        session_id, audio_path, duration_ms = _close_capture(capture, delete_audio=False)
        return {
            "text": "Ses kaydı tamamlandı.",
            "result": _capture_payload(session_id, "completed", audio_path, duration_ms),
            "artifacts": [],
        }
    if normalized == "cancel":
        with _LOCK:
            capture = _ACTIVE_CAPTURE
            _ACTIVE_CAPTURE = None
        session_id, _audio_path, duration_ms = _close_capture(capture, delete_audio=True)
        return {
            "text": "Ses kaydı iptal edildi.",
            "result": _capture_payload(session_id, "cancelled", "", duration_ms),
            "artifacts": [],
        }
    raise SafeCapabilityError("INVALID_ARGUMENT", "Geçersiz ses kaydı işlemi.")


def _session_audio_path(session_id: str) -> Path:
    normalized = str(session_id or "").strip()
    if not normalized:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Ses kaydı oturumu gerekli.")
    with _LOCK:
        metadata = _CAPTURE_HISTORY.get(normalized)
    if not isinstance(metadata, dict):
        raise SafeCapabilityError("FILE_NOT_FOUND", "Ses kaydı bulunamadı.")
    path = Path(str(metadata.get("audioPath", "") or ""))
    if not path.exists():
        raise SafeCapabilityError("FILE_NOT_FOUND", "Ses kaydı bulunamadı.")
    return path


def _resolve_audio_path(audio_path: str, session_id: str) -> Path:
    if str(session_id or "").strip():
        return _session_audio_path(session_id)
    try:
        return ensure_allowed_path(
            audio_path,
            allowed_suffixes=_AUDIO_SUFFIXES,
            root_resolver=_workspace_root,
        )
    except Exception as exc:
        if str(getattr(exc, "code", "") or "") != "ACCESS_DENIED":
            raise
        if not is_explicit_path_value(audio_path):
            raise
        candidate = Path(str(audio_path or "").strip()).expanduser().resolve()
        if not candidate.exists() or not candidate.is_file():
            raise SafeCapabilityError("FILE_NOT_FOUND", "İstenen dosya bulunamadı.") from exc
        if candidate.suffix.lower() not in _AUDIO_SUFFIXES:
            raise SafeCapabilityError("UNSUPPORTED_FORMAT", "Bu dosya türü bu özellik için desteklenmiyor.") from exc
        if not _is_under_config_root(candidate):
            raise SafeCapabilityError("ACCESS_DENIED", "Dosya yalnızca seçilmiş hedef veya izinli çalışma alanı içinden okunabilir.") from exc
        return candidate


def _transcribe_audio(path: Path, language_hint: str) -> tuple[str, str, int, list[dict[str, Any]]]:
    try:
        model = _whisper_model()
    except ModuleNotFoundError as exc:
        raise SafeCapabilityError("DEPENDENCY_UNAVAILABLE", "Bu özellik bu kurulumda hazır değil.") from exc
    segments, info = model.transcribe(
        str(path),
        language=(str(language_hint or "").strip() or None),
        vad_filter=True,
    )
    chunk_list: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for segment in segments:
        segment_text = str(getattr(segment, "text", "") or "").strip()
        if not segment_text:
            continue
        text_parts.append(segment_text)
        chunk_list.append(
            {
                "start": round(float(getattr(segment, "start", 0.0) or 0.0), 2),
                "end": round(float(getattr(segment, "end", 0.0) or 0.0), 2),
                "text": segment_text,
            }
        )
    transcript = " ".join(part for part in text_parts if part).strip()
    if not transcript:
        raise SafeCapabilityError("EMPTY_TRANSCRIPT", "Ses kaydından metin çıkarılamadı.")
    duration_ms = int(round(float(getattr(info, "duration", 0.0) or 0.0) * 1000))
    detected_language = str(getattr(info, "language", "") or language_hint or _DEFAULT_LANGUAGE)
    return transcript, detected_language, duration_ms, chunk_list


def _normalize_cloud_segments(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    segments: list[dict[str, Any]] = []
    speakers: list[dict[str, Any]] = []
    raw_segments = payload.get("segments")
    if isinstance(raw_segments, list):
        for item in raw_segments:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "") or "").strip()
            if not text:
                continue
            segment = {
                "start": round(float(item.get("start", 0.0) or 0.0), 2),
                "end": round(float(item.get("end", 0.0) or 0.0), 2),
                "text": text,
            }
            speaker = str(item.get("speaker", "") or item.get("speaker_label", "") or "").strip()
            if speaker:
                segment["speaker"] = speaker
                speakers.append({"id": speaker, "label": speaker})
            segments.append(segment)
    return segments, list({str(item["id"]): item for item in speakers}.values())


def _transcribe_cloud(path: Path, provider: str, language_hint: str) -> tuple[str, str, int, list[dict[str, Any]], list[dict[str, Any]], str]:
    family = _provider_family(provider)
    api_key = _cloud_api_key(family)
    if not api_key:
        raise SafeCapabilityError("CLOUD_SPEECH_UNAVAILABLE", "Bulut transkripsiyon anahtarı yapılandırılmamış.")
    try:
        import requests
    except ModuleNotFoundError as exc:
        raise SafeCapabilityError("DEPENDENCY_UNAVAILABLE", "Bulut transkripsiyon istemcisi hazır değil.") from exc
    model = _cloud_model(provider)
    data = {
        "model": model,
        "response_format": "verbose_json",
    }
    language = str(language_hint or "").strip()
    if language:
        data["language"] = language.split("_")[0].split("-")[0]
    if model == "gpt-4o-transcribe-diarize":
        data["chunking_strategy"] = "auto"
    with path.open("rb") as handle:
        response = requests.post(
            f"{_cloud_base_url(family)}/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            data=data,
            files={"file": (path.name, handle)},
            timeout=120,
        )
    if response.status_code >= 400:
        raise SafeCapabilityError("CLOUD_TRANSCRIPTION_FAILED", "Bulut transkripsiyon tamamlanamadı.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise SafeCapabilityError("CLOUD_TRANSCRIPTION_FAILED", "Bulut transkripsiyon yanıtı okunamadı.") from exc
    transcript = str(payload.get("text", "") or "").strip()
    if not transcript:
        raise SafeCapabilityError("EMPTY_TRANSCRIPT", "Ses kaydından metin çıkarılamadı.")
    segments, speakers = _normalize_cloud_segments(payload)
    duration_ms = int(round(float(payload.get("duration", 0.0) or 0.0) * 1000))
    detected_language = str(payload.get("language", "") or language_hint or _DEFAULT_LANGUAGE)
    return transcript, detected_language, duration_ms, segments, speakers, model


def speech_to_text(
    audio_path: str = "",
    session_id: str = "",
    language_hint: str = _DEFAULT_LANGUAGE,
    task_id: str = "",
    provider: str = "local",
    cloud_allowed: bool = False,
    _selectedPaths: list[str] | None = None,
) -> dict[str, Any]:
    del task_id
    provider_family = _provider_family(provider)
    if provider_family == "local" and not _stt_dependencies_available():
        _set_last_error("DEPENDENCY_UNAVAILABLE")
        raise SafeCapabilityError("DEPENDENCY_UNAVAILABLE", "Bu özellik bu kurulumda hazır değil.")
    if str(session_id or "").strip():
        resolved = _resolve_audio_path(audio_path, session_id)
    else:
        try:
            resolved = ensure_allowed_path(
                audio_path,
                allowed_suffixes=_AUDIO_SUFFIXES,
                selected_paths=_selectedPaths,
                root_resolver=_workspace_root,
            )
        except Exception as exc:
            if str(getattr(exc, "code", "") or "") != "ACCESS_DENIED" or not is_explicit_path_value(audio_path):
                raise
            candidate = Path(str(audio_path or "").strip()).expanduser().resolve()
            if not candidate.exists() or not candidate.is_file():
                raise SafeCapabilityError("FILE_NOT_FOUND", "İstenen dosya bulunamadı.") from exc
            if candidate.suffix.lower() not in _AUDIO_SUFFIXES:
                raise SafeCapabilityError("UNSUPPORTED_FORMAT", "Bu dosya türü bu özellik için desteklenmiyor.") from exc
            if not _is_under_config_root(candidate):
                raise SafeCapabilityError("ACCESS_DENIED", "Dosya yalnızca seçilmiş hedef veya izinli çalışma alanı içinden okunabilir.") from exc
            resolved = candidate
    try:
        if provider_family == "local":
            transcript, detected_language, duration_ms, segments = _transcribe_audio(
                resolved,
                str(language_hint or _DEFAULT_LANGUAGE).strip() or _DEFAULT_LANGUAGE,
            )
            speakers: list[dict[str, Any]] = []
            model_name = _stt_model_name()
        else:
            if not _cloud_speech_enabled(cloud_allowed):
                raise SafeCapabilityError("CLOUD_SPEECH_PERMISSION_REQUIRED", "Bulut transkripsiyon için açık izin gerekli.")
            transcript, detected_language, duration_ms, segments, speakers, model_name = _transcribe_cloud(
                resolved,
                provider,
                str(language_hint or _DEFAULT_LANGUAGE).strip() or _DEFAULT_LANGUAGE,
            )
    except Exception as exc:
        code = str(getattr(exc, "code", "") or "").strip()
        if code:
            _set_last_error(code)
        elif isinstance(exc, ModuleNotFoundError):
            _set_last_error("DEPENDENCY_UNAVAILABLE")
        else:
            _set_last_error("TRANSCRIPTION_FAILED")
        raise
    _set_last_error("")
    return {
        "text": transcript,
        "result": {
            "kind": "speech_to_text",
            "text": transcript,
            "language": detected_language,
            "durationMs": duration_ms,
            "segments": segments,
            "speakers": speakers,
            "audioPath": str(resolved),
            "sessionId": str(session_id or "").strip(),
            "providerFamily": provider_family,
            "model": model_name,
            "artifacts": [],
        },
        "artifacts": [],
    }


def speech_runtime_status() -> dict[str, Any]:
    capture = _capture_status_payload()
    return {
        "available": _capture_dependencies_available() or _stt_dependencies_available(),
        "recording": capture["status"] == "recording",
        "captureSessionId": capture["sessionId"],
        "transcriptionModel": _stt_model_name(),
        "cloudTranscriptionAvailable": bool(_cloud_api_key("groq") or _cloud_api_key("openai")),
        "ttsProvider": "",
        "lastErrorCode": _LAST_ERROR_CODE,
    }
