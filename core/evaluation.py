from __future__ import annotations

from typing import Any

from core.personalization import get_personalization_manager
from core.reliability import get_regression_evaluator


class EvaluationSuite:
    def __init__(self, *, regression_evaluator: Any | None = None, personalization: Any | None = None) -> None:
        self.regression_evaluator = regression_evaluator or get_regression_evaluator()
        self.personalization = personalization or get_personalization_manager()

    def run(self, target_id: str = "", suite_name: str = "offline") -> dict[str, Any]:
        suite = str(suite_name or "offline").strip().lower()
        if suite not in {"offline", "regression", "default"}:
            suite = "offline"
        return {
            "suite_name": suite,
            "target_id": str(target_id or ""),
            "reliability": self.regression_evaluator.run_offline_suite(str(target_id or "")),
            "personalization": self.personalization.get_status(),
        }

    def summary(self) -> dict[str, Any]:
        return self.run("", "offline")


_suite: EvaluationSuite | None = None


def get_evaluation_suite() -> EvaluationSuite:
    global _suite
    if _suite is None:
        _suite = EvaluationSuite()
    return _suite
