from __future__ import annotations

import base64
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

from actions._read_only_common import content_type_for, ensure_allowed_path, workspace_root
from actions._write_common import artifact_payload, ensure_allowed_output_path, normalize_source_context
from app_config import get_app_config_value
from runtime import state_store
from runtime.capability_registry import SafeCapabilityError

DEFAULT_GENERATE_MODEL = "gemini-3.1-flash-image-preview"
DEFAULT_EDIT_MODEL = "gemini-3-pro-image-preview"
DEFAULT_IMAGE_SIZE = "2K"
ALLOWED_ASPECT_RATIOS = {
    "1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1", "4:3",
    "4:5", "5:4", "8:1", "9:16", "16:9", "21:9",
}
ALLOWED_IMAGE_SIZES = {"1K", "2K", "4K"}
EDITABLE_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"}
MAX_SOURCE_IMAGE_BYTES = 12 * 1024 * 1024
MAX_SOURCE_IMAGES = 4

_LAST_ERROR_CODE = ""
_LAST_ERROR_MESSAGE = ""


class GeminiImageError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.code = str(code or "IMAGE_PROVIDER_ERROR").strip() or "IMAGE_PROVIDER_ERROR"
        self.message = str(message or "Görsel üretim isteği tamamlanamadı.").strip()
        self.status_code = status_code


def _workspace_root() -> Path:
    return workspace_root()


def _google_sdk() -> Any | None:
    try:
        from google import genai  # type: ignore[reportMissingImports]
    except (ImportError, ModuleNotFoundError):
        return None
    return genai


def sdk_version() -> str:
    try:
        import google.genai  # type: ignore[reportMissingImports]
    except (ImportError, ModuleNotFoundError):
        return "not-installed"
    return str(getattr(google.genai, "__version__", "unknown") or "unknown")


def _set_last_error(code: str, message: str) -> None:
    global _LAST_ERROR_CODE, _LAST_ERROR_MESSAGE
    _LAST_ERROR_CODE = str(code or "").strip()
    _LAST_ERROR_MESSAGE = _public_image_error_message(code, message)


def _public_image_error_message(code: str, message: str = "") -> str:
    normalized = str(code or "").strip()
    if not normalized and not str(message or "").strip():
        return ""
    if normalized == "PROVIDER_NOT_CONFIGURED":
        return "Görsel üretim ayarı eksik."
    if normalized == "DEPENDENCY_UNAVAILABLE":
        return "Görsel üretim altyapısı bu kurulumda hazır değil."
    if normalized == "PROVIDER_AUTH_FAILED":
        return "Görsel üretim ayarı geçersiz veya yetkisiz."
    if normalized == "PROVIDER_RATE_LIMITED":
        return "Görsel üretim kotası veya hız limiti doldu. Biraz bekleyip tekrar dene."
    if normalized == "PROVIDER_TIMEOUT":
        return "Görsel üretim isteği zaman aşımına uğradı. Biraz sonra tekrar dene."
    if normalized in {"INVALID_RESPONSE", "IMAGE_PROVIDER_ERROR"}:
        return "Görsel üretim işlemi şu anda tamamlanamadı. Lütfen biraz sonra tekrar dene."
    text = str(message or "").strip()
    if any(token in text.casefold() for token in ("gemini", "google", "genai", "model", "provider")):
        return "Görsel üretim işlemi şu anda tamamlanamadı. Lütfen biraz sonra tekrar dene."
    return text or "Görsel üretim işlemi şu anda tamamlanamadı. Lütfen biraz sonra tekrar dene."


def provider_settings(*, editing: bool) -> dict[str, str]:
    volatile = state_store.volatile_provider_secrets()
    api_key = str(
        os.environ.get("GEMINI_API_KEY", "")
        or os.environ.get("ELYAN_GOOGLE_API_KEY", "")
        or volatile.get("gemini", "")
        or get_app_config_value("gemini_api_key", "")
        or ""
    ).strip()
    default_model = DEFAULT_EDIT_MODEL if editing else DEFAULT_GENERATE_MODEL
    model_env = "ELYAN_GEMINI_IMAGE_EDIT_MODEL" if editing else "ELYAN_GEMINI_IMAGE_MODEL"
    model = str(os.environ.get(model_env, "") or default_model).strip() or default_model
    return {"provider": "gemini", "api_key": api_key, "model": model}


