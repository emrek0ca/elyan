"""P0 — Tek plan otoritesi (CompiledExecutionPlan) sözleşme testleri.

Garanti edilenler:
- Planner ve repair payload'ları backend'in 48.000 karakter sınırının altında.
- İmzalanan/onaylanan/yürütülen plan aynı kanonik hash'e bağlı.
- Plan/args/dependency tampering fail-closed reddedilir.
- Clarification/replan/revizyon yeni revision + yeni planHash üretir.
- 16 adımlık WorkOrder eksiksiz doğrulanır ve eksiksiz yürütülür.
- Deterministik capability shortlist 8–15 araç şeması gönderir.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from runtime import compiled_plan, state_store
from runtime import structured_planner as sp
from runtime.capability_shortlist import MAX_SHORTLIST, MIN_SHORTLIST, shortlist_capabilities
from runtime.desktop_work_order import MAX_STEPS, validate_payload
from runtime.execution_journal import plan_hash as journal_plan_hash
from runtime.execution_trust import ExecutionLedger, TrustError, prepare_work_order_v2
from runtime.executor_core import ExecutorCore


def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(state_store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(state_store, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(state_store, "LEGACY_STATE_PATH", tmp_path / "legacy.json")
    monkeypatch.setattr(state_store, "_STATE_CACHE", None)
    monkeypatch.setattr(state_store, "_STATE_CACHE_PATH", None)
    monkeypatch.setattr(state_store, "_STATE_CACHE_MTIME", -2)


# ── 48k payload sınırı ───────────────────────────────────────────────────────


def _worst_case_request() -> dict[str, Any]:
    turns = [{"role": "user", "text": "x" * 600} for _ in range(12)]
    retrieval = [{"text": "y" * 2000, "source": f"doc{i}"} for i in range(6)]
    skills = [{"id": f"skill_{i}", "description": "d" * 160, "expectedInputs": ["a", "b", "c", "d"]} for i in range(8)]
    mcp_tools = [{"name": f"tool_{i}", "description": "m" * 200} for i in range(16)]
    return sp.build_planning_request(
        "dosyaları tara, rapor yaz, tabloyu doldur, mail taslağı hazırla, takvime ekle, "
        "görsel üret, sunum hazırla, komut çalıştır, tarayıcıda araştır ve indir",
        conversation_turns=turns,
        retrieval_matches=retrieval,
        skills=skills,
        mcp_tools=mcp_tools,
        recent_intents=[{"kind": "success", "query": "q" * 120, "capability": "web_research"}] * 13,
        desktop_snapshot={"activeWindow": {"appName": "Safari"}, "openApps": ["a"] * 20},
    )


def test_planner_payload_stays_under_backend_limit() -> None:
    request = _worst_case_request()
    prompt = sp.planning_prompt(request)
    assert len(prompt) < sp.MAX_PLANNER_PAYLOAD_CHARS


def test_repair_payload_stays_under_backend_limit() -> None:
    request = _worst_case_request()
    invalid = {
        "contract": sp.PLAN_CONTRACT,
        "steps": [{"capability": "c" * 120, "args": {"a": "b" * 900}} for _ in range(24)],
    }
    _plan, errors = sp.validate_plan(invalid)
    repair = sp.build_repair_request(request, invalid, errors or ["bozuk"])
    prompt = sp.planning_prompt(repair)
    assert len(prompt) < sp.MAX_PLANNER_PAYLOAD_CHARS


def test_replan_payload_stays_under_backend_limit() -> None:
    request = _worst_case_request()
    observation = sp.build_replan_observation(
        {
            "reason": "tool_failure",
            "goal": "g" * 400,
            "failedCapability": "web_research",
            "errorCode": "NETWORK_FAILED",
            "message": "m" * 600,
            "failedArgs": {"query": "q" * 900},
            "stepOutputs": {f"s{i}": {"output": "o" * 500, "result": {"items": [{"x": "y" * 200}] * 20}} for i in range(12)},
            "remainingSteps": [{"capability": "document_write", "args": {"prompt": "p" * 700}}] * 12,
        }
    )
    replan = sp.build_replan_request(request, observation)
    assert len(sp.planning_prompt(replan)) < sp.MAX_PLANNER_PAYLOAD_CHARS


# ── Deterministik capability shortlist ───────────────────────────────────────


def test_planning_request_sends_shortlist_not_full_catalog() -> None:
    request = sp.build_planning_request("chrome'u aç ve youtube'da müzik aç")
    names = [tool["name"] for tool in request["toolCatalog"]]
    assert MIN_SHORTLIST <= len(names) <= MAX_SHORTLIST
    assert "open_app" in names
    assert "play_media" in names or "browser_control" in names
    # 77 aracın tamamı gitmiyor
    assert len(names) < len(sp.tool_catalog(platform="darwin"))


def test_shortlist_is_deterministic_and_bounded() -> None:
    first = shortlist_capabilities("tabloyu doldur ve mail at")
    second = shortlist_capabilities("tabloyu doldur ve mail at")
    assert first == second
    assert MIN_SHORTLIST <= len(first) <= MAX_SHORTLIST
    assert "spreadsheet_write" in first
    assert "email_draft" in first


def test_shortlist_always_includes_hinted_capabilities() -> None:
    result = shortlist_capabilities(
        "alakasız bir metin",
        extra_capabilities=["quantum_run_experiment"],
    )
    assert "quantum_run_experiment" in result


# ── Kanonik hash tek otorite ────────────────────────────────────────────────


_STEPS = [
    {"id": "a", "capability": "web_research", "args": {"query": "kuantum"}},
    {"id": "b", "capability": "document_write", "args": {"prompt": "rapor"}, "dependsOn": ["a"]},
]


def test_plan_signature_is_single_authority() -> None:
    assert journal_plan_hash(_STEPS) == compiled_plan.plan_signature(_STEPS)
    plan = compiled_plan.compile_plan(_STEPS, task_id="t1", revision=1)
    assert plan.planHash == compiled_plan.plan_signature(_STEPS)


def test_plan_signature_ignores_private_args_but_binds_public_shape() -> None:
    with_private = [{**_STEPS[0], "args": {"query": "kuantum", "_confirmed": True}}]
    without_private = [{**_STEPS[0], "args": {"query": "kuantum"}}]
    assert compiled_plan.plan_signature(with_private) == compiled_plan.plan_signature(without_private)
    changed_args = [{**_STEPS[0], "args": {"query": "farklı"}}]
    assert compiled_plan.plan_signature(changed_args) != compiled_plan.plan_signature(without_private)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda steps: steps[1].update({"args": {"prompt": "BAŞKA"}}),
        lambda steps: steps[1].update({"dependsOn": []}),
        lambda steps: steps[0].update({"capability": "shell_run"}),
        lambda steps: steps.append({"id": "c", "capability": "email_send", "args": {}}),
    ],
)
def test_tampered_steps_fail_closed(mutate) -> None:
    original = [dict(step) for step in _STEPS]
    expected = compiled_plan.plan_signature(original)
    tampered = [dict(step) for step in original]
    mutate(tampered)
    with pytest.raises(compiled_plan.PlanBindingError):
        compiled_plan.verify_steps_against_hash(tampered, expected)
    # Orijinal hâlâ geçer
    compiled_plan.verify_steps_against_hash(original, expected)


# ── Pending plan bağı: tamper fail-closed + revision ─────────────────────────


def test_pending_plan_binding_blocks_tampering(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate_state(monkeypatch, tmp_path)
    stored = state_store.save_pending_plan({"conversationId": "c1", "steps": [dict(s) for s in _STEPS]})
    plan_id = stored["id"]
    assert state_store.get_pending_plan(plan_id) is not None

    # Tamper: state dosyasındaki adımı doğrudan değiştir (binding'e dokunmadan).
    state = state_store.load_state()
    for item in state["taskIntelligence"]["pendingPlans"]:
        if item.get("id") == plan_id:
            item["steps"][1]["args"]["prompt"] = "kotu amaçlı içerik"
    state_store.save_state(state)

    assert state_store.get_pending_plan(plan_id) is None  # fail-closed


def test_pending_plan_revision_bumps_on_step_change(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _isolate_state(monkeypatch, tmp_path)
    stored = state_store.save_pending_plan({"conversationId": "c1", "steps": [dict(s) for s in _STEPS]})
    plan_id = stored["id"]
    first_binding = stored["planBinding"]
    assert first_binding["revision"] == 1

    # Yalnız yürütme durumu değişirse bağ aynı kalır.
    claimed = state_store.revise_pending_plan(plan_id, {"executionState": "executing"})
    assert claimed["planBinding"]["revision"] == 1
    assert claimed["planBinding"]["planHash"] == first_binding["planHash"]

    # Adımlar değişince (replan/clarification/revizyon) yeni revision + hash.
    revised = state_store.revise_pending_plan(
        plan_id,
        {"steps": [{"id": "a", "capability": "web_research", "args": {"query": "yeni konu"}}]},
    )
    assert revised["planBinding"]["revision"] == 2
    assert revised["planBinding"]["planHash"] != first_binding["planHash"]
    # Yeni bağla plan geçerli okunur.
    assert state_store.get_pending_plan(plan_id) is not None


# ── WorkOrder v2: planHash bağı + tamper fail-closed ─────────────────────────


def _sixteen_step_order() -> dict[str, Any]:
    steps = [
        {
            "id": f"step_{i}",
            "capability": "make_directory",
            "description": f"Klasör {i}",
            "args": {"path": f"~/Desktop/elyan_test_{i}"},
        }
        for i in range(1, MAX_STEPS + 1)
    ]
    return {
        "schema": "elyan.desktop_work_order.v1",
        "source": "mobile_chat_dispatch",
        "goal": {"kind": "task", "summary": "16 adımlı görev", "sourceTextHash": "a" * 24},
        "requiredCapabilities": ["make_directory"],
        "expectedOutputs": [{"kind": "chat_result", "format": "text", "required": True}],
        "verificationRules": [{"id": "r1", "description": "ok", "evidence": "runtime_status"}],
        "execution": {"mode": "cowork_dispatch", "maxSteps": MAX_STEPS},
        "planPreview": {"summary": "16 adım", "steps": steps},
    }


def test_work_order_supports_sixteen_steps_without_truncation() -> None:
    validation = validate_payload({"desktopWorkOrder": _sixteen_step_order()})
    assert validation.ok, validation.errors
    assert len(validation.work_order["planPreview"]["steps"]) == MAX_STEPS


def test_sixteen_step_plan_executes_all_steps() -> None:
    executed: list[str] = []

    def execute_step(capability: str, args: dict[str, Any], state: dict[str, Any], source: str):
        executed.append(str(args.get("index")))
        return {"ok": True, "tool": capability, "output": f"adım {args.get('index')}", "result": {"kind": "x"}, "artifacts": []}, []

    steps = [
        {"id": f"s{i}", "capability": "sys_info", "args": {"index": str(i)}}
        for i in range(1, MAX_STEPS + 1)
    ]
    core = ExecutorCore()
    ok, _summary, _events, error_code, _res, _arts = core.execute_plan_steps(
        steps=steps,
        state_factory=lambda: {},
        execute_step=execute_step,
        source="test",
    )
    assert ok is True and error_code == ""
    assert len(executed) == MAX_STEPS


def _trusted_state(tmp_path: Path) -> dict[str, Any]:
    return {
        "runtime": {
            "deviceId": "device-1",
            "deviceSecret": "s" * 32,
        }
    }


def test_work_order_plan_hash_binds_canonical_steps_and_blocks_tamper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    order = _sixteen_step_order()
    task = {
        "id": "task-16",
        "userId": "user-1",
        "targetDeviceId": "device-1",
        "revision": 1,
        "dispatchLeaseExpiresAt": (
            dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)
        ).isoformat().replace("+00:00", "Z"),
    }
    prepared = prepare_work_order_v2(task, order, prompt="16 adım", state=_trusted_state(tmp_path), ledger=ledger)
    assert prepared["planHash"] == compiled_plan.plan_signature(order["planPreview"]["steps"])

    # Aynı revision'da adım args'ı oynanırsa: planHash uyuşmaz → fail-closed.
    tampered = _sixteen_step_order()
    tampered["planPreview"]["steps"][0]["args"]["path"] = "/tmp/baska"
    with pytest.raises(TrustError) as exc:
        prepare_work_order_v2(task, tampered, prompt="16 adım", state=_trusted_state(tmp_path), ledger=ledger)
    assert exc.value.code == "WORK_ORDER_BINDING_MISMATCH"

    # Yeni revision'la (replan) aynı içerik yeniden bağlanabilir.
    task_v2 = {**task, "revision": 2}
    prepared_v2 = prepare_work_order_v2(task_v2, tampered, prompt="16 adım", state=_trusted_state(tmp_path), ledger=ledger)
    assert prepared_v2["revision"] == 2
    assert prepared_v2["planHash"] != prepared["planHash"]


def test_work_order_approval_lifetime_is_not_bound_to_dispatch_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    order = _sixteen_step_order()
    task = {
        "id": "task-lease",
        "userId": "user-1",
        "targetDeviceId": "device-1",
        "revision": 1,
        "dispatchLeaseExpiresAt": (
            dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=1)
        ).isoformat().replace("+00:00", "Z"),
    }

    prepared = prepare_work_order_v2(
        task, order, prompt="16 adım", state=_trusted_state(tmp_path), ledger=ledger
    )

    assert dt.datetime.fromisoformat(prepared["expiresAt"].replace("Z", "+00:00")) > (
        dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)
    )


def test_expired_work_order_binding_refreshes_for_same_bound_task(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    order = _sixteen_step_order()
    task = {
        "id": "task-refresh",
        "userId": "user-1",
        "targetDeviceId": "device-1",
        "revision": 1,
    }
    prepared = prepare_work_order_v2(
        task, order, prompt="16 adım", state=_trusted_state(tmp_path), ledger=ledger
    )
    with ledger._connect() as connection:
        connection.execute(
            "UPDATE work_orders SET expires_at=? WHERE user_id=? AND task_id=? AND revision=?",
            ("2020-01-01T00:00:00Z", "user-1", "task-refresh", 1),
        )

    refreshed = prepare_work_order_v2(
        task, order, prompt="16 adım", state=_trusted_state(tmp_path), ledger=ledger
    )

    assert refreshed["expiresAt"] != "2020-01-01T00:00:00Z"
    assert refreshed["nonce"] != prepared["nonce"]
    assert dt.datetime.fromisoformat(refreshed["expiresAt"].replace("Z", "+00:00")) > (
        dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)
    )
    assert ledger.claim_approval(refreshed, True) is True


def test_safe_baseline_transform_passes_scope_even_if_undeclared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verisiz yerel dönüşümler tabanda kalır; cihaz/dosya yetkileri kalmaz."""
    from runtime.execution_trust import SAFE_BASELINE_CAPABILITIES

    _isolate_state(monkeypatch, tmp_path)
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    order = _sixteen_step_order()
    assert "text_analyze" not in (order.get("requiredCapabilities") or [])
    task = {
        "id": "task-baseline",
        "userId": "user-1",
        "targetDeviceId": "device-1",
        "revision": 1,
        "dispatchLeaseExpiresAt": (
            dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)
        ).isoformat().replace("+00:00", "Z"),
    }
    prepared = prepare_work_order_v2(
        task, order, prompt="ekranda ne var", state=_trusted_state(tmp_path), ledger=ledger
    )
    assert ledger.claim_delivery(prepared).claimed is True

    # Zararsız yerel dönüşüm: kapsamda bildirilmese de grant verilir.
    grant = ledger.issue_grant(
        prepared,
        step_id="step_transform",
        capability="text_analyze",
        args={"text": "yerel metin"},
        device_secret="s" * 32,
    )
    assert isinstance(grant, dict)

    assert "text_analyze" in SAFE_BASELINE_CAPABILITIES
    assert "file_read" not in SAFE_BASELINE_CAPABILITIES
    assert "analyze_screen" not in SAFE_BASELINE_CAPABILITIES

    # Riskli yetenek hâlâ fail-closed.
    with pytest.raises(TrustError) as exc:
        ledger.issue_grant(
            prepared,
            step_id="step_risky",
            capability="shell_run",
            args={"command": "rm -rf /"},
            device_secret="s" * 32,
        )
    assert exc.value.code == "CAPABILITY_SCOPE_MISMATCH"


