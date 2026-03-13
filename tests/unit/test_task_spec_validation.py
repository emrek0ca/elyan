from core.spec.task_spec import validate_task_spec, TASK_SPEC_SCHEMA_VERSION


def _base_spec(intent: str):
    return {
        "task_id": "task_test_1",
        "intent": intent,
        "version": TASK_SPEC_SCHEMA_VERSION,
        "goal": "test",
        "user_goal": "test",
        "entities": {"topic": "test"},
        "deliverables": [{"name": "test-output", "kind": "response", "required": True}],
        "constraints": {},
        "context_assumptions": [],
        "artifacts_expected": [],
        "checks": [],
        "rollback": [],
        "required_tools": ["write_file"],
        "tool_candidates": ["write_file"],
        "priority": "normal",
        "risk_level": "low",
        "success_criteria": ["task_completed"],
        "timeouts": {"step_timeout_s": 10, "run_timeout_s": 60},
        "retries": {"max_attempts": 1},
        "steps": [],
    }


def test_validate_task_spec_filesystem_batch_ok():
    spec = _base_spec("filesystem_batch")
    spec["steps"] = [
        {"id": "s1", "action": "mkdir", "path": "~/Desktop/a"},
        {"id": "s2", "action": "write_file", "path": "~/Desktop/a/not.md", "content": "abc"},
    ]
    ok, errors = validate_task_spec(spec, strict_schema=False)
    assert ok is True
    assert errors == []


def test_validate_task_spec_api_batch_ok():
    spec = _base_spec("api_batch")
    spec["required_tools"] = ["api_health_check", "http_request"]
    spec["steps"] = [
        {"id": "s1", "action": "api_health_check", "params": {"url": "https://httpbin.org/get"}},
        {"id": "s2", "action": "http_request", "params": {"method": "GET", "url": "https://httpbin.org/get"}},
    ]
    ok, errors = validate_task_spec(spec, strict_schema=False)
    assert ok is True
    assert errors == []


def test_validate_task_spec_api_batch_missing_url_fails():
    spec = _base_spec("api_batch")
    spec["required_tools"] = ["api_health_check"]
    spec["steps"] = [{"id": "s1", "action": "api_health_check", "params": {}}]
    ok, errors = validate_task_spec(spec, strict_schema=False)
    assert ok is False
    assert any("params.url" in e for e in errors)


def test_validate_task_spec_duplicate_step_id_fails():
    spec = _base_spec("filesystem_batch")
    spec["steps"] = [
        {"id": "s1", "action": "mkdir", "path": "~/Desktop/a"},
        {"id": "s1", "action": "write_file", "path": "~/Desktop/a/not.md", "content": "abc"},
    ]
    ok, errors = validate_task_spec(spec, strict_schema=False)
    assert ok is False
    assert any("duplicate:steps.id:s1" == e for e in errors)


def test_validate_task_spec_unknown_dependency_fails():
    spec = _base_spec("filesystem_batch")
    spec["steps"] = [
        {"id": "s1", "action": "mkdir", "path": "~/Desktop/a", "depends_on": ["s2"]},
    ]
    ok, errors = validate_task_spec(spec, strict_schema=False)
    assert ok is False
    assert any("invalid:steps.depends_on.unknown:s1->s2" == e for e in errors)


def test_validate_task_spec_cycle_dependency_fails():
    spec = _base_spec("filesystem_batch")
    spec["steps"] = [
        {"id": "s1", "action": "mkdir", "path": "~/Desktop/a", "depends_on": ["s2"]},
        {"id": "s2", "action": "write_file", "path": "~/Desktop/a/not.md", "content": "abc", "depends_on": ["s1"]},
    ]
    ok, errors = validate_task_spec(spec, strict_schema=False)
    assert ok is False
    assert "invalid:steps.depends_on.cycle" in errors


def test_validate_task_spec_unknown_root_check_step_id_fails():
    spec = _base_spec("filesystem_batch")
    spec["steps"] = [
        {"id": "s1", "action": "mkdir", "path": "~/Desktop/a"},
    ]
    spec["checks"] = [{"step_id": "missing_step", "checks": [{"type": "path_exists"}]}]
    ok, errors = validate_task_spec(spec, strict_schema=False)
    assert ok is False
    assert any("invalid:checks[1].step_id:missing_step" == e for e in errors)


def test_validate_task_spec_unknown_check_type_fails():
    spec = _base_spec("filesystem_batch")
    spec["steps"] = [
        {
            "id": "s1",
            "action": "write_file",
            "path": "~/Desktop/a/not.md",
            "content": "abc",
            "checks": [{"type": "non_existing_check"}],
        }
    ]
    ok, errors = validate_task_spec(spec, strict_schema=False)
    assert ok is False
    assert any("invalid:steps[1].checks[1].type:non_existing_check" == e for e in errors)


def test_validate_task_spec_run_timeout_lt_step_timeout_fails():
    spec = _base_spec("filesystem_batch")
    spec["timeouts"] = {"step_timeout_s": 120, "run_timeout_s": 30}
    spec["steps"] = [{"id": "s1", "action": "mkdir", "path": "~/Desktop/a"}]
    ok, errors = validate_task_spec(spec, strict_schema=False)
    assert ok is False
    assert any("invalid:timeouts.run_timeout_lt_step_timeout" == e for e in errors)


def test_validate_task_spec_office_edit_text_ok():
    spec = _base_spec("office_batch")
    spec["required_tools"] = ["edit_text_file"]
    spec["steps"] = [
        {
            "id": "s1",
            "action": "edit_text_file",
            "path": "~/Desktop/not.md",
            "params": {"operations": [{"type": "replace", "find": "hata", "replace": "uyari", "all": True}]},
        }
    ]
    ok, errors = validate_task_spec(spec, strict_schema=False)
    assert ok is True
    assert errors == []


def test_validate_task_spec_write_file_with_params_path_and_content_ok():
    spec = _base_spec("filesystem_batch")
    spec["steps"] = [
        {
            "id": "s1",
            "action": "write_file",
            "params": {"path": "~/Desktop/a/from-params.md", "content": "hello"},
        }
    ]
    ok, errors = validate_task_spec(spec, strict_schema=False)
    assert ok is True
    assert errors == []


def test_validate_task_spec_empty_goal_fails():
    spec = _base_spec("filesystem_batch")
    spec["goal"] = ""
    spec["steps"] = [{"id": "s1", "action": "mkdir", "path": "~/Desktop/a"}]
    ok, errors = validate_task_spec(spec, strict_schema=False)
    assert ok is False
    assert "invalid:goal" in errors


def test_validate_task_spec_missing_deliverables_fails():
    spec = _base_spec("filesystem_batch")
    spec["deliverables"] = []
    spec["steps"] = [{"id": "s1", "action": "mkdir", "path": "~/Desktop/a"}]
    ok, errors = validate_task_spec(spec, strict_schema=False)
    assert ok is False
    assert "invalid:deliverables" in errors


def test_validate_task_spec_invalid_priority_fails():
    spec = _base_spec("filesystem_batch")
    spec["priority"] = "urgent"
    spec["steps"] = [{"id": "s1", "action": "mkdir", "path": "~/Desktop/a"}]
    ok, errors = validate_task_spec(spec, strict_schema=False)
    assert ok is False
    assert "invalid:priority" in errors
