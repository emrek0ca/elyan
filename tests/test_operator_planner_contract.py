"""elyan.operator.v1 görsel operatör planlama sözleşmesi testleri.

Ekran otomasyonu (GUI) planlama yüzeyinin de tamamen veri (JSON) sözleşmesiyle
çalışmasını, yanıtların şemayla doğrulanmasını ve bozuk/güvensiz planların
güvenle reddedilmesini garanti eder.
"""
from __future__ import annotations

import json

from runtime import operator_planner as op


_OBSERVATION = {
    "activeApp": "Safari",
    "activeWindow": "Docs",
    "resolutionMode": "browser_first",
    "elements": [
        {"type": "button", "text": "Continue", "source": "browser_dom", "focused": True},
    ],
}


# ── İstek zarfı ────────────────────────────────────────────────────────────────


def test_operator_request_is_pure_json_data() -> None:
    request = op.build_operator_request("devam butonuna bas", _OBSERVATION)
    encoded = op.operator_prompt(request)
    decoded = json.loads(encoded)
    assert decoded["type"] == "elyan.operator.request"
    assert decoded["contract"] == op.OPERATOR_CONTRACT
    assert decoded["request"]["goal"] == "devam butonuna bas"
    assert isinstance(decoded["actionCatalog"], list) and decoded["actionCatalog"]
    assert decoded["observation"]["activeApp"] == "Safari"
    assert decoded["responseSchema"]["properties"]["contract"]["const"] == op.OPERATOR_CONTRACT
    assert decoded["rules"]["role"] == "operator_planner_only"


def test_action_catalog_lists_allowed_actions_and_fields() -> None:
    catalog = {entry["action"]: entry for entry in op.action_catalog()}
    assert set(catalog) == set(op.ALLOWED_ACTIONS)
    assert "text" in catalog["type_text"]["fields"]
    assert catalog["hotkey"]["fields"]["keys"]["type"] == "array"
    assert catalog["wait"]["fields"]["duration"]["type"] == "number"


def test_observation_is_sanitized_and_truncated() -> None:
    noisy = {
        "activeApp": "Safari",
        "elements": [{"type": "button", "text": "x" * 200, "secret": "leak"} for _ in range(40)],
    }
    request = op.build_operator_request("goal", noisy)
    elements = request["observation"]["elements"]
    assert len(elements) == 24  # ilk 24 ile sınırlı
    assert len(elements[0]["text"]) <= 96
    assert "secret" not in elements[0]  # yalnız izinli alanlar taşınır


# ── Doğrulama ──────────────────────────────────────────────────────────────────


def test_validate_normalizes_and_prunes_unknown_fields() -> None:
    plan, errors = op.validate_operator_plan(
        {
            "contract": op.OPERATOR_CONTRACT,
            "confidence": 0.9,
            "steps": [
                {"action": "CLICK", "targetText": "Continue", "bogus": "drop"},
                {"action": "type_text", "text": "merhaba", "targetText": "search"},
            ],
        }
    )
    assert errors == []
    assert plan is not None
    assert plan["steps"][0]["action"] == "click"
    assert "bogus" not in plan["steps"][0]
    assert plan["steps"][1]["text"] == "merhaba"
    assert plan["confidence"] == 0.9


def test_validate_rejects_unknown_action() -> None:
    plan, errors = op.validate_operator_plan(
        {"steps": [{"action": "delete_everything", "targetText": "x"}]}
    )
    assert plan is None
    assert any("bilinmeyen eylem" in e for e in errors)


def test_validate_requires_text_for_type_text() -> None:
    plan, errors = op.validate_operator_plan({"steps": [{"action": "type_text", "targetText": "field"}]})
    assert plan is None
    assert any("type_text için zorunlu" in e for e in errors)


def test_validate_requires_keys_for_hotkey() -> None:
    plan, errors = op.validate_operator_plan({"steps": [{"action": "hotkey"}]})
    assert plan is None
    assert any("hotkey için zorunlu" in e for e in errors)


def test_validate_accepts_clarification_without_steps() -> None:
    plan, errors = op.validate_operator_plan(
        {"steps": [], "clarificationQuestion": "Hangi butona basayım?"}
    )
    assert plan is not None
    assert plan["steps"] == []
    assert plan["clarificationQuestion"] == "Hangi butona basayım?"


def test_validate_rejects_empty_plan() -> None:
    plan, errors = op.validate_operator_plan({"steps": [], "clarificationQuestion": ""})
    assert plan is None
    assert errors


def test_validate_step_limit_enforced() -> None:
    steps = [{"action": "wait", "duration": 1} for _ in range(10)]
    plan, _errors = op.validate_operator_plan({"steps": steps})
    assert plan is not None
    assert len(plan["steps"]) == op.MAX_STEPS


def test_repair_request_carries_errors_and_schema() -> None:
    request = op.build_operator_request("goal", _OBSERVATION)
    repair = op.build_repair_request(request, {"steps": "oops"}, ["steps: nesne değil"])
    assert repair["type"] == "elyan.operator.repair"
    assert repair["contract"] == op.OPERATOR_CONTRACT
    assert repair["validationErrors"] == ["steps: nesne değil"]
    assert repair["responseSchema"] == request["responseSchema"]
    assert repair["rules"]["repair"]
