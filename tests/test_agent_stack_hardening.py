"""Sertleştirme testleri: üretimde patlayacak uç durumlar.
Hedef: boş/None girdi, enjekte edilen çağrılabilirlerin patlaması, bütçe
sınırları, bozuk model çıktısı, Türkçe/unicode, çok uzun girdi."""
from __future__ import annotations




import json
import tempfile

import pytest

from runtime import intent_gate, understanding
from runtime.agent_loop import run_agent_loop, coerce_action, build_tool_catalog
from runtime.agent_decider import extract_json_object, make_model_decider
from runtime.computer_use_loop import run_computer_use_loop, build_screen_state
from runtime.retrieval_orchestrator import (
    retrieve_iteratively, decompose_query, assess_sufficiency, rerank, RetrievedItem,
)
from runtime.shell_session import SESSIONS, ShellSessionError
from runtime.reasoning_policy import decide_execution_mode


def ok_step(cap, args, state, src):
    return {"ok": True, "output": f"{cap} ok", "result": {"kind": cap}, "artifacts": []}, []


# ── AGENT LOOP ──────────────────────────────────────────────────────────────
def test_agent_loop_survives_decider_exception():
    def boom(_ctx): raise RuntimeError("model patladı")
    r = run_agent_loop(goal="x", decide_next=boom, execute_step=ok_step, state_factory=dict)
    assert r.ok is False and r.error_code == "AGENT_LOOP_DECIDER_FAILED"


def test_agent_loop_survives_execute_exception():
    def boom(*_a): raise RuntimeError("araç patladı")
    calls = {"n": 0}
    def decide(_ctx):
        calls["n"] += 1
        return {"kind": "tool", "capability": "sys_info", "args": {}} if calls["n"] < 3 else {"kind": "finish", "summary": "bitti"}
    r = run_agent_loop(goal="x", decide_next=decide, execute_step=boom,
                       state_factory=dict, confirmed=True, require_approval=False)
    assert isinstance(r.ok, bool)  # çökmemeli


def test_agent_loop_rejects_hallucinated_tool():
    seen = {"n": 0}
    def decide(_ctx):
        seen["n"] += 1
        if seen["n"] > 3: return {"kind": "finish", "summary": "vazgeçtim"}
        return {"kind": "tool", "capability": "uydurma_arac_xyz", "args": {}}
    r = run_agent_loop(goal="x", decide_next=decide, execute_step=ok_step, state_factory=dict)
    codes = [o.error_code for o in r.observations]
    assert "UNKNOWN_CAPABILITY" in codes


def test_agent_loop_budget_is_hard():
    def decide(_ctx): return {"kind": "tool", "capability": "sys_info", "args": {"q": "x"}}
    r = run_agent_loop(goal="x", decide_next=decide, execute_step=ok_step,
                       state_factory=dict, max_steps=3, confirmed=True, require_approval=False)
    assert r.steps_used <= 3 and r.ok is False


def test_agent_loop_garbage_model_output_is_safe():
    for junk in [None, "", 42, [], {"kind": "nonsense"}, {"capability": ""}]:
        r = run_agent_loop(goal="x", decide_next=lambda _c, j=junk: j,
                           execute_step=ok_step, state_factory=dict, max_steps=2)
        assert r.ok is False  # uydurma araç çalıştırmaz


def test_approval_gate_blocks_side_effect():
    def decide(_ctx): return {"kind": "tool", "capability": "shell_run", "args": {"command": "ls"}}
    r = run_agent_loop(goal="x", decide_next=decide, execute_step=ok_step,
                       state_factory=dict, confirmed=False, require_approval=True)
    assert r.stop_reason == "needs_approval" and r.pending_action["capability"] == "shell_run"


def test_agent_loop_strips_internal_flags_from_context():
    captured = {}
    def decide(ctx):
        captured.update(ctx)
        return {"kind": "finish", "summary": "ok"}
    def step(cap, args, state, src):
        return {"ok": True, "output": "x", "result": {}, "artifacts": []}, []
    run_agent_loop(goal="x", decide_next=decide, execute_step=step, state_factory=dict)
    assert "_confirmed" not in json.dumps(captured)


# ── JSON ÇIKARIM ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expect", [
    ('{"kind":"finish"}', True),
    ('```json\n{"kind":"finish"}\n```', True),
    ('bla bla {"kind":"finish","x":{"nested":1}} son', True),
    ('{"a": "içinde } var", "kind":"finish"}', True),
    ("düz metin", False), ("", False), ("{bozuk", False),
])
def test_json_extraction(raw, expect):
    assert (extract_json_object(raw) is not None) is expect


# ── ANLAMA / NİYET ──────────────────────────────────────────────────────────
def test_understanding_falls_back_when_model_dead():
    def dead(_p): raise RuntimeError("backend yok")
    u = intent_gate.understand("masaüstüne rapor.docx oluştur", send_prompt=dead)
    assert u.degraded is True and u.source == "deterministic_fallback"


def test_understanding_rejects_invalid_intent():
    u = intent_gate.understand("x", send_prompt=lambda _p: '{"intent":"HACK","confidence":9}')
    assert u.intent in {"chat", "task", "task_control", "clarify"} and u.degraded is True


def test_understanding_clamps_confidence():
    u = intent_gate.understand("x", send_prompt=lambda _p: '{"intent":"task","confidence":99}')
    assert 0.0 <= u.confidence <= 1.0


