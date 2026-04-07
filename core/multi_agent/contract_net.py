from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.observability.logger import get_structured_logger

slog = get_structured_logger("contract_net")


@dataclass(slots=True)
class TaskAnnouncement:
    task_id: str
    description: str
    required_capabilities: List[str] = field(default_factory=list)
    deadline_ms: int = 0
    priority: int = 0


@dataclass(slots=True)
class Bid:
    agent_id: str
    task_id: str
    estimated_time_ms: int
    confidence: float
    cost_units: float


@dataclass(slots=True)
class AgentProfile:
    agent_id: str
    capabilities: List[str] = field(default_factory=list)
    max_concurrent: int = 2
    current_load: int = 0


class ContractNetProtocol:
    ACTION_CAPABILITIES: dict[str, list[str]] = {
        "advanced_research": ["web_search", "summarization", "fact_extraction"],
        "research": ["web_search", "summarization"],
        "summarize_document": ["summarization"],
        "write_word": ["document_generation", "file_write"],
        "write_excel": ["document_generation", "file_write"],
        "write_presentation": ["presentation_generation", "file_write"],
        "create_report": ["document_generation", "summarization"],
        "search_files": ["file_search"],
        "list_files": ["file_search"],
        "read_file": ["file_read"],
        "write_file": ["file_write"],
        "edit_text_file": ["file_write"],
        "create_folder": ["filesystem"],
        "move_file": ["filesystem"],
        "copy_file": ["filesystem"],
        "rename_file": ["filesystem"],
        "delete_file": ["filesystem"],
        "open_url": ["browser"],
        "web_search": ["web_search"],
        "analyze_screen": ["screenshot", "ocr"],
        "take_screenshot": ["screenshot"],
        "computer_use": ["ui_automation"],
        "run_safe_command": ["code_execution"],
        "create_coding_project": ["task_decomposition", "code_execution", "testing"],
        "research_document_delivery": ["web_search", "summarization", "file_write"],
        "api_health_check": ["network"],
        "http_request": ["network"],
        "api_health_get_save": ["network", "file_write"],
    }

    def __init__(self):
        self.registered_agents: Dict[str, AgentProfile] = {}
        self.active_contracts: Dict[str, str] = {}
        self._bid_handlers: Dict[str, Callable[[TaskAnnouncement, AgentProfile], Bid]] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register_agent("research_agent", ["web_search", "summarization", "fact_extraction"])
        self.register_agent("vision_agent", ["screenshot", "ocr", "ui_automation"])
        self.register_agent("planning_agent", ["task_decomposition", "llm_reasoning"])
        self.register_agent("code_agent", ["code_execution", "ast_analysis", "testing"])
        self.register_agent("document_agent", ["document_generation", "presentation_generation", "summarization", "file_write"])
        self.register_agent("thinking_agent", ["llm_reasoning", "task_decomposition", "synthesis"])
        self.register_agent("approval_agent", ["approval_handling", "user_notification"])

    def register_agent(self, agent_id: str, capabilities: List[str], max_concurrent: int = 2) -> None:
        self.registered_agents[agent_id] = AgentProfile(
            agent_id=agent_id,
            capabilities=list(capabilities or []),
            max_concurrent=int(max_concurrent),
            current_load=0,
        )

    @classmethod
    def infer_required_capabilities(cls, action: str, *, owner: str = "", params: dict[str, Any] | None = None) -> list[str]:
        token = str(action or "").strip().lower()
        owner_token = str(owner or "").strip().lower()
        capabilities = list(cls.ACTION_CAPABILITIES.get(token, []))
        if not capabilities:
            if any(marker in token for marker in ("research", "search", "summar", "report")) or owner_token == "researcher":
                capabilities = ["web_search", "summarization"]
            elif any(marker in token for marker in ("write", "create", "build", "generate", "edit")) or owner_token == "builder":
                capabilities = ["file_write"]
            elif any(marker in token for marker in ("read", "list", "move", "copy", "rename", "delete")) or owner_token == "ops":
                capabilities = ["filesystem"]
            elif any(marker in token for marker in ("verify", "qa", "test", "lint")) or owner_token == "qa":
                capabilities = ["testing"]
            else:
                capabilities = ["llm_reasoning"]
        if isinstance(params, dict) and params.get("url") and "network" not in capabilities:
            capabilities.append("network")
        return list(dict.fromkeys(capabilities))

    @staticmethod
    def specialist_for_agent(agent_id: str) -> str:
        token = str(agent_id or "").strip().lower()
        mapping = {
            "research_agent": "research_agent",
            "vision_agent": "ops",
            "planning_agent": "thinking_agent",
            "code_agent": "code_agent",
            "document_agent": "document_agent",
            "thinking_agent": "thinking_agent",
            "approval_agent": "qa",
        }
        return mapping.get(token, "worker")

    def set_bid_handler(self, agent_id: str, handler: Callable[[TaskAnnouncement, AgentProfile], Bid]) -> None:
        self._bid_handlers[agent_id] = handler

    async def allocate_task(self, announcement: TaskAnnouncement) -> Optional[str]:
        eligible = [
            agent for agent in self.registered_agents.values()
            if agent.current_load < agent.max_concurrent
            and all(cap in agent.capabilities for cap in announcement.required_capabilities)
        ]
        if not eligible:
            return None
        bids = await asyncio.gather(*(self._request_bid(agent, announcement) for agent in eligible), return_exceptions=True)
        valid_bids: List[Bid] = [bid for bid in bids if isinstance(bid, Bid)]
        if not valid_bids:
            return None
        best_bid = min(valid_bids, key=self._utility)
        agent = self.registered_agents.get(best_bid.agent_id)
        if agent is None:
            return None
        agent.current_load += 1
        self.active_contracts[announcement.task_id] = best_bid.agent_id
        return best_bid.agent_id

    async def _request_bid(self, agent: AgentProfile, task: TaskAnnouncement) -> Bid:
        handler = self._bid_handlers.get(agent.agent_id)
        if handler is not None:
            result = handler(task, agent)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        load_factor = agent.current_load / max(agent.max_concurrent, 1)
        estimated_time = int(2000 * (1 + load_factor))
        confidence = max(0.3, 1.0 - load_factor)
        cost = 1.0 + load_factor * 2
        return Bid(agent.agent_id, task.task_id, estimated_time, confidence, cost)

    def _utility(self, bid: Bid) -> float:
        return bid.estimated_time_ms * 0.5 + bid.cost_units * 0.3 + (1.0 - bid.confidence) * 1000.0

    def report_completion(self, task_id: str, agent_id: str, success: bool) -> None:
        agent = self.registered_agents.get(agent_id)
        if agent is not None:
            agent.current_load = max(0, agent.current_load - 1)
        self.active_contracts.pop(task_id, None)
        try:
            from core.elyan_runtime import get_elyan_runtime

            runtime = get_elyan_runtime()
            runtime.record_tool_outcome("multi_agent", agent_id, bool(success), 0.0, user_satisfaction=0.7 if success else 0.2)
        except Exception:
            pass
        slog.log_event(
            "contract_completion",
            {"task_id": task_id, "agent_id": agent_id, "success": success},
        )
