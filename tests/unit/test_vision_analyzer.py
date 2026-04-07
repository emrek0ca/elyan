import pytest
from PIL import Image

from elyan.computer_use.vision.analyzer import VisionAnalyzer


def _png_bytes() -> bytes:
    import io

    image = Image.new("RGB", (8, 8), color="white")
    handle = io.BytesIO()
    image.save(handle, format="PNG")
    return handle.getvalue()


@pytest.mark.asyncio
async def test_vision_analyzer_prefers_glm_ocr_when_available(monkeypatch):
    analyzer = VisionAnalyzer(model="qwen2.5-vl:7b", ocr_backend="auto", glm_ocr_model="glm-ocr")
    analyzer.client = object()

    async def _vlm(*args, **kwargs):
        return {
            "description": "login screen",
            "elements": [{"id": "el_1", "type": "button", "bbox": [10, 10, 120, 32], "confidence": 0.8}],
            "ocr_text": "Log in",
        }

    async def _glm(*args, **kwargs):
        return {
            "success": True,
            "backend": "glm_ocr",
            "text": "Log in with Google",
            "lines": [{"text": "Log in with Google", "bbox": [10, 10, 120, 32], "confidence": 0.97, "source": "glm_ocr"}],
        }

    async def _tesseract(*args, **kwargs):
        raise AssertionError("tesseract fallback should not run")

    async def _ensure():
        return None

    monkeypatch.setattr(analyzer, "_ensure_client", _ensure)
    monkeypatch.setattr(analyzer, "_run_vlm_analysis", _vlm)
    monkeypatch.setattr(analyzer, "_run_glm_ocr", _glm)
    monkeypatch.setattr(analyzer, "_run_tesseract_ocr", _tesseract)

    result = await analyzer.analyze(screenshot=_png_bytes(), task_context="click login")
    assert result.ocr_text == "Log in with Google"
    assert result.metadata["ocr_backend"] == "glm_ocr"
    assert result.elements[0].text == "Log in with Google"


@pytest.mark.asyncio
async def test_vision_analyzer_falls_back_to_tesseract(monkeypatch):
    analyzer = VisionAnalyzer(model="qwen2.5-vl:7b", ocr_backend="auto", glm_ocr_model="glm-ocr")
    analyzer.client = object()

    async def _vlm(*args, **kwargs):
        return {"description": "", "elements": [], "ocr_text": ""}

    async def _glm(*args, **kwargs):
        return {"success": False, "backend": "glm_ocr", "text": "", "lines": [], "error": "missing"}

    async def _tesseract(*args, **kwargs):
        return {
            "success": True,
            "backend": "tesseract",
            "text": "Settings General Notifications",
            "lines": [{"text": "Settings", "bbox": [1, 1, 50, 12], "confidence": 0.88, "source": "tesseract"}],
        }

    async def _ensure():
        return None

    monkeypatch.setattr(analyzer, "_ensure_client", _ensure)
    monkeypatch.setattr(analyzer, "_run_vlm_analysis", _vlm)
    monkeypatch.setattr(analyzer, "_run_glm_ocr", _glm)
    monkeypatch.setattr(analyzer, "_run_tesseract_ocr", _tesseract)

    result = await analyzer.analyze(screenshot=_png_bytes(), task_context=None)
    assert result.metadata["ocr_backend"] == "tesseract"
    assert result.ocr_text == "Settings General Notifications"
    assert result.ocr_lines[0].text == "Settings"
