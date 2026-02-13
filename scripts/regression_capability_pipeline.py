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

    _assert("route.website", c1.domain == "website", f"{c1.domain}")
    _assert("route.code", c2.domain == "code", f"{c2.domain}")
    _assert("route.summary", c3.domain == "summarization", f"{c3.domain}")
    _assert("route.document", c4.domain == "document", f"{c4.domain}")


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
    )

    out = str(ROOT / ".wiqo")
    w = await create_web_project_scaffold("Regression Web", stack="react", output_dir=out)
    _assert("workflow.web.success", bool(w.get("success")), str(w))
    _assert("workflow.web.files", len(w.get("files_created", [])) >= 5, str(len(w.get("files_created", []))))

    i = await create_image_workflow_profile("Regression Visual", output_dir=out)
    _assert("workflow.image.success", bool(i.get("success")), str(i))
    _assert("workflow.image.files", len(i.get("files_created", [])) >= 2, str(len(i.get("files_created", []))))

    d = await generate_document_pack("Regression Docs", output_dir=out)
    _assert("workflow.doc.success", bool(d.get("success")), str(d))
    _assert("workflow.doc.outputs", len(d.get("outputs", [])) >= 3, str(len(d.get("outputs", []))))


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

    cm = get_capability_metrics()
    cm.record("website", True, 1200, "build_production_ready_web_artifact")
    cm.record("document", False, 2200, "generate_professional_document_bundle")
    s = cm.summary(window_hours=72)
    _assert("metrics.total", int(s.get("total", 0)) >= 2, str(s))
    _assert("metrics.domains", isinstance(s.get("domains", {}), dict), str(s))


async def main():
    check_capability_router()
    check_contract_builder()
    await check_workflow_tools()
    check_state_and_metrics()
    print("\nRegression suite completed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"\nRegression suite failed: {exc}")
        raise

