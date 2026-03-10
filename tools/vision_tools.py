"""Vision tools for AI analysis and practical image processing operations."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from security.validator import validate_path
from utils.logger import get_logger

try:
    from PIL import Image, ImageEnhance, ImageOps
except Exception:  # pragma: no cover - optional dependency
    Image = None
    ImageEnhance = None
    ImageOps = None

logger = get_logger("tools.vision")

VISION_MODEL_LOCAL = "llava:7b"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
VISION_OLLAMA_TIMEOUT_S = float(os.getenv("ELYAN_VISION_OLLAMA_TIMEOUT_S", "22"))
VISION_AUTO_PULL = str(os.getenv("ELYAN_VISION_AUTO_PULL", "")).strip().lower() == "force"

_MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def _detect_mime(path: Path) -> str:
    return _MIME_BY_EXT.get(path.suffix.lower(), "image/jpeg")


async def analyze_image(
    image_path: str,
    prompt: str = (
        "Gorseli detayli analiz et. OCR metinlerini cikar, baglami acikla, "
        "onemli nesneleri konumlariyla listele."
    ),
    analysis_type: str = "comprehensive",
    language: str = "tr",
) -> Dict[str, Any]:
    """Analyze image via Gemini (if configured) or local Ollama/Llava."""
    try:
        path = Path(image_path).expanduser().resolve()
        if not path.exists():
            return {"success": False, "error": f"Dosya bulunamadi: {image_path}"}

        with open(path, "rb") as image_file:
            raw = image_file.read()
            image_data = base64.b64encode(raw).decode("utf-8")

        google_api_key = os.getenv("GOOGLE_API_KEY")
        mime_type = _detect_mime(path)

        if google_api_key:
            return await _analyze_with_gemini(image_data, prompt, google_api_key, language, mime_type)

        return await _analyze_with_ollama(image_data, prompt, language, analysis_type)

    except Exception as e:
        logger.error(f"Vision analysis error: {e}")
        return {"success": False, "error": str(e)}


async def _analyze_with_gemini(
    image_base64: str,
    prompt: str,
    api_key: str,
    language: str,
    mime_type: str,
) -> Dict[str, Any]:
    """Analyze image using Gemini Flash REST API."""
    logger.info("Using Gemini Flash for vision analysis")

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"{prompt} Respond in {language}."},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": image_base64,
                        }
                    },
                ]
            }
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{GEMINI_API_URL}?key={api_key}",
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            description = data["candidates"][0]["content"]["parts"][0]["text"]
            return {
                "success": True,
                "provider": "gemini",
                "analysis": description,
                "message": "Gorsel Gemini ile analiz edildi.",
            }
    except Exception as e:
        logger.warning(f"Gemini Vision failed, falling back to local: {e}")
        return await _analyze_with_ollama(image_base64, prompt, language, "fallback")


async def _analyze_with_ollama(
    image_base64: str,
    prompt: str,
    language: str,
    analysis_type: str,
) -> Dict[str, Any]:
    """Analyze image using local Ollama (Llava)."""
    logger.info(f"Using local {VISION_MODEL_LOCAL} for vision analysis")

    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    payload = {
        "model": VISION_MODEL_LOCAL,
        "prompt": f"{prompt} (DIL: {language}, TIP: {analysis_type})",
        "images": [image_base64],
        "stream": False,
    }

    # Cold start can be slower on first request; retry once with a larger timeout.
    timeouts = [VISION_OLLAMA_TIMEOUT_S, max(30.0, VISION_OLLAMA_TIMEOUT_S)]
    last_exc: Exception | None = None

    for idx, timeout_s in enumerate(timeouts, start=1):
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(f"{ollama_host}/api/generate", json=payload)

                if response.status_code == 404:
                    if not VISION_AUTO_PULL:
                        logger.warning(
                            "Vision model %s not available locally. Auto-pull disabled; returning fast failure.",
                            VISION_MODEL_LOCAL,
                        )
                        return {
                            "success": False,
                            "error": (
                                f"Yerel vision modeli hazir degil: {VISION_MODEL_LOCAL}. "
                                "Arka planda kurup sonra tekrar deneyin."
                            ),
                            "provider": "ollama/llava",
                            "error_code": "vision_model_missing",
                        }
                    logger.info(f"Model {VISION_MODEL_LOCAL} not found, pulling...")
                    await client.post(f"{ollama_host}/api/pull", json={"name": VISION_MODEL_LOCAL})
                    response = await client.post(f"{ollama_host}/api/generate", json=payload)

                response.raise_for_status()
                description = response.json().get("response", "")

                return {
                    "success": True,
                    "provider": "ollama/llava",
                    "analysis": description,
                    "message": "Gorsel yerel yapay zeka ile analiz edildi.",
                }
        except Exception as e:
            last_exc = e
            logger.warning("Ollama Vision attempt %s failed: %s", idx, e)
            if idx < len(timeouts):
                continue
            break

    err_text = str(last_exc or "").strip() or (last_exc.__class__.__name__ if last_exc else "unknown_error")
    logger.error(f"Ollama Vision failed: {err_text}")
    return {"success": False, "error": f"Vision servisi kullanilamiyor: {err_text}"}


async def process_image_file(
    image_path: str,
    operation: str = "metadata",
    output_path: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    rotate_degrees: float = 0.0,
    crop_box: Optional[list[int]] = None,
    image_format: Optional[str] = None,
    quality: int = 92,
    grayscale: bool = False,
    enhance_contrast: Optional[float] = None,
) -> Dict[str, Any]:
    """Process images with practical operations (metadata/resize/crop/rotate/convert)."""
    try:
        if Image is None:
            return {
                "success": False,
                "error": "Pillow kurulu degil. Gorsel isleme icin 'pip install Pillow' gerekli.",
            }

        valid, msg, _ = validate_path(image_path)
        if not valid:
            return {"success": False, "error": msg}

        src = Path(image_path).expanduser().resolve()
        if not src.exists():
            return {"success": False, "error": f"Dosya bulunamadi: {src}"}

        def _target_path() -> Path:
            if output_path:
                return Path(output_path).expanduser().resolve()
            suffix = src.suffix.lower() or ".png"
            return src.with_name(f"{src.stem}_{operation}{suffix}")

        if operation == "metadata":
            with Image.open(src) as im:
                return {
                    "success": True,
                    "operation": "metadata",
                    "path": str(src),
                    "metadata": {
                        "width": im.width,
                        "height": im.height,
                        "mode": im.mode,
                        "format": im.format,
                        "size_bytes": src.stat().st_size,
                    },
                }

        out = _target_path()
        out.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(src) as im:
            result = im.copy()

            if operation == "resize":
                if width is None and height is None:
                    return {"success": False, "error": "resize icin width veya height gerekli"}

                if width is None:
                    ratio = float(height) / float(im.height)
                    width = max(1, int(im.width * ratio))
                elif height is None:
                    ratio = float(width) / float(im.width)
                    height = max(1, int(im.height * ratio))

                result = result.resize((int(width), int(height)), Image.Resampling.LANCZOS)

            elif operation == "crop":
                if not crop_box or len(crop_box) != 4:
                    return {"success": False, "error": "crop icin [left, top, right, bottom] gerekli"}
                left, top, right, bottom = [int(v) for v in crop_box]
                result = result.crop((left, top, right, bottom))

            elif operation == "rotate":
                result = result.rotate(float(rotate_degrees), expand=True)

            elif operation == "grayscale":
                result = ImageOps.grayscale(result)

            elif operation == "thumbnail":
                target_w = int(width or 256)
                target_h = int(height or target_w)
                result.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)

            elif operation == "convert":
                fmt = str(image_format or "PNG").upper()
                if fmt in {"JPG", "JPEG"} and result.mode in {"RGBA", "LA"}:
                    result = result.convert("RGB")

            else:
                return {"success": False, "error": f"Desteklenmeyen operation: {operation}"}

            if grayscale and operation != "grayscale":
                result = ImageOps.grayscale(result)

            if enhance_contrast and enhance_contrast > 0 and ImageEnhance is not None:
                result = ImageEnhance.Contrast(result).enhance(float(enhance_contrast))

            save_format = (image_format or result.format or src.suffix.replace(".", "") or "PNG").upper()
            if save_format == "JPG":
                save_format = "JPEG"
            save_kwargs: Dict[str, Any] = {}
            if save_format in {"JPEG", "WEBP"}:
                save_kwargs["quality"] = max(1, min(int(quality), 100))

            result.save(out, format=save_format, **save_kwargs)

        return {
            "success": True,
            "operation": operation,
            "input_path": str(src),
            "output_path": str(out),
            "size_bytes": out.stat().st_size,
        }
    except Exception as e:
        logger.error(f"process_image_file error: {e}")
        return {"success": False, "error": str(e)}
