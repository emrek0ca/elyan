"""
core/multi_agent/orchestrator_bridge.py
───────────────────────────────────────────────────────────────────────────────
Orchestrator ↔ Infrastructure Bridge

Cleanly connects the AgentOrchestrator to the new subsystems:
  - AgentMessageBus   (inter-agent communication)
  - AgentTaskTracker   (task lifecycle + metrics)
  - ModelSelectionPolicy (LLM selection per specialist call)

Design:
  This module is a *bridge*, not a modification of orchestrator.py.
  It wraps orchestrator lifecycle hooks so that:
    1. Each job creates an AgentTask tracked by the TaskTracker
    2. Specialist invocations publish messages to the MessageBus
    3. Model selection is delegated to ModelSelectionPolicy when available
    4. Results and failures are recorded for the learning loop

  The bridge is opt-in: if subsystems are unavailable, the orchestrator
  still works exactly as before (graceful degradation).

Integration point:
  Called from `manage_flow()` via `OrchestratorBridge.wrap_flow(...)`.
"""

from __future__ import annotations

import time
from typing import Any

from core.observability.logger import get_structured_logger

slog = get_structured_logger("orchestrator_bridge")


class OrchestratorBridge:
    """Bridges the orchestrator to MessageBus, TaskTracker, and ModelSelectionPolicy."""

    def __init__(self) -> None:
        self._bus = _safe_get_bus()
        self._tracker = _safe_get_tracker()
        self._model_policy = _safe_get_model_policy()

    # ── Job lifecycle ───────────────────────────────────────────────────────

    async def on_job_started(self, job_id: str, template_id: str, input_text: str) -> str | None:
        """Called when a new orchestrator job begins.

        Creates an AgentTask and registers it with the tracker.
        Returns the task_id for correlation, or None if tracker unavailable.
        """
        if self._tracker is None:
            return None

        from core.multi_agent.agent_task import AgentTask

        task = AgentTask(
            task_id=job_id,
            objective=f"{template_id}: {input_text[:180]}",
            assigned_to="orchestrator",
            priority=50,
        )
        try:
            await self._tracker.register(task)
            await self._tracker.start(task.task_id)
            slog.log_event("bridge.job_started", {
                "job_id": job_id,
                "template_id": template_id,
            })
        except Exception as exc:
            slog.log_event("bridge.job_start_failed", {"error": str(exc)}, level="warning")
        return task.task_id

    async def on_job_completed(self, job_id: str, result: dict[str, Any] | None = None) -> None:
        """Called when a job completes successfully."""
        if self._tracker is None:
            return
        try:
            await self._tracker.complete(job_id, result)
            slog.log_event("bridge.job_completed", {"job_id": job_id})
        except Exception as exc:
            slog.log_event("bridge.job_complete_failed", {"error": str(exc)}, level="warning")

    async def on_job_failed(self, job_id: str, error: str) -> None:
        """Called when a job fails."""
        if self._tracker is None:
            return
        try:
            await self._tracker.fail(job_id, error)
            slog.log_event("bridge.job_failed", {"job_id": job_id, "error": error[:120]})
        except Exception as exc:
            slog.log_event("bridge.job_fail_record_failed", {"error": str(exc)}, level="warning")

    # ── Specialist invocation ───────────────────────────────────────────────

    async def on_specialist_called(
        self,
        job_id: str,
        specialist_key: str,
        prompt_preview: str,
    ) -> str | None:
        """Called before a specialist is invoked.

        Creates a child task and publishes a bus message.
        Returns the child task_id, or None.
        """
        child_task_id = f"{job_id}:{specialist_key}:{int(time.time() * 1000) % 100000}"

        # Register child task
        if self._tracker is not None:
            from core.multi_agent.agent_task import AgentTask

            child = AgentTask(
                task_id=child_task_id,
                parent_task_id=job_id,
                objective=f"specialist:{specialist_key}",
                assigned_to=specialist_key,
                priority=40,
            )
            try:
                await self._tracker.register(child)
                await self._tracker.start(child.task_id)
            except Exception:
                pass

        # Publish to message bus
        if self._bus is not None:
            from core.multi_agent.message_bus import AgentMessage

            try:
                await self._bus.publish(AgentMessage(
                    topic="orchestrator.specialist.invoked",
                    from_agent="orchestrator",
                    to_agent=specialist_key,
                    payload={
                        "job_id": job_id,
                        "specialist": specialist_key,
                        "prompt_preview": prompt_preview[:200],
                    },
                    correlation_id=job_id,
                ))
            except Exception:
                pass

        return child_task_id

    async def on_specialist_completed(
        self,
        child_task_id: str,
        specialist_key: str,
        success: bool,
        latency_ms: float,
        model_used: str = "",
    ) -> None:
        """Called after a specialist returns."""
        # Update task tracker
        if self._tracker is not None:
            try:
                if success:
                    await self._tracker.complete(child_task_id)
                else:
                    await self._tracker.fail(child_task_id, "specialist_call_failed")
            except Exception:
                pass

        # Record outcome for model selection learning
        if self._model_policy is not None and model_used:
            provider, _, model = model_used.partition("/")
            if not model:
                model = provider
                provider = _infer_provider(model)
            try:
                self._model_policy.record_outcome(provider, model, success, latency_ms)
            except Exception:
                pass

        # Publish result to bus
        if self._bus is not None:
            from core.multi_agent.message_bus import AgentMessage

            try:
                await self._bus.publish(AgentMessage(
                    topic="orchestrator.specialist.completed",
                    from_agent=specialist_key,
                    payload={
                        "child_task_id": child_task_id,
                        "specialist": specialist_key,
                        "success": success,
                        "latency_ms": round(latency_ms, 1),
                        "model": model_used,
                    },
                ))
            except Exception:
                pass

    # ── Model selection ─────────────────────────────────────────────────────

    def select_model_for_specialist(
        self,
        specialist_key: str,
        *,
        preferred_model: str = "",
        is_local_first: bool = True,
        cloud_allowed: bool = False,
        capabilities: set[str] | None = None,
        complexity: str = "moderate",
        context_tokens: int = 4000,
    ) -> dict[str, Any] | None:
        """Consult the ModelSelectionPolicy for the best model.

        Returns a dict with {provider, model, is_local, score, reason}
        or None if the policy is unavailable (caller should use default).
        """
        if self._model_policy is None:
            return None

        from core.llm.model_selection_policy import (
            CapabilityTag,
            Complexity,
            PrivacyLevel,
            SelectionRequest,
        )

        # Map specialist flags to privacy level
        if not cloud_allowed:
            privacy = PrivacyLevel.SENSITIVE  # Force local
        elif is_local_first:
            privacy = PrivacyLevel.INTERNAL   # Prefer local
        else:
            privacy = PrivacyLevel.PUBLIC      # No restriction

        # Map complexity string to enum
        complexity_map = {
            "trivial": Complexity.TRIVIAL,
            "simple": Complexity.SIMPLE,
            "moderate": Complexity.MODERATE,
            "complex": Complexity.COMPLEX,
            "expert": Complexity.EXPERT,
        }
        cx = complexity_map.get(complexity, Complexity.MODERATE)

        # Build capabilities set
        caps = capabilities or {CapabilityTag.CHAT.value, CapabilityTag.CODE.value}

        try:
            request = SelectionRequest(
                privacy=privacy,
                complexity=cx,
                capabilities_needed=caps,
                context_tokens=context_tokens,
                agent_id=specialist_key,
                task_type=specialist_key,
            )
            decision = self._model_policy.select(request)
            return decision.to_dict()
        except Exception as exc:
            slog.log_event("bridge.model_select_failed", {
                "specialist": specialist_key,
                "error": str(exc),
            }, level="warning")
            return None

    # ── Phase events ────────────────────────────────────────────────────────

    async def on_phase_started(self, job_id: str, phase: str) -> None:
        """Publish a phase transition event to the message bus."""
        if self._bus is None:
            return
        from core.multi_agent.message_bus import AgentMessage

        try:
            await self._bus.publish(AgentMessage(
                topic=f"orchestrator.phase.{phase}",
                from_agent="orchestrator",
                payload={"job_id": job_id, "phase": phase, "ts": time.time()},
                correlation_id=job_id,
            ))
        except Exception:
            pass

    async def on_qa_result(self, job_id: str, passed: bool, issues: list[str]) -> None:
        """Publish QA result to message bus."""
        if self._bus is None:
            return
        from core.multi_agent.message_bus import AgentMessage

        try:
            await self._bus.publish(AgentMessage(
                topic="orchestrator.qa.result",
                from_agent="qa_pipeline",
                payload={
                    "job_id": job_id,
                    "passed": passed,
                    "issue_count": len(issues),
                    "issues_preview": issues[:5],
                },
                correlation_id=job_id,
            ))
        except Exception:
            pass

    # ── Metrics ─────────────────────────────────────────────────────────────

    def get_metrics(self) -> dict[str, Any]:
        """Aggregate metrics from the tracker."""
        if self._tracker is None:
            return {"tracker": "unavailable"}
        try:
            return self._tracker.metrics()
        except Exception:
            return {"tracker": "error"}


