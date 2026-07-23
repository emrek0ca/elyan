from __future__ import annotations

import pytest
from pathlib import Path

from runtime import bridge, state_store
from runtime.task_router import route_text_to_tool


def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(state_store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(state_store, "STATE_PATH", tmp_path / "elyan_state.json")
    monkeypatch.setattr(state_store, "LEGACY_STATE_PATH", tmp_path / "legacy.json")


PROFESSIONAL_WORKFLOW_CASES = [
    pytest.param(
        "legal_defense",
        "Avukat gibi çalış. Kira uyuşmazlığını araştır, dosya özetini analiz et ve savunma dilekçesi taslağı hazırla.",
        ["web_research", "document_write"],
        id="legal-defense-draft",
    ),
    pytest.param(
        "accounting_research_report",
        "Muhasebeci gibi çalış. 12000 TL ve 8500 TL hizmet faturası için yüzde 20 KDV hesapla, KDV kurallarını araştır ve rapor belgesi hazırla.",
        ["math_solve", "web_research", "document_write"],
        id="accounting-calc-research-report",
    ),
    pytest.param(
        "accounting_spreadsheet",
        "Muhasebeci gibi çalış. 12000 TL ve 8500 TL faturanın yüzde 20 KDV tutarını hesapla ve Excel tablosu hazırla.",
        ["math_solve", "spreadsheet_write"],
        id="accounting-calc-spreadsheet",
    ),
    pytest.param(
        "student_presentation",
        "Öğrenci gibi çalış. Kuantum annealing ile klasik optimizasyon farkını araştır, adım adım açıkla ve 5 sayfalık sunum hazırla.",
        ["web_research", "presentation_write"],
        id="student-research-presentation",
    ),
    pytest.param(
        "engineering_report",
        "Mühendis gibi çalış. Güneş paneli verim optimizasyonunu araştır, seçenekleri karşılaştır ve teknik çözüm raporu hazırla.",
        ["web_research", "document_write"],
        id="engineering-research-report",
    ),
    pytest.param(
        "medical_inline_report",
        "Doktor gibi çalış. Tahlil sonuçlarını yorumla ve rapor çıkar: Hb 10.5, ferritin 8, B12 220.",
        ["document_read", "document_write"],
        id="medical-inline-report",
    ),
    pytest.param(
        "optimization_decision_support",
        "Karar destek ajanı gibi çalış. A değer 10 maliyet 4, B değer 7 maliyet 3, C değer 12 maliyet 8; kapasite 10. Problemi karar değişkenleri, amaç fonksiyonu ve kısıtlarla modelle, çöz ve uygulanabilirliği doğrula.",
        ["quantum_model_problem", "quantum_run_experiment", "quantum_compare_classical", "quantum_generate_report"],
        id="optimization-decision-support",
    ),
]


@pytest.mark.parametrize(("name", "prompt", "expected"), PROFESSIONAL_WORKFLOW_CASES)
def test_professional_workflows_route_to_multi_step_capability_chains(
    name: str,
    prompt: str,
    expected: list[str],
) -> None:
    routed = route_text_to_tool(prompt)

    assert routed is not None, name
    assert routed.intent == "compound_task", name
    assert routed.is_multi_step is True, name
    assert routed.requires_confirmation is True, name
    assert [str(step.get("capability", "")) for step in routed.steps] == expected
    for index, step in enumerate(routed.steps):
        assert step.get("id") or index == 0
        if index > 0:
            assert step.get("dependsOn"), f"{name}:{step.get('capability')} missing dependsOn"


@pytest.mark.parametrize(("name", "prompt", "expected"), PROFESSIONAL_WORKFLOW_CASES)
def test_professional_workflows_preserve_router_plan_under_force_structured_planning(
    tmp_path,
    monkeypatch,
    name: str,
    prompt: str,
    expected: list[str],
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    runtime = bridge.RuntimeBridge()

    result = runtime.send_conversation(
        "",
        prompt,
        name,
        force_structured_planning=True,
    )

    assert result["executionMode"] == "plan_preview", name
    assert result["needsConfirmation"] is True, name
    steps = result["planPreview"]["steps"]
    assert [step["capability"] for step in steps] == expected


def test_optimization_research_report_stays_research_writer() -> None:
    routed = route_text_to_tool(
        "Mühendis gibi çalış. Güneş paneli verim optimizasyonunu araştır, seçenekleri karşılaştır ve teknik çözüm raporu hazırla."
    )

    assert routed is not None
    assert [step["capability"] for step in routed.steps] == ["web_research", "document_write"]