def test_model_plan_cannot_expand_the_signed_capability_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    order = _sixteen_step_order()
    order["planPreview"]["steps"] = [
        {"id": "model_added", "capability": "email_send", "args": {"to": ["x@example.test"]}}
    ]
    task = {
        "id": "task-model-scope",
        "userId": "user-1",
        "targetDeviceId": "device-1",
        "revision": 1,
    }

    prepared = prepare_work_order_v2(
        task, order, prompt="16 adım", state=_trusted_state(tmp_path), ledger=ledger
    )

    assert "email_send" not in prepared["capabilityScope"]
    assert "make_directory" in prepared["capabilityScope"]


def test_server_materialized_scope_replaces_heuristic_capability_hints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    order = _sixteen_step_order()
    order["planPreview"]["steps"] = [
        {"id": "write", "capability": "document_write", "args": {"prompt": "rapor"}}
    ]
    order["materializedCapabilityScope"] = ["document_write"]
    task = {
        "id": "task-server-scope",
        "userId": "user-1",
        "targetDeviceId": "device-1",
        "revision": 1,
    }

    prepared = prepare_work_order_v2(
        task, order, prompt="16 adım", state=_trusted_state(tmp_path), ledger=ledger
    )

    assert "document_write" in prepared["capabilityScope"]
    assert "make_directory" not in prepared["capabilityScope"]


