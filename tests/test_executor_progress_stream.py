from __future__ import annotations

from runtime.executor_core import ExecutorCore


def _ok_step(cap, args, state, source):
    # result_nonempty / tool_result doğrulamasını geçecek çıktı + artifact.
    return {
        "ok": True,
        "output": f"{cap} tamam",
        "result": {"kind": cap},
        "artifacts": [{"kind": "file", "name": "x"}],
        "stepEvidence": {"path": "/tmp/elyan-proof.txt"},
    }, []


def test_progress_emits_task_trace_blocks(tmp_path) -> None:
    ex = ExecutorCore()
    captured: list[dict] = []
    ex.set_progress_emitter(lambda cid, block: captured.append(block))

    # P3 ön koşulu girdi dosyasının var olmasını ister.
    source_file = tmp_path / "p.txt"
    source_file.write_text("icerik", encoding="utf-8")
    steps = [
        {"id": "s1", "capability": "web_research", "args": {"query": "x"}},
        {"id": "s2", "capability": "file_read", "args": {"path": str(source_file)}, "dependsOn": ["s1"]},
    ]
    ex.execute_plan_steps(
        steps=steps,
        state_factory=lambda: {},
        execute_step=_ok_step,
        source="confirmed_plan",
        conversation_id="conv_x",
    )

    assert captured, "en az bir progress bloğu yayınlanmalı"
    for block in captured:
        assert block["type"] == "task_trace"
        assert block["stableBlockId"].startswith("tasktrace_")
    # İlk emit: s1 running. Son emit: overall completed, iki adım da completed.
    assert captured[0]["steps"][0]["status"] == "running"
    final = captured[-1]
    assert final["status"] == "completed"
    assert [s["status"] for s in final["steps"]] == ["completed", "completed"]
    assert [s["label"] for s in final["steps"]] == ["Araştırılıyor", "Dosya okunuyor"]
    assert final["verification"]["checkedSteps"] == 2
    assert final["steps"][0]["artifactCount"] == 1
    assert final["steps"][0]["resultKind"] == "web_research"
    assert final["steps"][0]["evidence"] == {"path": "/tmp/elyan-proof.txt"}


def test_no_emitter_is_safe(tmp_path) -> None:
    # Emitter bağlı değilse yürütme normal çalışır (progress opsiyonel).
    source_file = tmp_path / "p.txt"
    source_file.write_text("icerik", encoding="utf-8")
    ex = ExecutorCore()
    ok, _content, _events, _err, _res, _arts = ex.execute_plan_steps(
        steps=[{"id": "s1", "capability": "file_read", "args": {"path": str(source_file)}}],
        state_factory=lambda: {},
        execute_step=_ok_step,
        source="confirmed_plan",
    )
    assert ok is True


def test_progress_marks_failure() -> None:
    ex = ExecutorCore()
    captured: list[dict] = []
    ex.set_progress_emitter(lambda cid, block: captured.append(block))

    def _fail_step(cap, args, state, source):
        return {"ok": False, "output": "patladı", "error": {"code": "X", "message": "patladı"}, "artifacts": []}, []

    ex.execute_plan_steps(
        steps=[{"id": "s1", "capability": "shell_run", "args": {"command": "x"}}],
        state_factory=lambda: {},
        execute_step=_fail_step,
        source="confirmed_plan",
    )
    assert captured
    assert captured[-1]["steps"][0]["status"] == "failed"


def test_progress_marks_cancellation_as_canceled() -> None:
    ex = ExecutorCore()
    captured: list[dict] = []
    ex.set_progress_emitter(lambda cid, block: captured.append(block))
    should_cancel = {"value": False}

    def _first_step_then_cancel(cap, args, state, source):
        should_cancel["value"] = True
        return {"ok": True, "output": "ilk adım tamam", "result": {"kind": cap}, "artifacts": []}, []

    ok, content, _events, error_code, _result, _artifacts = ex.execute_plan_steps(
        steps=[
            {"id": "s1", "capability": "math_solve", "args": {"expression": "1+1"}},
            {"id": "s2", "capability": "document_write", "args": {"prompt": "sonuç"}, "dependsOn": ["s1"]},
        ],
        state_factory=lambda: {},
        execute_step=_first_step_then_cancel,
        source="confirmed_plan",
        conversation_id="conv_cancel",
        should_cancel=lambda: "task_cancelled" if should_cancel["value"] else "",
    )

    assert ok is False
    assert content == "Görev iptal edildi."
    assert error_code == "EXECUTION_CANCELLED"
    assert captured[-1]["status"] == "canceled"
    assert captured[-1]["stopReason"] == "execution_cancelled"
    assert [step["status"] for step in captured[-1]["steps"]] == ["completed", "pending"]


def test_cancel_after_last_step_checkpoint_blocks_late_success() -> None:
    ex = ExecutorCore()
    captured: list[dict] = []
    ex.set_progress_emitter(lambda cid, block: captured.append(block))
    should_cancel = {"value": False}

    def _single_step_then_cancel(cap, args, state, source):
        should_cancel["value"] = True
        return {"ok": True, "output": "rapor hazır", "result": {"kind": cap}, "artifacts": []}, []

    ok, content, _events, error_code, _result, _artifacts = ex.execute_plan_steps(
        steps=[
            {"id": "write", "capability": "document_write", "args": {"prompt": "rapor"}},
        ],
        state_factory=lambda: {},
        execute_step=_single_step_then_cancel,
        source="confirmed_plan",
        conversation_id="conv_cancel_final",
        should_cancel=lambda: "task_cancelled" if should_cancel["value"] else "",
    )

    assert ok is False
    assert content == "Görev iptal edildi."
    assert error_code == "EXECUTION_CANCELLED"
    assert captured[-1]["status"] == "canceled"
    assert captured[-1]["stopReason"] == "execution_cancelled"
    assert captured[-1]["steps"][0]["status"] == "canceled"


def test_progress_uses_human_labels_for_professional_and_decision_steps() -> None:
    ex = ExecutorCore()
    captured: list[dict] = []
    ex.set_progress_emitter(lambda cid, block: captured.append(block))

    steps = [
        {"id": "read", "capability": "document_read", "args": {"text": "Hb 10.5"}},
        {"id": "calc", "capability": "math_solve", "args": {"expression": "12000+8500"}, "dependsOn": ["read"]},
        {
            "id": "model",
            "capability": "quantum_model_problem",
            "args": {"prompt": "capacity 10", "problemClass": "optimization"},
            "dependsOn": ["calc"],
        },
        {
            "id": "report",
            "capability": "quantum_generate_report",
            "args": {"prompt": "rapor"},
            "dependsOn": ["model"],
        },
        {"id": "mcp", "capability": "mcp_tool_call", "args": {"name": "safe.read"}, "dependsOn": ["report"]},
    ]
    ex.execute_plan_steps(
        steps=steps,
        state_factory=lambda: {},
        execute_step=_ok_step,
        source="confirmed_plan",
        conversation_id="conv_labels",
    )

    assert captured
    final = captured[-1]
    assert [step["label"] for step in final["steps"]] == [
        "Belge okunuyor",
        "Hesaplanıyor",
        "Problem modelleniyor",
        "Karar raporu hazırlanıyor",
        "Uygulama aracı çalışıyor",
    ]
