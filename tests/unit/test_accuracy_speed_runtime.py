from core.accuracy_speed_runtime import AccuracySpeedRuntime


def test_plan_for_verified_and_maximum_privacy():
    runtime = AccuracySpeedRuntime()

    decision = runtime.plan_for_text(
        text="bu repo'yu araştır ve kaynaklarla doğrula",
        request_kind="research",
        privacy_mode="maximum",
    )

    assert decision.provider_lane == "local_verified"
    assert decision.fallback_policy == "local_only"
    assert decision.verification_level == "strict"


def test_record_execution_updates_latency_bucket():
    runtime = AccuracySpeedRuntime()
    runtime.plan_for_text(text="ekrana bak ve tıkla", request_kind="computer_use")
    runtime.record_execution(
        lane="vision_lane",
        latency_ms=1800,
        success=True,
        fallback_active=True,
        verification_state="strong",
    )

    status = runtime.get_status()
    assert status["current_lane"] == "vision_lane"
    assert status["fallback_active"] is True
    assert status["verification_state"] == "strong"
    assert status["average_latency_bucket"] == "slow"


def test_recommend_collaboration_for_coding_and_research():
    runtime = AccuracySpeedRuntime()

    coding = runtime.recommend_collaboration(
        text="bu repo için production-grade refactor yap ve test açıklarını bul",
        request_kind="coding",
        role="code",
        provider_lane="turbo_hybrid",
    )
    research = runtime.recommend_collaboration(
        text="bu belgeyi kaynaklarla doğrula ve sentezle",
        request_kind="research",
        role="reasoning",
        provider_lane="verified_cloud",
        has_attachments=True,
    )

    assert coding.enabled is True
    assert coding.max_models >= 2
    assert any(item["name"] == "critic" for item in coding.lenses)
    assert research.enabled is True
    assert research.strategy == "read_synthesize_verify"
