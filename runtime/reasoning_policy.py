from __future__ import annotations

from dataclasses import dataclass
from typing import Any


GOAL_CONTEXT_CONTRACT = "elyan.execution_goal.v1"
_VALIDATED_DETERMINISTIC_PLANS = {
    "data_artifact_pipeline",
    "document_transform",
    "pdf_report",
    "research_spreadsheet",
    "selected_document_transform",
}
_REASONING_INTENTS = {
    "optimization_decision_support",
    "professional_workflow",
    "professional_analysis",
}


@dataclass(frozen=True, slots=True)
class ReasoningDecision:
    use_structured_planner: bool
    reason: str


def _bounded_texts(value: Any, *, limit: int = 12) -> list[str]:
    items = value if isinstance(value, (list, tuple)) else []
    return [str(item).strip()[:240] for item in items if str(item or "").strip()][:limit]


def _steps(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        raw = value.get("steps", [])
    else:
        raw = getattr(value, "steps", ())
        if not raw:
            preview = getattr(value, "plan_preview", None)
            raw = preview.get("steps", []) if isinstance(preview, dict) else []
    return [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, (list, tuple)) else []


def decide_reasoning_path(
    routed: Any,
    *,
    plan_mode: bool = False,
    work_order: dict[str, Any] | None = None,
    deterministic_only: bool = False,
) -> ReasoningDecision:
    """Choose the fast path or the structured planner from existing facts.

    This policy deliberately does not parse natural language. The router and the
    signed WorkOrder already expose the structural signals needed to identify a
    task that benefits from reasoning.
    """
    if deterministic_only:
        return ReasoningDecision(False, "deterministic_only")
    if plan_mode:
        return ReasoningDecision(True, "plan_mode")

    order = work_order if isinstance(work_order, dict) else {}
    preview = order.get("planPreview") if isinstance(order.get("planPreview"), dict) else {}
    explicit_steps = _steps(preview)
    if explicit_steps:
        return ReasoningDecision(False, "trusted_work_order_plan")

    routed_steps = _steps(routed)
    if routed is not None:
        route_kinds = {
            str(getattr(routed, "intent", "") or "").strip(),
            str(getattr(routed, "reason", "") or "").strip(),
        }
        if route_kinds.intersection(_REASONING_INTENTS):
            return ReasoningDecision(True, "reasoning_intent")
    if routed is not None and routed_steps:
        try:
            route_confidence = float(getattr(routed, "confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            route_confidence = 0.0
        if route_confidence >= 0.9 and route_kinds.intersection(_VALIDATED_DETERMINISTIC_PLANS):
            return ReasoningDecision(False, "validated_deterministic_plan")
    if bool(getattr(routed, "is_multi_step", False)) or len(routed_steps) > 1:
        return ReasoningDecision(True, "multi_step")
    if any(step.get("forEach") is not None or step.get("dependsOn") for step in routed_steps):
        return ReasoningDecision(True, "data_flow")

    capabilities = {
        str(item or "").strip()
        for item in order.get("requiredCapabilities", [])
        if str(item or "").strip()
    }
    if len(capabilities) > 1:
        return ReasoningDecision(True, "multi_capability_work_order")

    required_outputs = [
        item
        for item in order.get("expectedOutputs", [])
        if isinstance(item, dict) and item.get("required") is True
    ]
    if len(required_outputs) > 1:
        return ReasoningDecision(True, "multi_deliverable_work_order")

    if routed is not None:
        try:
            confidence = float(getattr(routed, "confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.8:
            return ReasoningDecision(True, "low_confidence_route")
    return ReasoningDecision(False, "atomic_fast_path")


# ── Yürütme modu politikası (P0) ─────────────────────────────────────────────
# Router artık BİRİNCİL beyin değil, yüksek güvenli bir HIZLI YOL önbelleğidir.
# Kalıba oturmayan / novel işler çok turlu ajan döngüsüne gider.

# Router'ın hızlı yolda kalabilmesi için asgari güven eşiği.
FAST_PATH_MIN_CONFIDENCE = 0.9

# Salt gözlem/okuma yetenekleri: kullanıcı açıkça ÜRETİM istediğinde bunlara
# rotalanmak bir uyumsuzluktur (canlıda görülen hata sınıfı: "masaüstünde
# liste.txt oluştur" → directory_tree).
_OBSERVATIONAL_CAPABILITIES = {
    "directory_tree",
    "file_search",
    "file_read",
    "sys_info",
    "document_read",
    "retrieve_context",
    "analyze_screen",
    "desktop_os.status",
    "desktop_os.processes",
    "desktop_os.active_window",
}

# Üretim/teslim niyeti taşıyan fiiller (TR + EN, normalize edilmiş kök).
_CREATION_MARKERS = (
    "olustur", "oluştur", "yarat", "yaz", "kaydet", "hazirla", "hazırla",
    "uret", "üret", "ekle", "indir", "gonder", "gönder", "duzenle", "düzenle",
    "create", "write", "save", "generate", "make", "build", "add", "send",
)


def _normalize_tr(value: Any) -> str:
    text = str(value or "").strip().lower()
    for source, target in (
        ("ı", "i"), ("ğ", "g"), ("ü", "u"), ("ş", "s"), ("ö", "o"), ("ç", "c")
    ):
        text = text.replace(source, target)
    return text


def route_capability_mismatch(routed: Any, query: str = "") -> bool:
    """Kullanıcı üretim isterken salt-gözlem yeteneğine rotalandıysa True.

    Bu, güven skoru yüksek olsa bile hızlı yolu iptal ettirir; iş ajan
    döngüsüne devredilir (yanlış yetenekle sessizce ilerlemek yerine)."""
    if routed is None:
        return False
    capability = str(getattr(routed, "tool_name", "") or "").strip()
    if capability not in _OBSERVATIONAL_CAPABILITIES:
        return False
    normalized = _normalize_tr(query)
    return any(marker in normalized for marker in _CREATION_MARKERS)


@dataclass(frozen=True, slots=True)
class ExecutionModeDecision:
    mode: str  # "fast_path" | "structured_plan" | "agent_loop"
    reason: str


def decide_execution_mode(
    routed: Any,
    *,
    query: str = "",
    plan_mode: bool = False,
    work_order: dict[str, Any] | None = None,
    deterministic_only: bool = False,
    agent_loop_enabled: bool = True,
) -> ExecutionModeDecision:
    """Bir işin hızlı yol, yapılandırılmış plan ya da ajan döngüsüyle
    yürütüleceğine karar verir.

    Sıra bilinçlidir: güvenli/deterministik yollar önce elenir; geriye kalan
    (novel, düşük güvenli, çok yetenekli, uyumsuz rotalanmış) işler ajan
    döngüsüne düşer. ``agent_loop_enabled=False`` ile eski davranışa dönülür.
    """
    if deterministic_only:
        return ExecutionModeDecision("fast_path", "deterministic_only")

    order = work_order if isinstance(work_order, dict) else {}
    preview = order.get("planPreview") if isinstance(order.get("planPreview"), dict) else {}
    if _steps(preview):
        # İmzalı iş emri açık adımlar taşıyor: otorite plandadır.
        return ExecutionModeDecision("structured_plan", "trusted_work_order_plan")

    if not agent_loop_enabled:
        decision = decide_reasoning_path(
            routed,
            plan_mode=plan_mode,
            work_order=work_order,
            deterministic_only=deterministic_only,
        )
        return ExecutionModeDecision(
            "structured_plan" if decision.use_structured_planner else "fast_path",
            decision.reason,
        )

    if plan_mode:
        return ExecutionModeDecision("agent_loop", "plan_mode")
    if routed is None:
        # Router hiçbir kalıba oturtamadı → tam da ajan döngüsünün alanı.
        return ExecutionModeDecision("agent_loop", "unrouted_novel_task")
    if route_capability_mismatch(routed, query):
        return ExecutionModeDecision("agent_loop", "route_capability_mismatch")

    try:
        confidence = float(getattr(routed, "confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    routed_steps = _steps(routed)
    multi_step = bool(getattr(routed, "is_multi_step", False)) or len(routed_steps) > 1

    if confidence < FAST_PATH_MIN_CONFIDENCE:
        return ExecutionModeDecision("agent_loop", "low_confidence_route")
    if multi_step:
        # Yüksek güvenli ÇOK adımlı kalıplar (araştır+yaz gibi) doğrulanmış
        # deterministik planlardır; ajan döngüsüne gerek yok.
        return ExecutionModeDecision("structured_plan", "validated_multi_step_route")
    if any(step.get("forEach") is not None or step.get("dependsOn") for step in routed_steps):
        return ExecutionModeDecision("structured_plan", "data_flow")
    return ExecutionModeDecision("fast_path", "high_confidence_atomic_route")


def deterministic_plan_hint(routed: Any) -> dict[str, Any] | None:
    if routed is None:
        return None
    steps = _steps(routed)
    return {
        "source": "deterministic_router",
        "intent": str(getattr(routed, "intent", "") or getattr(routed, "reason", "") or "task"),
        "capability": str(getattr(routed, "tool_name", "") or ""),
        "confidence": float(getattr(routed, "confidence", 0.0) or 0.0),
        "requiresConfirmation": bool(getattr(routed, "requires_confirmation", False)),
        "steps": steps[:16],
    }


def build_goal_context(
    *,
    query: str = "",
    goal_contract: dict[str, Any] | None = None,
    work_order: dict[str, Any] | None = None,
    privacy: str = "",
) -> dict[str, Any]:
    """Return the bounded, non-secret goal facts shared by planner/executor."""
    goal = dict(goal_contract) if isinstance(goal_contract, dict) else {}
    order = work_order if isinstance(work_order, dict) else {}
    order_goal = order.get("goal") if isinstance(order.get("goal"), dict) else {}
    execution = order.get("execution") if isinstance(order.get("execution"), dict) else {}

    objective = str(
        goal.get("objective", "")
        or order_goal.get("summary", "")
        or order_goal.get("topic", "")
        or query
    ).strip()[:1000]
    requested_privacy = str(
        goal.get("privacy", "")
        or order.get("privacyClass", "")
        or privacy
        or "public_text"
    ).strip()
    normalized_privacy = "public_text" if requested_privacy == "public_text" else "local_private"
    normalized_goal = {
        "contract": str(goal.get("contract", "") or "elyan.goal_contract.v1"),
        "objective": objective,
        "deliverables": _bounded_texts(goal.get("deliverables")),
        "constraints": _bounded_texts(goal.get("constraints")),
        "acceptanceCriteria": _bounded_texts(goal.get("acceptanceCriteria")),
        "prohibitedActions": _bounded_texts(goal.get("prohibitedActions")),
        "privacy": normalized_privacy,
        "risk": str(goal.get("risk", "") or "low"),
        "priority": str(goal.get("priority", "") or "normal"),
        "missingInformation": [
            dict(item)
            for item in goal.get("missingInformation", [])
            if isinstance(item, dict)
        ][:8],
    }
    try:
        max_steps = int(execution.get("maxSteps", 16) or 16)
    except (TypeError, ValueError):
        max_steps = 16

    return {
        "contract": GOAL_CONTEXT_CONTRACT,
        "goalContract": normalized_goal,
        "workOrder": {
            "schema": str(order.get("schema", "") or ""),
            "capabilityScope": [
                str(item) for item in order.get("capabilityScope", []) if str(item or "").strip()
            ][:80],
            "expectedOutputs": [
                dict(item) for item in order.get("expectedOutputs", []) if isinstance(item, dict)
            ][:12],
            "verificationRules": [
                dict(item) for item in order.get("verificationRules", []) if isinstance(item, dict)
            ][:12],
            # Backend'in tipli anlaması planlayıcıya tohum olarak taşınır:
            # entities (url/dosya/uygulama/konu) + önerilen adımlar. Daha önce
            # çöpe atılıyordu ve masaüstü aynı anlamayı özet metinden yeniden
            # türetmeye çalışıyordu (bağlam kaybı).
            "entities": [
                {
                    "type": str(item.get("type", "") or ""),
                    "value": str(item.get("value", "") or "")[:240],
                }
                for item in order.get("entities", [])
                if isinstance(item, dict) and str(item.get("value", "") or "").strip()
            ][:16],
            "suggestedSteps": [
                {
                    "capability": str(step.get("capability", "") or ""),
                    "description": str(step.get("description", "") or "")[:200],
                    "args": step.get("args") if isinstance(step.get("args"), dict) else {},
                }
                for step in (
                    order.get("planPreview", {}).get("steps", [])
                    if isinstance(order.get("planPreview"), dict)
                    else []
                )
                if isinstance(step, dict) and str(step.get("capability", "") or "").strip()
            ][:16],
            "understanding": (
                dict(order.get("understanding"))
                if isinstance(order.get("understanding"), dict)
                else {}
            ),
            "maxSteps": max(1, min(16, max_steps)),
        },
    }


def allowed_capabilities(goal_context: dict[str, Any] | None) -> set[str]:
    context = goal_context if isinstance(goal_context, dict) else {}
    order = context.get("workOrder") if isinstance(context.get("workOrder"), dict) else {}
    return {
        str(item or "").strip()
        for item in order.get("capabilityScope", [])
        if str(item or "").strip()
    }