# ── Safe subsystem accessors ────────────────────────────────────────────────


def _safe_get_bus():
    """Get MessageBus or None if not available."""
    try:
        from core.multi_agent.message_bus import get_message_bus
        return get_message_bus()
    except Exception:
        return None


def _safe_get_tracker():
    """Get TaskTracker or None if not available."""
    try:
        from core.multi_agent.task_tracker import get_task_tracker
        return get_task_tracker()
    except Exception:
        return None


def _safe_get_model_policy():
    """Get ModelSelectionPolicy or None if not available."""
    try:
        from core.llm.model_selection_policy import get_model_selection_policy
        return get_model_selection_policy()
    except Exception:
        return None


def _infer_provider(model: str) -> str:
    """Best-effort provider inference from model name."""
    m = model.lower()
    if "gpt" in m or "o1" in m:
        return "openai"
    if "claude" in m:
        return "anthropic"
    if "gemini" in m:
        return "google"
    if "llama" in m and "groq" not in m:
        return "ollama"
    if "qwen" in m or "deepseek" in m:
        return "ollama"
    return "unknown"


# ── Singleton ───────────────────────────────────────────────────────────────

_bridge_instance: OrchestratorBridge | None = None


def get_orchestrator_bridge() -> OrchestratorBridge:
    """Get or create the singleton OrchestratorBridge."""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = OrchestratorBridge()
    return _bridge_instance


__all__ = ["OrchestratorBridge", "get_orchestrator_bridge"]
