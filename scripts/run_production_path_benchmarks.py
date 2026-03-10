#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.runtime import run_production_benchmarks
from tests.e2e.test_production_path_reliability import _benchmark_cases


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Elyan production-path operator benchmarks.")
    parser.add_argument(
        "--reports-root",
        default=str(REPO_ROOT / "artifacts" / "production-benchmarks"),
        help="Directory where benchmark reports and task artifacts will be persisted.",
    )
    parser.add_argument(
        "--min-pass-count",
        type=int,
        default=5,
        help="Minimum pass count required for success.",
    )
    parser.add_argument(
        "--require-perfect",
        action="store_true",
        help="Fail unless every benchmark case passes.",
    )
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    root = Path(str(args.reports_root)).resolve()
    session_root = root / str(int(time.time() * 1000))
    workspace_root = session_root / "workspace"
    report = await run_production_benchmarks(_benchmark_cases(workspace_root), reports_root=session_root / "reports")
    summary = dict(report.get("summary") or {})
    summary_path = Path(str(report.get("report_root") or "")) / "summary.json"
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary_path.exists():
        return 1
    pass_count = int(summary.get("pass_count") or 0)
    total = int(summary.get("total") or 0)
    if total < int(args.min_pass_count or 0):
        return 1
    if pass_count < int(args.min_pass_count or 0):
        return 1
    if args.require_perfect and pass_count != total:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
