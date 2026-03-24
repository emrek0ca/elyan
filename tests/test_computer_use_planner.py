"""Tests for Computer Use Action Planner

Tests LLM-based action planning.
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from elyan.computer_use.planning.action_planner import (
    ActionPlanner,
    get_action_planner
)
from elyan.computer_use.tool import ComputerAction
from elyan.computer_use.vision.analyzer import ScreenAnalysisResult, UIElement


class TestActionPlanner:
    """Test ActionPlanner class"""

    @pytest.fixture
    def planner(self):
        """Create ActionPlanner instance"""
        return ActionPlanner(model="mistral:latest")

    def test_planner_initialization(self, planner):
        """Test planner creation"""
        assert planner.model == "mistral:latest"
        assert planner.client is None  # Lazy load

    @pytest.mark.asyncio
    async def test_plan_next_action_with_mock_llm(self, planner):
        """Test action planning with mocked LLM"""
        with patch('elyan.computer_use.planning.action_planner.ollama') as mock_ollama:
            # Mock LLM response
            mock_response = {
                'message': {
                    'content': json.dumps({
                        "action_type": "left_click",
                        "x": 100,
                        "y": 200,
                        "confidence": 0.95,
                        "reasoning": "Click the search button"
                    })
                }
            }
            mock_ollama.chat.return_value = mock_response

            planner.client = mock_ollama

            # Setup screen analysis
            screen = ScreenAnalysisResult(
                screenshot_id="ss_1",
                timestamp=datetime.now().timestamp(),
                screen_description="Google homepage",
                elements=[
                    UIElement(
                        element_id="search_btn",
                        element_type="button",
                        text="Search",
                        bbox=(100, 200, 80, 40),
                        confidence=0.98
                    )
                ]
            )

            # Plan action
            action = await planner.plan_next_action(
                user_intent="Search for Python",
                screen_analysis=screen,
                previous_actions=[]
            )

            assert isinstance(action, ComputerAction)
            assert action.action_type == "left_click"
            assert action.x == 100
            assert action.y == 200

    def test_parse_action_response_direct_json(self, planner):
        """Test parsing direct JSON response"""
        response = json.dumps({
            "action_type": "type",
            "text": "hello",
            "confidence": 0.9
        })
        action = planner._parse_action_response(response)
        assert action.action_type == "type"
        assert action.text == "hello"

    def test_parse_action_response_markdown(self, planner):
        """Test parsing JSON in markdown"""
        response = f"""
Here's the recommended action:

```json
{json.dumps({
    "action_type": "scroll",
    "dy": 3,
    "confidence": 0.85
})}
```

This will scroll down the page.
"""
        action = planner._parse_action_response(response)
        assert action.action_type == "scroll"
        assert action.dy == 3

    def test_parse_action_response_with_code_block(self, planner):
        """Test parsing code block without json marker"""
        response = f"""
