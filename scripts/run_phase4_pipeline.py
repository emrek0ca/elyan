#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.phase4_pipeline import Phase4Pipeline, Phase4Sample  # noqa: E402
from core.learning_engine import get_learning_engine  # noqa: E402
from core.training_system import get_training_system  # noqa: E402


def _demo_samples() -> list[Phase4Sample]:
    return [
        Phase4Sample("merhaba", "greeting", "Merhaba! Nasıl yardımcı olabilirim?", source="demo", confidence=1.0),
        Phase4Sample("pytorch hakkında araştırma yap", "research", "PyTorch hakkında güncel ve kaynaklı bir araştırma hazırla.", source="demo", confidence=1.0),
        Phase4Sample("landing page üret", "website", "Tek sayfa, modern ve temiz bir landing page üret.", source="demo", confidence=1.0),
        Phase4Sample("excel tablosu hazırla", "spreadsheet", "Düzenli bir Excel tablosu oluştur.", source="demo", confidence=1.0),
    ]


def _format_summary(run: dict[str, object]) -> str:
    metrics = dict(run.get("metrics") or {})
    bundle = dict(run.get("bundle") or {})
    benchmark = dict(run.get("benchmark") or {})
    lines = [
        "Phase 4 pipeline run",
        f"  model_id   : {run.get('model_id')}",
        f"  version    : {run.get('version')}",
        f"  status     : {run.get('status')}",
        f"  samples    : {run.get('samples')}",
        f"  accuracy   : {float(metrics.get('accuracy') or 0):.3f}",
        f"  macro_f1   : {float(metrics.get('macro_f1') or 0):.3f}",
        f"  bundle     : {bundle.get('root') or 'n/a'}",
        f"  onnx_ready : {bundle.get('onnx_ready')}",
        f"  latency_ms : {float(benchmark.get('latency_ms') or 0):.3f}",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Elyan Phase 4 fine-tuning pipeline")
    parser.add_argument("--model-id", default="intent_router")
    parser.add_argument("--name", default="Intent Router")
    parser.add_argument("--base-model", default="local-proto")
    parser.add_argument("--version", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-deploy", action="store_true")
    parser.add_argument("--no-export-onnx", action="store_true")
    parser.add_argument("--no-bundle", action="store_true")
    parser.add_argument("--no-benchmark", action="store_true")
    parser.add_argument("--use-live-learning", action="store_true")
    args = parser.parse_args()

    pipeline = Phase4Pipeline()
    samples = _demo_samples()

    if args.use_live_learning:
        training_system = get_training_system()
        learning_engine = get_learning_engine()
        collected = pipeline.collect_training_examples(
            training_system=training_system,
            learning_engine=learning_engine,
        )
        if collected:
            samples = collected

    run = pipeline.run_end_to_end(
        model_id=args.model_id,
        name=args.name,
        base_model=args.base_model,
        samples=samples,
        version=args.version,
        deploy=not args.no_deploy and not args.dry_run,
        export_onnx=not args.no_export_onnx and not args.dry_run,
        build_bundle=not args.no_bundle and not args.dry_run,
        benchmark=not args.no_benchmark and not args.dry_run,
    )

    payload = run.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_format_summary(payload))
        if args.dry_run:
            print("\nDry-run mode: bundle/export/deploy/benchmark were skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
