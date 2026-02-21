#!/usr/bin/env python3
"""
Regression checks for capability routing + pipeline foundations.

Run:
  python3 scripts/regression_capability_pipeline.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _assert(name: str, condition: bool, details: str = ""):
    if condition:
        print(f"[PASS] {name}")
        return
    extra = f" | {details}" if details else ""
    print(f"[FAIL] {name}{extra}")
    raise AssertionError(name)


def check_capability_router():
    from core.capability_router import get_capability_router

    router = get_capability_router()
    c1 = router.route("profesyonel bir website yap")
    c2 = router.route("bu kodu debug et")
    c3 = router.route("bunu ozetle")
    c4 = router.route("kurumsal rapor dokumani hazirla")
    c5 = router.route("bu ses kaydini transcribe et ve konusarak ozetle")
    c6 = router.route("oyun prototipi proje paketi üret")

    _assert("route.website", c1.domain == "website", f"{c1.domain}")
    _assert("route.code", c2.domain == "code", f"{c2.domain}")
    _assert("route.summary", c3.domain == "summarization", f"{c3.domain}")
    _assert("route.document", c4.domain == "document", f"{c4.domain}")
    _assert("route.multimodal", c5.domain == "multimodal", f"{c5.domain}")
    _assert("route.game_code", c6.domain == "code", f"{c6.domain}")


def check_intent_parser_website_priority():
    from core.intent_parser import IntentParser

    parser = IntentParser()
    text = "siyah beyaz temalı bir portfolyo sitesi oluştur html css js kullanarak"
    intent = parser.parse(text)
    _assert("intent.website.not_none", isinstance(intent, dict), str(intent))
    _assert("intent.website.multi_task", intent.get("action") == "multi_task", str(intent))
    tasks = intent.get("tasks", [])
    _assert("intent.website.has_write_file", any(t.get("action") == "write_file" for t in tasks), str(intent))


def check_contract_builder():
    from core.task_contract import build_task_contract

    req = {
        "capability_domain": "research",
        "primary_objective": "produce_reliable_multi_source_research",
        "output_artifacts": ["research_summary", "source_list"],
        "quality_checklist": ["source_quality", "traceability"],
    }
    contract = build_task_contract(req, task_count=5).to_dict()
    _assert("contract.domain", contract["capability_domain"] == "research")
    _assert("contract.objective", "research" in contract["objective"])
    _assert("contract.verify", contract["verification_method"] == "artifact_and_result_validation")


async def check_workflow_tools():
    from tools.pro_workflows import (
        create_web_project_scaffold,
        create_image_workflow_profile,
        generate_document_pack,
        create_software_project_pack,
    )

    out = str(ROOT / ".elyan")
    w = await create_web_project_scaffold("Regression Web", stack="react", output_dir=out)
    _assert("workflow.web.success", bool(w.get("success")), str(w))
    _assert("workflow.web.files", len(w.get("files_created", [])) >= 5, str(len(w.get("files_created", []))))

    i = await create_image_workflow_profile("Regression Visual", output_dir=out)
    _assert("workflow.image.success", bool(i.get("success")), str(i))
    _assert("workflow.image.files", len(i.get("files_created", [])) >= 2, str(len(i.get("files_created", []))))

    d = await generate_document_pack("Regression Docs", output_dir=out)
    _assert("workflow.doc.success", bool(d.get("success")), str(d))
    _assert("workflow.doc.outputs", len(d.get("outputs", [])) >= 3, str(len(d.get("outputs", []))))

    s = await create_software_project_pack("Regression Game", project_type="game", output_dir=out)
    _assert("workflow.software.success", bool(s.get("success")), str(s))
    _assert("workflow.software.files", len(s.get("files_created", [])) >= 6, str(len(s.get("files_created", []))))


def check_state_and_metrics():
    from core.pipeline_state import get_pipeline_state
    from core.capability_metrics import get_capability_metrics

    ps = get_pipeline_state()
    pid = ps.start(
        user_id="regression",
        user_input="demo pipeline",
        domain="website",
        tasks=[{"id": "task_1", "action": "create_web_project_scaffold", "description": "scaffold", "status": "pending"}],
    )
    ps.mark_task(pid, "task_1", True)
    active = ps.list_resume_candidates("regression")
    _assert("pipeline.active", len(active) >= 1, str(active))
    ps.complete(pid, True, "ok")
    active2 = ps.list_resume_candidates("regression")
    _assert("pipeline.complete", len(active2) == 0, str(active2))
    h = ps.history_summary(window_hours=72)
    _assert("pipeline.history_summary", int(h.get("history_count", 0)) >= 1, str(h))

    cm = get_capability_metrics()
    cm.record("website", True, 1200, "build_production_ready_web_artifact")
    cm.record("document", False, 2200, "generate_professional_document_bundle")
    s = cm.summary(window_hours=72)
    _assert("metrics.total", int(s.get("total", 0)) >= 2, str(s))
    _assert("metrics.domains", isinstance(s.get("domains", {}), dict), str(s))


def check_quality_engine():
    from core.artifact_quality_engine import get_artifact_quality_engine

    qe = get_artifact_quality_engine()
    report = qe.evaluate(
        domain="document",
        pipeline_id="pl_regression",
        task_contract={"quality_checklist": ["completeness", "correctness", "clarity"]},
        execution_result={
            "success": True,
            "succeeded": 2,
            "failed": 0,
            "data": {"results": [{"message": "ok", "data": {}}, {"message": "ok2", "data": {}}]},
        },
        tasks=[{"id": "task_1"}, {"id": "task_2"}],
        publish_threshold=70.0,
    )
    _assert("quality.score", float(report.get("overall_score", 0.0)) > 0, str(report))
    _assert("quality.publish_ready", bool(report.get("publish_ready")), str(report))

    summary = qe.summary(window_hours=72)
    _assert("quality.summary.total", int(summary.get("total", 0)) >= 1, str(summary))


def check_goal_graph_and_policy():
    from core.goal_graph import get_goal_graph_planner
    from core.operator_policy import get_operator_policy_engine

    graph = get_goal_graph_planner().build(
        "Önce pazar araştırması yap, sonra oyun kodla, ardından profesyonel rapor hazırla"
    )
    _assert("goal_graph.stage_count", int(graph.get("stage_count", 0)) >= 3, str(graph))
    _assert("goal_graph.chain", len(graph.get("workflow_chain", [])) >= 2, str(graph))
    constraints = graph.get("constraints", {})
    _assert("goal_graph.constraints", isinstance(constraints, dict), str(graph))
    _assert("goal_graph.constraints.deliverables", "game" in constraints.get("deliverables", []), str(constraints))

    policy_engine = get_operator_policy_engine()
    advisory = policy_engine.resolve("Advisory")
    trusted = policy_engine.resolve("Trusted")
    _assert("policy.advisory", not advisory.allow_destructive_actions, str(advisory))
    _assert("policy.trusted", trusted.allow_system_actions, str(trusted))


def check_clarification_gate():
    from core.task_engine import TaskEngine
    from core.capability_router import get_capability_router
    engine = TaskEngine.__new__(TaskEngine)
    engine.capability_router = get_capability_router()
    msg = engine._clarification_prompt(
        "dosya akışını optimize et",
        {"type": "UNKNOWN", "confidence": 0.0},
        {"capability_domain": "general", "goal_stage_count": 1},
    )
    _assert("clarification.gate", isinstance(msg, str) and len(msg) > 0, str(msg))


def check_plan_preview_builder():
    from core.task_engine import TaskEngine, TaskDefinition
    engine = TaskEngine.__new__(TaskEngine)
    req = {
        "capability_domain": "research",
        "primary_objective": "produce_reliable_multi_source_research",
        "goal_stage_count": 3,
        "goal_complexity_score": 0.72,
        "workflow_chain": ["research", "code", "document"],
    }
    tasks = [
        TaskDefinition(id="t1", action="advanced_research", params={}, description="r1", dependencies=[]),
        TaskDefinition(id="t2", action="create_software_project_pack", params={}, description="c1", dependencies=["t1"]),
        TaskDefinition(id="t3", action="generate_document_pack", params={}, description="d1", dependencies=["t2"]),
    ]
    preview = TaskEngine._build_explainability_preview(engine, req, tasks)
    _assert("preview.header", "Plan Preview" in preview, preview)
    _assert("preview.chain", "research -> code -> document" in preview, preview)
    _assert("preview.tasks", "advanced_research" in preview and "generate_document_pack" in preview, preview)


def check_plan_confirmation_policy():
    from core.task_engine import TaskEngine, TaskDefinition

    class _DummySettings:
        def get(self, key, default=None):
            if key == "require_plan_confirmation":
                return True
            return default

    engine = TaskEngine.__new__(TaskEngine)
    engine.settings = _DummySettings()
    engine._is_risky_action = lambda action: action in {"delete_file", "run_command"}

    req_complex = {"goal_stage_count": 3, "goal_complexity_score": 0.8}
    tasks = [
        TaskDefinition(id="t1", action="advanced_research", params={}, description="r1", dependencies=[]),
        TaskDefinition(id="t2", action="generate_document_pack", params={}, description="d1", dependencies=["t1"]),
    ]
    _assert("plan.confirm.complex", bool(TaskEngine._should_require_plan_confirmation(engine, req_complex, tasks)))

    req_simple = {"goal_stage_count": 1, "goal_complexity_score": 0.1}
    simple_tasks = [TaskDefinition(id="t1", action="read_file", params={}, description="x", dependencies=[])]
    _assert("plan.confirm.simple", not bool(TaskEngine._should_require_plan_confirmation(engine, req_simple, simple_tasks)))


async def check_learning_v2():
    from core.learning_engine import LearningEngine

    db_path = ROOT / ".elyan" / "learning_regression.db"
    if db_path.exists():
        db_path.unlink()
    engine = LearningEngine(db_path=db_path)
    await engine.record_outcome(
        domain="website",
        input_text="profesyonel website yap ve deploy et",
        execution_requirements={
            "preferred_output": "structured",
            "preferred_tools": ["create_web_project_scaffold", "generate_document_pack"],
            "quality_checklist": ["responsive", "testability", "maintainable"],
        },
        tool_actions=["create_web_project_scaffold", "generate_document_pack"],
        success=True,
        quality_score=88.0,
        publish_ready=True,
    )
    hints = engine.get_execution_hints("website yap ve deploy et", "website")
    _assert("learning.hints", bool(hints), str(hints))
    _assert("learning.hints.tools", isinstance(hints.get("preferred_tools_boost", []), list), str(hints))
    review = engine.self_review(window_days=7)
    _assert("learning.review", "recommendations" in review, str(review))


async def check_multimodal_tools():
    from tools.multimodal_tools import (
        create_visual_asset_pack,
        transcribe_audio_file,
        speak_text_local,
        get_multimodal_capability_report,
    )

    out = str(ROOT / ".elyan")
    p = await create_visual_asset_pack(
        "Regression Multimodal",
        brief="Elyan için premium launch visual set",
        output_dir=out,
    )
    _assert("multimodal.visual_pack.success", bool(p.get("success")), str(p))
    _assert("multimodal.visual_pack.files", len(p.get("files_created", [])) >= 4, str(p))

    # Runtime dependency may be missing in CI/local environment; ensure graceful fallback.
    t = await transcribe_audio_file(str(ROOT / "missing_audio.wav"))
    _assert("multimodal.transcribe.graceful", "success" in t and "error" in t, str(t))

    s = await speak_text_local("test", output_file="")
    _assert("multimodal.speak.graceful", "success" in s and ("error" in s or s.get("success")), str(s))

    r = await get_multimodal_capability_report()
    _assert("multimodal.capability.success", bool(r.get("success")), str(r))
    _assert("multimodal.capability.shape", isinstance(r.get("capabilities", {}), dict), str(r))


async def main():
    check_capability_router()
    check_intent_parser_website_priority()
    check_contract_builder()
    await check_workflow_tools()
    check_state_and_metrics()
    check_quality_engine()
    check_goal_graph_and_policy()
    check_clarification_gate()
    check_plan_preview_builder()
    check_plan_confirmation_policy()
    await check_learning_v2()
    await check_multimodal_tools()
    print("\nRegression suite completed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"\nRegression suite failed: {exc}")
        raise
