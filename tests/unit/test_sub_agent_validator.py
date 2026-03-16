import pytest

from core.sub_agent.validator import SubAgentValidator
from core.sub_agent.session import SubAgentResult


@pytest.mark.asyncio
async def test_validator_file_gates(tmp_path):
    f = tmp_path / "a.json"
    f.write_text('{"ok": true}', encoding="utf-8")

    validator = SubAgentValidator()
    result = SubAgentResult(status="success", result={"success": True}, artifacts=[str(f)])
    verdict = await validator.validate(result, ["file_exists", "file_not_empty", "valid_json"])

    assert verdict.passed is True


@pytest.mark.asyncio
async def test_validator_no_placeholder_gate_fails():
    validator = SubAgentValidator()
    result = SubAgentResult(status="success", result="TODO: daha sonra", artifacts=[])
    verdict = await validator.validate(result, ["no_placeholder"])

    assert verdict.passed is False
    assert "no_placeholder" in verdict.failed_gates


@pytest.mark.asyncio
async def test_validator_no_placeholder_gate_fails_for_lowercase_markers():
    validator = SubAgentValidator()
    result = SubAgentResult(status="success", result="tbd: placeholder metin", artifacts=[])
    verdict = await validator.validate(result, ["no_placeholder"])

    assert verdict.passed is False
    assert "no_placeholder" in verdict.failed_gates


@pytest.mark.asyncio
async def test_validator_tool_success_gate_checks_error_payload():
    validator = SubAgentValidator()
    result = SubAgentResult(status="partial", result={"success": False, "error": "boom"}, artifacts=[])
    verdict = await validator.validate(result, ["tool_success"])

    assert verdict.passed is False
    assert "tool_success" in verdict.failed_gates


@pytest.mark.asyncio
async def test_validator_artifact_or_content_gate_accepts_artifact():
    validator = SubAgentValidator()
    result = SubAgentResult(status="success", result={"success": True}, artifacts=["/tmp/example.txt"])
    verdict = await validator.validate(result, ["artifact_or_content"])

    assert verdict.passed is True


@pytest.mark.asyncio
async def test_validator_research_quality_gates_accept_complete_payload(tmp_path):
    claim_map = tmp_path / "claim_map.json"
    claim_map.write_text("{}", encoding="utf-8")
    revision = tmp_path / "revision_summary.txt"
    revision.write_text("# ok\n", encoding="utf-8")

    validator = SubAgentValidator()
    result = SubAgentResult(
        status="success",
        result={
            "success": True,
            "research_contract": {
                "claim_list": [],
                "citation_map": {},
                "critical_claim_ids": [],
                "uncertainty_log": [],
                "conflicts": [],
            },
            "quality_summary": {
                "claim_coverage": 1.0,
                "critical_claim_coverage": 1.0,
                "uncertainty_section_present": True,
            },
            "claim_map_path": str(claim_map),
            "revision_summary_path": str(revision),
        },
        artifacts=[str(claim_map), str(revision)],
    )
    verdict = await validator.validate(
        result,
        [
            "research_contract_complete",
            "claim_coverage_full",
            "critical_claim_support",
            "uncertainty_section_present",
            "claim_map_present",
            "revision_summary_present",
        ],
    )

    assert verdict.passed is True


@pytest.mark.asyncio
async def test_validator_workflow_execution_gates_accept_complete_payload():
    validator = SubAgentValidator()
    result = SubAgentResult(
        status="success",
        result={
            "success": True,
            "tests_written_first": True,
            "failing_test_observed": True,
            "tests_pass_after_change": True,
            "task_scope_respected": True,
            "review_passed": True,
            "artifact_bundle_complete": True,
        },
        artifacts=["/tmp/proof.txt"],
    )
    verdict = await validator.validate(
        result,
        [
            "tests_written_first",
            "failing_test_observed",
            "tests_pass_after_change",
            "task_scope_respected",
            "review_passed",
            "artifact_bundle_complete",
        ],
    )

    assert verdict.passed is True


@pytest.mark.asyncio
async def test_validator_workflow_execution_gates_fail_when_red_green_missing():
    validator = SubAgentValidator()
    result = SubAgentResult(
        status="partial",
        result={
            "success": True,
            "tests_written_first": False,
            "failing_test_observed": False,
            "tests_pass_after_change": True,
            "task_scope_respected": True,
            "review_passed": True,
            "artifact_bundle_complete": True,
        },
        artifacts=["/tmp/proof.txt"],
    )
    verdict = await validator.validate(
        result,
        ["tests_written_first", "failing_test_observed", "tests_pass_after_change"],
    )

    assert verdict.passed is False
    assert "tests_written_first" in verdict.failed_gates
    assert "failing_test_observed" in verdict.failed_gates
