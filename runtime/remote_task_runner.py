from __future__ import annotations

import datetime as dt
import time
import uuid
from typing import Any

from runtime import state_store
from runtime.agent_planning import build_agent_plan
from runtime.backend_client import BackendResult
from runtime.capability_registry import capability_readiness


REMOTE_TASK_RUNNER_VERSION = "remote_task_orchestrator_v1"
BACKEND_TASK_STATUSES = {"queued", "planning", "running", "waiting_approval", "completed", "failed", "canceled"}
TERMINAL_STATUSES = {"completed", "failed", "canceled", "cancelled"}
ACTIVE_STATUSES = {"queued", "planning", "running", "waiting_approval"}
LOCAL_TRACE_STATUSES = {"readiness_check", "verifying", "repairing", "failed_safe"}


def _utc_now_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _safe_text(value: Any, limit: int = 1000) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _normalize_capability(value: Any) -> str:
    text = " ".join(str(value or "").strip().lower().split())
    return text.replace(" ", "_")


def _safe_error_code(value: Any, fallback: str = "REMOTE_TASK_FAILED") -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return fallback
    return "".join(ch if ch.isalnum() else "_" for ch in raw)[:80] or fallback


def _backend_task_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status in BACKEND_TASK_STATUSES:
        return status
    if status in {"readiness_check"}:
        return "planning"
    if status in {"verifying", "repairing"}:
        return "running"
    if status in {"failed_safe", "error"}:
        return "failed"
    if status == "cancelled":
        return "canceled"
    return "running"


