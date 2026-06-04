from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

from actions._read_only_common import workspace_root
from actions._write_common import artifact_payload, ensure_allowed_output_path, normalize_source_context
from runtime import state_store
from runtime.capability_registry import SafeCapabilityError

_DEFAULT_ENDPOINT = "https://api.openai.com/v1"
_DEFAULT_IMAGE_MODEL = "gpt-image-1"
_DEFAULT_SIZE = "1024x1024"
_ALLOWED_SIZES = {"1024x1024", "1024x1536", "1536x1024"}
_ALLOWED_QUALITIES = {"auto", "standard", "high"}
_ALLOWED_BACKGROUNDS = {"auto", "transparent", "opaque"}
_LAST_ERROR_CODE = ""
_LAST_ERROR_MESSAGE = ""


class _ProviderImageError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.code = str(code or "IMAGE_GENERATION_FAILED").strip() or "IMAGE_GENERATION_FAILED"
        self.message = str(message or "OpenAI image generation failed.").strip() or "OpenAI image generation failed."
        self.status_code = status_code


def _workspace_root() -> Path:
    return workspace_root()


def _set_last_error(code: str, message: str) -> None:
    global _LAST_ERROR_CODE, _LAST_ERROR_MESSAGE
    _LAST_ERROR_CODE = str(code or "").strip()
    _LAST_ERROR_MESSAGE = str(message or "").strip()


def _openai_sdk_module() -> Any | None:
    try:
        import openai  # type: ignore[reportMissingImports]
    except ModuleNotFoundError:
        return None
    return openai


def _sdk_version() -> str:
    module = _openai_sdk_module()
    return str(getattr(module, "__version__", "not-installed") or "not-installed")


def _requests_module() -> Any:
    import requests  # type: ignore[reportMissingImports]

    return requests


def _provider_settings() -> dict[str, str]:
    state = state_store.snapshot()
    providers = state.get("providers", {})
    providers = providers if isinstance(providers, dict) else {}
    openai = providers.get("openai", {})
    openai = openai if isinstance(openai, dict) else {}
    api_key = str(
        os.environ.get("OPENAI_API_KEY", "")
        or openai.get("apiKey", "")
        or ""
    ).strip()
    endpoint = str(
        os.environ.get("OPENAI_BASE_URL", "")
        or openai.get("baseUrl", "")
        or _DEFAULT_ENDPOINT
    ).strip().rstrip("/")
    image_model = str(os.environ.get("OPENAI_IMAGE_MODEL", "") or _DEFAULT_IMAGE_MODEL).strip() or _DEFAULT_IMAGE_MODEL
    return {
        "provider": "openai",
        "api_key": api_key,
        "endpoint": endpoint or _DEFAULT_ENDPOINT,
        "model": image_model,
    }


def _normalize_size(value: str) -> str:
    normalized = str(value or _DEFAULT_SIZE).strip().lower() or _DEFAULT_SIZE
    if normalized not in _ALLOWED_SIZES:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Geçersiz görsel boyutu.")
    return normalized


def _normalize_quality(value: str) -> str:
    normalized = str(value or "auto").strip().lower() or "auto"
    if normalized not in _ALLOWED_QUALITIES:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Geçersiz görsel kalite seçimi.")
    return normalized


def _normalize_background(value: str) -> str:
    normalized = str(value or "auto").strip().lower() or "auto"
    if normalized not in _ALLOWED_BACKGROUNDS:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Geçersiz görsel arka plan seçimi.")
    return normalized


def _log_provider_event(
    *,
    provider: str,
    endpoint: str,
    sdk_version: str,
    model: str,
    raw_error_code: str,
    status_code: int | None = None,
    event: str,
) -> None:
    payload = {
        "event": event,
        "provider": provider,
        "endpoint": endpoint,
        "sdkVersion": sdk_version,
        "model": model,
        "rawErrorCode": raw_error_code,
    }
    if status_code is not None:
        payload["statusCode"] = int(status_code)
    print(f"image_generate {json.dumps(payload, ensure_ascii=False)}", file=sys.stderr)


def _should_fallback_to_default_model(model: str, error_code: str, message: str) -> bool:
    if str(model or "").strip() == _DEFAULT_IMAGE_MODEL:
        return False
    normalized_code = str(error_code or "").strip().lower()
    normalized_message = str(message or "").strip().lower()
    if normalized_code in {"invalid_value", "model_not_found", "unsupported_model"}:
        return True
    return "does not exist" in normalized_message or "not found" in normalized_message or "unsupported" in normalized_message


