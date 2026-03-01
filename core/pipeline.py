"""
Elyan Pipeline — Modüler İşlem Hattı

agent.py'nin 4715 satırlık monolitini 6 stage'e böler.
Her stage bağımsız test edilebilir.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time
import re
from utils.logger import get_logger
from core.reasoning.stage_profiler import stage_profiler
from tools import AVAILABLE_TOOLS

logger = get_logger("pipeline")


_NON_ACTIONABLE_INTENTS = {"", "chat", "unknown", "communication", "answer", "respond", "direct", "show_help"}


def _normalize_action(action: Any) -> str:
    return str(action or "").strip().lower()


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


def _job_type_from_action(action: str, current: str) -> str:
    cur = str(current or "communication").strip().lower() or "communication"
    if cur != "communication":
        return cur
    act = _normalize_action(action)
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
        addendum_parts.append(f"Güven skoru (otomatik): %{int(round(auto_conf * 100))}")

    if not has_risk_section:
        missing.append("risks")
        addendum_parts.append("Açık riskler:")
        addendum_parts.append("- Bazı kaynaklar güncellik/doğruluk açısından manuel teyit gerektirebilir.")

    addendum_text = ""
    if addendum_parts:
        addendum_text = "\n\nAraştırma kalite özeti:\n" + "\n".join(addendum_parts)

    return {
        "missing": missing,
        "sources_found": source_count,
        "confidence_estimate": round(auto_conf, 2),
        "addendum": addendum_text,
    }


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
    if not isinstance(inferred, dict):
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
    logger.info("Route rescue via LLM intent: action=%s c=%.2f", ctx.action, confidence)
    return True


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
    preferred_tools: List[str] = field(default_factory=list)
    multi_agent_recommended: bool = False
    goal_graph: Dict[str, Any] = field(default_factory=dict)
    goal_stage_count: int = 1
    goal_complexity: float = 0.0
    goal_constraints: Dict[str, Any] = field(default_factory=dict)
    workflow_chain: List[str] = field(default_factory=list)
    requires_evidence: bool = False

    # Stage 3: Plan
    plan: List[Dict] = field(default_factory=list)
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

        if not user_input:
            ctx.is_valid = False
            ctx.validation_error = "Boş girdi"
            ctx.final_response = "Bir şey yazmalısın."
        elif len(user_input) > 50000:
            ctx.is_valid = False
            ctx.validation_error = "Çok uzun girdi"
            ctx.final_response = "Mesaj çok uzun (max 50K karakter)."
            
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
            return ctx
            
        # 1. Action-Lock Check
        from core.action_lock import action_lock
        ctx.status_prefix = action_lock.get_status_prefix()
        if action_lock.is_locked:
            if any(kw in user_input.lower() for kw in ["dur", "iptal", "cancel", "stop"]):
                action_lock.unlock()
                ctx.is_valid = False
                ctx.final_response = "Üretim modu durduruldu ve kilit açıldı."
                return ctx
            ctx.is_valid = False
            ctx.final_response = f"{ctx.status_prefix}Şu an bir göreve odaklanmış durumdayım. İptal etmek için 'iptal' yazabilirsin."
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
                        "complexity_tier": str(getattr(cap_plan, "complexity_tier", "low") or "low"),
                        "suggested_job_type": str(getattr(cap_plan, "suggested_job_type", "communication") or "communication"),
                        "orchestration_mode": str(getattr(cap_plan, "orchestration_mode", "single_agent") or "single_agent"),
                        "preferred_tools": list(ctx.preferred_tools),
                    }

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
            if looks_multi_step and hasattr(agent, "_infer_multi_task_intent"):
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

        # Last-mile rescue with LLM JSON tool intent when deterministic routing could not map an action.
        try:
            llm_threshold = max(0.5, float(capability_override_threshold or 0.5))
        except Exception:
            llm_threshold = 0.5
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

        ctx.stage_timings["route"] = time.time() - t0
        return ctx


class StagePlan(PipelineStage):
    """Stage 3: Task decomposition and planning."""
    name = "plan"

    async def run(self, ctx: PipelineContext, agent) -> PipelineContext:
        t0 = time.time()
        if not ctx.needs_planning:
            ctx.stage_timings["plan"] = 0
            return ctx

        try:
            from core.intelligent_planner import IntelligentPlanner
            from core.job_templates import get_template
            from config.elyan_config import elyan_config
            planner = IntelligentPlanner()
            logger.info("IntelligentPlanner activated for context decomposition.")

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

        ctx.stage_timings["plan"] = time.time() - t0
        return ctx


class StageExecute(PipelineStage):
    """Stage 4: LLM call + tool execution."""
    name = "execute"

    async def run(self, ctx: PipelineContext, agent) -> PipelineContext:
        t0 = time.time()
        try:
            if ctx.delivery_blocked and ctx.final_response:
                ctx.stage_timings["execute"] = time.time() - t0
                return ctx

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
                direct_text = await agent._run_direct_intent(
                    ctx.intent, ctx.user_input, ctx.role, [], user_id=ctx.user_id
                )
                if direct_text is not None:
                    # Post-proof: set_wallpaper sonrası ekran görüntüsü
                    if ctx.action == "set_wallpaper":
                        try:
                            if "take_screenshot" in AVAILABLE_TOOLS:
                                shot = await agent._execute_tool("take_screenshot", {"filename": "wallpaper_proof.png"}, user_input=ctx.user_input, step_name="Kanıt SS")
                                proof_txt = agent._format_result_text(shot)
                                if proof_txt:
                                    direct_text += f"\nKanıt: {proof_txt}"
                        except Exception:
                            pass
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
                should_use_team = team_mode_enabled and (
                    ctx.team_mode_forced
                    or ctx.complexity >= team_mode_threshold
                    or team_complexity_signal
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
                        team_result = await team.execute_project(ctx.user_input)
                        team_status = str(getattr(team_result, "status", "success") or "success").lower()
                        summary = str(getattr(team_result, "summary", "") or "")
                        if summary:
                            ctx.final_response += summary
                        elif team_status == "success":
                            ctx.final_response += "✅ Team mode görevi tamamladı."
                        else:
                            ctx.final_response += "⚠️ Team mode kısmi sonuç üretti."
                        outputs = list(getattr(team_result, "outputs", []) or [])
                        if outputs:
                            ctx.tool_results.extend(outputs)
                        if team_status == "success":
                            if action_lock.is_locked:
                                action_lock.unlock()
                            ctx.stage_timings["execute"] = time.time() - t0
                            return ctx
                        logger.warning(
                            "Team mode incomplete (status=%s). Falling back to orchestrator/CDG.",
                            team_status,
                        )
                        ctx.errors.append(f"team_mode_incomplete:{team_status}")
                        ctx.final_response += "\nStandart orkestrasyon ile devam ediyorum...\n"
                    except Exception as team_exc:
                        logger.warning(f"Team mode failed, falling back to standard orchestration: {team_exc}")

                should_use_multi_agent = (
                    ctx.complexity >= multi_agent_complexity_threshold
                    or (ctx.multi_agent_recommended and ctx.capability_confidence >= multi_agent_capability_threshold)
                    or (
                        str(ctx.capability_plan.get("orchestration_mode", "single_agent")) == "multi_agent"
                        and ctx.capability_confidence >= multi_agent_capability_threshold
                    )
                )
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
                        return res if isinstance(res, dict) else {"output": str(res)}
                
                cdg_plan = await cdg_engine.execute(cdg_plan, cdg_executor)
                manifest = cdg_engine.get_evidence_manifest(cdg_plan)
                
                overall_success = cdg_plan.status == "passed"
                ctx.tool_results = [n.result for n in cdg_plan.nodes]
                
                if overall_success:
                    base_msg = "✅ İşlem tamamlandı."
                    if manifest["artifacts"]:
                        paths = [a.get("path") for a in manifest["artifacts"] if a.get("path")]
                        base_msg += f"\nÜretilen dosyalar: {', '.join(paths)}"
                else:
                    logger.warning("CDG failed, generating fallback assistant response.")
                    fallback_prompt = (
                        f"{style_profile.to_prompt_lines()}\n\n"
                        f"Kullanıcı isteği: {ctx.user_input}\n"
                        "Plan yürütmesi başarısız oldu. Kullanıcıya kısa, yardımcı ve uygulanabilir bir yanıt ver."
                    )
                    try:
                        base_msg = await agent.llm.generate(fallback_prompt, role=ctx.role, user_id=ctx.user_id)
                    except Exception as fallback_exc:
                        ctx.errors.append(f"cdg_fallback_chat_failed: {fallback_exc}")
                        base_msg = "❌ İşlem sırasında hatalar oluştu."
                
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
                    if ctx.memory_context: prompt_parts.append(f"Memory:\n{ctx.memory_context}")
                    if ctx.multimodal_context: prompt_parts.append(f"Multimodal Context:\n{ctx.multimodal_context}")
                    if ctx.context_docs: prompt_parts.append(f"Knowledge:\n{ctx.context_docs}")
                    prompt_parts.append(f"User: {ctx.user_input}")
                    
                    full_prompt = "\n\n".join(prompt_parts)
                    
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

        # Phase 22: Best Effort Delivery if blocked but informative
        if ctx.delivery_blocked and ctx.llm_response:
            logger.warning("Pipeline: Evidence gate blocked delivery, but Best Effort mode is enabled.")
            # Allow delivery with a disclaimer
            ctx.final_response = ctx.llm_response + "\n\n> ⚠️ **Not:** İşlem gerçekleşti ancak sistem tarafından tam olarak doğrulanamadı."
            ctx.delivery_blocked = False
            ctx.evidence_valid = True 

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
