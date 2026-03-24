"""Tests for Computer Use Router"""

import pytest
from core.computer_use_router import ComputerUseRouter, get_computer_use_router


class TestComputerUseRouter:
    """Tests for ComputerUseRouter"""

    def test_should_route_computer_use(self):
        """Test detection of computer_use action"""
        assert ComputerUseRouter.should_route_to_computer_use("computer_use")
        assert ComputerUseRouter.should_route_to_computer_use("COMPUTER_USE")
        assert ComputerUseRouter.should_route_to_computer_use("screen_control")
        assert ComputerUseRouter.should_route_to_computer_use("ui_automation")

    def test_should_not_route_other_actions(self):
        """Test non-computer_use actions"""
        assert not ComputerUseRouter.should_route_to_computer_use("web_search")
        assert not ComputerUseRouter.should_route_to_computer_use("file_operation")
        assert not ComputerUseRouter.should_route_to_computer_use("chat")
        assert not ComputerUseRouter.should_route_to_computer_use(None)
        assert not ComputerUseRouter.should_route_to_computer_use("")

    def test_extract_computer_use_intent(self):
        """Test intent extraction from action"""
        action = {"user_intent": "Open Chrome and read news"}
        intent = ComputerUseRouter.extract_computer_use_intent(action)
        assert intent == "Open Chrome and read news"

    def test_extract_intent_fallback_fields(self):
        """Test fallback field names for intent"""
        action1 = {"intent": "Click button"}
        assert ComputerUseRouter.extract_computer_use_intent(action1) == "Click button"

        action2 = {"description": "Type text"}
        assert ComputerUseRouter.extract_computer_use_intent(action2) == "Type text"

        action3 = {"task": "Scroll page"}
        assert ComputerUseRouter.extract_computer_use_intent(action3) == "Scroll page"

    def test_extract_intent_none_if_missing(self):
        """Test returns None if no intent field"""
        action = {"other_field": "value"}
        assert ComputerUseRouter.extract_computer_use_intent(action) is None

    def test_extract_approval_level(self):
        """Test approval level extraction"""
        action1 = {"approval_level": "CONFIRM"}
        assert ComputerUseRouter.extract_approval_level(action1) == "CONFIRM"

        action2 = {"approval_level": "SCREEN"}
        assert ComputerUseRouter.extract_approval_level(action2) == "SCREEN"

        action3 = {"approval_level": "TWO_FA"}
        assert ComputerUseRouter.extract_approval_level(action3) == "TWO_FA"

    def test_approval_level_default(self):
        """Test default approval level"""
        action = {}
        assert ComputerUseRouter.extract_approval_level(action) == "CONFIRM"

    def test_approval_level_case_insensitive(self):
        """Test approval level normalization"""
        action = {"approval_level": "confirm"}
        assert ComputerUseRouter.extract_approval_level(action) == "CONFIRM"

    def test_approval_level_invalid_defaults(self):
        """Test invalid approval level defaults to CONFIRM"""
        action = {"approval_level": "INVALID"}
        assert ComputerUseRouter.extract_approval_level(action) == "CONFIRM"

    def test_route_action_computer_use(self):
        """Test routing computer_use action"""
        action_params = {
            "user_intent": "Open website",
            "approval_level": "SCREEN"
        }

        result = ComputerUseRouter.route_action("computer_use", action_params)

        assert result["tool"] == "computer_use"
        assert result["intent"] == "Open website"
        assert result["approval_level"] == "SCREEN"
        assert result["original_action"] == "computer_use"

    def test_route_action_non_computer_use(self):
        """Test routing non-computer_use action"""
        result = ComputerUseRouter.route_action("web_search", {"query": "test"})

        assert result["tool"] is None
        assert "not routed" in result["reason"]

    def test_route_action_fallback_intent(self):
        """Test intent fallback in routing"""
        action_params = {
            "params": {"description": "Do something"}
        }

        result = ComputerUseRouter.route_action("computer_use", action_params)

        assert result["tool"] == "computer_use"
        assert result["intent"] == "Do something"

    def test_singleton_pattern(self):
        """Test singleton returns same instance"""
        router1 = get_computer_use_router()
        router2 = get_computer_use_router()

        assert router1 is router2


class TestRouterIntegrationPatterns:
    """Test router integration patterns"""

    def test_router_in_agent_flow(self):
        """Test router decision in typical agent flow"""
        # Simulate LLM response
        llm_action = {
            "action_type": "computer_use",
            "user_intent": "Navigate to website and extract data",
            "approval_level": "CONFIRM"
        }

        # Router decision
        action_type = llm_action.get("action_type")
        is_computer_use = ComputerUseRouter.should_route_to_computer_use(action_type)

        assert is_computer_use

        # Route the action
        route = ComputerUseRouter.route_action(
            action_type,
            llm_action
        )

        assert route["tool"] == "computer_use"
        assert route["intent"] == llm_action["user_intent"]

    def test_mixed_action_routing(self):
        """Test routing different action types"""
        actions = [
            ("computer_use", {"user_intent": "Click button"}, True),
            ("web_search", {"query": "test"}, False),
            ("ui_automation", {"task": "Fill form"}, True),
            ("chat", {"message": "hello"}, False),
        ]

        for action_type, params, should_route in actions:
            result = ComputerUseRouter.route_action(action_type, params)
            is_routed = result["tool"] == "computer_use"
            assert is_routed == should_route
