"""Görsel operatör planlama sözleşmesi — elyan.operator.v1

`structured_planner` (elyan.plan.v2) capability tabanlı görev planları üretir;
bu modül ikinci planlama yüzeyini — ekran otomasyonu (GUI) adımlarını — aynı
veri sözleşmesi disiplinine taşır:

- İstek: eylem kataloğu (izinli alanlarla), sanitize edilmiş ekran gözlemi,
  kurallar ve beklenen yanıt şeması içeren tek bir JSON zarfı.
- Yanıt: şemaya uyan tek bir plan JSON'u. Serbest metin yok.
- Doğrulama: eylem enum'u, alan tipleri ve güvenlik kısıtları TEK yerde
  (burada) doğrulanır; bilinmeyen alanlar budanır.

Sunucu beyni yalnız PLANLAR; yürütme her zaman masaüstü runtime'ındadır.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from typing import Any

OPERATOR_CONTRACT = "elyan.operator.v1"

# İzinli GUI eylemleri ve her eylemin taşıyabileceği alanlar. Bilinmeyen alan
# doğrulamada budanır; burada olmayan eylem tümüyle reddedilir.
ACTION_FIELDS: dict[str, tuple[str, ...]] = {
    "click": ("targetText", "elementType", "appName"),
    "double_click": ("targetText", "elementType", "appName"),
    "right_click": ("targetText", "elementType", "appName"),
    "type_text": ("targetText", "elementType", "text", "appName"),
    "scroll": ("targetText", "elementType", "delta", "appName"),
    "hotkey": ("keys", "appName"),
    "wait": ("duration",),
    "focus_window": ("appName",),
}

ALLOWED_ACTIONS = frozenset(ACTION_FIELDS)

_FIELD_TYPES: dict[str, str] = {
    "targetText": "string",
    "elementType": "string",
    "text": "string",
    "appName": "string",
    "keys": "array",
    "delta": "number",
    "duration": "number",
}

MAX_STEPS = 4


def action_catalog() -> list[dict[str, Any]]:
    """Sunucu beynine gönderilen eylem kataloğu: her eylem ve izinli alanları."""
    catalog: list[dict[str, Any]] = []
    for action in sorted(ACTION_FIELDS):
        fields = ACTION_FIELDS[action]
        catalog.append(
            {
                "action": action,
                "fields": {name: {"type": _FIELD_TYPES.get(name, "string")} for name in fields},
            }
        )
    return catalog


def _summarize_observation(observation: dict[str, Any], native_desktop: dict[str, Any] | None) -> dict[str, Any]:
    native = native_desktop if isinstance(native_desktop, dict) else {}
    native_active_window = native.get("activeWindow", {})
    native_active_window = native_active_window if isinstance(native_active_window, dict) else {}
    native_processes = native.get("processes", {})
    native_processes = native_processes if isinstance(native_processes, dict) else {}
    native_operator = native.get("operator", {})
    native_operator = native_operator if isinstance(native_operator, dict) else {}

    elements = observation.get("elements", [])
    elements = [dict(item) for item in elements if isinstance(item, dict)]
    summarized = []
    for item in elements[:24]:
        summarized.append(
            {
                "type": str(item.get("type", "") or ""),
                "text": " ".join(str(item.get("text", "") or "").split()).strip()[:96],
                "source": str(item.get("source", "") or ""),
                "role": str(item.get("role", "") or ""),
                "focused": bool(item.get("focused", False)),
                "enabled": bool(item.get("enabled", True)),
            }
        )
    return {
        "activeApp": str(observation.get("activeApp", "") or ""),
        "activeWindow": str(observation.get("activeWindow", "") or ""),
        "resolutionMode": str(observation.get("resolutionMode", "") or ""),
        "elements": summarized,
        "nativeDesktop": {
            "available": bool(native.get("available", False)),
            "platform": str(native.get("platform", "") or ""),
            "source": str(native.get("source", "") or ""),
            "activeWindow": {
                "appName": str(native_active_window.get("appName", "") or ""),
                "windowTitle": str(native_active_window.get("windowTitle", "") or ""),
            },
            "processCount": int(native_processes.get("total", 0) or 0),
            "operatorReady": bool(native_operator.get("available", False)),
            "accessibilityReady": bool(native_operator.get("accessibilityReady", False)),
            "inputControlReady": bool(native_operator.get("inputControlReady", False)),
        },
    }


def response_schema() -> dict[str, Any]:
    """Sunucu beyninin döndürmek ZORUNDA olduğu operatör plan şeması."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["contract", "steps", "confidence"],
        "properties": {
            "contract": {"const": OPERATOR_CONTRACT},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "message": {"type": "string"},
            "clarificationQuestion": {"type": "string"},
            "steps": {
                "type": "array",
                "maxItems": MAX_STEPS,
                "items": {
                    "type": "object",
                    "required": ["action"],
                    "properties": {
                        "action": {"enum": sorted(ALLOWED_ACTIONS)},
                        "targetText": {"type": "string"},
                        "elementType": {"type": "string"},
                        "text": {"type": "string"},
                        "keys": {"type": "array", "items": {"type": "string"}},
                        "delta": {"type": "number"},
                        "duration": {"type": "number"},
                        "appName": {"type": "string"},
                    },
                },
            },
        },
    }


