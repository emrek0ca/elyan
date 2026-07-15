"""P5 — Planner eval seti: güvenlik regresyonları + plan kalite ölçümleri.

`run_planner_eval()` gömülü vakaları `structured_planner.validate_plan`
üzerinden koşturur. Her vaka bir sözleşme iddiasıdır: geçerli plan kabul
edilir, bilinmeyen capability / eksik bağımlılık / DAG döngüsü / yasak eylem
fail-closed reddedilir. CI veya `pytest` bu raporu regresyon kapısı olarak
kullanır; vakalar ham kullanıcı verisi içermez.
"""

from __future__ import annotations

from typing import Any

from runtime import structured_planner as sp


def _goal_contract(**overrides: Any) -> dict[str, Any]:
    contract = {
        "contract": sp.GOAL_CONTRACT,
        "objective": "eval",
        "deliverables": [],
        "constraints": [],
        "acceptanceCriteria": [],
        "prohibitedActions": [],
        "privacy": "local_private",
        "risk": "low",
        "priority": "normal",
        "missingInformation": [],
    }
    contract.update(overrides)
    return contract


def _plan(steps: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    payload = {
        "contract": sp.PLAN_CONTRACT,
        "intent": "task",
        "goal": "eval",
        "goalContract": _goal_contract(**extra.pop("goalContract", {})),
        "confidence": 0.9,
        "privacyClass": "local_private",
        "steps": steps,
    }
    payload.update(extra)
    return payload


EVAL_CASES: list[dict[str, Any]] = [
    {
        "id": "accept_single_step",
        "kind": "quality",
        "payload": _plan([{"capability": "open_app", "args": {"app_name": "Safari"}}]),
        "expectAccepted": True,
    },
    {
        "id": "accept_dependent_steps",
        "kind": "quality",
        "payload": _plan([
            {"id": "s1", "capability": "retrieve_context", "args": {"query": "not"}},
            {"id": "s2", "capability": "sys_info", "args": {"query": "battery"}, "dependsOn": ["s1"]},
        ]),
        "expectAccepted": True,
    },
    {
        "id": "reject_unknown_capability",
        "kind": "security",
        "payload": _plan([{"capability": "rm_rf_everything", "args": {}}]),
        "expectAccepted": False,
    },
    {
        "id": "reject_missing_dependency",
        "kind": "security",
        "payload": _plan([
            {"id": "s1", "capability": "sys_info", "args": {}, "dependsOn": ["hayalet"]},
        ]),
        "expectAccepted": False,
    },
    {
        "id": "reject_dependency_cycle",
        "kind": "security",
        "payload": _plan([
            {"id": "a", "capability": "sys_info", "args": {}, "dependsOn": ["b"]},
            {"id": "b", "capability": "retrieve_context", "args": {"query": "x"}, "dependsOn": ["a"]},
        ]),
        "expectAccepted": False,
    },
    {
        "id": "reject_prohibited_capability_step",
        "kind": "security",
        "payload": _plan(
            [{"capability": "open_app", "args": {"app_name": "Safari"}}],
            goalContract={"prohibitedActions": ["capability:open_app"]},
        ),
        "expectAccepted": False,
    },
    {
        "id": "reject_missing_required_arg",
        "kind": "security",
        "payload": _plan([{"capability": "open_app", "args": {}}]),
        "expectAccepted": False,
    },
    {
        "id": "clarification_single_question",
        "kind": "quality",
        "payload": _plan([], clarification={"needed": True, "question": "Hangi dosya?"}),
        "expectAccepted": True,
        "expectQuestion": True,
    },
]


def run_planner_eval() -> dict[str, Any]:
    """Eval setini koşturur; başarısız vakaları ve kalite metriklerini raporlar."""
    failures: list[dict[str, str]] = []
    security_total = 0
    security_passed = 0
    for case in EVAL_CASES:
        plan, errors = sp.validate_plan(case["payload"])
        accepted = plan is not None
        expected = bool(case["expectAccepted"])
        ok = accepted is expected
        if ok and case.get("expectQuestion"):
            question = str((plan or {}).get("clarification", {}).get("question", "") or "")
            ok = bool(question)
        if case["kind"] == "security":
            security_total += 1
            security_passed += 1 if ok else 0
        if not ok:
            failures.append({
                "id": str(case["id"]),
                "expected": "accept" if expected else "reject",
                "got": "accept" if accepted else "reject",
                "errors": "; ".join(errors)[:400],
            })
    total = len(EVAL_CASES)
    return {
        "total": total,
        "passed": total - len(failures),
        "failures": failures,
        "securityRegressions": security_total - security_passed,
        "qualityScore": round((total - len(failures)) / total, 3) if total else 1.0,
    }
