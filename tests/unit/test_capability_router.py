from core.capability_router import get_capability_router


def test_capability_router_research_defaults_to_document_workflow():
    plan = get_capability_router().route("Fourier serileri hakkında kapsamlı araştırma yap")
    assert plan.domain == "research"
    assert plan.workflow_id == "research_workflow"
    assert plan.primary_action == "research_document_delivery"
    assert "research_document_delivery" in plan.preferred_tools


def test_capability_router_screen_routes_to_screen_workflow():
    plan = get_capability_router().route("ekrana bak ve ne olduğunu söyle")
    assert plan.domain == "screen_operator"
    assert plan.workflow_id == "screen_operator_workflow"
    assert plan.primary_action == "screen_workflow"


def test_capability_router_code_routes_to_coding_workflow():
    plan = get_capability_router().route("python ile script yaz ve test et")
    assert plan.domain == "code"
    assert plan.workflow_id == "coding_workflow"
    assert plan.primary_action == "create_coding_project"
