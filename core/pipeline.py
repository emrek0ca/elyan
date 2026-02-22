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

    # Stage 1: Validate
    is_valid: bool = True
    validation_error: str = ""

    # Stage 2: Route
    role: str = "inference"
    model: str = ""
    provider: str = ""
    complexity: float = 0.3
    reasoning_budget: str = "low"
    intent: Dict = field(default_factory=dict)
    action: str = ""
    job_type: str = "communication"

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
        # Execution delegated to agent.process() for now
        # This stage will be fully extracted in phase 2
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
