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
                elif g == "artifact_paths_nonempty":
                    ok = bool(artifacts)
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
