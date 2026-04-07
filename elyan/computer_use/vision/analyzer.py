"""VisionAnalyzer — local-first screen analysis with OCR fusion.

Primary semantic/layout understanding stays in the existing VLM lane.
OCR is upgraded through a backend chain:
- GLM-OCR via Ollama when available
- Tesseract fallback

This keeps Elyan on a single runtime surface while improving small-text accuracy.
"""

from __future__ import annotations

import asyncio
import base64
import json
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

from PIL import Image
from pydantic import BaseModel, Field

from core.capabilities.screen_operator.services import _default_ocr
from core.observability.logger import get_structured_logger

slog = get_structured_logger("vision_analyzer")


class OCRLine(BaseModel):
    text: str
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    confidence: float = 0.0
    source: str = "ocr"


class UIElement(BaseModel):
    """Detected UI element with bounding box and metadata."""

    element_id: str
    element_type: str
    text: Optional[str] = None
    bbox: tuple[int, int, int, int]
    confidence: float
    interactive: bool = True
    placeholder: Optional[str] = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class ScreenAnalysisResult(BaseModel):
    """Complete analysis of a single screenshot."""

    screenshot_id: str
    timestamp: float
    screen_description: str
    elements: list[UIElement]
    ocr_text: Optional[str] = None
    ocr_lines: list[OCRLine] = Field(default_factory=list)
    current_url: Optional[str] = None
    current_app: Optional[str] = None
    page_title: Optional[str] = None
    language: str = "en"
    metadata: dict[str, Any] = Field(default_factory=dict)


