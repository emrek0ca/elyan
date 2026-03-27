from __future__ import annotations

from pathlib import Path

import pytest

import core.run_store as run_store_module
from core.workflow.vertical_runner import VerticalWorkflowRunner


@pytest.fixture(autouse=True)
def isolated_runs_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_RUNS_DIR", str(tmp_path / "runs"))
    run_store_module._run_store = None
    yield
    run_store_module._run_store = None


@pytest.mark.asyncio
async def test_document_flow_creates_export_ready_artifacts(tmp_path):
    runner = VerticalWorkflowRunner()
    record = await runner.start_workflow(
        task_type="document",
        title="Elyan Document Flow",
        brief="Create a concise technical brief for Elyan runtime architecture.",
        output_dir=str(tmp_path / "artifacts"),
        background=False,
    )

    assert record.status == "completed"
    assert record.task_type == "document"
    assert record.artifact_path
    assert Path(record.artifact_path).exists()
    assert record.review_report
    assert record.review_report["status"] == "passed"
    assert any(Path(item["path"]).suffix.lower() in {".docx", ".pdf", ".md"} for item in record.artifacts)


@pytest.mark.asyncio
async def test_presentation_flow_creates_pptx(tmp_path):
    runner = VerticalWorkflowRunner()
    record = await runner.start_workflow(
        task_type="presentation",
        title="Elyan Deck",
        brief="Prepare an executive product presentation about Elyan as an AI operating system.",
        output_dir=str(tmp_path / "artifacts"),
        background=False,
    )

    assert record.status == "completed"
    assert record.task_type == "presentation"
    assert record.review_report
    assert record.review_report["status"] == "passed"
    assert any(Path(item["path"]).suffix.lower() == ".pptx" for item in record.artifacts)


@pytest.mark.asyncio
async def test_website_flow_creates_react_scaffold(tmp_path):
    runner = VerticalWorkflowRunner()
    record = await runner.start_workflow(
        task_type="website",
        title="Elyan Site",
        brief="Build a premium React landing scaffold for Elyan with calm command center positioning.",
        output_dir=str(tmp_path / "artifacts"),
        background=False,
    )

    assert record.status == "completed"
    assert record.task_type == "website"
    assert record.artifact_path
    root = Path(record.artifact_path)
    assert root.exists()
    assert (root / "package.json").exists()
    assert (root / "README.md").exists()
    assert record.review_report
    assert record.review_report["status"] == "passed"


@pytest.mark.asyncio
async def test_document_flow_respects_requested_output_profile(tmp_path):
    runner = VerticalWorkflowRunner()
    record = await runner.start_workflow(
        task_type="document",
        title="Elyan PDF Brief",
        brief="Create a concise architecture brief as a PDF-only artifact.",
        audience="developer",
        language="en",
        preferred_formats=["pdf"],
        output_dir=str(tmp_path / "artifacts"),
        background=False,
    )

    assert record.status == "completed"
    assert any(Path(item["path"]).suffix.lower() == ".pdf" for item in record.artifacts)
    assert not any(Path(item["path"]).suffix.lower() == ".docx" for item in record.artifacts)
    scope_step = next(step for step in record.steps if step["name"] == "scope_workflow")
    assert scope_step["result"]["audience"] == "developer"
    assert scope_step["result"]["language"] == "en"
    assert scope_step["result"]["preferred_formats"] == ["pdf"]


@pytest.mark.asyncio
async def test_workflow_persists_template_routing_and_review_contract(tmp_path):
    runner = VerticalWorkflowRunner()
    record = await runner.start_workflow(
        task_type="website",
        title="Elyan Launch Site",
        brief="Build a premium website scaffold for Elyan with clear information architecture.",
        project_template_id="web-launch",
        project_name="Web Launch",
        routing_profile="quality_first",
        review_strictness="strict",
        output_dir=str(tmp_path / "artifacts"),
        background=False,
    )

    assert record.status == "completed"
    classify_step = next(step for step in record.steps if step["name"] == "classify_request")
    scope_step = next(step for step in record.steps if step["name"] == "scope_workflow")
    review_step = next(step for step in record.steps if step["name"] == "review_artifact_output")

    assert classify_step["result"]["routing_profile"] == "quality_first"
    assert classify_step["result"]["review_strictness"] == "strict"
    assert classify_step["result"]["candidate_chain"]
    assert scope_step["result"]["project_template_id"] == "web-launch"
    assert scope_step["result"]["project_name"] == "Web Launch"
    assert review_step["result"]["strictness"] == "strict"
