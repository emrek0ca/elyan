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
