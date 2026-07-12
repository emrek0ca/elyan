"""Yapılandırılmış planlama sözleşmesi — elyan.plan.v1

Masaüstü ↔ sunucu beyni iletişimini düz metin prompttan çıkarıp tamamen
veri sözleşmesine taşır:

- İstek: araç kataloğu (JSON Schema parametreli), skill/MCP envanteri,
  bağlam ve beklenen yanıt şeması içeren tek bir JSON zarfı.
- Yanıt: şemaya uyan tek bir plan JSON'u. Serbest metin yok.
- Doğrulama: capability varlığı, argüman tipleri, zorunlu alanlar ve enum
  kısıtları TEK yerde (burada) doğrulanır; bilinmeyen argümanlar budanır.

Sunucu beyni yalnız PLANLAR; yürütme her zaman masaüstü runtime'ındadır.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from functools import lru_cache
from typing import Any

from runtime.agent_planning import build_agent_plan
from runtime.capability_registry import TOOL_DECLARATIONS, capability_metadata, capability_names

PLAN_CONTRACT = "elyan.plan.v1"
# Cowork bağlam zarfı sözleşmesi: server_brain'e sohbet/cowork turunda giden
# yapılandırılmış (düz metin değil) bağlam. Sorgu labeled alanda, bağlam metadata
# JSON'unda — brain sunucuda yeniden türetmeden anlar/planlar (daha az yük).
COWORK_CONTRACT = "elyan.cowork.v1"

# Argüman enum kısıtları — daha önce bridge._semantic_route içinde dağınık
# if bloklarıydı; artık sözleşmenin parçası.
ENUM_CONSTRAINTS: dict[str, dict[str, set[str]]] = {
    "browser_control": {"action": {"search", "open_url", "play_youtube"}},
    "document_read": {"mode": {"read", "summary", "bullets"}},
    "ocr_read": {"mode": {"read", "summary", "bullets"}},
    "image_read": {"mode": {"summary", "metadata", "palette"}},
    "data_analyze": {"mode": {"summary", "profile", "preview"}},
    "chart_generate": {"chartType": {"bar", "line", "scatter", "histogram"}},
    "math_solve": {"mode": {"solve", "simplify", "factor", "expand", "evaluate"}},
    "latex_parse": {"mode": {"parse", "normalize"}},
}

_TYPE_MAP = {"STRING": "string", "NUMBER": "number", "BOOLEAN": "boolean", "OBJECT": "object", "ARRAY": "array"}


def _declaration_index() -> dict[str, dict[str, Any]]:
    return {str(decl.get("name", "")): decl for decl in TOOL_DECLARATIONS if isinstance(decl, dict)}


def tool_catalog(*, platform: str = "") -> list[dict[str, Any]]:
    """Sunucu beynine gönderilen araç kataloğu: her araç JSON Schema
    parametreleri + yürütme meta verisiyle (yan etki, onay, platform).

    Katalog statik TOOL_DECLARATIONS'tan üretilir → platform başına önbelleğe
    alınır (her planlama çağrısında yeniden kurulmaz; salt-okunur tüketilir)."""
    platform = platform or ("darwin" if sys.platform == "darwin" else sys.platform)
    return _tool_catalog_cached(platform)


@lru_cache(maxsize=8)
def _tool_catalog_cached(platform: str) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for decl in TOOL_DECLARATIONS:
        if not isinstance(decl, dict):
            continue
        name = str(decl.get("name", "") or "")
        if not name:
            continue
        metadata = capability_metadata(name)
        supported = metadata.get("supportedPlatforms", ())
        if supported and platform not in tuple(supported):
            continue
        raw_params = decl.get("parameters", {}) if isinstance(decl.get("parameters"), dict) else {}
        raw_props = raw_params.get("properties", {}) if isinstance(raw_params.get("properties"), dict) else {}
        properties: dict[str, Any] = {}
        for key, value in raw_props.items():
            if not isinstance(value, dict):
                continue
            prop: dict[str, Any] = {
                "type": _TYPE_MAP.get(str(value.get("type", "STRING")).upper(), "string")
            }
            # Skill-benzeri: her argümanın açıklaması planlayıcıya taşınır
            # (doğru argüman seçimi için — eskiden düşürülüyordu).
            arg_desc = str(value.get("description", "") or "").strip()
            if arg_desc:
                prop["description"] = arg_desc
            properties[key] = prop
        for arg_name, allowed in ENUM_CONSTRAINTS.get(name, {}).items():
            if arg_name in properties:
                properties[arg_name]["enum"] = sorted(allowed)
        entry: dict[str, Any] = {
            "name": name,
            "description": str(decl.get("description", "") or ""),
            "parameters": {
                "type": "object",
                "properties": properties,
            },
            "sideEffect": bool(metadata.get("sideEffect", False)),
            "requiresApproval": str(metadata.get("permissionClass", "") or "") == "approval_required",
        }
        required = raw_params.get("required")
        if isinstance(required, list) and required:
            entry["parameters"]["required"] = [str(item) for item in required]
        # Skill-benzeri kullanım rehberi + örnekler (varsa) planlayıcıya gider.
        usage = str(decl.get("usage", "") or "").strip()
        if usage:
            entry["usage"] = usage
        examples = decl.get("examples")
        if isinstance(examples, list) and examples:
            entry["examples"] = [ex for ex in examples if isinstance(ex, dict)][:3]
        catalog.append(entry)
    return catalog


def response_schema() -> dict[str, Any]:
    """Sunucu beyninin döndürmek ZORUNDA olduğu plan şeması."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["contract", "intent", "confidence", "steps"],
        "properties": {
            "contract": {"const": PLAN_CONTRACT},
            "intent": {"type": "string"},
            "goal": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "privacyClass": {"enum": ["local_private", "public_text"]},
            "requiresConfirmation": {"type": "boolean"},
            "clarification": {
                "type": "object",
                "properties": {
                    "needed": {"type": "boolean"},
                    "question": {"type": "string"},
                },
            },
            "steps": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "required": ["capability"],
                    "properties": {
                        "id": {"type": "string"},
                        "capability": {"type": "string"},
                        "args": {"type": "object"},
                        "description": {"type": "string"},
                        "dependsOn": {"type": "array", "items": {"type": "string"}},
                        # Önceki bir adımın liste çıktısı üzerinde fan-out:
                        # "{{steps.<id>.result.items}}" — kopyalarda {{item...}}
                        # ve {{index}} kullanılabilir (bkz. executor_core).
                        "forEach": {"type": "string"},
                    },
                },
            },
        },
    }


