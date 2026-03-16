from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path
from typing import Any

from core.contracts.failure_taxonomy import RETRYABLE_FAILURE_CODES
from core.runtime.scenarios import OperatorScenarioRunner, _extract_target_decisions
from core.storage_paths import resolve_elyan_data_dir
from core.text_artifacts import preferred_text_path


def _default_tasks_root() -> Path:
    return resolve_elyan_data_dir() / "operator_tasks"


def _slugify(value: str) -> str:
    parts = [item for item in "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "")).split("-") if item]
    return "-".join(parts) or "task"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(text or ""), encoding="utf-8")


class OperatorTaskRuntime(OperatorScenarioRunner):
    def __init__(
        self,
        *,
        tasks_root: Path | None = None,
        default_max_step_retries: int = 1,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.tasks_root = Path(tasks_root or _default_tasks_root())
        self.default_max_step_retries = max(0, int(default_max_step_retries or 0))
        self._locks: dict[str, asyncio.Lock] = {}

    def _planner(self):
        from core.runtime.live_planner import LiveOperatorTaskPlanner

        return LiveOperatorTaskPlanner(task_runtime=self)

    def _task_lock(self, task_id: str) -> asyncio.Lock:
        key = str(task_id or "").strip()
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def _task_dir(self, task_id: str) -> Path:
        return self.tasks_root / str(task_id or "").strip()

    def _new_task_id(self, name: str) -> str:
        return f"task_{int(time.time() * 1000)}_{_slugify(name)[:48]}"

    def _state_paths(self, task_id: str) -> dict[str, Path]:
        root = self._task_dir(task_id)
        return {
            "root": root,
            "state": root / "task_state.json",
            "steps": root / "steps.json",
            "action_log": root / "action_log.json",
            "verification": root / "verification.json",
            "target_decisions": root / "target_decisions.json",
            "retry_history": root / "retry_history.json",
            "replan_history": root / "replan_history.json",
            "latest_observation": root / "latest_observation.json",
            "plan": root / "plan.json",
            "planning_trace": root / "planning_trace.json",
            "summary": preferred_text_path(root / "task_summary.txt"),
            "screenshots": root / "screenshots",
        }

    def _coerce_step_record(self, raw: Any, *, index: int, definition: dict[str, Any]) -> dict[str, Any]:
        record = raw if isinstance(raw, dict) else {}
        return {
            "step_index": int(record.get("step_index") or index),
            "name": str(record.get("name") or definition.get("name") or f"step_{index}").strip(),
            "kind": str(record.get("kind") or definition.get("kind") or "screen").strip().lower() or "screen",
            "status": str(record.get("status") or "pending").strip() or "pending",
            "attempts": max(0, int(record.get("attempts") or 0)),
            "verification": dict(record.get("verification") or {}) if isinstance(record.get("verification"), dict) else {},
            "message": str(record.get("message") or "").strip(),
            "error": str(record.get("error") or "").strip(),
            "error_code": str(record.get("error_code") or "").strip(),
            "screenshots": [str(path).strip() for path in list(record.get("screenshots") or []) if str(path).strip()],
            "artifacts": [dict(item) for item in list(record.get("artifacts") or []) if isinstance(item, dict)],
            "result": dict(record.get("result") or {}) if isinstance(record.get("result"), dict) else {},
        }

    def _base_state(
        self,
        *,
        task_id: str,
        name: str,
        goal: str,
        steps: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "version": 1,
            "task_id": task_id,
            "name": str(name or task_id).strip(),
            "goal": str(goal or "").strip(),
            "status": "pending",
            "created_at": float(time.time()),
            "updated_at": float(time.time()),
            "current_step": 1 if steps else 0,
            "completed_steps": [],
            "failed_steps": [],
            "retry_counts": {},
            "repair_history": [],
            "replan_history": [],
            "replan_count": 0,
            "last_failure_reason": "",
            "latest_observation": {},
            "last_ui_state": {},
            "browser_state": {},
            "desktop_host_state": {},
            "artifacts": [],
            "verifier_outcomes": [],
            "metadata": dict(metadata or {}) if isinstance(metadata, dict) else {},
            "steps": [
                self._coerce_step_record({}, index=index, definition=definition)
                for index, definition in enumerate(list(steps or []), start=1)
            ],
            "step_definitions": [dict(item or {}) for item in list(steps or []) if isinstance(item, dict)],
        }

    def _load_state(self, task_id: str) -> dict[str, Any] | None:
        state_path = self._state_paths(task_id)["state"]
        if not state_path.exists():
            return None
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        step_definitions = [dict(item) for item in list(payload.get("step_definitions") or []) if isinstance(item, dict)]
        step_records = [
            self._coerce_step_record(record, index=index, definition=step_definitions[index - 1] if index - 1 < len(step_definitions) else {})
            for index, record in enumerate(list(payload.get("steps") or []), start=1)
        ]
        return {
            **payload,
            "task_id": str(payload.get("task_id") or task_id).strip(),
            "name": str(payload.get("name") or task_id).strip(),
            "goal": str(payload.get("goal") or "").strip(),
            "status": str(payload.get("status") or "pending").strip() or "pending",
            "current_step": max(0, int(payload.get("current_step") or 0)),
            "completed_steps": [int(item) for item in list(payload.get("completed_steps") or []) if isinstance(item, int) or str(item).isdigit()],
            "failed_steps": [dict(item) for item in list(payload.get("failed_steps") or []) if isinstance(item, dict)],
            "retry_counts": {str(key): max(0, int(value or 0)) for key, value in dict(payload.get("retry_counts") or {}).items()},
            "repair_history": [dict(item) for item in list(payload.get("repair_history") or []) if isinstance(item, dict)],
            "replan_history": [dict(item) for item in list(payload.get("replan_history") or []) if isinstance(item, dict)],
            "replan_count": max(0, int(payload.get("replan_count") or 0)),
            "last_failure_reason": str(payload.get("last_failure_reason") or "").strip(),
            "latest_observation": dict(payload.get("latest_observation") or {}) if isinstance(payload.get("latest_observation"), dict) else {},
            "last_ui_state": dict(payload.get("last_ui_state") or {}) if isinstance(payload.get("last_ui_state"), dict) else {},
            "browser_state": dict(payload.get("browser_state") or {}) if isinstance(payload.get("browser_state"), dict) else {},
            "desktop_host_state": dict(payload.get("desktop_host_state") or {}) if isinstance(payload.get("desktop_host_state"), dict) else {},
            "artifacts": [dict(item) for item in list(payload.get("artifacts") or []) if isinstance(item, dict)],
            "verifier_outcomes": [dict(item) for item in list(payload.get("verifier_outcomes") or []) if isinstance(item, dict)],
            "metadata": dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), dict) else {},
            "steps": step_records,
            "step_definitions": step_definitions,
        }

    def _persist_state(self, state: dict[str, Any]) -> dict[str, Any]:
        task_id = str(state.get("task_id") or "").strip()
        paths = self._state_paths(task_id)
        payload = dict(state)
        payload["updated_at"] = float(time.time())
        paths["root"].mkdir(parents=True, exist_ok=True)
        _write_json(paths["state"], payload)
        _write_json(paths["steps"], payload.get("steps") or [])
        _write_json(paths["action_log"], payload.get("action_logs") or [])
        _write_json(paths["verification"], payload.get("verifier_outcomes") or [])
        _write_json(paths["target_decisions"], payload.get("target_decisions") or [])
        _write_json(paths["retry_history"], payload.get("repair_history") or [])
        _write_json(paths["replan_history"], payload.get("replan_history") or [])
        _write_json(paths["latest_observation"], payload.get("latest_observation") or {})
        _write_json(paths["plan"], list(payload.get("step_definitions") or []))
        _write_json(paths["planning_trace"], dict(payload.get("metadata") or {}).get("planning_trace") or {})
        _write_text(paths["summary"], self._build_summary(str(payload.get("name") or task_id), list(payload.get("steps") or []), success=str(payload.get("status") or "") == "completed"))
        return payload

    def _copy_step_screenshots(self, *, state: dict[str, Any], step_index: int, screenshots: list[str]) -> list[str]:
        paths = self._state_paths(str(state.get("task_id") or ""))
        copied: list[str] = []
        paths["screenshots"].mkdir(parents=True, exist_ok=True)
        step_record = state["steps"][step_index - 1] if step_index - 1 < len(state.get("steps") or []) else {}
        shot_offset = len(list(step_record.get("screenshots") or []))
        for offset, raw_path in enumerate(list(screenshots or []), start=1):
            source = Path(str(raw_path or "").strip())
            if not source.exists():
                continue
            target = paths["screenshots"] / f"step_{step_index:02d}_{shot_offset + offset:02d}{source.suffix or '.png'}"
            if source.resolve() != target.resolve():
                shutil.copyfile(source, target)
            else:
                target = source
            copied.append(str(target))
        return copied

    def _step_retry_budget(self, step: dict[str, Any]) -> int:
        repair_policy = step.get("repair_policy") if isinstance(step.get("repair_policy"), dict) else {}
        if "max_retries" in step:
            return max(0, int(step.get("max_retries") or 0))
        if "max_retries" in repair_policy:
            return max(0, int(repair_policy.get("max_retries") or 0))
        return self.default_max_step_retries

    def _failure_codes(self, *, result: dict[str, Any], verification: dict[str, Any]) -> list[str]:
        codes: list[str] = []
        if result.get("error_code") and str(result.get("error_code") or "").strip():
            codes.append(str(result.get("error_code") or "").strip())
        for item in list(result.get("verifier_outcomes") or []):
            if not isinstance(item, dict):
                continue
            for code in list(item.get("failed_codes") or []):
                normalized = str(code or "").strip()
                if normalized and normalized not in codes:
                    codes.append(normalized)
        for code in list(verification.get("failed_codes") or []):
            normalized = str(code or "").strip()
            if normalized and normalized == normalized.upper() and normalized not in codes:
                codes.append(normalized)
        return list(dict.fromkeys(codes))

    def _is_repairable(self, *, step: dict[str, Any], result: dict[str, Any], verification: dict[str, Any]) -> bool:
        repair_policy = step.get("repair_policy") if isinstance(step.get("repair_policy"), dict) else {}
        if repair_policy.get("retry_on_failure") is False:
            return False
        codes = self._failure_codes(result=result, verification=verification)
        if not codes:
            return False
        allowed = {str(code) for code in list(repair_policy.get("retry_on_failed_codes") or []) if str(code).strip()}
        if allowed:
            return any(code in allowed for code in codes)
        retryable = {str(code.value) if hasattr(code, "value") else str(code) for code in RETRYABLE_FAILURE_CODES}
        return any(code in retryable for code in codes)

    def _next_pending_step(self, state: dict[str, Any]) -> int:
        for record in list(state.get("steps") or []):
            if str(record.get("status") or "pending") != "completed":
                return int(record.get("step_index") or 0)
        return max(0, len(list(state.get("steps") or [])))

    def _merge_artifacts(self, state: dict[str, Any], artifacts: list[dict[str, Any]]) -> None:
        seen = {str(item.get("path") or "") for item in list(state.get("artifacts") or []) if str(item.get("path") or "")}
        merged = list(state.get("artifacts") or [])
        for item in list(artifacts or []):
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            if not path or path in seen:
                continue
            merged.append(dict(item))
            seen.add(path)
        state["artifacts"] = merged

    def _refresh_metadata_plan(self, state: dict[str, Any]) -> None:
        metadata = dict(state.get("metadata") or {}) if isinstance(state.get("metadata"), dict) else {}
        current_plan = {
            "name": str(metadata.get("plan", {}).get("name") or state.get("name") or "").strip(),
            "goal": str(metadata.get("plan", {}).get("goal") or state.get("goal") or "").strip(),
            "steps": [dict(item) for item in list(state.get("step_definitions") or []) if isinstance(item, dict)],
        }
        if "original_plan" not in metadata and isinstance(metadata.get("plan"), dict):
            metadata["original_plan"] = dict(metadata.get("plan") or {})
        metadata["plan"] = current_plan
        state["metadata"] = metadata

    def _current_observation(self, *, state: dict[str, Any], result: dict[str, Any], verification: dict[str, Any], step_index: int) -> dict[str, Any]:
        return {
            "step_index": int(step_index or 0),
            "failed_codes": [str(code).strip() for code in list(verification.get("failed_codes") or []) if str(code).strip()],
            "ui_state": dict(result.get("ui_state") or {}) if isinstance(result.get("ui_state"), dict) else {},
            "browser_state": dict(result.get("browser_state") or {}) if isinstance(result.get("browser_state"), dict) else {},
            "desktop_host_state": dict(state.get("desktop_host_state") or {}) if isinstance(state.get("desktop_host_state"), dict) else {},
            "recovery_hints": dict(result.get("recovery_hints") or {}) if isinstance(result.get("recovery_hints"), dict) else {},
            "task_state": dict(result.get("task_state") or {}) if isinstance(result.get("task_state"), dict) else {},
        }

    def _is_replan_eligible(self, *, failure_codes: list[str], state: dict[str, Any], step_index: int) -> bool:
        if not failure_codes:
            return False
        if max(0, int(state.get("replan_count") or 0)) >= 2:
            return False
        per_step = 0
        for item in list(state.get("replan_history") or []):
            if isinstance(item, dict) and int(item.get("step_index") or 0) == int(step_index):
                per_step += 1
        return per_step < 1

    def _replace_remaining_steps(self, *, state: dict[str, Any], start_step_index: int, new_steps: list[dict[str, Any]]) -> None:
        prefix_defs = [dict(item) for item in list(state.get("step_definitions") or [])[: max(0, start_step_index - 1)] if isinstance(item, dict)]
        prefix_records = [
            self._coerce_step_record(record, index=index, definition=prefix_defs[index - 1] if index - 1 < len(prefix_defs) else {})
            for index, record in enumerate(list(state.get("steps") or [])[: max(0, start_step_index - 1)], start=1)
        ]
        state["step_definitions"] = prefix_defs + [dict(item) for item in list(new_steps or []) if isinstance(item, dict)]
        state["steps"] = prefix_records + [
            self._coerce_step_record({}, index=index, definition=definition)
            for index, definition in enumerate(list(state.get("step_definitions") or [])[max(0, start_step_index - 1) :], start=start_step_index)
        ]
        state["current_step"] = min(max(1, int(start_step_index or 1)), max(1, len(list(state.get("step_definitions") or []))))
        self._refresh_metadata_plan(state)

    def _record_replan(self, *, state: dict[str, Any], step_index: int, rationale: str, replan_trace: dict[str, Any], new_steps: list[dict[str, Any]]) -> None:
        state["replan_count"] = max(0, int(state.get("replan_count") or 0)) + 1
        state.setdefault("replan_history", [])
        state["replan_history"].append(
            {
                "step_index": int(step_index or 0),
                "rationale": str(rationale or "").strip(),
                "trace": dict(replan_trace or {}),
                "new_step_names": [str(item.get("name") or "").strip() for item in list(new_steps or []) if isinstance(item, dict)],
                "timestamp": float(time.time()),
            }
        )

    async def create_task(
        self,
        *,
        goal: str,
        steps: list[dict[str, Any]],
        name: str = "",
        task_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_name = str(name or goal or "operator-task").strip() or "operator-task"
        resolved_task_id = str(task_id or "").strip() or self._new_task_id(resolved_name)
        async with self._task_lock(resolved_task_id):
            existing = self._load_state(resolved_task_id)
            if existing is not None:
                return existing
            state = self._base_state(task_id=resolved_task_id, name=resolved_name, goal=goal, steps=steps, metadata=metadata)
            return self._persist_state(state)

    async def get_task_state(self, task_id: str) -> dict[str, Any]:
        async with self._task_lock(task_id):
            return self._load_state(task_id) or {}

    async def get_failed_step(self, task_id: str) -> dict[str, Any]:
        async with self._task_lock(task_id):
            state = self._load_state(task_id) or {}
            failed = list(state.get("failed_steps") or [])
            return dict(failed[-1]) if failed else {}

    async def get_retry_history(self, task_id: str) -> list[dict[str, Any]]:
        async with self._task_lock(task_id):
            state = self._load_state(task_id) or {}
            return [dict(item) for item in list(state.get("repair_history") or []) if isinstance(item, dict)]

    async def get_replan_history(self, task_id: str) -> list[dict[str, Any]]:
        async with self._task_lock(task_id):
            state = self._load_state(task_id) or {}
            return [dict(item) for item in list(state.get("replan_history") or []) if isinstance(item, dict)]

    async def reset_task(self, task_id: str, *, clear_live_state: bool = False) -> dict[str, Any]:
        async with self._task_lock(task_id):
            state = self._load_state(task_id)
            if state is None:
                return {}
            if clear_live_state:
                await self.desktop_host.clear_live_state()
            reset = self._base_state(task_id=task_id, name=str(state.get("name") or task_id), goal=str(state.get("goal") or ""), steps=list(state.get("step_definitions") or []))
            reset["created_at"] = float(state.get("created_at") or time.time())
            reset["metadata"] = dict(state.get("metadata") or {}) if isinstance(state.get("metadata"), dict) else {}
            return self._persist_state(reset)

    async def clear_task(self, task_id: str, *, clear_live_state: bool = False) -> dict[str, Any]:
        async with self._task_lock(task_id):
            paths = self._state_paths(task_id)
            if clear_live_state:
                await self.desktop_host.clear_live_state()
            if paths["root"].exists():
                shutil.rmtree(paths["root"])
            return {"task_id": str(task_id or "").strip(), "cleared": True}

    async def run_task(
        self,
        task_id: str,
        *,
        screen_services: Any = None,
        browser_services: Any = None,
        clear_live_state: bool = False,
    ) -> dict[str, Any]:
        async with self._task_lock(task_id):
            state = self._load_state(task_id)
            if state is None:
                return {
                    "success": False,
                    "status": "failed",
                    "error": "task_not_found",
                    "error_code": "TASK_NOT_FOUND",
                    "message": f"Task not found: {task_id}",
                    "task_state": {},
                }
            if clear_live_state:
                await self.desktop_host.clear_live_state()
            state["status"] = "running"
            state["current_step"] = self._next_pending_step(state)
            state.setdefault("action_logs", [])
            state.setdefault("target_decisions", [])
            state.setdefault("replan_history", [])
            state.setdefault("latest_observation", {})
            self._refresh_metadata_plan(state)
            self._persist_state(state)

            overall_success = True
            final_error = ""
            final_error_code = ""
            step_index = max(1, int(state.get("current_step") or 1)) if list(state.get("step_definitions") or []) else 0

            while step_index and step_index <= len(list(state.get("step_definitions") or [])):
                steps = [dict(item) for item in list(state.get("step_definitions") or []) if isinstance(item, dict)]
                step = steps[step_index - 1]
                record = state["steps"][step_index - 1]
                if str(record.get("status") or "") == "completed" and bool((record.get("verification") if isinstance(record.get("verification"), dict) else {}).get("ok")):
                    step_index += 1
                    continue
                state["current_step"] = step_index
                attempts = max(0, int(record.get("attempts") or 0))
                retry_budget = self._step_retry_budget(step)
                next_step_index = step_index + 1
                while True:
                    attempts += 1
                    if str(step.get("kind") or "screen").strip().lower() == "system":
                        result = await self._run_system_step(step, screen_services=screen_services)
                    elif str(step.get("kind") or "screen").strip().lower() == "browser":
                        result = await self._run_browser_step(step, browser_services=browser_services, screen_services=screen_services)
                    else:
                        result = await self._run_screen_step(step, screen_services=screen_services)
                    verification = self._verify_step(step=step, result=result if isinstance(result, dict) else {})
                    copied_screenshots = self._copy_step_screenshots(state=state, step_index=step_index, screenshots=list(result.get("screenshots") or []))
                    step_artifacts = [dict(item) for item in list(result.get("artifacts") or []) if isinstance(item, dict)] + [
                        {"path": path, "type": "image"} for path in copied_screenshots
                    ]
                    record.update(
                        {
                            "status": "completed" if verification.get("ok") else "failed",
                            "attempts": attempts,
                            "verification": dict(verification or {}),
                            "message": str(result.get("message") or result.get("summary") or result.get("error") or "").strip(),
                            "error": str(result.get("error") or "").strip(),
                            "error_code": str(result.get("error_code") or "").strip(),
                            "screenshots": copied_screenshots,
                            "artifacts": step_artifacts,
                            "result": dict(result or {}),
                        }
                    )
                    state["last_ui_state"] = dict(result.get("ui_state") or state.get("last_ui_state") or {})
                    state["browser_state"] = dict(result.get("browser_state") or state.get("browser_state") or {})
                    state["desktop_host_state"] = dict(result.get("desktop_host_state") or await self.desktop_host.get_live_state() or {})
                    state["latest_observation"] = self._current_observation(state=state, result=result if isinstance(result, dict) else {}, verification=verification, step_index=step_index)
                    self._merge_artifacts(state, step_artifacts)
                    for entry in list(result.get("action_logs") or []):
                        if isinstance(entry, dict):
                            state["action_logs"].append({"task_step": step_index, "task_step_name": str(record.get("name") or ""), **dict(entry)})
                    state["target_decisions"].extend(_extract_target_decisions(result if isinstance(result, dict) else {}))
                    state["verifier_outcomes"].append(
                        {
                            "step_index": step_index,
                            "name": str(record.get("name") or ""),
                            "kind": str(record.get("kind") or ""),
                            "verification": dict(verification or {}),
                        }
                    )
                    state["completed_steps"] = sorted({int(item) for item in list(state.get("completed_steps") or []) if isinstance(item, int) or str(item).isdigit()} | ({step_index} if verification.get("ok") else set()))
                    state["failed_steps"] = [item for item in list(state.get("failed_steps") or []) if int(item.get("step_index") or 0) != step_index]
                    if verification.get("ok"):
                        state["retry_counts"][str(step_index)] = max(0, int(state.get("retry_counts", {}).get(str(step_index), 0)))
                        state["last_failure_reason"] = ""
                        planner_replan = self._planner().replan_remaining(
                            task_state=state,
                            latest_result=result if isinstance(result, dict) else {},
                            latest_verification=verification,
                            desktop_state=state.get("desktop_host_state") if isinstance(state.get("desktop_host_state"), dict) else {},
                            browser_state=state.get("browser_state") if isinstance(state.get("browser_state"), dict) else {},
                        )
                        new_remaining = [dict(item) for item in list(planner_replan.get("remaining_steps") or []) if isinstance(item, dict)]
                        current_remaining = [dict(item) for item in list(state.get("step_definitions") or [])[step_index:] if isinstance(item, dict)]
                        if new_remaining != current_remaining:
                            self._record_replan(
                                state=state,
                                step_index=step_index + 1,
                                rationale=str(planner_replan.get("rationale") or "post_step_replan"),
                                replan_trace=dict(planner_replan.get("replan_trace") or {}),
                                new_steps=new_remaining,
                            )
                            self._replace_remaining_steps(state=state, start_step_index=step_index + 1, new_steps=new_remaining)
                            next_step_index = step_index + 1
                        break

                    failure_codes = self._failure_codes(result=result, verification=verification)
                    state["last_failure_reason"] = failure_codes[0] if failure_codes else str(record.get("error_code") or "TASK_STEP_FAILED")
                    state["failed_steps"].append(
                        {
                            "step_index": step_index,
                            "name": str(record.get("name") or ""),
                            "kind": str(record.get("kind") or ""),
                            "attempts": attempts,
                            "failed_codes": failure_codes,
                            "message": str(record.get("message") or "").strip(),
                        }
                    )
                    retry_count = max(0, int(state.get("retry_counts", {}).get(str(step_index), 0)))
                    if self._is_repairable(step=step, result=result, verification=verification) and retry_count < retry_budget:
                        retry_count += 1
                        state["retry_counts"][str(step_index)] = retry_count
                        state["repair_history"].append(
                            {
                                "step_index": step_index,
                                "name": str(record.get("name") or ""),
                                "kind": str(record.get("kind") or ""),
                                "attempt": attempts,
                                "retry_count": retry_count,
                                "failed_codes": failure_codes,
                                "strategy": "rerun_step",
                                "status": "retry_scheduled",
                                "timestamp": float(time.time()),
                            }
                        )
                        self._persist_state(state)
                        continue

                    if self._is_replan_eligible(failure_codes=failure_codes, state=state, step_index=step_index):
                        planner_replan = self._planner().replan_remaining(
                            task_state=state,
                            latest_result=result if isinstance(result, dict) else {},
                            latest_verification=verification,
                            desktop_state=state.get("desktop_host_state") if isinstance(state.get("desktop_host_state"), dict) else {},
                            browser_state=state.get("browser_state") if isinstance(state.get("browser_state"), dict) else {},
                        )
                        new_remaining = [dict(item) for item in list(planner_replan.get("remaining_steps") or []) if isinstance(item, dict)]
                        current_remaining = [dict(item) for item in list(state.get("step_definitions") or [])[max(0, step_index - 1) :] if isinstance(item, dict)]
                        if new_remaining and new_remaining != current_remaining:
                            self._record_replan(
                                state=state,
                                step_index=step_index,
                                rationale=str(planner_replan.get("rationale") or "failure_replan"),
                                replan_trace=dict(planner_replan.get("replan_trace") or {}),
                                new_steps=new_remaining,
                            )
                            self._replace_remaining_steps(state=state, start_step_index=step_index, new_steps=new_remaining)
                            next_step_index = step_index
                            break

                    overall_success = False
                    final_error = str(record.get("error") or record.get("message") or "task_step_failed").strip() or "task_step_failed"
                    final_error_code = failure_codes[0] if failure_codes else str(record.get("error_code") or "TASK_STEP_FAILED")
                    break

                self._persist_state(state)
                if not overall_success:
                    break
                step_index = next_step_index

            if overall_success:
                state["status"] = "completed"
                state["current_step"] = max(0, len(list(state.get("step_definitions") or [])))
            else:
                state["status"] = "failed"
                state["current_step"] = max(1, int(state.get("current_step") or 1))
            persisted = self._persist_state(state)

        response = {
            "success": bool(overall_success),
            "status": str(persisted.get("status") or ("completed" if overall_success else "failed")),
            "message": f"Task {persisted.get('name')} completed." if overall_success else f"Task {persisted.get('name')} failed.",
            "task_id": str(persisted.get("task_id") or "").strip(),
            "task_state": persisted,
            "artifacts": list(persisted.get("artifacts") or []),
            "verifier_outcomes": list(persisted.get("verifier_outcomes") or []),
            "replan_history": list(persisted.get("replan_history") or []),
        }
        if not overall_success:
            response["error"] = final_error or "task_step_failed"
            response["error_code"] = final_error_code or "TASK_STEP_FAILED"
        return response

    async def resume_task(
        self,
        task_id: str,
        *,
        screen_services: Any = None,
        browser_services: Any = None,
    ) -> dict[str, Any]:
        return await self.run_task(task_id, screen_services=screen_services, browser_services=browser_services, clear_live_state=False)

    async def start_task(
        self,
        *,
        goal: str,
        steps: list[dict[str, Any]],
        name: str = "",
        task_id: str = "",
        metadata: dict[str, Any] | None = None,
        screen_services: Any = None,
        browser_services: Any = None,
        clear_live_state: bool = False,
    ) -> dict[str, Any]:
        created = await self.create_task(goal=goal, steps=steps, name=name, task_id=task_id, metadata=metadata)
        return await self.run_task(str(created.get("task_id") or ""), screen_services=screen_services, browser_services=browser_services, clear_live_state=clear_live_state)


__all__ = ["OperatorTaskRuntime"]
