"""
Elyan Pipeline — Modüler İşlem Hattı

agent.py'nin 4715 satırlık monolitini 6 stage'e böler.
Her stage bağımsız test edilebilir.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time
import re
import asyncio
from pathlib import Path
from utils.logger import get_logger
from core.reasoning.stage_profiler import stage_profiler
from core.monitoring import record_orchestration_decision, record_pipeline_job
from tools import AVAILABLE_TOOLS
from core.pipeline_upgrade import (
    flag_enabled,
    deterministic_intent_score,
    parse_llm_intent_envelope,
    index_attachments,
    context_fingerprint,
    build_context_working_set,
    route_model_tier,
    build_skeleton_plan,
    build_step_specs_from_plan,
    get_plan_cache,
    make_plan_cache_key,
    load_output_contract,
    validate_output_contract,
    assign_model_roles,
    build_success_criteria,
    validate_research_payload,
    validate_tool_io,
    detect_artifact_mismatch,
    collect_paths_from_tool_results,
    decide_orchestration_policy,
    fallback_ladder,
    diff_only_failed_steps,
    enforce_output_contract,
    verify_code_gates,
    verify_research_gates,
    verify_asset_gates,
    verify_taskspec_contract,
    build_reflexion_hint,
    build_critic_review_prompt,
    JobTelemetryAccumulator,
    estimate_token_cost,
)
from core.workspace_contract import ensure_workspace_contract
from core.hybrid_model_policy import build_hybrid_model_plan
from core.verifier import evaluate_runtime_capability
from core.process_profiles import (
    approval_granted,
    artifact_entry,
    build_task_packets,
    get_process_profile,
    infer_nexus_mode,
    inspect_workspace,
    normalize_workflow_profile,
    profile_applicable,
    render_design_markdown,
    render_finish_branch_report,
    render_plan_markdown,
    render_review_report,
    write_json_artifact,
    write_text_artifact,
)
from core.failure_classification import classify_failure_class
from core.recovery_policy import select_recovery_strategy
from core.telemetry.runtime_trace import ensure_runtime_trace, update_runtime_trace
from core.spec.task_spec_standard import coerce_task_spec_standard

logger = get_logger("pipeline")


_NON_ACTIONABLE_INTENTS = {"", "chat", "unknown", "communication", "answer", "respond", "direct", "show_help"}
_SHALLOW_ACTION_INTENTS = {"", "chat", "unknown", "communication", "answer", "respond", "direct", "show_help", "open_app", "open_url", "get_word_definition"}
_MODEL_A_SAFE_ACTIONS = [
    "open_app",
    "close_app",
    "open_url",
    "web_search",
    "create_folder",
    "list_files",
    "read_file",
    "write_file",
    "run_safe_command",
    "http_request",
    "api_health_get_save",
    "set_wallpaper",
    "analyze_screen",
    "take_screenshot",
]

_EXECUTION_MODE_ALIASES = {
    "chat": "chat",
    "conversation": "chat",
    "conversational": "chat",
    "talk": "chat",
    "assist": "assist",
    "assisted": "assist",
    "assistant": "assist",
    "review": "assist",
    "confirmed": "assist",
    "operator": "operator",
    "operate": "operator",
    "autonomy": "operator",
    "full": "operator",
    "full-autonomy": "operator",
    "full_autonomy": "operator",
}

_OP_MODE_TO_EXEC_MODE = {
    "advisory": "chat",
    "assisted": "assist",
    "confirmed": "assist",
    "trusted": "operator",
    "operator": "operator",
}


def _normalize_action(action: Any) -> str:
    return str(action or "").strip().lower()


def _normalize_execution_mode(mode: Any) -> str:
    raw = str(mode or "").strip().lower()
    if not raw:
        return ""
    return _EXECUTION_MODE_ALIASES.get(raw, raw if raw in {"chat", "assist", "operator"} else "")


def _resolve_execution_mode(ctx: Any) -> str:
    policy = ctx.runtime_policy if isinstance(getattr(ctx, "runtime_policy", {}), dict) else {}
    execution_cfg = policy.get("execution", {}) if isinstance(policy.get("execution"), dict) else {}
    metadata = policy.get("metadata", {}) if isinstance(policy.get("metadata"), dict) else {}

    for candidate in (
        metadata.get("execution_mode"),
        metadata.get("agent_mode"),
        execution_cfg.get("mode"),
    ):
        normalized = _normalize_execution_mode(candidate)
        if normalized:
            return normalized

    derive = bool(execution_cfg.get("derive_from_operator_mode", False))
    if derive:
        security_cfg = policy.get("security", {}) if isinstance(policy.get("security"), dict) else {}
        op_mode = str(security_cfg.get("operator_mode") or "").strip().lower()
        mapped = _normalize_execution_mode(_OP_MODE_TO_EXEC_MODE.get(op_mode, ""))
        if mapped:
            return mapped

    default_mode = _normalize_execution_mode(execution_cfg.get("default_mode"))
    if default_mode:
        return default_mode
    return "operator"


def _build_assist_mode_preview(ctx: Any) -> str:
    intent = ctx.intent if isinstance(getattr(ctx, "intent", {}), dict) else {}
    action = _normalize_action(getattr(ctx, "action", "") or intent.get("action"))
    params = intent.get("params", {}) if isinstance(intent.get("params"), dict) else {}
    policy = ctx.runtime_policy if isinstance(getattr(ctx, "runtime_policy", {}), dict) else {}
    execution_cfg = policy.get("execution", {}) if isinstance(policy.get("execution"), dict) else {}
    try:
        max_steps = int(execution_cfg.get("assist_preview_max_steps", 6) or 6)
    except Exception:
        max_steps = 6
    max_steps = max(1, min(12, max_steps))

    lines: list[str] = [
        "Assist Mode: plan hazir, otomatik calistirma kapali.",
        f"Intent: {action or 'chat'}",
    ]
    if params:
        preview = []
        for key in ("path", "url", "app_name", "command", "topic", "query"):
            val = str(params.get(key) or "").strip()
            if val:
                preview.append(f"{key}={val}")
        if preview:
            lines.append("Slots: " + ", ".join(preview[:6]))

    tasks = intent.get("tasks") if isinstance(intent.get("tasks"), list) else []
    if tasks:
        lines.append("Plan:")
        for idx, task in enumerate(tasks[:max_steps], start=1):
            if not isinstance(task, dict):
                continue
            step_action = _normalize_action(task.get("action"))
            desc = str(task.get("description") or task.get("title") or "").strip()
            lines.append(f"{idx}. {step_action or 'step'} - {desc or 'adim'}")
    elif isinstance(getattr(ctx, "plan", None), list) and ctx.plan:
        lines.append("Plan:")
        for idx, step in enumerate(ctx.plan[:max_steps], start=1):
            if not isinstance(step, dict):
                continue
            step_action = _normalize_action(step.get("action"))
            desc = str(step.get("description") or step.get("title") or "").strip()
            lines.append(f"{idx}. {step_action or 'step'} - {desc or 'adim'}")
    else:
        lines.append("Plan: 1 adimli dogrudan islem.")

    lines.append("Operator Mode icin `execution_mode=operator` gonder.")
    return "\n".join(lines)


def _build_capability_fallback_params(action: str, user_input: str) -> Dict[str, Any]:
    fallback_action = _normalize_action(action)
    low_input = str(user_input or "").lower()
    if fallback_action == "research_document_delivery":
        return {
            "topic": user_input,
            "depth": "standard",
            "include_word": True,
            "include_report": True,
        }
    if fallback_action == "screen_workflow":
        return {
            "instruction": user_input,
            "mode": "inspect_and_control" if any(tok in low_input for tok in ("tıkla", "tikla", "aç", "ac", "yaz", "bas")) else "inspect",
            "action_goal": user_input,
            "final_screenshot": True,
            "include_analysis": True,
        }
    if fallback_action == "vision_operator_loop":
        return {
            "objective": user_input,
            "max_iterations": 2,
            "pause_ms": 250,
            "include_ui_map": True,
        }
    if fallback_action == "operator_mission_control":
        return {
            "objective": user_input,
            "max_subtasks": 4,
            "pause_ms": 250,
        }
    if fallback_action == "create_coding_project":
        return {"project_name": "elyan-project", "brief": user_input}
    if fallback_action == "create_web_project_scaffold":
        return {"project_name": "elyan-web", "brief": user_input}
    if fallback_action == "generate_document_pack":
        return {"topic": user_input, "brief": user_input}
    if fallback_action == "summarize_text":
        return {"text": user_input}
    return {}


def _should_realign_to_capability(
    *,
    user_input: str,
    action: str,
    capability_domain: str,
    capability_confidence: float,
    capability_primary_action: str,
    intent_confidence: float,
    override_threshold: float,
) -> bool:
    fallback_action = _normalize_action(capability_primary_action)
    current_action = _normalize_action(action)
    domain = str(capability_domain or "").strip().lower()
    low_input = str(user_input or "").lower()

    if not fallback_action or fallback_action == current_action:
        return False
    if domain in {"", "general"}:
        return False
    if float(capability_confidence or 0.0) < max(0.62, float(override_threshold or 0.0)):
        return False
    if current_action not in _SHALLOW_ACTION_INTENTS and float(intent_confidence or 0.0) >= 0.72:
        return False

    if domain == "screen_operator":
        explicit_screen_markers = (
            "durum nedir", "ekrana bak", "ekranı oku", "ekrani oku", "ekranda ne var",
            "screen", "screenshot", "bilgisayari kullan", "bilgisayarı kullan",
            "tikla", "tıkla", "click", "type", "mouse", "klavye", "tuş", "tus",
        )
        operator_step_markers = (
            "durum nedir", "ekrana bak", "ekranı oku", "ekrani oku", "ekranda ne var",
            "ardindan", "ardından", "ve sonra", "ayni anda", "aynı anda",
            "tikla", "tıkla", "yaz", "click", "type", "mouse", "klavye", "tuş", "tus",
            "kısayol", "kisayol",
        )
        if current_action == "multi_task" and _looks_simple_app_control_command(low_input):
            return False
        if not any(k in low_input for k in explicit_screen_markers) and any(
            k in low_input for k in ("araştır", "arastir", "research", "kaydet", "rapor", "belge", "word", "excel")
        ):
            return False
        simple_app_control = current_action in {"open_app", "close_app"} and not any(
            k in low_input for k in operator_step_markers
        )
        # Basit app odaklama/acma/kapama komutlari deterministic parser sonucunda kalmali.
        # Aksi halde "safari ac" gibi net komutlar gereksizce screen_operator path'ine kayiyor.
        if simple_app_control:
            return False
        return any(
            k in low_input
            for k in (
                "durum nedir", "ekrana bak", "ekranı oku", "ekrani oku", "ekranda ne var",
                "screen", "screenshot", "bilgisayari kullan", "bilgisayarı kullan",
                "tikla", "tıkla", "yaz", "ac", "aç", "kapat", "click", "type",
                "ardindan", "ardından", "ve sonra", "ayni anda", "aynı anda",
            )
        )
    if domain == "research":
        return any(k in low_input for k in ("araştır", "arastir", "research", "kaynak", "rapor", "literatür", "literatur", "incele", "karşılaştır", "karsilastir"))
    if domain in {"document", "summarization"}:
        return any(k in low_input for k in ("belge", "doküman", "dokuman", "pdf", "docx", "sunum", "özet", "ozet", "rapor"))
    if domain in {"code", "website", "full_stack_delivery"}:
        return any(k in low_input for k in ("kod", "code", "script", "python", "react", "website", "web sitesi", "landing page", "hata", "debug", "refactor"))
    if domain == "automation":
        return any(k in low_input for k in ("otomasyon", "automation", "schedule", "cron", "arka planda", "workflow"))
    if domain == "api_integration":
        return any(k in low_input for k in ("api", "endpoint", "http", "graphql", "webhook", "request"))
    if domain == "file_ops":
        return any(k in low_input for k in ("dosya", "klasör", "klasor", "kaydet", "yaz", "oku", "listele"))
    return False


def _is_likely_information_query(text: str) -> bool:
    low = str(text or "").strip().lower()
    if not low:
        return False
    question_words = (
        "nedir",
        "kimdir",
        "nasıl",
        "nasil",
        "neden",
        "niye",
        "hangi",
        "kaç",
        "kac",
        "ne demek",
        "what",
        "who",
        "why",
        "how",
        "when",
        "where",
    )
    if low.endswith("?") and any(w in low for w in question_words):
        return True
    return False


def _looks_actionable_input(text: str, attachments: Optional[List[str]] = None) -> bool:
    if isinstance(attachments, list) and any(str(a or "").strip() for a in attachments):
        return True
    low = str(text or "").strip().lower()
    if not low:
        return False
    if _is_likely_information_query(low):
        return False
    if re.search(r"\b\d+\)\s+\S+", low):
        return True
    strong_markers = (
        "yap", "oluştur", "olustur", "kaydet", "sil", "taşı", "tasi", "kopyala",
        "aç", "ac", "kapat", "çalıştır", "calistir", "ind", "gönder", "gonder",
        "duvar kağıdı", "duvar kagidi", "arka plan", "wallpaper",
        "ekrana bak", "ekranı analiz", "screenshot", "ss al",
        "mouse", "imlec", "cursor", "tıkla", "tikla", "klavye", "tuş", "tus", "kısayol", "kisayol",
        "health check", "dosya", "klasör", "klasor", "planla", "uygula", "adım", "adim",
    )
    if any(m in low for m in strong_markers):
        return True
    weak_markers = ("api", "http", "endpoint", "graphql", "webhook")
    has_weak = any(m in low for m in weak_markers)
    has_url = bool(re.search(r"https?://", low))
    has_command_hint = any(m in low for m in ("check", "at", "çağır", "cagir", "kaydet", "istek", "request"))
    if has_weak and (has_url or has_command_hint):
        return True
    if low.endswith("?"):
        return False
    return False


def _looks_simple_app_control_command(text: str) -> bool:
    low = str(text or "").strip().lower()
    if not low:
        return False
    ui_markers = (
        "tıkla", "tikla", "click", "type", "yaz", "enter", "buton", "button",
        "mouse", "imlec", "cursor", "tuş", "tus", "kısayol", "kisayol",
        "sekme", "tab", "adres çubuğu", "adres cubugu",
    )
    if any(marker in low for marker in ui_markers):
        return False
    control_markers = ("aç", "ac", "kapat", "close", "open", "geç", "odaklan", "focus", "launch", "başlat", "baslat")
    if not any(marker in low for marker in control_markers):
        return False
    app_markers = (
        "safari", "chrome", "firefox", "vscode", "vs code", "visual studio code",
        "terminal", "iterm", "finder", "telegram", "discord", "slack", "spotify",
        "mail", "calendar", "takvim", "notes", "notlar", "preview", "photos",
        "mesajlar", "messages", "browser", "tarayıcı", "tarayici",
    )
    if any(marker in low for marker in app_markers):
        return True
    return bool(re.search(r"[\"']([^\"']{2,40})[\"']\s*(aç|ac|kapat|open|close|focus|odaklan)", low))


def _is_simple_browser_or_app_intent(intent: Any) -> bool:
    if not isinstance(intent, dict):
        return False
    action = _normalize_action(intent.get("action"))
    if action in {"open_app", "open_url", "close_app"}:
        return True
    if action != "multi_task":
        return False
    tasks = intent.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return False
    allowed_actions = {"open_app", "open_url", "close_app"}
    normalized_actions = []
    for task in tasks:
        if not isinstance(task, dict):
            return False
        task_action = _normalize_action(task.get("action"))
        if task_action not in allowed_actions:
            return False
        normalized_actions.append(task_action)
    return "open_url" in normalized_actions and len(normalized_actions) <= 3


def _resolve_runtime_autonomy_mode(ctx: Any) -> tuple[str, str]:
    policy = getattr(ctx, "runtime_policy", {}) if isinstance(getattr(ctx, "runtime_policy", {}), dict) else {}
    metadata = policy.get("metadata", {}) if isinstance(policy.get("metadata"), dict) else {}
    raw = str(
        metadata.get("autonomy_mode")
        or metadata.get("autonomy")
        or policy.get("name")
        or ((policy.get("execution") or {}).get("mode") if isinstance(policy.get("execution"), dict) else "")
        or ""
    ).strip().lower()
    if raw in {"full", "full-autonomy", "full_autonomy", "tam_otonom", "tam-otonom"}:
        return "tam_otonom", raw or "full-autonomy"
    if raw in {"chat", "manual", "operator_onayli", "operator-onayli"}:
        return "operator_onayli", raw or "chat"
    if raw:
        return "yari_otonom", raw
    return "yari_otonom", "balanced"


def _set_execution_trace(
    ctx: Any,
    *,
    route: str,
    decision_path: List[str] | None = None,
    details: Dict[str, Any] | None = None,
) -> None:
    route_name = str(route or "").strip() or "single_agent"
    logical_mode, raw_mode = _resolve_runtime_autonomy_mode(ctx)
    path = [str(x).strip() for x in list(decision_path or []) if str(x).strip()]
    ctx.execution_route = route_name
    ctx.autonomy_mode = logical_mode
    ctx.autonomy_policy = raw_mode
    ctx.orchestration_decision_path = path
    if not isinstance(getattr(ctx, "telemetry", None), dict):
        ctx.telemetry = {}
    trace = {
        "route": route_name,
        "autonomy_mode": logical_mode,
        "autonomy_policy": raw_mode,
        "decision_path": list(path),
    }
    if isinstance(details, dict) and details:
        trace["details"] = dict(details)
    ctx.telemetry["execution_trace"] = trace
    if isinstance(getattr(ctx, "capability_plan", None), dict):
        ctx.capability_plan["execution_trace"] = trace


def _resolve_model_a_policy(ctx: Any) -> tuple[bool, str, float, list[str]]:
    enabled = True
    model_path = str(Path.home() / ".elyan" / "models" / "nlu" / "baseline_intent_model.json")
    min_confidence = 0.78
    allowed_actions = list(_MODEL_A_SAFE_ACTIONS)

    try:
        from config.elyan_config import elyan_config

        enabled = bool(elyan_config.get("agent.nlu.model_a.enabled", enabled))
        model_path = str(elyan_config.get("agent.nlu.model_a.model_path", model_path) or model_path)
        min_confidence = float(elyan_config.get("agent.nlu.model_a.min_confidence", min_confidence) or min_confidence)
        configured_actions = elyan_config.get("agent.nlu.model_a.allowed_actions", None)
        if isinstance(configured_actions, list) and configured_actions:
            allowed_actions = [str(x).strip().lower() for x in configured_actions if str(x).strip()]
    except Exception:
        pass

    try:
        policy = ctx.runtime_policy if isinstance(ctx.runtime_policy, dict) else {}
        nlu_cfg = policy.get("nlu", {}) if isinstance(policy.get("nlu"), dict) else {}
        model_a_cfg = nlu_cfg.get("model_a", {}) if isinstance(nlu_cfg.get("model_a"), dict) else {}
        meta = policy.get("metadata", {}) if isinstance(policy.get("metadata"), dict) else {}
        if "enabled" in model_a_cfg:
            enabled = bool(model_a_cfg.get("enabled"))
        if "model_path" in model_a_cfg:
            model_path = str(model_a_cfg.get("model_path") or model_path)
        if "min_confidence" in model_a_cfg:
            min_confidence = float(model_a_cfg.get("min_confidence") or min_confidence)
        if isinstance(model_a_cfg.get("allowed_actions"), list) and model_a_cfg.get("allowed_actions"):
            allowed_actions = [str(x).strip().lower() for x in model_a_cfg.get("allowed_actions") if str(x).strip()]
        if "model_a_enabled" in meta:
            enabled = bool(meta.get("model_a_enabled"))
        if "model_a_path" in meta:
            model_path = str(meta.get("model_a_path") or model_path)
        if "model_a_min_confidence" in meta:
            min_confidence = float(meta.get("model_a_min_confidence") or min_confidence)
    except Exception:
        pass

    min_confidence = max(0.0, min(1.0, float(min_confidence or 0.78)))
    return enabled, model_path, min_confidence, [str(x).strip().lower() for x in allowed_actions if str(x).strip()]


def _try_model_a_intent_rescue(
    ctx: Any,
    agent: Any,
    *,
    enabled: bool,
    model_path: str,
    min_confidence: float,
    allowed_actions: list[str],
) -> bool:
    if not enabled:
        return False
    if _normalize_action(getattr(ctx, "action", "")) not in _NON_ACTIONABLE_INTENTS:
        return False
    if not _looks_actionable_input(getattr(ctx, "user_input", ""), getattr(ctx, "attachments", [])):
        return False

    infer = getattr(agent, "_infer_model_a_intent", None)
    if not callable(infer):
        return False

    try:
        inferred = infer(
            getattr(ctx, "user_input", ""),
            min_confidence=min_confidence,
            model_path=model_path,
            allowed_actions=list(allowed_actions or []),
        )
    except Exception:
        return False
    if not isinstance(inferred, dict):
        return False

    action = _normalize_action(inferred.get("action"))
    if action in _NON_ACTIONABLE_INTENTS:
        return False
    confidence = float(inferred.get("confidence", 0.0) or 0.0)
    if confidence < max(0.0, min(1.0, float(min_confidence or 0.0))):
        return False

    ctx.intent = inferred
    ctx.action = action
    ctx.job_type = _job_type_from_action(ctx.action, getattr(ctx, "job_type", "communication"))
    logger.info("Route rescue via Model-A intent: action=%s c=%.2f", ctx.action, confidence)
    return True


def _build_low_confidence_actionable_clarification(ctx: Any) -> str:
    user_input = str(getattr(ctx, "user_input", "") or "").strip()
    attachments = getattr(ctx, "attachments", None)
    action = _normalize_action(getattr(ctx, "action", ""))
    if action not in _NON_ACTIONABLE_INTENTS:
        return ""
    if not _looks_actionable_input(user_input, attachments):
        return ""

    intent = getattr(ctx, "intent", {})
    if not isinstance(intent, dict):
        intent = {}
    intent_conf = float(intent.get("confidence", 0.0) or 0.0)
    intent_score = float(getattr(ctx, "intent_score", 0.0) or 0.0)
    capability_conf = float(getattr(ctx, "capability_confidence", 0.0) or 0.0)
    confidence = max(intent_conf, intent_score, min(0.49, capability_conf * 0.7))
    if confidence >= 0.5:
        return ""

    low = user_input.lower()
    prompts: List[str] = []
    if any(k in low for k in ("safari", "chrome", "firefox", "browser", "tarayici", "tarayıcı")):
        prompts.append("Hangi sayfayi veya arama sorgusunu acmami istiyorsun?")
    if any(k in low for k in ("kaydet", "dosya", "klasor", "klasör", "path", "yol")):
        prompts.append("Ciktiyi hangi dosya/klasor yoluna kaydetmemi istiyorsun?")
    if any(k in low for k in ("tikla", "tıkla", "yaz", "enter", "bas", "button", "buton")):
        prompts.append("UI adimini netlestir: hangi buton/alan ve hangi sirada?")
    if not prompts:
        prompts.append("Tek cumlede hedef + beklenen cikti + (varsa) dosya yolunu yazar misin?")

    prompt_lines = "\n".join(f"- {row}" for row in prompts[:2])
    return (
        "Komutu yanlis calistirmamak icin netlestirmem gerekiyor.\n"
        f"{prompt_lines}"
    ).strip()


def _looks_execution_failure_text(text: str) -> bool:
    low = str(text or "").strip().lower()
    if not low:
        return True
    failure_markers = (
        "hata:",
        "error:",
        "failed",
        "başarısız",
        "basarisiz",
        "zaman aşımı",
        "zaman asimi",
        "timeout",
        "erişilemiyor",
        "erisilemiyor",
        "unavailable",
    )
    return any(m in low for m in failure_markers)


def _extract_direct_failure_class(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    primary = str(payload.get("failure_class") or "").strip().lower()
    if primary:
        return primary
    failed_step = payload.get("failed_step")
    if isinstance(failed_step, dict):
        nested = str(failed_step.get("failure_class") or "").strip().lower()
        if nested:
            return nested
    return ""


def _infer_failure_class_from_text(text: str) -> str:
    low = str(text or "").strip().lower()
    if not low:
        return ""
    if any(tok in low for tok in ("policy block", "security policy", "permission denied", "yetki yok", "izin yok")):
        return "policy_block"
    if any(tok in low for tok in ("planlama", "planning", "dependency", "bagimlilik", "bağımlılık")):
        return "planning_failure"
    return ""


def _has_successful_tool_result(tool_results: List[Dict[str, Any]]) -> bool:
    for row in tool_results or []:
        for payload in _iter_result_payloads(row):
            if payload.get("success") is True:
                return True
            status = str(payload.get("status") or "").strip().lower()
            if status in {"success", "completed", "ok"}:
                return True
    return False


def _iter_result_payloads(payload: Any, *, _depth: int = 0):
    if _depth > 3 or not isinstance(payload, dict):
        return
    yield payload
    for key in ("result", "raw"):
        nested = payload.get(key)
        if isinstance(nested, dict) and nested is not payload:
            yield from _iter_result_payloads(nested, _depth=_depth + 1)


def _extract_screen_summary_signals(tool_results: List[Dict[str, Any]], final_response: str) -> bool:
    for row in tool_results or []:
        text_fields: list[str] = []
        for payload in _iter_result_payloads(row):
            text_fields.extend(
                [
                    str(payload.get("summary") or ""),
                    str(payload.get("message") or ""),
                    str(payload.get("analysis") or ""),
                    str(payload.get("status_report") or ""),
                ]
            )
            obs = payload.get("observations")
            if isinstance(obs, list):
                for item in obs:
                    if isinstance(item, dict):
                        text_fields.append(str(item.get("summary") or ""))
                        ui_map = item.get("ui_map") if isinstance(item.get("ui_map"), dict) else {}
                        text_fields.extend(
                            [
                                str(ui_map.get("frontmost_app") or ""),
                                " ".join(str(app or "") for app in list(ui_map.get("running_apps") or []) if str(app or "").strip()),
                            ]
                        )
            ui_map = payload.get("ui_map") if isinstance(payload.get("ui_map"), dict) else {}
            text_fields.extend(
                [
                    str(ui_map.get("frontmost_app") or ""),
                    " ".join(str(app or "") for app in list(ui_map.get("running_apps") or []) if str(app or "").strip()),
                ]
            )
        if any(t.strip() for t in text_fields):
            return True
    final_low = str(final_response or "").lower()
    return any(k in final_low for k in ("analiz:", "ekranda", "on planda", "çalışan uygulamalar", "calisan uygulamalar"))


def _synthesize_screen_summary(tool_results: List[Dict[str, Any]]) -> str:
    frontmost_app = ""
    running_apps: list[str] = []
    summary_candidates: list[str] = []
    warning_text = ""

    for row in tool_results or []:
        for payload in _iter_result_payloads(row):
            for key in ("summary", "analysis", "message", "status_report"):
                value = str(payload.get(key) or "").strip()
                if value and value not in summary_candidates:
                    summary_candidates.append(value)
            ui_map = payload.get("ui_map") if isinstance(payload.get("ui_map"), dict) else {}
            if not frontmost_app:
                frontmost_app = str(ui_map.get("frontmost_app") or "").strip()
            if isinstance(ui_map.get("running_apps"), list):
                for item in list(ui_map.get("running_apps") or []):
                    app_name = str(item or "").strip()
                    if app_name and app_name not in running_apps:
                        running_apps.append(app_name)
            if not warning_text:
                warning_text = str(payload.get("warning") or payload.get("error") or "").strip()
            observations = payload.get("observations")
            if isinstance(observations, list):
                for item in observations:
                    if not isinstance(item, dict):
                        continue
                    value = str(item.get("summary") or "").strip()
                    if value and value not in summary_candidates:
                        summary_candidates.append(value)
                    obs_ui_map = item.get("ui_map") if isinstance(item.get("ui_map"), dict) else {}
                    if not frontmost_app:
                        frontmost_app = str(obs_ui_map.get("frontmost_app") or "").strip()
                    if isinstance(obs_ui_map.get("running_apps"), list):
                        for app in list(obs_ui_map.get("running_apps") or []):
                            app_name = str(app or "").strip()
                            if app_name and app_name not in running_apps:
                                running_apps.append(app_name)

    if summary_candidates:
        return summary_candidates[0]
    parts: list[str] = []
    if frontmost_app:
        parts.append(f"On planda {frontmost_app} acik gorunuyor.")
    if running_apps:
        parts.append("Calisan uygulamalar: " + ", ".join(running_apps[:5]) + ".")
    if warning_text and not parts:
        parts.append(f"Not: {warning_text[:180]}")
    return " ".join(parts).strip()


def _repair_screen_completion(ctx) -> Dict[str, Any]:
    tool_results = [r for r in list(getattr(ctx, "tool_results", []) or []) if isinstance(r, dict)]
    summary = _synthesize_screen_summary(tool_results)
    if summary:
        ctx.final_response = summary
        synthetic_result = {
            "status": "success",
            "message": summary,
            "summary": summary,
            "data": {"repair_strategy": "screen_summary_synthesized"},
        }
        ctx.tool_results.append(synthetic_result)
        return {"repaired": True, "summary": summary, "strategy": "screen_summary_synthesized"}

    screenshot_paths = collect_paths_from_tool_results(tool_results)
    controlled = "Ekran ozeti alinamadi. Screenshot/artifact uretildi ancak dogrulanabilir screen summary cikmadi."
    if screenshot_paths:
        controlled += f" Artifact sayisi: {len(screenshot_paths)}."
    ctx.final_response = controlled
    return {"repaired": False, "summary": "", "strategy": "screen_controlled_failure", "artifacts": screenshot_paths}


def _is_non_empty_file(path: str) -> bool:
    try:
        from pathlib import Path as _Path

        target = _Path(str(path or "")).expanduser()
        return bool(target.exists() and target.is_file() and int(target.stat().st_size) > 0)
    except Exception:
        return False


async def _repair_taskspec_contract(ctx, agent, task_spec: Dict[str, Any], verification_payload: Dict[str, Any]) -> Dict[str, Any]:
    failed = [str(x).strip() for x in list((verification_payload or {}).get("failed") or []) if str(x).strip()]
    if not failed or not isinstance(task_spec, dict):
        return {"repaired": False, "strategy": "noop", "rechecked": verification_payload or {}}

    reparable_markers = (
        "deliverable:",
        "criteria:artifact_file_exists",
        "criteria:artifact_path_exists",
        "criteria:artifact_file_not_empty",
        "document:missing_artifact",
        "document:empty_artifact",
    )
    if not any(any(marker in item for marker in reparable_markers) for item in failed):
        return {"repaired": False, "strategy": "unsupported_failure", "rechecked": verification_payload or {}}

    steps = task_spec.get("steps") if isinstance(task_spec.get("steps"), list) else []
    if not steps:
        return {"repaired": False, "strategy": "no_steps", "rechecked": verification_payload or {}}

    required_artifacts = [
        dict(item)
        for item in list(task_spec.get("artifacts_expected") or [])
        if isinstance(item, dict) and bool(item.get("must_exist", False))
    ]
    needs_repair: set[str] = set()
    for item in required_artifacts:
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        kind = str(item.get("type") or "").strip().lower()
        from pathlib import Path as _Path

        if kind == "directory" and not _Path(path).expanduser().exists():
            needs_repair.add(path)
        elif kind == "file" and not _is_non_empty_file(path):
            needs_repair.add(path)

    ran_steps: list[str] = []
    executed = False
    local_action_tool_map = {
        "mkdir": "create_folder",
        "write_file": "write_file",
    }

    for step in steps:
        if not isinstance(step, dict):
            continue
        action = str(step.get("action") or "").strip().lower()
        if action not in local_action_tool_map:
            continue
        step_path = str(step.get("path") or ((step.get("params") or {}).get("path") if isinstance(step.get("params"), dict) else "") or "").strip()
        if step_path and needs_repair and step_path not in needs_repair:
            continue

        if action == "mkdir":
            res = await agent._execute_tool(
                local_action_tool_map[action],
                {"path": step_path},
                user_input=str(getattr(ctx, "user_input", "") or ""),
                step_name=f"{step.get('id') or 'step'} (verify_repair)",
            )
            ctx.tool_results.append(
                {
                    "tool": "create_folder",
                    "action": "verify_repair_mkdir",
                    "success": not (isinstance(res, dict) and res.get("success") is False),
                    "path": step_path,
                    "result": res,
                }
            )
            executed = True
            ran_steps.append(str(step.get("id") or "mkdir"))
            continue

        if action == "write_file":
            content = str(step.get("content") or ((step.get("params") or {}).get("content") if isinstance(step.get("params"), dict) else "") or "").strip()
            if not step_path or not content:
                continue
            res = await agent._execute_tool(
                local_action_tool_map[action],
                {"path": step_path, "content": content},
                user_input=str(getattr(ctx, "user_input", "") or ""),
                step_name=f"{step.get('id') or 'step'} (verify_repair)",
            )
            ctx.tool_results.append(
                {
                    "tool": "write_file",
                    "action": "verify_repair_write_file",
                    "success": not (isinstance(res, dict) and res.get("success") is False),
                    "path": step_path,
                    "result": res,
                }
            )
            executed = True
            ran_steps.append(str(step.get("id") or "write_file"))
            if isinstance(getattr(ctx, "intent", None), dict):
                params = ctx.intent.get("params") if isinstance(ctx.intent.get("params"), dict) else {}
                params["path"] = step_path
                ctx.intent["params"] = params

    if not executed:
        return {"repaired": False, "strategy": "no_repairable_steps", "rechecked": verification_payload or {}}

    produced_paths = collect_paths_from_tool_results(ctx.tool_results)
    rechecked = verify_taskspec_contract(
        task_spec=task_spec,
        job_type=str(getattr(ctx, "job_type", "") or ""),
        final_response=str(getattr(ctx, "final_response", "") or ""),
        tool_results=[r for r in list(getattr(ctx, "tool_results", []) or []) if isinstance(r, dict)],
        produced_paths=produced_paths,
    )
    if rechecked.get("ok", False):
        repaired_paths = [str(p).strip() for p in produced_paths if str(p).strip()]
        if repaired_paths:
            ctx.final_response = f"{str(getattr(ctx, 'final_response', '') or '').strip()}\nOnarım sonrası doğrulandı: {repaired_paths[0]}".strip()
    return {
        "repaired": bool(rechecked.get("ok", False)),
        "strategy": "taskspec_artifact_replay",
        "replayed_steps": ran_steps,
        "rechecked": rechecked,
    }


def _classify_taskspec_failure(task_contract: Dict[str, Any], *, action: str) -> str:
    failed = [str(x).strip() for x in list((task_contract or {}).get("failed") or []) if str(x).strip()]
    artifact_markers = ("deliverable:", "document:missing_artifact", "document:empty_artifact", "criteria:artifact_")
    if any(any(marker in item for marker in artifact_markers) for item in failed):
        return "planning_failure"
    return classify_failure_class(reason=", ".join(failed), action=action, payload=task_contract if isinstance(task_contract, dict) else {})


def _build_code_quality_gate_plan(*, produced_paths: List[str], failed_gates: List[str]) -> Dict[str, Any]:
    gates = [str(x).strip().lower() for x in (failed_gates or []) if str(x).strip()]
    paths = [str(p).strip() for p in (produced_paths or []) if str(p).strip()]
    suffixes = {Path(p).suffix.lower() for p in paths}

    commands: list[str] = []
    stack = "generic"
    if suffixes & {".py"}:
        stack = "python"
        if "lint" in gates:
            commands.append("ruff check .")
        if "smoke" in gates:
            commands.append("python -m pytest -q")
        if "typecheck" in gates:
            commands.append("mypy .")
    elif suffixes & {".ts", ".tsx", ".js", ".jsx"}:
        stack = "node"
        if "lint" in gates:
            commands.append("npm run lint")
        if "smoke" in gates:
            commands.append("npm test -- --runInBand")
        if "typecheck" in gates:
            commands.append("npm run typecheck")
    elif suffixes & {".go"}:
        stack = "go"
        if "lint" in gates:
            commands.append("go vet ./...")
        if "smoke" in gates:
            commands.append("go test ./...")
    elif suffixes & {".rs"}:
        stack = "rust"
        if "lint" in gates:
            commands.append("cargo clippy -- -D warnings")
        if "smoke" in gates:
            commands.append("cargo test")
    else:
        if "lint" in gates:
            commands.append("run project lint command")
        if "smoke" in gates:
            commands.append("run project test command")
        if "typecheck" in gates:
            commands.append("run project typecheck command")

    commands = [cmd for i, cmd in enumerate(commands) if cmd and cmd not in commands[:i]]
    return {
        "stack": stack,
        "failed_gates": gates,
        "commands": commands,
        "repairable": bool(commands),
    }


def _build_research_recovery_plan(
    *,
    failed_gates: List[str],
    source_urls: List[str],
    payload_errors: List[str],
) -> Dict[str, Any]:
    gates = [str(x).strip().lower() for x in (failed_gates or []) if str(x).strip()]
    payload_errs = [str(x).strip() for x in (payload_errors or []) if str(x).strip()]
    steps: list[str] = []
    if "sources" in gates:
        steps.append("En az 3 güvenilir kaynak ekle")
    if "claim_mapping" in gates:
        steps.append("Ana iddiaları kaynaklarla eşle")
    if "unknowns" in gates:
        steps.append("Belirsizlikler ve sınırlılıklar bölümü ekle")
    if "claim_coverage" in gates:
        steps.append("Her ana paragrafı en az bir claim ile ilişkilendir")
    if "critical_claim_coverage" in gates:
        steps.append("Kritik iddialar için ikinci bağımsız kaynak ekle")
    if "uncertainty_section" in gates:
        steps.append("Belirsizlikler veya açık riskler bölümünü görünür kıl")
    if any(item.startswith("payload:") for item in gates) or payload_errs:
        steps.append("Yapısal research payload üret ve doğrula")
    steps = [item for i, item in enumerate(steps) if item not in steps[:i]]
    return {
        "failed_gates": gates,
        "source_count": len([str(x).strip() for x in (source_urls or []) if str(x).strip()]),
        "payload_errors": payload_errs,
        "steps": steps,
        "repairable": bool(steps),
    }


def _evaluate_completion_gate(ctx) -> Dict[str, Any]:
    action = _normalize_action(getattr(ctx, "action", ""))
    final_response = str(getattr(ctx, "final_response", "") or "")
    errors = [str(e) for e in list(getattr(ctx, "errors", []) or [])]
    tool_results = [r for r in list(getattr(ctx, "tool_results", []) or []) if isinstance(r, dict)]

    non_actionable = {"", "chat", "unknown", "communication", "answer", "respond", "show_help"}
    if action in non_actionable:
        return {"ok": True, "failed": [], "signals": {"actionable": False}}

    failed: list[str] = []
    low_err = " ".join(errors).lower()
    if "timeout" in low_err or "zaman asimi" in low_err or "zaman aşımı" in low_err:
        failed.append("timeout")

    if _looks_execution_failure_text(final_response):
        failed.append("error_text")

    has_tool_success = _has_successful_tool_result(tool_results)
    if action in AVAILABLE_TOOLS and not has_tool_success:
        failed.append("no_successful_tool_result")

    if action in {"screen_workflow", "analyze_screen"}:
        if not _extract_screen_summary_signals(tool_results, final_response):
            failed.append("missing_screen_summary")

    write_like_actions = {
        "write_file",
        "write_word",
        "write_excel",
        "create_web_project_scaffold",
        "create_software_project_pack",
        "research_document_delivery",
    }
    if action in write_like_actions:
        produced_paths = collect_paths_from_tool_results(tool_results)
        if not produced_paths:
            failed.append("missing_artifacts")

    failed = sorted(set(failed))
    return {
        "ok": len(failed) == 0,
        "failed": failed,
        "signals": {
            "actionable": True,
            "has_tool_success": bool(has_tool_success),
            "tool_result_count": len(tool_results),
        },
    }


def _job_type_from_action(action: str, current: str) -> str:
    cur = str(current or "communication").strip().lower() or "communication"
    act = _normalize_action(action)
    if act in {"screen_workflow", "analyze_screen", "take_screenshot", "vision_operator_loop", "operator_mission_control", "computer_use"}:
        return "system_automation"
    if cur != "communication":
        return cur
    if act in {
        "set_wallpaper",
        "take_screenshot",
        "analyze_screen",
        "capture_region",
        "open_app",
        "close_app",
        "type_text",
        "press_key",
        "key_combo",
        "mouse_move",
        "mouse_click",
        "computer_use",
    }:
        return "system_automation"
    if act in {"http_request", "api_health_check", "graphql_query", "api_health_get_save"}:
        return "api_integration"
    if act in {
        "multi_task",
        "filesystem_batch",
        "write_file",
        "read_file",
        "create_folder",
        "list_files",
        "edit_text_file",
        "batch_edit_text",
        "edit_word_document",
        "summarize_document",
        "analyze_document",
    }:
        return "file_operations"
    if act in {"create_coding_project", "create_software_project_pack", "debug_code"}:
        return "code_project"
    return cur


def _iter_nested_strings(value: Any, *, _depth: int = 0):
    """Yield string leaves from nested dict/list payloads (depth-limited)."""
    if _depth > 4:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_nested_strings(item, _depth=_depth + 1)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_nested_strings(item, _depth=_depth + 1)


def _collect_urls(*payloads: Any) -> List[str]:
    urls: List[str] = []
    seen: set[str] = set()
    for payload in payloads:
        for text in _iter_nested_strings(payload):
            for hit in re.findall(r"https?://[^\s)>\]\"']+", text):
                url = str(hit).strip().rstrip(".,;")
                if not url or url in seen:
                    continue
                seen.add(url)
                urls.append(url)
    return urls


def _is_research_task(ctx) -> bool:
    action = _normalize_action(getattr(ctx, "action", ""))
    if "research" in action:
        return True
    job = str(getattr(ctx, "job_type", "") or "").strip().lower()
    if job in {"data_analysis", "research"}:
        return True
    low = str(getattr(ctx, "user_input", "") or "").lower()
    return any(tok in low for tok in ("araştır", "arastir", "research", "literatür", "literatur", "makale"))


def _has_marker(text: str, markers: tuple[str, ...]) -> bool:
    low = str(text or "").lower()
    return any(m in low for m in markers)


def _detect_code_quality_signals(ctx) -> Dict[str, Any]:
    text_blob = "\n".join(
        part for part in [str(getattr(ctx, "final_response", "") or ""), str(getattr(ctx, "llm_response", "") or "")]
        if part
    )
    tool_blob = " ".join(_iter_nested_strings(getattr(ctx, "tool_results", [])))
    combined = f"{text_blob}\n{tool_blob}".lower()
    signals = {
        "tests": _has_marker(combined, ("pytest", "unit test", "tests passed", "test passed", "smoke test", "testler geçti", "testler gecti", "✅ test")),
        "lint": _has_marker(combined, ("lint", "ruff", "flake8", "eslint", "pylint", "biome")),
        "typecheck": _has_marker(combined, ("typecheck", "type check", "mypy", "pyright", "tsc", "type-safe", "tip kontrol")),
    }
    signals["missing"] = [k for k in ("tests", "lint", "typecheck") if not signals.get(k)]
    return signals


def _format_research_contract_addendum(ctx) -> Dict[str, Any]:
    text = str(getattr(ctx, "final_response", "") or "")
    has_sources_section = _has_marker(text, ("kaynaklar:", "sources:", "references:"))
    has_confidence_section = _has_marker(text, ("güven skoru", "confidence", "trust score"))
    has_risk_section = _has_marker(text, ("açık risk", "acik risk", "riskler", "risks"))
    has_uncertainty_section = _has_marker(text, ("belirsizlik", "uncertainty", "sınırlılık", "sinirlilik"))

    research_payload = _extract_research_payload(getattr(ctx, "tool_results", []))
    quality_summary = research_payload.get("quality_summary") if isinstance(research_payload, dict) and isinstance(research_payload.get("quality_summary"), dict) else {}

    urls = _collect_urls(text, getattr(ctx, "tool_results", []))
    source_rows = [f"- {u}" for u in urls[:5]]
    source_count = len(urls)
    auto_conf = max(0.35, min(0.9, 0.35 + (0.1 * min(5, source_count))))

    missing: List[str] = []
    addendum_parts: List[str] = []

    if not has_sources_section:
        missing.append("sources")
        if source_rows:
            addendum_parts.append("Kaynaklar:")
            addendum_parts.extend(source_rows)

    if not has_confidence_section:
        missing.append("confidence")
        if quality_summary:
            addendum_parts.append(
                f"Güven skoru (otomatik): %{int(round(float(quality_summary.get('avg_reliability', auto_conf) or auto_conf) * 100))}"
            )
        else:
            addendum_parts.append(f"Güven skoru (otomatik): %{int(round(auto_conf * 100))}")

    if not has_risk_section:
        missing.append("risks")
        addendum_parts.append("Açık riskler:")
        if quality_summary and float(quality_summary.get("critical_claim_coverage", 1.0) or 1.0) < 1.0:
            addendum_parts.append("- Bazı kritik iddialar ikinci bağımsız kaynakla doğrulanamadı.")
        else:
            addendum_parts.append("- Bazı kaynaklar güncellik/doğruluk açısından manuel teyit gerektirebilir.")

    if not has_uncertainty_section:
        missing.append("uncertainty")
        addendum_parts.append("Belirsizlikler:")
        uncertainty_count = int(quality_summary.get("uncertainty_count", 0) or 0) if quality_summary else 0
        if uncertainty_count > 0:
            addendum_parts.append(f"- Yapısal doğrulamada {uncertainty_count} belirsizlik kaydı bulundu.")
        else:
            addendum_parts.append("- Belirgin belirsizlik kaydı görünmüyor; yine de kritik sayısal iddialar manuel teyit gerektirir.")

    if quality_summary:
        addendum_parts.append(
            f"Kritik claim coverage: %{int(round(float(quality_summary.get('critical_claim_coverage', 0.0) or 0.0) * 100))}"
        )
        addendum_parts.append(
            f"Claim coverage: %{int(round(float(quality_summary.get('claim_coverage', 0.0) or 0.0) * 100))}"
        )

    addendum_text = ""
    if addendum_parts:
        addendum_text = "\n\nAraştırma kalite özeti:\n" + "\n".join(addendum_parts)

    return {
        "missing": missing,
        "sources_found": source_count,
        "confidence_estimate": round(auto_conf, 2),
        "addendum": addendum_text,
    }


def _extract_research_payload(tool_results: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    for row in reversed(tool_results or []):
        if not isinstance(row, dict):
            continue
        if isinstance(row.get("research_contract"), dict):
            payload = dict(row.get("research_contract") or {})
            if isinstance(row.get("quality_summary"), dict):
                payload["quality_summary"] = dict(row.get("quality_summary") or {})
            if str(row.get("claim_map_path") or "").strip():
                payload["claim_map_path"] = str(row.get("claim_map_path") or "").strip()
            if str(row.get("revision_summary_path") or "").strip():
                payload["revision_summary_path"] = str(row.get("revision_summary_path") or "").strip()
            return payload
        result = row.get("result")
        if isinstance(result, dict) and isinstance(result.get("research_contract"), dict):
            payload = dict(result.get("research_contract") or {})
            if isinstance(result.get("quality_summary"), dict):
                payload["quality_summary"] = dict(result.get("quality_summary") or {})
            if str(result.get("claim_map_path") or "").strip():
                payload["claim_map_path"] = str(result.get("claim_map_path") or "").strip()
            if str(result.get("revision_summary_path") or "").strip():
                payload["revision_summary_path"] = str(result.get("revision_summary_path") or "").strip()
            return payload
    return None


async def _try_llm_intent_rescue(ctx, agent, *, min_confidence: float = 0.62) -> bool:
    if _normalize_action(getattr(ctx, "action", "")) not in _NON_ACTIONABLE_INTENTS:
        return False
    if not _looks_actionable_input(getattr(ctx, "user_input", ""), getattr(ctx, "attachments", None)):
        return False
    infer = getattr(agent, "_infer_llm_tool_intent", None)
    if not callable(infer):
        return False
    history = []
    try:
        mem = str(getattr(ctx, "memory_context", "") or "").strip()
        if mem:
            history = [{"role": "system", "content": f"Conversation memory (kısa bağlam): {mem[:600]}"}]
    except Exception:
        history = []
    try:
        inferred = await infer(ctx.user_input, history=history, user_id=ctx.user_id)
    except Exception:
        return False

    strict_json_envelope = flag_enabled(ctx, "upgrade_intent_json_envelope", default=False)
    envelope = parse_llm_intent_envelope(inferred) if strict_json_envelope else None
    if strict_json_envelope:
        if envelope is None:
            return False
        inferred = dict(envelope.intent or {})
        if not isinstance(inferred, dict):
            return False
        inferred["confidence"] = float(envelope.confidence)
        inferred["required_artifacts"] = list(envelope.required_artifacts)
        inferred["tools_needed"] = list(envelope.tools_needed)
        inferred["safety_flags"] = list(envelope.safety_flags)
        inferred["assumptions"] = list(envelope.assumptions)
    elif not isinstance(inferred, dict):
        return False

    action = _normalize_action(inferred.get("action"))
    if action in _NON_ACTIONABLE_INTENTS:
        return False
    confidence = float(inferred.get("confidence", 0.0) or 0.0)
    if confidence < max(0.0, min(1.0, float(min_confidence or 0.62))):
        return False
    ctx.intent = inferred
    ctx.action = action
    ctx.job_type = _job_type_from_action(ctx.action, getattr(ctx, "job_type", "communication"))
    if strict_json_envelope:
        ctx.required_artifacts = list(inferred.get("required_artifacts") or [])
        ctx.tools_needed = list(inferred.get("tools_needed") or [])
        ctx.safety_flags = list(inferred.get("safety_flags") or [])
        ctx.assumptions = list(inferred.get("assumptions") or [])
    logger.info("Route rescue via LLM intent: action=%s c=%.2f", ctx.action, confidence)
    return True


def _run_dir(ctx: Any) -> str:
    policy = getattr(ctx, "runtime_policy", {}) if isinstance(getattr(ctx, "runtime_policy", {}), dict) else {}
    metadata = policy.get("metadata", {}) if isinstance(policy.get("metadata"), dict) else {}
    value = str(metadata.get("run_dir") or "").strip()
    if value:
        return value
    return str(Path.home() / ".elyan" / "runs" / f"pipeline-{int(time.time())}")


def _workflow_policy_snapshot(ctx: Any) -> Dict[str, Any]:
    policy = getattr(ctx, "runtime_policy", {}) if isinstance(getattr(ctx, "runtime_policy", {}), dict) else {}
    workflow_cfg = policy.get("workflow", {}) if isinstance(policy.get("workflow"), dict) else {}
    metadata = policy.get("metadata", {}) if isinstance(policy.get("metadata"), dict) else {}
    workflow_session = metadata.get("workflow_session", {}) if isinstance(metadata.get("workflow_session"), dict) else {}
    return {
        "profile": normalize_workflow_profile(metadata.get("workflow_profile") or workflow_cfg.get("profile")),
        "allowed_domains": list(workflow_cfg.get("allowed_domains") or []),
        "require_explicit_approval": bool(workflow_cfg.get("require_explicit_approval", True)),
        "workspace_policy": str(workflow_cfg.get("workspace_policy") or "auto"),
        "session": workflow_session,
    }


def _sync_workflow_metadata(ctx: Any) -> None:
    policy = getattr(ctx, "runtime_policy", {}) if isinstance(getattr(ctx, "runtime_policy", {}), dict) else {}
    metadata = policy.get("metadata", {}) if isinstance(policy.get("metadata"), dict) else {}
    metadata["workflow_profile"] = str(getattr(ctx, "workflow_profile", "") or "")
    metadata["workflow_phase"] = str(getattr(ctx, "workflow_phase", "") or "")
    metadata["approval_status"] = str(getattr(ctx, "approval_status", "") or "")
    metadata["capability_domain"] = str(getattr(ctx, "capability_domain", "") or "")
    metadata["workflow_id"] = str(getattr(ctx, "workflow_id", "") or "")
    metadata["execution_route"] = str(getattr(ctx, "execution_route", "") or "")
    metadata["autonomy_mode"] = str(getattr(ctx, "autonomy_mode", "") or "")
    metadata["autonomy_policy"] = str(getattr(ctx, "autonomy_policy", "") or "")
    metadata["orchestration_decision_path"] = list(getattr(ctx, "orchestration_decision_path", []) or [])
    if getattr(ctx, "workflow_session_id", ""):
        metadata["workflow_session_id"] = str(ctx.workflow_session_id)
    if isinstance(getattr(ctx, "workflow_artifacts", {}), dict) and ctx.workflow_artifacts:
        metadata["workflow_artifacts"] = dict(ctx.workflow_artifacts)
    policy["metadata"] = metadata
    ctx.runtime_policy = policy


def _apply_workflow_profile(ctx: Any) -> None:
    snapshot = _workflow_policy_snapshot(ctx)
    profile = str(snapshot.get("profile") or "default")
    session = snapshot.get("session") if isinstance(snapshot.get("session"), dict) else {}
    if session and approval_granted(getattr(ctx, "user_input", "")):
        ctx.user_input = str(session.get("objective") or ctx.user_input)
        ctx.workflow_session_id = str(session.get("session_id") or "")
        ctx.approval_status = "approved"
        ctx.workflow_phase = "approved"
    allowed_domains = snapshot.get("allowed_domains") if isinstance(snapshot.get("allowed_domains"), list) else []
    ctx.workflow_profile = profile
    ctx.requires_design_phase = profile_applicable(profile, getattr(ctx, "capability_domain", ""), allowed_domains)
    ctx.requires_worktree = bool(
        getattr(ctx, "capability_plan", {}).get("requires_worktree")
        if isinstance(getattr(ctx, "capability_plan", {}), dict)
        else False
    )
    if ctx.requires_design_phase and ctx.approval_status == "not_required":
        ctx.approval_status = "pending"
    if ctx.requires_design_phase and ctx.workflow_phase == "intake":
        ctx.workflow_phase = "brainstorming"
    _sync_workflow_metadata(ctx)


def _persist_workflow_artifact(ctx: Any, *, key: str, path: str) -> None:
    path_str = str(path or "").strip()
    if not path_str:
        return
    if not isinstance(getattr(ctx, "workflow_artifacts", {}), dict):
        ctx.workflow_artifacts = {}
    ctx.workflow_artifacts[str(key)] = path_str
    _sync_workflow_metadata(ctx)


def _ensure_design_artifact(ctx: Any) -> str:
    existing = str((getattr(ctx, "workflow_artifacts", {}) or {}).get("design_artifact_path") or "").strip()
    if existing:
        return existing
    nexus_mode = infer_nexus_mode(
        complexity=float(getattr(ctx, "complexity", 0.0) or 0.0),
        goal_stage_count=int(getattr(ctx, "goal_stage_count", 1) or 1),
        plan_length=len(list(getattr(ctx, "plan", []) or [])),
    )
    design_md = render_design_markdown(
        objective=str(getattr(ctx, "user_input", "") or ""),
        domain=str(getattr(ctx, "capability_domain", "general") or "general"),
        workflow_profile=str(getattr(ctx, "workflow_profile", "default") or "default"),
        workflow_id=str(getattr(ctx, "workflow_id", "") or ""),
        nexus_mode=nexus_mode,
        capability_plan=dict(getattr(ctx, "capability_plan", {}) or {}),
    )
    path = write_text_artifact(_run_dir(ctx), "artifacts/design.txt", design_md)
    _persist_workflow_artifact(ctx, key="design_artifact_path", path=path)
    return path


def _ensure_plan_and_workspace_artifacts(ctx: Any) -> None:
    if not getattr(ctx, "requires_design_phase", False):
        return
    nexus_mode = infer_nexus_mode(
        complexity=float(getattr(ctx, "complexity", 0.0) or 0.0),
        goal_stage_count=int(getattr(ctx, "goal_stage_count", 1) or 1),
        plan_length=len(list(getattr(ctx, "plan", []) or [])),
    )
    process_profile = get_process_profile(str(getattr(ctx, "workflow_profile", "default") or "default"), nexus_mode=nexus_mode)
    packets = build_task_packets(
        objective=str(getattr(ctx, "user_input", "") or ""),
        plan=list(getattr(ctx, "plan", []) or []),
        workflow_id=str(getattr(ctx, "workflow_id", "") or ""),
        nexus_mode=process_profile.nexus_mode,
    )
    ctx.task_packets = [packet.to_dict() for packet in packets]
    plan_md = render_plan_markdown(
        objective=str(getattr(ctx, "user_input", "") or ""),
        packets=packets,
        nexus_mode=process_profile.nexus_mode,
    )
    plan_md_path = write_text_artifact(_run_dir(ctx), "artifacts/implementation_plan.txt", plan_md)
    plan_json_path = write_json_artifact(
        _run_dir(ctx),
        "artifacts/implementation_plan.json",
        {
            "workflow_profile": process_profile.id,
            "nexus_mode": process_profile.nexus_mode,
            "task_packets": [packet.to_dict() for packet in packets],
        },
    )
    workspace_info = inspect_workspace(
        current_dir=str(Path.cwd()),
        profile=str(getattr(ctx, "workflow_profile", "default") or "default"),
        run_dir=_run_dir(ctx),
    )
    ctx.workspace_mode = str(workspace_info.get("workspace_mode") or "")
    ctx.workspace_path = str(workspace_info.get("isolated_workspace") or getattr(ctx, "workspace_path", ""))
    _persist_workflow_artifact(ctx, key="plan_artifact_path", path=plan_md_path)
    _persist_workflow_artifact(ctx, key="plan_json_artifact_path", path=plan_json_path)
    _persist_workflow_artifact(ctx, key="workspace_report_path", path=str(workspace_info.get("workspace_report_path") or ""))
    _persist_workflow_artifact(ctx, key="baseline_check_path", path=str(workspace_info.get("baseline_check_path") or ""))


def _ensure_review_artifact(ctx: Any) -> str:
    existing = str((getattr(ctx, "workflow_artifacts", {}) or {}).get("review_artifact_path") or "").strip()
    if existing:
        return existing
    report = render_review_report(
        outputs=[row for row in list(getattr(ctx, "tool_results", []) or []) if isinstance(row, dict)],
        notes=list(((getattr(ctx, "telemetry", {}) if isinstance(getattr(ctx, "telemetry", {}), dict) else {}).get("review_notes", [])) or []),
        review_status=str(getattr(ctx, "approval_status", "") or "pending"),
    )
    path = write_text_artifact(_run_dir(ctx), "artifacts/review_report.txt", report)
    _persist_workflow_artifact(ctx, key="review_artifact_path", path=path)
    return path


def _ensure_finish_branch_artifact(ctx: Any) -> str:
    existing = str((getattr(ctx, "workflow_artifacts", {}) or {}).get("finish_branch_report_path") or "").strip()
    if existing:
        return existing
    report = render_finish_branch_report(
        workflow_profile=str(getattr(ctx, "workflow_profile", "default") or "default"),
        workspace_mode=str(getattr(ctx, "workspace_mode", "") or ""),
        verified=bool(getattr(ctx, "verified", False) and not getattr(ctx, "delivery_blocked", False)),
        errors=list(getattr(ctx, "errors", []) or []),
    )
    path = write_text_artifact(_run_dir(ctx), "artifacts/finish_branch_report.txt", report)
    _persist_workflow_artifact(ctx, key="finish_branch_report_path", path=path)
    return path


def _workflow_brainstorm_response(ctx: Any) -> str:
    design_path = _ensure_design_artifact(ctx)
    ctx.workflow_phase = "design_ready"
    _sync_workflow_metadata(ctx)
    return (
        "Superpowers workflow aktif. Kod yazmadan önce tasarımı netleştiriyorum.\n"
        "Design artifact oluşturuldu ve approval bekleniyor.\n"
        f"- design: {design_path}\n"
        "Devam etmek için `onay`, `go`, `uygula`, `implement`, veya `devam et` yaz."
    )


@dataclass
class PipelineContext:
    """Pipeline boyunca taşınan paylaşımlı bağlam."""
    # Input
    user_input: str = ""
    channel: str = "cli"
    user_id: str = "unknown"

    # Stage 1: Validate & Pre-checks
    is_valid: bool = True
    validation_error: str = ""
    status_prefix: str = ""
    quota_limited: bool = False

    # Stage 2: Route & Context Intel
    role: str = "inference"
    model: str = ""
    provider: str = ""
    complexity: float = 0.3
    reasoning_budget: str = "low"
    intent: Dict = field(default_factory=dict)
    action: str = ""
    job_type: str = "communication"
    context_docs: str = ""
    specialized_prompt: str = ""
    op_domain: str = ""
    capability_domain: str = "general"
    capability_confidence: float = 0.0
    capability_plan: Dict[str, Any] = field(default_factory=dict)
    workflow_id: str = ""
    capability_primary_action: str = ""
    workflow_profile: str = "default"
    workflow_phase: str = "intake"
    approval_status: str = "not_required"
    execution_route: str = ""
    autonomy_mode: str = ""
    autonomy_policy: str = ""
    orchestration_decision_path: List[str] = field(default_factory=list)
    requires_design_phase: bool = False
    requires_worktree: bool = False
    workflow_artifacts: Dict[str, str] = field(default_factory=dict)
    workflow_session_id: str = ""
    workspace_mode: str = ""
    preferred_tools: List[str] = field(default_factory=list)
    multi_agent_recommended: bool = False
    goal_graph: Dict[str, Any] = field(default_factory=dict)
    goal_stage_count: int = 1
    goal_complexity: float = 0.0
    goal_constraints: Dict[str, Any] = field(default_factory=dict)
    workflow_chain: List[str] = field(default_factory=list)
    requires_evidence: bool = False
    intent_score: float = 0.0
    intent_reasons: List[str] = field(default_factory=list)
    required_artifacts: List[str] = field(default_factory=list)
    tools_needed: List[str] = field(default_factory=list)
    safety_flags: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    context_fingerprint: str = ""
    context_working_set: str = ""
    attachment_index: List[Dict[str, Any]] = field(default_factory=list)
    model_route: Dict[str, Any] = field(default_factory=dict)
    model_roles: Dict[str, Any] = field(default_factory=dict)
    workspace_path: str = ""
    workspace_files: Dict[str, str] = field(default_factory=dict)
    understand_phase: Dict[str, Any] = field(default_factory=dict)
    phase_records: Dict[str, Any] = field(default_factory=dict)
    output_contract_spec: Dict[str, Any] = field(default_factory=dict)
    world_snapshot: Dict[str, Any] = field(default_factory=dict)

    # Stage 3: Plan
    plan: List[Dict] = field(default_factory=list)
    task_packets: List[Dict[str, Any]] = field(default_factory=list)
    skeleton_plan: List[Dict[str, Any]] = field(default_factory=list)
    step_specs: List[Dict[str, Any]] = field(default_factory=list)
    plan_cache_hit: bool = False
    needs_planning: bool = False
    needs_reasoning: bool = False
    is_code_job: bool = False

    # Stage 4: Execute
    llm_response: str = ""
    tool_results: List[Dict] = field(default_factory=list)
    tool_calls: List[Dict] = field(default_factory=list)

    # Stage 5: Verify
    verified: bool = False
    qa_results: Dict = field(default_factory=dict)
    contract: Optional[Any] = None

    # Stage 6: Deliver
    final_response: str = ""
    evidence_valid: bool = True
    delivery_blocked: bool = False

    # Memory Tracking
    memory_context: str = ""
    memory_results: Dict = field(default_factory=dict)

    # Phase 19: Multimodal Tracking
    raw_attachments: List[Dict[str, Any]] = field(default_factory=list)
    attachments: List[str] = field(default_factory=list)
    multimodal_context: str = ""
    is_multimodal: bool = False
    team_mode_forced: bool = False
    runtime_policy: Dict[str, Any] = field(default_factory=dict)

    # Metadata
    started_at: float = field(default_factory=time.time)
    telemetry: Dict[str, Any] = field(default_factory=dict)
    stage_timings: Dict[str, float] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


class PipelineStage:
    """Base class for pipeline stages."""
    name: str = "base"

    async def run(self, ctx: PipelineContext, agent) -> PipelineContext:
        raise NotImplementedError


class StageValidate(PipelineStage):
    """Stage 1: Input validation."""
    name = "validate"

    async def run(self, ctx: PipelineContext, agent) -> PipelineContext:
        t0 = time.time()
        user_input = ctx.user_input.strip()
        ensure_runtime_trace(ctx)
        update_runtime_trace(ctx, delivery_mode=str(ctx.channel or "cli"))

        if not user_input:
            ctx.is_valid = False
            ctx.validation_error = "Boş girdi"
            ctx.final_response = "Bir şey yazmalısın."
            update_runtime_trace(ctx, final_status="rejected")
        elif len(user_input) > 50000:
            ctx.is_valid = False
            ctx.validation_error = "Çok uzun girdi"
            ctx.final_response = "Mesaj çok uzun (max 50K karakter)."
            update_runtime_trace(ctx, final_status="rejected")
            
        # 0. Quota Check
        from core.quota import quota_manager
        quota = quota_manager.check_quota(ctx.user_id)
        if not quota.get("allowed", True):
            ctx.is_valid = False
            ctx.quota_limited = True
            limit_msg = f"\n\nGünlük mesaj sınırına ulaştın ({quota.get('limit')} mesaj). Devam etmek için Pro plana geçebilirsin."
            if quota.get("reason") == "monthly_token_limit_reached":
                limit_msg = f"\n\nAylık token sınırına ulaştın ({quota.get('limit')} token). Devam etmek için Pro plana geçebilirsin."
            ctx.final_response = f"Üzgünüm, {limit_msg}"
            update_runtime_trace(ctx, final_status="quota_blocked")
            return ctx
            
        # 1. Action-Lock Check
        from core.action_lock import action_lock
        ctx.status_prefix = action_lock.get_status_prefix()
        if action_lock.is_locked:
            if any(kw in user_input.lower() for kw in ["dur", "iptal", "cancel", "stop"]):
                action_lock.unlock()
                ctx.is_valid = False
                ctx.final_response = "Üretim modu durduruldu ve kilit açıldı."
                update_runtime_trace(ctx, final_status="cancelled")
                return ctx
            ctx.is_valid = False
            ctx.final_response = f"{ctx.status_prefix}Şu an bir göreve odaklanmış durumdayım. İptal etmek için 'iptal' yazabilirsin."
            update_runtime_trace(ctx, final_status="action_locked")
            return ctx

        # Security validation
        if ctx.is_valid and hasattr(agent, '_validate_input'):
            try:
                result = agent._validate_input(user_input)
                if isinstance(result, str):
                    ctx.is_valid = False
                    ctx.final_response = result
            except Exception:
                pass

        ctx.stage_timings["validate"] = time.time() - t0
        return ctx


class StageRoute(PipelineStage):
    """Stage 2: Neural routing + intent parsing + job type detection."""
    name = "route"

    async def run(self, ctx: PipelineContext, agent) -> PipelineContext:
        t0 = time.time()

        # Phase 19: Multimodal Attachment Detection
        import re
        inbound_paths: list[str] = []
        if isinstance(ctx.raw_attachments, list):
            for raw in ctx.raw_attachments:
                if not isinstance(raw, dict):
                    continue
                p = str(raw.get("path") or raw.get("file_path") or raw.get("local_path") or "").strip()
                if p:
                    inbound_paths.append(p)

        if "attach:" in ctx.user_input:
            matches = re.findall(r"attach:([^\s,]+)", ctx.user_input)
            if matches:
                inbound_paths.extend(matches)
                ctx.user_input = re.sub(r"attach:[^\s,]+", "", ctx.user_input).strip()

        if inbound_paths:
            deduped = list(dict.fromkeys([str(p).strip() for p in inbound_paths if str(p).strip()]))
            if deduped:
                ctx.attachments = list(dict.fromkeys([*ctx.attachments, *deduped]))
                ctx.is_multimodal = True

                # Upgrade path: attachment indexer runs before multimodal inference.
                if flag_enabled(ctx, "upgrade_attachment_indexer", default=False):
                    try:
                        ctx.attachment_index = index_attachments(ctx.attachments)
                    except Exception as idx_exc:
                        logger.debug(f"Attachment index skipped: {idx_exc}")

                from core.multimodal_processor import get_multimodal_processor

                processor = get_multimodal_processor()
                mm_reports = []
                for path in deduped:
                    logger.info(f"Processing multimodal attachment: {path}")
                    res = await processor.process_file(path)
                    if res.get("success"):
                        if "transcription" in res:
                            mm_reports.append(f"[Audio: {res['transcription']}]")
                        elif "description" in res:
                            mm_reports.append(f"[Image: {res['description']}]")
                        elif "analysis" in res:
                            mm_reports.append(f"[Analysis: {res['analysis']}]")

                ctx.multimodal_context = "\n".join(mm_reports)
                logger.info(f"Multimodal context generated: {len(mm_reports)} items")

        # Phase 20: Natural Language Cron Detection
        try:
            from core.nl_cron import nl_cron
            from core.automation_registry import automation_registry
            cron_task = nl_cron.parse(ctx.user_input)
            if cron_task:
                import uuid
                task_id = str(uuid.uuid4())[:8]
                automation_registry.register(task_id, {
                    "id": task_id,
                    "cron": cron_task.get("cron"),
                    "rrule": cron_task.get("rrule"),
                    "task": cron_task["original_task"],
                    "user_id": ctx.user_id,
                    "channel": ctx.channel
                })
                ctx.role = "automation_reg"
                rrule = cron_task.get("rrule") or cron_task.get("cron")
                ctx.final_response = f"✅ Otomasyon kaydedildi (ID: {task_id}). {rrule} zamanında '{cron_task['original_task']}' işlemini yapacağım."
                ctx.delivery_blocked = False # Allow bypass to delivery
                logger.info(f"Automation registered via NL: {task_id}")
                return ctx # Early exit for registration
        except Exception as e:
            logger.error(f"NL Cron detection error: {e}")

        # Phase 17: Unified Memory Retrieval
        try:
            from core.memory.unified import memory
            from core.memory.context_optimizer import context_optimizer
            
            ctx.memory_results = await memory.recall(ctx.user_id, ctx.user_input)
            ctx.memory_context = context_optimizer.optimize(ctx.memory_results, ctx.user_input)
            logger.info(f"Memory context retrieved ({len(ctx.memory_context)} chars)")
        except Exception as e:
            logger.debug(f"Memory retrieval skip: {e}")

        # Upgrade path: deterministic intent score + compact working context.
        if flag_enabled(ctx, "upgrade_intent_hardening", default=False):
            try:
                score = deterministic_intent_score(
                    ctx.user_input,
                    memory_context=ctx.memory_context,
                    attachments=ctx.attachments,
                )
                ctx.intent_score = float(score.score)
                ctx.intent_reasons = list(score.reasons)
            except Exception:
                pass

        # Context7 Injection Check
        if "use context7" in ctx.user_input.lower():
            try:
                from core.context7_client import context7_client
                tech = "React" if "react" in ctx.user_input.lower() else "Python"
                ctx.context_docs = await context7_client.fetch_docs(tech)
                ctx.user_input = ctx.user_input.replace("use context7", "").strip()
                logger.info(f"Context7 docs injected for {tech}")
            except Exception as e:
                logger.error(f"Context7 error: {e}")

        # Context Intelligence - Dynamic Morphing
        try:
            from core.context_intelligence import get_context_intelligence
            ctx_intel = get_context_intelligence()
            op_context = ctx_intel.detect(ctx.user_input)
            ctx.specialized_prompt = ctx_intel.get_specialized_prompt(op_context)
            ctx.op_domain = op_context["domain"]
            logger.info(f"Operation Context: {ctx.op_domain}")
        except Exception:
            pass

        # Neural routing
        try:
            from core.neural_router import neural_router
            route = neural_router.route(ctx.user_input)
            ctx.role = route["role"]
            ctx.model = route["model"]
            ctx.provider = route["provider"]
            ctx.complexity = route["complexity"]
            ctx.reasoning_budget = route.get("reasoning_budget", "low")
        except Exception as e:
            ctx.errors.append(f"route: {e}")

        # Cognitive parsing: goal graph + constraints for complex instructions.
        try:
            from core.goal_graph import get_goal_graph_planner

            graph = get_goal_graph_planner().build(ctx.user_input)
            if isinstance(graph, dict):
                ctx.goal_graph = graph
                ctx.goal_stage_count = max(1, int(graph.get("stage_count", 1) or 1))
                ctx.goal_complexity = max(0.0, min(1.0, float(graph.get("complexity_score", 0.0) or 0.0)))
                ctx.goal_constraints = graph.get("constraints", {}) if isinstance(graph.get("constraints"), dict) else {}
                ctx.workflow_chain = list(graph.get("workflow_chain", []) or [])
                ctx.requires_evidence = bool(ctx.goal_constraints.get("requires_evidence", False))

                # Blend neural complexity with goal-graph complexity to better detect complex commands.
                if ctx.goal_complexity > 0.0:
                    ctx.complexity = max(float(ctx.complexity or 0.0), ctx.goal_complexity)
        except Exception as e:
            logger.debug(f"Goal graph parse skipped: {e}")

        # Job type detection
        try:
            from core.job_templates import detect_job_type
            ctx.job_type = detect_job_type(ctx.user_input)
        except Exception:
            ctx.job_type = "communication"

        # Hybrid AI routing: cheap/local router, strong workers for research/coding, tool-first operator.
        try:
            hybrid_plan = build_hybrid_model_plan(
                getattr(ctx, "capability_domain", ""),
                getattr(ctx, "workflow_id", ""),
                current_role=getattr(ctx, "role", "inference"),
            )
            ctx.hybrid_model = hybrid_plan.to_dict()
            ctx.role = str(hybrid_plan.role or ctx.role or "inference")
            if getattr(hybrid_plan, "tool_first", False):
                ctx.reasoning_budget = "low"
            from core.neural_router import neural_router

            model_cfg = neural_router.get_model_for_role(ctx.role)
            if isinstance(model_cfg, dict):
                ctx.provider = str(model_cfg.get("provider") or getattr(ctx, "provider", "") or "")
                ctx.model = str(model_cfg.get("model") or getattr(ctx, "model", "") or "")
        except Exception as e:
            logger.debug(f"Hybrid model routing skipped: {e}")

        # Cognitive graph can upgrade legacy "communication" routes into execution routes.
        try:
            if ctx.job_type == "communication" and ctx.goal_stage_count >= 2:
                delivery_domain = str(ctx.goal_graph.get("primary_delivery_domain", "") or "").strip().lower()
                domain_to_job = {
                    "building": "code_project",
                    "system": "system_automation",
                    "operations": "system_automation",
                    "api": "api_integration",
                    "research": "data_analysis",
                }
                mapped_job = domain_to_job.get(delivery_domain, "")
                if mapped_job:
                    ctx.job_type = mapped_job
        except Exception:
            pass

        capability_enabled = True
        capability_override_threshold = 0.5
        api_tools_enabled = True
        try:
            from config.elyan_config import elyan_config

            capability_enabled = bool(elyan_config.get("agent.capability_router.enabled", True))
            capability_override_threshold = float(
                elyan_config.get("agent.capability_router.min_confidence_override", 0.5) or 0.5
            )
            capability_override_threshold = max(0.0, min(1.0, capability_override_threshold))
            api_tools_enabled = bool(elyan_config.get("agent.api_tools.enabled", True))
        except Exception:
            pass
        try:
            policy = ctx.runtime_policy if isinstance(ctx.runtime_policy, dict) else {}
            cap_policy = policy.get("capability", {}) if isinstance(policy.get("capability"), dict) else {}
            api_policy = policy.get("api_tools", {}) if isinstance(policy.get("api_tools"), dict) else {}
            if "enabled" in cap_policy:
                capability_enabled = bool(cap_policy.get("enabled"))
            if "min_confidence_override" in cap_policy:
                capability_override_threshold = float(cap_policy.get("min_confidence_override") or capability_override_threshold)
            if "enabled" in api_policy:
                api_tools_enabled = bool(api_policy.get("enabled"))
            capability_override_threshold = max(0.0, min(1.0, capability_override_threshold))
        except Exception:
            pass

        # Capability routing (high-level domain + tool strategy)
        if capability_enabled:
            try:
                cap_router = getattr(agent, "capability_router", None)
                cap_plan = cap_router.route(ctx.user_input) if cap_router else None
                if cap_plan:
                    ctx.capability_domain = str(getattr(cap_plan, "domain", "general") or "general")
                    ctx.capability_confidence = float(getattr(cap_plan, "confidence", 0.0) or 0.0)
                    ctx.preferred_tools = list(getattr(cap_plan, "preferred_tools", []) or [])
                    ctx.multi_agent_recommended = bool(getattr(cap_plan, "multi_agent_recommended", False))
                    ctx.capability_plan = {
                        "domain": ctx.capability_domain,
                        "confidence": ctx.capability_confidence,
                        "objective": str(getattr(cap_plan, "objective", "") or ""),
                        "workflow_id": str(getattr(cap_plan, "workflow_id", "") or ""),
                        "primary_action": str(getattr(cap_plan, "primary_action", "") or ""),
                        "complexity_tier": str(getattr(cap_plan, "complexity_tier", "low") or "low"),
                        "suggested_job_type": str(getattr(cap_plan, "suggested_job_type", "communication") or "communication"),
                        "orchestration_mode": str(getattr(cap_plan, "orchestration_mode", "single_agent") or "single_agent"),
                        "workflow_profile_applicable": bool(getattr(cap_plan, "workflow_profile_applicable", False)),
                        "requires_design_phase": bool(getattr(cap_plan, "requires_design_phase", False)),
                        "requires_worktree": bool(getattr(cap_plan, "requires_worktree", False)),
                        "preferred_tools": list(ctx.preferred_tools),
                    }
                    ctx.workflow_id = str(getattr(cap_plan, "workflow_id", "") or "")
                    ctx.capability_primary_action = str(getattr(cap_plan, "primary_action", "") or "")

                    suggested_job = str(getattr(cap_plan, "suggested_job_type", "") or "").strip().lower()
                    if (
                        suggested_job
                        and suggested_job != "communication"
                        and ctx.job_type == "communication"
                        and ctx.capability_confidence >= capability_override_threshold
                    ):
                        ctx.job_type = suggested_job
            except Exception as e:
                logger.debug(f"Capability routing skipped: {e}")

        if ctx.job_type == "api_integration" and not api_tools_enabled:
            logger.warning("API tools are disabled by policy; routing task to communication fallback.")
            ctx.errors.append("api_tools_disabled")
            ctx.job_type = "communication"

        # Intent parsing
        if hasattr(agent, 'intent_parser'):
            try:
                ctx.intent = agent.intent_parser.parse(ctx.user_input)
                if isinstance(ctx.intent, dict):
                    ctx.action = str(ctx.intent.get("action", "")).lower()
                    ctx.job_type = _job_type_from_action(ctx.action, ctx.job_type)
            except Exception:
                pass

        # World model snapshot: deterministic bridge from memory -> plan context.
        try:
            from core.world_model import get_world_model

            ctx.world_snapshot = get_world_model().build_snapshot(
                user_id=ctx.user_id,
                query=ctx.user_input,
                goal_graph=ctx.goal_graph,
                memory_results=ctx.memory_results,
                action=ctx.action,
                job_type=ctx.job_type,
            )
            if isinstance(ctx.telemetry, dict):
                ctx.telemetry["world_model"] = {
                    "domains": list(ctx.world_snapshot.get("domains", []) or []),
                    "strategy_count": len(list(ctx.world_snapshot.get("strategy_hints", []) or [])),
                    "experience_hits": len(list(ctx.world_snapshot.get("similar_experiences", []) or [])),
                }
        except Exception as world_exc:
            logger.debug(f"World model snapshot skipped: {world_exc}")

        # Capability realignment: fix shallow/misaligned parser actions using high-confidence capability plan.
        try:
            parsed_conf = 0.0
            if isinstance(ctx.intent, dict):
                parsed_conf = float(ctx.intent.get("confidence", 0.0) or 0.0)
            if _should_realign_to_capability(
                user_input=ctx.user_input,
                action=ctx.action,
                capability_domain=ctx.capability_domain,
                capability_confidence=ctx.capability_confidence,
                capability_primary_action=ctx.capability_primary_action,
                intent_confidence=parsed_conf,
                override_threshold=capability_override_threshold,
            ):
                fallback_action = str(ctx.capability_primary_action or "").strip().lower()
                if fallback_action and fallback_action in AVAILABLE_TOOLS:
                    params = _build_capability_fallback_params(fallback_action, ctx.user_input)
                    ctx.intent = {
                        "action": fallback_action,
                        "params": params,
                        "_workflow_id": str(ctx.workflow_id or ""),
                        "_capability_domain": str(ctx.capability_domain or ""),
                        "_fallback_source": "capability_realign",
                    }
                    ctx.action = fallback_action
                    ctx.job_type = _job_type_from_action(ctx.action, ctx.job_type)
                    logger.info("Capability realignment activated: action=%s domain=%s c=%.2f", ctx.action, ctx.capability_domain, ctx.capability_confidence)
        except Exception:
            pass

        # Capability workflow fallback: promote deterministic workflow entrypoints
        # when parser leaves the request in a non-actionable state.
        try:
            if ctx.action in {"", "chat", "unknown", None} and ctx.capability_confidence >= capability_override_threshold:
                learned_quick = ""
                try:
                    if hasattr(agent, "learning") and agent.learning:
                        learned_quick = str(agent.learning.quick_match(ctx.user_input) or "").strip().lower()
                except Exception:
                    learned_quick = ""
                if learned_quick:
                    raise ValueError("capability_router_skip_due_to_learned_quick_match")
                fallback_action = str(ctx.capability_primary_action or "").strip().lower()
                if fallback_action and fallback_action in AVAILABLE_TOOLS:
                    low_input = str(ctx.user_input or "").lower()
                    if fallback_action in {"screen_workflow", "vision_operator_loop", "operator_mission_control"}:
                        if _looks_simple_app_control_command(low_input):
                            fallback_action = ""
                        explicit_screen_markers = (
                            "durum nedir", "ekrana bak", "ekranı oku", "ekrani oku", "ekranda ne var",
                            "screen", "screenshot", "bilgisayari kullan", "bilgisayarı kullan",
                            "tikla", "tıkla", "click", "type", "mouse", "klavye", "tuş", "tus",
                        )
                        if not any(k in low_input for k in explicit_screen_markers) and any(
                            k in low_input for k in ("araştır", "arastir", "research", "kaydet", "rapor", "belge", "word", "excel")
                        ):
                            fallback_action = ""
                    if not fallback_action:
                        raise ValueError("capability_router_skip_screen_fallback")
                    params = _build_capability_fallback_params(fallback_action, ctx.user_input)
                    ctx.intent = {
                        "action": fallback_action,
                        "params": params,
                        "_workflow_id": str(ctx.workflow_id or ""),
                        "_capability_domain": str(ctx.capability_domain or ""),
                        "_fallback_source": "capability_router",
                    }
                    ctx.action = fallback_action
                    ctx.job_type = _job_type_from_action(ctx.action, ctx.job_type)
        except Exception:
            pass

        # Parser tekil FS aksiyonuna düşse bile "klasör + kaydet + doğrula" gibi komutları multi_task'a yükselt.
        try:
            if ctx.action in {"create_folder", "write_file", "read_file", "list_files"}:
                low_in = ctx.user_input.lower()
                has_save = any(k in low_in for k in ("kaydet", "kayd", "yaz", "not olarak"))
                has_sequence = any(k in low_in for k in ("sonra", "ardından", "ardindan", "ve ", "1)", "2)", "3)", "adım", "adim"))
                has_fs_scope = any(k in low_in for k in ("klasör", "klasor", "dosya", "artifact", "path", "doğrula", "dogrula", "verify"))
                if has_save and (has_sequence or has_fs_scope) and hasattr(agent, "_infer_multi_task_intent"):
                    forced = agent._infer_multi_task_intent(ctx.user_input)
                    if not (isinstance(forced, dict) and str(forced.get("action") or "").strip().lower() == "multi_task"):
                        try:
                            inferred = agent._infer_general_tool_intent(ctx.user_input)
                            if isinstance(inferred, dict) and str(inferred.get("action") or "").strip().lower() == "multi_task":
                                forced = inferred
                        except Exception:
                            pass
                    if isinstance(forced, dict) and str(forced.get("action") or "").strip().lower() == "multi_task":
                        ctx.intent = forced
                        ctx.action = "multi_task"
        except Exception:
            pass

        # Structured/multi-step inputs should not be collapsed into a single learned quick action.
        looks_multi_step = False
        try:
            if hasattr(agent, "_split_multi_step_text"):
                parts = agent._split_multi_step_text(ctx.user_input)
                looks_multi_step = isinstance(parts, list) and len(parts) >= 2
        except Exception:
            looks_multi_step = False

        # Quick-match learning shortcuts (compat path for safe, deterministic actions)
        try:
            if (
                hasattr(agent, "learning")
                and agent.learning
                and not looks_multi_step
                and ctx.action in {"", "chat", "unknown", None}
            ):
                quick_match = agent.learning.quick_match(ctx.user_input)
                if quick_match:
                    ctx.intent = {"action": quick_match, "params": {}}
                    ctx.action = quick_match
        except Exception:
            pass

        # Structured multi-step override: if numbered/sequence command detected,
        # prefer deterministic multi-task inference even when parser guessed single action.
        try:
            if looks_multi_step and ctx.action not in {"multi_task", "filesystem_batch"} and hasattr(agent, "_infer_multi_task_intent"):
                multi_intent = agent._infer_multi_task_intent(ctx.user_input)
                if isinstance(multi_intent, dict) and str(multi_intent.get("action") or "").strip().lower() == "multi_task":
                    tasks = multi_intent.get("tasks", [])
                    if isinstance(tasks, list) and len(tasks) >= 2:
                        ctx.intent = multi_intent
                        ctx.action = "multi_task"
                        ctx.job_type = "file_operations"
            elif ctx.action in {"write_file", "create_folder"} and hasattr(agent, "_infer_multi_task_intent"):
                # Tek cümleli ama ardışık eylem içeren komutlar (örn. "klasör oluştur, not yaz, doğrula")
                low_in = ctx.user_input.lower()
                if any(k in low_in for k in ("doğrula", "dogrula", "verify", "artifact", "yolları", "yollari", "sonra", "ardından", "ardindan")):
                    multi_intent = agent._infer_multi_task_intent(ctx.user_input)
                    if isinstance(multi_intent, dict) and str(multi_intent.get("action") or "").strip().lower() == "multi_task":
                        tasks = multi_intent.get("tasks", [])
                        if isinstance(tasks, list) and len(tasks) >= 2:
                            ctx.intent = multi_intent
                            ctx.action = "multi_task"
                            ctx.job_type = "file_operations"
        except Exception:
            pass

        # Multi-step free-form intent detection (legacy compat)
        try:
            if ctx.action in {"", "chat", "unknown", None} and hasattr(agent, "_infer_multi_task_intent"):
                multi_intent = agent._infer_multi_task_intent(ctx.user_input)
                if isinstance(multi_intent, dict):
                    ctx.intent = multi_intent
                    ctx.action = str(multi_intent.get("action", "") or "").lower()
        except Exception:
            pass

        # Skill-based fallback: research command tokens while parser returns chat
        try:
            if ctx.action in {"", "chat", "unknown", None}:
                skills = skill_manager.list_skills(available=False, enabled_only=True)
                if skills:
                    import core.agent as _agent_mod
                    tokens = {tok.strip() for tok in ctx.user_input.lower().split() if tok.strip()}
                    matched = None
                    for tok in tokens:
                        matched = _agent_mod.skill_registry.get_skill_for_command(tok)
                        if matched:
                            break
                    if matched and matched.get("name") == "research":
                        topic = agent._sanitize_research_topic(agent._extract_topic(ctx.user_input, ctx.user_input), user_input=ctx.user_input, step_name=ctx.user_input)
                        ctx.intent = {"action": "advanced_research", "params": {"topic": topic, "depth": "standard"}}
                        ctx.action = "advanced_research"
        except Exception:
            pass

        # Skill workflow fallback (skill+tool zinciri)
        try:
            if ctx.action in {"", "chat", "unknown", None} and hasattr(agent, "_infer_skill_workflow_intent"):
                wf_intent = agent._infer_skill_workflow_intent(ctx.user_input, ctx.attachments)
                if wf_intent and isinstance(wf_intent, dict):
                    ctx.intent = wf_intent
                    ctx.action = str(wf_intent.get("action", "") or "").lower()
        except Exception:
            pass

        # General tool inference fallback (e.g., duvar kağıdı değiştir)
        try:
            if ctx.action in {"", "chat", "unknown", None} and hasattr(agent, "_infer_general_tool_intent"):
                inferred = agent._infer_general_tool_intent(ctx.user_input)
                if inferred and isinstance(inferred, dict):
                    ctx.intent = inferred
                    ctx.action = str(inferred.get("action", "") or "").lower()
        except Exception:
            pass

        # Attachment-based intent inference (e.g., görseli duvar kağıdı yap)
        try:
            if ctx.action in {"", "chat", "unknown", None} and ctx.attachments and hasattr(agent, "_infer_attachment_intent"):
                a_intent = agent._infer_attachment_intent(ctx.attachments, ctx.user_input)
                if a_intent:
                    ctx.intent = a_intent
                    ctx.action = str(a_intent.get("action", "") or "").lower()
                    params = a_intent.get("params", {})
                    if isinstance(params, dict) and params.get("image_path"):
                        ctx.attachments = [params["image_path"]] + ctx.attachments
        except Exception:
            pass

        # Autonomy rescue: actionable text should not remain in chat/communication intent.
        try:
            if _normalize_action(ctx.action) in _NON_ACTIONABLE_INTENTS and _looks_actionable_input(ctx.user_input, ctx.attachments):
                rescued = None
                if ctx.attachments and hasattr(agent, "_infer_attachment_intent"):
                    rescued = agent._infer_attachment_intent(ctx.attachments, ctx.user_input)
                if not isinstance(rescued, dict) and hasattr(agent, "_infer_general_tool_intent"):
                    rescued = agent._infer_general_tool_intent(ctx.user_input)
                if isinstance(rescued, dict):
                    ctx.intent = rescued
                    ctx.action = _normalize_action(rescued.get("action"))
        except Exception:
            pass

        # Request-shape guard: çok adımlı görünen komutları tek-adım intent'e düşürme.
        try:
            coerce = getattr(agent, "_coerce_intent_for_request_shape", None)
            if callable(coerce) and isinstance(ctx.intent, dict):
                coerced = coerce(ctx.intent, ctx.user_input, ctx.attachments)
                if isinstance(coerced, dict):
                    ctx.intent = coerced
                    ctx.action = _normalize_action(coerced.get("action"))
        except Exception:
            pass

        ctx.job_type = _job_type_from_action(ctx.action, ctx.job_type)

        # Model-A rescue: deterministic low-cost intent recovery before LLM fallback.
        try:
            model_a_enabled, model_a_path, model_a_min_conf, model_a_allowed = _resolve_model_a_policy(ctx)
            _try_model_a_intent_rescue(
                ctx,
                agent,
                enabled=model_a_enabled,
                model_path=model_a_path,
                min_confidence=model_a_min_conf,
                allowed_actions=model_a_allowed,
            )
        except Exception:
            pass

        # Last-mile rescue with LLM JSON tool intent when deterministic routing could not map an action.
        try:
            llm_threshold = max(0.5, float(capability_override_threshold or 0.5))
        except Exception:
            llm_threshold = 0.5
        if flag_enabled(ctx, "upgrade_intent_hardening", default=False):
            # Deterministic scorer confidence boosts rescue threshold for safety.
            llm_threshold = max(llm_threshold, 0.62 if ctx.intent_score < 0.42 else 0.7)
        try:
            if _looks_actionable_input(ctx.user_input, ctx.attachments):
                llm_threshold = min(llm_threshold, 0.42)
                if re.search(r"\b\d+\)\s+\S+", str(ctx.user_input or "").lower()):
                    llm_threshold = min(llm_threshold, 0.35)
        except Exception:
            pass
        try:
            await _try_llm_intent_rescue(ctx, agent, min_confidence=llm_threshold)
        except Exception:
            pass

        # TaskSpec-first normalization (strict mode optional):
        # actionable intents should be transformed into a schema-valid TaskSpec.
        strict_taskspec = False
        try:
            from config.elyan_config import elyan_config

            strict_taskspec = bool(elyan_config.get("agent.flags.strict_taskspec", False))
        except Exception:
            strict_taskspec = False
        try:
            policy_meta = {}
            if isinstance(ctx.runtime_policy, dict):
                policy_meta = ctx.runtime_policy.get("metadata", {}) if isinstance(ctx.runtime_policy.get("metadata"), dict) else {}
            if "strict_taskspec" in policy_meta:
                strict_taskspec = bool(policy_meta.get("strict_taskspec"))
        except Exception:
            pass

        try:
            if ctx.action not in {"", "chat", "unknown", None} and isinstance(ctx.intent, dict):
                task_spec = ctx.intent.get("task_spec") if isinstance(ctx.intent.get("task_spec"), dict) else None
                if task_spec is None and hasattr(agent, "_build_task_spec_from_intent"):
                    task_spec = agent._build_task_spec_from_intent(ctx.user_input, ctx.intent, ctx.job_type)
                    if isinstance(task_spec, dict):
                        ctx.intent["task_spec"] = task_spec
                if isinstance(task_spec, dict):
                    task_spec = coerce_task_spec_standard(
                        task_spec,
                        user_input=ctx.user_input,
                        intent_payload=ctx.intent,
                        intent_confidence=float(ctx.intent.get("confidence", 0.0) or 0.0),
                    )
                    ctx.intent["task_spec"] = task_spec

                if strict_taskspec:
                    from core.spec.task_spec import validate_task_spec

                    ok, errors = validate_task_spec(task_spec, strict_schema=True) if task_spec else (False, ["missing_task_spec"])
                    if not ok:
                        err = ", ".join(str(x) for x in (errors or [])[:5]) or "invalid_task_spec"
                        ctx.errors.append(f"taskspec_validation:{err}")
                        ctx.final_response = (
                            "İsteği güvenli ve deterministik yürütmek için geçerli TaskSpec üretemedim. "
                            f"Lütfen hedef/çıktı/path bilgisini netleştir. (detay: {err})"
                        )
                        ctx.delivery_blocked = True
        except Exception as e:
            logger.debug(f"TaskSpec normalization skipped: {e}")

        try:
            clarification = _build_low_confidence_actionable_clarification(ctx)
            if clarification:
                ctx.action = "clarify"
                ctx.job_type = "communication"
                ctx.final_response = clarification
                ctx.delivery_blocked = True
        except Exception:
            pass

        # Feedback / Correction Detection
        try:
            from core.feedback import get_feedback_store, get_feedback_detector
            fb_store = get_feedback_store()
            fb_detector = get_feedback_detector()
            is_corr, corr_text = fb_detector.extract_correction_intent(ctx.user_input)
            if is_corr and corr_text != ctx.user_input:
                if hasattr(agent, '_last_action') and agent._last_action:
                    fb_store.record_correction(
                        user_id=ctx.user_id,
                        original_input=ctx.user_input,
                        wrong_action=agent._last_action,
                        corrected_text=corr_text
                    )
                    logger.info(f"Correction detected: {ctx.user_input} -> {corr_text}")
                    ctx.user_input = corr_text
        except Exception as e:
            logger.debug(f"Feedback detection error: {e}")

        # Planning detection
        if (
            ctx.job_type != "communication"
            and (ctx.complexity > 0.45 or ctx.capability_confidence >= 0.45)
        ):
            ctx.needs_planning = True
        elif ctx.complexity > 0.6 and ctx.job_type == "communication" and ctx.action not in {"chat", "direct"}:
            ctx.needs_planning = True
        elif ctx.goal_stage_count >= 2 or len(ctx.workflow_chain) >= 2:
            ctx.needs_planning = True
        elif ctx.requires_evidence:
            ctx.needs_planning = True
             
        # Reasoning detection (extreme complexity or complex job types)
        if (
            ctx.complexity > 0.8
            or ctx.job_type in {"web_project", "code_project", "data_analysis", "api_integration"}
            or (ctx.multi_agent_recommended and ctx.capability_confidence >= 0.7)
            or ctx.goal_complexity >= 0.75
        ):
            ctx.needs_reasoning = True
             
        code_ext_markers = re.search(r"\.(py|js|jsx|ts|tsx|java|go|rs|c|cpp|cs|php|rb|swift|kt|sql|sh|html|css)\b", ctx.user_input.lower())
        code_action = _normalize_action(ctx.action) in {"edit_text_file", "write_file", "create_coding_project", "create_software_project_pack"}
        code_path_hit = False
        try:
            params = ctx.intent.get("params", {}) if isinstance(ctx.intent, dict) and isinstance(ctx.intent.get("params"), dict) else {}
            path_candidate = str(params.get("path") or params.get("file_path") or "").lower()
            code_path_hit = bool(re.search(r"\.(py|js|jsx|ts|tsx|java|go|rs|c|cpp|cs|php|rb|swift|kt|sql|sh|html|css)$", path_candidate))
        except Exception:
            code_path_hit = False
        if (
            ctx.job_type in {"code_project"}
            or any(kw in ctx.user_input.lower() for kw in ["kod", "python", "script", "yazılım", "yazilim", "refactor", "lint", "typecheck"])
            or bool(code_ext_markers)
            or (code_action and code_path_hit)
        ):
            ctx.is_code_job = True

        try:
            if flag_enabled(ctx, "upgrade_performance_routing", default=False):
                ctx.context_working_set = build_context_working_set(ctx, max_chars=1600)
                ctx.context_fingerprint = context_fingerprint(
                    ctx.user_input,
                    memory_context=ctx.memory_context,
                    attachment_index=ctx.attachment_index,
                )
            ctx.model_route = route_model_tier(
                complexity_score=ctx.complexity,
                is_code_job=ctx.is_code_job,
                needs_reasoning=ctx.needs_reasoning,
            )
            ctx.model_roles = assign_model_roles(ctx.model_route)
        except Exception as route_exc:
            logger.debug(f"Performance route skipped: {route_exc}")

        try:
            ctx.output_contract_spec = load_output_contract(ctx.job_type)
            ctx.understand_phase = {
                "phase": "Understand",
                "intent": dict(ctx.intent or {}) if isinstance(ctx.intent, dict) else {},
                "job_type": ctx.job_type,
                "constraints": {
                    "language": "tr" if any(ch in ctx.user_input.lower() for ch in ("ş", "ğ", "ı", "ö", "ü", "ç")) else "auto",
                    "attachments": len(ctx.attachments or []),
                    "required_artifacts": list(ctx.required_artifacts or []),
                    "safety_flags": list(ctx.safety_flags or []),
                    "assumptions": list(ctx.assumptions or []),
                },
                "success_criteria": build_success_criteria(
                    ctx.job_type,
                    required_artifacts=list(ctx.required_artifacts or []),
                ),
                "output_contract_id": ctx.output_contract_spec.get("contract_id"),
                "model_roles": dict(ctx.model_roles or {}),
            }
            ctx.phase_records["understand"] = dict(ctx.understand_phase)
            params = ctx.intent.get("params", {}) if isinstance(ctx.intent, dict) and isinstance(ctx.intent.get("params"), dict) else {}
            ctx.phase_records["route"] = {
                "phase": "Route",
                "action": str(ctx.action or ""),
                "job_type": str(ctx.job_type or ""),
                "capability_domain": str(ctx.capability_domain or "general"),
                "workflow_id": str(ctx.workflow_id or ""),
                "intent_score": float(ctx.intent_score or 0.0),
                "capability_confidence": float(ctx.capability_confidence or 0.0),
                "extracted_params": dict(params),
            }
            update_runtime_trace(
                ctx,
                capability=str(ctx.capability_domain or "general"),
                selected_workflow=str(ctx.workflow_id or ctx.action or ""),
                extracted_params=dict(params),
            )
        except Exception as understand_exc:
            logger.debug(f"Understand phase record skipped: {understand_exc}")

        logger.info(
            "Route: %s/%s c=%.2f plan=%s reason=%s cap=%s(%.2f) goal_stages=%d wf=%d proof=%s",
            ctx.role,
            ctx.job_type,
            ctx.complexity,
            ctx.needs_planning,
            ctx.needs_reasoning,
            ctx.capability_domain,
            ctx.capability_confidence,
            ctx.goal_stage_count,
            len(ctx.workflow_chain),
            ctx.requires_evidence,
        )

        # Late-stage research skill fallback (ensures chat-parser routes still hit research tool)
        try:
            if ctx.action in {"", "chat", "unknown", None}:
                skills = skill_manager.list_skills(available=False, enabled_only=True)
                has_research = any(s.get("name") == "research" and s.get("enabled", True) for s in (skills or []))
                wants_research = any(tok in ctx.user_input.lower() for tok in ["araştır", "arastir", "research"])
                if has_research or wants_research:
                    import core.agent as _agent_mod
                    topic = agent._sanitize_research_topic(
                        agent._extract_topic(ctx.user_input, ctx.user_input),
                        user_input=ctx.user_input,
                        step_name=ctx.user_input,
                    )
                    ctx.intent = {"action": "advanced_research", "params": {"topic": topic, "depth": "standard"}}
                    ctx.action = "advanced_research"
                    ctx.job_type = "communication"
                    ctx.needs_planning = False
        except Exception:
            pass

        try:
            _apply_workflow_profile(ctx)
            if getattr(ctx, "requires_design_phase", False):
                session = {}
                if callable(getattr(agent, "_get_workflow_session", None)):
                    session = agent._get_workflow_session(ctx.user_id, ctx.channel)
                if session:
                    ctx.workflow_session_id = str(session.get("session_id") or ctx.workflow_session_id or "")
                    if not approval_granted(ctx.user_input):
                        ctx.approval_status = str(session.get("approval_status") or ctx.approval_status or "pending")
                        ctx.workflow_phase = str(session.get("workflow_phase") or ctx.workflow_phase or "brainstorming")
                elif not ctx.workflow_session_id:
                    ctx.workflow_session_id = f"wf_{int(time.time() * 1000)}"
                _sync_workflow_metadata(ctx)
        except Exception as workflow_exc:
            logger.debug(f"Workflow profile setup skipped: {workflow_exc}")

        ctx.stage_timings["route"] = time.time() - t0
        return ctx


class StagePlan(PipelineStage):
    """Stage 3: Task decomposition and planning."""
    name = "plan"

    async def run(self, ctx: PipelineContext, agent) -> PipelineContext:
        t0 = time.time()
        if getattr(ctx, "requires_design_phase", False) and str(getattr(ctx, "approval_status", "") or "").lower() != "approved":
            ctx.phase_records["plan"] = {
                "phase": "Plan",
                "skipped": True,
                "reason": "approval_missing",
                "workflow_profile": str(getattr(ctx, "workflow_profile", "default") or "default"),
            }
            ctx.stage_timings["plan"] = time.time() - t0
            return ctx
        if not ctx.needs_planning:
            ctx.stage_timings["plan"] = 0
            return ctx

        if flag_enabled(ctx, "upgrade_planning_split_cache", default=False):
            try:
                skeleton = build_skeleton_plan(ctx.job_type, ctx.user_input)
                cache = get_plan_cache()
                key = make_plan_cache_key(
                    intent=ctx.intent if isinstance(ctx.intent, dict) else {},
                    job_type=ctx.job_type,
                    context_fingerprint=ctx.context_fingerprint or "",
                )
                cached = cache.get(key)
                if cached:
                    ctx.plan_cache_hit = True
                    ctx.skeleton_plan = cached
                    ctx.plan = list(cached)
                else:
                    ctx.plan_cache_hit = False
                    ctx.skeleton_plan = list(skeleton)
                    ctx.plan = list(skeleton)
                    cache.set(key, skeleton, ttl_s=300)
                ctx.step_specs = build_step_specs_from_plan(ctx.plan)
            except Exception as split_exc:
                logger.debug(f"Planning split/cache skipped: {split_exc}")

        try:
            from core.intelligent_planner import IntelligentPlanner
            from core.job_templates import get_template
            from config.elyan_config import elyan_config
            planner = IntelligentPlanner()
            logger.info("IntelligentPlanner activated for context decomposition.")

            if flag_enabled(ctx, "upgrade_planning_split_cache", default=False) and ctx.plan:
                # Skeleton plan already generated deterministically; avoid extra LLM planning calls.
                ctx.stage_timings["plan"] = time.time() - t0
                return ctx

            preferred_tools = list(ctx.preferred_tools or [])
            if not preferred_tools and ctx.job_type != "communication":
                preferred_tools = list(get_template(ctx.job_type).get("allowed_tools", []) or [])

            planner_use_llm = bool(elyan_config.get("agent.planning.use_llm", True))
            max_subtasks = int(elyan_config.get("agent.planning.max_subtasks", 10) or 10)
            max_subtasks = max(1, min(20, max_subtasks))
            try:
                planning_policy = {}
                if isinstance(ctx.runtime_policy, dict):
                    planning_policy = ctx.runtime_policy.get("planning", {}) if isinstance(ctx.runtime_policy.get("planning"), dict) else {}
                if "use_llm" in planning_policy:
                    planner_use_llm = bool(planning_policy.get("use_llm"))
                if "max_subtasks" in planning_policy:
                    max_subtasks = int(planning_policy.get("max_subtasks") or max_subtasks)
                max_subtasks = max(1, min(20, max_subtasks))
            except Exception:
                pass

            # Build structured plan object
            plan_obj = await planner.create_plan(
                description=ctx.user_input,
                llm_client=agent.llm,
                use_llm=planner_use_llm,
                user_id=ctx.user_id,
                preferred_tools=preferred_tools,
                context={
                    "goal_graph": ctx.goal_graph,
                    "goal_constraints": ctx.goal_constraints,
                    "execution_requirements": {
                        "requires_evidence": ctx.requires_evidence,
                        "goal_stage_count": ctx.goal_stage_count,
                        "workflow_chain": ctx.workflow_chain,
                    },
                },
            )

            subtasks = list(getattr(plan_obj, "subtasks", []) or [])
            if len(subtasks) > max_subtasks:
                subtasks = subtasks[:max_subtasks]
                kept = {s.task_id for s in subtasks}
                for s in subtasks:
                    s.dependencies = [d for d in list(s.dependencies or []) if d in kept]

            ctx.plan = [
                {
                    "id": s.task_id,
                    "title": s.name,
                    "description": s.name,
                    "action": s.action,
                    "depends_on": s.dependencies,
                    "params": s.params,
                }
                for s in subtasks
            ]

            # Enforce minimum verification/proof step for evidence-heavy tasks.
            if ctx.requires_evidence and ctx.plan:
                has_proof_step = any(
                    str(step.get("action", "")).strip() in {"take_screenshot", "generate_report", "write_file"}
                    for step in ctx.plan
                )
                if not has_proof_step:
                    proof_dep = str(ctx.plan[-1].get("id") or "")
                    ctx.plan.append(
                        {
                            "id": f"subtask_{len(ctx.plan) + 1}",
                            "title": "Kanıt Topla",
                            "description": "Çalışma kanıtını ekran görüntüsüyle kaydet",
                            "action": "take_screenshot",
                            "depends_on": [proof_dep] if proof_dep else [],
                            "params": {"filename": "proof_capture.png"},
                        }
                    )
            logger.info(f"Generated plan with {len(ctx.plan)} subtasks.")
            
        except Exception as e:
            logger.error(f"Planning failed: {e}")
            ctx.errors.append(f"plan: {e}")
            ctx.needs_planning = False # Fallback to direct execution

        try:
            ctx.phase_records["plan"] = {
                "phase": "Plan",
                "job_type": ctx.job_type,
                "plan_step_count": len(ctx.plan or []),
                "step_specs": list(ctx.step_specs or []),
                "skeleton_used": bool(ctx.skeleton_plan),
                "cache_hit": bool(ctx.plan_cache_hit),
            }
        except Exception as phase_exc:
            logger.debug(f"Plan phase record skipped: {phase_exc}")

        try:
            if getattr(ctx, "requires_design_phase", False) and str(getattr(ctx, "approval_status", "") or "").lower() == "approved":
                _ensure_plan_and_workspace_artifacts(ctx)
                ctx.workflow_phase = "plan_ready"
                _sync_workflow_metadata(ctx)
        except Exception as workflow_exc:
            logger.debug(f"Workflow plan artifact generation skipped: {workflow_exc}")

        ctx.stage_timings["plan"] = time.time() - t0
        return ctx


class StageExecute(PipelineStage):
    """Stage 4: LLM call + tool execution."""
    name = "execute"

    async def run(self, ctx: PipelineContext, agent) -> PipelineContext:
        t0 = time.time()
        telemetry_acc = JobTelemetryAccumulator()
        try:
            if ctx.delivery_blocked and ctx.final_response:
                ctx.stage_timings["execute"] = time.time() - t0
                return ctx

            exec_mode = _resolve_execution_mode(ctx)
            if isinstance(ctx.telemetry, dict):
                ctx.telemetry["execution_mode"] = exec_mode

            try:
                if getattr(ctx, "requires_design_phase", False):
                    if str(getattr(ctx, "approval_status", "") or "").lower() != "approved":
                        ctx.final_response = _workflow_brainstorm_response(ctx)
                        ctx.intent = {"action": "chat", "params": {"mode": "workflow_brainstorm"}}
                        ctx.action = "chat"
                        ctx.job_type = "communication"
                        if callable(getattr(agent, "_store_workflow_session", None)):
                            agent._store_workflow_session(
                                ctx.user_id,
                                ctx.channel,
                                {
                                    "session_id": str(ctx.workflow_session_id or f"wf_{int(time.time() * 1000)}"),
                                    "objective": str(ctx.user_input or ""),
                                    "workflow_profile": str(ctx.workflow_profile or "default"),
                                    "workflow_phase": "design_ready",
                                    "approval_status": "pending",
                                    "workflow_id": str(ctx.workflow_id or ""),
                                    "capability_domain": str(ctx.capability_domain or ""),
                                    "design_artifact_path": str((ctx.workflow_artifacts or {}).get("design_artifact_path") or ""),
                                },
                            )
                        ctx.stage_timings["execute"] = time.time() - t0
                        return ctx
                    _ensure_plan_and_workspace_artifacts(ctx)
                    ctx.workflow_phase = "executing"
                    _sync_workflow_metadata(ctx)
                    if str(ctx.workflow_profile or "") == "superpowers_strict" and str(ctx.workspace_mode or "") == "strict_worktree_required":
                        ctx.final_response = (
                            "Superpowers strict profilinde worktree zorunlu. "
                            "Workspace report hazır; worktree hazırlanmadan execution başlamadı."
                        )
                        ctx.intent = {"action": "chat", "params": {"mode": "workflow_blocked", "reason": "worktree_required"}}
                        ctx.action = "chat"
                        ctx.job_type = "communication"
                        ctx.errors.append("workflow:worktree_required")
                        ctx.delivery_blocked = True
                        ctx.stage_timings["execute"] = time.time() - t0
                        return ctx
                    ctx.team_mode_forced = True
            except Exception as workflow_exc:
                logger.debug(f"Workflow execution preflight skipped: {workflow_exc}")

            # Conversation Brain boundary:
            # - chat mode: actionable commands are understood but not executed.
            # - assist mode: produce deterministic plan preview without side effects.
            actionable = _looks_actionable_input(ctx.user_input, ctx.attachments) or _normalize_action(ctx.action) not in _NON_ACTIONABLE_INTENTS
            if exec_mode == "chat" and actionable:
                ctx.final_response = (
                    "Chat Mode aktif. Bu istegi anladim ama islem baslatmadim.\n"
                    + _build_assist_mode_preview(ctx)
                )
                ctx.intent = {"action": "chat", "params": {"mode": "chat"}}
                ctx.action = "chat"
                ctx.job_type = "communication"
                ctx.stage_timings["execute"] = time.time() - t0
                return ctx
            if exec_mode == "assist" and actionable:
                ctx.final_response = _build_assist_mode_preview(ctx)
                ctx.intent = {"action": "chat", "params": {"mode": "assist", "preview_only": True}}
                ctx.action = "chat"
                ctx.job_type = "communication"
                ctx.stage_timings["execute"] = time.time() - t0
                return ctx

            if flag_enabled(ctx, "upgrade_workspace_isolation", default=False):
                try:
                    if not ctx.workspace_path:
                        run_id = f"job_{int(time.time() * 1000)}_{str(ctx.user_id or 'local')[:12]}"
                        base = (Path.home() / ".elyan" / "jobs" / run_id).resolve()
                        files = ensure_workspace_contract(
                            base,
                            role=f"job:{ctx.job_type or 'general'}",
                            allowed_tools=list(ctx.preferred_tools or []),
                            metadata={
                                "user_id": str(ctx.user_id or ""),
                                "channel": str(ctx.channel or ""),
                                "job_type": str(ctx.job_type or ""),
                                "input_preview": str(ctx.user_input or "")[:220],
                            },
                        )
                        ctx.workspace_path = str(base)
                        ctx.workspace_files = dict(files or {})
                        ctx.telemetry["workspace"] = {"path": ctx.workspace_path, "files": ctx.workspace_files}
                except Exception as ws_exc:
                    logger.debug(f"Workspace isolation skipped: {ws_exc}")

            # 1. Health Checks & Locks
            from core.monitoring import get_resource_monitor
            from core.action_lock import action_lock
            from core.timeout_guard import with_timeout, LLM_TIMEOUT
            import os
            testing = "PYTEST_CURRENT_TEST" in os.environ
            
            monitor = get_resource_monitor()
            health = monitor.get_health_snapshot()
            if not testing:
                if health.status == "warning":
                    ctx.final_response += f"> 💡 **Sistem Notu:** {', '.join(health.issues)}. İşlem biraz yavaş seyredebilir.\n\n"
                elif health.status == "critical":
                    ctx.errors.append("Resource critical")
                    ctx.final_response = f"⚠️ **İşlem Durduruldu:** Sistem kaynakları kritik seviyede ({', '.join(health.issues)})."
                    return ctx

            # Attachment-aware intent enrichment (e.g., duvar kağıdı için görsel)
            try:
                if isinstance(ctx.intent, dict) and ctx.action == "set_wallpaper" and not ctx.intent.get("params", {}).get("image_path"):
                    if ctx.attachments:
                        params = ctx.intent.get("params", {}) or {}
                        params["image_path"] = ctx.attachments[0]
                        ctx.intent["params"] = params
            except Exception:
                pass

            # Late autonomy rescue at execution phase: avoid chat fallback for actionable commands.
            try:
                if _normalize_action(ctx.action) in _NON_ACTIONABLE_INTENTS and _looks_actionable_input(ctx.user_input, ctx.attachments):
                    rescued = None
                    if ctx.attachments and hasattr(agent, "_infer_attachment_intent"):
                        rescued = agent._infer_attachment_intent(ctx.attachments, ctx.user_input)
                    if not isinstance(rescued, dict) and hasattr(agent, "_infer_general_tool_intent"):
                        rescued = agent._infer_general_tool_intent(ctx.user_input)
                    if isinstance(rescued, dict):
                        ctx.intent = rescued
                        ctx.action = _normalize_action(rescued.get("action"))
                        ctx.job_type = _job_type_from_action(ctx.action, ctx.job_type)
            except Exception:
                pass

            try:
                coerce = getattr(agent, "_coerce_intent_for_request_shape", None)
                if callable(coerce) and isinstance(ctx.intent, dict):
                    coerced = coerce(ctx.intent, ctx.user_input, ctx.attachments)
                    if isinstance(coerced, dict):
                        ctx.intent = coerced
                        ctx.action = _normalize_action(coerced.get("action"))
                        ctx.job_type = _job_type_from_action(ctx.action, ctx.job_type)
            except Exception:
                pass

            try:
                llm_min_conf = 0.62
                if isinstance(ctx.runtime_policy, dict):
                    cap_cfg = ctx.runtime_policy.get("capability", {}) if isinstance(ctx.runtime_policy.get("capability"), dict) else {}
                    llm_min_conf = max(0.55, float(cap_cfg.get("min_confidence_override", 0.5) or 0.5))
                await _try_llm_intent_rescue(ctx, agent, min_confidence=llm_min_conf)
            except Exception:
                pass

            # 2. Direct Intent Execution (Deterministic Tools)
            if hasattr(agent, '_should_run_direct_intent') and agent._should_run_direct_intent(ctx.intent, ctx.user_input):
                logger.info(f"Direct intent path for action: {ctx.action}")
                micro_route = "direct_intent"
                micro_path = ["intent_parsed", "direct_intent"]
                if _is_simple_browser_or_app_intent(ctx.intent):
                    micro_route = "micro_orchestration"
                    micro_path.append("simple_browser_or_app")
                    current_action = _normalize_action((ctx.intent or {}).get("action"))
                    if current_action == "multi_task":
                        micro_path.append("deterministic_sequence")
                    elif current_action == "open_url":
                        micro_path.append("direct_browser_open")
                    else:
                        micro_path.append("direct_app_control")
                _set_execution_trace(ctx, route=micro_route, decision_path=micro_path)
                try:
                    agent._last_direct_intent_payload = None
                except Exception:
                    pass
                direct_text = await agent._run_direct_intent(
                    ctx.intent, ctx.user_input, ctx.role, [], user_id=ctx.user_id
                )
                if direct_text is not None:
                    direct_failed = _looks_execution_failure_text(direct_text)
                    direct_verification_failed = False
                    direct_verification_warning = ""
                    direct_payload = getattr(agent, "_last_direct_intent_payload", None)
                    direct_failure_class = _extract_direct_failure_class(direct_payload) or _infer_failure_class_from_text(
                        direct_text
                    )
                    direct_row = {
                        "action": str(ctx.action or ""),
                        "success": not direct_failed,
                        "message": str(direct_text or ""),
                        "source": "direct_intent",
                    }
                    if isinstance(direct_payload, dict):
                        direct_row["raw"] = dict(direct_payload)
                        if "success" in direct_payload:
                            direct_row["success"] = bool(direct_payload.get("success"))
                        for key in ("status", "summary", "artifacts", "screenshots", "observations", "ui_map", "ocr", "objects", "error"):
                            if key in direct_payload:
                                direct_row[key] = direct_payload.get(key)
                        app_control_actions = {"open_app", "close_app", "key_combo", "open_url"}
                        if _normalize_action(ctx.action) in app_control_actions:
                            verified_raw = direct_payload.get("verified")
                            warn_raw = str(direct_payload.get("verification_warning") or "").strip()
                            direct_verification_warning = warn_raw
                            if verified_raw is False:
                                direct_verification_failed = True
                            warn_low = warn_raw.lower()
                            if any(
                                marker in warn_low
                                for marker in (
                                    "uyumsuz",
                                    "hedef dışı",
                                    "hedef disi",
                                    "dogrulanamadi",
                                    "doğrulanamadı",
                                )
                            ):
                                direct_verification_failed = True
                            if direct_verification_failed:
                                direct_row["success"] = False
                    ctx.tool_results.append(direct_row)
                    # Post-proof: set_wallpaper sonrası ekran görüntüsü
                    if ctx.action == "set_wallpaper":
                        try:
                            if "take_screenshot" in AVAILABLE_TOOLS:
                                shot = await agent._execute_tool(
                                    "take_screenshot",
                                    {"filename": f"wallpaper_proof_{int(time.time() * 1000)}.png"},
                                    user_input=ctx.user_input,
                                    step_name="Kanıt SS",
                                )
                                proof_txt = agent._format_result_text(shot)
                                if proof_txt:
                                    direct_text += f"\nKanıt: {proof_txt}"
                        except Exception:
                            pass
                    if direct_verification_failed:
                        warn_text = (
                            f"\nNot: {direct_verification_warning}"
                            if direct_verification_warning
                            else "\nNot: Aksiyon dogrulama katisi basarisiz."
                        )
                        ctx.errors.append(f"direct_intent_unverified:{ctx.action}")
                        ctx.final_response += str(direct_text or "").strip() + warn_text
                        if action_lock.is_locked:
                            action_lock.unlock()
                        ctx.stage_timings["execute"] = time.time() - t0
                        return ctx
                    if direct_failed:
                        if direct_failure_class in {"policy_block", "planning_failure"}:
                            logger.warning(
                                "Direct intent failed with deterministic class=%s; skipping fallback.",
                                direct_failure_class,
                            )
                            ctx.errors.append(f"direct_intent_blocked:{direct_failure_class}")
                            ctx.final_response += str(direct_text or "")
                            if action_lock.is_locked:
                                action_lock.unlock()
                            ctx.stage_timings["execute"] = time.time() - t0
                            return ctx
                        if _is_simple_browser_or_app_intent(ctx.intent):
                            logger.warning(
                                "Simple browser/app direct intent failed; blocking orchestrator fallback for action=%s.",
                                ctx.action,
                            )
                            ctx.errors.append(f"direct_intent_failed:{ctx.action}")
                            ctx.final_response += str(direct_text or "")
                            if action_lock.is_locked:
                                action_lock.unlock()
                            ctx.stage_timings["execute"] = time.time() - t0
                            return ctx
                        screen_actions = {"screen_workflow", "analyze_screen", "take_screenshot", "vision_operator_loop", "operator_mission_control", "computer_use"}
                        if _normalize_action(ctx.action) in screen_actions:
                            logger.warning("Direct intent screen/operator result failed; preserving workflow boundary.")
                            ctx.errors.append(f"direct_intent_failed:{ctx.action}")
                            ctx.final_response += str(direct_text or "")
                            if action_lock.is_locked:
                                action_lock.unlock()
                            ctx.stage_timings["execute"] = time.time() - t0
                            return ctx
                        logger.warning("Direct intent returned failure text; falling back to standard execution path.")
                        ctx.errors.append(f"direct_intent_failed:{ctx.action}")
                    else:
                        ctx.final_response += direct_text
                        if action_lock.is_locked: action_lock.unlock()
                        ctx.stage_timings["execute"] = time.time() - t0
                        return ctx
                logger.info("Direct intent returned None, falling back to standard LLM path.")

            # Research skill fast-path when parser returned chat but research intent is obvious
            try:
                if ctx.action in {"", "chat", "unknown", None}:
                    wants_research = any(tok in ctx.user_input.lower() for tok in ["araştır", "arastir", "research"])
                    if wants_research and "advanced_research" in AVAILABLE_TOOLS:
                        topic = agent._sanitize_research_topic(agent._extract_topic(ctx.user_input, ctx.user_input), user_input=ctx.user_input, step_name=ctx.user_input)
                        res = await agent._execute_tool("advanced_research", {"topic": topic, "depth": "standard"}, user_input=ctx.user_input, step_name="Araştır")
                        ctx.final_response += agent._format_result_text(res)
                        if action_lock.is_locked: action_lock.unlock()
                        ctx.stage_timings["execute"] = time.time() - t0
                        return ctx
            except Exception:
                pass

            # 3. CDG Engine / Multi-Agent Orchestration (for non-communication jobs)
            should_use_orchestrated_execution = (
                (ctx.job_type != "communication" and ctx.action not in {"chat", "unknown", ""})
                or (ctx.needs_planning and ctx.goal_stage_count >= 3)
            )
            if _is_simple_browser_or_app_intent(ctx.intent):
                should_use_orchestrated_execution = False
            if should_use_orchestrated_execution:
                # Expert tasks (extreme complexity) bypass standard CDG for Multi-Agent Orchestration
                multi_agent_enabled = True
                multi_agent_complexity_threshold = 0.82
                multi_agent_capability_threshold = 0.7
                team_mode_enabled = True
                team_mode_threshold = 0.86
                team_max_parallel = 4
                team_timeout_s = 900
                team_max_retries_per_task = 1
                try:
                    from config.elyan_config import elyan_config
                    multi_agent_enabled = bool(elyan_config.get("agent.multi_agent.enabled", True))
                    multi_agent_complexity_threshold = float(
                        elyan_config.get("agent.multi_agent.complexity_threshold", 0.82) or 0.82
                    )
                    multi_agent_capability_threshold = float(
                        elyan_config.get("agent.multi_agent.capability_confidence_threshold", 0.7) or 0.7
                    )
                    team_mode_enabled = bool(elyan_config.get("agent.team_mode.enabled", True))
                    team_mode_threshold = float(elyan_config.get("agent.team_mode.threshold", 0.86) or 0.86)
                    team_max_parallel = int(elyan_config.get("agent.team_mode.max_parallel", 4) or 4)
                    team_timeout_s = int(elyan_config.get("agent.team_mode.timeout_s", 900) or 900)
                    team_max_retries_per_task = int(elyan_config.get("agent.team_mode.max_retries_per_task", 1) or 1)
                    multi_agent_complexity_threshold = max(0.5, min(1.0, multi_agent_complexity_threshold))
                    multi_agent_capability_threshold = max(0.3, min(1.0, multi_agent_capability_threshold))
                    team_mode_threshold = max(0.6, min(1.0, team_mode_threshold))
                    team_max_parallel = max(1, min(8, team_max_parallel))
                    team_timeout_s = max(60, min(3600, team_timeout_s))
                    team_max_retries_per_task = max(0, min(4, team_max_retries_per_task))
                except Exception:
                    multi_agent_enabled = True
                    multi_agent_complexity_threshold = 0.82
                    multi_agent_capability_threshold = 0.7
                    team_mode_enabled = True
                    team_mode_threshold = 0.86
                    team_max_parallel = 4
                    team_timeout_s = 900
                    team_max_retries_per_task = 1

                try:
                    orchestration_policy = {}
                    if isinstance(ctx.runtime_policy, dict):
                        orchestration_policy = ctx.runtime_policy.get("orchestration", {}) if isinstance(ctx.runtime_policy.get("orchestration"), dict) else {}
                    if "multi_agent_enabled" in orchestration_policy:
                        multi_agent_enabled = bool(orchestration_policy.get("multi_agent_enabled"))
                    if "complexity_threshold" in orchestration_policy:
                        multi_agent_complexity_threshold = float(orchestration_policy.get("complexity_threshold") or multi_agent_complexity_threshold)
                    if "capability_confidence_threshold" in orchestration_policy:
                        multi_agent_capability_threshold = float(
                            orchestration_policy.get("capability_confidence_threshold") or multi_agent_capability_threshold
                        )
                    if "team_threshold" in orchestration_policy:
                        team_mode_threshold = float(orchestration_policy.get("team_threshold") or team_mode_threshold)
                    if "team_max_parallel" in orchestration_policy:
                        team_max_parallel = int(orchestration_policy.get("team_max_parallel") or team_max_parallel)
                    if "team_timeout_s" in orchestration_policy:
                        team_timeout_s = int(orchestration_policy.get("team_timeout_s") or team_timeout_s)
                    if "team_max_retries_per_task" in orchestration_policy:
                        team_max_retries_per_task = int(
                            orchestration_policy.get("team_max_retries_per_task") or team_max_retries_per_task
                        )
                    multi_agent_complexity_threshold = max(0.5, min(1.0, multi_agent_complexity_threshold))
                    multi_agent_capability_threshold = max(0.3, min(1.0, multi_agent_capability_threshold))
                    team_mode_threshold = max(0.6, min(1.0, team_mode_threshold))
                    team_max_parallel = max(1, min(8, team_max_parallel))
                    team_timeout_s = max(60, min(3600, team_timeout_s))
                    team_max_retries_per_task = max(0, min(4, team_max_retries_per_task))
                except Exception:
                    pass
                if flag_enabled(ctx, "upgrade_telemetry_autotune", default=False):
                    try:
                        from core.monitoring import get_monitoring

                        summary = get_monitoring().get_pipeline_job_summary()
                        avg_verify = float(summary.get("avg_verify_pass_rate", 0.0) or 0.0)
                        if avg_verify < 0.75:
                            team_mode_threshold = min(0.95, team_mode_threshold + 0.04)
                            team_max_retries_per_task = min(4, team_max_retries_per_task + 1)
                        elif avg_verify > 0.92:
                            team_mode_threshold = max(0.75, team_mode_threshold - 0.02)
                    except Exception:
                        pass

                team_complexity_signal = (
                    ctx.goal_stage_count >= 4
                    or len(ctx.workflow_chain) >= 2
                    or ctx.goal_complexity >= max(0.7, team_mode_threshold - 0.15)
                )
                low_in = str(ctx.user_input or "").lower()
                explicit_autonomy_signal = any(
                    k in low_in
                    for k in (
                        "adım adım",
                        "adim adim",
                        "tam otonom",
                        "sub-agent",
                        "sub agent",
                        "team mode",
                        "otomasyon",
                        "bilgisayarı kontrol",
                        "bilgisayari kontrol",
                        "mouse",
                        "klavye",
                    )
                )
                multi_step_signal = (
                    bool(re.search(r"\b\d+\)\s+\S+", low_in))
                    or " sonra " in low_in
                    or " ardından " in low_in
                    or " ardindan " in low_in
                )
                team_complexity_signal = bool(team_complexity_signal or explicit_autonomy_signal or multi_step_signal)
                should_use_multi_agent = (
                    ctx.complexity >= multi_agent_complexity_threshold
                    or (ctx.multi_agent_recommended and ctx.capability_confidence >= multi_agent_capability_threshold)
                    or (
                        str(ctx.capability_plan.get("orchestration_mode", "single_agent")) == "multi_agent"
                        and ctx.capability_confidence >= multi_agent_capability_threshold
                    )
                )
                should_use_team = team_mode_enabled and (
                    ctx.team_mode_forced
                    or ctx.complexity >= team_mode_threshold
                    or team_complexity_signal
                )
                selected_mode = (
                    "team_mode"
                    if should_use_team
                    else ("multi_agent" if (multi_agent_enabled and should_use_multi_agent) else "single_agent_cdg")
                )
                if flag_enabled(ctx, "upgrade_orchestration_policy", default=False):
                    parallelizable = bool(team_complexity_signal or len(ctx.plan or []) >= 3)
                    op = decide_orchestration_policy(
                        complexity_score=ctx.complexity,
                        parallelizable=parallelizable,
                        default_threshold=multi_agent_complexity_threshold,
                        team_threshold=team_mode_threshold,
                    )
                    selected_mode = str(op.get("mode") or selected_mode)
                    team_max_parallel = min(team_max_parallel, int(op.get("max_agents", team_max_parallel) or team_max_parallel))
                    ctx.telemetry["orchestration_budget"] = {
                        "max_agents": int(op.get("max_agents", 1) or 1),
                        "token_budget": int(op.get("token_budget", 0) or 0),
                        "time_budget_s": int(op.get("time_budget_s", 0) or 0),
                    }
                    should_use_team = selected_mode == "team_mode"
                    should_use_multi_agent = selected_mode == "multi_agent"
                decision_reason = "default"
                if ctx.team_mode_forced:
                    decision_reason = "forced"
                elif should_use_team and ctx.complexity >= team_mode_threshold:
                    decision_reason = "complexity_threshold"
                elif should_use_team and team_complexity_signal:
                    decision_reason = "complexity_signal"
                elif selected_mode == "multi_agent":
                    if ctx.complexity >= multi_agent_complexity_threshold:
                        decision_reason = "multi_agent_complexity_threshold"
                    elif ctx.multi_agent_recommended and ctx.capability_confidence >= multi_agent_capability_threshold:
                        decision_reason = "capability_recommendation"
                    else:
                        decision_reason = "capability_orchestration_hint"
                telemetry_meta = {
                    "complexity": round(float(ctx.complexity or 0.0), 3),
                    "goal_complexity": round(float(ctx.goal_complexity or 0.0), 3),
                    "capability_confidence": round(float(ctx.capability_confidence or 0.0), 3),
                    "team_threshold": float(team_mode_threshold),
                    "multi_agent_threshold": float(multi_agent_complexity_threshold),
                    "multi_agent_capability_threshold": float(multi_agent_capability_threshold),
                    "team_mode_enabled": bool(team_mode_enabled),
                    "multi_agent_enabled": bool(multi_agent_enabled),
                    "team_forced": bool(ctx.team_mode_forced),
                    "team_complexity_signal": bool(team_complexity_signal),
                }
                record_orchestration_decision(
                    mode=selected_mode,
                    selected=True,
                    reason=decision_reason,
                    metadata=telemetry_meta,
                )
                if isinstance(ctx.capability_plan, dict):
                    ctx.capability_plan["orchestration_telemetry"] = {
                        "selected_mode": selected_mode,
                        "reason": decision_reason,
                        **telemetry_meta,
                    }
                _set_execution_trace(
                    ctx,
                    route=selected_mode,
                    decision_path=[
                        "intent_parsed",
                        f"capability:{str(ctx.capability_domain or 'general')}",
                        f"complexity:{round(float(ctx.complexity or 0.0), 2)}",
                        f"decision:{decision_reason}",
                        f"mode:{selected_mode}",
                    ],
                    details=telemetry_meta,
                )
                if should_use_team:
                    try:
                        from core.sub_agent.team import AgentTeam, TeamConfig

                        team = AgentTeam(
                            agent,
                            TeamConfig(
                                timeout_s=team_timeout_s,
                                max_parallel=team_max_parallel,
                                use_llm_planner=bool(ctx.runtime_policy.get("planning", {}).get("use_llm", True))
                                if isinstance(ctx.runtime_policy, dict)
                                else True,
                                max_retries_per_task=team_max_retries_per_task,
                            ),
                        )
                        team_kwargs = {
                            "task_packets": list(getattr(ctx, "task_packets", []) or []),
                            "workflow_context": {
                                "workflow_profile": str(getattr(ctx, "workflow_profile", "default") or "default"),
                                "workflow_id": str(getattr(ctx, "workflow_id", "") or ""),
                                "workspace_mode": str(getattr(ctx, "workspace_mode", "") or ""),
                                "approval_status": str(getattr(ctx, "approval_status", "") or ""),
                            },
                        }
                        try:
                            team_result = await team.execute_project(ctx.user_input, **team_kwargs)
                        except TypeError:
                            team_result = await team.execute_project(ctx.user_input)
                        team_status = str(getattr(team_result, "status", "success") or "success").lower()
                        summary = str(getattr(team_result, "summary", "") or "")
                        team_telemetry = dict(getattr(team_result, "telemetry", {}) or {})
                        if team_telemetry:
                            ctx.telemetry["team_mode"] = team_telemetry
                            if isinstance(ctx.capability_plan, dict):
                                ctx.capability_plan["team_mode_telemetry"] = team_telemetry
                        if summary:
                            ctx.final_response += summary
                        elif team_status == "success":
                            ctx.final_response += "✅ Team mode görevi tamamladı."
                        else:
                            ctx.final_response += "⚠️ Team mode kısmi sonuç üretti."
                        outputs = list(getattr(team_result, "outputs", []) or [])
                        if outputs:
                            ctx.tool_results.extend(outputs)
                        if getattr(ctx, "requires_design_phase", False):
                            ctx.approval_status = "review_passed" if team_status == "success" else "review_blocked"
                            _ensure_review_artifact(ctx)
                            _sync_workflow_metadata(ctx)
                            if callable(getattr(agent, "_store_workflow_session", None)):
                                agent._store_workflow_session(
                                    ctx.user_id,
                                    ctx.channel,
                                    {
                                        "session_id": str(ctx.workflow_session_id or f"wf_{int(time.time() * 1000)}"),
                                        "objective": str(ctx.user_input or ""),
                                        "workflow_profile": str(ctx.workflow_profile or "default"),
                                        "workflow_phase": "executing" if team_status == "success" else "review_blocked",
                                        "approval_status": str(ctx.approval_status or ""),
                                        "workflow_id": str(ctx.workflow_id or ""),
                                        "capability_domain": str(ctx.capability_domain or ""),
                                        "design_artifact_path": str((ctx.workflow_artifacts or {}).get("design_artifact_path") or ""),
                                        "plan_artifact_path": str((ctx.workflow_artifacts or {}).get("plan_artifact_path") or ""),
                                        "review_artifact_path": str((ctx.workflow_artifacts or {}).get("review_artifact_path") or ""),
                                        "workspace_mode": str(ctx.workspace_mode or ""),
                                    },
                                )
                        if team_status == "success":
                            if action_lock.is_locked:
                                action_lock.unlock()
                            ctx.stage_timings["execute"] = time.time() - t0
                            return ctx
                        logger.warning(
                            "Team mode incomplete (status=%s). Falling back to orchestrator/CDG.",
                            team_status,
                        )
                        record_orchestration_decision(
                            mode="team_mode",
                            selected=False,
                            reason=f"team_incomplete:{team_status}",
                            metadata={"fallback": "multi_agent_or_cdg", **telemetry_meta, **team_telemetry},
                        )
                        if flag_enabled(ctx, "upgrade_fallback_ladder", default=False):
                            ctx.telemetry["fallback_ladder"] = fallback_ladder()
                            ctx.telemetry["fallback_step"] = "same_plan_different_model"
                        ctx.errors.append(f"team_mode_incomplete:{team_status}")
                        ctx.final_response += "\nStandart orkestrasyon ile devam ediyorum...\n"
                    except Exception as team_exc:
                        logger.warning(f"Team mode failed, falling back to standard orchestration: {team_exc}")
                        record_orchestration_decision(
                            mode="team_mode",
                            selected=False,
                            reason="team_exception",
                            metadata={"fallback": "multi_agent_or_cdg", "error": str(team_exc), **telemetry_meta},
                        )
                        if flag_enabled(ctx, "upgrade_fallback_ladder", default=False):
                            ctx.telemetry["fallback_ladder"] = fallback_ladder()
                            ctx.telemetry["fallback_step"] = "reduced_minimal_plan"
                if multi_agent_enabled and should_use_multi_agent:
                    from core.multi_agent.orchestrator import AgentOrchestrator
                    orch = AgentOrchestrator(agent)
                    logger.info(
                        "Advanced task detected (c=%.2f, cap=%s). Activating Multi-Agent Orchestrator.",
                        ctx.complexity,
                        ctx.capability_domain,
                    )
                    resp = await orch.manage_flow(ctx.plan, ctx.user_input)
                    ctx.final_response += resp
                    if action_lock.is_locked: action_lock.unlock()
                    ctx.stage_timings["execute"] = time.time() - t0
                    return ctx

                from core.cdg_engine import cdg_engine
                from core.style_profile import style_profile
                
                logger.info(f"CDG Engine activated for job: {ctx.job_type}")
                job_id = f"job_{int(time.time())}"
                cdg_plan = await cdg_engine.create_plan(
                    job_id, ctx.job_type, ctx.user_input, llm_client=agent.llm
                )
                
                async def cdg_executor(node):
                    patch_inst = node.params.pop("_auto_patch_instruction", "")
                    if node.action in ("plan", "refine", "chat", "respond", "answer"):
                        prompt = f"{style_profile.to_prompt_lines()}\n\nGirdi: {ctx.user_input}\nGörev: {node.name}\nAçıklama: Bu adımda ne yapılmalı planla.{patch_inst}"
                        resp = await agent.llm.generate(prompt)
                        return {"output": resp}
                    elif node.action == "verify":
                        return {"output": "QA check passed", "success": True}
                    else:
                        patched_input = ctx.user_input + patch_inst if patch_inst else ctx.user_input
                        res = await agent._execute_tool(node.action, node.params, user_input=patched_input, step_name=node.name)
                        if flag_enabled(ctx, "upgrade_typed_tool_io", default=False):
                            io_res = validate_tool_io(node.action, node.params if isinstance(node.params, dict) else {}, res)
                            if not io_res.ok:
                                raise ValueError(f"tool_schema_mismatch:{';'.join(io_res.errors)}")
                        return res if isinstance(res, dict) else {"output": str(res)}
                
                cdg_plan = await cdg_engine.execute(cdg_plan, cdg_executor)
                manifest = cdg_engine.get_evidence_manifest(cdg_plan)
                
                overall_success = cdg_plan.status == "passed"
                ctx.tool_results = [n.result for n in cdg_plan.nodes]
                if collect_paths_from_tool_results([r for r in ctx.tool_results if isinstance(r, dict)]):
                    telemetry_acc.mark_first_artifact()

                rendered_tool_msg = ""
                for node in reversed(list(getattr(cdg_plan, "nodes", []) or [])):
                    action_name = str(getattr(node, "action", "") or "").strip()
                    if action_name in {"plan", "refine", "chat", "respond", "answer", "verify"}:
                        continue
                    node_result = getattr(node, "result", None)
                    if not isinstance(node_result, dict) or node_result.get("success") is False:
                        continue
                    candidate = str(agent._format_result_text(node_result) or "").strip()
                    if candidate and candidate not in {"İşlem başarıyla tamamlandı.", "Islem basariyla tamamlandi."}:
                        rendered_tool_msg = candidate
                        break
                
                if overall_success:
                    base_msg = rendered_tool_msg or "✅ İşlem tamamlandı."
                    if manifest["artifacts"]:
                        paths = [a.get("path") for a in manifest["artifacts"] if a.get("path")]
                        if paths and not any(str(path) in base_msg for path in paths[:3]):
                            base_msg += f"\nÜretilen dosyalar: {', '.join(paths)}"
                else:
                    logger.warning("CDG failed, applying fallback ladder.")
                    failed_nodes = [
                        n for n in cdg_plan.nodes
                        if str(getattr(getattr(n, "state", None), "value", "")) == "failed"
                    ]
                    failed_ids = [str(getattr(n, "id", "")) for n in failed_nodes]
                    fallback_step = ""
                    recovered = False
                    ladder_enabled = flag_enabled(ctx, "upgrade_fallback_ladder", default=False)
                    if ladder_enabled:
                        ctx.telemetry["fallback_ladder"] = fallback_ladder()
                        ctx.telemetry["diff_repair_plan"] = diff_only_failed_steps(ctx.plan, failed_ids)

                    def _result_ok(res: Any) -> bool:
                        if isinstance(res, dict):
                            if "success" in res:
                                return bool(res.get("success"))
                            if isinstance(res.get("result"), dict) and "success" in res["result"]:
                                return bool(res["result"].get("success"))
                        return bool(res)

                    # Diff-based repair: retry only failed tool steps.
                    if failed_nodes:
                        repaired = 0
                        retryable = 0
                        for node in failed_nodes:
                            action = str(getattr(node, "action", "") or "").strip()
                            if not action or action in {"plan", "refine", "chat", "respond", "answer", "verify"}:
                                continue
                            retryable += 1
                            params = getattr(node, "params", {}) if isinstance(getattr(node, "params", {}), dict) else {}
                            params = dict(params)
                            patch_inst = params.pop("_auto_patch_instruction", "")
                            try:
                                patched_input = ctx.user_input + patch_inst if patch_inst else ctx.user_input
                                retry_res = await agent._execute_tool(
                                    action,
                                    params,
                                    user_input=patched_input,
                                    step_name=str(getattr(node, "name", "") or "retry_step"),
                                )
                                if flag_enabled(ctx, "upgrade_typed_tool_io", default=False):
                                    io_res = validate_tool_io(action, params, retry_res)
                                    if not io_res.ok:
                                        raise ValueError(f"tool_schema_mismatch:{';'.join(io_res.errors)}")
                                if isinstance(retry_res, dict):
                                    ctx.tool_results.append(retry_res)
                                    if collect_paths_from_tool_results([retry_res]):
                                        telemetry_acc.mark_first_artifact()
                                if _result_ok(retry_res):
                                    repaired += 1
                            except Exception as repair_exc:
                                ctx.errors.append(f"repair_step:{action}:{repair_exc}")
                        if retryable > 0 and repaired >= retryable:
                            recovered = True
                            overall_success = True
                            base_msg = "✅ İşlem diff-repair ile tamamlandı."
                            ctx.telemetry["repair_loops"] = int(ctx.telemetry.get("repair_loops", 0) or 0) + 1

                    # Fallback ladder
                    if not recovered:
                        fallback_prompt = (
                            f"{style_profile.to_prompt_lines()}\n\n"
                            f"Kullanıcı isteği: {ctx.user_input}\n"
                            "Plan yürütmesi başarısız oldu. Kısa ve uygulanabilir bir kurtarma yanıtı ver."
                        )
                        try:
                            # (a) same plan different model profile
                            base_msg = await agent.llm.generate(fallback_prompt, role="reasoning", user_id=ctx.user_id)
                            fallback_step = "same_plan_different_model"
                            recovered = bool(str(base_msg or "").strip())
                        except Exception as fallback_exc:
                            ctx.errors.append(f"cdg_fallback_chat_failed: {fallback_exc}")

                    if not recovered and failed_nodes:
                        # (b) reduced minimal plan: retry first failing tool step only.
                        first = failed_nodes[0]
                        action = str(getattr(first, "action", "") or "").strip()
                        if action and action not in {"plan", "refine", "chat", "respond", "answer", "verify"}:
                            params = getattr(first, "params", {}) if isinstance(getattr(first, "params", {}), dict) else {}
                            params = dict(params)
                            params.pop("_auto_patch_instruction", None)
                            try:
                                min_res = await agent._execute_tool(
                                    action, params, user_input=ctx.user_input, step_name="minimal_recovery_step"
                                )
                                if isinstance(min_res, dict):
                                    ctx.tool_results.append(min_res)
                                    txt = agent._format_result_text(min_res)
                                    if txt:
                                        base_msg = f"⚠️ Kısmi kurtarma uygulandı:\n{txt}"
                                        recovered = True
                                        fallback_step = "reduced_minimal_plan"
                                        if collect_paths_from_tool_results([min_res]):
                                            telemetry_acc.mark_first_artifact()
                            except Exception as minimal_exc:
                                ctx.errors.append(f"fallback_minimal:{minimal_exc}")

                    if not recovered:
                        # (c) deterministic tool-only macro: directly execute routed intent once.
                        action = _normalize_action(ctx.action)
                        params = ctx.intent.get("params", {}) if isinstance(ctx.intent, dict) and isinstance(ctx.intent.get("params"), dict) else {}
                        if action and action in AVAILABLE_TOOLS:
                            try:
                                macro_res = await agent._execute_tool(
                                    action, dict(params), user_input=ctx.user_input, step_name="deterministic_macro"
                                )
                                if isinstance(macro_res, dict):
                                    ctx.tool_results.append(macro_res)
                                    txt = agent._format_result_text(macro_res)
                                    if txt:
                                        base_msg = txt
                                        recovered = True
                                        fallback_step = "deterministic_tool_macro"
                                        if collect_paths_from_tool_results([macro_res]):
                                            telemetry_acc.mark_first_artifact()
                            except Exception as macro_exc:
                                ctx.errors.append(f"fallback_macro:{macro_exc}")

                    if not recovered:
                        # (d) ask user last.
                        fallback_step = "ask_user"
                        base_msg = (
                            "❌ Görevi güvenli şekilde tamamlayamadım. "
                            "Lütfen hedef path/çıktı formatı/beklenen sonucu netleştir, yalnızca hatalı adımları tekrar deneyeceğim."
                        )

                    if ladder_enabled:
                        ctx.telemetry["fallback_step"] = fallback_step or "deterministic_tool_macro"
                
                # Apply hard constraints
                from core.constraint_engine import constraint_engine
                result_str, violations = constraint_engine.enforce(
                    base_msg,
                    tool_results=ctx.tool_results,
                    job_type=ctx.job_type,
                    contract_passed=overall_success
                )
                
                # Apply Auto-Patch telemetry log for unrecoverable errors
                if not overall_success:
                    if flag_enabled(ctx, "upgrade_fallback_ladder", default=False):
                        if "fallback_ladder" not in ctx.telemetry:
                            failed_ids = [str(getattr(n, "id", "")) for n in cdg_plan.nodes if str(getattr(getattr(n, "state", None), "value", "")) == "failed"]
                            ctx.telemetry["diff_repair_plan"] = diff_only_failed_steps(ctx.plan, failed_ids)
                            ctx.telemetry["fallback_ladder"] = fallback_ladder()
                            ctx.telemetry["fallback_step"] = "deterministic_tool_macro"
                    from core.failure_clustering import failure_clustering
                    for node in cdg_plan.nodes:
                        if node.state.value == "failed":
                            fail_code = failure_clustering.detect_failure_code(node.error or str(node.result), node.action, str(node.result))
                            suggestion = failure_clustering.suggest_fix(fail_code)
                            result_str += f"\n\n**Hata Analizi ({node.name})**\n{suggestion}"
                
                ctx.final_response += result_str
                
                if action_lock.is_locked: action_lock.unlock()

            # 4. Standard execution (Reasoning or simple)
            else:
                if ctx.needs_reasoning:
                    from core.reasoning.chain_of_thought import ReasoningChain
                    reasoner = ReasoningChain(agent)
                    logger.info("ReasoningChain activated for deep thinking loop.")
                    # Inject memory and multimodal context into reasoning
                    context_units = []
                    if ctx.memory_context: context_units.append(f"Memory:\n{ctx.memory_context}")
                    if ctx.multimodal_context: context_units.append(f"Multimodal Context:\n{ctx.multimodal_context}")
                    if ctx.context_docs: context_units.append(f"Knowledge:\n{ctx.context_docs}")
                    
                    full_context = "\n\n".join(context_units)
                    reason_res = await reasoner.reason(ctx.user_input, context=full_context)
                    ctx.final_response += reason_res.final_answer
                    ctx.llm_response = reason_res.final_answer
                else:
                    logger.debug(f"Executing standard chat route for intent {ctx.action}")
                    context_prefix = f"[MOD: {ctx.specialized_prompt}]\n\n" if ctx.specialized_prompt else ""
                    
                    # Unified prompt with Memory + Multimodal + Knowledge + User Input
                    prompt_parts = []
                    if context_prefix: prompt_parts.append(context_prefix)
                    if flag_enabled(ctx, "upgrade_performance_routing", default=False):
                        if ctx.context_working_set:
                            prompt_parts.append(f"Working Set:\n{ctx.context_working_set}")
                        elif ctx.memory_context:
                            prompt_parts.append(f"Memory:\n{ctx.memory_context[:800]}")
                        if ctx.multimodal_context:
                            prompt_parts.append(f"Multimodal Context:\n{ctx.multimodal_context[:500]}")
                        if ctx.context_docs:
                            prompt_parts.append(f"Knowledge:\n{ctx.context_docs[:600]}")
                    else:
                        if ctx.memory_context: prompt_parts.append(f"Memory:\n{ctx.memory_context}")
                        if ctx.multimodal_context: prompt_parts.append(f"Multimodal Context:\n{ctx.multimodal_context}")
                        if ctx.context_docs: prompt_parts.append(f"Knowledge:\n{ctx.context_docs}")
                    prompt_parts.append(f"User: {ctx.user_input}")
                    
                    full_prompt = "\n\n".join(prompt_parts)

                    # Ensure LLM is available (lazy init safety net)
                    if agent.llm is None:
                        agent._ensure_llm()

                    try:
                        chat_resp = await with_timeout(
                            agent.llm.generate(full_prompt, role=ctx.role, user_id=ctx.user_id),
                            seconds=LLM_TIMEOUT,
                            fallback="LLM timeout.",
                            context="pipeline_execute_chat"
                        )
                        # If the LLM returned a structured tool-call JSON, execute it (legacy tool-router compat)
                        executed_tool = False
                        if isinstance(chat_resp, str):
                            try:
                                parsed = None
                                parser = getattr(agent, "_extract_first_json_object", None)
                                if callable(parser):
                                    parsed = parser(chat_resp)
                                if isinstance(parsed, dict) and ("action" in parsed):
                                    action = str(parsed.get("action") or "").strip()
                                    params = parsed.get("params") if isinstance(parsed.get("params"), dict) else {}
                                    if action:
                                        res = await agent._execute_tool(
                                            action,
                                            params,
                                            user_input=ctx.user_input,
                                            step_name=parsed.get("step_name", ""),
                                        )
                                        if flag_enabled(ctx, "upgrade_typed_tool_io", default=False):
                                            io_res = validate_tool_io(action, params, res)
                                            if not io_res.ok:
                                                raise ValueError(f"tool_schema_mismatch:{';'.join(io_res.errors)}")
                                        if isinstance(res, dict):
                                            maybe_path = res.get("path") or (res.get("result", {}).get("path") if isinstance(res.get("result"), dict) else "")
                                            if isinstance(maybe_path, str) and maybe_path.strip():
                                                telemetry_acc.mark_first_artifact()
                                        ctx.final_response += agent._format_result_text(res)
                                        executed_tool = True
                            except Exception:
                                pass
                        if not executed_tool:
                            ctx.final_response += chat_resp
                    except Exception as e:
                        ctx.errors.append(f"chat_failed: {e}")
                        ctx.final_response += "LLM sağlayıcısına şu an erişemiyorum. Lütfen tekrar dener misin?"

        except Exception as exc:
            logger.error(f"StageExecute failed: {exc}")
            ctx.errors.append(str(exc))
            ctx.final_response = f"Çalıştırma sırasında kritik bir hata oluştu: {exc}"

        try:
            token_est = estimate_token_cost(
                user_input=ctx.user_input,
                memory_context=ctx.memory_context,
                plan=ctx.plan,
            )
            ctx.telemetry.update(
                telemetry_acc.snapshot(
                    complexity_score=ctx.complexity,
                    token_cost_estimate=token_est,
                    tool_results=ctx.tool_results,
                    verified=ctx.verified,
                    repair_loops=int(ctx.telemetry.get("repair_loops", 0) or 0),
                )
            )
        except Exception:
            pass

        try:
            ctx.phase_records["execute"] = {
                "phase": "Execute",
                "tool_call_count": len(ctx.tool_calls or []),
                "tool_result_count": len(ctx.tool_results or []),
                "delivery_blocked": bool(ctx.delivery_blocked),
                "worker_model": dict((ctx.model_roles or {}).get("worker") or {}),
            }
        except Exception:
            pass

        ctx.stage_timings["execute"] = time.time() - t0
        return ctx


class StageVerify(PipelineStage):
    """Stage 5: Output contract verification + QA."""
    name = "verify"

    async def run(self, ctx: PipelineContext, agent) -> PipelineContext:
        t0 = time.time()
        
        # AST-Aware Code Validation (if code was likely produced)
        if ctx.is_code_job and (ctx.llm_response or ctx.final_response):
            try:
                from core.reasoning.code_validator import CodeValidator
                validator = CodeValidator(agent)
                logger.info("CodeValidator activated for syntax and logic audit.")
                
                # Extract code from response
                import re
                source = ctx.llm_response or ctx.final_response
                code_blocks = re.findall(r"```python\n(.*?)\n```", source, re.DOTALL)
                if code_blocks:
                    for code in code_blocks:
                        val_res = await validator.validate_and_repair(code, intent=ctx.user_input)
                        if val_res.repair_attempts > 0:
                            ctx.final_response = ctx.final_response.replace(code, val_res.final_code)
                            ctx.final_response += f"\n\n> 🛠️ **Otomatik Onarım:** Kodda hatalar tespit edildi ve {val_res.repair_attempts} denemede düzeltildi."
                        
                        if not val_res.test_passed:
                            ctx.errors.append("code_validation_failed")
                            ctx.final_response += f"\n\n⚠️ **UYARI:** Üretilen kod testleri geçemedi: {val_res.test_output[:100]}..."
            except Exception as e:
                logger.error(f"Code validation error: {e}")

        # Output quality contract (professional delivery guardrails).
        try:
            quality_contract: Dict[str, Any] = {}

            if ctx.is_code_job:
                code_signals = _detect_code_quality_signals(ctx)
                quality_contract = {
                    "kind": "code",
                    "signals": code_signals,
                    "status": "pass" if not code_signals.get("missing") else "partial",
                }
                missing = list(code_signals.get("missing", []) or [])
                if missing:
                    rows = ", ".join(missing)
                    note = (
                        "\n\nKalite kontrol özeti:\n"
                        f"- Eksik kapılar: {rows}\n"
                        "- Not: Profesyonel teslim için test/lint/typecheck adımlarını tamamlamanı öneririm."
                    )
                    if note not in str(ctx.final_response or ""):
                        ctx.final_response = f"{str(ctx.final_response or '').rstrip()}{note}"

            elif _is_research_task(ctx):
                research_contract = _format_research_contract_addendum(ctx)
                quality_contract = {
                    "kind": "research",
                    "missing": list(research_contract.get("missing", []) or []),
                    "sources_found": int(research_contract.get("sources_found", 0) or 0),
                    "confidence_estimate": float(research_contract.get("confidence_estimate", 0.0) or 0.0),
                    "status": "pass" if not research_contract.get("missing") else "partial",
                }
                addendum = str(research_contract.get("addendum") or "")
                if addendum and addendum not in str(ctx.final_response or ""):
                    ctx.final_response = f"{str(ctx.final_response or '').rstrip()}{addendum}"

            if quality_contract:
                ctx.qa_results["output_contract"] = quality_contract
        except Exception as e:
            logger.debug(f"Output quality contract skipped: {e}")

        try:
            contract_payload = {
                "contract_id": ctx.output_contract_spec.get("contract_id") if isinstance(ctx.output_contract_spec, dict) else "",
                "job_type": ctx.job_type,
                "objective": str(ctx.user_input or "").strip(),
            }
            contract_ok, contract_errors = validate_output_contract(ctx.job_type, contract_payload)
            ctx.qa_results["declared_output_contract"] = {
                "ok": contract_ok,
                "errors": contract_errors,
                "contract_id": contract_payload.get("contract_id"),
            }
            if not contract_ok:
                ctx.errors.extend([f"contract_decl:{err}" for err in contract_errors])
        except Exception as contract_exc:
            ctx.errors.append(f"contract_decl:{contract_exc}")

        # Upgrade mandatory verify gates + output contract enforcement.
        if flag_enabled(ctx, "upgrade_verify_mandatory_gates", default=False):
            try:
                produced_paths = collect_paths_from_tool_results(ctx.tool_results)
                task_spec = ctx.intent.get("task_spec") if isinstance(ctx.intent, dict) and isinstance(ctx.intent.get("task_spec"), dict) else None
                expected_ext = []
                if isinstance(ctx.intent, dict):
                    exp = ctx.intent.get("expected_extensions")
                    if isinstance(exp, list):
                        expected_ext = [str(x) for x in exp]
                evidence_checks = []
                if isinstance(ctx.qa_results, dict):
                    evidence_checks = [k for k, v in (ctx.qa_results.get("output_contract", {}).get("signals", {}) or {}).items() if isinstance(v, bool) and v]
                contract_res = enforce_output_contract(
                    job_type=ctx.job_type,
                    expected_extensions=expected_ext,
                    produced_paths=produced_paths,
                    evidence_checks=evidence_checks,
                )

                task_contract = verify_taskspec_contract(
                    task_spec=task_spec,
                    job_type=ctx.job_type,
                    final_response=ctx.final_response,
                    tool_results=[r for r in ctx.tool_results if isinstance(r, dict)],
                    produced_paths=produced_paths,
                )
                if not task_contract.get("ok", True):
                    taskspec_failure_class = _classify_taskspec_failure(
                        task_contract,
                        action=str(getattr(ctx, "action", "") or ""),
                    )
                    recovery_strategy = select_recovery_strategy(
                        failure_class=taskspec_failure_class,
                        action=str(getattr(ctx, "action", "") or ""),
                        reason=", ".join(str(x) for x in list(task_contract.get("failed") or [])),
                        params=ctx.intent.get("params") if isinstance(ctx.intent.get("params"), dict) else {},
                        result={"task_spec": task_spec or {}, "failed": list(task_contract.get("failed") or [])},
                    )
                    ctx.qa_results["taskspec_failure"] = {
                        "class": taskspec_failure_class,
                        "failed": [str(x) for x in list(task_contract.get("failed") or []) if str(x).strip()],
                    }
                    ctx.qa_results["taskspec_recovery_strategy"] = recovery_strategy
                    recovery_kind = str(recovery_strategy.get("kind") or "").strip().lower()
                    repair_info = {"repaired": False, "strategy": "noop", "rechecked": task_contract}
                    if recovery_kind == "replay_taskspec_artifact":
                        repair_info = await _repair_taskspec_contract(ctx, agent, task_spec or {}, task_contract)
                        ctx.qa_results["taskspec_contract_repair"] = repair_info
                        if repair_info.get("repaired"):
                            produced_paths = collect_paths_from_tool_results(ctx.tool_results)
                            task_contract = repair_info.get("rechecked") if isinstance(repair_info.get("rechecked"), dict) else task_contract
                            repair_evidence = list(evidence_checks)
                            repair_evidence.append("taskspec_contract_repaired")
                            contract_res = enforce_output_contract(
                                job_type=ctx.job_type,
                                expected_extensions=expected_ext,
                                produced_paths=produced_paths,
                                evidence_checks=repair_evidence,
                            )
                            if isinstance(ctx.telemetry, dict):
                                repair_steps = list(ctx.telemetry.get("repair_steps", []) or [])
                                strategy = str(repair_info.get("strategy") or "").strip()
                                if strategy and strategy not in repair_steps:
                                    repair_steps.append(strategy)
                                    ctx.telemetry["repair_steps"] = repair_steps
                ctx.qa_results["upgrade_output_contract"] = contract_res
                ctx.qa_results["taskspec_contract"] = task_contract

                mismatch = detect_artifact_mismatch(expected_extensions=expected_ext, produced_paths=produced_paths)
                if mismatch:
                    ctx.qa_results["tool_mismatch"] = {"failed": mismatch}
                    ctx.errors.append("tool_mismatch_detector")
                    ctx.telemetry["fallback_step"] = "reduced_minimal_plan"

                gate_failed: list[str] = []
                if ctx.is_code_job:
                    code_gate = verify_code_gates(
                        final_response=ctx.final_response,
                        produced_paths=produced_paths,
                        tool_results=[r for r in ctx.tool_results if isinstance(r, dict)],
                    )
                    ctx.qa_results["code_gate"] = code_gate
                    if not code_gate.get("ok", False):
                        code_failure_class = "planning_failure"
                        declared_missing = [
                            str(x).strip().lower()
                            for x in list((((ctx.qa_results.get("output_contract") or {}) if isinstance(ctx.qa_results.get("output_contract"), dict) else {}).get("signals") or {}).get("missing") or [])
                            if str(x).strip()
                        ]
                        normalized_missing = []
                        for item in declared_missing:
                            if item == "tests":
                                normalized_missing.append("smoke")
                            else:
                                normalized_missing.append(item)
                        combined_failed_gates = list(dict.fromkeys(
                            [str(x).strip().lower() for x in list(code_gate.get("failed") or []) if str(x).strip()] + normalized_missing
                        ))
                        code_gate_plan = _build_code_quality_gate_plan(
                            produced_paths=produced_paths,
                            failed_gates=combined_failed_gates,
                        )
                        code_recovery_strategy = select_recovery_strategy(
                            failure_class=code_failure_class,
                            action=str(getattr(ctx, "action", "") or ""),
                            reason=", ".join(f"code:{x}" for x in combined_failed_gates),
                            params=ctx.intent.get("params") if isinstance(ctx.intent.get("params"), dict) else {},
                            result={
                                "code_gate": {"failed": combined_failed_gates},
                                "quality_gate_commands": list(code_gate_plan.get("commands") or []),
                            },
                        )
                        ctx.qa_results["code_failure"] = {
                            "class": code_failure_class,
                            "failed": combined_failed_gates,
                        }
                        ctx.qa_results["code_recovery_strategy"] = code_recovery_strategy
                        if code_gate_plan.get("repairable"):
                            ctx.qa_results["code_repair_plan"] = code_gate_plan
                            if str(code_recovery_strategy.get("kind") or "").strip().lower() == "quality_gate_plan":
                                cmds = [str(x).strip() for x in list(code_gate_plan.get("commands") or []) if str(x).strip()]
                                if cmds:
                                    marker = "Quality gate next:"
                                    hint = f"{marker} " + " ; ".join(cmds[:3])
                                    if hint not in str(ctx.final_response or ""):
                                        ctx.final_response = f"{str(ctx.final_response or '').rstrip()}\n{hint}".strip()
                                    if isinstance(ctx.telemetry, dict):
                                        repair_steps = list(ctx.telemetry.get("repair_steps", []) or [])
                                        strategy = str(code_recovery_strategy.get("note") or code_recovery_strategy.get("kind") or "").strip()
                                        if strategy and strategy not in repair_steps:
                                            repair_steps.append(strategy)
                                            ctx.telemetry["repair_steps"] = repair_steps
                        gate_failed.extend([f"code:{x}" for x in code_gate.get("failed", [])])
                elif _is_research_task(ctx):
                    research_urls = _collect_urls(ctx.final_response, ctx.tool_results)
                    research_payload = _extract_research_payload(ctx.tool_results)
                    research_gate = verify_research_gates(
                        final_response=ctx.final_response,
                        source_urls=research_urls,
                        research_payload=research_payload,
                    )
                    ctx.qa_results["research_gate"] = research_gate
                    if not research_gate.get("ok", False):
                        gate_failed.extend([f"research:{x}" for x in research_gate.get("failed", [])])
                    payload_ok, payload_errors = validate_research_payload(research_payload)
                    ctx.qa_results["research_payload"] = {
                        "ok": payload_ok,
                        "errors": payload_errors,
                    }
                    if not research_gate.get("ok", False) or not payload_ok:
                        combined_research_failed = list(dict.fromkeys(
                            [str(x).strip() for x in list(research_gate.get("failed") or []) if str(x).strip()] +
                            [f"payload:{err}" for err in payload_errors]
                        ))
                        research_failure_class = "planning_failure"
                        research_repair_plan = _build_research_recovery_plan(
                            failed_gates=combined_research_failed,
                            source_urls=research_urls,
                            payload_errors=payload_errors,
                        )
                        research_recovery_strategy = select_recovery_strategy(
                            failure_class=research_failure_class,
                            action=str(getattr(ctx, "action", "") or ""),
                            reason=", ".join(f"research:{x}" for x in combined_research_failed),
                            params=ctx.intent.get("params") if isinstance(ctx.intent.get("params"), dict) else {},
                            result={
                                "research_gate": {"failed": combined_research_failed},
                                "research_repair_steps": list(research_repair_plan.get("steps") or []),
                            },
                        )
                        ctx.qa_results["research_failure"] = {
                            "class": research_failure_class,
                            "failed": combined_research_failed,
                        }
                        ctx.qa_results["research_recovery_strategy"] = research_recovery_strategy
                        if research_repair_plan.get("repairable"):
                            ctx.qa_results["research_repair_plan"] = research_repair_plan
                            if str(research_recovery_strategy.get("kind") or "").strip().lower() == "research_revision_plan":
                                steps = [str(x).strip() for x in list(research_repair_plan.get("steps") or []) if str(x).strip()]
                                if steps:
                                    marker = "Research next:"
                                    hint = f"{marker} " + " ; ".join(steps[:3])
                                    if hint not in str(ctx.final_response or ""):
                                        ctx.final_response = f"{str(ctx.final_response or '').rstrip()}\n{hint}".strip()
                                    if isinstance(ctx.telemetry, dict):
                                        repair_steps = list(ctx.telemetry.get("repair_steps", []) or [])
                                        strategy = str(research_recovery_strategy.get("note") or research_recovery_strategy.get("kind") or "").strip()
                                        if strategy and strategy not in repair_steps:
                                            repair_steps.append(strategy)
                                            ctx.telemetry["repair_steps"] = repair_steps
                    if not payload_ok:
                        gate_failed.extend([f"research_payload:{err}" for err in payload_errors])
                elif ctx.attachment_index:
                    asset_gate = verify_asset_gates(attachment_index=ctx.attachment_index)
                    ctx.qa_results["asset_gate"] = asset_gate
                    if not asset_gate.get("ok", False):
                        gate_failed.extend([f"asset:{x}" for x in asset_gate.get("failed", [])])

                if not contract_res.get("ok", True):
                    gate_failed.extend([f"contract:{x}" for x in contract_res.get("errors", [])])
                if not task_contract.get("ok", True):
                    gate_failed.extend([f"taskspec:{x}" for x in task_contract.get("failed", [])])
                if mismatch:
                    gate_failed.append("artifact_mismatch")

                if gate_failed:
                    ctx.verified = False
                    ctx.delivery_blocked = True
                    ctx.errors.extend(gate_failed)
                    reflexion_hint = build_reflexion_hint(
                        verification_payload=task_contract,
                        job_type=ctx.job_type,
                    )
                    suffix = f"\n{reflexion_hint}" if reflexion_hint else ""
                    ctx.final_response = f"{str(ctx.final_response or '').rstrip()}\n\n❌ Verify gate failed: {', '.join(gate_failed)}{suffix}"
            except Exception as verify_exc:
                ctx.errors.append(f"upgrade_verify_gate:{verify_exc}")

        # Deterministic completion gate: actionable tasks must have a verifiable success signal.
        try:
            capability_runtime = evaluate_runtime_capability(
                ctx,
                synthesize_screen_summary=_repair_screen_completion,
            )
            repair_info = capability_runtime.get("repair", {}) if isinstance(capability_runtime.get("repair"), dict) else {}
            if repair_info.get("repaired"):
                capability_runtime = evaluate_runtime_capability(
                    ctx,
                    synthesize_screen_summary=_repair_screen_completion,
                )
                capability_runtime["repair"] = repair_info
            verify_info = capability_runtime.get("verify", {}) if isinstance(capability_runtime.get("verify"), dict) else {}
            ctx.qa_results["capability_runtime"] = capability_runtime
            capability_failed_codes = []
            if isinstance(verify_info.get("failed_codes"), list):
                capability_failed_codes = [str(x).strip() for x in verify_info.get("failed_codes", []) if str(x).strip()]
            elif isinstance(capability_runtime.get("failed_codes"), list):
                capability_failed_codes = [str(x).strip() for x in capability_runtime.get("failed_codes", []) if str(x).strip()]
            capability_failed_reasons = [str(x).strip() for x in list(verify_info.get("failed") or []) if str(x).strip()]
            capability_reason = ", ".join(capability_failed_reasons)
            capability_failure_class = classify_failure_class(
                reason=capability_reason,
                failed_codes=capability_failed_codes,
                action=str(getattr(ctx, "action", "") or ""),
                payload=verify_info if isinstance(verify_info, dict) else {},
            )
            if capability_failed_reasons:
                ctx.qa_results["capability_failure"] = {
                    "class": capability_failure_class,
                    "failed": capability_failed_reasons,
                    "failed_codes": capability_failed_codes,
                }

            repair_strategy = str(repair_info.get("strategy") or "").strip()
            trace_repairs = list(ctx.telemetry.get("repair_steps", []) or []) if isinstance(ctx.telemetry, dict) else []
            if repair_strategy and repair_strategy not in {"", "noop"} and repair_strategy not in trace_repairs:
                trace_repairs.append(repair_strategy)

            verifier_results = {}
            if isinstance(ctx.telemetry, dict) and isinstance(ctx.telemetry.get("verifier_results"), dict):
                verifier_results = dict(ctx.telemetry.get("verifier_results") or {})
            verifier_results["capability_runtime"] = verify_info
            if capability_failed_reasons:
                verifier_results["capability_failure"] = {
                    "class": capability_failure_class,
                    "failed": capability_failed_reasons,
                    "failed_codes": capability_failed_codes,
                }
            update_runtime_trace(
                ctx,
                tool_calls=list(ctx.tool_calls or []),
                verifier_results=verifier_results,
                repair_steps=trace_repairs,
            )

            if not verify_info.get("ok", True):
                gate_failed = [f"capability:{x}" for x in list(verify_info.get("failed") or [])]
                if gate_failed:
                    ctx.verified = False
                    ctx.delivery_blocked = True
                    ctx.errors.extend(gate_failed)
        except Exception as runtime_exc:
            ctx.errors.append(f"capability_runtime:{runtime_exc}")

        try:
            completion_gate = _evaluate_completion_gate(ctx)
            if not completion_gate.get("ok", True) and _normalize_action(getattr(ctx, "action", "")) in {"screen_workflow", "analyze_screen"}:
                repair_info = _repair_screen_completion(ctx)
                ctx.qa_results["screen_completion_repair"] = repair_info
                if repair_info.get("repaired"):
                    completion_gate = _evaluate_completion_gate(ctx)
            ctx.qa_results["completion_gate"] = completion_gate
            verifier_results = {}
            if isinstance(ctx.telemetry, dict) and isinstance(ctx.telemetry.get("verifier_results"), dict):
                verifier_results = dict(ctx.telemetry.get("verifier_results") or {})
            verifier_results["completion_gate"] = completion_gate
            update_runtime_trace(ctx, verifier_results=verifier_results)
            if not completion_gate.get("ok", True):
                gate_failed = [f"completion:{x}" for x in completion_gate.get("failed", [])]
                ctx.verified = False
                ctx.delivery_blocked = True
                ctx.errors.extend(gate_failed)
                marker = "❌ Completion gate failed:"
                if marker not in str(ctx.final_response or ""):
                    suffix = ", ".join(gate_failed) if gate_failed else "unknown"
                    ctx.final_response = f"{str(ctx.final_response or '').rstrip()}\n\n{marker} {suffix}"
        except Exception as completion_exc:
            ctx.errors.append(f"completion_gate:{completion_exc}")

        try:
            critic_prompt = build_critic_review_prompt(
                job_type=ctx.job_type,
                final_response=ctx.final_response,
                qa_results=ctx.qa_results,
                errors=ctx.errors,
            )
            if critic_prompt and getattr(agent, "llm", None) is not None:
                critic_role = str((getattr(ctx, "hybrid_model", {}) or {}).get("critic_role") or "critic")
                critic_text = await agent.llm.generate(
                    critic_prompt,
                    role=critic_role,
                    user_id=ctx.user_id,
                )
                critic_text = str(critic_text or "").strip()
                if critic_text:
                    ctx.qa_results["critic_review"] = {
                        "role": critic_role,
                        "text": critic_text,
                    }
                    if not ctx.verified and "Critic review:" not in str(ctx.final_response or ""):
                        ctx.final_response = f"{str(ctx.final_response or '').rstrip()}\n\nCritic review:\n{critic_text}"
        except Exception as critic_exc:
            ctx.errors.append(f"critic_review:{critic_exc}")

        try:
            ctx.phase_records["verify"] = {
                "phase": "Verify",
                "critic_model": dict((ctx.model_roles or {}).get("critic") or {}),
                "verified": bool(ctx.verified),
                "qa_results": dict(ctx.qa_results or {}),
                "errors": list(ctx.errors or []),
            }
        except Exception:
            pass

        if ctx.contract:
            try:
                # Artifact verification
                art_results = ctx.contract.verify_artifacts()
                ctx.qa_results["artifacts"] = art_results

                # QA checks
                qa_results = ctx.contract.run_qa()
                ctx.qa_results["qa"] = qa_results

                ctx.verified = (
                    art_results.get("found", 0) == art_results.get("total", 0) and
                    len(qa_results.get("failed", [])) == 0
                )
            except Exception as e:
                ctx.errors.append(f"verify: {e}")
                ctx.verified = False
        else:
            # No contract → inline delivery, skip verification
            if not (flag_enabled(ctx, "upgrade_verify_mandatory_gates", default=False) and ctx.delivery_blocked):
                ctx.verified = True

        ctx.stage_timings["verify"] = time.time() - t0
        return ctx


class StageDeliver(PipelineStage):
    """Stage 6: Response formatting + evidence gate."""
    name = "deliver"

    async def run(self, ctx: PipelineContext, agent) -> PipelineContext:
        t0 = time.time()

        # Evidence Gate enforcement
        try:
            from core.evidence_gate import evidence_gate
            ctx.final_response = evidence_gate.enforce(
                ctx.final_response or ctx.llm_response,
                ctx.tool_results
            )
            ctx.evidence_valid = not evidence_gate.has_delivery_claims(ctx.final_response) or \
                                 evidence_gate.has_real_evidence(ctx.tool_results)
            ctx.delivery_blocked = not ctx.evidence_valid
            if flag_enabled(ctx, "upgrade_verify_mandatory_gates", default=False) and not ctx.verified:
                ctx.evidence_valid = False
                ctx.delivery_blocked = True
        except Exception as e:
            ctx.errors.append(f"deliver: {e}")

        # Phase 19: Real-time Voice Feedback
        if ctx.channel == "voice" and (ctx.final_response or ctx.llm_response):
            try:
                from core.voice.text_to_speech import get_tts_service
                tts = get_tts_service()
                if tts:
                    # Asynchronously trigger speech synthesis
                    asyncio.create_task(tts.synthesize(ctx.final_response or ctx.llm_response))
                    logger.info("Voice feedback triggered")
            except Exception as e:
                logger.error(f"Voice feedback error: {e}")

        # Phase 17: Unified Memory Recording
        try:
            from core.memory.unified import memory
            # Record user input and bot response asynchronously
            asyncio.create_task(memory.remember(
                ctx.user_id, 
                ctx.user_input, 
                {"role": "user", "channel": ctx.channel}
            ))
            if ctx.final_response or ctx.llm_response:
                asyncio.create_task(memory.remember(
                    ctx.user_id, 
                    ctx.final_response or ctx.llm_response, 
                    {"role": "assistant", "channel": ctx.channel, "type": "response"}
                ))
        except Exception:
            pass

        # Experience learning loop: persist verified/partial runs for later strategy selection.
        try:
            action_name = str(ctx.action or "").strip().lower()
            if action_name not in {"", "chat", "communication", "unknown"}:
                from core.world_model import get_world_model

                if ctx.delivery_blocked:
                    success_score = 0.2
                elif ctx.verified:
                    success_score = 1.0
                elif str(ctx.final_response or ctx.llm_response or "").strip():
                    success_score = 0.65
                else:
                    success_score = 0.0

                get_world_model().record_experience(
                    user_id=ctx.user_id,
                    goal=ctx.user_input,
                    action=ctx.action,
                    job_type=ctx.job_type,
                    plan=ctx.plan,
                    tool_calls=ctx.tool_calls,
                    errors=ctx.errors,
                    final_response=ctx.final_response or ctx.llm_response,
                    verified=bool(ctx.verified and not ctx.delivery_blocked),
                    success_score=success_score,
                    metadata={
                        "channel": ctx.channel,
                        "requires_evidence": bool(ctx.requires_evidence),
                        "goal_stage_count": int(ctx.goal_stage_count or 1),
                        "world_domains": list((ctx.world_snapshot or {}).get("domains", []) or []),
                    },
                )
        except Exception:
            pass

        # Phase 22: Best Effort Delivery if blocked but informative
        if ctx.delivery_blocked and ctx.llm_response:
            strict_verify = flag_enabled(ctx, "upgrade_verify_mandatory_gates", default=False)
            if strict_verify:
                logger.warning("Pipeline: Evidence/verify gate blocked delivery (strict mode).")
            else:
                logger.warning("Pipeline: Evidence gate blocked delivery, but Best Effort mode is enabled.")
                # Allow delivery with a disclaimer
                ctx.final_response = ctx.llm_response + "\n\n> ⚠️ **Not:** İşlem gerçekleşti ancak sistem tarafından tam olarak doğrulanamadı."
                ctx.delivery_blocked = False
                ctx.evidence_valid = True

        # Job telemetry envelope (non-breaking, additive).
        try:
            if isinstance(ctx.telemetry, dict):
                if "verify_pass_rate" not in ctx.telemetry:
                    ctx.telemetry["verify_pass_rate"] = 1.0 if ctx.verified else 0.0
                record_pipeline_job(
                    {
                        "complexity_score": float(ctx.telemetry.get("complexity_score", ctx.complexity) or 0.0),
                        "token_cost_estimate": int(ctx.telemetry.get("token_cost_estimate", 0) or 0),
                        "tool_success_rate": float(ctx.telemetry.get("tool_success_rate", 0.0) or 0.0),
                        "verify_pass_rate": float(ctx.telemetry.get("verify_pass_rate", 0.0) or 0.0),
                        "repair_loops": int(ctx.telemetry.get("repair_loops", 0) or 0),
                        "ttfa_ms": int(ctx.telemetry.get("ttfa_ms", 0) or 0),
                        "orchestration_mode": str(ctx.capability_plan.get("orchestration_telemetry", {}).get("selected_mode", "single_agent"))
                        if isinstance(ctx.capability_plan, dict)
                        else "single_agent",
                    }
                )
        except Exception:
            pass

        try:
            final_status = "success" if ctx.verified and not ctx.delivery_blocked else "blocked" if ctx.delivery_blocked else "partial"
            if getattr(ctx, "requires_design_phase", False):
                _ensure_finish_branch_artifact(ctx)
                ctx.workflow_phase = "finished" if final_status == "success" else str(getattr(ctx, "workflow_phase", "") or "review_blocked")
                _sync_workflow_metadata(ctx)
            update_runtime_trace(
                ctx,
                tool_calls=list(ctx.tool_calls or []),
                delivery_mode=str(ctx.channel or "cli"),
                final_status=final_status,
            )
            ctx.phase_records["deliver"] = {
                "phase": "Deliver",
                "delivery_mode": str(ctx.channel or "cli"),
                "delivery_blocked": bool(ctx.delivery_blocked),
                "evidence_valid": bool(ctx.evidence_valid),
                "final_status": final_status,
            }
        except Exception:
            pass

        try:
            if getattr(ctx, "requires_design_phase", False) and final_status == "success":
                clear = getattr(agent, "_clear_workflow_session", None)
                if callable(clear):
                    clear(ctx.user_id, ctx.channel)
        except Exception:
            pass

        ctx.stage_timings["deliver"] = time.time() - t0
        return ctx


class PipelineRunner:
    """
    Modüler pipeline çalıştırıcı.
    
    Her stage bağımsız. Bir stage fail olursa pipeline durur.
    """

    def __init__(self):
        self.stages: List[PipelineStage] = [
            StageValidate(),
            StageRoute(),
            StagePlan(),
            StageExecute(),
            StageVerify(),
            StageDeliver(),
        ]

    async def run(self, ctx: PipelineContext, agent) -> PipelineContext:
        """Tüm stage'leri sırayla çalıştır."""
        for stage in self.stages:
            # Phase 20: Early exit or bypass for automation registration
            if ctx.role == "automation_reg" and stage.name not in ["route", "deliver"]:
                continue

            # Retry logic for critical execution stage
            max_retries = 2 if stage.name == "execute" else 1
            for attempt in range(max_retries):
                try:
                    t0 = time.time()
                    
                    # Apply Profiling
                    @stage_profiler.profile_stage(stage.name)
                    async def run_stage():
                        return await stage.run(ctx, agent)
                    
                    ctx = await run_stage()
                    ctx.stage_timings[stage.name] = time.time() - t0
                    logger.debug(f"Stage {stage.name}: OK ({ctx.stage_timings.get(stage.name, 0):.3f}s)")
                    break # Success, exit retry loop
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Stage {stage.name} failed (attempt {attempt+1}). Retrying...")
                        await asyncio.sleep(1)
                    else:
                        ctx.errors.append(f"{stage.name}: {e}")
                        logger.error(f"Stage {stage.name} failed after {max_retries} attempts: {e}")
                        break

            # Early exit on validation failure
            if stage.name == "validate" and not ctx.is_valid:
                break

        return ctx

    def get_timing_report(self, ctx: PipelineContext) -> str:
        """Stage timing raporu."""
        total = sum(ctx.stage_timings.values())
        lines = [f"Pipeline ({total:.3f}s):"]
        for name, duration in ctx.stage_timings.items():
            pct = (duration / total * 100) if total > 0 else 0
            lines.append(f"  {name}: {duration:.3f}s ({pct:.0f}%)")
        return "\n".join(lines)


# Global instance
pipeline_runner = PipelineRunner()
