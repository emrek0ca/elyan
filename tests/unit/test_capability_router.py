from core.capability_router import get_capability_router
from core.process_profiles import approval_granted


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
    assert plan.workflow_profile_applicable is True
    assert plan.requires_design_phase is True
    assert plan.requires_worktree is False


def test_capability_router_full_stack_requires_worktree():
    plan = get_capability_router().route("production için uçtan uca full stack dashboard mimarisi kur")
    assert plan.domain == "full_stack_delivery"
    assert plan.workflow_profile_applicable is True
    assert plan.requires_design_phase is True
    assert plan.requires_worktree is True


def test_approval_granted_uses_explicit_tokens_only():
    assert approval_granted("go") is True
    assert approval_granted("devam et") is True
    assert approval_granted("logo varyasyonu üret") is False