def test_chat_during_dispatch_never_becomes_task():
    for msg in ["adım ne benim", "nasılsın", "teşekkürler", "ne yapıyorsun", "hava nasıl"]:
        d = intent_gate.classify_message(msg, dispatch_active=True)
        assert d.kind != "task", msg


def test_empty_and_huge_inputs():
    for msg in ["", "   ", "\n\t", "a" * 20000, "🚀🔥", "'; DROP TABLE--"]:
        d = intent_gate.classify_message(msg)
        assert d.kind in {"chat", "task", "task_control"}


# ── SHELL SESSION ───────────────────────────────────────────────────────────
def test_shell_session_isolation_and_errors():
    tmp = tempfile.mkdtemp()
    s = SESSIONS.open(cwd=tmp, root=tmp)
    with pytest.raises(ShellSessionError):
        SESSIONS.run("yok_boyle_oturum", "ls")
    with pytest.raises(ShellSessionError):
        SESSIONS.run(s.session_id, "")
    with pytest.raises(ShellSessionError):
        SESSIONS.run(s.session_id, "cd /etc")           # kök kaçışı
    with pytest.raises(ShellSessionError):
        SESSIONS.run(s.session_id, "vim x")             # etkileşimli
    r = SESSIONS.run(s.session_id, "sleep 3", timeout=1)
    assert r["timedOut"] is True
    assert SESSIONS.close(s.session_id) is True
    assert SESSIONS.close(s.session_id) is False        # çift kapatma güvenli


def test_shell_session_two_sessions_do_not_share_cwd():
    a, b = tempfile.mkdtemp(), tempfile.mkdtemp()
    s1 = SESSIONS.open(cwd=a); s2 = SESSIONS.open(cwd=b)
    assert SESSIONS.run(s1.session_id, "pwd")["cwd"] != SESSIONS.run(s2.session_id, "pwd")["cwd"]


def test_shell_session_chained_cd_does_not_leak():
    tmp = tempfile.mkdtemp()
    s = SESSIONS.open(cwd=tmp, root=tmp)
    import os; os.makedirs(os.path.join(tmp, "sub"), exist_ok=True)
    before = SESSIONS.run(s.session_id, "pwd")["cwd"]
    SESSIONS.run(s.session_id, "cd sub && pwd")   # zincirli: oturum cwd'si DEĞİŞMEMELİ
    assert SESSIONS.run(s.session_id, "pwd")["cwd"] == before


# ── RETRIEVAL ───────────────────────────────────────────────────────────────
def test_retrieval_survives_search_exception():
    def boom(_q): raise RuntimeError("arama çöktü")
    out = retrieve_iteratively("a ve b", search=boom)
    assert out.items == [] and out.sufficient is False


def test_retrieval_handles_empty_and_weird_results():
    for payload in [None, [], "metin", [{"no_text": 1}], [{"text": ""}]]:
        out = retrieve_iteratively("soru", search=lambda _q, p=payload: p)
        assert isinstance(out.items, list)


def test_retrieval_no_second_round_when_sufficient():
    calls = []
    def search(q):
        calls.append(q)
        return [{"text": "faiz karari sabit enflasyon orani yuzde 24 aciklandi"}]
    retrieve_iteratively("faiz karari ne oldu ve enflasyon orani kac", search=search)
    assert len(calls) == 1  # yeterliyse EK ÇAĞRI YOK (gecikme korunur)


def test_rerank_dedupes():
    items = [RetrievedItem("aynı metin burada", "a"), RetrievedItem("aynı metin burada", "b")]
    assert len(rerank(items, "aynı metin", limit=5)) == 1


# ── COMPUTER USE ────────────────────────────────────────────────────────────
def test_computer_use_survives_observe_exception():
    def boom(): raise RuntimeError("ekran yok")
    r = run_computer_use_loop(goal="x", observe=boom,
                              decide_action=lambda c: {"kind": "act"}, act=lambda a: {"ok": True})
    assert r.ok is False and r.error_code == "PERCEPTION_FAILED"


def test_computer_use_survives_act_exception():
    n = {"i": 0}
    def obs():
        n["i"] += 1
        return {"result": {"elements": [{"title": f"btn{n['i']}", "role": "button"}]}}
    def boom(_a): raise RuntimeError("tık patladı")
    r = run_computer_use_loop(goal="x", observe=obs,
                              decide_action=lambda c: {"kind": "act"}, act=boom, max_actions=3)
    assert isinstance(r.ok, bool)


def test_screen_state_handles_garbage():
    for payload in [{}, {"result": None}, {"result": {"elements": "değil-liste"}}, {"result": {}}]:
        assert build_screen_state(payload).signature


# ── POLİTİKA ────────────────────────────────────────────────────────────────
def test_policy_never_crashes_on_weird_routes():
    class Bad:
        tool_name = None; confidence = "abc"; is_multi_step = None; steps = None
        intent = None; reason = None
    for routed in [None, Bad()]:
        d = decide_execution_mode(routed, query="x")
        assert d.mode in {"fast_path", "structured_plan", "agent_loop"}


def test_tool_catalog_is_not_empty_and_bounded():
    cat = build_tool_catalog()
    assert 10 < len(cat) <= 80
    assert all("name" in c for c in cat)
