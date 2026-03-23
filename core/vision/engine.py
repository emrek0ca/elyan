"""
Vision Engine — Screen understanding, OCR, UI element detection.
Wraps existing vision tools (analyze_image, take_screenshot, _default_ocr, accessibility).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from utils.logger import get_logger

logger = get_logger("vision.engine")


@dataclass
class VisionResult:
    """Complete vision analysis result."""
    success: bool
    text: str
    raw: dict = field(default_factory=dict)
    image_path: Optional[str] = None
    source: str = ""  # "gemini", "ollama", "tesseract", "applescript"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class VisionEngine:
    """
    Multi-source visual intelligence engine.
    - Capture: screenshot (native or mss)
    - OCR: tesseract CLI
    - Vision: Gemini Flash or Ollama/LLaVA
    - Accessibility: macOS AppleScript, Windows UIAutomation
    """

    def __init__(self):
        self._screenshot_tool = None
        self._analyze_tool = None
        self._ocr_tool = None
        self._accessibility_tool = None
        self._load_tools()

    def _load_tools(self):
        """Load tool wrappers (lazy)."""
        try:
            from tools.system_tools import take_screenshot
            self._screenshot_tool = take_screenshot
            logger.info("Screenshot tool loaded")
        except ImportError as e:
            logger.warning(f"Screenshot tool load failed: {e}")

        try:
            from tools.vision_tools import analyze_image
            self._analyze_tool = analyze_image
            logger.info("Analyze image tool loaded")
        except ImportError as e:
            logger.warning(f"Analyze image tool load failed: {e}")

        try:
            from core.capabilities.screen_operator.services import _default_ocr
            self._ocr_tool = _default_ocr
            logger.info("OCR tool loaded")
        except ImportError as e:
            logger.warning(f"OCR tool load failed: {e}")

        try:
            from core.capabilities.screen_operator.services import _default_accessibility_snapshot
            self._accessibility_tool = _default_accessibility_snapshot
            logger.info("Accessibility tool loaded")
        except ImportError as e:
            logger.warning(f"Accessibility tool load failed: {e}")

    async def capture_and_analyze(
        self,
        target: Optional[str] = None,
        prompt: str = "Gorseli detayli analiz et.",
        analysis_type: str = "comprehensive",
    ) -> VisionResult:
        """
        Capture and analyze image.

        Args:
            target: image file path or None for live screenshot
            prompt: analysis prompt
            analysis_type: comprehensive|ocr|ui|diff

        Returns:
            VisionResult with analysis text and raw response
        """
        try:
            # Step 1: Get image path
            image_path = await self._get_image(target)
            if not image_path:
                return VisionResult(
                    success=False,
                    text="Ekran goruntusu alinamamadi",
                    image_path=None,
                )

            # Step 2: Analyze via vision tool
            if not self._analyze_tool:
                return VisionResult(
                    success=False,
                    text="Vision tool kullanilabilir degil",
                    image_path=image_path,
                )

            raw = await self._analyze_tool(
                image_path=image_path,
                prompt=prompt,
                analysis_type=analysis_type,
                language="tr",
            )

            if not raw.get("success"):
                return VisionResult(
                    success=False,
                    text=raw.get("error", "Analysis failed"),
                    raw=raw,
                    image_path=image_path,
                )

            text = raw.get("analysis", "")
            provider = raw.get("provider", "unknown")
            source = "gemini" if "gemini" in provider.lower() else "ollama" if "ollama" in provider.lower() else provider

            return VisionResult(
                success=True,
                text=text,
                raw=raw,
                image_path=image_path,
                source=source,
            )

        except Exception as e:
            logger.error(f"capture_and_analyze failed: {e}")
            return VisionResult(
                success=False,
                text=f"Hata: {e}",
            )

    async def ocr(self, target: Optional[str] = None) -> VisionResult:
        """
        Extract text from image via OCR.

        Args:
            target: image file path or None for live screenshot

        Returns:
            VisionResult with extracted text
        """
        try:
            # Step 1: Get image path
            image_path = await self._get_image(target)
            if not image_path:
                return VisionResult(
                    success=False,
                    text="Ekran goruntusu alinamamadi",
                    image_path=None,
                )

            # Step 2: Run OCR
            if not self._ocr_tool:
                return VisionResult(
                    success=False,
                    text="OCR tool kullanilabilir degil",
                    image_path=image_path,
                )

            raw = await self._ocr_tool(image_path)

            if not raw.get("success"):
                return VisionResult(
                    success=False,
                    text=raw.get("error", "OCR failed"),
                    raw=raw,
                    image_path=image_path,
                )

            text = raw.get("text", "")
            return VisionResult(
                success=True,
                text=text,
                raw=raw,
                image_path=image_path,
                source="tesseract",
            )

        except Exception as e:
            logger.error(f"ocr failed: {e}")
            return VisionResult(
                success=False,
                text=f"Hata: {e}",
            )

    async def accessibility(self, app: Optional[str] = None) -> VisionResult:
        """
        Get accessibility tree (UI elements, buttons, text fields).

        Args:
            app: macOS app name or None for frontmost window

        Returns:
            VisionResult with accessibility snapshot
        """
        try:
            if not self._accessibility_tool:
                return VisionResult(
                    success=False,
                    text="Accessibility tool kullanilabilir degil",
                )

            raw = await self._accessibility_tool()

            if not raw.get("success"):
                return VisionResult(
                    success=False,
                    text=raw.get("error", "Accessibility snapshot failed"),
                    raw=raw,
                )

            # Format accessibility info
            app_name = raw.get("frontmost_app", "Unknown")
            window_title = raw.get("window_title", "")
            elements = raw.get("elements", [])

            text = f"App: {app_name}\nWindow: {window_title}\nElements: {len(elements)}"

            return VisionResult(
                success=True,
                text=text,
                raw=raw,
                source="applescript",
            )

        except Exception as e:
            logger.error(f"accessibility failed: {e}")
            return VisionResult(
                success=False,
                text=f"Hata: {e}",
            )

    async def _get_image(self, target: Optional[str]) -> Optional[str]:
        """
        Get image path. If target is None, capture live screenshot.

        Args:
            target: file path or None

        Returns:
            Absolute path to image file or None if failed
        """
        if target:
            # Validate path
            try:
                from security.validator import validate_path
                validate_path(target)
                path = Path(target).expanduser().resolve()
                if path.exists():
                    return str(path)
                else:
                    logger.warning(f"File not found: {target}")
                    return None
            except Exception as e:
                logger.error(f"Path validation failed: {e}")
                return None
        else:
            # Capture live screenshot
            if not self._screenshot_tool:
                logger.warning("Screenshot tool not available")
                return None

            try:
                result = await self._screenshot_tool()
                if result.get("success"):
                    return result.get("path")
                else:
                    logger.error(f"Screenshot failed: {result.get('error')}")
                    return None
            except Exception as e:
                logger.error(f"Screenshot capture failed: {e}")
                return None


__all__ = [
    "VisionEngine",
    "VisionResult",
]