class VisionAnalyzer:
    """Local VLM-powered screen analysis with OCR backend fusion."""

    def __init__(
        self,
        model: str = "qwen2.5-vl:7b",
        *,
        ocr_backend: str = "auto",
        glm_ocr_model: str = "glm-4.1v-9b-thinking",
    ):
        self.model = str(model or "qwen2.5-vl:7b")
        self.ocr_backend = str(ocr_backend or "auto").strip().lower()
        self.glm_ocr_model = str(glm_ocr_model or "glm-4.1v-9b-thinking")
        self.client = None
        slog.log_event(
            "vision_analyzer_init",
            {
                "model": self.model,
                "ocr_backend": self.ocr_backend,
                "glm_ocr_model": self.glm_ocr_model,
            },
        )

    async def _ensure_client(self):
        if self.client is None:
            try:
                import ollama

                self.client = ollama
            except ImportError:
                slog.log_event("ollama_import_failed", {}, level="error")
                raise RuntimeError("ollama not installed. Install with: pip install ollama")

    async def analyze(
        self,
        screenshot: bytes,
        task_context: Optional[str] = None,
    ) -> ScreenAnalysisResult:
        await self._ensure_client()
        try:
            Image.open(BytesIO(screenshot))
            screenshot_id = f"ss_{int(time.time() * 1000)}"
            prompt = self._build_analysis_prompt(task_context)
            image_b64 = self._image_to_base64(screenshot)

            vlm_task = asyncio.create_task(self._run_vlm_analysis(prompt=prompt, image_b64=image_b64, screenshot_id=screenshot_id))
            ocr_task = asyncio.create_task(self._run_ocr_chain(screenshot=screenshot, task_context=task_context))
            vlm_analysis, ocr_payload = await asyncio.gather(vlm_task, ocr_task)

            merged = self._merge_analysis(vlm_analysis=vlm_analysis, ocr_payload=ocr_payload)
            result = ScreenAnalysisResult(
                screenshot_id=screenshot_id,
                timestamp=time.time(),
                screen_description=str(merged.get("description") or "").strip(),
                elements=[
                    UIElement(
                        element_id=str(el.get("id") or f"el_{idx}"),
                        element_type=str(el.get("type") or "unknown"),
                        text=str(el.get("text") or "").strip() or None,
                        bbox=self._coerce_bbox(el.get("bbox")),
                        confidence=float(el.get("confidence") or 0.0),
                        interactive=bool(el.get("interactive", self._is_interactive(str(el.get("type") or "")))),
                        placeholder=str(el.get("placeholder") or "").strip() or None,
                        attributes=dict(el.get("attributes") or {}),
                    )
                    for idx, el in enumerate(list(merged.get("elements") or []))
                ],
                ocr_text=str(merged.get("ocr_text") or "").strip() or None,
                ocr_lines=[
                    OCRLine(
                        text=str(line.get("text") or "").strip(),
                        bbox=self._coerce_bbox(line.get("bbox")),
                        confidence=float(line.get("confidence") or 0.0),
                        source=str(line.get("source") or "ocr"),
                    )
                    for line in list(merged.get("ocr_lines") or [])
                    if str(line.get("text") or "").strip()
                ],
                current_url=str(merged.get("url") or "").strip() or None,
                current_app=str(merged.get("app") or "").strip() or None,
                page_title=str(merged.get("title") or "").strip() or None,
                language=str(merged.get("language") or "en"),
                metadata=dict(merged.get("metadata") or {}),
            )
            slog.log_event(
                "vision_analysis_complete",
                {
                    "screenshot_id": screenshot_id,
                    "elements_detected": len(result.elements),
                    "ocr_lines": len(result.ocr_lines),
                    "ocr_backend": result.metadata.get("ocr_backend"),
                },
            )
            return result
        except Exception as exc:
            slog.log_event("vision_analysis_error", {"error": str(exc)}, level="error")
            raise

    async def _run_vlm_analysis(self, *, prompt: str, image_b64: str, screenshot_id: str) -> dict[str, Any]:
        slog.log_event("vlm_request_start", {"model": self.model, "screenshot_id": screenshot_id})
        response = await asyncio.to_thread(
            self.client.chat,
            model=self.model,
            messages=[{"role": "user", "content": prompt, "images": [image_b64]}],
            stream=False,
        )
        output = str(((response or {}).get("message") or {}).get("content") or "")
        return self._parse_vlm_response(output)

    async def _run_ocr_chain(self, *, screenshot: bytes, task_context: Optional[str]) -> dict[str, Any]:
        backend = self.ocr_backend
        if backend in {"auto", "glm_ocr", "glm"}:
            glm_result = await self._run_glm_ocr(screenshot=screenshot, task_context=task_context)
            if glm_result.get("success"):
                return glm_result
            if backend in {"glm_ocr", "glm"}:
                return glm_result
        return await self._run_tesseract_ocr(screenshot)

    async def _run_glm_ocr(self, *, screenshot: bytes, task_context: Optional[str]) -> dict[str, Any]:
        try:
            prompt = self._build_glm_ocr_prompt(task_context)
            response = await asyncio.to_thread(
                self.client.chat,
                model=self.glm_ocr_model,
                messages=[{"role": "user", "content": prompt, "images": [self._image_to_base64(screenshot)]}],
                stream=False,
            )
            content = str(((response or {}).get("message") or {}).get("content") or "")
            parsed = self._parse_glm_ocr_response(content)
            if parsed.get("text") or parsed.get("lines"):
                parsed["success"] = True
                parsed["backend"] = "glm_ocr"
                return parsed
        except Exception as exc:
            slog.log_event("glm_ocr_failed", {"error": str(exc), "model": self.glm_ocr_model}, level="warning")
        return {"success": False, "backend": "glm_ocr", "text": "", "lines": [], "error": "glm_ocr_unavailable"}

    async def _run_tesseract_ocr(self, screenshot: bytes) -> dict[str, Any]:
        tmp_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
                handle.write(screenshot)
                tmp_path = handle.name
            payload = await _default_ocr(tmp_path)
            return {
                "success": bool(payload.get("success")),
                "backend": "tesseract",
                "text": str(payload.get("text") or ""),
                "lines": [
                    {
                        "text": str(line.get("text") or "").strip(),
                        "bbox": self._xywh_to_bbox(line),
                        "confidence": float(line.get("confidence") or 0.0),
                        "source": "tesseract",
                    }
                    for line in list(payload.get("lines") or [])
                    if str(line.get("text") or "").strip()
                ],
                "error": str(payload.get("error") or ""),
            }
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    def _merge_analysis(self, *, vlm_analysis: dict[str, Any], ocr_payload: dict[str, Any]) -> dict[str, Any]:
        merged = dict(vlm_analysis or {})
        vlm_ocr_text = str(merged.get("ocr_text") or "").strip()
        ocr_text = str(ocr_payload.get("text") or "").strip()
        merged["ocr_text"] = ocr_text if len(ocr_text) >= len(vlm_ocr_text) else vlm_ocr_text
        merged["ocr_lines"] = list(ocr_payload.get("lines") or [])
        metadata = dict(merged.get("metadata") or {})
        metadata["ocr_backend"] = str(ocr_payload.get("backend") or "none")
        metadata["ocr_backend_error"] = str(ocr_payload.get("error") or "")
        metadata["vision_model"] = self.model
        metadata["ocr_model"] = self.glm_ocr_model if metadata["ocr_backend"] == "glm_ocr" else ""
        merged["metadata"] = metadata
        if not str(merged.get("description") or "").strip() and ocr_text:
            merged["description"] = ocr_text[:220]
        merged["elements"] = self._enrich_elements_with_ocr(
            elements=list(merged.get("elements") or []),
            ocr_lines=list(merged.get("ocr_lines") or []),
        )
        return merged

    @staticmethod
    def _enrich_elements_with_ocr(*, elements: list[dict[str, Any]], ocr_lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not ocr_lines:
            return elements
        enriched: list[dict[str, Any]] = []
        for element in elements:
            row = dict(element or {})
            bbox = VisionAnalyzer._coerce_bbox(row.get("bbox"))
            if not row.get("text"):
                for line in ocr_lines:
                    if VisionAnalyzer._intersects(bbox, VisionAnalyzer._coerce_bbox(line.get("bbox"))):
                        candidate = str(line.get("text") or "").strip()
                        if candidate:
                            row["text"] = candidate
                            break
            enriched.append(row)
        return enriched

    def _build_analysis_prompt(self, task_context: Optional[str]) -> str:
        task_part = f"\nCurrent task: {task_context}" if task_context else ""
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
    }}
  ],
  "ocr_text": "all visible text on screen",
  "url": "current URL if visible",
  "app": "active application name",
  "title": "page/window title",
  "language": "en"
}}

