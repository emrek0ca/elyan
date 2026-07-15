"""Executor şablon çözümleme + forEach fan-out sözleşmeleri (Faz 2)."""

from __future__ import annotations

from typing import Any

from runtime.executor_core import ExecutorCore


def _run(steps: list[dict[str, Any]], responses: dict[str, Any]):
    """execute_plan_steps'i sahte capability yürütücüsüyle koşar; çağrı
    kayıtlarını döndürür."""
    calls: list[tuple[str, dict[str, Any]]] = []

    def _execute(capability: str, args: dict[str, Any], _state: dict[str, Any], _source: str):
        public_args = {k: v for k, v in args.items() if not k.startswith("_")}
        calls.append((capability, public_args))
        payload = responses.get(capability, {"ok": True, "output": f"{capability} tamam", "result": {}})
        if callable(payload):
            payload = payload(public_args)
        return dict(payload), []

    core = ExecutorCore()
    ok, summary, _events, error_code, _structured, _artifacts = core.execute_plan_steps(
        steps=steps,
        state_factory=dict,
        execute_step=_execute,
        source="test",
    )
    return ok, summary, error_code, calls


def test_step_output_templates_resolve_into_later_args() -> None:
    steps = [
        {"id": "listele", "capability": "browser_session.extract", "args": {"selector": "a"}},
        {"id": "git", "capability": "browser_session.goto", "args": {"url": "{{steps.listele.result.items[0].href}}"}},
    ]
    responses = {
        "browser_session.extract": {
            "ok": True,
            "output": "2 öğe",
            "result": {"items": [{"href": "https://a.example"}, {"href": "https://b.example"}]},
        },
        # P3: yan etkili adım boş result ile doğrulanamaz — gözlemlenen durum döner.
        "browser_session.goto": {
            "ok": True,
            "output": "gidildi",
            "result": {"url": "https://a.example", "readBackVerified": True},
        },
    }
    ok, _summary, error_code, calls = _run(steps, responses)
    assert ok, error_code
    assert calls[1] == ("browser_session.goto", {"url": "https://a.example"})


def test_for_each_fans_out_over_list_output(tmp_path) -> None:
    fake_file = tmp_path / "indirme.txt"
    fake_file.write_text("x", encoding="utf-8")
    steps = [
        {"id": "linkler", "capability": "browser_session.extract", "args": {"selector": "a", "attribute": "href"}},
        {
            "id": "indir",
            "capability": "browser_session.download",
            "forEach": "{{steps.linkler.result.items}}",
            "args": {"url": "{{item.href}}", "output_dir": str(tmp_path)},
            "description": "{{index}}. link indirilecek",
        },
    ]
    responses = {
        "browser_session.extract": {
            "ok": True,
            "output": "3 öğe",
            "result": {"items": [{"href": f"https://v{i}.example"} for i in (1, 2, 3)]},
        },
        "browser_session.download": {
            "ok": True,
            "output": "indirildi",
            "result": {"outputPath": str(fake_file)},
            "artifacts": [{"kind": "file", "path": str(fake_file)}],
        },
    }
    ok, _summary, error_code, calls = _run(steps, responses)
    assert ok, error_code
    download_calls = [args for cap, args in calls if cap == "browser_session.download"]
    assert [c["url"] for c in download_calls] == ["https://v1.example", "https://v2.example", "https://v3.example"]
    assert all(c["output_dir"] == str(tmp_path) for c in download_calls)


def test_unresolved_template_fails_with_clear_code() -> None:
    steps = [
        {"id": "tek", "capability": "browser_session.goto", "args": {"url": "{{steps.yok.result.url}}"}},
    ]
    ok, summary, error_code, calls = _run(steps, {})
    assert not ok
    assert error_code == "TEMPLATE_UNRESOLVED"
    assert "steps.yok" in summary
    assert calls == []  # araç hiç çağrılmadı


def test_whole_template_preserves_list_type() -> None:
    captured: dict[str, Any] = {}

    def _writer(args: dict[str, Any]):
        captured.update(args)
        # P3: yan etkili adım için gözlemlenen durum kanıtı.
        return {"ok": True, "output": "yazıldı", "result": {"typed": True, "readBackVerified": True}}

    steps = [
        {"id": "kaynak", "capability": "browser_session.extract", "args": {}},
        {"id": "yaz", "capability": "browser_session.type", "args": {"value": "x", "lines": "{{steps.kaynak.result.items}}"}},
    ]
    responses = {
        "browser_session.extract": {"ok": True, "output": "ok", "result": {"items": ["a", "b"]}},
        "browser_session.type": _writer,
    }
    ok, _summary, error_code, _calls = _run(steps, responses)
    assert ok, error_code
    assert captured["lines"] == ["a", "b"]  # tip korunur, str'e çevrilmez
