from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from core.agents.ai_decision_journal import run_ai_decision_journal_module
from core.agents.automatic_learning_tracker import run_automatic_learning_tracker_module
from core.agents.context_recovery import run_context_recovery_module
from core.agents.deep_work_protector import run_deep_work_protector_module
from core.agents.digital_time_auditor import run_digital_time_auditor_module
from core.agents.invisible_meeting_assistant import run_invisible_meeting_assistant_module
from core.agents.life_admin_automation import run_life_admin_automation_module
from core.agents.personal_knowledge_miner import run_personal_knowledge_miner_module
from core.agents.project_reality_check import run_project_reality_check_module
from core.agents.website_change_intelligence import run_website_change_intelligence_module


@dataclass(frozen=True)
class AgentModuleSpec:
    module_id: str
    name: str
    description: str
    category: str
    default_interval_seconds: int = 3600
    data_sources: list[str] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "default_interval_seconds": int(self.default_interval_seconds),
            "data_sources": list(self.data_sources),
            "deliverables": list(self.deliverables),
        }


ModuleRunner = Callable[[dict[str, Any] | None], Awaitable[dict[str, Any]]]


_CATALOG: dict[str, AgentModuleSpec] = {
    "context_recovery": AgentModuleSpec(
        module_id="context_recovery",
        name="Context Recovery",
        description="Restores yesterday's working context from code, runs, notes, and shell activity.",
        category="productivity",
        default_interval_seconds=24 * 3600,
        data_sources=["run_store", "desktop_host_state", "git_status", "terminal_history", "notes"],
        deliverables=["morning_recovery_dashboard", "priority_next_steps"],
    ),
    "automatic_learning_tracker": AgentModuleSpec(
        module_id="automatic_learning_tracker",
        name="Automatic Learning Tracker",
        description="Tracks learning signals from web/video/repo activity and maps them to a topic graph.",
        category="learning",
        default_interval_seconds=4 * 3600,
        data_sources=["browser_history", "notes", "bookmarks", "repo_activity"],
        deliverables=["learning_graph", "knowledge_gaps", "next_learning_targets"],
    ),
    "invisible_meeting_assistant": AgentModuleSpec(
        module_id="invisible_meeting_assistant",
        name="Invisible Meeting Assistant",
        description="Summarizes meetings and filters only user-relevant segments.",
        category="meetings",
        default_interval_seconds=3600,
        data_sources=["meeting_transcripts", "calendar", "project_context"],
        deliverables=["relevance_filtered_summary", "action_items", "time_saved_report"],
    ),
    "website_change_intelligence": AgentModuleSpec(
        module_id="website_change_intelligence",
        name="Website Change Intelligence",
        description="Detects and classifies strategic website changes (feature, pricing, positioning).",
        category="market_intel",
        default_interval_seconds=6 * 3600,
        data_sources=["tracked_urls", "historical_snapshots", "diff_signals"],
        deliverables=["change_digest", "strategic_impact_notes"],
    ),
    "life_admin_automation": AgentModuleSpec(
        module_id="life_admin_automation",
        name="Life Admin Automation",
        description="Extracts admin tasks from inbox flow and converts them into scheduled automations.",
        category="ops",
        default_interval_seconds=2 * 3600,
        data_sources=["email", "calendar", "billing_docs"],
        deliverables=["detected_admin_tasks", "auto_generated_workflows"],
    ),
    "deep_work_protector": AgentModuleSpec(
        module_id="deep_work_protector",
        name="Deep Work Protector",
        description="Detects distraction patterns and applies adaptive focus protection actions.",
        category="focus",
        default_interval_seconds=15 * 60,
        data_sources=["app_usage", "browser_domains", "notification_signals"],
        deliverables=["focus_state", "interventions", "focus_score"],
    ),
    "ai_decision_journal": AgentModuleSpec(
        module_id="ai_decision_journal",
        name="AI Decision Journal",
        description="Captures major decisions and measures long-term outcome quality.",
        category="decision_intel",
        default_interval_seconds=12 * 3600,
        data_sources=["notes", "task_history", "project_milestones"],
        deliverables=["decision_log", "decision_quality_metrics"],
    ),
    "personal_knowledge_miner": AgentModuleSpec(
        module_id="personal_knowledge_miner",
        name="AI Personal Knowledge Miner",
        description="Builds a personal expertise graph from files, notes, and code artifacts.",
        category="knowledge",
        default_interval_seconds=24 * 3600,
        data_sources=["documents", "codebase", "notes", "email"],
        deliverables=["expertise_graph", "topic_confidence_map"],
    ),
    "project_reality_check": AgentModuleSpec(
        module_id="project_reality_check",
        name="Project Reality Check",
        description="Evaluates project feasibility across technical, cost, and execution risk.",
        category="strategy",
        default_interval_seconds=24 * 3600,
        data_sources=["roadmaps", "plans", "resource_constraints", "market_inputs"],
        deliverables=["feasibility_score", "risk_register", "recommendation"],
    ),
    "digital_time_auditor": AgentModuleSpec(
        module_id="digital_time_auditor",
        name="Digital Time Auditor",
        description="Builds a productivity-aware daily time allocation report.",
        category="productivity",
        default_interval_seconds=24 * 3600,
        data_sources=["app_usage", "browser_activity", "task_events"],
        deliverables=["time_allocation_report", "distraction_ratio", "improvement_actions"],
    ),
}


_RUNNERS: dict[str, ModuleRunner] = {
    "context_recovery": run_context_recovery_module,
    "automatic_learning_tracker": run_automatic_learning_tracker_module,
    "website_change_intelligence": run_website_change_intelligence_module,
    "invisible_meeting_assistant": run_invisible_meeting_assistant_module,
    "life_admin_automation": run_life_admin_automation_module,
    "deep_work_protector": run_deep_work_protector_module,
    "ai_decision_journal": run_ai_decision_journal_module,
    "personal_knowledge_miner": run_personal_knowledge_miner_module,
    "project_reality_check": run_project_reality_check_module,
    "digital_time_auditor": run_digital_time_auditor_module,
}


def list_agent_modules() -> list[dict[str, Any]]:
    modules = [spec.to_dict() for spec in _CATALOG.values()]
    modules.sort(key=lambda item: str(item.get("module_id") or ""))
    return modules


def get_agent_module_spec(module_id: str) -> dict[str, Any] | None:
    key = str(module_id or "").strip().lower()
    spec = _CATALOG.get(key)
    return spec.to_dict() if spec else None


async def run_agent_module(module_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    key = str(module_id or "").strip().lower()
    spec = _CATALOG.get(key)
    if spec is None:
        return {
            "success": False,
            "module_id": key,
            "error": "module_not_found",
        }

    runner = _RUNNERS.get(key)
    if runner is None:
        return {
            "success": True,
            "module_id": key,
            "status": "planned_only",
            "message": "Module spec is registered; execution runner is not implemented yet.",
            "spec": spec.to_dict(),
        }

    result = await runner(payload or {})
    if not isinstance(result, dict):
        result = {"success": bool(result), "module_id": key, "result": result}
    result.setdefault("module_id", key)
    return result


__all__ = [
    "AgentModuleSpec",
    "get_agent_module_spec",
    "list_agent_modules",
    "run_agent_module",
]
