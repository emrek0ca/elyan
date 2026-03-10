from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from core.storage_paths import resolve_elyan_data_dir

from .benchmarks import run_production_benchmarks


EMRE_WORKFLOW_PRESETS: list[dict[str, str]] = [
    {
        "name": "telegram_desktop_task_completion",
        "workflow_name": "Telegram-triggered desktop task completion",
        "description": "Telegram source request opens the right desktop app and completes the visible UI action.",
        "request": "Telegram tetiklemeli masaustu gorevini calistir, Safari'yi ac ve Continue butonuna tikla.",
    },
    {
        "name": "research_document_creation_verification",
        "workflow_name": "Research -> document creation -> file verification",
        "description": "Research request generates verified document artifacts and source files.",
        "request": "AI agents hakkinda arastirma yap, rapor olustur ve dosya artifactlerini dogrula.",
    },
    {
        "name": "app_switch_finder_safari_cursor_terminal",
        "workflow_name": "Safari / Cursor / Terminal / Finder switching tasks",
        "description": "Desktop operator switches between core apps and continues the intended action.",
        "request": "Finder'i ac sonra Terminal'i ac sonra Cursor'u ac sonra Safari'ye gec ve arama kutusuna kittens yaz.",
    },
    {
        "name": "login_continue_upload_flow",
        "workflow_name": "Login -> continue -> upload",
        "description": "Mixed browser and native-dialog flow completes login, continuation, and upload confirmation.",
        "request": "https://login.local ac ve email alanina user@example.com yaz, sifre alanina secret123 yaz ve giris yap sonra Continue butonuna tikla sonra https://upload.local ac ve yukleme diyalogunu onayla.",
    },
    {
        "name": "interrupted_resume_after_partial_completion",
        "workflow_name": "Interrupted resume after partial completion",
        "description": "A partially completed task resumes from the failed point and finishes safely.",
        "request": "https://upload.local ac ve yukleme diyalogunu onayla sonra Save butonuna tikla.",
    },
]


def _default_reports_root() -> Path:
    return resolve_elyan_data_dir() / "emre_workflows"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text or ""), encoding="utf-8")


def _preset_map() -> dict[str, dict[str, str]]:
    return {str(item.get("name") or ""): dict(item) for item in EMRE_WORKFLOW_PRESETS}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _preset_runs_root(reports_root: Path | None = None) -> Path:
    return Path(reports_root or _default_reports_root()) / "preset_runs"


def _coerce_workflow_artifacts(values: Any) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    for item in list(values or []):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        artifacts.append(
            {
                "path": path,
                "type": str(item.get("type") or "").strip() or "artifact",
            }
        )
    return artifacts