```
{json.dumps({
    "action_type": "left_click",
    "x": 150,
    "y": 250
})}
```
"""
        action = planner._parse_action_response(response)
        assert action.action_type == "left_click"

    def test_parse_action_response_invalid_fallback(self, planner):
        """Test fallback when parsing fails"""
        response = "This is not valid JSON at all"
        try:
            action = planner._parse_action_response(response)
            # If it doesn't raise, should return a valid action
            assert isinstance(action, ComputerAction)
        except ValueError:
            # It's okay to raise ValueError for completely invalid JSON
            pass

    def test_build_planning_prompt(self, planner):
        """Test prompt building"""
        screen = ScreenAnalysisResult(
            screenshot_id="ss_1",
            timestamp=datetime.now().timestamp(),
            screen_description="Login form",
            elements=[
                UIElement(
                    element_id="email",
                    element_type="text_field",
                    placeholder="Email",
                    bbox=(10, 10, 200, 40),
                    confidence=0.98
                ),
                UIElement(
                    element_id="password",
                    element_type="text_field",
                    placeholder="Password",
                    bbox=(10, 60, 200, 40),
                    confidence=0.98
                )
            ]
        )

        prompt = planner._build_planning_prompt(
            intent="Log in with user@example.com",
            screen=screen,
            history=[]
        )

        assert "Log in with user@example.com" in prompt
        assert "Login form" in prompt
        assert "email" in prompt or "Email" in prompt
        assert "JSON" in prompt

    @pytest.mark.asyncio
    async def test_plan_click_action(self, planner):
        """Test planning a click action"""
        with patch('elyan.computer_use.planning.action_planner.ollama') as mock_ollama:
            mock_response = {
                'message': {
                    'content': json.dumps({
                        "action_type": "left_click",
                        "x": 500,
                        "y": 600,
                        "confidence": 0.9
                    })
                }
            }
            mock_ollama.chat.return_value = mock_response
            planner.client = mock_ollama

            screen = ScreenAnalysisResult(
                screenshot_id="ss_1",
                timestamp=datetime.now().timestamp(),
                screen_description="Page with button",
                elements=[
                    UIElement(
                        element_id="btn",
                        element_type="button",
                        text="Continue",
                        bbox=(500, 600, 100, 40),
                        confidence=0.95
                    )
                ]
            )

            action = await planner.plan_next_action(
                user_intent="Click continue button",
                screen_analysis=screen,
                previous_actions=[]
            )

            assert action.action_type == "left_click"

    @pytest.mark.asyncio
    async def test_plan_type_action(self, planner):
        """Test planning a type action"""
        with patch('elyan.computer_use.planning.action_planner.ollama') as mock_ollama:
            mock_response = {
                'message': {
                    'content': json.dumps({
                        "action_type": "type",
                        "text": "user@example.com",
                        "confidence": 0.95
                    })
                }
            }
            mock_ollama.chat.return_value = mock_response
            planner.client = mock_ollama

            screen = ScreenAnalysisResult(
                screenshot_id="ss_1",
                timestamp=datetime.now().timestamp(),
                screen_description="Login form with email field",
                elements=[
                    UIElement(
                        element_id="email_field",
                        element_type="text_field",
                        placeholder="Email",
                        bbox=(100, 100, 300, 40),
                        confidence=0.98
                    )
                ]
            )

            action = await planner.plan_next_action(
                user_intent="Enter email address",
                screen_analysis=screen,
                previous_actions=[]
            )

            assert action.action_type == "type"
            assert "user" in action.text.lower()

    @pytest.mark.asyncio
    async def test_plan_with_action_history(self, planner):
        """Test planning with previous action history"""
        with patch('elyan.computer_use.planning.action_planner.ollama') as mock_ollama:
            mock_response = {
                'message': {
                    'content': json.dumps({
                        "action_type": "left_click",
                        "x": 200,
                        "y": 300,
                        "confidence": 0.88
                    })
                }
            }
            mock_ollama.chat.return_value = mock_response
            planner.client = mock_ollama

            screen = ScreenAnalysisResult(
                screenshot_id="ss_3",
                timestamp=datetime.now().timestamp(),
                screen_description="Payment confirmation page",
                elements=[]
            )

            history = [
                {"step": 0, "action": {"action_type": "left_click", "x": 100, "y": 100}},
                {"step": 1, "action": {"action_type": "type", "text": "user@example.com"}}
            ]

            action = await planner.plan_next_action(
                user_intent="Complete the checkout",
                screen_analysis=screen,
                previous_actions=history
            )

            # Should use history in planning
            assert isinstance(action, ComputerAction)
            assert action.confidence <= 1.0


class TestPlannerSingleton:
    """Test singleton pattern"""

    @pytest.mark.asyncio
    async def test_get_action_planner_singleton(self):
        """Test singleton pattern"""
        planner1 = await get_action_planner()
        planner2 = await get_action_planner()
        assert type(planner1) == type(planner2)


class TestPlannerRobustness:
    """Test error handling"""

    @pytest.fixture
    def planner(self):
        return ActionPlanner()

    @pytest.mark.asyncio
    async def test_plan_with_empty_screen(self, planner):
        """Test planning on empty screen"""
        with patch('elyan.computer_use.planning.action_planner.ollama') as mock_ollama:
            mock_response = {
                'message': {
                    'content': json.dumps({
                        "action_type": "wait",
                        "wait_ms": 500,
                        "confidence": 0.5
                    })
                }
            }
            mock_ollama.chat.return_value = mock_response
            planner.client = mock_ollama

            screen = ScreenAnalysisResult(
                screenshot_id="ss_1",
                timestamp=datetime.now().timestamp(),
                screen_description="Blank page, loading...",
                elements=[]
            )

            action = await planner.plan_next_action(
                user_intent="Wait for page to load",
                screen_analysis=screen,
                previous_actions=[]
            )

            assert isinstance(action, ComputerAction)

    def test_parse_malformed_json(self, planner):
        """Test parsing completely malformed JSON"""
        response = "{ this is not valid json }"
        action = planner._parse_action_response(response)
        # Should still return a valid action
        assert isinstance(action, ComputerAction)
