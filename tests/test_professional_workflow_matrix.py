from __future__ import annotations

import pytest
from pathlib import Path

from runtime import bridge, state_store
from runtime.executor_core import ExecutorCore
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


def test_professional_executor_passes_prior_outputs_into_writer(tmp_path: Path) -> None:
    routed = route_text_to_tool(
        "Muhasebeci gibi çalış. 12000 TL ve 8500 TL hizmet faturası için yüzde 20 KDV hesapla, "
        "KDV kurallarını araştır ve rapor belgesi hazırla."
    )
    assert routed is not None
    observed_writer_args: dict[str, object] = {}
    output_path = tmp_path / "kdv-raporu.docx"

    def execute_step(capability: str, args: dict, _state: dict, _source: str):
        if capability == "math_solve":
            return {"ok": True, "output": "KDV tutarı: 4100", "result": {"kind": "math_solve", "result": "4100"}}, []
        if capability == "web_research":
            assert args["_previousOutput"] == "KDV tutarı: 4100"
            return {
                "ok": True,
                "output": "KDV genel oranı yüzde 20 olarak uygulanır.",
                "result": {"kind": "web_research", "summary": "KDV oranı yüzde 20."},
            }, []
        if capability == "document_write":
            observed_writer_args.update(args)
            output_path.write_bytes(b"fake-docx-proof" * 80)
            return {
                "ok": True,
                "output": f"DOCX oluşturuldu: {output_path.name}",
                "result": {"kind": "document_write", "outputPath": str(output_path)},
                "artifacts": [{"kind": "file", "path": str(output_path), "name": output_path.name}],
            }, []
        raise AssertionError(capability)

    ok, _content, _events, error_code, result, artifacts = ExecutorCore().execute_plan_steps(
        steps=[dict(step) for step in routed.steps],
        state_factory=lambda: {},
        execute_step=execute_step,
        source="confirmed_plan",
        confirmed=True,
    )

    assert ok is True
    assert error_code == ""
    assert result and result["kind"] == "document_write"
    assert artifacts and artifacts[-1]["path"] == str(output_path)
    assert observed_writer_args["_previousOutput"] == "KDV genel oranı yüzde 20 olarak uygulanır."
    assert observed_writer_args["_previousResult"]["kind"] == "web_research"
    assert "_previousArtifacts" not in observed_writer_args


def test_inline_analysis_executor_passes_read_output_into_report_writer(tmp_path: Path) -> None:
    routed = route_text_to_tool(
        "Doktor gibi çalış. Tahlil sonuçlarını yorumla ve rapor çıkar: Hb 10.5, ferritin 8, B12 220."
    )
    assert routed is not None
    assert [step["capability"] for step in routed.steps] == ["document_read", "document_write"]

    observed_writer_args: dict[str, object] = {}
    calls: list[str] = []
    output_path = tmp_path / "tahlil-raporu.docx"
    read_output = "Okunan tahlil verisi: Hb 10.5, ferritin 8, B12 220. Bulgular analiz raporu icin uygundur."

    def execute_step(capability: str, args: dict, _state: dict, _source: str):
        calls.append(capability)
        if capability == "document_read":
            assert "Hb 10.5" in str(args.get("text", ""))
            return {
                "ok": True,
                "output": read_output,
                "result": {"kind": "document_read", "text": read_output},
            }, []
        if capability == "document_write":
            observed_writer_args.update(args)
            output_path.write_bytes(b"fake-medical-docx-proof" * 80)
            return {
                "ok": True,
                "output": f"DOCX oluşturuldu: {output_path.name}",
                "result": {"kind": "document_write", "outputPath": str(output_path)},
                "artifacts": [{"kind": "file", "path": str(output_path), "name": output_path.name}],
            }, []
        raise AssertionError(capability)

    ok, _content, _events, error_code, result, artifacts = ExecutorCore().execute_plan_steps(
        steps=[dict(step) for step in routed.steps],
        state_factory=lambda: {},
        execute_step=execute_step,
        source="confirmed_plan",
        confirmed=True,
    )

    assert ok is True
    assert error_code == ""
    assert result and result["kind"] == "document_write"
    assert artifacts and artifacts[-1]["path"] == str(output_path)
    assert calls == ["document_read", "document_write"]
    assert observed_writer_args["sourceContext"] == read_output
    assert observed_writer_args["_previousOutput"] == read_output
    assert observed_writer_args["_previousResult"]["kind"] == "document_read"


