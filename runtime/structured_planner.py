"""Yapılandırılmış planlama sözleşmesi — elyan.plan.v2

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
import re
import sys
from functools import lru_cache
from typing import Any

from runtime.agent_planning import build_agent_plan
from runtime.capability_registry import TOOL_DECLARATIONS, capability_metadata, capability_names
from runtime.capability_shortlist import MIN_SHORTLIST, shortlist_capabilities

PLAN_CONTRACT = "elyan.plan.v2"

# Backend planlama endpoint'inin kabul ettiği azami istek gövdesi. Normal ve
# repair payload'ları bu sınırın ALTINDA kalmak zorundadır; planning_prompt()
# bunu deterministik budamayla garanti eder (bkz. _fit_envelope).
MAX_PLANNER_PAYLOAD_CHARS = 48_000
GOAL_CONTRACT = "elyan.goal_contract.v1"
# Cowork bağlam zarfı sözleşmesi: server_brain'e sohbet/cowork turunda giden
# yapılandırılmış (düz metin değil) bağlam. Sorgu labeled alanda, bağlam metadata
# JSON'unda — brain sunucuda yeniden türetmeden anlar/planlar (daha az yük).
COWORK_CONTRACT = "elyan.cowork.v1"

# Bir planın taşıyabileceği azami adım sayısı. Eskiden 8'e sabitliydi ve
# çok-adımlı ("karmaşık") görevler sessizce 8 adıma kırpılıp yarım
# yürütülüyordu. Zincirleme (dependsOn) + fan-out ile daha derin planlara
# izin vermek için yükseltildi; executor'da ayrıca sabit tavan yok.
MAX_PLAN_STEPS = 16

# Argüman enum kısıtları — daha önce bridge._semantic_route içinde dağınık
# if bloklarıydı; artık sözleşmenin parçası.
ENUM_CONSTRAINTS: dict[str, dict[str, set[str]]] = {
    "browser_control": {"action": {"search", "open_url", "play_youtube"}},
    "document_read": {"mode": {"read", "summary", "bullets"}},
    "ocr_read": {"mode": {"read", "summary", "bullets"}},
    "image_read": {"mode": {"summary", "metadata", "palette"}},
    "data_analyze": {"mode": {"summary", "profile", "preview"}},
    "text_analyze": {"mode": {"professional", "legal", "medical", "accounting", "technical", "student"}},
    "chart_generate": {"chartType": {"bar", "line", "scatter", "histogram"}},
    "math_solve": {"mode": {"solve", "simplify", "factor", "expand", "evaluate"}},
    "latex_parse": {"mode": {"parse", "normalize"}},
}

_TYPE_MAP = {"STRING": "string", "NUMBER": "number", "BOOLEAN": "boolean", "OBJECT": "object", "ARRAY": "array"}

_COMMON_RESULT_PROPERTIES: dict[str, dict[str, Any]] = {
    "kind": {"type": "string"},
}

_RESULT_PROPERTIES: dict[str, dict[str, dict[str, Any]]] = {
    "web_research": {
        "summary": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "object"}},
    },
    "retrieve_context": {
        "matches": {"type": "array", "items": {"type": "object"}},
        "summary": {"type": "string"},
    },
    "document_read": {
        "text": {"type": "string"},
        "summary": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "string"}},
    },
    "ocr_read": {
        "text": {"type": "string"},
        "summary": {"type": "string"},
    },
    "data_analyze": {
        "rowCount": {"type": "number"},
        "columns": {"type": "array", "items": {"type": "string"}},
        "previewRows": {"type": "array", "items": {"type": "object"}},
        "profile": {"type": "object"},
        "summary": {"type": "string"},
    },
    "text_analyze": {
        "summary": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "recommendations": {"type": "array", "items": {"type": "string"}},
    },
    "browser_session.extract": {
        "items": {"type": "array", "items": {"type": "object"}},
        "text": {"type": "string"},
    },
    "spreadsheet_write": {
        "outputPath": {"type": "string"},
        "columns": {"type": "array", "items": {"type": "string"}},
        "rows": {"type": "array", "items": {"type": "array"}},
        "rowCount": {"type": "number"},
    },
    "document_write": {
        "outputPath": {"type": "string"},
        "summary": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "string"}},
    },
    "presentation_write": {
        "outputPath": {"type": "string"},
        "slideCount": {"type": "number"},
        "summary": {"type": "string"},
    },
    "canvas_write": {"outputPath": {"type": "string"}},
    "chart_generate": {"outputPath": {"type": "string"}},
    "image_generate": {"outputPath": {"type": "string"}},
    "image_edit": {"outputPath": {"type": "string"}, "sourcePaths": {"type": "array", "items": {"type": "string"}}},
    "file_search": {"items": {"type": "array", "items": {"type": "object"}}},
}


def _declaration_index() -> dict[str, dict[str, Any]]:
    return {str(decl.get("name", "")): decl for decl in TOOL_DECLARATIONS if isinstance(decl, dict)}


def tool_catalog(*, platform: str = "", allowed: list[str] | set[str] | tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Sunucu beynine gönderilen araç kataloğu: her araç JSON Schema
    parametreleri + yürütme meta verisiyle (yan etki, onay, platform).

    Katalog statik TOOL_DECLARATIONS'tan üretilir → platform başına önbelleğe
    alınır (her planlama çağrısında yeniden kurulmaz; salt-okunur tüketilir).
    `allowed` verilirse yalnız o adlar döner (deterministik shortlist)."""
    platform = platform or ("darwin" if sys.platform == "darwin" else sys.platform)
    catalog = _tool_catalog_cached(platform)
    if allowed is None:
        return catalog
    allowed_names = {str(item or "").strip() for item in allowed if str(item or "").strip()}
    return [entry for entry in catalog if entry.get("name") in allowed_names]


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
            "resultSchema": {
                "type": "object",
                "properties": {
                    **_COMMON_RESULT_PROPERTIES,
                    **_RESULT_PROPERTIES.get(name, {}),
                },
            },
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
        "required": ["contract", "intent", "confidence", "goalContract", "steps"],
        "properties": {
            "contract": {"const": PLAN_CONTRACT},
            "intent": {"type": "string"},
            "goal": {"type": "string"},
            "goalContract": {
                "type": "object",
                "required": [
                    "contract",
                    "objective",
                    "deliverables",
                    "constraints",
                    "acceptanceCriteria",
                    "prohibitedActions",
                    "privacy",
                    "risk",
                    "priority",
                    "missingInformation",
                ],
                "properties": {
                    "contract": {"const": GOAL_CONTRACT},
                    "objective": {"type": "string"},
                    "deliverables": {"type": "array", "maxItems": 12, "items": {"type": "string"}},
                    "constraints": {"type": "array", "maxItems": 12, "items": {"type": "string"}},
                    "acceptanceCriteria": {"type": "array", "maxItems": 12, "items": {"type": "string"}},
                    "prohibitedActions": {"type": "array", "maxItems": 12, "items": {"type": "string"}},
                    "privacy": {"enum": ["local_private", "public_text"]},
                    "risk": {"enum": ["low", "medium", "high", "critical"]},
                    "priority": {"enum": ["low", "normal", "high", "urgent"]},
                    "missingInformation": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {
                            "type": "object",
                            "required": ["id", "question", "blocking"],
                            "properties": {
                                "id": {"type": "string"},
                                "question": {"type": "string"},
                                "blocking": {"type": "boolean"},
                            },
                        },
                    },
                },
            },
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
                "maxItems": MAX_PLAN_STEPS,
                "items": {
                    "type": "object",
                    "required": ["capability"],
                    "properties": {
                        "id": {"type": "string"},
                        "capability": {"type": "string"},
                        "args": {"type": "object"},
                        "description": {"type": "string"},
                        "dependsOn": {"type": "array", "items": {"type": "string"}},
                        "priority": {"enum": ["low", "normal", "high", "urgent"]},
                        "deadlineAt": {"type": "string"},
                        "queuedAt": {"type": "string"},
                        "resourceScope": {"type": "array", "items": {"type": "string"}},
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


def _bounded_json(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return "[bounded]"
    if isinstance(value, dict):
        return {
            str(key)[:80]: _bounded_json(item, depth=depth + 1)
            for key, item in list(value.items())[:16]
            if not str(key).startswith("_")
        }
    if isinstance(value, list):
        return [_bounded_json(item, depth=depth + 1) for item in value[:20]]
    if isinstance(value, tuple):
        return [_bounded_json(item, depth=depth + 1) for item in value[:20]]
    if isinstance(value, str):
        return value[:600]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:240]


def build_replan_observation(context: dict[str, Any]) -> dict[str, Any]:
    """Yürütme sırasında bir adım başarısız/doğrulanamaz olunca üretilen
    yapılandırılmış gözlem (elyan.replan.v1) — düz metin değil, labeled JSON.
    Deterministik kurtarma ve yapılandırılmış model yeniden planlaması aynı
    gözlemi kullanır (plan -> adım -> gözlem -> uyarla döngüsü)."""
    ctx = context if isinstance(context, dict) else {}
    completed: list[dict[str, Any]] = []
    step_outputs = ctx.get("stepOutputs")
    if isinstance(step_outputs, dict):
        for step_id, payload in list(step_outputs.items())[:12]:
            if not isinstance(payload, dict):
                continue
            completed.append({
                "id": str(step_id)[:80],
                "outputPreview": " ".join(str(payload.get("output", "") or "").split())[:240],
                "result": _bounded_json(payload.get("result", {})),
                "artifacts": _bounded_json(payload.get("artifacts", [])),
                "verification": _bounded_json(payload.get("verification", {})),
            })
    else:
        for output in (ctx.get("completedOutputs") or [])[:8]:
            preview = " ".join(str(output or "").split())[:200]
            if preview:
                completed.append({"outputPreview": preview})
    failed_args = ctx.get("failedArgs")
    failed_args = failed_args if isinstance(failed_args, dict) else {}
    remaining: list[dict[str, Any]] = []
    for step in (ctx.get("remainingSteps") or []):
        if isinstance(step, dict) and str(step.get("capability", "") or "").strip():
            remaining_step = {
                "id": str(step.get("id", "") or "")[:80],
                "capability": str(step.get("capability", "") or "").strip(),
                "description": " ".join(str(step.get("description", "") or "").split())[:160],
                "args": _bounded_json(step.get("args", {})),
                "dependsOn": _bounded_json(step.get("dependsOn", [])),
            }
            if step.get("forEach") is not None:
                remaining_step["forEach"] = str(step.get("forEach", ""))[:240]
            remaining.append(remaining_step)
    failed_step: dict[str, Any] = {
        "id": str(ctx.get("failedStepId", "") or "")[:80],
        "capability": str(ctx.get("failedCapability", "") or ""),
        "errorCode": str(ctx.get("errorCode", "") or ""),
        "message": " ".join(str(ctx.get("message", "") or "").split())[:300],
        "args": _bounded_json({k: v for k, v in failed_args.items() if not str(k).startswith("_")}),
        "verification": _bounded_json(ctx.get("verification", {})),
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
        "goalContext": _bounded_json(ctx.get("goalContext", {})),
        "completedSteps": completed,
        "failedStep": failed_step,
        "remainingSteps": remaining,
        "missingEvidence": _bounded_json(ctx.get("missingEvidence", [])),
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
    conversation_turns: list[dict[str, Any]] | None = None,
    selected_artifacts: list[dict[str, Any]] | None = None,
    retrieval_matches: list[dict[str, Any]] | None = None,
    skills: list[dict[str, Any]] | None = None,
    mcp_tools: list[dict[str, Any]] | None = None,
    recent_intents: list[dict[str, Any]] | None = None,
    desktop_snapshot: dict[str, Any] | None = None,
    planner_hint: dict[str, Any] | None = None,
    goal_context: dict[str, Any] | None = None,
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
    if conversation_turns:
        turns: list[dict[str, str]] = []
        for turn in conversation_turns[-12:]:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role", "") or "").strip().lower()
            if role not in {"user", "assistant"}:
                continue
            turn_text = " ".join(
                str(turn.get("text", "") or turn.get("content", "") or "").split()
            )[:600]
            if turn_text:
                turns.append({"role": role, "text": turn_text})
        if turns:
            context["conversationTurns"] = turns
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
    if planner_hint:
        context["deterministicPlanHint"] = planner_hint
    if goal_context:
        context["executionGoal"] = goal_context

    # P0: 77 aracın tamamı yerine deterministik shortlist (8–15 araç şeması).
    # İş emri/hint'in açıkça istediği yetenekler her zaman bütçeye dahildir.
    known_names = {str(entry.get("name", "") or "") for entry in tool_catalog(platform=platform)}
    hinted = _referenced_capabilities({"hint": planner_hint, "goal": goal_context})
    shortlist = shortlist_capabilities(
        str(text or ""),
        known_capabilities=known_names,
        extra_capabilities=sorted(hinted & known_names),
    )

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
        "toolCatalog": tool_catalog(platform=platform, allowed=shortlist),
        "rules": {
            "role": "planner_only",
            "execution": "desktop_runtime",
            "outputFormat": "single_json_object",
            "unknownRequest": {
                "contract": PLAN_CONTRACT,
                "intent": "chat",
                "confidence": 1.0,
                "goalContract": {
                    "contract": GOAL_CONTRACT,
                    "objective": "answer the user",
                    "deliverables": [],
                    "constraints": [],
                    "acceptanceCriteria": [],
                    "prohibitedActions": [],
                    "privacy": "public_text",
                    "risk": "low",
                    "priority": "normal",
                    "missingInformation": [],
                },
                "steps": [],
            },
            "goalContract": (
                "always describe objective, deliverables, constraints, acceptanceCriteria, "
                "prohibitedActions, privacy, risk, priority and missingInformation; encode "
                "a forbidden tool as capability:<capability_name> in prohibitedActions"
            ),
            "missingInformation": (
                "record every unknown in goalContract.missingInformation; if execution is "
                "blocked set clarification.needed=true and ask only the first blocking "
                "question; never invent paths, apps, recipients or file contents"
            ),
            "sideEffects": "steps using sideEffect tools must set requiresConfirmation=true",
            "sequencing": (
                "decompose multi-action requests into one ordered step per action; "
                "connectives such as 've', 'sonra', 'ardından', 'daha sonra', 'önce', "
                "'and then', 'then' signal separate sequential steps; "
                "list every step id in execution order; when a step needs a prior "
                "step's result, put that prior step id in dependsOn"
            ),
            "scheduling": (
                "set step priority only when it differs from goalContract.priority; "
                "preserve explicit deadlineAt and resourceScope; never mark side-effect "
                "capabilities as read-only or parallel-safe"
            ),
            "dataFlow": (
                "a step's args may reference a prior step's structured output with "
                "{{steps.<stepId>.result.<path>}} (e.g. {{steps.listele.result.items[0].href}}); "
                "give steps short stable ids to enable this; use each tool's resultSchema and "
                "bind structured writer inputs such as rows, columns, sections, blocks or slides "
                "directly instead of flattening them into prose"
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


def _referenced_capabilities(value: Any, *, depth: int = 0) -> set[str]:
    """Hint/goal ağacındaki `capability`/`requiredCapabilities` alanlarından
    yetenek adlarını çıkarır (shortlist'e zorunlu dahil edilirler)."""
    names: set[str] = set()
    if depth >= 6:
        return names
    if isinstance(value, dict):
        raw = value.get("capability")
        if isinstance(raw, str) and raw.strip():
            names.add(raw.strip())
        raw_list = value.get("requiredCapabilities")
        if isinstance(raw_list, list):
            names.update(str(item).strip() for item in raw_list if str(item or "").strip())
        raw_scope = value.get("capabilityScope")
        if isinstance(raw_scope, list):
            names.update(str(item).strip() for item in raw_scope if str(item or "").strip())
        for item in value.values():
            names |= _referenced_capabilities(item, depth=depth + 1)
    elif isinstance(value, list):
        for item in value[:32]:
            names |= _referenced_capabilities(item, depth=depth + 1)
    return names


def _compact_catalog_entry(entry: dict[str, Any], *, drop_examples: bool, drop_usage: bool, description_limit: int) -> dict[str, Any]:
    compact = dict(entry)
    if drop_examples:
        compact.pop("examples", None)
    if drop_usage:
        compact.pop("usage", None)
    description = str(compact.get("description", "") or "")
    if len(description) > description_limit:
        compact["description"] = description[:description_limit]
    return compact


def _fit_envelope(request_envelope: dict[str, Any], *, budget: int = MAX_PLANNER_PAYLOAD_CHARS) -> dict[str, Any]:
    """Zarfı 48k karakter bütçesine DETERMİNİSTİK budamayla sığdırır.

    Sıra: bağlam kısaltma → araç örnekleri/rehberi → geçersiz yanıt kırpma →
    katalog açıklamalarını kısaltma → bağlamı tamamen düşürme. JSON yapısı hep
    geçerli kalır; asla ham metin kesilmez."""

    def _encoded_length(envelope: dict[str, Any]) -> int:
        return len(json.dumps(envelope, ensure_ascii=False))

    envelope = dict(request_envelope)
    if _encoded_length(envelope) <= budget:
        return envelope

    context = envelope.get("context")
    if isinstance(context, dict):
        trimmed_context = dict(context)
        turns = trimmed_context.get("conversationTurns")
        if isinstance(turns, list) and len(turns) > 6:
            trimmed_context["conversationTurns"] = turns[-6:]
        retrieval = trimmed_context.get("retrieval")
        if isinstance(retrieval, list) and len(retrieval) > 3:
            trimmed_context["retrieval"] = retrieval[:3]
        trimmed_context = _bounded_json(trimmed_context)
        envelope["context"] = trimmed_context
        if _encoded_length(envelope) <= budget:
            return envelope

    catalog = envelope.get("toolCatalog")
    if isinstance(catalog, list):
        for drop_examples, drop_usage, description_limit in (
            (True, False, 400),
            (True, True, 200),
            (True, True, 96),
        ):
            envelope["toolCatalog"] = [
                _compact_catalog_entry(entry, drop_examples=drop_examples, drop_usage=drop_usage, description_limit=description_limit)
                for entry in catalog
                if isinstance(entry, dict)
            ]
            if _encoded_length(envelope) <= budget:
                return envelope

    invalid = envelope.get("invalidResponse")
    if invalid is not None:
        envelope["invalidResponse"] = _bounded_json(
            invalid if isinstance(invalid, (dict, list)) else str(invalid)[:1200],
            depth=2,
        )
        if _encoded_length(envelope) <= budget:
            return envelope

    envelope["context"] = {}
    if _encoded_length(envelope) <= budget:
        return envelope

    # Son çare: katalog boyutunu deterministik olarak MIN_SHORTLIST'e indir.
    catalog = envelope.get("toolCatalog")
    if isinstance(catalog, list) and len(catalog) > MIN_SHORTLIST:
        envelope["toolCatalog"] = catalog[:MIN_SHORTLIST]
    return envelope


def planning_prompt(request_envelope: dict[str, Any]) -> str:
    """Model API'lerine gönderilen ham içerik — çıplak JSON, süsleme yok.

    Payload backend'in 48.000 karakter sınırını asla aşmaz (deterministik
    budama; bkz. _fit_envelope)."""
    return json.dumps(_fit_envelope(request_envelope), ensure_ascii=False)


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
        "context": _bounded_json(request_envelope.get("context", {})),
        "toolCatalog": request_envelope.get("toolCatalog", []),
        "rules": {
            **(request_envelope.get("rules", {}) if isinstance(request_envelope.get("rules"), dict) else {}),
            "repair": "fix validationErrors and return one corrected JSON object conforming to responseSchema; no prose",
        },
        "responseSchema": request_envelope.get("responseSchema", {}),
        "invalidResponse": _bounded_json(
            invalid_response
            if isinstance(invalid_response, (dict, list, str))
            else str(invalid_response)
        ),
        "validationErrors": [str(item) for item in errors[:12]],
    }


def build_replan_request(
    planning_request: dict[str, Any],
    observation: dict[str, Any],
) -> dict[str, Any]:
    """Build a bounded remaining-plan request using the normal plan schema."""
    context = planning_request.get("context")
    context = dict(context) if isinstance(context, dict) else {}
    context["executionObservation"] = observation
    return {
        "type": "elyan.plan.replan",
        "contract": PLAN_CONTRACT,
        "request": planning_request.get("request", {}),
        "context": context,
        "toolCatalog": planning_request.get("toolCatalog", []),
        "rules": {
            **(planning_request.get("rules", {}) if isinstance(planning_request.get("rules"), dict) else {}),
            "replan": (
                "return only replacement steps that are still needed; never repeat completed "
                "side effects, never widen capability scope, preserve the execution goal and "
                "use completed structured results as data"
            ),
        },
        "responseSchema": planning_request.get("responseSchema", response_schema()),
    }


# ── Doğrulama ────────────────────────────────────────────────────────────────


def _coerce_value(value: Any, expected: str) -> tuple[Any, bool]:
    if isinstance(value, str) and re.fullmatch(r"\s*\{\{.+?\}\}\s*", value):
        # Deferred values are type-checked after their producing step runs. Keep
        # the template intact so arrays/numbers/objects are not rejected early.
        return value, True
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
    public_args = {
        str(key): value
        for key, value in args.items()
        if not str(key).startswith("_")
    }
    decl = _declaration_index().get(capability)
    if decl is None:
        # Bildirimi olmayan capability (ör. dinamik MCP/skill) — argümanları
        # koru; runtime'a ait alt çizgili güven bayraklarını modelden alma.
        return public_args, errors
    params = decl.get("parameters", {}) if isinstance(decl.get("parameters"), dict) else {}
    props = params.get("properties", {}) if isinstance(params.get("properties"), dict) else {}
    required = [str(item) for item in params.get("required", []) or []]

    cleaned: dict[str, Any] = {}
    for key, value in public_args.items():
        key_text = str(key)
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
            if isinstance(cleaned[arg_name], str) and "{{" in cleaned[arg_name]:
                continue
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


def _text_list(value: Any, *, limit: int = 12, item_limit: int = 240) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value[:limit]:
        text = " ".join(str(item or "").split())[:item_limit]
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _normalize_missing_information(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(value[:8], start=1):
        raw = item if isinstance(item, dict) else {"question": item}
        question = " ".join(str(raw.get("question", "") or "").split())[:240]
        if not question:
            continue
        normalized.append({
            "id": " ".join(str(raw.get("id", "") or f"missing_{index}").split())[:80],
            "question": question,
            "blocking": bool(raw.get("blocking", True)),
        })
    return normalized


def _normalize_goal_contract(
    value: Any,
    *,
    intent: str,
    goal: str,
    privacy: str,
    requires_confirmation: bool,
    steps: list[dict[str, Any]],
    legacy_clarification: dict[str, Any],
) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    objective = " ".join(str(raw.get("objective", "") or goal or intent).split())[:1000]
    deliverables = _text_list(raw.get("deliverables"))
    if not deliverables and steps:
        deliverables = _text_list([step.get("description", "") for step in steps])

    missing_information = _normalize_missing_information(raw.get("missingInformation"))
    legacy_question = " ".join(str(legacy_clarification.get("question", "") or "").split())[:240]
    if legacy_clarification.get("needed") and legacy_question:
        if not any(item["question"] == legacy_question for item in missing_information):
            missing_information.insert(0, {
                "id": "clarification_1",
                "question": legacy_question,
                "blocking": True,
            })
            missing_information = missing_information[:8]

    normalized_privacy = str(raw.get("privacy", "") or privacy).strip()
    if normalized_privacy not in {"local_private", "public_text"}:
        normalized_privacy = "public_text"
    risk = str(raw.get("risk", "") or "").strip().lower()
    if risk not in {"low", "medium", "high", "critical"}:
        risk = "high" if requires_confirmation else "low"
    priority = str(raw.get("priority", "") or "").strip().lower()
    if priority not in {"low", "normal", "high", "urgent"}:
        priority = "normal"

    return {
        "contract": GOAL_CONTRACT,
        "objective": objective,
        "deliverables": deliverables,
        "constraints": _text_list(raw.get("constraints")),
        "acceptanceCriteria": _text_list(raw.get("acceptanceCriteria")),
        "prohibitedActions": _text_list(raw.get("prohibitedActions")),
        "privacy": normalized_privacy,
        "risk": risk,
        "priority": priority,
        "missingInformation": missing_information,
    }


def _validate_goal_contract_input(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["goalContract nesnesi eksik"]

    errors: list[str] = []
    if str(value.get("contract", "") or "").strip() != GOAL_CONTRACT:
        errors.append("goalContract.contract geçersiz")
    if not isinstance(value.get("objective"), str) or not str(value.get("objective", "") or "").strip():
        errors.append("goalContract.objective eksik")

    for field in ("deliverables", "constraints", "acceptanceCriteria", "prohibitedActions"):
        items = value.get(field)
        if not isinstance(items, list):
            errors.append(f"goalContract.{field} bir dizi değil")
        elif len(items) > 12:
            errors.append(f"goalContract.{field} 12 öğe sınırını aşıyor")
        elif any(not isinstance(item, str) or not item.strip() for item in items):
            errors.append(f"goalContract.{field} yalnız dolu metinler içermeli")

    if str(value.get("privacy", "") or "").strip() not in {"local_private", "public_text"}:
        errors.append("goalContract.privacy geçersiz")
    if str(value.get("risk", "") or "").strip().lower() not in {"low", "medium", "high", "critical"}:
        errors.append("goalContract.risk geçersiz")
    if str(value.get("priority", "") or "").strip().lower() not in {"low", "normal", "high", "urgent"}:
        errors.append("goalContract.priority geçersiz")

    missing_information = value.get("missingInformation")
    if not isinstance(missing_information, list):
        errors.append("goalContract.missingInformation bir dizi değil")
    else:
        if len(missing_information) > 8:
            errors.append("goalContract.missingInformation 8 öğe sınırını aşıyor")
        for index, item in enumerate(missing_information[:8], start=1):
            prefix = f"goalContract.missingInformation[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} nesne değil")
                continue
            if not isinstance(item.get("id"), str) or not str(item.get("id", "") or "").strip():
                errors.append(f"{prefix}.id eksik")
            if not isinstance(item.get("question"), str) or not str(item.get("question", "") or "").strip():
                errors.append(f"{prefix}.question eksik")
            if not isinstance(item.get("blocking"), bool):
                errors.append(f"{prefix}.blocking boolean değil")
    return errors


def _lint_plan_steps(steps: list[dict[str, Any]]) -> list[str]:
    """Capability doğrulamasından geçmiş adımların DAG bütünlüğünü denetler."""
    errors: list[str] = []
    step_ids = [str(step.get("id", "") or "").strip() for step in steps]
    known_ids = set(step_ids)
    seen: set[str] = set()
    for step_id in step_ids:
        if not step_id or step_id in seen:
            errors.append(f"plan linter: tekrarlı veya boş step id {step_id!r}")
        seen.add(step_id)

    dependencies: dict[str, set[str]] = {step_id: set() for step_id in step_ids if step_id}
    reference_pattern = re.compile(r"\{\{\s*steps\.([A-Za-z0-9_\-]+)")
    for step in steps:
        step_id = str(step.get("id", "") or "").strip()
        for dependency in step.get("dependsOn", []) or []:
            dependency_id = str(dependency or "").strip()
            if dependency_id not in known_ids:
                errors.append(
                    f"plan linter: {step_id!r} bilinmeyen bağımlılık {dependency_id!r} içeriyor"
                )
                continue
            dependencies.setdefault(step_id, set()).add(dependency_id)
        referenced = set(reference_pattern.findall(json.dumps({
            "args": step.get("args", {}),
            "forEach": step.get("forEach"),
        }, ensure_ascii=False)))
        for dependency_id in sorted(referenced):
            if dependency_id not in known_ids:
                errors.append(
                    f"plan linter: {step_id!r} bilinmeyen veri referansı {dependency_id!r} içeriyor"
                )
                continue
            if dependency_id != step_id:
                dependencies.setdefault(step_id, set()).add(dependency_id)

    if errors:
        return errors

    remaining = {step_id: set(items) for step_id, items in dependencies.items()}
    resolved: set[str] = set()
    while remaining:
        ready = sorted(step_id for step_id, deps in remaining.items() if deps <= resolved)
        if not ready:
            cycle_nodes = ", ".join(sorted(remaining))
            errors.append(f"plan linter: DAG döngüsü bulundu ({cycle_nodes})")
            break
        for step_id in ready:
            resolved.add(step_id)
            remaining.pop(step_id, None)
    return errors


def _normalize_data_dependencies(steps: list[dict[str, Any]]) -> None:
    """Şablon veri referanslarını açık DAG bağımlılıklarına dönüştür.

    Model `{{steps.read.result.items}}` yazıp `dependsOn` alanını unutursa veri
    tüketen adım üreticiden önce schedule edilmemeli. Bilinmeyen referanslar
    burada korunur; hemen ardından çalışan linter bunları güvenli biçimde
    reddeder.
    """
    reference_pattern = re.compile(r"\{\{\s*steps\.([A-Za-z0-9_\-]+)")
    for step in steps:
        step_id = str(step.get("id", "") or "").strip()
        dependencies: list[str] = []
        for item in (step.get("dependsOn", []) or [])[:MAX_PLAN_STEPS]:
            dependency_id = str(item or "").strip()[:80]
            if dependency_id and dependency_id not in dependencies:
                dependencies.append(dependency_id)
        referenced = reference_pattern.findall(
            json.dumps(
                {
                    "args": step.get("args", {}),
                    "forEach": step.get("forEach"),
                    "resourceScope": step.get("resourceScope", []),
                },
                ensure_ascii=False,
            )
        )
        for dependency_id in referenced:
            if dependency_id != step_id and dependency_id not in dependencies:
                dependencies.append(dependency_id)
        if dependencies:
            step["dependsOn"] = dependencies
        else:
            step.pop("dependsOn", None)


def _lint_prohibited_actions(goal_contract: dict[str, Any], steps: list[dict[str, Any]]) -> list[str]:
    prohibited_capabilities: set[str] = set()
    for action in goal_contract.get("prohibitedActions", []) or []:
        token = str(action or "").strip().lower()
        if token.startswith("capability:"):
            token = token.split(":", 1)[1].strip()
        if token in capability_names():
            prohibited_capabilities.add(token)

    return [
        f"plan linter: GoalContract {step['capability']!r} capability adımını yasaklıyor"
        for step in steps
        if str(step.get("capability", "") or "") in prohibited_capabilities
    ]


def validate_plan(payload: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """Sunucudan gelen plan JSON'unu sözleşmeye göre doğrular ve normalize eder.

    Dönen plan: {intent, goal, goalContract, confidence, privacyClass,
    requiresConfirmation, clarification{needed,question},
    steps[{id,capability,args,description,dependsOn}]}.
    """
    errors: list[str] = []
    blocking_errors: list[str] = []
    if not isinstance(payload, dict):
        return None, ["plan bir JSON nesnesi değil"]

    contract = str(payload.get("contract", "") or "")
    if contract != PLAN_CONTRACT:
        error = f"bilinmeyen sözleşme: {contract}"
        errors.append(error)
        blocking_errors.append(error)

    intent = str(payload.get("intent", "") or "").strip() or "chat"
    goal = str(payload.get("goal", "") or "").strip()
    try:
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.0) or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
        errors.append("confidence sayı değil")

    privacy = str(payload.get("privacyClass", "") or "").strip()
    if privacy and privacy not in {"local_private", "public_text"}:
        error = "privacyClass geçersiz"
        errors.append(error)
        blocking_errors.append(error)
        privacy = ""

    clarification_raw = payload.get("clarification")
    clarification_raw = clarification_raw if isinstance(clarification_raw, dict) else {}
    clarification = {
        "needed": bool(clarification_raw.get("needed", False)),
        "question": str(clarification_raw.get("question", "") or "").strip(),
    }
    if clarification["needed"] and not clarification["question"]:
        error = "clarification.needed true ancak tek hedefli soru eksik"
        errors.append(error)
        blocking_errors.append(error)

    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list):
        error = "steps bir dizi değil"
        errors.append(error)
        blocking_errors.append(error)
        raw_steps = []
    if len(raw_steps) > MAX_PLAN_STEPS:
        error = f"plan linter: adım sayısı {MAX_PLAN_STEPS} sınırını aşıyor"
        errors.append(error)
        blocking_errors.append(error)
    known = capability_names()
    steps: list[dict[str, Any]] = []
    requires_confirmation = bool(payload.get("requiresConfirmation", False))
    for index, raw in enumerate(raw_steps[:MAX_PLAN_STEPS], start=1):
        if not isinstance(raw, dict):
            error = f"steps[{index}]: nesne değil"
            errors.append(error)
            blocking_errors.append(error)
            continue
        capability = str(raw.get("capability", "") or "").strip()
        if not capability:
            error = f"steps[{index}]: capability boş"
            errors.append(error)
            blocking_errors.append(error)
            continue
        if capability not in known:
            error = f"steps[{index}]: bilinmeyen capability {capability!r}"
            errors.append(error)
            blocking_errors.append(error)
            continue
        raw_args = raw.get("args", {})
        if not isinstance(raw_args, dict):
            error = f"steps[{index}].args: nesne değil"
            errors.append(error)
            blocking_errors.append(error)
            raw_args = {}
        args, arg_errors = _validate_step_args(capability, raw_args)
        errors.extend(arg_errors)
        blocking_errors.extend(arg_errors)
        if any("zorunlu argüman eksik" in item for item in arg_errors):
            # Eksik zorunlu argümanla adım yürütülemez; adımı düşür — plan
            # tamamen boş kalırsa aşağıda reddedilir, üst katman netleştirme
            # sorusuna döner.
            continue
        metadata = capability_metadata(capability)
        if bool(metadata.get("sideEffect", False)) or str(metadata.get("permissionClass", "") or "") == "approval_required":
            requires_confirmation = True
        raw_depends = raw.get("dependsOn")
        if raw_depends is not None and not isinstance(raw_depends, list):
            error = f"steps[{index}].dependsOn: dizi değil"
            errors.append(error)
            blocking_errors.append(error)
        depends_on = (
            [
                str(item).strip()[:80]
                for item in raw_depends[:MAX_PLAN_STEPS]
                if str(item or "").strip()
            ]
            if isinstance(raw_depends, list)
            else []
        )
        depends_on = list(dict.fromkeys(depends_on))
        step_payload: dict[str, Any] = {
            "id": str(raw.get("id", "") or f"step_{index}").strip()[:80],
            "capability": capability,
            "args": args,
            "description": str(raw.get("description", "") or "").strip() or capability,
        }
        if depends_on:
            step_payload["dependsOn"] = depends_on
        for_each = raw.get("forEach")
        if for_each is not None:
            if not isinstance(for_each, str) or not for_each.strip():
                error = f"steps[{index}].forEach: dolu şablon metni değil"
                errors.append(error)
                blocking_errors.append(error)
            else:
                step_payload["forEach"] = for_each.strip()
        priority = str(raw.get("priority", raw.get("userPriority", "")) or "").strip().lower()
        if priority in {"low", "normal", "high", "urgent"}:
            step_payload["userPriority"] = priority
        for field in ("deadlineAt", "queuedAt"):
            value = str(raw.get(field, "") or "").strip()
            if value:
                step_payload[field] = value[:64]
        resource_scope = raw.get("resourceScope")
        if isinstance(resource_scope, list):
            normalized_scope = [
                " ".join(str(item or "").split())[:240]
                for item in resource_scope[:12]
                if str(item or "").strip()
            ]
            if normalized_scope:
                step_payload["resourceScope"] = normalized_scope
        steps.append(step_payload)

    _normalize_data_dependencies(steps)
    lint_errors = _lint_plan_steps(steps)
    errors.extend(lint_errors)
    blocking_errors.extend(lint_errors)

    raw_goal_contract = payload.get("goalContract")
    goal_contract_errors = _validate_goal_contract_input(raw_goal_contract)
    errors.extend(goal_contract_errors)
    blocking_errors.extend(goal_contract_errors)
    goal_contract = _normalize_goal_contract(
        raw_goal_contract,
        intent=intent,
        goal=goal,
        privacy=privacy,
        requires_confirmation=requires_confirmation,
        steps=steps,
        legacy_clarification=clarification,
    )
    goal_privacy = str(goal_contract.get("privacy", "") or "")
    if privacy and goal_privacy != privacy:
        error = "goalContract.privacy ile privacyClass uyuşmuyor"
        errors.append(error)
        blocking_errors.append(error)
    privacy = privacy or goal_privacy
    for step in steps:
        step.setdefault("userPriority", str(goal_contract.get("priority", "normal") or "normal"))
    prohibition_errors = _lint_prohibited_actions(goal_contract, steps)
    errors.extend(prohibition_errors)
    blocking_errors.extend(prohibition_errors)
    first_blocking_question = next(
        (
            item["question"]
            for item in goal_contract["missingInformation"]
            if item.get("blocking") and item.get("question")
        ),
        "",
    )
    if first_blocking_question:
        clarification = {"needed": True, "question": first_blocking_question}

    plan = {
        "intent": intent,
        "goal": goal,
        "goalContract": goal_contract,
        "confidence": confidence,
        "privacyClass": privacy,
        "requiresConfirmation": requires_confirmation,
        "clarification": clarification,
        "steps": steps,
    }
    if blocking_errors:
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
    effective_privacy = str(plan.get("privacyClass", "") or fallback_privacy)
    goal_contract = dict(plan.get("goalContract", {}) or {})
    if goal_contract:
        goal_contract["privacy"] = effective_privacy
    if clarification.get("needed") and clarification.get("question"):
        return {
            "intent": str(plan.get("intent", "") or "clarification"),
            "capability": "",
            "args": {},
            "confidence": float(plan.get("confidence", 0.0) or 0.0),
            "requiresConfirmation": False,
            "isMultiStep": False,
            "privacyClass": effective_privacy,
            "goalContract": goal_contract,
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
            "privacyClass": effective_privacy,
            "goalContract": goal_contract,
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
        "privacyClass": effective_privacy,
        "goalContract": goal_contract,
    }
    if is_multi or plan.get("goal") or goal_contract.get("objective"):
        summary = str(plan.get("goal", "") or goal_contract.get("objective", "") or "") or " → ".join(
            str(step.get("capability", "")) for step in steps
        )
        payload["planPreview"] = {
            "summary": summary,
            "steps": [dict(step) for step in steps],
            "privacyClass": payload["privacyClass"],
            "goalContract": goal_contract,
            "agentPlan": build_agent_plan([dict(step) for step in steps], summary=summary),
        }
    else:
        payload["planPreview"] = None
    return payload
