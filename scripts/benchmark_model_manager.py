#!/usr/bin/env python3
"""Phase-0 benchmark for Elyan's model manager."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.model_manager import get_model_manager  # noqa: E402


def _format_report(report: dict[str, Any]) -> str:
    env = report["environment"]
    phase0 = report["phase0"]
    benchmark = report.get("benchmark", {})
    lines = [
        "Phase 0 Model Manager Report",
        f"  Shared embedder   : {phase0['shared_embedder']}",
        f"  Torch available   : {env['torch_available']}",
        f"  SentenceTransform : {env['sentence_transformers_available']}",
        f"  Backend           : {env['backend']}",
        f"  Device            : {env['device']}",
        f"  Process RSS (MB)  : {env['process_rss_mb']:.2f}",
        f"  Loaded models     : {len(env['cached_models'])}",
    ]
    if benchmark:
        lines.extend(
            [
                "  Benchmark",
                f"    load_seconds    : {benchmark['load_seconds']:.4f}",
                f"    encode_seconds  : {benchmark['encode_seconds']:.4f}",
                f"    vector_dimension: {benchmark['vector_dimension']}",
                f"    passed          : {benchmark['passed']}",
            ]
        )
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Elyan Phase 0 model manager")
    parser.add_argument("--model", default=None, help="Model spec to benchmark")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    parser.add_argument("--keep-cache", action="store_true", help="Benchmark without forcing a reload")
    args = parser.parse_args()

    manager = get_model_manager()
    benchmark = await manager.benchmark_model(
        args.model,
        force_reload=not args.keep_cache,
    )
    report = manager.get_phase0_report(args.model)
    report["benchmark"] = benchmark

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(_format_report(report))

    return 0 if bool(benchmark.get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

