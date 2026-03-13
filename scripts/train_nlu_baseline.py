#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from core.nlu.baseline_intent_model import NaiveBayesIntentModel


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a baseline intent model (naive bayes) from NLU JSONL dataset.")
    parser.add_argument("--dataset", required=True, help="Path to NLU dataset JSONL")
    parser.add_argument(
        "--label-field",
        default="action_label",
        choices=["action_label", "intent"],
        help="Label field to learn (action_label is recommended for parser parity).",
    )
    parser.add_argument(
        "--model-out",
        default=str(Path("artifacts") / "nlu" / "baseline_intent_model.json"),
        help="Output model file path",
    )
    parser.add_argument(
        "--eval-ratio",
        type=float,
        default=0.2,
        help="Holdout ratio for offline evaluation (0-0.9)",
    )
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


def _is_eval_row(text: str, ratio: float) -> bool:
    digest = hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()
    bucket = int(digest[:8], 16) / float(0xFFFFFFFF)
    return bucket < ratio


def main() -> int:
    args = _parse_args()
    ratio = max(0.0, min(0.9, float(args.eval_ratio)))
    label_key = str(args.label_field or "action_label")
    rows = _load_rows(Path(args.dataset).expanduser())

    train_x: list[str] = []
    train_y: list[str] = []
    eval_x: list[str] = []
    eval_y: list[str] = []

    for row in rows:
        text = str(row.get("text") or "").strip()
        label = str(row.get(label_key) or "").strip().lower()
        if not text or not label:
            continue
        if _is_eval_row(text, ratio):
            eval_x.append(text)
            eval_y.append(label)
        else:
            train_x.append(text)
            train_y.append(label)

    model = NaiveBayesIntentModel().fit(train_x, train_y)
    model_path = model.save(Path(args.model_out).expanduser())

    correct = 0
    total = 0
    for text, expected in zip(eval_x, eval_y):
        predicted, _confidence = model.predict(text)
        total += 1
        if predicted == expected:
            correct += 1
    acc = (correct / total) if total else 0.0

    report = {
        "train_rows": len(train_x),
        "eval_rows": len(eval_x),
        "label_field": label_key,
        "labels": len(model.labels),
        "eval_accuracy": round(acc, 4),
        "model_out": str(model_path),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
