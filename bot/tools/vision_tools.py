"""
Vision Tools - Image analysis, OCR, and visual scene description
Supports both Gemini Flash (Cloud) and Llava (Local Ollama)
"""

import os
import json
import base64
import httpx
from pathlib import Path
from typing import Any, Dict, Optional
from core.dependencies import get_system_dependency_runtime
from utils.ollama_helper import OllamaHelper
from utils.logger import get_logger

logger = get_logger("tools.vision")

# Settings
VISION_MODEL_LOCAL = "llava:7b"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"


def _ensure_ollama_runtime() -> bool:
    try:
        if OllamaHelper.ensure_available(allow_install=True, start_service=True):
            return True
    except Exception as exc:
        logger.debug("Ollama helper ensure_available failed: %s", exc)
    try:
        record = get_system_dependency_runtime().ensure_binary(
            "ollama",
            allow_install=True,
            skill_name="vision",
            tool_name="ollama",
        )
        return str(record.status).lower() in {"ready", "installed"}
    except Exception as exc:
        logger.debug("System ollama ensure failed: %s", exc)
        return False

async def analyze_image(
    image_path: str,
    prompt: str = """Görseli en üst düzey detayla analiz et. 
    1. OCR: Gördüğün tüm metinleri oku ve yapılandırılmış şekilde sun.
    2. Bağlam: Bu görselin ne olduğunu ve neden önemli olabileceğini açıkla.
    3. Nesneler: Önemli objeleri ve konumlarını belirt.
    Yanıtını profesyonel bir dille ve Türkçe olarak ver.""",
    analysis_type: str = "comprehensive",
    language: str = "tr"
) -> Dict[str, Any]:
    """
    Analyzes an image using Vision AI (Gemini or Llava)
    
    Args:
        image_path: Path to the image file
        prompt: Specific instruction for analysis
        analysis_type: "general", "ocr", "scene", "object_detection"
        language: Response language
    """
    try:
        path = Path(image_path).expanduser().resolve()
        if not path.exists():
            return {"success": False, "error": f"Dosya bulunamadı: {image_path}"}

        # Read and encode image
        with open(path, "rb") as image_file:
            image_data = base64.b64encode(image_file.read()).decode('utf-8')

        # Try Gemini first if API key is available
        google_api_key = os.getenv("GOOGLE_API_KEY")
        if google_api_key:
            return await _analyze_with_gemini(image_data, prompt, google_api_key, language)
        
        # Fallback to Local Ollama
        return await _analyze_with_ollama(image_data, prompt, language)

    except Exception as e:
        logger.error(f"Vision analysis error: {e}")
        return {"success": False, "error": str(e)}

async def _analyze_with_gemini(image_base64: str, prompt: str, api_key: str, language: str) -> Dict[str, Any]:
    """Analyzes image using Google Gemini Flash API via REST"""
    logger.info("Using Gemini Flash for vision analysis")
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{
            "parts": [
                {"text": f"{prompt} Respond in {language}."},
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": image_base64
                    }
                }
            ]
        }]
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{GEMINI_API_URL}?key={api_key}",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            
            description = data['candidates'][0]['content']['parts'][0]['text']
            return {
                "success": True,
                "provider": "gemini",
                "analysis": description,
                "message": "Görsel Gemini ile analiz edildi."
            }
    except Exception as e:
        logger.warning(f"Gemini Vision failed, falling back to local: {e}")
        return await _analyze_with_ollama(image_base64, prompt, language)

async def _analyze_with_ollama(image_base64: str, prompt: str, language: str) -> Dict[str, Any]:
    """Analyzes image using local Ollama (Llava)"""
    logger.info(f"Using local {VISION_MODEL_LOCAL} for vision analysis")

    if not _ensure_ollama_runtime():
        return {
            "success": False,
            "error": "Ollama runtime hazir degil.",
            "provider": "ollama/llava",
            "error_code": "ollama_runtime_missing",
        }
    
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    
    payload = {
        "model": VISION_MODEL_LOCAL,
        "prompt": f"{prompt} (DİL: {language})",
        "images": [image_base64],
        "stream": False
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{ollama_host}/api/generate", json=payload)
            
            # If model not found, try to pull it
            if response.status_code == 404:
                logger.info(f"Model {VISION_MODEL_LOCAL} not found, pulling...")
                await client.post(f"{ollama_host}/api/pull", json={"name": VISION_MODEL_LOCAL})
                # Retry once after pulling (async wait might be needed, but we keep it simple)
                response = await client.post(f"{ollama_host}/api/generate", json=payload)

            response.raise_for_status()
            description = response.json().get("response", "")
            
            return {
                "success": True,
                "provider": "ollama/llava",
                "analysis": description,
                "message": "Görsel yerel yapay zeka ile analiz edildi."
            }
    except Exception as e:
        logger.error(f"Ollama Vision failed: {e}")
        return {"success": False, "error": f"Vision servisi kullanılamıyor: {str(e)}"}