class RemoteTaskRunner:
    """Backend-assigned task orchestration around the existing bridge/executor seams.

    The runner intentionally delegates capability execution to RuntimeBridge. It owns
    remote lifecycle, readiness, idempotency, approval pause/resume, and backend payload
    normalization without creating a second task product model.
    """

    def __init__(self, host: Any) -> None:
        self.host = host

    def execute_assigned_runtime_tasks(self, limit: int = 1) -> dict[str, Any]:
        self.host._assigned_task_fetch_requested.clear()
        self.host._last_assigned_task_fetch_at = time.monotonic()
        assigned = self.host.backend.runtime_tasks_assigned()
        if not assigned.ok:
            return {
                "ok": False,
                "error": {"code": "TASK_FETCH_FAILED", "message": "Atanmış görevler alınamadı."},
                "result": assigned.to_dict(),
            }

        data = assigned.data if isinstance(assigned.data, dict) else {}
        tasks = data.get("tasks", [])
        if not isinstance(tasks, list):
            tasks = []
        self._sync_assigned_items(tasks)

        executions: list[dict[str, Any]] = []
        for task in tasks[: max(1, limit)]:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("id", "") or "").strip()
            status = str(task.get("status", "") or "").strip().lower()
            if status in {"canceled", "cancelled"}:
                self.host._discard_remote_pending_task_locally(task_id)
                self._upsert_local_task(
                    task_id,
                    status="canceled",
                    summary="Görev iptal edildi.",
                    approval_request={},
                )
                self.host._remember_terminal_assigned_task(task_id)
                executions.append({"taskId": task_id, "ok": True, "status": "skipped_terminal"})
                continue
            if status in {"completed", "failed", "failed_safe"}:
                self.host._remove_remote_task_local_link(task_id)
                self.host._remember_terminal_assigned_task(task_id)
                executions.append({"taskId": task_id, "ok": True, "status": "skipped_terminal"})
                continue

            execution_gate = self.host._begin_assigned_task_execution(task_id)
            if execution_gate != "accepted":
                executions.append({"taskId": task_id, "ok": True, "status": execution_gate})
                continue

            try:
                approval_request = task.get("approvalRequest", {})
                approval_request = approval_request if isinstance(approval_request, dict) else {}
                if status == "waiting_approval":
                    resolution_state = self.host._approval_resolution_state(approval_request)
                    if resolution_state == "approved":
                        executions.append(self.resume_after_approval(task_id, True))
                    elif resolution_state == "rejected":
                        executions.append(self.resume_after_approval(task_id, False))
                    else:
                        executions.append({"taskId": task_id, "ok": True, "status": "waiting_approval"})
                    continue
                executions.append(self.execute_runtime_task(task, dispatched_via_websocket=False))
            finally:
                self.host._clear_assigned_task_inflight(task_id)

        return {"ok": True, "executions": executions, "fetched": len(tasks)}

    def execute_runtime_task(self, task: dict[str, Any], dispatched_via_websocket: bool = False) -> dict[str, Any]:
        task_id = str(task.get("id", "") or "").strip()
        payload = task.get("payload", {})
        payload = payload if isinstance(payload, dict) else {}
        title = str(task.get("title", "") or payload.get("title", "") or "Elyan görevi")
        prompt = str(payload.get("prompt", "") or payload.get("message", "") or title).strip()
        task_run_id = self._ensure_task_run_id(task_id)
        if not task_id:
            return {"taskId": "", "ok": False, "status": "missing_task_id"}

        preflight_error = self.host._runtime_task_preflight_error(task, payload)
        if preflight_error is not None:
            return self._fail_safe(
                task_id,
                task_run_id,
                message=preflight_error["message"],
                error_code=preflight_error["code"],
                result_status="failed_closed",
            )
        if not prompt:
            return self._fail_safe(
                task_id,
                task_run_id,
                message="Görev metni boş.",
                error_code="TASK_PROMPT_MISSING",
            )

        self._report_lifecycle(task_id, task_run_id, "planning", "Görev planlanıyor.", task=task)
        plan_preview = self.host._remote_task_running_plan_preview(task, prompt, payload)
        readiness = self._readiness_for_plan(plan_preview)
        if plan_preview:
            self._report_lifecycle(
                task_id,
                task_run_id,
                "readiness_check",
                "Capability readiness kontrol ediliyor.",
                task=task,
                plan_preview=plan_preview,
                capability_readiness_payload=readiness,
            )
            readiness_error = self._readiness_error(readiness)
            if readiness_error is not None:
                return self._fail_safe(
                    task_id,
                    task_run_id,
                    message=readiness_error["message"],
                    error_code=readiness_error["code"],
                    plan_preview=plan_preview,
                    capability_readiness_payload=readiness,
                )

        self.host._set_runtime_task_heartbeat(dispatched_via_websocket, "busy", task_id)
        running_payload = self._status_payload(
            task_id,
            task_run_id,
            status="running",
            message="Desktop runtime görevi yürütüyor.",
            task=task,
            plan_preview=plan_preview,
            capability_readiness_payload=readiness,
        )
        running = self.host._report_runtime_task_status(task_id, running_payload)
        if running is None or not running.ok:
            self.host._set_runtime_task_heartbeat(dispatched_via_websocket, "idle")
            return {"taskId": task_id, "ok": False, "status": "running_rejected", "report": running.to_dict() if running else None}

        try:
            local_result = self.host._execute_deterministic_remote_task(task, prompt, title)
            if local_result is None:
                local_result = self.host.send_conversation("", prompt, title)
            local_result = self._augment_local_result(
                local_result,
                task_id=task_id,
                task_run_id=task_run_id,
                plan_preview=plan_preview,
                capability_readiness_payload=readiness,
            )
            if local_result.get("needsConfirmation") is True and str(local_result.get("pendingPlanId", "") or "").strip():
                return self._pause_for_approval(task_id, task_run_id, title, local_result, dispatched_via_websocket)

            self._report_lifecycle(
                task_id,
                task_run_id,
                "verifying",
                "Görev sonucu doğrulanıyor.",
                task=task,
                plan_preview=local_result.get("planPreview") if isinstance(local_result.get("planPreview"), dict) else plan_preview,
                capability_readiness_payload=readiness,
            )
            result = self.host._report_runtime_task_terminal_result(
                task_id,
                local_result,
                dispatched_via_websocket=dispatched_via_websocket,
            )
            self._mark_link_terminal(task_id, result.get("status", "completed"))
            return result
        finally:
            self.host._set_runtime_task_heartbeat(dispatched_via_websocket, "idle")

    def resume_after_approval(self, task_id: str, approved: bool) -> dict[str, Any]:
        if not approved:
            self.host._cancel_remote_pending_task(task_id)
            self._mark_link_terminal(task_id, "canceled")
            return {"taskId": task_id, "ok": True, "status": "canceled"}

        link = state_store.get_remote_task_link(task_id)
        task_run_id = str((link or {}).get("taskRunId", "") or "").strip() or self._ensure_task_run_id(task_id)
        if not isinstance(link, dict):
            self.host._runtime_diag("task_approval_missing_link", task_id=task_id)
            return self._fail_safe(
                task_id,
                task_run_id,
                message="Onay bağlantısı bulunamadı. Görev güvenli şekilde durduruldu.",
                error_code="pending_link_missing",
            )

        pending_plan_id = str(link.get("pendingPlanId", "") or "").strip()
        conversation_id = str(link.get("conversationId", "") or "").strip()
        if not pending_plan_id:
            self.host._runtime_diag("task_approval_missing_plan", task_id=task_id)
            state_store.remove_remote_task_link(task_id)
            return self._fail_safe(
                task_id,
                task_run_id,
                message="Onay bekleyen yerel plan bulunamadı. Görev güvenli şekilde durduruldu.",
                error_code="pending_plan_missing",
            )

        self.host._set_runtime_task_heartbeat(False, "busy", task_id)
        running = self.host._report_runtime_task_status(
            task_id,
            self._status_payload(
                task_id,
                task_run_id,
                status="running",
                message="Onay alındı, görev sürdürülüyor.",
                approval_request={},
            ),
        )
        if running is None or not running.ok:
            self.host._set_runtime_task_heartbeat(False, "idle")
            return {"taskId": task_id, "ok": False, "status": "running_rejected", "report": running.to_dict() if running else None}

        try:
            self._report_lifecycle(task_id, task_run_id, "repairing", "Onaylanan adım yürütülüyor.")
            local_result = self.host.confirm_conversation_plan(conversation_id, pending_plan_id, True)
            local_result = self._augment_local_result(local_result, task_id=task_id, task_run_id=task_run_id)
            self._report_lifecycle(task_id, task_run_id, "verifying", "Görev sonucu doğrulanıyor.")
            result = self.host._report_runtime_task_terminal_result(
                task_id,
                local_result,
                dispatched_via_websocket=False,
                separate_artifacts=True,
            )
            state_store.remove_remote_task_link(task_id)
            self._mark_link_terminal(task_id, result.get("status", "completed"))
            return result
        finally:
            self.host._set_runtime_task_heartbeat(False, "idle")

    def _sync_assigned_items(self, tasks: list[Any]) -> None:
        if tasks:
            items = [
                self.host._normalized_task_inbox_item(task)
                for task in tasks
                if isinstance(task, dict) and str(task.get("id", "") or "").strip()
            ]
            for item in items:
                state_store.upsert_task_inbox_item(item, last_synced_at=_utc_now_iso())
        self.host._reconcile_task_inbox_active_truth(
            {str(task.get("id", "") or "").strip() for task in tasks if isinstance(task, dict)}
        )

    def _ensure_task_run_id(self, task_id: str) -> str:
        link = state_store.get_remote_task_link(task_id)
        if isinstance(link, dict):
            existing = str(link.get("taskRunId", "") or "").strip()
            if existing:
                return existing
        task_run_id = f"run_{uuid.uuid4().hex[:12]}"
        if task_id:
            state_store.update_remote_task_link(task_id, {"taskRunId": task_run_id, "remoteTaskId": task_id}) or state_store.save_remote_task_link(
                task_id,
                "",
                "",
                status="planning",
                task_run_id=task_run_id,
                remote_task_id=task_id,
            )
        return task_run_id

    def _readiness_for_plan(self, plan_preview: dict[str, Any]) -> list[dict[str, Any]]:
        steps = plan_preview.get("steps", []) if isinstance(plan_preview, dict) else []
        if not isinstance(steps, list):
            return []
        result: list[dict[str, Any]] = []
        snapshot = state_store.snapshot()
        seen: set[str] = set()
        for step in steps:
            if not isinstance(step, dict):
                continue
            capability = _normalize_capability(step.get("capability"))
            if not capability or capability in seen:
                continue
            seen.add(capability)
            ready = capability_readiness(capability, state=snapshot)
            result.append(
                {
                    "capability": capability,
                    "ready": bool(ready.get("ready", False)),
                    "available": bool(ready.get("available", False)),
                    "dependencyReady": bool(ready.get("dependencyReady", False)),
                    "platformSupported": bool(ready.get("platformSupported", True)),
                    "permissionClass": str(ready.get("permissionClass", "") or ""),
                    "osPermissionStatus": str(ready.get("osPermissionStatus", "") or ""),
                    "errorCode": str(ready.get("errorCode", "") or ""),
                    "missingDependencies": list(ready.get("missingDependencies", []) or []),
                    "degradationReason": str(ready.get("degradationReason", "") or ""),
                }
            )
        return result

    def _readiness_error(self, readiness: list[dict[str, Any]]) -> dict[str, str] | None:
        for item in readiness:
            if item.get("ready") is True:
                continue
            capability = str(item.get("capability", "") or "capability")
            code = _safe_error_code(item.get("errorCode"), "CAPABILITY_NOT_READY")
            if code == "DEPENDENCY_UNAVAILABLE" and capability.startswith("quantum_"):
                code = "QUANTUM_DEPENDENCY_UNAVAILABLE"
            if code == "UNSUPPORTED_PLATFORM":
                message = f"{capability} bu işletim sisteminde desteklenmiyor."
            elif code == "OS_PERMISSION_REQUIRED":
                message = f"{capability} için işletim sistemi izni gerekiyor."
            elif code == "QUANTUM_DEPENDENCY_UNAVAILABLE":
                message = "Quantum görevi için Qiskit/Aer bağımlılığı hazır değil."
            else:
                message = f"{capability} için gerekli bağımlılık hazır değil."
            return {"code": code, "message": message}
        return None

    def _status_payload(
        self,
        task_id: str,
        task_run_id: str,
        *,
        status: str,
        message: str,
        task: dict[str, Any] | None = None,
        plan_preview: dict[str, Any] | None = None,
        capability_readiness_payload: list[dict[str, Any]] | None = None,
        approval_request: dict[str, Any] | None = None,
        error_code: str = "",
    ) -> dict[str, Any]:
        preview = dict(plan_preview) if isinstance(plan_preview, dict) else {}
        trace = self._trace_for_status(task_id, task_run_id, status, preview)
        safe_summary = _safe_text(message, 1000)
        canonical = {
            "taskId": task_id,
            "taskRunId": task_run_id,
            "runnerVersion": REMOTE_TASK_RUNNER_VERSION,
            "plan": preview,
            "stepStates": trace.get("steps", []),
            "capabilityReadiness": capability_readiness_payload or [],
            "approvalRequest": approval_request or {},
            "executionTrace": trace,
            "verification": {"status": "pending" if status not in TERMINAL_STATUSES else status},
            "repair": {"attempted": status == "repairing", "repairAttempts": 1 if status == "repairing" else 0},
            "artifacts": [],
            "safeSummary": safe_summary,
        }
        payload: dict[str, Any] = {
            "status": _backend_task_status(status),
            "message": message,
            "summary": safe_summary,
            "approvalRequest": approval_request or {},
            "artifacts": [],
            "result": canonical,
            "executionTrace": trace,
            "capabilityReadiness": capability_readiness_payload or [],
            "taskRunId": task_run_id,
        }
        if preview:
            payload["planPreview"] = preview
        if error_code:
            payload["error"] = error_code
            canonical["error"] = {"code": error_code, "message": message}
        if isinstance(task, dict):
            payload["routeDecision"] = task.get("routeDecision") if isinstance(task.get("routeDecision"), dict) else {}
        return payload

    def _trace_for_status(self, task_id: str, task_run_id: str, status: str, plan_preview: dict[str, Any]) -> dict[str, Any]:
        trace = self.host._remote_task_trace_payload(plan_preview, status=status, task_id=task_id) if plan_preview else {
            "type": "task_trace",
            "taskId": task_id,
            "status": status,
            "title": "Görev yürütülüyor.",
            "steps": [],
            "visibility": "user_visible",
            "agentPlan": build_agent_plan([], summary=""),
        }
        trace["taskRunId"] = task_run_id
        trace["runnerVersion"] = REMOTE_TASK_RUNNER_VERSION
        return trace

    def _report_lifecycle(
        self,
        task_id: str,
        task_run_id: str,
        status: str,
        message: str,
        *,
        task: dict[str, Any] | None = None,
        plan_preview: dict[str, Any] | None = None,
        capability_readiness_payload: list[dict[str, Any]] | None = None,
    ) -> BackendResult | None:
        payload = self._status_payload(
            task_id,
            task_run_id,
            status=status,
            message=message,
            task=task,
            plan_preview=plan_preview,
            capability_readiness_payload=capability_readiness_payload,
        )
        state_store.upsert_task_inbox_item(
            {
                "id": task_id,
                "status": _backend_task_status(status),
                "summary": payload.get("summary", ""),
                "planPreview": payload.get("planPreview", {}),
                "executionTrace": payload.get("executionTrace", {}),
                "capabilityReadiness": payload.get("capabilityReadiness", []),
                "taskRunId": task_run_id,
                "updatedAt": _utc_now_iso(),
            },
            last_synced_at=_utc_now_iso(),
        )
        state_store.update_remote_task_link(
            task_id,
            {"status": status, "lastBackendStatus": _backend_task_status(status), "taskRunId": task_run_id},
        )
        return BackendResult(ok=True, request_id="", status_code=200, data={"ok": True, "transport": "local_lifecycle"})

    def _fail_safe(
        self,
        task_id: str,
        task_run_id: str,
        *,
        message: str,
        error_code: str,
        plan_preview: dict[str, Any] | None = None,
        capability_readiness_payload: list[dict[str, Any]] | None = None,
        result_status: str = "failed",
    ) -> dict[str, Any]:
        payload = self._status_payload(
            task_id,
            task_run_id,
            status="failed",
            message=message,
            plan_preview=plan_preview,
            capability_readiness_payload=capability_readiness_payload,
            error_code=str(error_code or "remote_task_failed"),
        )
        payload["result"]["assistantMessage"] = message
        payload["result"]["provider"] = "remote_task_runner"
        report = self.host._report_runtime_task_status(task_id, payload)
        self._mark_link_terminal(task_id, "failed_safe")
        return {
            "taskId": task_id,
            "ok": False,
            "status": result_status,
            "report": report.to_dict() if report else None,
        }

    def _pause_for_approval(
        self,
        task_id: str,
        task_run_id: str,
        title: str,
        local_result: dict[str, Any],
        dispatched_via_websocket: bool,
    ) -> dict[str, Any]:
        pending_plan_id = str(local_result.get("pendingPlanId", "") or "").strip()
        conversation_id = str(local_result.get("conversationId", "") or "").strip()
        permission_error = self.host._pending_plan_permission_error(pending_plan_id)
        if permission_error is not None:
            state_store.remove_pending_plan(pending_plan_id)
            return self._fail_safe(
                task_id,
                task_run_id,
                message=str(permission_error.get("message", "") or "Görev için açık izin gerekiyor."),
                error_code=str(permission_error.get("code", "") or "PERMISSION_REQUIRED"),
                plan_preview=local_result.get("planPreview") if isinstance(local_result.get("planPreview"), dict) else None,
                capability_readiness_payload=local_result.get("capabilityReadiness") if isinstance(local_result.get("capabilityReadiness"), list) else None,
            )

        approval_request = self.host._approval_request_payload(local_result)
        waiting_result = {
            "assistantMessage": str(local_result.get("assistantMessage", "") or "").strip(),
            "provider": str(local_result.get("provider", "") or ""),
            "toolEvents": local_result.get("toolEvents", []) if isinstance(local_result.get("toolEvents"), list) else [],
            "conversationId": conversation_id,
            "taskRunId": task_run_id,
            "approvalRequest": approval_request,
        }
        plan_preview = local_result.get("planPreview") if isinstance(local_result.get("planPreview"), dict) else {}
        execution_trace = local_result.get("executionTrace") if isinstance(local_result.get("executionTrace"), dict) else {}
        if plan_preview:
            waiting_result["planPreview"] = dict(plan_preview)
        if execution_trace:
            waiting_result["executionTrace"] = dict(execution_trace)
        state_store.save_remote_task_link(
            task_id,
            pending_plan_id,
            conversation_id,
            title=title,
            status="waiting_approval",
            task_run_id=task_run_id,
            remote_task_id=task_id,
            last_backend_status="waiting_approval",
            resume_token=str(local_result.get("resumeToken", "") or pending_plan_id),
        )
        payload = self._status_payload(
            task_id,
            task_run_id,
            status="waiting_approval",
            message="Yerel onay bekleniyor.",
            plan_preview=plan_preview if isinstance(plan_preview, dict) else None,
            capability_readiness_payload=local_result.get("capabilityReadiness") if isinstance(local_result.get("capabilityReadiness"), list) else None,
            approval_request=approval_request,
        )
        payload["summary"] = approval_request.get("summary", payload["summary"]) or payload["summary"]
        payload["result"] = {**payload["result"], **waiting_result}
        report = self.host._report_runtime_task_status(task_id, payload)
        self.host._set_runtime_task_heartbeat(dispatched_via_websocket, "idle")
        return {
            "taskId": task_id,
            "ok": bool(report and report.ok),
            "status": "waiting_approval",
            "report": report.to_dict() if report else None,
            "local": {"conversationId": conversation_id, "provider": waiting_result["provider"], "pendingPlanId": pending_plan_id},
        }

    def _augment_local_result(
        self,
        local_result: dict[str, Any],
        *,
        task_id: str,
        task_run_id: str,
        plan_preview: dict[str, Any] | None = None,
        capability_readiness_payload: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        result = dict(local_result) if isinstance(local_result, dict) else {}
        preview = result.get("planPreview") if isinstance(result.get("planPreview"), dict) else plan_preview
        if isinstance(preview, dict):
            result["planPreview"] = dict(preview)
        trace = result.get("executionTrace") if isinstance(result.get("executionTrace"), dict) else None
        if isinstance(trace, dict):
            trace = dict(trace)
            trace["taskRunId"] = task_run_id
            trace["runnerVersion"] = REMOTE_TASK_RUNNER_VERSION
            result["executionTrace"] = trace
        elif isinstance(preview, dict):
            result["executionTrace"] = self._trace_for_status(task_id, task_run_id, "completed", preview)
        result["taskRunId"] = task_run_id
        result["capabilityReadiness"] = capability_readiness_payload or result.get("capabilityReadiness", [])
        result["agentStatus"] = {
            "remoteTask": {
                "taskId": task_id,
                "taskRunId": task_run_id,
                "runnerVersion": REMOTE_TASK_RUNNER_VERSION,
            }
        }
        return result

    def _upsert_local_task(
        self,
        task_id: str,
        *,
        status: str,
        summary: str = "",
        approval_request: dict[str, Any] | None = None,
    ) -> None:
        state_store.upsert_task_inbox_item(
            {
                "id": task_id,
                "status": status,
                "summary": summary,
                "approvalRequest": approval_request or {},
                "updatedAt": _utc_now_iso(),
            },
            last_synced_at=_utc_now_iso(),
        )

    def _mark_link_terminal(self, task_id: str, status: str) -> None:
        state_store.update_remote_task_link(
            task_id,
            {
                "status": status,
                "lastBackendStatus": status,
                "terminalDuplicateGuard": True,
            },
        )