def _extract_completed_step_names(comparison: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in list(comparison.get("steps") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "").strip() != "completed":
            continue
        name = str(item.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _extract_screenshot_artifacts(artifacts: list[dict[str, str]]) -> list[dict[str, str]]:
    screenshots: list[dict[str, str]] = []
    for item in artifacts:
        path = str(item.get("path") or "").strip().lower()
        if path.endswith((".png", ".jpg", ".jpeg", ".webp")):
            screenshots.append(dict(item))
    return screenshots


def _single_workflow_markdown(report: dict[str, Any]) -> str:
    completed = list(report.get("completed_step_names") or [])
    artifacts = [dict(item) for item in list(report.get("artifacts") or []) if isinstance(item, dict)]
    screenshots = [dict(item) for item in list(report.get("screenshots") or []) if isinstance(item, dict)]
    lines = [
        f"# {str(report.get('workflow_name') or report.get('name') or 'Workflow')}",
        "",
        f"- status: {str(report.get('status') or '')}",
        f"- completed_steps: {int(report.get('completed_steps') or 0)}/{int(report.get('planned_steps') or 0)}",
        f"- retries: {int(report.get('retry_count') or 0)}",
        f"- replans: {int(report.get('replan_count') or 0)}",
        f"- failure_code: {str(report.get('failure_code') or 'none') or 'none'}",
        "",
        "## Summary",
        "",
        str(report.get("summary") or ""),
    ]
    if completed:
        lines.extend(["", "## Completed Steps", ""])
        for name in completed:
            lines.append(f"- {name}")
    if screenshots:
        lines.extend(["", "## Screenshots", ""])
        for item in screenshots[:6]:
            lines.append(f"- {item['path']}")
    if artifacts:
        lines.extend(["", "## Artifacts", ""])
        for item in artifacts[:10]:
            lines.append(f"- {item['type']}: {item['path']}")
    return "\n".join(lines).strip() + "\n"


def _report_summary_text(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "").strip() or "unknown"
    completed = f"{int(row.get('completed_steps') or 0)}/{int(row.get('planned_steps') or 0)}"
    retries = int(row.get("retry_count") or 0)
    replans = int(row.get("replan_count") or 0)
    failure = str(row.get("failure_code") or "").strip() or "none"
    return f"{status} | completed={completed} | retries={retries} | replans={replans} | failure={failure}"


def _latest_report_dirs(root: Path, *, limit: int = 10) -> list[Path]:
    if not root.exists():
        return []
    directories = [item for item in root.iterdir() if item.is_dir()]
    directories.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return directories[: max(1, int(limit or 10))]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return dict(payload) if isinstance(payload, dict) else {}
    except Exception:
        return {}


def select_emre_workflow_cases(
    cases: list[dict[str, Any]],
    *,
    preset_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    preset_map = _preset_map()
    selected_names = [str(name).strip() for name in list(preset_names or []) if str(name).strip()] or list(preset_map.keys())
    available = {str(case.get("name") or ""): dict(case) for case in list(cases or []) if isinstance(case, dict)}
    selected: list[dict[str, Any]] = []
    for name in selected_names:
        if name in available and name in preset_map:
            selected.append(dict(available[name]))
    return selected


async def run_emre_workflow_preset(
    preset_name: str,
    *,
    planner: Any = None,
    reports_root: Path | None = None,
    clear_live_state: bool = True,
) -> dict[str, Any]:
    preset = _preset_map().get(str(preset_name or "").strip())
    if not preset:
        raise ValueError(f"Unknown workflow preset: {preset_name}")

    if planner is None:
        from .live_planner import LiveOperatorTaskPlanner

        planner = LiveOperatorTaskPlanner()

    root = _preset_runs_root(reports_root) / f"{int(time.time() * 1000)}_{preset['name']}"
    result = await planner.start_request(
        str(preset.get("request") or "").strip(),
        clear_live_state=bool(clear_live_state),
    )
    task_result = dict(result.get("task_result") or {}) if isinstance(result.get("task_result"), dict) else {}
    task_state = dict(task_result.get("task_state") or {}) if isinstance(task_result.get("task_state"), dict) else {}
    comparison = dict(result.get("comparison") or {}) if isinstance(result.get("comparison"), dict) else {}
    plan = dict(result.get("plan") or {}) if isinstance(result.get("plan"), dict) else {}
    completed_names = _extract_completed_step_names(comparison)
    retry_count = sum(int(value or 0) for value in dict(task_state.get("retry_counts") or {}).values())
    replan_count = int(task_state.get("replan_count") or 0)
    artifacts = _coerce_workflow_artifacts(task_result.get("artifacts"))
    screenshots = _extract_screenshot_artifacts(artifacts)
    report = {
        "name": str(preset.get("name") or "").strip(),
        "workflow_name": str(preset.get("workflow_name") or preset.get("name") or "").strip(),
        "description": str(preset.get("description") or "").strip(),
        "request": str(preset.get("request") or "").strip(),
        "task_id": str(result.get("task_id") or "").strip(),
        "status": str(result.get("status") or "").strip(),
        "success": bool(result.get("success")),
        "planned_steps": max(0, int(comparison.get("planned_step_count") or len(list(plan.get("steps") or [])))),
        "completed_steps": max(0, int(comparison.get("completed_step_count") or len(completed_names))),
        "completed_step_names": completed_names,
        "retry_count": retry_count,
        "replan_count": replan_count,
        "failure_code": str(task_result.get("error_code") or "").strip(),
        "artifacts": artifacts,
        "screenshots": screenshots,
        "summary": _report_summary_text(
            {
                "status": str(result.get("status") or "").strip(),
                "completed_steps": max(0, int(comparison.get("completed_step_count") or len(completed_names))),
                "planned_steps": max(0, int(comparison.get("planned_step_count") or len(list(plan.get("steps") or [])))),
                "retry_count": retry_count,
                "replan_count": replan_count,
                "failure_code": str(task_result.get("error_code") or "").strip(),
            }
        ),
        "plan": {
            "name": str(plan.get("name") or "").strip(),
            "goal": str(plan.get("goal") or "").strip(),
            "steps": [dict(item) for item in list(plan.get("steps") or []) if isinstance(item, dict)],
        },
        "planning_trace": dict(result.get("planning_trace") or {}),
        "comparison": comparison,
    }
    report_json = root / "report.json"
    report_md = root / "report.md"
    _write_json(report_json, report)
    _write_text(report_md, _single_workflow_markdown(report))
    return {
        "success": bool(result.get("success")),
        "status": str(result.get("status") or ""),
        "report_root": str(root),
        "workflow": report,
        "artifacts": artifacts
        + [
            {"path": str(report_json), "type": "json"},
            {"path": str(report_md), "type": "text"},
        ],
    }


def list_emre_workflow_reports(
    *,
    reports_root: Path | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    root = _preset_runs_root(reports_root)
    rows: list[dict[str, Any]] = []
    for directory in _latest_report_dirs(root, limit=limit):
        report = _load_json(directory / "report.json")
        if not report:
            continue
        rows.append(
            {
                "name": str(report.get("name") or "").strip(),
                "workflow_name": str(report.get("workflow_name") or report.get("name") or "").strip(),
                "status": str(report.get("status") or "").strip(),
                "task_id": str(report.get("task_id") or "").strip(),
                "completed_steps": int(report.get("completed_steps") or 0),
                "planned_steps": int(report.get("planned_steps") or 0),
                "completed_step_names": [str(item).strip() for item in list(report.get("completed_step_names") or []) if str(item).strip()],
                "retry_count": int(report.get("retry_count") or 0),
                "replan_count": int(report.get("replan_count") or 0),
                "failure_code": str(report.get("failure_code") or "").strip(),
                "summary": str(report.get("summary") or "").strip(),
                "artifacts": _coerce_workflow_artifacts(report.get("artifacts")),
                "screenshots": _coerce_workflow_artifacts(report.get("screenshots")),
                "report_root": str(directory),
                "updated_at": float(directory.stat().st_mtime),
            }
        )
    return rows


def load_latest_benchmark_summary(*, reports_roots: list[Path] | None = None) -> dict[str, Any]:
    candidate_roots = list(reports_roots or [])
    if not candidate_roots:
        candidate_roots = [
            resolve_elyan_data_dir() / "runtime_benchmarks",
            _repo_root() / "artifacts" / "production-benchmarks",
        ]
    latest_path: Path | None = None
    latest_ts = 0.0
    for root in candidate_roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
        for directory in _latest_report_dirs(root_path, limit=20):
            summary_path = directory / "summary.json"
            if not summary_path.exists():
                continue
            try:
                mtime = summary_path.stat().st_mtime
            except Exception:
                continue
            if mtime >= latest_ts:
                latest_ts = mtime
                latest_path = summary_path
    if latest_path is None:
        return {
            "pass_count": 0,
            "total": 0,
            "average_retries": 0.0,
            "average_replans": 0.0,
            "remaining_failure_codes": [],
            "last_benchmark_timestamp": "",
            "report_root": "",
        }
    summary = _load_json(latest_path)
    return {
        "pass_count": int(summary.get("pass_count") or 0),
        "total": int(summary.get("total") or 0),
        "average_retries": float(summary.get("average_retries") or 0),
        "average_replans": float(summary.get("average_replans") or 0),
        "remaining_failure_codes": sorted(dict(summary.get("failure_reasons") or {}).keys()),
        "last_benchmark_timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest_ts)),
        "report_root": str(latest_path.parent),
    }


def _workflow_report_markdown(rows: list[dict[str, Any]], *, pass_count: int, total: int) -> str:
    lines = [
        "# Emre Workflow Pack",
        "",
        f"Pass rate: {pass_count}/{total}",
        "",
        "| workflow | final_status | completed_steps | retries | replans | failure_code |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for row in rows:
        completed = ", ".join(str(item) for item in list(row.get("completed_steps") or []) if str(item).strip()) or "-"
        lines.append(
            f"| {row['workflow_name']} | {row['final_status']} | {completed} | {row['retry_count']} | {row['replan_count']} | {row['failure_code'] or 'none'} |"
        )
    return "\n".join(lines).strip() + "\n"


def _workflow_dashboard_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Emre Workflow Dashboard",
        "",
        f"- pass_count: {int(summary.get('pass_count') or 0)}/{int(summary.get('total') or 0)}",
        f"- average_retries: {float(summary.get('average_retries') or 0):.3f}",
        f"- average_replans: {float(summary.get('average_replans') or 0):.3f}",
        f"- remaining_failure_codes: {', '.join(sorted(summary.get('failure_reasons') or [])) if summary.get('failure_reasons') else 'none'}",
        "",
    ]
    for row in list(summary.get("rows") or []):
        if not isinstance(row, dict):
            continue
        lines.append(
            f"- {row['workflow_name']}: {row['final_status']} (retries={row['retry_count']}, replans={row['replan_count']}, failure={row['failure_code'] or 'none'})"
        )
    return "\n".join(lines).strip() + "\n"


async def run_emre_workflow_pack(
    cases: list[dict[str, Any]],
    *,
    reports_root: Path | None = None,
    preset_names: list[str] | None = None,
) -> dict[str, Any]:
    selected_cases = select_emre_workflow_cases(cases, preset_names=preset_names)
    root = Path(reports_root or _default_reports_root()) / str(int(time.time() * 1000))
    benchmark_report = await run_production_benchmarks(selected_cases, reports_root=root / "benchmarks")
    benchmark_summary = dict(benchmark_report.get("summary") or {})
    preset_map = _preset_map()

    workflow_rows: list[dict[str, Any]] = []
    for row in list(benchmark_summary.get("rows") or []):
        if not isinstance(row, dict):
            continue
        preset = preset_map.get(str(row.get("name") or ""), {})
        workflow_rows.append(
            {
                "name": str(row.get("name") or ""),
                "workflow_name": str(preset.get("workflow_name") or row.get("name") or ""),
                "request": str(row.get("request") or ""),
                "task_id": str(row.get("task_id") or ""),
                "completed_steps": list(row.get("completed_step_names") or []),
                "retry_count": int(row.get("retry_count") or 0),
                "replan_count": int(row.get("replan_count") or 0),
                "final_status": str(row.get("status") or ""),
                "failure_code": str(row.get("failure_code") or ""),
                "artifacts": [dict(item) for item in list(row.get("artifacts") or []) if isinstance(item, dict)],
            }
        )

    summary = {
        "pass_count": int(benchmark_summary.get("pass_count") or 0),
        "total": int(benchmark_summary.get("total") or 0),
        "average_retries": float(benchmark_summary.get("average_retries") or 0),
        "average_replans": float(benchmark_summary.get("average_replans") or 0),
        "failure_reasons": sorted(dict(benchmark_summary.get("failure_reasons") or {}).keys()),
        "rows": workflow_rows,
    }

    workflow_json = root / "workflow_report.json"
    workflow_md = root / "workflow_report.md"
    dashboard_json = root / "dashboard.json"
    dashboard_md = root / "dashboard.md"
    _write_json(workflow_json, {"summary": summary, "workflow_rows": workflow_rows})
    _write_text(workflow_md, _workflow_report_markdown(workflow_rows, pass_count=summary["pass_count"], total=summary["total"]))
    _write_json(dashboard_json, summary)
    _write_text(dashboard_md, _workflow_dashboard_markdown(summary))

    return {
        "success": bool(benchmark_report.get("success")),
        "status": str(benchmark_report.get("status") or ""),
        "report_root": str(root),
        "summary": summary,
        "workflow_rows": workflow_rows,
        "benchmark_report": benchmark_report,
        "artifacts": list(benchmark_report.get("artifacts") or [])
        + [
            {"path": str(workflow_json), "type": "json"},
            {"path": str(workflow_md), "type": "text"},
            {"path": str(dashboard_json), "type": "json"},
            {"path": str(dashboard_md), "type": "text"},
        ],
    }


__all__ = [
    "EMRE_WORKFLOW_PRESETS",
    "list_emre_workflow_reports",
    "load_latest_benchmark_summary",
    "run_emre_workflow_pack",
    "run_emre_workflow_preset",
    "select_emre_workflow_cases",
]
