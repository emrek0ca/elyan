from core.capability_router import CapabilityRouter


def test_capability_router_does_not_match_app_inside_whatsapp():
    router = CapabilityRouter()
    plan = router.route("whatsapp kapat")
    assert plan.domain != "code"


def test_capability_router_routes_screen_status_to_screen_operator():
    router = CapabilityRouter()
    plan = router.route("durum nedir")
    assert plan.domain == "screen_operator"


def test_capability_router_routes_app_control_to_screen_operator():
    router = CapabilityRouter()
    plan = router.route("whatsapp kapat")
    assert plan.domain == "screen_operator"
    assert plan.confidence >= 0.8
    assert plan.primary_action == "vision_operator_loop"


def test_capability_router_keeps_status_prompts_on_screen_workflow():
    router = CapabilityRouter()
    plan = router.route("durum nedir")
    assert plan.domain == "screen_operator"
    assert plan.primary_action == "screen_workflow"


def test_capability_router_routes_multi_step_operator_to_mission_control():
    router = CapabilityRouter()
    plan = router.route("safariyi ac ve sonra maili kontrol et")
    assert plan.domain == "screen_operator"
    assert plan.primary_action == "operator_mission_control"
    assert plan.multi_agent_recommended is True


def test_capability_router_routes_new_tab_app_control_to_screen_operator():
    router = CapabilityRouter()
    plan = router.route("chrome dan yeni sekme aç")
    assert plan.domain == "screen_operator"
    assert plan.primary_action == "vision_operator_loop"


def test_capability_router_builds_web_request_contract_for_landing_pages():
    router = CapabilityRouter()
    contract = router.build_request_contract(
        "landing page üret html olarak kaydet",
        domain="website",
        confidence=0.78,
        route_mode="code",
    )

    assert contract.content_kind == "web_project"
    assert "html" in contract.output_formats
    assert contract.style_profile == "executive" or contract.style_profile == "implementation"
    assert contract.preview


def test_capability_router_requests_clarification_for_ambiguous_requests():
    router = CapabilityRouter()
    contract = router.build_request_contract(
        "bir şey hazırla",
        domain="general",
        confidence=0.3,
        route_mode="task",
    )

    assert contract.needs_clarification is True
    assert contract.clarifying_question
    assert "netleştirme" in contract.preview or "gerekebilir" in contract.preview
