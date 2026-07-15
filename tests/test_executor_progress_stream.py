from __future__ import annotations

from runtime.executor_core import ExecutorCore


def _ok_step(cap, args, state, source):
    # result_nonempty / tool_result doğrulamasını geçecek çıktı + artifact.
    return {"ok": True, "output": f"{cap} tamam", "result": {"kind": cap}, "artifacts": [{"kind": "file", "name": "x"}]}, []


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
