#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.intent_parser import IntentParser


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate parser intent accuracy on NLU dataset JSONL.")
    parser.add_argument("--dataset", required=True, help="Path to NLU dataset JSONL")
    return parser.parse_args()


def _load_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def main() -> int:
    args = _parse_args()
    dataset_path = Path(args.dataset).expanduser()
    rows = _load_rows(dataset_path)
    parser = IntentParser()

    total = 0
    action_ok = 0
    batch_intent_ok = 0
    hard_negative_total = 0
    hard_negative_ok = 0

    for row in rows:
        text = str(row.get("text") or "").strip()
        expected_intent = str(row.get("intent") or "").strip().lower()
        expected_action = str(row.get("action_label") or "").strip().lower()
        if not expected_action:
            steps = row.get("steps")
            if isinstance(steps, list) and steps and isinstance(steps[0], dict):
                expected_action = str(steps[0].get("action") or "").strip().lower()
        if not text or not expected_intent:
            continue
        total += 1
        result = parser.parse(text)
        predicted = str(result.get("action") or "").strip().lower() if isinstance(result, dict) else ""
        if predicted == expected_action:
            action_ok += 1
            if bool(row.get("hard_negative")):
                hard_negative_ok += 1
        if predicted == expected_intent:
            batch_intent_ok += 1
        if bool(row.get("hard_negative")):
            hard_negative_total += 1

    action_acc = (action_ok / total) if total else 0.0
    batch_intent_acc = (batch_intent_ok / total) if total else 0.0
    hard_negative_acc = (hard_negative_ok / hard_negative_total) if hard_negative_total else 0.0
    print(
        json.dumps(
            {
                "total": total,
                "action_accuracy": round(action_acc, 4),
                "batch_intent_accuracy": round(batch_intent_acc, 4),
                "hard_negative_total": hard_negative_total,
                "hard_negative_accuracy": round(hard_negative_acc, 4),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
