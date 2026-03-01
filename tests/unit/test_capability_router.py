from core.capability_router import CapabilityRouter


def test_capability_router_detects_api_integration_domain():
    router = CapabilityRouter()
    plan = router.route("REST API endpoint health check yap ve sonucu raporla")

    assert plan.domain == "api_integration"
    assert plan.suggested_job_type == "api_integration"
    assert "http_request" in plan.preferred_tools
    assert 0.0 <= plan.confidence <= 1.0


def test_capability_router_detects_full_stack_delivery_and_multi_agent_hint():
    router = CapabilityRouter()
    plan = router.route(
        "Uctan uca full stack dashboard website ve backend api entegrasyonu kur, deployment plani cikart"
    )

    assert plan.domain == "full_stack_delivery"
    assert plan.complexity_tier in {"high", "extreme"}
    assert plan.multi_agent_recommended is True
    assert plan.orchestration_mode == "multi_agent"


def test_capability_router_general_fallback_for_simple_chat():
    router = CapabilityRouter()
    plan = router.route("Merhaba nasilsin")

    assert plan.domain == "general"
    assert plan.suggested_job_type == "communication"
    assert plan.multi_agent_recommended is False
