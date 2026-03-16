from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from core.storage_paths import resolve_elyan_data_dir
from core.text_artifacts import preferred_text_path


def _default_reports_root() -> Path:
    return resolve_elyan_data_dir() / "runtime_benchmarks"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text or ""), encoding="utf-8")


def _summary_markdown(rows: list[dict[str, Any]], *, pass_count: int, total: int) -> str:
    lines = [
        "# Production Path Benchmark",
        "",
        f"Pass rate: {pass_count}/{total}",
        "",
        "| task | status | planned | completed | retries | replans | failure | elapsed_s |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['name']} | {row['status']} | {row['planned_steps']} | {row['completed_steps']} | {row['retry_count']} | {row['replan_count']} | {row['failure_code']} | {row['elapsed_s']:.3f} |"
        )
    return "\n".join(lines).strip() + "\n"


def _dashboard_markdown(summary: dict[str, Any]) -> str:
    rows = [dict(item) for item in list(summary.get("rows") or []) if isinstance(item, dict)]
    failure_reasons = dict(summary.get("failure_reasons") or {})
    lines = [
        "# Elyan Benchmark Dashboard",
        "",
        f"- pass_count: {int(summary.get('pass_count') or 0)}/{int(summary.get('total') or 0)}",
        f"- average_retries: {float(summary.get('average_retries') or 0):.3f}",
        f"- average_replans: {float(summary.get('average_replans') or 0):.3f}",
        f"- remaining_failure_codes: {', '.join(sorted(failure_reasons)) if failure_reasons else 'none'}",
        "",
        "## Task Outcomes",
        "",
        "| task | final_status | retries | replans | failure_code |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['name']} | {row['status']} | {row['retry_count']} | {row['replan_count']} | {row['failure_code'] or 'none'} |"
        )
    return "\n".join(lines).strip() + "\n"


async def run_production_benchmarks(
    cases: list[dict[str, Any]],
    *,
    reports_root: Path | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    root = Path(reports_root or _default_reports_root()) / str(int(time.time() * 1000))
    rows: list[dict[str, Any]] = []
    failure_reasons: dict[str, int] = {}

    for item in list(cases or []):
        case = dict(item or {})
        request = str(case.get("request") or "").strip()
        name = str(case.get("name") or request or f"benchmark_{len(rows) + 1}").strip()
        case_started = time.monotonic()
        runner = case.get("runner")
        if callable(runner):
            result = await runner(case)
        else:
            planner = case.get("planner")
            if planner is None:
                raise ValueError(f"Benchmark case missing planner: {case}")
            result = await planner.start_request(
                request,
                screen_services=case.get("screen_services"),
                browser_services=case.get("browser_services"),
                clear_live_state=bool(case.get("clear_live_state", True)),
            )
        task_result = dict(result.get("task_result") or {}) if isinstance(result.get("task_result"), dict) else {}
        task_state = dict(task_result.get("task_state") or {}) if isinstance(task_result.get("task_state"), dict) else {}
        comparison = dict(result.get("comparison") or {}) if isinstance(result.get("comparison"), dict) else {}
        plan = dict(result.get("plan") or {}) if isinstance(result.get("plan"), dict) else {}
        failure_code = str(task_result.get("error_code") or "").strip()
        if failure_code:
            failure_reasons[failure_code] = int(failure_reasons.get(failure_code, 0)) + 1
        completed_step_names = [
            str(item.get("name") or "").strip()
            for item in list(comparison.get("steps") or [])
            if isinstance(item, dict) and str(item.get("status") or "").strip() == "completed"
        ]
        rows.append(
            {
                "name": name,
                "request": request,
                "task_id": str(result.get("task_id") or "").strip(),
                "status": str(result.get("status") or "").strip(),
                "success": bool(result.get("success")),
                "planned_steps": max(0, int(comparison.get("planned_step_count") or 0)),
                "completed_steps": max(0, int(comparison.get("completed_step_count") or 0)),
                "retry_count": sum(int(value or 0) for value in dict(task_state.get("retry_counts") or {}).values()),
                "replan_count": max(0, int(task_state.get("replan_count") or 0)),
                "failure_code": failure_code,
                "elapsed_s": round(time.monotonic() - case_started, 3),
                "plan_steps": [dict(item) for item in list(plan.get("steps") or []) if isinstance(item, dict)],
                "completed_step_names": completed_step_names,
                "artifacts": [dict(artifact) for artifact in list(task_result.get("artifacts") or []) if isinstance(artifact, dict)],
            }
        )

    pass_count = sum(1 for row in rows if bool(row.get("success")))
    total = len(rows)
    summary = {
        "pass_count": pass_count,
        "total": total,
        "completion_rate": round((pass_count / total), 3) if total else 0.0,
        "average_retries": round(sum(float(row.get("retry_count") or 0) for row in rows) / total, 3) if total else 0.0,
        "average_replans": round(sum(float(row.get("replan_count") or 0) for row in rows) / total, 3) if total else 0.0,
        "failure_reasons": dict(sorted(failure_reasons.items())),
        "rows": rows,
        "elapsed_s": round(time.monotonic() - started, 3),
    }

    summary_json = root / "summary.json"
    summary_txt = preferred_text_path(root / "summary.txt")
    dashboard_json = root / "dashboard.json"
    dashboard_txt = preferred_text_path(root / "dashboard.txt")
    _write_json(summary_json, summary)
    _write_text(summary_txt, _summary_markdown(rows, pass_count=pass_count, total=total))
    _write_json(
        dashboard_json,
        {
            "pass_count": int(summary.get("pass_count") or 0),
            "total": int(summary.get("total") or 0),
            "average_retries": float(summary.get("average_retries") or 0),
            "average_replans": float(summary.get("average_replans") or 0),
            "remaining_failure_codes": sorted(dict(summary.get("failure_reasons") or {}).keys()),
            "tasks": [
                {
                    "name": str(row.get("name") or ""),
                    "final_status": str(row.get("status") or ""),
                    "retry_count": int(row.get("retry_count") or 0),
                    "replan_count": int(row.get("replan_count") or 0),
                    "failure_code": str(row.get("failure_code") or ""),
                }
                for row in rows
            ],
        },
    )
    _write_text(dashboard_txt, _dashboard_markdown(summary))

    return {
        "success": bool(pass_count == total if total else False),
        "status": "success" if total and pass_count == total else "failed",
        "report_root": str(root),
        "summary": summary,
        "artifacts": [
            {"path": str(summary_json), "type": "json"},
            {"path": str(summary_txt), "type": "text"},
            {"path": str(dashboard_json), "type": "json"},
            {"path": str(dashboard_txt), "type": "text"},
        ],
    }


__all__ = ["run_production_benchmarks"]