def test_timed_out_delivery_rejects_new_and_preissued_grants(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    ledger = ExecutionLedger(tmp_path / "ledger.sqlite3")
    order = _sixteen_step_order()
    task = {
        "id": "task-timeout-authority",
        "userId": "user-1",
        "targetDeviceId": "device-1",
        "revision": 1,
    }
    prepared = prepare_work_order_v2(
        task, order, prompt="16 adım", state=_trusted_state(tmp_path), ledger=ledger
    )
    assert ledger.claim_delivery(prepared).claimed is True
    args = {"path": "~/Desktop/test"}
    grant = ledger.issue_grant(
        prepared,
        step_id="step_1",
        capability="make_directory",
        args=args,
        device_secret="s" * 32,
    )
    ledger.set_delivery_status("user-1", "task-timeout-authority", 1, "timed_out")

    with pytest.raises(TrustError) as new_grant_error:
        ledger.issue_grant(
            prepared,
            step_id="step_2",
            capability="make_directory",
            args={"path": "~/Desktop/test-2"},
            device_secret="s" * 32,
        )
    assert new_grant_error.value.code == "WORK_ORDER_NOT_EXECUTING"

    with pytest.raises(TrustError) as consume_error:
        ledger.consume_grant(
            grant,
            capability="make_directory",
            args=args,
            trust_context={
                "userId": "user-1",
                "taskId": "task-timeout-authority",
                "revision": 1,
                "stepId": "step_1",
            },
            device_secret="s" * 32,
        )
    assert consume_error.value.code == "WORK_ORDER_NOT_EXECUTING"
