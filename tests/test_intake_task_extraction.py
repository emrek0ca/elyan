from core.intake.task_extraction import extract_task_summary


def test_extract_task_summary_flags_urgent_mobile_request():
    summary = extract_task_summary(
        "Acil: yarina kadar landing page sunumu hazirla ve ekibe gonder.",
        source_type="whatsapp",
        title="Musteri mesaji",
    )

    assert summary["task_type"] == "presentation"
    assert summary["urgency"] == "high"
    assert summary["approval_required"] is True
    assert summary["source_type"] == "whatsapp"
    assert summary["recommended_prompt"]
