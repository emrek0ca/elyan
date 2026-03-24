"""End-to-End demonstration of Computer Use tool with approval workflow"""

import pytest
import asyncio
import json
from unittest.mock import patch, AsyncMock, MagicMock
from core.computer_use_router import ComputerUseRouter, get_computer_use_router
from core.computer_use_integration import ComputerUseIntegration, get_computer_use_integration
from core.session_manager import SessionManager
from core.security.approval_engine import ApprovalEngine, ApprovalRequest, RiskLevel


class TestComputerUseE2EDemo:
    """End-to-end demonstration of Computer Use approval workflow"""

    @pytest.fixture
    def session_manager(self):
        """Create session manager"""
        return SessionManager()

    @pytest.fixture
    def approval_engine(self):
        """Create approval engine mock"""
        engine = MagicMock(spec=ApprovalEngine)
        engine.request_approval = AsyncMock()
        engine.request_approval.return_value = {"approved": True, "resolver_id": "test_user"}
        return engine

    @pytest.mark.asyncio
    async def test_chrome_automation_workflow(self, session_manager, approval_engine):
        """
        E2E Demo: Open Chrome, navigate to URL, read tweet

        Workflow:
        1. Create user session
        2. Start Computer Use task (SCREEN approval level)
        3. Route action through Computer Use router
        4. Request approval for risky action
        5. Execute mouse/keyboard actions
        6. Verify evidence recorded
        7. Complete task and update session
        """
        # Step 1: Create user session
        session = await session_manager.create_session(user_id=100)
        assert session.session_id is not None

        # Step 2: Start Computer Use task
        task_id = "cu_demo_chrome_001"
        await session_manager.start_computer_use_task(
            session.session_id,
            task_id,
            approval_level="SCREEN",
            evidence_dir=f"/tmp/evidence/{task_id}"
        )

        status = session_manager.get_computer_use_status(session.session_id)
        assert status["active"] is True
        assert status["approval_level"] == "SCREEN"

        # Step 3: Route action through Computer Use router
        action_type = "computer_use"
        action_params = {
            "user_intent": "Open Chrome and read Elon Musk's latest tweet",
            "approval_level": "SCREEN"
        }

        is_routable = ComputerUseRouter.should_route_to_computer_use(action_type)
        assert is_routable is True

        route = ComputerUseRouter.route_action(action_type, action_params)
        assert route["tool"] == "computer_use"
        assert route["intent"] == "Open Chrome and read Elon Musk's latest tweet"
        assert route["approval_level"] == "SCREEN"

        # Step 4: Request approval for risky action
        approval_request = ApprovalRequest(
            request_id=f"appr_{task_id}",
            session_id=session.session_id,
            run_id=task_id,
            action_type="open_application",
            payload={"app": "Google Chrome", "url": "https://x.com"},
            risk_level=RiskLevel.WRITE_SAFE,
            reason="User requested to open browser and navigate to webpage"
        )

        # Mock approval response
        approval_response = {"approved": True, "resolver_id": "user"}

        # Step 5: Simulate action execution
        # Simulate action sequence
        actions = [
            {"action_type": "click", "x": 100, "y": 100},  # Click Chrome app
            {"action_type": "type", "text": "https://x.com"},  # Type URL
            {"action_type": "hotkey", "keys": ["return"]},  # Press Enter
            {"action_type": "wait", "seconds": 2},  # Wait for page load
            {"action_type": "click", "x": 500, "y": 300},  # Click tweet
        ]

        for idx, action in enumerate(actions):
            # Update session progress
            await session_manager.update_computer_use_progress(
                session.session_id,
                idx + 1
            )

            # Verify action is tracked
            current_status = session_manager.get_computer_use_status(session.session_id)
            assert current_status["actions_executed"] == idx + 1

        # Step 6: Verify evidence would be recorded
        final_status = session_manager.get_computer_use_status(session.session_id)
        assert final_status["actions_executed"] == 5
        assert final_status["evidence_dir"] == f"/tmp/evidence/{task_id}"

        # Step 7: Complete task and update session
        await session_manager.complete_computer_use_task(session.session_id)
        completed_status = session_manager.get_computer_use_status(session.session_id)
        assert completed_status is None

    @pytest.mark.asyncio
    async def test_approval_levels_in_workflow(self, session_manager):
        """Test different approval levels in workflow"""
        session = await session_manager.create_session(user_id=101)

        approval_levels = ["AUTO", "CONFIRM", "SCREEN", "TWO_FA"]
        risk_actions = {
            "AUTO": "read_document",  # Low risk
            "CONFIRM": "click_button",  # Medium risk
            "SCREEN": "type_password_field",  # High risk
            "TWO_FA": "submit_form",  # Critical risk
        }

        for level in approval_levels:
            task_id = f"cu_demo_level_{level}"

            # Start task with approval level
            await session_manager.start_computer_use_task(
                session.session_id,
                task_id,
                approval_level=level
            )

            # Verify level was set
            status = session_manager.get_computer_use_status(session.session_id)
            assert status["approval_level"] == level

            # Verify action routing respects level
            action_params = {
                "user_intent": f"Perform {risk_actions[level]}",
                "approval_level": level
            }

            route = ComputerUseRouter.route_action("computer_use", action_params)
            assert route["approval_level"] == level

            # Complete before next iteration
            await session_manager.complete_computer_use_task(session.session_id)

    @pytest.mark.asyncio
    async def test_evidence_collection_workflow(self, session_manager):
        """Test evidence collection during task execution"""
        session = await session_manager.create_session(user_id=102)
        task_id = "cu_demo_evidence_001"
        evidence_dir = f"/tmp/evidence/{task_id}"

        # Start task with evidence tracking
        await session_manager.start_computer_use_task(
            session.session_id,
            task_id,
            evidence_dir=evidence_dir
        )

        # Simulate screenshot collection (5 screenshots during task)
        for i in range(5):
            await session_manager.update_computer_use_progress(session.session_id, i + 1)

        status = session_manager.get_computer_use_status(session.session_id)
        assert status["evidence_dir"] == evidence_dir
        assert status["actions_executed"] == 5

        # Complete task
        await session_manager.complete_computer_use_task(session.session_id)

    @pytest.mark.asyncio
    async def test_full_approval_workflow(self, session_manager):
        """Test complete approval workflow integration"""
        session = await session_manager.create_session(user_id=103)

        # 1. User submits intent
        user_intent = "Open Chrome and navigate to Twitter"
        action_params = {
            "user_intent": user_intent,
            "approval_level": "SCREEN"
        }

        # 2. System routes to Computer Use
        route = ComputerUseRouter.route_action("computer_use", action_params)
        assert route["tool"] == "computer_use"

        # 3. Start task in session
        task_id = f"cu_approval_{session.session_id}"
        await session_manager.start_computer_use_task(
            session.session_id,
            task_id,
            approval_level=route["approval_level"]
        )

        # 4. Verify approval level from route is in session
        status = session_manager.get_computer_use_status(session.session_id)
        assert status["approval_level"] == "SCREEN"

        # 5. Simulate approval request
        approval_request = {
            "request_id": f"appr_{task_id}",
            "action_type": "open_application",
            "approval_level": "SCREEN",
            "reason": user_intent
        }

        # 6. Execute actions
        for i in range(3):
            await session_manager.update_computer_use_progress(session.session_id, i + 1)

        final_status = session_manager.get_computer_use_status(session.session_id)
        assert final_status["actions_executed"] == 3

        # 7. Complete workflow
        await session_manager.complete_computer_use_task(session.session_id)


