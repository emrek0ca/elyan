from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VerificationCheck:
    code: str
    passed: bool
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {"code": self.code, "passed": bool(self.passed)}
        if self.message:
            payload["message"] = self.message
        if self.details:
            payload["details"] = dict(self.details)
        return payload


@dataclass
class VerificationResult:
    status: str
    checks: list[VerificationCheck] = field(default_factory=list)
    failed_codes: list[str] = field(default_factory=list)
    repairable: bool = True
    summary: str = ""
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "success" and not self.failed_codes

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "checks": [item.to_dict() for item in self.checks],
            "failed": list(self.failed_codes),
            "failed_codes": list(self.failed_codes),
            "repairable": bool(self.repairable),
            "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
            "metrics": dict(self.metrics),
        }

    @classmethod
    def from_checks(
        cls,
        checks: list[VerificationCheck],
        *,
        summary: str = "",
        evidence_refs: list[dict[str, Any]] | None = None,
        metrics: dict[str, Any] | None = None,
        repairable: bool = True,
    ) -> "VerificationResult":
        failed_codes = [item.code for item in checks if not item.passed]
        status = "success" if not failed_codes else "failed"
        return cls(
            status=status,
            checks=list(checks),
            failed_codes=failed_codes,
            repairable=bool(repairable),
            summary=summary,
            evidence_refs=list(evidence_refs or []),
            metrics=dict(metrics or {}),
        )


__all__ = ["VerificationCheck", "VerificationResult"]
