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


def test_progress_includes_quantum_liveness_snapshot(tmp_path) -> None:
    ex = ExecutorCore()
    captured: list[dict] = []
    ex.set_progress_emitter(lambda cid, block: captured.append(block))
    source_file = tmp_path / "p.txt"
    source_file.write_text("icerik", encoding="utf-8")

    ex.execute_plan_steps(
        steps=[
            {"id": "read_a", "capability": "file_read", "args": {"path": str(source_file)}},
            {"id": "read_b", "capability": "web_research", "args": {"query": "elyan"}},
        ],
        state_factory=lambda: {},
        execute_step=_ok_step,
        source="confirmed_plan",
        conversation_id="conv_quantum_live",
        plan_preview={
            "responsiveExecution": {
                "strategy": "quantum_liveness_guard_v1",
                "source": "backend_neural_readiness",
                "active": True,
                "qualified": True,
                "livenessScore": 0.82,
                "boostWeight": 0.06,
                "metric": "responsive_execution_liveness",
            },
            "livenessGuard": {
                "strategy": "quantum_replan_liveness_guard_v1",
                "source": "backend_neural_readiness",
                "active": True,
                "timeoutRisk": "medium",
                "maxReplans": 3,
                "earlyProgressCheckpoint": True,
                "safeStopOnTimeout": True,
                "metric": "responsive_execution_liveness",
            },
        },
    )

    quantum = captured[-1]["quantumLiveness"]
    assert quantum["strategy"] == "quantum_runtime_liveness_snapshot_v1"
    assert quantum["source"] == "desktop_runtime_progress"
    assert quantum["backendResponsiveActive"] is True
    assert quantum["livenessGuardActive"] is True
    assert quantum["livenessGuardTimeoutRisk"] == "medium"
    assert quantum["livenessGuardEffectiveMaxReplans"] == 3
    assert quantum["qualified"] is True


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


def test_progress_records_quantum_liveness_stop_policy_on_timeout() -> None:
    ex = ExecutorCore()
    captured: list[dict] = []
    ex.set_progress_emitter(lambda cid, block: captured.append(block))
    should_timeout = {"value": False}

    def _first_step_then_timeout(cap, args, state, source):
        should_timeout["value"] = True
        return {"ok": True, "output": "ilk adım tamam", "result": {"kind": cap}, "artifacts": []}, []

    ok, content, _events, error_code, _result, _artifacts = ex.execute_plan_steps(
        steps=[
            {"id": "read", "capability": "document_read", "args": {"text": "x"}},
            {"id": "write", "capability": "document_write", "args": {"prompt": "x"}, "dependsOn": ["read"]},
        ],
        state_factory=lambda: {},
        execute_step=_first_step_then_timeout,
        source="confirmed_plan",
        conversation_id="conv_timeout",
        should_cancel=lambda: "task_execution_timeout" if should_timeout["value"] else "",
        plan_preview={
            "livenessGuard": {
                "strategy": "quantum_replan_liveness_guard_v1",
                "source": "backend_neural_readiness",
                "active": True,
                "timeoutRisk": "high",
                "maxReplans": 3,
                "earlyProgressCheckpoint": True,
                "safeStopOnTimeout": True,
                "metric": "responsive_execution_liveness",
            },
        },
    )

    assert ok is False
    assert content == "Görev zaman aşımı nedeniyle güvenli adım sınırında durduruldu."
    assert error_code == "TASK_EXECUTION_TIMEOUT"
    assert captured[-1]["status"] == "canceled"
    assert captured[-1]["stopReason"] == "execution_timeout"
    stop_policy = captured[-1]["quantumLiveness"]["stopPolicy"]
    assert stop_policy["strategy"] == "quantum_liveness_stop_policy_v1"
    assert stop_policy["action"] == "safe_stop_timeout"
    assert stop_policy["stopReason"] == "execution_timeout"
    assert stop_policy["timeoutRisk"] == "high"
    assert stop_policy["safeStopOnTimeout"] is True


def test_progress_uses_human_labels_for_professional_and_decision_steps() -> None:
    ex = ExecutorCore()
    captured: list[dict] = []
    ex.set_progress_emitter(lambda cid, block: captured.append(block))

    steps = [
        {"id": "read", "capability": "document_read", "args": {"text": "Hb 10.5"}},
        {"id": "calc", "capability": "math_solve", "args": {"expression": "12000+8500"}, "dependsOn": ["read"]},
        {
            "id": "legal",
            "capability": "text_analyze",
            "args": {"prompt": "dava", "sourceContext": "{{steps.read.output}}", "mode": "legal"},
            "dependsOn": ["read"],
        },
        {
            "id": "medical",
            "capability": "text_analyze",
            "args": {"prompt": "tahlil", "sourceContext": "{{steps.read.output}}", "mode": "medical"},
            "dependsOn": ["read"],
        },
        {
            "id": "accounting",
            "capability": "text_analyze",
            "args": {"prompt": "kdv", "sourceContext": "{{steps.calc.output}}", "mode": "accounting"},
            "dependsOn": ["calc"],
        },
        {
            "id": "student",
            "capability": "text_analyze",
            "args": {"prompt": "ödev", "sourceContext": "{{steps.read.output}}", "mode": "student"},
            "dependsOn": ["read"],
        },
        {
            "id": "technical",
            "capability": "text_analyze",
            "args": {"prompt": "optimizasyon", "sourceContext": "{{steps.calc.output}}", "mode": "technical"},
            "dependsOn": ["calc"],
        },
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
        {
            "id": "mcp",
            "capability": "mcp_call_tool",
            "args": {
                "serverId": "app_github",
                "toolName": "list_issues",
                "arguments": {"repo": "private/repo"},
            },
            "dependsOn": ["report"],
        },
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
        "Hukuki analiz yapılıyor",
        "Tıbbi bağlam yorumlanıyor",
        "Muhasebe analizi yapılıyor",
        "Öğrenci içeriği analiz ediliyor",
        "Teknik analiz yapılıyor",
        "Problem modelleniyor",
        "Karar raporu hazırlanıyor",
        "GitHub aracı çalışıyor",
    ]
    mcp_step = final["steps"][-1]
    assert mcp_step["detail"] == "GitHub / list_issues"
    assert "private/repo" not in str(mcp_step)