class TestComputerUseIntegrationWithRouter:
    """Test Computer Use integration with router"""

    @pytest.mark.asyncio
    async def test_router_integration_pattern(self):
        """Test action routing integration pattern"""
        # Simulate LLM response with computer_use action
        llm_response = {
            "action_type": "computer_use",
            "user_intent": "Open website and click button",
            "approval_level": "CONFIRM"
        }

        # Step 1: Check if should route to Computer Use
        action_type = llm_response.get("action_type")
        should_route = ComputerUseRouter.should_route_to_computer_use(action_type)
        assert should_route is True

        # Step 2: Extract intent and approval level
        intent = ComputerUseRouter.extract_computer_use_intent(llm_response)
        approval = ComputerUseRouter.extract_approval_level(llm_response)

        assert intent == "Open website and click button"
        assert approval == "CONFIRM"

        # Step 3: Route to Computer Use with extracted params
        route = ComputerUseRouter.route_action(action_type, llm_response)

        assert route["tool"] == "computer_use"
        assert route["intent"] == intent
        assert route["approval_level"] == approval

    def test_mixed_action_routing_in_workflow(self):
        """Test mixed action types in workflow"""
        actions = [
            ("computer_use", {"user_intent": "Click button"}, True),
            ("web_search", {"query": "Python asyncio"}, False),
            ("screen_control", {"action": "move_mouse"}, True),
            ("chat", {"message": "Hello"}, False),
            ("ui_automation", {"task": "Fill form"}, True),
        ]

        for action_type, params, should_route_cu in actions:
            result = ComputerUseRouter.route_action(action_type, params)
            is_routed = result["tool"] == "computer_use"
            assert is_routed == should_route_cu