def _first_data_item(payload: Any) -> Any:
    data = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(data, list) or not data:
        raise _ProviderImageError("INVALID_RESPONSE", "Görsel üretim yanıtı veri içermiyor.")
    return data[0]


def _item_value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _download_image_bytes(url: str) -> bytes:
    requests = _requests_module()
    try:
        response = requests.get(url, timeout=90)
    except requests.RequestException as exc:
        raise _ProviderImageError("NETWORK_ERROR", "Üretilen görsel indirilemedi.") from exc
    if not response.ok:
        raise _ProviderImageError("IMAGE_DOWNLOAD_FAILED", "Üretilen görsel indirilemedi.", response.status_code)
    return bytes(response.content or b"")


def _decode_image_item(item: Any) -> tuple[bytes, str]:
    b64_json = _item_value(item, "b64_json")
    if isinstance(b64_json, str) and b64_json.strip():
        try:
            return base64.b64decode(b64_json), "b64_json"
        except Exception as exc:
            raise _ProviderImageError("INVALID_RESPONSE", "Görsel verisi çözümlenemedi.") from exc
    url = str(_item_value(item, "url") or "").strip()
    if url:
        return _download_image_bytes(url), "url"
    raise _ProviderImageError("INVALID_RESPONSE", "Görsel üretim yanıtı desteklenen çıktı formatını döndürmedi.")


def _extract_http_error(response: Any) -> tuple[str, str, int | None]:
    status_code = getattr(response, "status_code", None)
    try:
        payload = response.json()
    except Exception:
        payload = {}
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    if isinstance(error, dict):
        code = str(error.get("code", "") or error.get("type", "") or "IMAGE_GENERATION_FAILED")
        message = str(error.get("message", "") or "").strip()
        if message:
            return code, message, status_code
    text = str(getattr(response, "text", "") or "").strip()
    if text:
        return "IMAGE_GENERATION_FAILED", text[:400], status_code
    return "IMAGE_GENERATION_FAILED", "Görsel üretimi sağlayıcısı isteği reddetti.", status_code


def _generate_image_bytes_http(
    *,
    prompt: str,
    api_key: str,
    endpoint: str,
    model: str,
    size: str,
    quality: str,
    background: str,
) -> tuple[bytes, dict[str, Any]]:
    requests = _requests_module()
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "response_format": "b64_json",
    }
    if quality != "auto":
        payload["quality"] = quality
    if background != "auto":
        payload["background"] = background
    try:
        response = requests.post(
            f"{endpoint}/images/generations",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=90,
        )
    except requests.RequestException as exc:
        raise _ProviderImageError("NETWORK_ERROR", "OpenAI görsel servisine bağlanılamadı.") from exc
    if not response.ok:
        code, message, status_code = _extract_http_error(response)
        raise _ProviderImageError(code, message, status_code)
    response_payload = response.json() if response.content else {}
    item = _first_data_item(response_payload)
    image_bytes, source = _decode_image_item(item)
    return image_bytes, {"source": source}


def _generate_image_bytes_sdk(
    *,
    prompt: str,
    api_key: str,
    endpoint: str,
    model: str,
    size: str,
    quality: str,
    background: str,
) -> tuple[bytes, dict[str, Any]] | None:
    openai = _openai_sdk_module()
    if openai is None:
        return None
    client = openai.OpenAI(api_key=api_key, base_url=endpoint)
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "size": size,
    }
    if quality != "auto":
        payload["quality"] = quality
    if background != "auto":
        payload["background"] = background
    try:
        response = client.images.generate(**payload)
    except Exception as exc:
        code = str(getattr(exc, "code", "") or getattr(exc, "type", "") or "IMAGE_GENERATION_FAILED")
        status_code = getattr(exc, "status_code", None)
        message = str(exc or "OpenAI image generation failed.").strip() or "OpenAI image generation failed."
        raise _ProviderImageError(code, message, status_code) from exc
    item = _first_data_item(response.model_dump() if hasattr(response, "model_dump") else response)
    image_bytes, source = _decode_image_item(item)
    return image_bytes, {"source": source}


