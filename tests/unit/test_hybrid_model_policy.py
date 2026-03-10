from core.hybrid_model_policy import build_hybrid_model_plan
from core.model_orchestrator import ModelOrchestrator


def test_hybrid_model_policy_routes_research_to_strong_worker():
    plan = build_hybrid_model_plan("research", "research_workflow", current_role="inference")
    assert plan.role == "research_worker"
    assert plan.tool_first is False
    assert plan.tier == "strong"


def test_hybrid_model_policy_routes_screen_to_tool_first_router():
    plan = build_hybrid_model_plan("screen_operator", "screen_operator_workflow", current_role="reasoning")
    assert plan.role == "router"
    assert plan.tool_first is True
    assert plan.prefer_local is True


def test_model_orchestrator_prefers_local_for_router_role():
    orchestrator = ModelOrchestrator()
    orchestrator.providers = {
        "ollama": {"type": "ollama", "model": "llama3.1:8b", "status": "configured"},
        "openai": {"type": "openai", "model": "gpt-4o", "status": "configured"},
    }
    selected = orchestrator.get_best_available("router")
    assert selected["type"] == "ollama"


def test_model_orchestrator_prefers_strong_cloud_for_research_worker():
    orchestrator = ModelOrchestrator()
    orchestrator.providers = {
        "ollama": {"type": "ollama", "model": "llama3.1:8b", "status": "configured"},
        "openai": {"type": "openai", "model": "gpt-4o", "status": "configured"},
    }
    selected = orchestrator.get_best_available("research_worker")
    assert selected["type"] == "openai"