REPLAN_CONTRACT = "elyan.replan.v1"


def build_replan_observation(context: dict[str, Any]) -> dict[str, Any]:
    """Yürütme sırasında bir adım başarısız/doğrulanamaz olunca üretilen
    yapılandırılmış gözlem (elyan.replan.v1) — düz metin değil, labeled JSON.
    Deterministik kurtarma bunu tanılamaya yazar; deploy turunda server_brain
    bu gözlemle akıllı replan üretecek (plan→adım→gözlem→uyarla döngüsü)."""
    ctx = context if isinstance(context, dict) else {}
    completed: list[dict[str, Any]] = []
    for output in (ctx.get("completedOutputs") or [])[:8]:
        preview = " ".join(str(output or "").split())[:200]
        if preview:
            completed.append({"outputPreview": preview})
    failed_args = ctx.get("failedArgs")
    failed_args = failed_args if isinstance(failed_args, dict) else {}
    remaining: list[dict[str, Any]] = []
    for step in (ctx.get("remainingSteps") or []):
        if isinstance(step, dict) and str(step.get("capability", "") or "").strip():
            remaining.append({
                "capability": str(step.get("capability", "") or "").strip(),
                "description": " ".join(str(step.get("description", "") or "").split())[:160],
            })
    failed_step: dict[str, Any] = {
        "capability": str(ctx.get("failedCapability", "") or ""),
        "errorCode": str(ctx.get("errorCode", "") or ""),
        "message": " ".join(str(ctx.get("message", "") or "").split())[:300],
        "args": {k: v for k, v in failed_args.items() if not str(k).startswith("_")},
    }
    # APP_NOT_FOUND gibi düzeltilebilir hatalarda planlayıcıya somut alternatif
    # adaylar ver (ör. kurulu uygulama adları) — "adı düzelt" sinyali.
    suggestions = [str(s).strip() for s in (ctx.get("appSuggestions") or []) if str(s or "").strip()]
    if suggestions:
        failed_step["suggestions"] = suggestions[:8]
    return {
        "contract": REPLAN_CONTRACT,
        "reason": str(ctx.get("reason", "") or "tool_failure"),
        "goal": " ".join(str(ctx.get("goal", "") or "").split())[:200],
        "completedSteps": completed,
        "failedStep": failed_step,
        "remainingSteps": remaining,
    }


