"""elyan.plan.v1 yapılandırılmış planlama sözleşmesi testleri.

Masaüstü ↔ sunucu beyni planlama iletişiminin tamamen veri (JSON) olarak
gitmesini, yanıtların şemayla doğrulanmasını ve bozuk planların güvenle
reddedilmesini garanti eder.
"""
from __future__ import annotations

import json

from runtime import structured_planner as sp


# ── İstek zarfı ────────────────────────────────────────────────────────────────


def test_planning_request_is_pure_json_data() -> None:
    request = sp.build_planning_request("safariyi aç")
    # Tamamı JSON-serileştirilebilir olmalı; prompt düz metin cümle değil,
    # bu zarfın kendisi.
    encoded = sp.planning_prompt(request)
    decoded = json.loads(encoded)
    assert decoded["type"] == "elyan.plan.request"
    assert decoded["contract"] == sp.PLAN_CONTRACT
    assert decoded["request"]["text"] == "safariyi aç"
    assert isinstance(decoded["toolCatalog"], list) and decoded["toolCatalog"]
    assert decoded["responseSchema"]["properties"]["contract"]["const"] == sp.PLAN_CONTRACT
    assert decoded["rules"]["role"] == "planner_only"


def test_tool_catalog_has_json_schema_and_execution_metadata() -> None:
    catalog = {tool["name"]: tool for tool in sp.tool_catalog(platform="darwin")}
    open_app = catalog["open_app"]
    assert open_app["parameters"]["type"] == "object"
    assert open_app["parameters"]["properties"]["app_name"]["type"] == "string"
    assert "app_name" in open_app["parameters"]["required"]
    assert open_app["sideEffect"] is True
    browser = catalog["browser_control"]
    assert sorted(browser["parameters"]["properties"]["action"]["enum"]) == [
        "open_url",
        "play_youtube",
        "search",
    ]


# ── Plan doğrulama ────────────────────────────────────────────────────────────


def _plan(steps, **extra):
    return {
        "contract": sp.PLAN_CONTRACT,
        "intent": "task",
        "goal": "test",
        "confidence": 0.9,
        "privacyClass": "local_private",
        "steps": steps,
        **extra,
    }


def test_valid_single_step_plan() -> None:
    plan, errors = sp.validate_plan(_plan([{"capability": "open_app", "args": {"app_name": "Safari"}}]))
    assert plan is not None
    assert not [e for e in errors if "zorunlu" in e]
    assert plan["steps"][0]["args"] == {"app_name": "Safari"}
    # open_app yan etkili → onay zorunlu hale gelir
    assert plan["requiresConfirmation"] is True


def test_unknown_capability_rejected() -> None:
    plan, errors = sp.validate_plan(_plan([{"capability": "rm_rf_everything", "args": {}}]))
    assert plan is None
    assert any("bilinmeyen capability" in e for e in errors)


def test_unknown_args_pruned_and_types_coerced() -> None:
    plan, _errors = sp.validate_plan(
        _plan([
            {
                "capability": "get_calendar_events",
                "args": {"query": "bugün", "limit": "5", "evil_flag": True},
            }
        ])
    )
    assert plan is not None
    args = plan["steps"][0]["args"]
    assert args["limit"] == 5          # "5" → 5
    assert "evil_flag" not in args      # bildirimde olmayan argüman budanır


def test_enum_constraint_normalized() -> None:
    plan, errors = sp.validate_plan(
        _plan([{"capability": "browser_control", "args": {"action": "OPEN_URL", "url": "https://x.com"}}])
    )
    assert plan is not None
    assert plan["steps"][0]["args"]["action"] == "open_url"
    assert not errors


def test_missing_required_arg_flagged() -> None:
    plan, errors = sp.validate_plan(_plan([{"capability": "open_app", "args": {}}]))
    assert any("zorunlu argüman eksik" in e for e in errors)
    # Tek adım ve bloklayıcı hata → plan reddedilir
    assert plan is None


def test_clarification_plan_maps_to_question() -> None:
    plan, _errors = sp.validate_plan(
        _plan([], clarification={"needed": True, "question": "Hangi dosyayı özetleyeyim?"})
    )
    assert plan is not None
    payload = sp.plan_to_semantic_payload(plan)
    assert payload["capability"] == ""
    assert payload["clarificationQuestion"] == "Hangi dosyayı özetleyeyim?"


def test_multi_step_plan_maps_to_plan_preview() -> None:
    plan, _errors = sp.validate_plan(
        _plan([
            {"capability": "web_research", "args": {"query": "kuantum"}},
            {"capability": "document_write", "args": {"prompt": "kuantum raporu"}},
        ])
    )
    assert plan is not None
    payload = sp.plan_to_semantic_payload(plan)
    assert payload["isMultiStep"] is True
    assert payload["requiresConfirmation"] is True
    steps = payload["planPreview"]["steps"]
    assert [s["capability"] for s in steps] == ["web_research", "document_write"]
    agent_plan = payload["planPreview"]["agentPlan"]
    assert agent_plan["stepCount"] == 2


def test_non_dict_payload_rejected() -> None:
    plan, errors = sp.validate_plan("düz metin cevap")
    assert plan is None
    assert errors


# ── Öğrenilmiş bağlam ve onarım turu ──────────────────────────────────────────


def test_intelligence_context_is_structured_records() -> None:
    state = {
        "taskIntelligence": {
            "recentSuccessfulRoutes": [
                {"query": "safariyi aç", "capability": "open_app", "intent": "open_app"},
            ],
            "recentMisroutes": [
                {"query": "notları belgele", "capability": "shell_run"},
            ],
            "confirmedPlanPatterns": [
                {"query": "araştır ve belgele", "capability": "web_research"},
            ],
        }
    }
    records = sp.intelligence_context(state)
    kinds = {record["kind"] for record in records}
    assert kinds == {"success", "misroute", "confirmed_plan"}
    for record in records:
        assert set(record) <= {"kind", "query", "capability", "intent"}
        assert record["query"]


def test_intelligence_context_empty_state() -> None:
    assert sp.intelligence_context({}) == []
    assert sp.intelligence_context({"taskIntelligence": "bozuk"}) == []


def test_build_repair_request_carries_errors_and_schema() -> None:
    envelope = sp.build_planning_request("safariyi aç")
    invalid = {"contract": sp.PLAN_CONTRACT, "steps": [{"capability": "uydurma_arac"}]}
    _plan, errors = sp.validate_plan(invalid)
    repair = sp.build_repair_request(envelope, invalid, errors)
    assert repair["type"] == "elyan.plan.repair"
    assert repair["contract"] == sp.PLAN_CONTRACT
    assert repair["invalidResponse"] == invalid
    assert repair["validationErrors"]
    assert repair["responseSchema"] == envelope["responseSchema"]
    assert "repair" in repair["rules"]


def test_planning_request_includes_recent_intents() -> None:
    envelope = sp.build_planning_request(
        "youtube'a gir",
        recent_intents=[{"kind": "success", "query": "safariyi aç", "capability": "open_app"}],
    )
    assert envelope["context"]["recentIntents"][0]["capability"] == "open_app"
