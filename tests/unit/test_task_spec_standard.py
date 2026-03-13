from core.spec.task_spec_standard import coerce_task_spec_standard


def test_coerce_task_spec_standard_adds_slots_and_success_criteria():
    spec = {
        "intent": "general_batch",
        "version": "1.1",
        "goal": "safari ac",
        "steps": [
            {
                "id": "step_1",
                "action": "open_app",
                "params": {"app_name": "Safari"},
                "checks": [{"type": "tool_success"}],
            }
        ],
    }
    intent_payload = {"action": "open_app", "params": {"app_name": "Safari"}, "confidence": 0.86}

    out = coerce_task_spec_standard(
        spec,
        user_input="safari ac",
        intent_payload=intent_payload,
        intent_confidence=0.86,
    )

    assert isinstance(out.get("slots"), dict)
    assert str(out.get("task_id") or "").startswith("open_app_")
    assert out.get("user_goal") == "safari ac"
    assert isinstance(out.get("entities"), dict)
    assert out["entities"].get("app_name") == "Safari"
    assert isinstance(out.get("deliverables"), list) and out["deliverables"]
    assert out["deliverables"][0]["required"] is True
    assert isinstance(out.get("tool_candidates"), list) and out["tool_candidates"]
    assert out.get("priority") == "normal"
    assert out.get("risk_level") == "low"
    assert out["slots"].get("app_name") == "Safari"
    assert isinstance(out.get("success_criteria"), list)
    assert len(out["success_criteria"]) >= 1
    assert isinstance(out.get("steps"), list) and out["steps"]
    step = out["steps"][0]
    assert isinstance(step.get("depends_on"), list)
    assert isinstance(step.get("success_criteria"), list)
    assert len(step["success_criteria"]) >= 1
    assert float(out.get("confidence", 0.0)) == 0.86
