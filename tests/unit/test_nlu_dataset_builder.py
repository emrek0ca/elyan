import json
from pathlib import Path

from core.nlu.dataset_builder import build_nlu_dataset_from_runs, export_nlu_dataset_jsonl


def _write_run(root: Path, run_id: str, *, user_input: str, task_spec: dict, status: str) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "task.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "user_input": user_input,
                "task_spec": task_spec,
                "metadata": {"action": task_spec.get("intent", "")},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "summary.md").write_text(
        f"# Run Summary ({run_id})\n\n- Status: {status}\n",
        encoding="utf-8",
    )


def test_build_nlu_dataset_from_runs_marks_hard_negatives(tmp_path: Path):
    runs_root = tmp_path / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    task_spec = {
        "intent": "general_batch",
        "slots": {"app_name": "Safari"},
        "success_criteria": ["tool_success"],
        "steps": [
            {
                "id": "step_1",
                "action": "open_app",
                "params": {"app_name": "Safari"},
                "depends_on": [],
                "success_criteria": ["tool_success"],
            }
        ],
    }
    _write_run(
        runs_root,
        "run_1",
        user_input="safari ac",
        task_spec=task_spec,
        status="success",
    )

    feedback_path = tmp_path / "feedback.json"
    feedback_path.write_text(
        json.dumps(
            {
                "corrections": [
                    {
                        "user_id": 1,
                        "original_input": "safari ac",
                        "wrong_action": "screen_workflow",
                        "correction_text": "safariyi ac",
                    }
                ],
                "positives": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    rows = build_nlu_dataset_from_runs(
        runs_root,
        limit=10,
        include_synthetic=False,
        feedback_path=feedback_path,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.text == "safari ac"
    assert row.redacted_text
    assert row.intent == "general_batch"
    assert row.hard_negative is True
    assert row.slots.get("hard_negative_wrong_action") == "screen_workflow"
    assert row.depends_on.get("step_1") == []
    assert row.data_classification in {"operational", "workspace", "public"}
    assert row.learning_scope in {"local", "workspace", "global"}
    assert isinstance(row.shared_learning_eligible, bool)


def test_export_nlu_dataset_jsonl_writes_rows(tmp_path: Path):
    runs_root = tmp_path / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    task_spec = {
        "intent": "filesystem_batch",
        "steps": [
            {
                "id": "step_1",
                "action": "write_file",
                "params": {"path": "~/Desktop/a.txt"},
                "success_criteria": ["artifact_file_exists"],
            }
        ],
        "success_criteria": ["artifacts_expected_exist"],
    }
    _write_run(
        runs_root,
        "run_2",
        user_input="not yaz",
        task_spec=task_spec,
        status="success",
    )
    rows = build_nlu_dataset_from_runs(runs_root, limit=10, include_synthetic=False)
    out = export_nlu_dataset_jsonl(rows, tmp_path / "nlu.jsonl")
    assert out.exists()
    content = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(content) == 1
    payload = json.loads(content[0])
    assert payload["text"] == "not yaz"
    assert "redacted_text" in payload
    assert "data_classification" in payload
    assert "learning_scope" in payload
    assert "shared_learning_eligible" in payload
    assert "privacy_reason" in payload
    assert payload["intent"] == "filesystem_batch"


def test_build_nlu_dataset_from_runs_supports_summary_txt_and_label_confidence(tmp_path: Path):
    runs_root = tmp_path / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    run_dir = runs_root / "run_3"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "task.json").write_text(
        json.dumps(
            {
                "run_id": "run_3",
                "user_input": "ekrana bak",
                "task_spec": {
                    "intent": "screen_workflow",
                    "confidence": "High",
                    "steps": [{"id": "step_1", "action": "take_screenshot", "params": {}}],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "summary.txt").write_text("- Status: failed\n", encoding="utf-8")

    rows = build_nlu_dataset_from_runs(runs_root, limit=10, include_synthetic=False)

    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].confidence == 0.82


def test_build_nlu_dataset_redacts_personal_text(tmp_path: Path):
    runs_root = tmp_path / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    task_spec = {
        "intent": "contact_info",
        "steps": [{"id": "step_1", "action": "store_note", "params": {}}],
    }
    _write_run(
        runs_root,
        "run_4",
        user_input="emailim test@example.com",
        task_spec=task_spec,
        status="success",
    )

    rows = build_nlu_dataset_from_runs(runs_root, limit=5, include_synthetic=False)
    assert len(rows) == 1
    row = rows[0]
    assert row.data_classification == "personal"
    assert row.shared_learning_eligible is False
    assert row.privacy_reason == "personal_data_default_denied"
    assert "test@example.com" not in row.redacted_text