def build_cowork_context(
    *,
    platform: str = "",
    capabilities: list[str] | None = None,
    desktop_snapshot: dict[str, Any] | None = None,
    recent_intents: list[dict[str, Any]] | None = None,
    conversation_turns: list[dict[str, Any]] | None = None,
    retrieval_matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """server_brain sohbet/cowork çağrısına metadata olarak eklenen hafif,
    yapılandırılmış bağlam zarfı (elyan.cowork.v1). Sınırlı boyut — her turda
    tam katalog değil, yalnız yetenek ADLARI + masaüstü durumu + son turlar +
    rota geçmişi gider (sunucu yükü minimum)."""
    plat = platform or ("darwin" if sys.platform == "darwin" else sys.platform)
    context: dict[str, Any] = {"contract": COWORK_CONTRACT, "platform": plat}
    if capabilities:
        names = sorted({str(c).strip() for c in capabilities if str(c or "").strip()})
        if names:
            context["capabilities"] = names[:80]
    if isinstance(desktop_snapshot, dict) and desktop_snapshot:
        context["desktop"] = desktop_snapshot
    if recent_intents:
        context["recentIntents"] = [r for r in recent_intents if isinstance(r, dict)][:13]
    if conversation_turns:
        turns: list[dict[str, Any]] = []
        for turn in conversation_turns[-12:]:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role", "") or "").strip().lower() or "user"
            if role == "system":
                continue  # prose system talimatı bağlam değil; dışarıda bırak
            turn_text = " ".join(str(turn.get("text", "") or turn.get("content", "") or "").split())[:600]
            if turn_text:
                turns.append({"role": role, "text": turn_text})
        if turns:
            context["conversationTurns"] = turns
    if retrieval_matches:
        context["retrieval"] = [m for m in retrieval_matches if isinstance(m, dict)][:6]
    return context


def build_planning_request(
    text: str,
    *,
    locale: str = "tr",
    selected_artifacts: list[dict[str, Any]] | None = None,
    retrieval_matches: list[dict[str, Any]] | None = None,
    skills: list[dict[str, Any]] | None = None,
    mcp_tools: list[dict[str, Any]] | None = None,
    recent_intents: list[dict[str, Any]] | None = None,
    desktop_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Düz metin prompt yerine gönderilen planlama isteği zarfı."""
    platform = "darwin" if sys.platform == "darwin" else sys.platform
    context: dict[str, Any] = {}
    if selected_artifacts:
        context["selectedArtifacts"] = [
            {k: item.get(k) for k in ("path", "kind", "name") if item.get(k)}
            for item in selected_artifacts
            if isinstance(item, dict)
        ]
    if retrieval_matches:
        context["retrieval"] = retrieval_matches[:6]
    if skills:
        context["skills"] = [
            {
                "skillId": str(item.get("id", "") or ""),
                "description": str(item.get("description", "") or "")[:160],
                "requiresConfirmation": bool(item.get("requiresConfirmation", False)),
                "expectedInputs": list(item.get("expectedInputs", []) or [])[:4],
            }
            for item in skills[:8]
            if isinstance(item, dict) and str(item.get("id", "") or "")
        ]
    if mcp_tools:
        context["mcpTools"] = mcp_tools[:16]
    if recent_intents:
        context["recentIntents"] = recent_intents[:13]
    if desktop_snapshot:
        context["desktop"] = desktop_snapshot

    return {
        "type": "elyan.plan.request",
        "contract": PLAN_CONTRACT,
        "request": {
            "text": str(text or ""),
            "locale": locale,
            "platform": platform,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        },
        "context": context,
        "toolCatalog": tool_catalog(platform=platform),
        "rules": {
            "role": "planner_only",
            "execution": "desktop_runtime",
            "outputFormat": "single_json_object",
            "unknownRequest": {"intent": "chat", "steps": []},
            "missingInformation": "set clarification.needed=true with one short question; never invent paths, apps, recipients or file contents",
            "sideEffects": "steps using sideEffect tools must set requiresConfirmation=true",
            "sequencing": (
                "decompose multi-action requests into one ordered step per action; "
                "connectives such as 've', 'sonra', 'ardından', 'daha sonra', 'önce', "
                "'and then', 'then' signal separate sequential steps; "
                "list every step id in execution order; when a step needs a prior "
                "step's result, put that prior step id in dependsOn"
            ),
            "dataFlow": (
                "a step's args may reference a prior step's structured output with "
                "{{steps.<stepId>.result.<path>}} (e.g. {{steps.listele.result.items[0].href}}); "
                "give steps short stable ids to enable this"
            ),
            "fanOut": (
                "to repeat one step for EVERY element of a prior step's list output, "
                "set forEach to the list reference (e.g. \"{{steps.listele.result.items}}\") "
                "and use {{item.<field>}} / {{index}} inside that step's args; "
                "browser_session.extract returns result.items"
            ),
            "browserWork": (
                "for multi-step browser tasks on pages whose layout you cannot know, "
                "prefer a single browser_agent.run step with the natural-language goal; "
                "use browser_session.* steps only when the exact selectors/urls are known"
            ),
        },
        "responseSchema": response_schema(),
    }


def planning_prompt(request_envelope: dict[str, Any]) -> str:
    """Model API'lerine gönderilen ham içerik — çıplak JSON, süsleme yok."""
    return json.dumps(request_envelope, ensure_ascii=False)


def intelligence_context(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Öğrenilmiş rota geçmişini (task intelligence) plan zarfına giden
    yapılandırılmış kayıtlara çevirir — düz cümle değil, veri."""
    intelligence = state.get("taskIntelligence", {})
    if not isinstance(intelligence, dict):
        return []
    records: list[dict[str, Any]] = []
    for kind, key, limit in (
        ("confirmed_plan", "confirmedPlanPatterns", 4),
        ("success", "recentSuccessfulRoutes", 4),
        ("misroute", "recentMisroutes", 3),
        ("clarified", "recentClarifications", 2),
    ):
        items = intelligence.get(key, [])
        if not isinstance(items, list):
            continue
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            query = str(item.get("query", "") or "").strip()[:120]
            capability = str(item.get("capability", "") or "").strip()
            if not query and not capability:
                continue
            record: dict[str, Any] = {"kind": kind, "query": query}
            if capability:
                record["capability"] = capability
            intent = str(item.get("intent", "") or "").strip()
            if intent:
                record["intent"] = intent
            records.append(record)

    # Araç güvenilirliği: çalışma zamanında sık başarısız olan capability'ler
    # planlayıcıya "reliability" kaydı olarak bildirilir; planlayıcı güvenilir
    # alternatifleri tercih edebilir.
    quality = intelligence.get("capabilityQuality", {})
    if isinstance(quality, dict):
        reliability: list[dict[str, Any]] = []
        for capability, stats in quality.items():
            if not isinstance(stats, dict):
                continue
            executions = int(stats.get("executions", 0) or 0)
            failures = int(stats.get("executionFailures", 0) or 0)
            if executions < 3 or failures == 0:
                continue
            failure_rate = round(failures / executions, 2)
            if failure_rate < 0.34:
                continue  # yalnız gerçekten güvenilmez olanları bildir
            reliability.append(
                {
                    "kind": "reliability",
                    "capability": str(capability),
                    "executions": executions,
                    "failureRate": failure_rate,
                }
            )
        reliability.sort(key=lambda item: item["failureRate"], reverse=True)
        records.extend(reliability[:5])
    return records


def build_repair_request(
    request_envelope: dict[str, Any],
    invalid_response: Any,
    errors: list[str],
) -> dict[str, Any]:
    """Geçersiz plan yanıtı için tek turluk yapılandırılmış onarım isteği:
    orijinal istek + geçersiz yanıt + doğrulama hataları veri olarak geri
    gönderilir; düzeltilmiş TEK JSON nesnesi beklenir."""
    return {
        "type": "elyan.plan.repair",
        "contract": PLAN_CONTRACT,
        "request": request_envelope.get("request", {}),
        "toolCatalog": request_envelope.get("toolCatalog", []),
        "rules": {
            **(request_envelope.get("rules", {}) if isinstance(request_envelope.get("rules"), dict) else {}),
            "repair": "fix validationErrors and return one corrected JSON object conforming to responseSchema; no prose",
        },
        "responseSchema": request_envelope.get("responseSchema", {}),
        "invalidResponse": invalid_response if isinstance(invalid_response, (dict, list, str)) else str(invalid_response),
        "validationErrors": [str(item) for item in errors[:12]],
    }


# ── Doğrulama ────────────────────────────────────────────────────────────────


def _coerce_value(value: Any, expected: str) -> tuple[Any, bool]:
    if expected == "string":
        return ("" if value is None else str(value)), True
    if expected == "number":
        try:
            number = float(value)
            return (int(number) if number.is_integer() else number), True
        except (TypeError, ValueError):
            return value, False
    if expected == "boolean":
        if isinstance(value, bool):
            return value, True
        text = str(value or "").strip().lower()
        if text in {"true", "1", "yes", "evet"}:
            return True, True
        if text in {"false", "0", "no", "hayir", "hayır"}:
            return False, True
        return value, False
    if expected == "object":
        return (dict(value) if isinstance(value, dict) else value), isinstance(value, dict)
    if expected == "array":
        return (list(value) if isinstance(value, (list, tuple)) else value), isinstance(value, (list, tuple))
    return value, True


def _validate_step_args(capability: str, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    decl = _declaration_index().get(capability)
    if decl is None:
        # Bildirimi olmayan capability (ör. dinamik MCP/skill) — argümanları
        # olduğu gibi bırak; özel doğrulama çağıran tarafta.
        return dict(args), errors
    params = decl.get("parameters", {}) if isinstance(decl.get("parameters"), dict) else {}
    props = params.get("properties", {}) if isinstance(params.get("properties"), dict) else {}
    required = [str(item) for item in params.get("required", []) or []]

    cleaned: dict[str, Any] = {}
    for key, value in args.items():
        key_text = str(key)
        if key_text.startswith("_"):
            cleaned[key_text] = value  # runtime iç bayrakları geçer
            continue
        spec = props.get(key_text)
        if not isinstance(spec, dict):
            continue  # bilinmeyen argüman: buda
        expected = _TYPE_MAP.get(str(spec.get("type", "STRING")).upper(), "string")
        coerced, ok = _coerce_value(value, expected)
        if not ok:
            errors.append(f"{capability}.{key_text}: {expected} bekleniyordu")
            continue
        cleaned[key_text] = coerced

    for arg_name, allowed in ENUM_CONSTRAINTS.get(capability, {}).items():
        if arg_name in cleaned:
            normalized = str(cleaned[arg_name] or "").strip().lower()
            match = next((item for item in allowed if item.lower() == normalized), None)
            if match is None:
                errors.append(f"{capability}.{arg_name}: {sorted(allowed)} dışında değer")
            else:
                cleaned[arg_name] = match

    for name in required:
        value = cleaned.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"{capability}.{name}: zorunlu argüman eksik")

    return cleaned, errors


def validate_plan(payload: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """Sunucudan gelen plan JSON'unu sözleşmeye göre doğrular ve normalize eder.

    Dönen plan: {intent, goal, confidence, privacyClass, requiresConfirmation,
    clarification{needed,question}, steps[{id,capability,args,description}]}.
    """
    errors: list[str] = []
    if not isinstance(payload, dict):
        return None, ["plan bir JSON nesnesi değil"]

    contract = str(payload.get("contract", "") or "")
    if contract and contract != PLAN_CONTRACT:
        errors.append(f"bilinmeyen sözleşme: {contract}")

    intent = str(payload.get("intent", "") or "").strip() or "chat"
    goal = str(payload.get("goal", "") or "").strip()
    try:
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.0) or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
        errors.append("confidence sayı değil")

    privacy = str(payload.get("privacyClass", "") or "").strip()
    if privacy not in {"local_private", "public_text"}:
        privacy = ""

    clarification_raw = payload.get("clarification")
    clarification_raw = clarification_raw if isinstance(clarification_raw, dict) else {}
    clarification = {
        "needed": bool(clarification_raw.get("needed", False)),
        "question": str(clarification_raw.get("question", "") or "").strip(),
    }

    raw_steps = payload.get("steps")
    raw_steps = raw_steps if isinstance(raw_steps, list) else []
    known = capability_names()
    steps: list[dict[str, Any]] = []
    requires_confirmation = bool(payload.get("requiresConfirmation", False))
    for index, raw in enumerate(raw_steps[:8], start=1):
        if not isinstance(raw, dict):
            errors.append(f"steps[{index}]: nesne değil")
            continue
        capability = str(raw.get("capability", "") or "").strip()
        if not capability:
            errors.append(f"steps[{index}]: capability boş")
            continue
        if capability not in known:
            errors.append(f"steps[{index}]: bilinmeyen capability {capability!r}")
            continue
        raw_args = raw.get("args", {})
        raw_args = raw_args if isinstance(raw_args, dict) else {}
        args, arg_errors = _validate_step_args(capability, raw_args)
        errors.extend(arg_errors)
        if any("zorunlu argüman eksik" in item for item in arg_errors):
            # Eksik zorunlu argümanla adım yürütülemez; adımı düşür — plan
            # tamamen boş kalırsa aşağıda reddedilir, üst katman netleştirme
            # sorusuna döner.
            continue
        metadata = capability_metadata(capability)
        if bool(metadata.get("sideEffect", False)) or str(metadata.get("permissionClass", "") or "") == "approval_required":
            requires_confirmation = True
        raw_depends = raw.get("dependsOn")
        depends_on = (
            [str(item).strip() for item in raw_depends if str(item or "").strip()]
            if isinstance(raw_depends, list)
            else []
        )
        step_payload: dict[str, Any] = {
            "id": str(raw.get("id", "") or f"step_{index}"),
            "capability": capability,
            "args": args,
            "description": str(raw.get("description", "") or "").strip() or capability,
        }
        if depends_on:
            step_payload["dependsOn"] = depends_on
        steps.append(step_payload)

    plan = {
        "intent": intent,
        "goal": goal,
        "confidence": confidence,
        "privacyClass": privacy,
        "requiresConfirmation": requires_confirmation,
        "clarification": clarification,
        "steps": steps,
    }
    blocking = [e for e in errors if "zorunlu argüman eksik" in e or "bilinmeyen capability" in e]
    if blocking and not steps:
        return None, errors
    return plan, errors


def _order_steps_by_dependencies(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adımları `dependsOn`'a göre kararlı topolojik sıraya dizer.

    LLM adımları gevşek sırayla verse bile bir adım, bağımlı olduğu adımlardan
    SONRA yürütülür. Bağımsız adımlar için orijinal (LLM) sırası korunur. Döngü
    ya da çözülemeyen referansta orijinal sıraya düşer — asla plan bozulmaz.
    Bilinmeyen id'ye yapılan dependsOn referansları kısıt saymaz (yok sayılır).
    """
    if len(steps) <= 1:
        return list(steps)
    id_to_index: dict[str, int] = {}
    for idx, step in enumerate(steps):
        sid = str(step.get("id", "") or "").strip()
        if sid and sid not in id_to_index:
            id_to_index[sid] = idx
    deps: dict[int, set[int]] = {i: set() for i in range(len(steps))}
    for i, step in enumerate(steps):
        for dep in step.get("dependsOn", []) or []:
            j = id_to_index.get(str(dep).strip())
            if j is not None and j != i:
                deps[i].add(j)
    indeg = {i: len(deps[i]) for i in range(len(steps))}
    resolved: set[int] = set()
    ordered: list[int] = []
    available = [i for i in range(len(steps)) if indeg[i] == 0]
    while available:
        available.sort()  # eşitlikte en küçük orijinal indeks → kararlı
        node = available.pop(0)
        ordered.append(node)
        resolved.add(node)
        for k in range(len(steps)):
            if k in resolved or node not in deps[k]:
                continue
            indeg[k] -= 1
            if indeg[k] == 0 and k not in available:
                available.append(k)
    if len(ordered) != len(steps):
        return list(steps)  # döngü/çözülemedi → orijinal sıra
    return [steps[i] for i in ordered]


def plan_to_semantic_payload(plan: dict[str, Any], *, fallback_privacy: str = "public_text") -> dict[str, Any]:
    """Doğrulanmış planı bridge'in semantik rota sonucu şekline çevirir."""
    steps = plan.get("steps", [])
    steps = steps if isinstance(steps, list) else []
    steps = _order_steps_by_dependencies([s for s in steps if isinstance(s, dict)])
    clarification = plan.get("clarification", {}) if isinstance(plan.get("clarification"), dict) else {}
    if clarification.get("needed") and clarification.get("question"):
        return {
            "intent": str(plan.get("intent", "") or "clarification"),
            "capability": "",
            "args": {},
            "confidence": float(plan.get("confidence", 0.0) or 0.0),
            "requiresConfirmation": False,
            "isMultiStep": False,
            "privacyClass": str(plan.get("privacyClass", "") or fallback_privacy),
            "planPreview": None,
            "clarificationQuestion": str(clarification.get("question", "") or ""),
        }
    if not steps:
        return {
            "intent": str(plan.get("intent", "") or "chat"),
            "capability": "",
            "args": {},
            "confidence": float(plan.get("confidence", 0.0) or 0.0),
            "requiresConfirmation": False,
            "isMultiStep": False,
            "privacyClass": str(plan.get("privacyClass", "") or fallback_privacy),
            "planPreview": None,
        }
    first = steps[0]
    is_multi = len(steps) > 1
    payload: dict[str, Any] = {
        "intent": str(plan.get("intent", "") or first.get("capability", "") or "task"),
        "capability": str(first.get("capability", "") or ""),
        "args": dict(first.get("args", {}) or {}),
        "confidence": float(plan.get("confidence", 0.0) or 0.0),
        "requiresConfirmation": bool(plan.get("requiresConfirmation", False)) or is_multi,
        "isMultiStep": is_multi,
        "privacyClass": str(plan.get("privacyClass", "") or fallback_privacy),
    }
    if is_multi or plan.get("goal"):
        summary = str(plan.get("goal", "") or "") or " → ".join(
            str(step.get("capability", "")) for step in steps
        )
        payload["planPreview"] = {
            "summary": summary,
            "steps": [dict(step) for step in steps],
            "privacyClass": payload["privacyClass"],
            "agentPlan": build_agent_plan([dict(step) for step in steps], summary=summary),
        }
    else:
        payload["planPreview"] = None
    return payload
