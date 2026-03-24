"""VisionAnalyzer — Local VLM-powered Screen Analysis

Uses Qwen2.5-VL via Ollama for UI detection, OCR, and semantic understanding.
Zero cloud, pure local processing.
"""

import json
import asyncio
from io import BytesIO
from typing import Optional
from pydantic import BaseModel
from PIL import Image
import base64

from core.observability.logger import get_structured_logger

slog = get_structured_logger("vision_analyzer")


# ============================================================================
# DATA MODELS
# ============================================================================

class UIElement(BaseModel):
    """Detected UI element with bounding box and metadata"""
    element_id: str
    element_type: str  # "button", "text_field", "link", "image", "icon", etc
    text: Optional[str] = None
    bbox: tuple[int, int, int, int]  # (x, y, width, height)
    confidence: float  # 0-1
    interactive: bool = True
    placeholder: Optional[str] = None
    attributes: dict = {}


class ScreenAnalysisResult(BaseModel):
    """Complete analysis of a single screenshot"""
    screenshot_id: str
    timestamp: float
    screen_description: str  # Natural language summary
    elements: list[UIElement]
    ocr_text: Optional[str] = None  # Full page OCR
    current_url: Optional[str] = None  # Browser URL if visible
    current_app: Optional[str] = None  # Active window/app
    page_title: Optional[str] = None
    language: str = "en"
    metadata: dict = {}


# ============================================================================
# VISION ANALYZER
# ============================================================================

class VisionAnalyzer:
    """
    Local VLM-powered screen analysis

    Uses Qwen2.5-VL 7B via Ollama for:
    - UI element detection (bounding boxes)
    - Text recognition (OCR)
    - Semantic understanding (what's happening on screen)
    """

    def __init__(self, model: str = "qwen2.5-vl:7b"):
        """
        Initialize VisionAnalyzer

        Args:
            model: Ollama model name (must be VLM capable)
        """
        self.model = model
        self.client = None  # Lazy load

        slog.log_event("vision_analyzer_init", {
            "model": model
        })

    async def _ensure_client(self):
        """Lazy load ollama client"""
        if self.client is None:
            try:
                import ollama
                self.client = ollama
            except ImportError:
                slog.log_event("ollama_import_failed", {}, level="error")
                raise RuntimeError(
                    "ollama not installed. Install with: pip install ollama"
                )

    async def analyze(
        self,
        screenshot: bytes,
        task_context: Optional[str] = None
    ) -> ScreenAnalysisResult:
        """
        Analyze screenshot for UI elements and content

        Args:
            screenshot: Image bytes (PNG, JPG, etc)
            task_context: Current task description (helps VLM focus)

        Returns:
            ScreenAnalysisResult with detected elements, text, metadata
        """
        await self._ensure_client()

        try:
            # Parse image
            image = Image.open(BytesIO(screenshot))
            screenshot_id = f"ss_{int(__import__('time').time() * 1000)}"

            # Build VLM prompt
            prompt = self._build_analysis_prompt(task_context)

            # Convert image to base64 for Ollama
            image_b64 = self._image_to_base64(screenshot)

            # Call VLM via Ollama
            slog.log_event("vlm_request_start", {
                "model": self.model,
                "screenshot_id": screenshot_id
            })

            response = self.client.chat(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [image_b64]
                    }
                ],
                stream=False
            )

            # Parse response
            vlm_output = response['message']['content']
            analysis = self._parse_vlm_response(vlm_output)

            slog.log_event("vlm_analysis_complete", {
                "screenshot_id": screenshot_id,
                "elements_detected": len(analysis.get("elements", [])),
                "has_text": bool(analysis.get("ocr_text"))
            })

            # Build result
            result = ScreenAnalysisResult(
                screenshot_id=screenshot_id,
                timestamp=__import__('time').time(),
                screen_description=analysis.get("description", ""),
                elements=[
                    UIElement(
                        element_id=el.get("id", f"el_{i}"),
                        element_type=el.get("type", "unknown"),
                        text=el.get("text"),
                        bbox=tuple(el.get("bbox", [0, 0, 0, 0])),
                        confidence=float(el.get("confidence", 0.9)),
                        interactive=el.get("type") in [
                            "button", "link", "text_field", "checkbox",
                            "radio", "select", "textarea"
                        ],
                        placeholder=el.get("placeholder"),
                        attributes=el.get("attributes", {})
                    )
                    for i, el in enumerate(analysis.get("elements", []))
                ],
                ocr_text=analysis.get("ocr_text"),
                current_url=analysis.get("url"),
                current_app=analysis.get("app"),
                page_title=analysis.get("title"),
                language=analysis.get("language", "en")
            )

            return result

        except Exception as e:
            slog.log_event("vision_analysis_error", {
                "error": str(e)
            }, level="error")
            raise

    def _build_analysis_prompt(self, task_context: Optional[str]) -> str:
        """Build VLM analysis prompt"""
        task_part = ""
        if task_context:
            task_part = f"\nCurrent task: {task_context}"

        return f"""
Analyze this screenshot for UI automation.{task_part}

Return JSON with this exact structure:
{{
    "description": "What's on the screen in 1-2 sentences",
    "elements": [
        {{
            "id": "el_1",
            "type": "button",
            "text": "Submit",
            "bbox": [x, y, width, height],
            "confidence": 0.95,
            "placeholder": null,
            "attributes": {{"aria-label": "..."}}
        }},
        ...
    ],
    "ocr_text": "all visible text on screen",
    "url": "current URL if visible",
    "app": "active application name",
    "title": "page/window title",
    "language": "en"
}}

Focus on interactive elements (buttons, inputs, links).
Include precise bounding boxes [left, top, width, height].
Be thorough but concise.
"""

    def _parse_vlm_response(self, response_text: str) -> dict:
        """
        Parse VLM JSON response

        VLM might wrap JSON in markdown or extra text, so extract it
        """
        try:
            # Try direct JSON parse
            return json.loads(response_text)
        except json.JSONDecodeError:
            # Try extracting JSON from markdown code blocks
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                if end > start:
                    json_str = response_text[start:end].strip()
                    return json.loads(json_str)
            elif "```" in response_text:
                start = response_text.find("```") + 3
                end = response_text.find("```", start)
                if end > start:
                    json_str = response_text[start:end].strip()
                    return json.loads(json_str)

            # Fallback: return minimal structure
            slog.log_event("vlm_parse_failed", {
                "response_preview": response_text[:200]
            }, level="warning")

            return {
                "description": response_text[:100],
                "elements": [],
                "ocr_text": response_text
            }

    @staticmethod
    def _image_to_base64(image_bytes: bytes) -> str:
        """Convert image bytes to base64 for Ollama"""
        return base64.b64encode(image_bytes).decode('utf-8')


# ============================================================================
# SINGLETON
# ============================================================================

_vision_analyzer: Optional[VisionAnalyzer] = None


async def get_vision_analyzer(model: str = "qwen2.5-vl:7b") -> VisionAnalyzer:
    """Get or create VisionAnalyzer singleton"""
    global _vision_analyzer
    if _vision_analyzer is None:
        _vision_analyzer = VisionAnalyzer(model=model)
    return _vision_analyzer
