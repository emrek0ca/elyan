"""
Agentic Loop — Observe → Plan → Act → Verify → Adjust cycle.

Wraps the existing pipeline with a feedback loop that:
1. Detects when verification fails
2. Analyzes the failure
3. Re-plans with error context
4. Re-executes with corrections
5. Repeats until success or max iterations

Integration: Called from process_envelope() after initial pipeline run.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.pipeline import PipelineContext

logger = logging.getLogger(__name__)

# Maximum retry iterations to prevent infinite loops
MAX_LOOP_ITERATIONS = 3

# Actions that are eligible for agentic loop (complex, verifiable)
LOOPABLE_ACTIONS = {
    "create_coding_project", "create_web_project_scaffold",
    "generate_document_pack", "research_document_delivery",
    "advanced_research", "write_file", "create_presentation",
    "create_coding_delivery_plan", "run_code",
}

# Actions that should never be looped (simple, chat, system)
NON_LOOPABLE_ACTIONS = {
    "chat", "greeting", "set_volume", "open_app", "open_url",
    "take_screenshot", "get_system_info", "get_weather",
    "get_time", "get_battery_status", "notification",
}


@dataclass
class LoopIteration:
    """Tracks a single iteration of the agentic loop."""
    iteration: int
    action: str = ""
    errors: List[str] = field(default_factory=list)
    verification_status: str = "pending"  # pending, passed, failed, skipped
    fix_applied: str = ""
    duration_ms: float = 0.0


@dataclass
class AgenticLoopResult:
    """Result of the full agentic loop execution."""
    iterations: List[LoopIteration] = field(default_factory=list)
    final_status: str = "success"  # success, partial, failed, skipped
    total_iterations: int = 0
    total_duration_ms: float = 0.0
    improvements_made: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "final_status": self.final_status,
            "total_iterations": self.total_iterations,
            "total_duration_ms": round(self.total_duration_ms, 1),
            "improvements_made": self.improvements_made,
            "iterations": [
                {
                    "iteration": it.iteration,
                    "action": it.action,
                    "errors": it.errors,
                    "verification_status": it.verification_status,
                    "fix_applied": it.fix_applied,
                    "duration_ms": round(it.duration_ms, 1),
                }
                for it in self.iterations
            ],
        }


def should_use_agentic_loop(ctx: "PipelineContext") -> bool:
    """
    Determine if the agentic loop should be used for this context.

    Returns True for complex, verifiable tasks that benefit from
    iterative refinement.
    """
    action = str(getattr(ctx, "action", "") or "").strip()

    # Explicit non-loopable
    if action in NON_LOOPABLE_ACTIONS:
        return False

    # Explicit loopable
    if action in LOOPABLE_ACTIONS:
        return True

    # Heuristic: complex tasks with high complexity score
    complexity = float(getattr(ctx, "complexity", 0.0) or 0.0)
    if complexity >= 0.6:
        return True

    # Code generation tasks
    if getattr(ctx, "is_code_job", False):
        return True

    # Multi-step plans
    plan = getattr(ctx, "plan", None)
    if isinstance(plan, list) and len(plan) >= 3:
        return True

    return False


def analyze_verification_failures(ctx: "PipelineContext") -> List[Dict[str, str]]:
    """
    Analyze verification results and extract actionable failure info.

    Returns a list of {type, description, suggestion} dicts.
    """
    failures = []

    # Check QA results
    qa = getattr(ctx, "qa_results", {}) or {}

    # Output contract failures
    output_contract = qa.get("output_contract", {})
    if isinstance(output_contract, dict):
        status = str(output_contract.get("status", "")).lower()
        if status in ("partial", "fail", "failed"):
            missing = output_contract.get("signals", {}).get("missing", [])
            if missing:
                failures.append({
                    "type": "output_contract",
                    "description": f"Eksik kalite kapıları: {', '.join(missing)}",
                    "suggestion": "Eksik kapıları tamamla: " + ", ".join(missing),
                })

    # Declared output contract failures
    declared = qa.get("declared_output_contract", {})
    if isinstance(declared, dict) and not declared.get("ok", True):
        errors = declared.get("errors", [])
        if errors:
            failures.append({
                "type": "declared_contract",
                "description": f"Çıktı sözleşmesi ihlali: {'; '.join(str(e) for e in errors[:3])}",
                "suggestion": "Çıktı sözleşmesini karşılayacak şekilde düzelt",
            })

    # Code validation failures
    errors = list(getattr(ctx, "errors", []) or [])
    for err in errors:
        err_str = str(err)
        if "code_validation_failed" in err_str:
            failures.append({
                "type": "code_validation",
                "description": "Üretilen kod doğrulamayı geçemedi",
                "suggestion": "Kod syntax hatalarını düzelt ve tekrar doğrula",
            })
        elif "timeout" in err_str.lower():
            failures.append({
                "type": "timeout",
                "description": f"Zaman aşımı: {err_str[:100]}",
                "suggestion": "İşlemi parçalara böl veya timeout süresini artır",
            })

    # Empty response for complex task
    response = str(getattr(ctx, "final_response", "") or "").strip()
    if not response and str(getattr(ctx, "action", "")) not in NON_LOOPABLE_ACTIONS:
        failures.append({
            "type": "empty_response",
            "description": "Karmaşık görev için boş yanıt üretildi",
            "suggestion": "Görevi basitleştirerek tekrar dene",
        })

    return failures


def build_correction_prompt(
    original_input: str,
    failures: List[Dict[str, str]],
    iteration: int,
) -> str:
    """
    Build a correction prompt that includes failure analysis
    for the LLM to use in the next iteration.
    """
    failure_descriptions = "\n".join(
        f"  - [{f['type']}] {f['description']}: {f['suggestion']}"
        for f in failures
    )

    return (
        f"[AGENTIC LOOP - Düzeltme İterasyonu {iteration}]\n"
        f"Orijinal görev: {original_input}\n\n"
        f"Önceki denemede şu sorunlar tespit edildi:\n{failure_descriptions}\n\n"
        f"Lütfen bu sorunları düzelterek görevi tekrar tamamla. "
        f"Her bir sorunu ayrı ayrı ele al."
    )


async def run_agentic_loop(ctx: "PipelineContext", agent) -> "PipelineContext":
    """
    Run the agentic loop on an already-executed pipeline context.

    This is called AFTER the initial pipeline run. It checks verification
    results and iteratively fixes issues.

    Flow:
    1. Check if agentic loop is needed
    2. Analyze verification failures
    3. If failures found, inject correction context and re-run execute+verify
    4. Repeat until success or MAX_LOOP_ITERATIONS
    5. Record learning data for future improvement

    Args:
        ctx: PipelineContext after initial pipeline run
        agent: The Agent instance

    Returns:
        Updated PipelineContext with improvements applied
    """
    loop_result = AgenticLoopResult()
    loop_start = time.perf_counter()

    if not should_use_agentic_loop(ctx):
        loop_result.final_status = "skipped"
        ctx.agentic_loop_result = loop_result.to_dict()
        return ctx

    # Record initial iteration (the one already done by pipeline)
    initial_iter = LoopIteration(
        iteration=0,
        action=str(getattr(ctx, "action", "") or ""),
        errors=list(str(e) for e in (getattr(ctx, "errors", []) or [])),
    )

    # Analyze initial verification
    failures = analyze_verification_failures(ctx)

    if not failures and not initial_iter.errors:
        initial_iter.verification_status = "passed"
        loop_result.iterations.append(initial_iter)
        loop_result.final_status = "success"
        loop_result.total_iterations = 1
        loop_result.total_duration_ms = (time.perf_counter() - loop_start) * 1000
        ctx.agentic_loop_result = loop_result.to_dict()
        return ctx

    initial_iter.verification_status = "failed"
    loop_result.iterations.append(initial_iter)

    logger.info(
        f"Agentic loop activated: {len(failures)} failures detected. "
        f"Starting correction cycle (max {MAX_LOOP_ITERATIONS} iterations)."
    )

    # Correction loop
    for iteration in range(1, MAX_LOOP_ITERATIONS + 1):
        iter_start = time.perf_counter()
        current_iter = LoopIteration(iteration=iteration)

        # Build correction prompt
        correction_prompt = build_correction_prompt(
            original_input=str(getattr(ctx, "user_input", "") or ""),
            failures=failures,
            iteration=iteration,
        )

        # Inject correction context into the pipeline context
        original_response = str(getattr(ctx, "final_response", "") or "")
        ctx.correction_context = correction_prompt
        ctx.correction_iteration = iteration
        ctx.errors = []  # Clear errors for retry

        # Re-run execute and verify stages only
        try:
            from core.pipeline import pipeline_runner

            # Run execute stage
            execute_stage = pipeline_runner.stages[3]  # StageExecute
            ctx = await execute_stage.run(ctx, agent)

            # Run verify stage
            verify_stage = pipeline_runner.stages[4]  # StageVerify
            ctx = await verify_stage.run(ctx, agent)

            current_iter.action = str(getattr(ctx, "action", "") or "")
            current_iter.errors = list(str(e) for e in (getattr(ctx, "errors", []) or []))

            # Re-analyze
            new_failures = analyze_verification_failures(ctx)

            if not new_failures and not current_iter.errors:
                current_iter.verification_status = "passed"
                current_iter.fix_applied = "; ".join(f["suggestion"] for f in failures)
                current_iter.duration_ms = (time.perf_counter() - iter_start) * 1000
                loop_result.iterations.append(current_iter)
                loop_result.improvements_made.append(
                    f"İterasyon {iteration}: {len(failures)} sorun düzeltildi"
                )

                # Add improvement note to response
                if ctx.final_response and original_response != ctx.final_response:
                    ctx.final_response += (
                        f"\n\n> 🔄 **Otonom Düzeltme:** {len(failures)} sorun tespit edildi "
                        f"ve {iteration} iterasyonda otomatik olarak düzeltildi."
                    )

                logger.info(f"Agentic loop: All issues resolved in iteration {iteration}")
                break
            else:
                current_iter.verification_status = "failed"
                current_iter.duration_ms = (time.perf_counter() - iter_start) * 1000
                loop_result.iterations.append(current_iter)
                failures = new_failures  # Update for next iteration
                logger.info(
                    f"Agentic loop iteration {iteration}: "
                    f"{len(new_failures)} failures remain"
                )

        except Exception as e:
            current_iter.verification_status = "failed"
            current_iter.errors.append(str(e))
            current_iter.duration_ms = (time.perf_counter() - iter_start) * 1000
            loop_result.iterations.append(current_iter)
            logger.error(f"Agentic loop iteration {iteration} failed: {e}")
            break

    # Determine final status
    last_iter = loop_result.iterations[-1] if loop_result.iterations else None
    if last_iter and last_iter.verification_status == "passed":
        loop_result.final_status = "success"
    elif any(it.verification_status == "passed" for it in loop_result.iterations):
        loop_result.final_status = "partial"
    else:
        loop_result.final_status = "failed"

    loop_result.total_iterations = len(loop_result.iterations)
    loop_result.total_duration_ms = (time.perf_counter() - loop_start) * 1000

    # Record learning data
    try:
        _record_loop_learning(ctx, loop_result, agent)
    except Exception as e:
        logger.debug(f"Failed to record loop learning: {e}")

    ctx.agentic_loop_result = loop_result.to_dict()
    return ctx


def _record_loop_learning(ctx: "PipelineContext", result: AgenticLoopResult, agent):
    """
    Feed agentic loop results back to the learning engine.
    This creates a feedback signal for future pattern improvement.
    """
    try:
        from core.learning_engine import get_learning_engine

        user_id = str(getattr(ctx, "user_id", "default") or "default")
        engine = get_learning_engine(user_id)

        action = str(getattr(ctx, "action", "") or "")
        success = result.final_status in ("success", "partial")

        # Record the interaction
        engine.record_interaction(
            tool=action,
            params={"user_input": str(getattr(ctx, "user_input", ""))[:200]},
            success=success,
        )

        # If loop had to correct, record what went wrong
        if result.total_iterations > 1:
            for iteration in result.iterations:
                if iteration.errors:
                    for error in iteration.errors:
                        engine.record_interaction(
                            tool=f"{action}_error",
                            params={"error": error[:200]},
                            success=False,
                        )

        logger.debug(
            f"Learning recorded: action={action}, "
            f"success={success}, iterations={result.total_iterations}"
        )
    except Exception as e:
        logger.debug(f"Learning recording failed: {e}")
