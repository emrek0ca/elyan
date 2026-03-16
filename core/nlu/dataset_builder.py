from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from core.confidence import coerce_confidence
from core.text_artifacts import existing_text_path


@dataclass
class NLUExample:
    text: str
    intent: str
    action_label: str
    slots: Dict[str, Any]
    steps: List[Dict[str, Any]]
    depends_on: Dict[str, List[str]]
    success_criteria: List[str]
    confidence: float
    source: str
    hard_negative: bool
    run_id: str = ""
    status: str = ""


def _safe_load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


def _parse_run_status(run_dir: Path) -> str:
    summary = existing_text_path(run_dir / "summary.txt")
    if not summary.exists():
        return ""
    try:
        lines = summary.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return ""
    for line in lines:
        low = line.lower().strip()
        if low.startswith("- status:"):
            return line.split(":", 1)[1].strip().lower()
    return ""


def _dedupe_keep_order(items: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in items:
        val = str(item or "").strip()
        if not val or val in seen:
            continue
        seen.add(val)
        out.append(val)
    return out


def _extract_steps(task_spec: Dict[str, Any]) -> tuple[List[Dict[str, Any]], Dict[str, List[str]]]:
    raw_steps = task_spec.get("steps")
    if not isinstance(raw_steps, list):
        return [], {}

    rows: List[Dict[str, Any]] = []
    deps_map: Dict[str, List[str]] = {}
    for idx, step in enumerate(raw_steps, start=1):
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id") or "").strip() or f"step_{idx}"
        action = str(step.get("action") or "").strip().lower()
        depends = step.get("depends_on") if step.get("depends_on") is not None else step.get("dependencies")
        dep_list: List[str] = []
        if isinstance(depends, list):
            dep_list = [str(x).strip() for x in depends if str(x).strip()]
        elif isinstance(depends, str) and depends.strip():
            dep_list = [depends.strip()]
        dep_list = _dedupe_keep_order(dep_list)
        deps_map[step_id] = dep_list

        success_criteria = step.get("success_criteria")
        if not isinstance(success_criteria, list):
            success_criteria = []
        rows.append(
            {
                "id": step_id,
                "action": action,
                "params": step.get("params") if isinstance(step.get("params"), dict) else {},
                "depends_on": dep_list,
                "success_criteria": _dedupe_keep_order([str(x).strip() for x in success_criteria if str(x).strip()]),
            }
        )
    return rows, deps_map


def _extract_slots(task_spec: Dict[str, Any], steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    slots = task_spec.get("slots")
    if isinstance(slots, dict) and slots:
        return dict(slots)
    out: Dict[str, Any] = {}
    if steps:
        first_params = steps[0].get("params")
        if isinstance(first_params, dict):
            for key in ("app_name", "url", "path", "query", "topic", "browser", "text", "command", "combo"):
                val = first_params.get(key)
                if isinstance(val, str):
                    val = val.strip()
                    if not val:
                        continue
                if val is None:
                    continue
                out[key] = val
    return out


def _build_example(
    *,
    text: str,
    task_spec: Dict[str, Any],
    source: str,
    run_id: str = "",
    status: str = "",
    hard_negative: bool = False,
) -> NLUExample | None:
    utterance = str(text or "").strip()
    if not utterance:
        return None
    intent = str(task_spec.get("intent") or "").strip().lower()
    if not intent:
        return None
    steps, deps_map = _extract_steps(task_spec)
    slots = _extract_slots(task_spec, steps)
    success_criteria = task_spec.get("success_criteria")
    if not isinstance(success_criteria, list) or not success_criteria:
        success_criteria = []
        for step in steps:
            for row in list(step.get("success_criteria") or []):
                sval = str(row or "").strip()
                if sval:
                    success_criteria.append(sval)
    confidence = coerce_confidence(task_spec.get("confidence"), 0.0)
    return NLUExample(
        text=utterance,
        intent=intent,
        action_label=str(steps[0].get("action") or "").strip().lower() if steps else intent,
        slots=slots,
        steps=steps,
        depends_on=deps_map,
        success_criteria=_dedupe_keep_order([str(x).strip() for x in success_criteria if str(x).strip()]) or ["task_completed"],
        confidence=max(0.0, min(1.0, confidence)),
        source=str(source or "").strip() or "run_store",
        hard_negative=bool(hard_negative),
        run_id=str(run_id or "").strip(),
        status=str(status or "").strip().lower(),
    )


def _load_feedback_signals(feedback_path: Path | None) -> tuple[set[str], Dict[str, str]]:
    path = feedback_path or (Path.home() / ".elyan" / "feedback.json")
    if not path.exists():
        return set(), {}
    payload = _safe_load_json(path)
    corrections = payload.get("corrections")
    if not isinstance(corrections, list):
        return set(), {}
    originals: set[str] = set()
    wrong_action: Dict[str, str] = {}
    for item in corrections:
        if not isinstance(item, dict):
            continue
        original_input = str(item.get("original_input") or "").strip()
        wrong = str(item.get("wrong_action") or "").strip().lower()
        if original_input:
            originals.add(original_input.lower())
            if wrong:
                wrong_action[original_input.lower()] = wrong
    return originals, wrong_action


def _synthetic_paraphrases(text: str) -> List[str]:
    base = str(text or "").strip()
    if not base:
        return []
    variants = [
        f"lutfen {base}",
        f"{base} hemen",
        f"bunu yap: {base}",
        f"rica etsem {base}",
    ]
    return _dedupe_keep_order(variants)


def build_nlu_dataset_from_runs(
    runs_root: Path,
    *,
    limit: int = 10000,
    include_synthetic: bool = True,
    paraphrases_per_row: int = 1,
    feedback_path: Path | None = None,
) -> List[NLUExample]:
    root = Path(runs_root).expanduser()
    if not root.exists():
        return []

    correction_inputs, wrong_action_by_input = _load_feedback_signals(feedback_path)
    run_dirs = [p for p in root.iterdir() if p.is_dir()]
    run_dirs.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)

    examples: List[NLUExample] = []
    seen_pairs: set[tuple[str, str]] = set()
    max_rows = max(1, int(limit))
    para_count = max(0, int(paraphrases_per_row))

    for run_dir in run_dirs:
        if len(examples) >= max_rows:
            break
        task_path = run_dir / "task.json"
        if not task_path.exists():
            continue
        payload = _safe_load_json(task_path)
        if not payload:
            continue
        user_input = str(payload.get("user_input") or "").strip()
        task_spec = payload.get("task_spec") if isinstance(payload.get("task_spec"), dict) else {}
        if not user_input or not task_spec:
            continue

        status = _parse_run_status(run_dir)
        source = "run_store"
        if status in {"failed", "blocked"}:
            source = "run_store_failed"
        hard_negative = user_input.lower() in correction_inputs
        row = _build_example(
            text=user_input,
            task_spec=task_spec,
            source=source,
            run_id=run_dir.name,
            status=status,
            hard_negative=hard_negative,
        )
        if row is None:
            continue

        pair = (row.text.lower(), row.intent)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        examples.append(row)

        if hard_negative:
            wrong_action = wrong_action_by_input.get(user_input.lower(), "")
            if wrong_action:
                row.slots.setdefault("hard_negative_wrong_action", wrong_action)

        if include_synthetic and para_count > 0:
            generated = _synthetic_paraphrases(user_input)[:para_count]
            for variant in generated:
                if len(examples) >= max_rows:
                    break
                fake = _build_example(
                    text=variant,
                    task_spec=task_spec,
                    source="synthetic_paraphrase",
                    run_id=run_dir.name,
                    status=status,
                    hard_negative=hard_negative,
                )
                if fake is None:
                    continue
                fake_pair = (fake.text.lower(), fake.intent)
                if fake_pair in seen_pairs:
                    continue
                seen_pairs.add(fake_pair)
                examples.append(fake)

    return examples[:max_rows]


def export_nlu_dataset_jsonl(examples: List[NLUExample], output_path: Path) -> Path:
    out = Path(output_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [json.dumps(asdict(item), ensure_ascii=False) for item in examples]
    out.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    return out


__all__ = [
    "NLUExample",
    "build_nlu_dataset_from_runs",
    "export_nlu_dataset_jsonl",
]