def test_professional_executor_passes_analysis_output_into_writer(tmp_path: Path) -> None:
    runtime = bridge.RuntimeBridge()
    plan = runtime._professional_workflow_plan(
        "Avukat gibi çalış. Bu dosya metnini analiz et: tahliye davası. Mevzuatı araştır ve savunma dilekçesi hazırla.",
        {"document_read", "web_research", "text_analyze", "document_write"},
    )
    assert plan is not None
    steps, _preview = plan

    observed_writer_args: dict[str, object] = {}
    calls: list[str] = []
    output_path = tmp_path / "savunma-dilekcesi.docx"

    def execute_step(capability: str, args: dict, _state: dict, _source: str):
        calls.append(capability)
        if capability == "document_read":
            return {"ok": True, "output": "Dosya bağlamı: tahliye itirazı", "result": {"kind": "document_read", "text": "Dosya bağlamı: tahliye itirazı"}}, []
        if capability == "web_research":
            return {"ok": True, "output": "Mevzuat bağlamı: TBK kira hükümleri", "result": {"kind": "web_research", "summary": "Mevzuat bağlamı: TBK kira hükümleri"}}, []
        if capability == "text_analyze":
            assert "Dosya bağlamı" in str(args)
            assert "Mevzuat bağlamı" in str(args)
            return {"ok": True, "output": "Analiz: savunma odağı süre ve delil kontrolü", "result": {"kind": "text_analyze", "summary": "savunma odağı"}}, []
        if capability == "document_write":
            observed_writer_args.update(args)
            output_path.write_bytes(b"fake-legal-docx-proof" * 80)
            return {
                "ok": True,
                "output": f"DOCX oluşturuldu: {output_path.name}",
                "result": {"kind": "document_write", "outputPath": str(output_path)},
                "artifacts": [{"kind": "file", "path": str(output_path), "name": output_path.name}],
            }, []
        raise AssertionError(capability)

    ok, _content, _events, error_code, result, artifacts = ExecutorCore().execute_plan_steps(
        steps=[dict(step) for step in steps],
        state_factory=lambda: {},
        execute_step=execute_step,
        source="confirmed_plan",
        confirmed=True,
    )

    assert ok is True
    assert error_code == ""
    assert result and result["kind"] == "document_write"
    assert artifacts and artifacts[-1]["path"] == str(output_path)
    assert calls == ["document_read", "web_research", "text_analyze", "document_write"]
    assert observed_writer_args["_previousOutput"] == "Analiz: savunma odağı süre ve delil kontrolü"
    assert observed_writer_args["_previousResult"]["kind"] == "text_analyze"
    assert observed_writer_args["_dependencyResults"]["analyze"]["summary"] == "savunma odağı"


def test_accounting_spreadsheet_executor_resolves_calculation_into_cells(tmp_path: Path) -> None:
    routed = route_text_to_tool(
        "Muhasebeci gibi çalış. 12000 TL ve 8500 TL faturanın yüzde 20 KDV tutarını hesapla ve Excel tablosu hazırla."
    )
    assert routed is not None
    assert [step["capability"] for step in routed.steps] == ["math_solve", "spreadsheet_write"]

    observed_sheet_args: dict[str, object] = {}
    output_path = tmp_path / "kdv-tablosu.xlsx"

    def execute_step(capability: str, args: dict, _state: dict, _source: str):
        if capability == "math_solve":
            return {"ok": True, "output": "4100", "result": {"kind": "math_solve", "result": "4100"}}, []
        if capability == "spreadsheet_write":
            observed_sheet_args.update(args)
            output_path.write_bytes(b"fake-xlsx-proof" * 80)
            return {
                "ok": True,
                "output": f"XLSX oluşturuldu: {output_path.name}",
                "result": {"kind": "spreadsheet_write", "outputPath": str(output_path)},
                "artifacts": [{"kind": "file", "path": str(output_path), "name": output_path.name}],
            }, []
        raise AssertionError(capability)

    ok, _content, _events, error_code, result, artifacts = ExecutorCore().execute_plan_steps(
        steps=[dict(step) for step in routed.steps],
        state_factory=lambda: {},
        execute_step=execute_step,
        source="server_materialized",
        confirmed=True,
    )

    assert ok is True
    assert error_code == ""
    assert result and result["kind"] == "spreadsheet_write"
    assert artifacts and artifacts[-1]["path"] == str(output_path)
    assert observed_sheet_args["_previousOutput"] == "4100"
    assert observed_sheet_args["_previousResult"]["kind"] == "math_solve"
    assert observed_sheet_args["_dependencyResults"]["calculate"]["result"] == "4100"
    assert "4100" in str(observed_sheet_args)


def test_student_presentation_executor_resolves_research_into_prompt(tmp_path: Path) -> None:
    routed = route_text_to_tool(
        "Öğrenci gibi çalış. Kuantum annealing ile klasik optimizasyon farkını araştır, adım adım açıkla ve 5 sayfalık sunum hazırla."
    )
    assert routed is not None
    assert [step["capability"] for step in routed.steps] == ["web_research", "presentation_write"]

    observed_presentation_args: dict[str, object] = {}
    output_path = tmp_path / "kuantum-sunum.pptx"
    research_output = "Kuantum annealing sezgisel optimizasyon için kullanılır; klasik yöntemler deterministik baseline sağlar."

    def execute_step(capability: str, args: dict, _state: dict, _source: str):
        if capability == "web_research":
            return {
                "ok": True,
                "output": research_output,
                "result": {"kind": "web_research", "summary": research_output},
            }, []
        if capability == "presentation_write":
            observed_presentation_args.update(args)
            output_path.write_bytes(b"fake-pptx-proof" * 80)
            return {
                "ok": True,
                "output": f"PPTX oluşturuldu: {output_path.name}",
                "result": {"kind": "presentation_write", "outputPath": str(output_path)},
                "artifacts": [{"kind": "file", "path": str(output_path), "name": output_path.name}],
            }, []
        raise AssertionError(capability)

    ok, _content, _events, error_code, result, artifacts = ExecutorCore().execute_plan_steps(
        steps=[dict(step) for step in routed.steps],
        state_factory=lambda: {},
        execute_step=execute_step,
        source="server_materialized",
        confirmed=True,
    )

    assert ok is True
    assert error_code == ""
    assert result and result["kind"] == "presentation_write"
    assert artifacts and artifacts[-1]["path"] == str(output_path)
    assert observed_presentation_args["_previousOutput"] == research_output
    assert observed_presentation_args["_previousResult"]["kind"] == "web_research"
    research_id = str(routed.steps[0].get("id") or "")
    assert observed_presentation_args["_dependencyResults"][research_id]["summary"] == research_output
    assert research_output in str(observed_presentation_args)
