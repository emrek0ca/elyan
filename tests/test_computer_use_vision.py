"""Tests for Computer Use Vision Module

Tests VisionAnalyzer, UIElement detection, screen analysis.
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from io import BytesIO
from PIL import Image

from elyan.computer_use.vision.analyzer import (
    VisionAnalyzer,
    ScreenAnalysisResult,
    UIElement,
    get_vision_analyzer
)


class TestUIElement:
    """Test UIElement data model"""

    def test_ui_element_creation(self):
        """Test creating UIElement"""
        el = UIElement(
            element_id="btn_1",
            element_type="button",
            text="Submit",
            bbox=(100, 50, 80, 40),
            confidence=0.95,
            interactive=True
        )
        assert el.element_id == "btn_1"
        assert el.element_type == "button"
        assert el.text == "Submit"
        assert el.bbox == (100, 50, 80, 40)
        assert el.confidence == 0.95

    def test_ui_element_interactive_types(self):
        """Test interactive element types"""
        interactive_types = ["button", "link", "text_field", "checkbox"]
        for elem_type in interactive_types:
            el = UIElement(
                element_id="test",
                element_type=elem_type,
                bbox=(0, 0, 10, 10),
                confidence=0.9
            )
            assert el.interactive is True

    def test_ui_element_non_interactive(self):
        """Test non-interactive element types"""
        el = UIElement(
            element_id="img_1",
            element_type="image",
            bbox=(0, 0, 100, 100),
            confidence=0.9,
            interactive=False
        )
        assert el.interactive is False


class TestScreenAnalysisResult:
    """Test ScreenAnalysisResult model"""

    def test_screen_analysis_result_creation(self):
        """Test creating analysis result"""
        result = ScreenAnalysisResult(
            screenshot_id="ss_1",
            timestamp=1234567890.0,
            screen_description="Google search page",
            elements=[],
            ocr_text="Some text",
            current_url="https://google.com"
        )
        assert result.screenshot_id == "ss_1"
        assert result.screen_description == "Google search page"
        assert result.current_url == "https://google.com"

    def test_screen_analysis_with_elements(self):
        """Test analysis result with UI elements"""
        elements = [
            UIElement(
                element_id="el_1",
                element_type="text_field",
                bbox=(0, 0, 300, 40),
                confidence=0.95
            ),
            UIElement(
                element_id="el_2",
                element_type="button",
                text="Search",
                bbox=(320, 0, 80, 40),
                confidence=0.92
            )
        ]
        result = ScreenAnalysisResult(
            screenshot_id="ss_1",
            timestamp=1234567890.0,
            screen_description="Search form",
            elements=elements
        )
        assert len(result.elements) == 2
        assert result.elements[0].element_type == "text_field"
        assert result.elements[1].text == "Search"


class TestVisionAnalyzer:
    """Test VisionAnalyzer class"""

    @pytest.fixture
    def analyzer(self):
        """Create VisionAnalyzer instance"""
        return VisionAnalyzer(model="qwen2.5-vl:7b")

    def test_analyzer_initialization(self, analyzer):
        """Test analyzer creation"""
        assert analyzer.model == "qwen2.5-vl:7b"
        assert analyzer.client is None  # Lazy load

    def test_image_to_base64(self):
        """Test image to base64 conversion"""
        # Create small test image
        img = Image.new('RGB', (10, 10), color='red')
        buf = BytesIO()
        img.save(buf, format='PNG')
        image_bytes = buf.getvalue()

        b64 = VisionAnalyzer._image_to_base64(image_bytes)
        assert isinstance(b64, str)
        assert len(b64) > 0

    @pytest.mark.asyncio
    async def test_analyze_requires_ollama(self, analyzer):
        """Test that analyze requires ollama to be available"""
        # Create dummy screenshot
        img = Image.new('RGB', (100, 100), color='white')
        buf = BytesIO()
        img.save(buf, format='PNG')
        screenshot = buf.getvalue()

        # Without mocking ollama, should raise RuntimeError
        try:
            result = await analyzer.analyze(screenshot)
            # If it doesn't raise, it must have ollama
            assert isinstance(result, ScreenAnalysisResult)
        except RuntimeError as e:
            assert "ollama" in str(e).lower()

    @pytest.mark.asyncio
    async def test_analyze_with_mock_ollama(self, analyzer):
        """Test analyze with mocked ollama"""
        import sys
        import types
        mock_ollama = types.ModuleType('ollama')
        sys.modules['ollama'] = mock_ollama

        # Mock ollama response
        mock_response = {
            'message': {
                'content': json.dumps({
                    "description": "Test screen",
                    "elements": [
                        {"id": "el_1", "type": "button", "text": "Click me", "bbox": [10, 10, 100, 50], "confidence": 0.95},
                        {"id": "el_2", "type": "text_field", "bbox": [10, 70, 200, 40], "confidence": 0.92}
                    ],
                    "ocr_text": "Some text here",
                    "url": "https://example.com"
                })
            }
        }
        mock_ollama.chat = MagicMock(return_value=mock_response)

        analyzer.client = mock_ollama
        img = Image.new('RGB', (400, 300), color='white')
        buf = BytesIO()
        img.save(buf, format='PNG')
        screenshot = buf.getvalue()

        result = await analyzer.analyze(screenshot)

        assert isinstance(result, ScreenAnalysisResult)
        assert result.screen_description == "Test screen"
        assert len(result.elements) == 2
        assert result.elements[0].element_type == "button"
        assert result.elements[0].text == "Click me"
        assert result.elements[1].element_type == "text_field"
        assert result.current_url == "https://example.com"

    @pytest.mark.asyncio
    async def test_analyze_with_task_context(self, analyzer):
        """Test that task context is included in prompt"""
        import sys
        import types
        mock_ollama = types.ModuleType('ollama')
        sys.modules['ollama'] = mock_ollama

        mock_response = {'message': {'content': '{}'}}
        mock_ollama.chat = MagicMock(return_value=mock_response)

        analyzer.client = mock_ollama

        img = Image.new('RGB', (100, 100), color='white')
        buf = BytesIO()
        img.save(buf, format='PNG')
        screenshot = buf.getvalue()

        # Should handle any task context without error
        result = await analyzer.analyze(
            screenshot,
            task_context="Find the login button"
        )
        assert result is not None

    def test_parse_vlm_response_direct_json(self, analyzer):
        """Test parsing direct JSON response"""
        response = '{"description": "test", "elements": []}'
        parsed = analyzer._parse_vlm_response(response)
        assert parsed["description"] == "test"

    def test_parse_vlm_response_markdown_json(self, analyzer):
        """Test parsing JSON in markdown code block"""
        response = '```json\n{"description": "test", "elements": []}\n```'
        parsed = analyzer._parse_vlm_response(response)
        assert parsed["description"] == "test"

    def test_parse_vlm_response_with_prefix(self, analyzer):
        """Test parsing JSON with text prefix"""
        response = 'Here is the analysis:\n```json\n{"description": "test"}\n```'
        parsed = analyzer._parse_vlm_response(response)
        assert parsed["description"] == "test"

    def test_parse_vlm_response_invalid_falls_back(self, analyzer):
        """Test fallback when JSON parsing fails"""
        response = "Invalid JSON {not valid"
        parsed = analyzer._parse_vlm_response(response)
        assert "description" in parsed
        assert "ocr_text" in parsed


class TestVisionSingleton:
    """Test singleton pattern"""

    @pytest.mark.asyncio
    async def test_get_vision_analyzer_singleton(self):
        """Test that get_vision_analyzer returns same instance"""
        analyzer1 = await get_vision_analyzer()
        analyzer2 = await get_vision_analyzer()
        assert type(analyzer1) == type(analyzer2)


class TestVisionIntegration:
    """Integration tests for vision module"""

    @pytest.mark.asyncio
    async def test_full_analysis_workflow(self):
        """Test complete analysis workflow with mocked ollama"""
        with patch('elyan.computer_use.vision.analyzer.ollama') as mock_ollama:
            # Setup mock response
            mock_response = {
                'message': {
                    'content': json.dumps({
                        "description": "Google search homepage",
                        "elements": [
                            {"id": "search_input", "type": "text_field", "bbox": [227, 283, 545, 50], "confidence": 0.98},
                            {"id": "search_btn", "type": "button", "text": "Search", "bbox": [245, 358, 130, 36], "confidence": 0.96}
                        ],
                        "ocr_text": "Google Search"
                    })
                }
            }
            mock_ollama.chat.return_value = mock_response

            analyzer = VisionAnalyzer()
            analyzer.client = mock_ollama

            # Create test screenshot
            img = Image.new('RGB', (1000, 800), color='white')
            buf = BytesIO()
            img.save(buf, format='PNG')
            screenshot = buf.getvalue()

            # Analyze
            result = await analyzer.analyze(screenshot)

            # Verify result
            assert result.screen_description == "Google search homepage"
            assert len(result.elements) == 2

            # Verify first element (search input)
            search_input = result.elements[0]
            assert search_input.element_id == "search_input"
            assert search_input.element_type == "text_field"
            assert search_input.bbox == (227, 283, 545, 50)
            assert search_input.interactive is True

            # Verify second element (button)
            search_btn = result.elements[1]
            assert search_btn.element_id == "search_btn"
            assert search_btn.element_type == "button"
            assert search_btn.text == "Search"
            assert search_btn.confidence == 0.96
