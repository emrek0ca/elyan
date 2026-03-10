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

from core.runtime import run_emre_workflow_pack
from tests.e2e.test_production_path_reliability import _benchmark_cases


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Emre workflow preset pack on Elyan's production path.")
    parser.add_argument(
        "--reports-root",
        default=str(REPO_ROOT / "artifacts" / "emre-workflows"),
        help="Directory where workflow reports and benchmark artifacts will be persisted.",
    )
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    root = Path(str(args.reports_root)).resolve()
    session_root = root / str(int(time.time() * 1000))
    workspace_root = session_root / "workspace"
    report = await run_emre_workflow_pack(_benchmark_cases(workspace_root), reports_root=session_root / "reports")
    print(json.dumps(report.get("summary") or {}, ensure_ascii=False, indent=2))
    return 0 if bool(report.get("success")) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