def build_operator_request(
    goal: str,
    observation: dict[str, Any],
    *,
    native_desktop: dict[str, Any] | None = None,
    locale: str = "tr",
) -> dict[str, Any]:
    """Düz metin operatör prompt'u yerine gönderilen planlama isteği zarfı."""
    platform = "darwin" if sys.platform == "darwin" else sys.platform
    return {
        "type": "elyan.operator.request",
        "contract": OPERATOR_CONTRACT,
        "request": {
            "goal": str(goal or "").strip(),
            "locale": locale,
            "platform": platform,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        },
        "observation": _summarize_observation(observation, native_desktop),
        "actionCatalog": action_catalog(),
        "rules": {
            "role": "operator_planner_only",
            "execution": "desktop_runtime",
            "outputFormat": "single_json_object",
            "grounding": "use only the sanitized screen metadata in observation; never invent unseen UI",
            "stepLimit": MAX_STEPS,
            "ambiguity": "if the target is ambiguous or unsafe, return empty steps and one short clarificationQuestion",
        },
        "responseSchema": response_schema(),
    }


def operator_prompt(request_envelope: dict[str, Any]) -> str:
    """Model API'lerine gönderilen ham içerik — çıplak JSON, süsleme yok."""
    return json.dumps(request_envelope, ensure_ascii=False)


def build_repair_request(
    request_envelope: dict[str, Any],
    invalid_response: Any,
    errors: list[str],
) -> dict[str, Any]:
    """Geçersiz operatör planı için tek turluk yapılandırılmış onarım isteği."""
    return {
        "type": "elyan.operator.repair",
        "contract": OPERATOR_CONTRACT,
        "request": request_envelope.get("request", {}),
        "observation": request_envelope.get("observation", {}),
        "actionCatalog": request_envelope.get("actionCatalog", []),
        "rules": {
            **(request_envelope.get("rules", {}) if isinstance(request_envelope.get("rules"), dict) else {}),
            "repair": "fix validationErrors and return one corrected JSON object conforming to responseSchema; no prose",
        },
        "responseSchema": request_envelope.get("responseSchema", {}),
        "invalidResponse": invalid_response if isinstance(invalid_response, (dict, list, str)) else str(invalid_response),
        "validationErrors": [str(item) for item in errors[:12]],
    }


# ── Doğrulama ────────────────────────────────────────────────────────────────


def _coerce_field(value: Any, expected: str) -> tuple[Any, bool]:
    if expected == "string":
        return ("" if value is None else str(value)), True
    if expected == "number":
        try:
            number = float(value)
            return (int(number) if number.is_integer() else number), True
        except (TypeError, ValueError):
            return value, False
    if expected == "array":
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value], True
        return value, False
    return value, True


def _validate_step(index: int, raw: Any) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    if not isinstance(raw, dict):
        return None, [f"steps[{index}]: nesne değil"]
    action = str(raw.get("action", "") or "").strip().lower()
    if action not in ALLOWED_ACTIONS:
        return None, [f"steps[{index}]: bilinmeyen eylem {action!r}"]
    allowed_fields = ACTION_FIELDS[action]
    step: dict[str, Any] = {"action": action}
    for name in allowed_fields:
        if name not in raw:
            continue
        expected = _FIELD_TYPES.get(name, "string")
        coerced, ok = _coerce_field(raw.get(name), expected)
        if not ok:
            errors.append(f"steps[{index}].{name}: {expected} bekleniyordu")
            continue
        step[name] = coerced
    # Eyleme özgü zorunluluklar
    if action == "type_text" and not str(step.get("text", "") or "").strip():
        errors.append(f"steps[{index}].text: type_text için zorunlu")
        return None, errors
    if action == "hotkey" and not (isinstance(step.get("keys"), list) and step["keys"]):
        errors.append(f"steps[{index}].keys: hotkey için zorunlu")
        return None, errors
    return step, errors


def validate_operator_plan(payload: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """Sunucudan gelen operatör planını sözleşmeye göre doğrular ve normalize eder.

    Dönen plan: {steps[{action, ...izinli alanlar}], confidence, message,
    clarificationQuestion}. Doğrulanamayan plan için (None, errors).
    """
    errors: list[str] = []
    if not isinstance(payload, dict):
        return None, ["plan bir JSON nesnesi değil"]

    contract = str(payload.get("contract", "") or "")
    if contract and contract != OPERATOR_CONTRACT:
        errors.append(f"bilinmeyen sözleşme: {contract}")

    try:
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.0) or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
        errors.append("confidence sayı değil")

    clarification = str(payload.get("clarificationQuestion", "") or "").strip()
    message = str(payload.get("message", "") or "").strip()

    raw_steps = payload.get("steps")
    raw_steps = raw_steps if isinstance(raw_steps, list) else []
    steps: list[dict[str, Any]] = []
    for position, raw in enumerate(raw_steps[:MAX_STEPS], start=1):
        step, step_errors = _validate_step(position, raw)
        errors.extend(step_errors)
        if step is not None:
            steps.append(step)

    plan = {
        "steps": steps,
        "confidence": confidence,
        "message": message,
        "clarificationQuestion": clarification,
    }
    # Ne adım ne de netleştirme sorusu varsa plan işe yaramaz.
    if not steps and not clarification:
        return None, errors or ["operatör planı boş: adım veya netleştirme sorusu yok"]
    return plan, errors
