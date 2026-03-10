#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BENCH_ROOT="${ELYAN_BENCH_REPORTS_ROOT:-$ROOT_DIR/artifacts/production-benchmarks}"
WORKFLOW_ROOT="${ELYAN_WORKFLOW_REPORTS_ROOT:-$ROOT_DIR/artifacts/emre-workflows}"
MIN_PASS_COUNT="${ELYAN_MIN_PASS_COUNT:-20}"

echo "Elyan production readiness check starting..."
cd "$ROOT_DIR"

echo "Checking environment..."
if [ ! -f ".env" ]; then
  echo "Error: .env file missing."
  exit 1
fi

echo "Checking core dependencies..."
python3 -c "import aiohttp, click, httpx, rich" >/dev/null

echo "Running production benchmark gate..."
python3 scripts/run_production_path_benchmarks.py \
  --reports-root "$BENCH_ROOT" \
  --min-pass-count "$MIN_PASS_COUNT" \
  --require-perfect

echo "Running hero workflow pack..."
python3 scripts/run_emre_workflow_pack.py \
  --reports-root "$WORKFLOW_ROOT"

echo "Production readiness is GREEN."
echo "Benchmark reports: $BENCH_ROOT"
echo "Workflow reports: $WORKFLOW_ROOT"
