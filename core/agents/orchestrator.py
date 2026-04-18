from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import uuid

from core.agents.code_scout import CodeScoutAgent
from core.agents.message_bus import get_agent_bus
from core.multi_agent.message_bus import AgentMessage
from utils.logger import get_logger

logger = get_logger("agents.orchestrator")


@dataclass(slots=True)
class OrchestrationStep:
    """A deterministic step in a small sub-agent plan."""

    kind: str
    title: str
    description: str
    workspace: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "description": self.description,
            "workspace": self.workspace,
            "metadata": dict(self.metadata),
        }


class DevAgentOrchestrator:
    """Minimal production-safe orchestrator for developer workflows.

    The class is intentionally small: it creates a stable plan structure and
    delegates actual intelligence to existing workspace-scanning and message
    bus infrastructure.
    """

    def __init__(
        self,
        *,
        scout: CodeScoutAgent | None = None,
        message_bus: Any | None = None,
    ) -> None:
        self._scout = scout or CodeScoutAgent()
        self._message_bus = message_bus or get_agent_bus()

    def build_plan(
        self,
        objective: str,
        *,
        workspace: str | Path | None = None,
    ) -> list[OrchestrationStep]:
        """Build a small, auditable execution plan.

        The first step always scouts the workspace. A verify step is always
        included so callers can deterministically assert the plan shape.
        """

        prompt = " ".join(str(objective or "").strip().split())
        workspace_path = str(Path(workspace).expanduser().resolve()) if workspace else ""
        query_hint = self._infer_query_hint(prompt)
        job_id = f"job_{uuid.uuid4().hex[:10]}"

        steps = [
            OrchestrationStep(
                kind="scout",
                title="Workspace scout",
                description="Inspect the affected surface before changing code.",
                workspace=workspace_path,
                metadata={
                    "job_id": job_id,
                    "query": query_hint,
                    "scout": "code",
                },
            ),
            OrchestrationStep(
                kind="plan",
                title="Implementation plan",
                description="Translate the findings into a minimal, safe change set.",
                workspace=workspace_path,
                metadata={"job_id": job_id},
            ),
            OrchestrationStep(
                kind="execute",
                title="Targeted implementation",
                description="Apply the smallest production-safe fix that satisfies the objective.",
                workspace=workspace_path,
                metadata={"job_id": job_id},
            ),
            OrchestrationStep(
                kind="verify",
                title="Verification pass",
                description="Run the relevant checks and inspect the output before delivery.",
                workspace=workspace_path,
                metadata={"job_id": job_id, "requires_validation": True},
            ),
        ]

        self._publish_plan(prompt=prompt, steps=steps)
        return steps

    async def orchestrate(
        self,
        objective: str,
        *,
        workspace: str | Path | None = None,
    ) -> dict[str, Any]:
        """Execute a low-risk orchestration pass.

        This method stays intentionally conservative: it produces a plan,
        emits a message-bus event if the bus supports it, and returns the
        plan for downstream execution.
        """

        steps = self.build_plan(objective, workspace=workspace)
        payload = {
            "objective": " ".join(str(objective or "").strip().split()),
            "steps": [step.to_dict() for step in steps],
        }
        await self._emit("orchestrator.plan.built", payload)
        return payload

    def _infer_query_hint(self, prompt: str) -> str:
        lowered = prompt.lower()
        if any(token in lowered for token in ("auth", "login", "session")):
            return "auth session login"
        if any(token in lowered for token in ("fatura", "logo", "sgk", "kep")):
            return "turkey connector"
        if any(token in lowered for token in ("test", "verify", "check")):
            return "test verify"
        return "workspace code"

    def _publish_plan(self, *, prompt: str, steps: list[OrchestrationStep]) -> None:
        if self._message_bus is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._publish_plan_async(prompt=prompt, steps=steps))

    async def _publish_plan_async(self, *, prompt: str, steps: list[OrchestrationStep]) -> None:
        publish = getattr(self._message_bus, "publish", None)
        if not callable(publish):
            return
        try:
            await publish(
                AgentMessage(
                    topic="agents.orchestrator.plan_built",
                    from_agent="dev_agent_orchestrator",
                    payload={
                        "objective": prompt,
                        "steps": [step.to_dict() for step in steps],
                    },
                )
            )
        except Exception:
            logger.debug("Plan publish skipped", exc_info=True)

    async def _emit(self, topic: str, payload: dict[str, Any]) -> None:
        publish = getattr(self._message_bus, "publish", None)
        if not callable(publish):
            return
        try:
            await publish(
                AgentMessage(
                    topic=topic,
                    from_agent="dev_agent_orchestrator",
                    payload=dict(payload or {}),
                )
            )
        except Exception:
            logger.debug("Orchestrator event emit skipped", exc_info=True)


__all__ = ["DevAgentOrchestrator", "OrchestrationStep"]
