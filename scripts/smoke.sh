#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

echo "[SMOKE] doctor"
bash scripts/doctor.sh

echo "[SMOKE] py_compile"
"$PY" -m py_compile core/agent.py core/pipeline.py core/spec/task_spec.py

echo "[SMOKE] unit subset"
"$PY" -m pytest \
  tests/unit/test_agent_routing.py::test_agent_infer_multi_task_intent_numbered_file_flow \
  tests/unit/test_agent_routing.py::test_agent_process_executes_numbered_plan_steps \
  tests/unit/test_pipeline.py \
  -q

echo "[SMOKE] tamam"

