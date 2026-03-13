#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.nlu.dataset_builder import build_nlu_dataset_from_runs, export_nlu_dataset_jsonl
from core.storage_paths import resolve_runs_root


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build NLU dataset from Elyan run logs.")
    parser.add_argument(
        "--runs-root",
        default=str(resolve_runs_root()),
        help="Root directory that contains run folders with task.json",
    )
    parser.add_argument(
        "--output",
        default=str(Path("artifacts") / "nlu" / "nlu_dataset.jsonl"),
        help="Output JSONL path",
    )
    parser.add_argument("--limit", type=int, default=10000, help="Max dataset row count")
    parser.add_argument(
        "--paraphrases-per-row",
        type=int,
        default=1,
        help="Synthetic paraphrase rows to add per source row",
    )
    parser.add_argument(
        "--no-synthetic",
        action="store_true",
        help="Disable synthetic paraphrase generation",
    )
    parser.add_argument(
        "--feedback-path",
        default="",
        help="Optional feedback.json path for hard-negative labels",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    feedback_path = Path(args.feedback_path).expanduser() if str(args.feedback_path or "").strip() else None
    examples = build_nlu_dataset_from_runs(
        Path(args.runs_root).expanduser(),
        limit=max(1, int(args.limit)),
        include_synthetic=not bool(args.no_synthetic),
        paraphrases_per_row=max(0, int(args.paraphrases_per_row)),
        feedback_path=feedback_path,
    )
    out = export_nlu_dataset_jsonl(examples, Path(args.output).expanduser())

    hard_negatives = sum(1 for row in examples if row.hard_negative)
    source_counts: dict[str, int] = {}
    for row in examples:
        source_counts[row.source] = source_counts.get(row.source, 0) + 1
    report = {
        "rows": len(examples),
        "hard_negatives": hard_negatives,
        "sources": source_counts,
        "output": str(out),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
