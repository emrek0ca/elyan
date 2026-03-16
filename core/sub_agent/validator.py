from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from .session import SubAgentResult, SubAgentSession


@dataclass
class ValidationResult:
    passed: bool
    failed_gates: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    should_retry: bool = False


class SubAgentValidator:
    """Validates sub-agent output against deterministic gates."""

    @staticmethod
    def _payload_dict(result_payload: Any) -> Dict[str, Any]:
        return dict(result_payload) if isinstance(result_payload, dict) else {}

    @staticmethod
    def _quality_summary(result_payload: Any) -> Dict[str, Any]:
        payload = SubAgentValidator._payload_dict(result_payload)
        summary = payload.get("quality_summary")
        return dict(summary) if isinstance(summary, dict) else {}

    @staticmethod
    def _gate_research_contract_complete(result_payload: Any) -> bool:
        payload = SubAgentValidator._payload_dict(result_payload)
        contract = payload.get("research_contract")
        if not isinstance(contract, dict):
            return False
        required = ("claim_list", "citation_map", "critical_claim_ids", "uncertainty_log", "conflicts")
        return all(key in contract for key in required)

    @staticmethod
    def _gate_claim_coverage_full(result_payload: Any) -> bool:
        quality = SubAgentValidator._quality_summary(result_payload)
        try:
            return float(quality.get("claim_coverage", 0.0) or 0.0) >= 1.0
        except Exception:
            return False

    @staticmethod
    def _gate_critical_claim_support(result_payload: Any) -> bool:
        quality = SubAgentValidator._quality_summary(result_payload)
        try:
            return float(quality.get("critical_claim_coverage", 0.0) or 0.0) >= 1.0
        except Exception:
            return False

    @staticmethod
    def _gate_uncertainty_section_present(result_payload: Any) -> bool:
        quality = SubAgentValidator._quality_summary(result_payload)
        if "uncertainty_section_present" not in quality:
            return False
        return bool(quality.get("uncertainty_section_present"))

    @staticmethod
    def _gate_claim_map_present(result_payload: Any, artifacts: List[str]) -> bool:
        payload = SubAgentValidator._payload_dict(result_payload)
        claim_map_path = str(payload.get("claim_map_path") or "").strip()
        if claim_map_path:
            try:
                if Path(claim_map_path).expanduser().exists():
                    return True
            except Exception:
                pass
        return any(str(item).endswith("claim_map.json") for item in list(artifacts or []))

    @staticmethod
    def _gate_revision_summary_present(result_payload: Any, artifacts: List[str]) -> bool:
        payload = SubAgentValidator._payload_dict(result_payload)
        revision_path = str(payload.get("revision_summary_path") or "").strip()
        if revision_path:
            try:
                if Path(revision_path).expanduser().exists():
                    return True
            except Exception:
                pass
        return any(
            str(item).endswith("revision_summary.txt")
            or str(item).endswith(".revision_summary.txt")
            or str(item).endswith("revision_summary.md")
            or str(item).endswith(".revision_summary.md")
            for item in list(artifacts or [])
        )

    @staticmethod
    def _gate_tests_written_first(result_payload: Any) -> bool:
        payload = SubAgentValidator._payload_dict(result_payload)
        return bool(payload.get("tests_written_first", False))

    @staticmethod
    def _gate_failing_test_observed(result_payload: Any) -> bool:
        payload = SubAgentValidator._payload_dict(result_payload)
        return bool(payload.get("failing_test_observed", False))

    @staticmethod
    def _gate_tests_pass_after_change(result_payload: Any) -> bool:
        payload = SubAgentValidator._payload_dict(result_payload)
        return bool(payload.get("tests_pass_after_change", False))

    @staticmethod
    def _gate_task_scope_respected(result_payload: Any) -> bool:
        payload = SubAgentValidator._payload_dict(result_payload)
        return bool(payload.get("task_scope_respected", False))

    @staticmethod
    def _gate_review_passed(result_payload: Any) -> bool:
        payload = SubAgentValidator._payload_dict(result_payload)
        return bool(payload.get("review_passed", False))

    @staticmethod
    def _gate_artifact_bundle_complete(result_payload: Any, artifacts: List[str]) -> bool:
        payload = SubAgentValidator._payload_dict(result_payload)
        if "artifact_bundle_complete" in payload:
            return bool(payload.get("artifact_bundle_complete"))
        return bool(list(artifacts or []))

    def _gate_file_exists(self, path: str) -> bool:
        return Path(path).expanduser().exists()

    def _gate_file_not_empty(self, path: str) -> bool:
        p = Path(path).expanduser()
        return p.exists() and p.stat().st_size > 0

    def _gate_valid_json(self, path: str) -> bool:
        p = Path(path).expanduser()
        json.loads(p.read_text(encoding="utf-8"))
        return True

    def _gate_valid_html(self, path: str) -> bool:
        p = Path(path).expanduser()
        return "<html" in p.read_text(encoding="utf-8", errors="ignore").lower()

    def _gate_valid_python(self, path: str) -> bool:
        p = Path(path).expanduser()
        compile(p.read_text(encoding="utf-8"), str(p), "exec")
        return True

    @staticmethod
    def _gate_has_content(text: Any) -> bool:
        return len(str(text or "").strip()) > 50

    @staticmethod
    def _gate_no_placeholder(text: Any) -> bool:
        low = str(text or "").lower()
        markers = ("todo", "tbd", "lorem ipsum", "{{", "}}", "placeholder")
        return not any(marker in low for marker in markers)

    @staticmethod
    def _gate_tool_success(result_payload: Any) -> bool:
        if isinstance(result_payload, dict):
            success = result_payload.get("success")
            if isinstance(success, bool):
                return success
            if "error" in result_payload and result_payload.get("error"):
                return False
        return True

    async def validate(self, result: SubAgentResult, gates: List[str]) -> ValidationResult:
        failed: List[str] = []
        issues: List[str] = []

        artifacts = list(result.artifacts or [])
        payload_text = result.result if isinstance(result.result, str) else str(result.result)

        for gate in list(gates or []):
            g = str(gate or "").strip().lower()
            try:
                if g == "file_exists":
                    ok = bool(artifacts and all(self._gate_file_exists(p) for p in artifacts))
                elif g == "file_not_empty":
                    ok = bool(artifacts and all(self._gate_file_not_empty(p) for p in artifacts))
                elif g == "valid_json":
                    ok = bool(artifacts and all(self._gate_valid_json(p) for p in artifacts))
                elif g == "valid_html":
                    ok = bool(artifacts and all(self._gate_valid_html(p) for p in artifacts))
                elif g == "valid_python":
                    ok = bool(artifacts and all(self._gate_valid_python(p) for p in artifacts))
                elif g == "has_content":
                    ok = self._gate_has_content(payload_text)
                elif g == "no_placeholder":
                    ok = self._gate_no_placeholder(payload_text)
                elif g == "tool_success":
                    ok = self._gate_tool_success(result.result)
                elif g == "research_contract_complete":
                    ok = self._gate_research_contract_complete(result.result)
                elif g == "claim_coverage_full":
                    ok = self._gate_claim_coverage_full(result.result)
                elif g == "critical_claim_support":
                    ok = self._gate_critical_claim_support(result.result)
                elif g == "uncertainty_section_present":
                    ok = self._gate_uncertainty_section_present(result.result)
                elif g == "claim_map_present":
                    ok = self._gate_claim_map_present(result.result, artifacts)
                elif g == "revision_summary_present":
                    ok = self._gate_revision_summary_present(result.result, artifacts)
                elif g == "tests_written_first":
                    ok = self._gate_tests_written_first(result.result)
                elif g == "failing_test_observed":
                    ok = self._gate_failing_test_observed(result.result)
                elif g == "tests_pass_after_change":
                    ok = self._gate_tests_pass_after_change(result.result)
                elif g == "task_scope_respected":
                    ok = self._gate_task_scope_respected(result.result)
                elif g == "review_passed":
                    ok = self._gate_review_passed(result.result)
                elif g == "artifact_bundle_complete":
                    ok = self._gate_artifact_bundle_complete(result.result, artifacts)
                elif g == "artifact_paths_nonempty":
                    ok = bool(artifacts)
                elif g == "artifact_or_content":
                    ok = bool(artifacts) or self._gate_has_content(payload_text)
                else:
                    ok = True
            except Exception as exc:
                ok = False
                issues.append(f"{g}: {exc}")

            if not ok:
                failed.append(g)

        return ValidationResult(
            passed=not failed,
            failed_gates=failed,
            issues=issues,
            should_retry=bool(failed),
        )

    async def validate_and_retry(
        self,
        executor,
        session: SubAgentSession,
        gates: List[str],
        max_retries: int = 2,
    ) -> tuple[SubAgentResult, ValidationResult]:
        retries = max(0, min(5, int(max_retries or 0)))
        last_result = await executor.run(session)
        validation = await self.validate(last_result, gates)

        while validation.should_retry and retries > 0:
            retries -= 1
            session.task.context.setdefault("validation_issues", []).extend(validation.failed_gates)
            last_result = await executor.run(session)
            validation = await self.validate(last_result, gates)

        return last_result, validation


__all__ = ["SubAgentValidator", "ValidationResult"]