Focus on interactive elements, layout hierarchy, and visible action targets.
"""

    @staticmethod
    def _build_glm_ocr_prompt(task_context: Optional[str]) -> str:
        focus = f" Task context: {task_context}." if task_context else ""
        return (
            "Extract all visible text and document-like structure from this screenshot."
            f"{focus} Return strict JSON with keys text, lines. "
            "Each line must contain text, bbox [x,y,width,height], confidence."
        )

    def _parse_vlm_response(self, response_text: str) -> dict[str, Any]:
        parsed = self._extract_json_object(response_text)
        if parsed:
            return parsed
        slog.log_event("vlm_parse_failed", {"response_preview": response_text[:200]}, level="warning")
        return {"description": response_text[:160], "elements": [], "ocr_text": response_text, "metadata": {"raw_fallback": True}}

    def _parse_glm_ocr_response(self, response_text: str) -> dict[str, Any]:
        parsed = self._extract_json_object(response_text)
        if parsed:
            lines: list[dict[str, Any]] = []
            for item in list(parsed.get("lines") or []):
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                lines.append(
                    {
                        "text": text,
                        "bbox": self._coerce_bbox(item.get("bbox")),
                        "confidence": float(item.get("confidence") or 0.0),
                        "source": "glm_ocr",
                    }
                )
            return {"text": str(parsed.get("text") or "").strip(), "lines": lines}
        text = str(response_text or "").strip()
        return {"text": text, "lines": []}

    @staticmethod
    def _extract_json_object(response_text: str) -> dict[str, Any]:
        text = str(response_text or "").strip()
        for candidate in (text,):
            try:
                return json.loads(candidate)
            except Exception:
                pass
            for marker in ("```json", "```"):
                if marker not in candidate:
                    continue
                start = candidate.find(marker) + len(marker)
                end = candidate.find("```", start)
                if end <= start:
                    continue
                snippet = candidate[start:end].strip()
                try:
                    return json.loads(snippet)
                except Exception:
                    continue
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(candidate[start : end + 1])
                except Exception:
                    pass
        return {}

    @staticmethod
    def _image_to_base64(image_bytes: bytes) -> str:
        return base64.b64encode(image_bytes).decode("utf-8")

    @staticmethod
    def _xywh_to_bbox(row: dict[str, Any]) -> tuple[int, int, int, int]:
        return (
            int(float(row.get("x") or 0)),
            int(float(row.get("y") or 0)),
            int(float(row.get("width") or 0)),
            int(float(row.get("height") or 0)),
        )

    @staticmethod
    def _coerce_bbox(value: Any) -> tuple[int, int, int, int]:
        if isinstance(value, (list, tuple)) and len(value) >= 4:
            try:
                return tuple(int(float(item or 0)) for item in value[:4])  # type: ignore[return-value]
            except Exception:
                return (0, 0, 0, 0)
        if isinstance(value, dict):
            return VisionAnalyzer._xywh_to_bbox(value)
        return (0, 0, 0, 0)

    @staticmethod
    def _is_interactive(element_type: str) -> bool:
        return str(element_type or "").strip().lower() in {
            "button",
            "link",
            "text_field",
            "checkbox",
            "radio",
            "select",
            "textarea",
            "tab",
            "menu_item",
        }

    @staticmethod
    def _intersects(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


_vision_analyzer: Optional[VisionAnalyzer] = None


async def get_vision_analyzer(
    model: str = "qwen2.5-vl:7b",
    *,
    ocr_backend: str = "auto",
    glm_ocr_model: str = "glm-4.1v-9b-thinking",
) -> VisionAnalyzer:
    global _vision_analyzer
    if _vision_analyzer is None:
        _vision_analyzer = VisionAnalyzer(
            model=model,
            ocr_backend=ocr_backend,
            glm_ocr_model=glm_ocr_model,
        )
    return _vision_analyzer

