"""
Elyan Pipeline — Modüler İşlem Hattı

agent.py'nin 4715 satırlık monolitini 6 stage'e böler.
Her stage bağımsız test edilebilir.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time
from utils.logger import get_logger

logger = get_logger("pipeline")


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

    # Stage 3: Plan
    plan: List[Dict] = field(default_factory=list)
    needs_planning: bool = False

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
    evidence_valid: bool = False
    delivery_blocked: bool = False

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

        # Job type detection
        try:
            from core.job_templates import detect_job_type
            ctx.job_type = detect_job_type(ctx.user_input)
        except Exception:
            ctx.job_type = "communication"

        # Intent parsing
        if hasattr(agent, 'intent_parser'):
            try:
                ctx.intent = agent.intent_parser.parse(ctx.user_input)
                if isinstance(ctx.intent, dict):
                    ctx.action = str(ctx.intent.get("action", "")).lower()
            except Exception:
                pass

        logger.info(f"Route: {ctx.role}/{ctx.job_type} model={ctx.model} complexity={ctx.complexity}")
        ctx.stage_timings["route"] = time.time() - t0
        return ctx


class StageExecute(PipelineStage):
    """Stage 4: LLM call + tool execution."""
    name = "execute"

    async def run(self, ctx: PipelineContext, agent) -> PipelineContext:
        t0 = time.time()
        try:
            # 1. Health Checks & Locks
            from core.monitoring import get_resource_monitor
            from core.action_lock import action_lock
            from core.timeout_guard import with_timeout, LLM_TIMEOUT
            
            monitor = get_resource_monitor()
            health = monitor.get_health_snapshot()
            if health.status == "warning":
                ctx.final_response += f"> 💡 **Sistem Notu:** {', '.join(health.issues)}. İşlem biraz yavaş seyredebilir.\n\n"
            elif health.status == "critical":
                ctx.errors.append("Resource critical")
                ctx.final_response = f"⚠️ **İşlem Durduruldu:** Sistem kaynakları kritik seviyede ({', '.join(health.issues)})."
                return ctx

            # 2. CDG Engine Execution (for non-communication jobs)
            if ctx.job_type != "communication":
                from core.cdg_engine import cdg_engine
                from core.style_profile import style_profile
                
                logger.info(f"CDG Engine activated for job: {ctx.job_type}")
                job_id = f"job_{int(time.time())}"
                cdg_plan = cdg_engine.create_plan(job_id, ctx.job_type, ctx.user_input)
                
                async def cdg_executor(node):
                    patch_inst = node.params.pop("_auto_patch_instruction", "")
                    if node.action in ("plan", "refine"):
                        prompt = f"{style_profile.to_prompt_lines()}\n\nGirdi: {ctx.user_input}\nGörev: {node.name}\nAçıklama: Bu adımda ne yapılmalı planla.{patch_inst}"
                        resp = await agent.llm.generate(prompt)
                        return {"output": resp}
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

            # 3. Simple Communication / Chat Fallback
            else:
                logger.debug(f"Executing standard chat route for intent {ctx.action}")
                context_prefix = f"[MOD: {ctx.specialized_prompt}]\n\n" if ctx.specialized_prompt else ""
                full_prompt = f"{context_prefix}Docs: {ctx.context_docs}\n\nUser: {ctx.user_input}" if ctx.context_docs else f"{context_prefix}{ctx.user_input}"
                
                try:
                    chat_resp = await with_timeout(
                        agent.llm.generate(full_prompt, role=ctx.role, user_id=ctx.user_id),
                        seconds=LLM_TIMEOUT,
                        fallback="LLM timeout.",
                        context="pipeline_execute_chat"
                    )
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
            # StageExecute delegated to agent for now
            StageVerify(),
            StageDeliver(),
        ]

    async def run(self, ctx: PipelineContext, agent) -> PipelineContext:
        """Tüm stage'leri sırayla çalıştır."""
        for stage in self.stages:
            try:
                ctx = await stage.run(ctx, agent)
                logger.debug(f"Stage {stage.name}: OK ({ctx.stage_timings.get(stage.name, 0):.3f}s)")
            except Exception as e:
                ctx.errors.append(f"{stage.name}: {e}")
                logger.error(f"Stage {stage.name} failed: {e}")
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
