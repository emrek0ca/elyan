from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from core.capabilities.browser import run_browser_runtime
from core.contracts.failure_taxonomy import FailureCode
from core.contracts.verification_result import VerificationCheck, VerificationResult
from core.runtime.hosts import DesktopHost, get_desktop_host
from core.storage_paths import resolve_elyan_data_dir
from core.task_executor import TaskExecutor
from core.text_artifacts import preferred_text_path
from tools import AVAILABLE_TOOLS

SystemToolRunner = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
BrowserRunner = Callable[..., Awaitable[dict[str, Any]]]


def _slugify(value: str) -> str:
    parts = [item for item in "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "")).split("-") if item]
    return "-".join(parts) or "scenario"


def _scenario_root(name: str, *, artifacts_root: Path | None = None) -> Path:
    base = Path(artifacts_root or (resolve_elyan_data_dir() / "operator_scenarios"))
    root = base / f"{int(time.time() * 1000)}-{_slugify(name)}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text or ""), encoding="utf-8")


def _copy_screenshots(root: Path, step_index: int, result: dict[str, Any]) -> list[str]:
    copied: list[str] = []
    screenshots_root = root / "screenshots"
    screenshots_root.mkdir(parents=True, exist_ok=True)
    for shot_index, raw_path in enumerate(list(result.get("screenshots") or []), start=1):
        source = Path(str(raw_path or "").strip())
        if not source.exists():
            continue
        target = screenshots_root / f"step_{step_index:02d}_{shot_index:02d}{source.suffix or '.png'}"
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        else:
            target = source
        copied.append(str(target))
    return copied


def _extract_target_decisions(result: dict[str, Any]) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for item in list(result.get("action_logs") or []):
        if not isinstance(item, dict):
            continue
        planned = item.get("planned_action") if isinstance(item.get("planned_action"), dict) else {}
        trace = planned.get("decision_trace") if isinstance(planned.get("decision_trace"), dict) else {}
        if trace:
            decisions.append(dict(trace))
    return decisions


def _result_search_blob(result: dict[str, Any], post_observation: dict[str, Any] | None = None) -> str:
    ui_state = result.get("ui_state") if isinstance(result.get("ui_state"), dict) else {}
    browser_state = result.get("browser_state") if isinstance(result.get("browser_state"), dict) else {}
    action_result = result.get("action_result") if isinstance(result.get("action_result"), dict) else {}
    post_ui = post_observation.get("ui_state") if isinstance((post_observation or {}).get("ui_state"), dict) else {}
    bits = [
        str(result.get("message") or ""),
        str(result.get("summary") or ""),
        str(result.get("extracted_text") or ""),
        str(action_result.get("text") or ""),
        str(action_result.get("value") or ""),
        str(ui_state.get("summary") or ""),
        str(browser_state.get("visible_text") or ""),
        str(post_observation.get("summary") or "") if isinstance(post_observation, dict) else "",
        str(post_ui.get("summary") or ""),
        json.dumps(list(ui_state.get("elements") or []), ensure_ascii=False),
        json.dumps(list(post_ui.get("elements") or []), ensure_ascii=False),
    ]
    return " ".join(bit for bit in bits if bit).lower()


def _artifact_paths(result: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for item in list(result.get("artifacts") or []):
        if not isinstance(item, dict):
            continue
        raw = str(item.get("path") or "").strip()
        if not raw:
            continue
        path = Path(raw)
        if path not in paths:
            paths.append(path)
    return paths


def _verification_failure_codes(*, step: dict[str, Any], result: dict[str, Any], verification: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for code in list(verification.get("failed_codes") or []):
        normalized = str(code or "").strip()
        if normalized and normalized == normalized.upper():
            codes.append(normalized)
    for check in list(verification.get("checks") or []):
        if not isinstance(check, dict) or bool(check.get("passed")):
            continue
        check_code = str(check.get("code") or "").strip()
        if check_code == "frontmost_app_matches":
            codes.append(FailureCode.WRONG_APP_CONTEXT.value)
        elif check_code == "window_title_contains":
            codes.append(FailureCode.WRONG_WINDOW_CONTEXT.value)
        elif check_code in {"url_contains", "title_contains"}:
            codes.append(FailureCode.NAVIGATION_NOT_VERIFIED.value)
        elif check_code == "text_contains":
            codes.append(FailureCode.TEXT_NOT_VERIFIED.value)
        elif check_code == "goal_achieved":
            codes.append(FailureCode.NO_VISUAL_CHANGE.value)
        elif check_code in {"artifact_count_min", "artifacts_exist"}:
            codes.append(FailureCode.ARTIFACT_MISSING.value)
        elif check_code == "artifacts_non_empty":
            codes.append(FailureCode.EMPTY_FILE_OUTPUT.value)
        elif check_code == "fallback_used_matches":
            fallback = result.get("fallback") if isinstance(result.get("fallback"), dict) else {}
            if bool(fallback.get("used")):
                reason = str(fallback.get("reason") or "").strip().upper()
                if reason:
                    codes.append(reason)
    error_code = str(result.get("error_code") or "").strip()
    if error_code:
        codes.append(error_code)
    return list(dict.fromkeys(code for code in codes if code))


def _system_observation_satisfies_verify(*, verify_cfg: dict[str, Any], post_observation: dict[str, Any]) -> bool:
    if not verify_cfg:
        return False
    if not isinstance(post_observation, dict) or not bool(post_observation.get("success")):
        return False
    ui_state = post_observation.get("ui_state") if isinstance(post_observation.get("ui_state"), dict) else {}
    if "frontmost_app" in verify_cfg:
        expected = str(verify_cfg.get("frontmost_app") or "").strip().lower()
        actual = str(ui_state.get("frontmost_app") or "").strip().lower()
        if expected and expected != actual:
            return False
    if "window_title_contains" in verify_cfg:
        expected_window = str(verify_cfg.get("window_title_contains") or "").strip().lower()
        actual_window = str(((ui_state.get("active_window") if isinstance(ui_state.get("active_window"), dict) else {}) or {}).get("title") or "").strip().lower()
        if expected_window and expected_window not in actual_window:
            return False
    if "text_contains" in verify_cfg:
        expected_text = str(verify_cfg.get("text_contains") or "").strip().lower()
        blob = _result_search_blob({}, post_observation=post_observation)
        if expected_text and expected_text not in blob:
            return False
    return True


class OperatorScenarioRunner:
    def __init__(
        self,
        *,
        desktop_host: DesktopHost | None = None,
        browser_runner: BrowserRunner | None = None,
        system_tool_runner: SystemToolRunner | None = None,
        artifacts_root: Path | None = None,
    ) -> None:
        self.desktop_host = desktop_host or get_desktop_host()
        self.browser_runner = browser_runner or run_browser_runtime
        self.system_tool_runner = system_tool_runner or self._default_system_tool_runner
        self.artifacts_root = Path(artifacts_root) if artifacts_root is not None else None

    async def _default_system_tool_runner(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        tool = AVAILABLE_TOOLS.get(str(tool_name or "").strip())
        if not callable(tool):
            return {
                "success": False,
                "status": "failed",
                "error": "unknown_tool",
                "error_code": "UNKNOWN_TOOL",
                "message": f"Unknown tool: {tool_name}",
                "action_logs": [],
                "artifacts": [],
                "screenshots": [],
                "verifier_outcomes": [],
            }
        return await TaskExecutor().execute(tool, dict(params or {}))

    async def _run_system_step(self, step: dict[str, Any], *, screen_services: Any = None) -> dict[str, Any]:
        tool_name = str(step.get("tool") or "").strip()
        params = dict(step.get("params") or {}) if isinstance(step.get("params"), dict) else {}
        verify_cfg = step.get("verify") if isinstance(step.get("verify"), dict) else {}
        needs_observation = any(key in verify_cfg for key in ("frontmost_app", "window_title_contains", "text_contains"))
        tool_result = await self.system_tool_runner(tool_name, params)
        tool_artifacts = [dict(item) for item in list(tool_result.get("artifacts") or []) if isinstance(item, dict)]
        tool_screenshots = [str(path).strip() for path in list(tool_result.get("screenshots") or []) if str(path).strip()]
        post_observation: dict[str, Any] = {}
        if needs_observation:
            post_observation = await self.desktop_host.run_screen_operator(
                instruction="ekrana bak",
                mode="inspect",
                services=screen_services,
            )
        observation_satisfied = _system_observation_satisfies_verify(verify_cfg=verify_cfg, post_observation=post_observation)
        tool_success = bool(tool_result.get("success"))
        success = (tool_success and (not needs_observation or bool(post_observation.get("success")))) or observation_satisfied
        status = "success" if success else str(tool_result.get("status") or ("success" if tool_result.get("success") else "failed"))
        action_logs = [
            {
                "step": 1,
                "planned_action": {"kind": tool_name, "params": params},
                "execution_result": dict(tool_result or {}),
            }
        ]
        return {
            "success": bool(success),
            "status": str(status),
            "message": str(post_observation.get("message") or tool_result.get("message") or tool_result.get("error") or "").strip(),
            "summary": str(post_observation.get("summary") or tool_result.get("message") or tool_result.get("error") or "").strip(),
            "tool_result": dict(tool_result or {}),
            "post_observation": dict(post_observation or {}),
            "ui_state": dict(post_observation.get("ui_state") or {}),
            "screenshots": tool_screenshots + [str(path).strip() for path in list(post_observation.get("screenshots") or []) if str(path).strip()],
            "artifacts": tool_artifacts + [dict(item) for item in list(post_observation.get("artifacts") or []) if isinstance(item, dict)],
            "action_logs": action_logs,
            "verifier_outcomes": [dict(item) for item in list(tool_result.get("verifier_outcomes") or []) if isinstance(item, dict)] + [dict(item) for item in list(post_observation.get("verifier_outcomes") or []) if isinstance(item, dict)],
            "task_state": dict(post_observation.get("task_state") or {}),
        }

    async def _run_screen_step(self, step: dict[str, Any], *, screen_services: Any = None) -> dict[str, Any]:
        return await self.desktop_host.run_screen_operator(
            instruction=str(step.get("instruction") or "").strip(),
            mode=str(step.get("mode") or "control").strip() or "control",
            region=step.get("region") if isinstance(step.get("region"), dict) else None,
            final_screenshot=bool(step.get("final_screenshot", True)),
            max_actions=int(step.get("max_actions") or 4),
            max_retries_per_action=int(step.get("max_retries_per_action") or 2),
            services=screen_services,
            task_state=step.get("task_state") if isinstance(step.get("task_state"), dict) else None,
        )

    async def _run_browser_step(self, step: dict[str, Any], *, browser_services: Any = None, screen_services: Any = None) -> dict[str, Any]:
        async def _screen_operator_runner(**kwargs):
            return await self.desktop_host.run_screen_operator(services=screen_services, **kwargs)

        return await self.browser_runner(
            action=str(step.get("action") or "").strip(),
            url=str(step.get("url") or "").strip(),
            selector=str(step.get("selector") or "").strip(),
            text=str(step.get("text") or "").strip(),
            headless=bool(step.get("headless", True)),
            timeout_ms=int(step.get("timeout_ms") or 10000),
            screenshot=bool(step.get("screenshot", True)),
            expected_text=str(step.get("expected_text") or "").strip(),
            expected_url_contains=str(step.get("expected_url_contains") or "").strip(),
            expected_title_contains=str(step.get("expected_title_contains") or "").strip(),
            native_dialog_expected=bool(step.get("native_dialog_expected")),
            uncontrolled_chrome_expected=bool(step.get("uncontrolled_chrome_expected")),
            screen_instruction=str(step.get("screen_instruction") or "").strip(),
            services=browser_services,
            screen_operator_runner=_screen_operator_runner,
            table_selector=str(step.get("table_selector") or "table").strip() or "table",
            pattern=str(step.get("pattern") or "").strip(),
        )

    def _verify_step(self, *, step: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        verify_cfg = step.get("verify") if isinstance(step.get("verify"), dict) else {}
        post_observation = result.get("post_observation") if isinstance(result.get("post_observation"), dict) else {}
        ui_state = result.get("ui_state") if isinstance(result.get("ui_state"), dict) else {}
        if not ui_state:
            ui_state = post_observation.get("ui_state") if isinstance(post_observation.get("ui_state"), dict) else {}
        browser_state = result.get("browser_state") if isinstance(result.get("browser_state"), dict) else {}
        fallback = result.get("fallback") if isinstance(result.get("fallback"), dict) else {}
        checks: list[VerificationCheck] = [
            VerificationCheck(code="step_result_success", passed=bool(result.get("success")), details={"status": str(result.get("status") or "")}),
        ]
        if "frontmost_app" in verify_cfg:
            checks.append(
                VerificationCheck(
                    code="frontmost_app_matches",
                    passed=str(ui_state.get("frontmost_app") or "").strip().lower() == str(verify_cfg.get("frontmost_app") or "").strip().lower(),
                    details={"actual": str(ui_state.get("frontmost_app") or ""), "expected": str(verify_cfg.get("frontmost_app") or "")},
                )
            )
        if "window_title_contains" in verify_cfg:
            actual_window = str(((ui_state.get("active_window") if isinstance(ui_state.get("active_window"), dict) else {}) or {}).get("title") or browser_state.get("title") or "")
            expected_window = str(verify_cfg.get("window_title_contains") or "")
            checks.append(
                VerificationCheck(
                    code="window_title_contains",
                    passed=expected_window.lower() in actual_window.lower(),
                    details={"actual": actual_window, "expected": expected_window},
                )
            )
        if "url_contains" in verify_cfg:
            actual_url = str(browser_state.get("url") or result.get("url") or "")
            expected_url = str(verify_cfg.get("url_contains") or "")
            checks.append(
                VerificationCheck(code="url_contains", passed=expected_url.lower() in actual_url.lower(), details={"actual": actual_url, "expected": expected_url})
            )
        if "title_contains" in verify_cfg:
            actual_title = str(browser_state.get("title") or result.get("title") or "")
            expected_title = str(verify_cfg.get("title_contains") or "")
            checks.append(
                VerificationCheck(code="title_contains", passed=expected_title.lower() in actual_title.lower(), details={"actual": actual_title, "expected": expected_title})
            )
        if "text_contains" in verify_cfg:
            expected_text = str(verify_cfg.get("text_contains") or "")
            blob = _result_search_blob(result, post_observation=post_observation)
            checks.append(
                VerificationCheck(code="text_contains", passed=expected_text.lower() in blob, details={"expected": expected_text})
            )
        if "goal_achieved" in verify_cfg:
            checks.append(
                VerificationCheck(
                    code="goal_achieved",
                    passed=bool(result.get("goal_achieved")) == bool(verify_cfg.get("goal_achieved")),
                    details={"actual": bool(result.get("goal_achieved")), "expected": bool(verify_cfg.get("goal_achieved"))},
                )
            )
        if "fallback_used" in verify_cfg:
            checks.append(
                VerificationCheck(
                    code="fallback_used_matches",
                    passed=bool(fallback.get("used")) == bool(verify_cfg.get("fallback_used")),
                    details={"actual": bool(fallback.get("used")), "expected": bool(verify_cfg.get("fallback_used"))},
                )
            )
        artifact_paths = _artifact_paths(result)
        if "artifact_count_min" in verify_cfg:
            minimum = max(0, int(verify_cfg.get("artifact_count_min") or 0))
            checks.append(
                VerificationCheck(
                    code="artifact_count_min",
                    passed=len(artifact_paths) >= minimum,
                    details={"actual": len(artifact_paths), "expected": minimum},
                )
            )
        if "artifacts_exist" in verify_cfg:
            checks.append(
                VerificationCheck(
                    code="artifacts_exist",
                    passed=all(path.exists() for path in artifact_paths) if artifact_paths else False,
                    details={"artifact_count": len(artifact_paths)},
                )
            )
        if "artifacts_non_empty" in verify_cfg:
            checks.append(
                VerificationCheck(
                    code="artifacts_non_empty",
                    passed=all(path.exists() and path.stat().st_size > 0 for path in artifact_paths) if artifact_paths else False,
                    details={"artifact_count": len(artifact_paths)},
                )
            )

        verification = VerificationResult.from_checks(
            checks,
            summary=f"scenario verification for {str(step.get('name') or step.get('kind') or 'step')}",
            evidence_refs=[
                {"type": "ui_state", "frontmost_app": str(ui_state.get("frontmost_app") or ""), "window_title": str(((ui_state.get("active_window") if isinstance(ui_state.get("active_window"), dict) else {}) or {}).get("title") or "")},
                {"type": "browser_state", "url": str(browser_state.get("url") or ""), "title": str(browser_state.get("title") or "")},
            ],
            metrics={"action_log_count": len(list(result.get("action_logs") or [])), "verifier_outcome_count": len(list(result.get("verifier_outcomes") or []))},
            repairable=False,
        ).to_dict()
        verification["failed_codes"] = _verification_failure_codes(step=step, result=result, verification=verification)
        verification["ok"] = bool(verification.get("status") == "success" and not list(verification.get("failed_codes") or []))
        return verification

    def _build_summary(self, name: str, step_records: list[dict[str, Any]], *, success: bool) -> str:
        lines = [f"# {name}", "", f"Status: {'success' if success else 'failed'}", ""]
        for item in step_records:
            verification = item.get("verification") if isinstance(item.get("verification"), dict) else {}
            lines.append(f"- Step {int(item.get('step_index') or 0)} `{str(item.get('name') or item.get('kind') or 'step')}`: {str(item.get('status') or '')} (verified={bool(verification.get('ok'))})")
            message = str(item.get("message") or "").strip()
            if message:
                lines.append(f"  Message: {message}")
            failed_codes = ", ".join(str(code) for code in list(verification.get("failed_codes") or []) if str(code).strip())
            if failed_codes:
                lines.append(f"  Failed codes: {failed_codes}")
        return "\n".join(lines).strip() + "\n"

    async def run(
        self,
        *,
        name: str,
        steps: list[dict[str, Any]],
        screen_services: Any = None,
        browser_services: Any = None,
        clear_live_state: bool = False,
    ) -> dict[str, Any]:
        if clear_live_state:
            await self.desktop_host.clear_live_state()
        root = _scenario_root(name, artifacts_root=self.artifacts_root)
        step_records: list[dict[str, Any]] = []
        aggregate_action_logs: list[dict[str, Any]] = []
        aggregate_target_decisions: list[dict[str, Any]] = []
        ui_state_snapshots: list[dict[str, Any]] = []
        browser_state_snapshots: list[dict[str, Any]] = []
        copied_screenshots: list[str] = []
        final_error = ""
        final_error_code = ""
        overall_success = True

        for step_index, raw_step in enumerate(list(steps or []), start=1):
            step = dict(raw_step or {})
            kind = str(step.get("kind") or "screen").strip().lower()
            if kind == "system":
                result = await self._run_system_step(step, screen_services=screen_services)
            elif kind == "browser":
                result = await self._run_browser_step(step, browser_services=browser_services, screen_services=screen_services)
            else:
                result = await self._run_screen_step(step, screen_services=screen_services)
            verification = self._verify_step(step=step, result=result if isinstance(result, dict) else {})
            status = str(result.get("status") or ("success" if result.get("success") else "failed"))
            copied = _copy_screenshots(root, step_index, result if isinstance(result, dict) else {})
            copied_screenshots.extend(copied)
            if isinstance(result.get("ui_state"), dict) and result.get("ui_state"):
                ui_state_snapshots.append({"step_index": step_index, "name": str(step.get("name") or ""), "ui_state": dict(result.get("ui_state") or {})})
            post_observation = result.get("post_observation") if isinstance(result.get("post_observation"), dict) else {}
            if isinstance(post_observation.get("ui_state"), dict) and post_observation.get("ui_state"):
                ui_state_snapshots.append({"step_index": step_index, "name": f"{str(step.get('name') or '')}:post_observation", "ui_state": dict(post_observation.get("ui_state") or {})})
            if isinstance(result.get("browser_state"), dict) and result.get("browser_state"):
                browser_state_snapshots.append({"step_index": step_index, "name": str(step.get("name") or ""), "browser_state": dict(result.get("browser_state") or {})})
            for entry in list(result.get("action_logs") or []):
                if isinstance(entry, dict):
                    aggregate_action_logs.append({"scenario_step": step_index, "scenario_step_name": str(step.get("name") or kind), "kind": kind, **dict(entry)})
            aggregate_target_decisions.extend(_extract_target_decisions(result if isinstance(result, dict) else {}))
            step_record = {
                "step_index": step_index,
                "name": str(step.get("name") or f"step_{step_index}").strip(),
                "kind": kind,
                "status": status,
                "message": str(result.get("message") or result.get("summary") or result.get("error") or "").strip(),
                "verification": verification,
                "result": result,
                "screenshots": copied,
            }
            step_records.append(step_record)
            if not verification.get("ok"):
                overall_success = False
                final_error = str(result.get("error") or result.get("message") or "scenario_step_failed").strip() or "scenario_step_failed"
                final_error_code = str(result.get("error_code") or (list(verification.get("failed_codes") or []) or ["SCENARIO_STEP_FAILED"])[0])
                break

        final_desktop_state = await self.desktop_host.get_live_state()
        scenario_task_state = {
            "name": str(name or "").strip(),
            "step_count": len(step_records),
            "completed": bool(overall_success),
            "steps": [
                {
                    "step_index": int(item.get("step_index") or 0),
                    "name": str(item.get("name") or ""),
                    "kind": str(item.get("kind") or ""),
                    "status": str(item.get("status") or ""),
                    "verification": dict(item.get("verification") or {}),
                    "task_state": dict(((item.get("result") if isinstance(item.get("result"), dict) else {}) or {}).get("task_state") or {}),
                }
                for item in step_records
            ],
            "desktop_live_state": final_desktop_state,
            "browser_state_snapshots": browser_state_snapshots,
        }
        aggregate_verification = {
            "status": "success" if overall_success else "failed",
            "ok": bool(overall_success),
            "steps": [
                {
                    "step_index": int(item.get("step_index") or 0),
                    "name": str(item.get("name") or ""),
                    "kind": str(item.get("kind") or ""),
                    "verification": dict(item.get("verification") or {}),
                }
                for item in step_records
            ],
        }
        summary_text = self._build_summary(name, step_records, success=overall_success)

        action_log_path = root / "action_log.json"
        target_decisions_path = root / "target_decisions.json"
        verification_path = root / "verification.json"
        task_state_path = root / "task_state.json"
        summary_path = preferred_text_path(root / "scenario_summary.txt")
        ui_state_path = root / "ui_state_snapshots.json"
        browser_state_path = root / "browser_state_snapshots.json"

        _write_json(action_log_path, aggregate_action_logs)
        _write_json(target_decisions_path, aggregate_target_decisions)
        _write_json(verification_path, aggregate_verification)
        _write_json(task_state_path, scenario_task_state)
        _write_text(summary_path, summary_text)
        _write_json(ui_state_path, ui_state_snapshots)
        _write_json(browser_state_path, browser_state_snapshots)

        artifacts = [
            {"path": str(action_log_path), "type": "json"},
            {"path": str(target_decisions_path), "type": "json"},
            {"path": str(verification_path), "type": "json"},
            {"path": str(task_state_path), "type": "json"},
            {"path": str(summary_path), "type": "text"},
            {"path": str(ui_state_path), "type": "json"},
            {"path": str(browser_state_path), "type": "json"},
        ] + [{"path": path, "type": "image"} for path in copied_screenshots]

        payload = {
            "success": bool(overall_success),
            "status": "success" if overall_success else "failed",
            "message": f"Scenario {name} completed." if overall_success else f"Scenario {name} failed.",
            "summary": summary_text,
            "name": str(name or "").strip(),
            "steps": step_records,
            "artifacts": artifacts,
            "screenshots": copied_screenshots,
            "action_logs": aggregate_action_logs,
            "verifier_outcomes": aggregate_verification["steps"],
            "task_state": scenario_task_state,
            "desktop_host_state": final_desktop_state,
        }
        if not overall_success:
            payload["error"] = final_error or "scenario_step_failed"
            payload["error_code"] = final_error_code or "SCENARIO_STEP_FAILED"
        return payload


__all__ = ["OperatorScenarioRunner"]