def _generate_image_bytes(
    *,
    prompt: str,
    api_key: str,
    endpoint: str,
    model: str,
    size: str,
    quality: str,
    background: str,
) -> tuple[bytes, dict[str, Any]]:
    sdk_result = _generate_image_bytes_sdk(
        prompt=prompt,
        api_key=api_key,
        endpoint=endpoint,
        model=model,
        size=size,
        quality=quality,
        background=background,
    )
    if sdk_result is not None:
        return sdk_result
    return _generate_image_bytes_http(
        prompt=prompt,
        api_key=api_key,
        endpoint=endpoint,
        model=model,
        size=size,
        quality=quality,
        background=background,
    )


def image_generate_status() -> dict[str, Any]:
    settings = _provider_settings()
    api_key = settings["api_key"]
    if not api_key:
        return {
            "available": False,
            "lastErrorCode": "PROVIDER_NOT_CONFIGURED",
            "lastErrorMessage": "OpenAI image generation için API anahtarı gerekli.",
            "provider": settings["provider"],
            "endpoint": settings["endpoint"],
            "model": settings["model"],
            "sdkVersion": _sdk_version(),
        }
    return {
        "available": True,
        "lastErrorCode": _LAST_ERROR_CODE,
        "lastErrorMessage": _LAST_ERROR_MESSAGE,
        "provider": settings["provider"],
        "endpoint": settings["endpoint"],
        "model": settings["model"],
        "sdkVersion": _sdk_version(),
    }


def image_generate(
    prompt: str,
    outputPath: str = "",
    title: str = "",
    size: str = _DEFAULT_SIZE,
    quality: str = "auto",
    background: str = "auto",
    overwrite: bool = False,
) -> dict[str, Any]:
    prompt_text = " ".join(str(prompt or "").split()).strip()
    if not prompt_text:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Görsel üretmek için açıklama gerekli.")

    settings = _provider_settings()
    if not settings["api_key"]:
        _set_last_error("PROVIDER_NOT_CONFIGURED", "OpenAI API anahtarı eksik.")
        raise SafeCapabilityError("PROVIDER_NOT_CONFIGURED", "OpenAI image generation için API anahtarı gerekli.")

    normalized_size = _normalize_size(size)
    normalized_quality = _normalize_quality(quality)
    normalized_background = _normalize_background(background)
    sdk_version = _sdk_version()
    output_path = ensure_allowed_output_path(
        outputPath,
        extension=".png",
        overwrite=overwrite,
        hint=title or prompt_text[:48],
        root_resolver=_workspace_root,
    )

    candidate_models = [settings["model"]]
    if settings["model"] != _DEFAULT_IMAGE_MODEL:
        candidate_models.append(_DEFAULT_IMAGE_MODEL)

    last_error: _ProviderImageError | None = None
    for candidate_model in candidate_models:
        try:
            image_bytes, metadata = _generate_image_bytes(
                prompt=prompt_text,
                api_key=settings["api_key"],
                endpoint=settings["endpoint"],
                model=candidate_model,
                size=normalized_size,
                quality=normalized_quality,
                background=normalized_background,
            )
            output_path.write_bytes(image_bytes)
            _set_last_error("", "")
            _log_provider_event(
                provider=settings["provider"],
                endpoint=settings["endpoint"],
                sdk_version=sdk_version,
                model=candidate_model,
                raw_error_code="",
                event="success",
            )
            return {
                "text": f"Görsel üretildi.\n{output_path.name}",
                "result": {
                    "kind": "image_generate",
                    "provider": settings["provider"],
                    "endpoint": settings["endpoint"],
                    "sdkVersion": sdk_version,
                    "model": candidate_model,
                    "source": metadata.get("source", "unknown"),
                    "outputPath": str(output_path),
                    "size": normalized_size,
                    "quality": normalized_quality,
                    "background": normalized_background,
                    "promptPreview": normalize_source_context(prompt_text, max_chars=220),
                    "title": str(title or "").strip(),
                },
                "artifacts": [artifact_payload(output_path)],
            }
        except _ProviderImageError as exc:
            last_error = exc
            _set_last_error(exc.code, exc.message)
            _log_provider_event(
                provider=settings["provider"],
                endpoint=settings["endpoint"],
                sdk_version=sdk_version,
                model=candidate_model,
                raw_error_code=exc.code,
                status_code=exc.status_code,
                event="error",
            )
            if _should_fallback_to_default_model(candidate_model, exc.code, exc.message):
                continue
            break

    raise SafeCapabilityError(
        last_error.code if last_error else "IMAGE_GENERATION_FAILED",
        "Görsel üretimi şu anda tamamlanamadı. Lütfen model ayarlarını kontrol edip tekrar dene.",
    )
