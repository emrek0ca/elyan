#!/usr/bin/env python3
"""Elyan ML fine-tune worker.

This script is dependency-aware:
- If PyTorch/HuggingFace/LoRA are available, it performs a small adapter fine-tune.
- Otherwise it writes a deterministic fallback report and exits successfully.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _module_available(name: str) -> bool:
  try:
    return importlib.util.find_spec(name) is not None
  except Exception:
    return False


def _now() -> str:
  return datetime.now(timezone.utc).isoformat()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
  rows: list[dict[str, Any]] = []
  if not path.exists():
    return rows

  for line in path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
      continue
    try:
      item = json.loads(line)
      if isinstance(item, dict):
        rows.append(item)
    except Exception:
      continue
  return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _dataset_rows(dataset: list[dict[str, Any]]) -> list[dict[str, Any]]:
  rows: list[dict[str, Any]] = []
  for row in dataset:
    input_text = str(row.get("input") or "").strip()
    output_text = str(row.get("output") or "").strip()
    better_output = str(row.get("better_output") or "").strip()
    reasoning_trace = row.get("reasoning_trace")
    score = row.get("score")
    accepted = bool(row.get("accepted", True))

    if not accepted:
      continue

    if not isinstance(score, (int, float)) or not math.isfinite(float(score)) or float(score) < 0.6:
      continue

    if isinstance(reasoning_trace, list):
      reasoning_text = "\n".join(str(item).strip() for item in reasoning_trace if str(item).strip())
    else:
      reasoning_text = str(reasoning_trace or "").strip()

    if not input_text or not output_text or not better_output:
      continue
    rows.append(
      {
        "input": input_text,
        "output": output_text,
        "better_output": better_output,
        "reasoning_trace": reasoning_text,
        "score": float(score),
        "prompt": "\n".join(
          [
            f"Input: {input_text}",
            f"Output: {output_text}",
            f"Better Output: {better_output}",
            f"Reasoning Trace: {reasoning_text}" if reasoning_text else "Reasoning Trace:",
            "Score:",
          ]
        ).strip(),
      }
    )
  return rows


def _format_example(row: dict[str, Any]) -> str:
  reasoning_trace = str(row.get("reasoning_trace") or "").strip()
  return "\n".join(
    [
      f"Input: {row['input']}",
      f"Output: {row['output']}",
      f"Better Output: {row['better_output']}",
      f"Reasoning Trace: {reasoning_trace}" if reasoning_trace else "Reasoning Trace:",
      f"Score: {row.get('score', '')}",
    ]
  ).strip() + "\n"


def _fallback_report(
  *,
  dataset_path: Path,
  output_dir: Path,
  base_model: str,
  reason: str,
  train_rows: int,
  eval_rows: int,
) -> dict[str, Any]:
  report = {
    "ok": True,
    "status": "fallback",
    "fallback": True,
    "reason": reason,
    "base_model": base_model,
    "dataset_path": str(dataset_path),
    "output_dir": str(output_dir),
    "train_samples": train_rows,
    "eval_samples": eval_rows,
    "metrics": {
      "loss": None,
      "perplexity": None,
    },
    "artifacts": [],
    "created_at": _now(),
  }
  _write_json(output_dir / "training-report.json", report)
  return report


def _run_fallback(
  *,
  dataset_path: Path,
  output_dir: Path,
  base_model: str,
  reason: str,
  rows: list[dict[str, Any]],
) -> dict[str, Any]:
  split_index = max(1, int(len(rows) * 0.9)) if rows else 0
  train_rows = rows[:split_index]
  eval_rows = rows[split_index:]
  return _fallback_report(
    dataset_path=dataset_path,
    output_dir=output_dir,
    base_model=base_model,
    reason=reason,
    train_rows=len(train_rows),
    eval_rows=len(eval_rows),
  )


@dataclass
class TrainingArgs:
  dataset: Path
  output_dir: Path
  base_model: str
  run_dir: Path


def _parse_args() -> TrainingArgs:
  parser = argparse.ArgumentParser(description="Elyan ML fine-tune worker")
  parser.add_argument("--dataset", required=True)
  parser.add_argument("--output-dir", required=True)
  parser.add_argument("--base-model", required=True)
  parser.add_argument("--run-dir", required=True)
  args = parser.parse_args()
  return TrainingArgs(
    dataset=Path(args.dataset),
    output_dir=Path(args.output_dir),
    base_model=str(args.base_model),
    run_dir=Path(args.run_dir),
  )


def _train_with_hf(config: TrainingArgs, rows: list[dict[str, Any]]) -> dict[str, Any]:
  import torch
  from datasets import Dataset
  from peft import LoraConfig, TaskType, get_peft_model
  from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForLanguageModeling,
    Trainer,
    TrainingArguments,
  )

  config.output_dir.mkdir(parents=True, exist_ok=True)
  config.run_dir.mkdir(parents=True, exist_ok=True)

  formatted = [_format_example(row) for row in rows if row["output"]]
  if not formatted:
    return _fallback_report(
      dataset_path=config.dataset,
      output_dir=config.output_dir,
      base_model=config.base_model,
      reason="dataset contained no trainable examples",
      train_rows=0,
      eval_rows=0,
    )

  split_index = max(1, int(len(formatted) * 0.9)) if len(formatted) > 1 else len(formatted)
  train_texts = formatted[:split_index]
  eval_texts = formatted[split_index:] if split_index < len(formatted) else formatted[:1]

  tokenizer = AutoTokenizer.from_pretrained(config.base_model, use_fast=True)
  if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

  train_dataset = Dataset.from_dict({"text": train_texts})
  eval_dataset = Dataset.from_dict({"text": eval_texts})

  def tokenize(batch: dict[str, list[str]]) -> dict[str, Any]:
    return tokenizer(batch["text"], truncation=True, max_length=512)

  train_dataset = train_dataset.map(tokenize, batched=True, remove_columns=["text"])
  eval_dataset = eval_dataset.map(tokenize, batched=True, remove_columns=["text"])

  model = AutoModelForCausalLM.from_pretrained(config.base_model)

  model_type = getattr(model.config, "model_type", "")
  if model_type in {"gpt2", "gpt_neo", "gptj"}:
    target_modules = ["c_attn", "c_proj"]
  else:
    target_modules = ["q_proj", "v_proj"]

  lora_config = LoraConfig(
    task_type=TaskType.CAUSAL_LM,
    r=8,
    lora_alpha=16,
    lora_dropout=0.05,
    target_modules=target_modules,
  )
  model = get_peft_model(model, lora_config)
  model.print_trainable_parameters()

  use_cuda = torch.cuda.is_available()
  training_args = TrainingArguments(
    output_dir=str(config.output_dir),
    per_device_train_batch_size=1,
    per_device_eval_batch_size=1,
    num_train_epochs=1,
    learning_rate=2e-4,
    logging_steps=10,
    save_strategy="epoch",
    evaluation_strategy="epoch",
    report_to=[],
    fp16=use_cuda,
    save_total_limit=1,
    remove_unused_columns=False,
    load_best_model_at_end=False,
  )

  data_collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)
  trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=eval_dataset,
    data_collator=data_collator,
  )

  train_result = trainer.train()
  eval_result = trainer.evaluate()

  model.save_pretrained(config.output_dir)
  tokenizer.save_pretrained(config.output_dir)

  loss = float(eval_result.get("eval_loss") or 0.0)
  perplexity = math.exp(loss) if loss > 0 else None
  report = {
    "ok": True,
    "status": "trained",
    "fallback": False,
    "base_model": config.base_model,
    "dataset_path": str(config.dataset),
    "output_dir": str(config.output_dir),
    "train_samples": len(train_texts),
    "eval_samples": len(eval_texts),
    "metrics": {
      "train_loss": float(train_result.training_loss or 0.0),
      "eval_loss": loss,
      "perplexity": perplexity,
    },
    "artifacts": [
      str(config.output_dir / "adapter_config.json"),
      str(config.output_dir / "adapter_model.safetensors"),
      str(config.output_dir / "tokenizer.json"),
    ],
    "created_at": _now(),
  }
  _write_json(config.run_dir / "training-report.json", report)
  _write_json(config.output_dir / "training-report.json", report)
  return report


def main() -> int:
  args = _parse_args()
  dataset = _load_jsonl(args.dataset)
  rows = _dataset_rows(dataset)

  args.output_dir.mkdir(parents=True, exist_ok=True)
  args.run_dir.mkdir(parents=True, exist_ok=True)

  if not rows:
    report = _fallback_report(
      dataset_path=args.dataset,
      output_dir=args.output_dir,
      base_model=args.base_model,
      reason="dataset is empty",
      train_rows=0,
      eval_rows=0,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0

  required_modules = ["torch", "datasets", "transformers", "peft"]
  missing = [name for name in required_modules if not _module_available(name)]
  if missing:
    report = _run_fallback(
      dataset_path=args.dataset,
      output_dir=args.output_dir,
      base_model=args.base_model,
      reason=f"missing python dependencies: {', '.join(missing)}",
      rows=rows,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0

  if not args.base_model.strip():
    report = _run_fallback(
      dataset_path=args.dataset,
      output_dir=args.output_dir,
      base_model=args.base_model,
      reason="base model is not configured",
      rows=rows,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0

  try:
    report = _train_with_hf(args, rows)
  except Exception as exc:
    report = _run_fallback(
      dataset_path=args.dataset,
      output_dir=args.output_dir,
      base_model=args.base_model,
      reason=str(exc),
      rows=rows,
    )

  print(json.dumps(report, ensure_ascii=False))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
