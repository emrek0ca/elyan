from __future__ import annotations

import sys

from .dataset_builder import (
    NLUExample,
    build_nlu_dataset_from_runs,
    export_nlu_dataset_jsonl,
)
from .baseline_intent_model import NaiveBayesIntentModel


def get_phase1_engine():
    """
    Phase1 NLU is disabled on macOS by default because its numpy dependency
    can hard-crash the process in this environment.
    """
    if sys.platform == "darwin":
        return None

    from .phase1_engine import get_phase1_engine as _get_phase1_engine

    return _get_phase1_engine()


def __getattr__(name: str):
    if name in {"IntentTaxonomyEntry", "Phase1Decision", "Phase1NLUEngine"}:
        if sys.platform == "darwin":
            raise AttributeError(name)
        from .phase1_engine import (  # local import to avoid eager numpy load
            IntentTaxonomyEntry,
            Phase1Decision,
            Phase1NLUEngine,
        )

        return {
            "IntentTaxonomyEntry": IntentTaxonomyEntry,
            "Phase1Decision": Phase1Decision,
            "Phase1NLUEngine": Phase1NLUEngine,
        }[name]
    raise AttributeError(name)

__all__ = [
    "NLUExample",
    "build_nlu_dataset_from_runs",
    "export_nlu_dataset_jsonl",
    "NaiveBayesIntentModel",
    "get_phase1_engine",
]