def image_status(*, editing: bool) -> dict[str, Any]:
    settings = provider_settings(editing=editing)
    available = bool(settings["api_key"] and _google_sdk() is not None)
    if not settings["api_key"]:
        code = "PROVIDER_NOT_CONFIGURED"
        message = "Görsel üretim ayarı eksik."
    elif _google_sdk() is None:
        code = "DEPENDENCY_UNAVAILABLE"
        message = "Görsel üretim altyapısı bu kurulumda hazır değil."
    else:
        code = _LAST_ERROR_CODE
        message = _LAST_ERROR_MESSAGE
    return {
        "available": available,
        "lastErrorCode": code,
        "lastErrorMessage": message,
    }


def normalize_aspect_ratio(value: str, *, legacy_size: str = "", allow_empty: bool = False) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        if allow_empty and not str(legacy_size or "").strip():
            return ""
        normalized = {
            "1024x1024": "1:1",
            "1024x1536": "2:3",
            "1536x1024": "3:2",
        }.get(str(legacy_size or "").strip().lower(), "1:1")
    if normalized not in ALLOWED_ASPECT_RATIOS:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Geçersiz görsel en-boy oranı.")
    return normalized


def normalize_image_size(value: str, *, legacy_quality: str = "") -> str:
    normalized = str(value or "").strip().upper()
    if not normalized:
        normalized = "4K" if str(legacy_quality or "").strip().lower() == "high" else DEFAULT_IMAGE_SIZE
    if normalized not in ALLOWED_IMAGE_SIZES:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Geçersiz görsel çözünürlüğü.")
    return normalized


def resolve_source_paths(
    source_path: str,
    source_paths: list[str] | None,
    selected_paths: list[str] | None,
) -> list[Path]:
    raw_items = [str(item or "").strip() for item in (source_paths or []) if str(item or "").strip()]
    primary = str(source_path or "").strip()
    if primary and primary not in raw_items:
        raw_items.insert(0, primary)
    if not raw_items:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Düzenlenecek görsel gerekli.")
    if len(raw_items) > MAX_SOURCE_IMAGES:
        raise SafeCapabilityError("INVALID_ARGUMENT", f"En fazla {MAX_SOURCE_IMAGES} kaynak görsel kullanılabilir.")

    resolved: list[Path] = []
    total_bytes = 0
    for item in raw_items:
        path = ensure_allowed_path(
            item,
            allowed_suffixes=EDITABLE_IMAGE_SUFFIXES,
            selected_paths=selected_paths,
            root_resolver=_workspace_root,
        )
        size = path.stat().st_size
        total_bytes += size
        if size <= 0:
            raise SafeCapabilityError("INVALID_ARGUMENT", "Kaynak görsel boş.")
        if total_bytes > MAX_SOURCE_IMAGE_BYTES:
            raise SafeCapabilityError("FILE_TOO_LARGE", "Kaynak görsellerin toplam boyutu 12 MB sınırını aşıyor.")
        resolved.append(path)
    return resolved


def _source_mime_type(path: Path) -> str:
    mime_type = content_type_for(path)
    if mime_type == "image/jpg":
        return "image/jpeg"
    if mime_type not in {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}:
        raise SafeCapabilityError("UNSUPPORTED_IMAGE_FORMAT", "Bu görsel formatı düzenleme için desteklenmiyor.")
    return mime_type


def _response_image(response: Any) -> tuple[bytes, str]:
    output_image = getattr(response, "output_image", None)
    if output_image is None and isinstance(response, dict):
        output_image = response.get("output_image")
    if output_image is None:
        raise GeminiImageError("INVALID_RESPONSE", "Görsel üretim çıktısı alınamadı.")
    data = output_image.get("data") if isinstance(output_image, dict) else getattr(output_image, "data", None)
    mime_type = (
        output_image.get("mime_type") if isinstance(output_image, dict) else getattr(output_image, "mime_type", None)
    )
    if isinstance(data, bytes):
        image_bytes = data
    elif isinstance(data, str) and data.strip():
        try:
            image_bytes = base64.b64decode(data, validate=True)
        except Exception as exc:
            raise GeminiImageError("INVALID_RESPONSE", "Görsel üretim verisi çözümlenemedi.") from exc
    else:
        raise GeminiImageError("INVALID_RESPONSE", "Görsel üretim verisi boş döndü.")
    if not image_bytes:
        raise GeminiImageError("INVALID_RESPONSE", "Görsel üretim boş çıktı döndürdü.")
    return image_bytes, str(mime_type or "image/png").strip().lower()


