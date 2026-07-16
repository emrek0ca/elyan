from __future__ import annotations

from runtime.execution_journal import plan_hash


def test_plan_hash_binds_arguments_dependencies_and_fanout_shape() -> None:
    base = [
        {
            "id": "write",
            "capability": "spreadsheet_write",
            "args": {"outputPath": "/tmp/a.xlsx", "rows": [[1]]},
            "dependsOn": ["collect"],
            "forEach": "{{steps.collect.result.items}}",
        }
    ]

    changed_args = [{**base[0], "args": {"outputPath": "/tmp/b.xlsx", "rows": [[1]]}}]
    changed_dependencies = [{**base[0], "dependsOn": ["other"]}]
    changed_fanout = [{**base[0], "forEach": "{{steps.other.result.items}}"}]

    assert plan_hash(base) != plan_hash(changed_args)
    assert plan_hash(base) != plan_hash(changed_dependencies)
    assert plan_hash(base) != plan_hash(changed_fanout)


def test_plan_hash_ignores_executor_internal_arguments() -> None:
    first = [
        {
            "id": "read",
            "capability": "file_read",
            "args": {"path": "/tmp/a.txt", "_retryAttempt": 1},
        }
    ]
    second = [
        {
            "id": "read",
            "capability": "file_read",
            "args": {"path": "/tmp/a.txt", "_retryAttempt": 2, "_confirmed": True},
        }
    ]

    assert plan_hash(first) == plan_hash(second)