def _validate_output_image(image_bytes: bytes) -> tuple[int, int]:
    try:
        from PIL import Image  # type: ignore[reportMissingImports]
    except (ImportError, ModuleNotFoundError):
        return 0, 0
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.verify()
        with Image.open(io.BytesIO(image_bytes)) as image:
            width, height = image.size
    except Exception as exc:
        raise GeminiImageError("INVALID_RESPONSE", "Geçerli bir görsel dosyası alınamadı.") from exc
    if width <= 0 or height <= 0:
        raise GeminiImageError("INVALID_RESPONSE", "Geçersiz görsel boyutu alındı.")
    return int(width), int(height)


def _provider_error(exc: Exception) -> GeminiImageError:
    status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    message = str(exc or "Image generation request failed.")
    lowered = message.lower()
    if "api_key_invalid" in lowered or "api key not valid" in lowered:
        return GeminiImageError("PROVIDER_AUTH_FAILED", "Görsel üretim ayarı geçersiz.", 400)
    if status_code == 429 or "quota" in lowered or "resource exhausted" in lowered:
        return GeminiImageError("PROVIDER_RATE_LIMITED", message, 429)
    if status_code in {401, 403} or "api key" in lowered or "permission denied" in lowered:
        return GeminiImageError("PROVIDER_AUTH_FAILED", message, int(status_code) if isinstance(status_code, int) else None)
    if "timeout" in lowered or "timed out" in lowered:
        return GeminiImageError("PROVIDER_TIMEOUT", message)
    return GeminiImageError("IMAGE_PROVIDER_ERROR", message, int(status_code) if isinstance(status_code, int) else None)


def _is_transient(error: GeminiImageError) -> bool:
    return error.code in {"PROVIDER_RATE_LIMITED", "PROVIDER_TIMEOUT"} or bool(
        error.status_code and error.status_code >= 500
    )


def _brand_logo_path() -> Path:
    return Path(__file__).resolve().parent.parent / "logo.png"


def _apply_elyan_logo(path: Path) -> bool:
    try:
        from PIL import Image, ImageDraw  # type: ignore[reportMissingImports]
    except (ImportError, ModuleNotFoundError):
        return False
    logo_path = _brand_logo_path()
    if not logo_path.exists():
        return False
    try:
        with Image.open(path).convert("RGBA") as base_image:
            with Image.open(logo_path).convert("RGBA") as raw_logo:
                width, height = base_image.size
                if width <= 0 or height <= 0:
                    return False
                logo_size = max(36, min(width, height) // 9)
                logo = raw_logo.copy()
                logo.thumbnail((logo_size, logo_size), Image.Resampling.LANCZOS)
                margin = max(16, min(width, height) // 32)
                pad = max(8, logo_size // 6)
                badge_w = logo.width + pad * 2
                badge_h = logo.height + pad * 2
                x = width - badge_w - margin
                y = height - badge_h - margin
                badge = Image.new("RGBA", (badge_w, badge_h), (0, 0, 0, 0))
                draw = ImageDraw.Draw(badge)
                radius = max(10, badge_h // 4)
                draw.rounded_rectangle(
                    (0, 0, badge_w - 1, badge_h - 1),
                    radius=radius,
                    fill=(255, 255, 255, 210),
                    outline=(20, 28, 32, 46),
                    width=1,
                )
                badge.alpha_composite(logo, (pad, pad))
                base_image.alpha_composite(badge, (max(0, x), max(0, y)))
                base_image.save(path, format="PNG")
        return True
    except Exception:
        return False


def request_image(
    *,
    prompt: str,
    source_paths: list[Path],
    aspect_ratio: str,
    image_size: str,
    model: str,
    api_key: str,
    background: str = "auto",
) -> tuple[bytes, dict[str, Any]]:
    genai = _google_sdk()
    if genai is None:
        raise SafeCapabilityError("DEPENDENCY_UNAVAILABLE", "Görsel üretim altyapısı bu kurulumda hazır değil.")

    editing = bool(source_paths)
    inputs: str | list[dict[str, str]]
    if editing:
        inputs = [{"type": "text", "text": prompt}]
        for path in source_paths:
            inputs.append({
                "type": "image",
                "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                "mime_type": _source_mime_type(path),
            })
    else:
        inputs = prompt

    system_instruction = (
        "Edit the supplied image exactly as requested. Preserve every unmentioned person, face, product, "
        "object, composition detail, color, and proportion. Do not add text, logos, or elements unless requested."
        if editing
        else "Follow the user's visual request precisely. Do not add unrequested text, logos, watermarks, or objects."
    )
    if not editing and str(background or "").strip().lower() == "transparent":
        system_instruction += " Return a transparent background when the requested subject permits it."

    client = genai.Client(api_key=api_key)
    last_error: GeminiImageError | None = None
    for attempt in range(2):
        try:
            response_format: dict[str, str] = {
                "type": "image",
                "mime_type": "image/png",
                "image_size": image_size,
            }
            if aspect_ratio:
                response_format["aspect_ratio"] = aspect_ratio
            response = client.interactions.create(
                model=model,
                input=inputs,
                system_instruction=system_instruction,
                response_format=response_format,
                timeout=150.0,
            )
            image_bytes, mime_type = _response_image(response)
            width, height = _validate_output_image(image_bytes)
            return image_bytes, {"mimeType": mime_type, "width": width, "height": height, "source": "interaction.output_image"}
        except SafeCapabilityError:
            raise
        except GeminiImageError as exc:
            last_error = exc
        except Exception as exc:
            last_error = _provider_error(exc)
        if attempt == 0 and last_error is not None and _is_transient(last_error):
            time.sleep(0.8)
            continue
        break
    assert last_error is not None
    raise last_error


def run_image_operation(
    *,
    prompt: str,
    output_path: str,
    title: str,
    aspect_ratio: str,
    image_size: str,
    overwrite: bool,
    source_paths: list[Path] | None = None,
    background: str = "auto",
    request_fn: Callable[..., tuple[bytes, dict[str, Any]]] | None = None,
    root_resolver: Callable[[], Path] | None = None,
) -> dict[str, Any]:
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Görsel işlemi için açıklama gerekli.")
    editing = bool(source_paths)
    settings = provider_settings(editing=editing)
    if not settings["api_key"]:
        _set_last_error("PROVIDER_NOT_CONFIGURED", "Görsel üretim ayarı eksik.")
        raise SafeCapabilityError("PROVIDER_NOT_CONFIGURED", "Görsel üretim ayarı eksik.")

    resolved_output = ensure_allowed_output_path(
        output_path,
        extension=".png",
        overwrite=overwrite,
        hint=title or prompt_text[:48],
        root_resolver=root_resolver or _workspace_root,
    )
    try:
        image_bytes, metadata = (request_fn or request_image)(
            prompt=prompt_text,
            source_paths=list(source_paths or []),
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            model=settings["model"],
            api_key=settings["api_key"],
            background=background,
        )
        resolved_output.write_bytes(image_bytes)
        branded = _apply_elyan_logo(resolved_output)
    except GeminiImageError as exc:
        _set_last_error(exc.code, exc.message)
        print(
            "image_generation " + json.dumps({
                "event": "error",
                "rawErrorCode": exc.code, "statusCode": exc.status_code,
            }, ensure_ascii=True),
            file=sys.stderr,
        )
        message = _public_image_error_message(exc.code, exc.message)
        raise SafeCapabilityError(exc.code, message) from exc

    _set_last_error("", "")
    kind = "image_edit" if editing else "image_generate"
    artifact = artifact_payload(resolved_output)
    artifact.update({"shareable": True, "requiresUserShare": False, "viewerHint": "image", "contentFamily": "image"})
    return {
        "text": f"Görsel {'düzenlendi' if editing else 'üretildi'}.\n{resolved_output.name}",
        "result": {
            "kind": kind,
            "outputPath": str(resolved_output),
            "sourcePaths": [str(path) for path in source_paths or []],
            "aspectRatio": aspect_ratio,
            "imageSize": image_size,
            "contentType": metadata.get("mimeType", "image/png"),
            "width": metadata.get("width", 0),
            "height": metadata.get("height", 0),
            "branded": branded,
            "promptPreview": normalize_source_context(prompt_text, max_chars=220),
            "title": str(title or "").strip(),
        },
        "artifacts": [artifact],
    }
