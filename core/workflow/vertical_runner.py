"""
Deterministic vertical workflow runner for Elyan vNext.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import os
import time
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from core.billing.reconciliation_bridge import activate_billing_usage_scope
from core.persistence import get_runtime_database, sync_runtime_outbox_once
from core.run_store import RunRecord, RunStore, get_run_store
from tools.pro_workflows import create_web_project_scaffold, generate_document_pack
from utils.logger import get_logger

from .contracts import FLOW_TEMPLATES, WorkflowLifecycleState, WorkflowTaskType
from .state_machine import WorkflowState, WorkflowStateMachine

logger = get_logger("workflow.vertical_runner")


def _publish_workflow_activity(*, event_type: str, channel: str, detail: str, success: bool = True) -> None:
    try:
        from core.gateway.server import push_activity

        push_activity(event_type, channel, detail, success)
    except Exception:
        return


def _publish_workflow_tool_event(
    *,
    stage: str,
    run_id: str,
    step_name: str,
    success: Optional[bool] = None,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    try:
        from core.gateway.server import push_tool_event

        push_tool_event(
            stage,
            "workflow",
            step=step_name,
            request_id=run_id,
            success=success,
            payload=payload or {},
        )
    except Exception:
        return


def _publish_cowork_event(event_type: str, payload: dict[str, Any]) -> None:
    try:
        from core.gateway.server import push_cowork_event

        push_cowork_event(event_type, payload)
    except Exception:
        return


class VerticalWorkflowRunner:
    """Run canonical document, presentation, and website flows."""

    def __init__(self):
        self._state_machine = WorkflowStateMachine()
        self._tasks: dict[str, asyncio.Task] = {}
        self._runtime_db = None

    def _execution_repo(self):
        if self._runtime_db is None:
            try:
                self._runtime_db = get_runtime_database()
            except Exception:
                self._runtime_db = False
        if not self._runtime_db:
            return None
        return getattr(self._runtime_db, "execution", None)

    async def _exec_db_call(self, method_name: str, **payload: Any) -> Any:
        repo = self._execution_repo()
        if repo is None:
            return None
        method = getattr(repo, method_name, None)
        if method is None:
            return None
        try:
            result = method(**payload)
            if inspect.isawaitable(result):
                return await result
            return result
        except TypeError:
            try:
                result = method(payload)
                if inspect.isawaitable(result):
                    return await result
                return result
            except Exception:
                return None
        except Exception:
            return None

    @staticmethod
    def _step_name_for_state(state: WorkflowLifecycleState) -> str:
        mapping = {
            WorkflowLifecycleState.CLASSIFIED: "classify_request",
            WorkflowLifecycleState.SCOPED: "scope_workflow",
            WorkflowLifecycleState.PLANNED: "build_plan",
            WorkflowLifecycleState.GATHERING_CONTEXT: "gather_context",
            WorkflowLifecycleState.EXECUTING: "execute_artifact_flow",
            WorkflowLifecycleState.REVIEWING: "review_artifact_output",
            WorkflowLifecycleState.READY_FOR_APPROVAL: "ready_for_approval",
            WorkflowLifecycleState.EXPORTING: "finalize_export_manifest",
        }
        return mapping.get(state, state.value)

    def _build_execution_plan(self, *, record: RunRecord, template, artifact_targets: list[str]) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        for index, stage in enumerate(template.stages, start=1):
            if stage.state == WorkflowLifecycleState.RECEIVED:
                continue
            step_name = self._step_name_for_state(stage.state)
            steps.append(
                {
                    "planned_step_id": f"plan_{record.run_id}_{step_name}",
                    "sequence_number": index,
                    "step_type": "workflow_stage",
                    "objective": step_name.replace("_", " "),
                    "expected_artifacts": list(artifact_targets if stage.state in {WorkflowLifecycleState.EXECUTING, WorkflowLifecycleState.EXPORTING} else []),
                    "verification_method": "artifact_review" if stage.state == WorkflowLifecycleState.REVIEWING else "stage_status",
                    "rollback_strategy": "retry_stage" if stage.retry_budget else "none",
                    "state": stage.state.value,
                    "owner": stage.owner.value,
                }
            )
        return steps

    async def _record_plan(self, *, record: RunRecord, steps: list[dict[str, Any]]) -> None:
        await self._exec_db_call(
            "persist_plan",
            run_id=record.run_id,
            steps=list(steps or []),
        )

    async def _record_execution_step_start(
        self,
        *,
        record: RunRecord,
        state: WorkflowLifecycleState,
        planned_step_id: str,
        step_name: str,
        payload: dict[str, Any] | None = None,
    ) -> str:
        result = await self._exec_db_call(
            "start_execution_step",
            run_id=record.run_id,
            planned_step_id=str(planned_step_id or ""),
            step_name=step_name,
            workflow_state=state.value,
            payload=dict(payload or {}),
        )
        return str(result or "")

    async def _record_execution_step_complete(
        self,
        *,
        execution_step_id: str,
        payload: dict[str, Any],
        success: bool = True,
    ) -> None:
        await self._exec_db_call(
            "complete_execution_step",
            execution_step_id=str(execution_step_id or ""),
            status="completed" if success else "failed",
            result=dict(payload or {}),
        )

    async def _record_verification(
        self,
        *,
        record: RunRecord,
        execution_step_id: str,
        method: str,
        payload: dict[str, Any],
        success: bool,
    ) -> str:
        result = await self._exec_db_call(
            "record_verification",
            run_id=record.run_id,
            execution_step_id=str(execution_step_id or ""),
            method=str(method or "stage_verification"),
            status="passed" if success else "failed",
            payload=dict(payload or {}),
        )
        return str(result or "")

    async def _record_recovery(
        self,
        *,
        record: RunRecord,
        verification_id: str,
        decision: str,
        payload: dict[str, Any],
    ) -> None:
        await self._exec_db_call(
            "record_recovery",
            run_id=record.run_id,
            verification_id=str(verification_id or ""),
            decision=str(decision or "retry"),
            payload=dict(payload or {}),
        )

    async def _record_checkpoint(
        self,
        *,
        run_id: str,
        state: WorkflowLifecycleState,
        step_id: str,
        payload: dict[str, Any],
    ) -> None:
        await self._exec_db_call(
            "record_checkpoint",
            run_id=str(run_id),
            step_id=str(step_id or ""),
            workflow_state=state.value,
            summary=dict(payload or {}),
        )

    async def _drain_runtime_outbox(self) -> None:
        try:
            runtime_db = self._runtime_db
            if runtime_db is False:
                runtime_db = None
            elif runtime_db is None:
                try:
                    runtime_db = get_runtime_database()
                except Exception:
                    runtime_db = None
            await sync_runtime_outbox_once(runtime_db=runtime_db, limit=100)
        except Exception:
            return

    async def start_workflow(
        self,
        *,
        task_type: str,
        brief: str,
        session_id: str = "desktop",
        title: str = "",
        audience: str = "executive",
        language: str = "tr",
        theme: str = "premium",
        stack: str = "react",
        preferred_formats: Any = None,
        project_template_id: str = "",
        project_name: str = "",
        routing_profile: str = "balanced",
        review_strictness: str = "balanced",
        output_dir: str = "",
        thread_id: str = "",
        workspace_id: str = "",
        actor_id: str = "",
        billing_usage_id: str = "",
        background: bool = True,
    ) -> RunRecord:
        normalized_task_type = self._normalize_task_type(task_type)
        normalized_brief = str(brief or "").strip()
        if not normalized_brief:
            raise ValueError("workflow brief required")

        workflow_id = f"{normalized_task_type.value}_flow"
        workflow_run = self._state_machine.start_run(workflow_id)
        run_id = workflow_run.run_id
        run_title = self._build_title(normalized_task_type, title=title, brief=normalized_brief)
        normalized_routing_profile = self._normalize_routing_profile(routing_profile)
        candidate_chain = self._candidate_chain_for_task(
            task_type=normalized_task_type,
            routing_profile=normalized_routing_profile,
        )

        record = RunRecord(
            run_id=run_id,
            session_id=str(session_id or "desktop"),
            status=WorkflowLifecycleState.RECEIVED.value,
            intent=run_title,
            workflow_state=WorkflowLifecycleState.RECEIVED.value,
            task_type=normalized_task_type.value,
            assigned_agents=self._assigned_agents(normalized_task_type),
            workflow_history=list(workflow_run.history),
            metadata={
                "thread_id": str(thread_id or "").strip(),
                "workspace_id": str(workspace_id or "").strip(),
                "actor_id": str(actor_id or "").strip(),
                "billing_usage_id": str(billing_usage_id or "").strip(),
                "candidate_chain": list(candidate_chain),
                "collaboration_strategy": "parallel_synthesis" if normalized_routing_profile == "quality_first" else "adaptive",
                "collaboration_trace": self._collaboration_trace_for_candidate_chain(
                    task_type=normalized_task_type,
                    routing_profile=normalized_routing_profile,
                    candidate_chain=candidate_chain,
                ),
            },
        )
        await get_run_store().record_run(record)
        _publish_workflow_activity(
            event_type="workflow_start",
            channel=normalized_task_type.value,
            detail=f"{run_title} accepted into {normalized_task_type.value} lane",
            success=True,
        )
        _publish_workflow_tool_event(
            stage="start",
            run_id=run_id,
            step_name="workflow_received",
            success=True,
            payload={"task_type": normalized_task_type.value, "title": run_title},
        )
        if str(thread_id or "").strip():
            _publish_cowork_event(
                "cowork.run.state_changed",
                {
                    "thread_id": str(thread_id or "").strip(),
                    "workspace_id": str(workspace_id or "").strip(),
                    "run_id": run_id,
                    "task_type": normalized_task_type.value,
                    "workflow_state": WorkflowLifecycleState.RECEIVED.value,
                    "status": WorkflowLifecycleState.RECEIVED.value,
                },
            )

        task = asyncio.create_task(
            self._execute_workflow_scoped(
                workflow_run=workflow_run,
                record=record,
                brief=normalized_brief,
                audience=audience,
                language=language,
                theme=theme,
                stack=stack,
                preferred_formats=preferred_formats,
                project_template_id=project_template_id,
                project_name=project_name,
                routing_profile=routing_profile,
                review_strictness=review_strictness,
                output_dir=output_dir,
                billing_usage_id=str(billing_usage_id or "").strip(),
            )
        )

        if background:
            self._tasks[run_id] = task
            task.add_done_callback(lambda _done, rid=run_id: self._tasks.pop(rid, None))
            return record

        await task
        updated = await get_run_store().get_run(run_id)
        return updated or record

    async def _execute_workflow_scoped(
        self,
        *,
        workflow_run: WorkflowState,
        record: RunRecord,
        brief: str,
        audience: str,
        language: str,
        theme: str,
        stack: str,
        preferred_formats: Any,
        project_template_id: str,
        project_name: str,
        routing_profile: str,
        review_strictness: str,
        output_dir: str,
        billing_usage_id: str = "",
    ) -> None:
        workspace_id = str((record.metadata or {}).get("workspace_id") or "").strip()
        session_id = str(record.session_id or "").strip()
        normalized_usage_id = str(billing_usage_id or "").strip()
        if not workspace_id or not normalized_usage_id:
            await self._execute_workflow(
                workflow_run=workflow_run,
                record=record,
                brief=brief,
                audience=audience,
                language=language,
                theme=theme,
                stack=stack,
                preferred_formats=preferred_formats,
                project_template_id=project_template_id,
                project_name=project_name,
                routing_profile=routing_profile,
                review_strictness=review_strictness,
                output_dir=output_dir,
            )
            return
        with activate_billing_usage_scope(
            workspace_id=workspace_id,
            usage_id=normalized_usage_id,
            metric="workflow_runs",
            run_id=str(record.run_id or "").strip(),
            session_id=session_id,
            metadata={
                "actor_id": str((record.metadata or {}).get("actor_id") or "").strip(),
                "thread_id": str((record.metadata or {}).get("thread_id") or "").strip(),
                "task_type": str(record.task_type or "").strip(),
                "routing_profile": str(routing_profile or "").strip().lower(),
                "review_strictness": str(review_strictness or "").strip().lower(),
            },
        ):
            await self._execute_workflow(
                workflow_run=workflow_run,
                record=record,
                brief=brief,
                audience=audience,
                language=language,
                theme=theme,
                stack=stack,
                preferred_formats=preferred_formats,
                project_template_id=project_template_id,
                project_name=project_name,
                routing_profile=routing_profile,
                review_strictness=review_strictness,
                output_dir=output_dir,
            )

    async def cancel_run(self, run_id: str) -> bool:
        normalized = str(run_id or "").strip()
        if not normalized:
            return False
        task = self._tasks.get(normalized)
        if task and not task.done():
            task.cancel()
        cancelled = await get_run_store().cancel_run(normalized)
        if cancelled:
            _publish_workflow_activity(
                event_type="workflow_cancelled",
                channel="workflow",
                detail=f"{normalized} cancelled by operator",
                success=False,
            )
        return cancelled

    async def _execute_workflow(
        self,
        *,
        workflow_run,
        record: RunRecord,
        brief: str,
        audience: str,
        language: str,
        theme: str,
        stack: str,
        preferred_formats: Any,
        project_template_id: str,
        project_name: str,
        routing_profile: str,
        review_strictness: str,
        output_dir: str,
    ) -> None:
        task_type = self._normalize_task_type(record.task_type or WorkflowTaskType.DOCUMENT.value)
        template = FLOW_TEMPLATES[task_type.value]
        per_run_store = RunStore(run_id=record.run_id)
        artifact_root = str(Path(output_dir).expanduser()) if str(output_dir or "").strip() else str(per_run_store.base_dir / "artifacts")
        requested_artifact_targets = self._resolve_artifact_targets(task_type=task_type, preferred_formats=preferred_formats)
        normalized_routing_profile = self._normalize_routing_profile(routing_profile)
        normalized_review_strictness = self._normalize_review_strictness(review_strictness)
        resolved_project_name = str(project_name or record.intent or "").strip()
        candidate_chain = self._candidate_chain_for_task(
            task_type=task_type,
            routing_profile=normalized_routing_profile,
        )
        execution_plan = self._build_execution_plan(
            record=record,
            template=template,
            artifact_targets=requested_artifact_targets,
        )
        pre_execution_inventory = self._snapshot_existing_files(Path(artifact_root).expanduser())
        planned_step_ids = {
            str(step.get("objective") or self._step_name_for_state(WorkflowLifecycleState.PLANNED)).replace(" ", "_"): str(step.get("planned_step_id") or "")
            for step in execution_plan
        }
        execution_step_ids: dict[str, str] = {}

        try:
            per_run_store.write_task(
                {
                    "task_type": task_type.value,
                    "title": record.intent,
                    "brief": brief,
                    "artifact_targets": list(requested_artifact_targets),
                    "project_template_id": str(project_template_id or "").strip(),
                    "project_name": resolved_project_name,
                    "routing_profile": normalized_routing_profile,
                    "review_strictness": normalized_review_strictness,
                    "candidate_chain": list(candidate_chain),
                },
                user_input=brief,
                metadata={"workflow_id": template.task_type.value, "status": "received"},
            )

            scoped_payload: dict[str, Any] = {}

            await self._run_stage(
                workflow_run=workflow_run,
                record=record,
                state=WorkflowLifecycleState.CLASSIFIED,
                step_name="classify_request",
                action=lambda: self._classify_payload(
                    task_type=task_type,
                    brief=brief,
                    title=record.intent,
                    routing_profile=normalized_routing_profile,
                    review_strictness=normalized_review_strictness,
                    candidate_chain=candidate_chain,
                ),
                planned_step_id=planned_step_ids.get("classify_request", ""),
                execution_step_ids=execution_step_ids,
            )
            scoped_payload = await self._run_stage(
                workflow_run=workflow_run,
                record=record,
                state=WorkflowLifecycleState.SCOPED,
                step_name="scope_workflow",
                action=lambda: self._scope_payload(
                    task_type=task_type,
                    title=record.intent,
                    brief=brief,
                    audience=audience,
                    language=language,
                    theme=theme,
                    stack=stack,
                    artifact_root=artifact_root,
                    preferred_formats=requested_artifact_targets,
                    project_template_id=str(project_template_id or "").strip(),
                    project_name=resolved_project_name,
                ),
                planned_step_id=planned_step_ids.get("scope_workflow", ""),
                execution_step_ids=execution_step_ids,
            )
            await self._run_stage(
                workflow_run=workflow_run,
                record=record,
                state=WorkflowLifecycleState.PLANNED,
                step_name="build_plan",
                action=lambda: self._plan_payload(task_type=task_type, preferred_formats=requested_artifact_targets),
                planned_steps=execution_plan,
                planned_step_id=planned_step_ids.get("build_plan", ""),
                execution_step_ids=execution_step_ids,
            )
            await self._run_stage(
                workflow_run=workflow_run,
                record=record,
                state=WorkflowLifecycleState.GATHERING_CONTEXT,
                step_name="gather_context",
                action=lambda: self._context_payload(task_type=task_type, brief=brief, scoped_payload=scoped_payload),
                planned_step_id=planned_step_ids.get("gather_context", ""),
                execution_step_ids=execution_step_ids,
            )

            execution_result = await self._run_stage(
                workflow_run=workflow_run,
                record=record,
                state=WorkflowLifecycleState.EXECUTING,
                step_name="execute_artifact_flow",
                action=lambda: self._execute_artifact_flow(
                    task_type=task_type,
                    title=record.intent,
                    brief=brief,
                    audience=audience,
                    language=language,
                    theme=theme,
                    stack=stack,
                    preferred_formats=requested_artifact_targets,
                    artifact_root=artifact_root,
                ),
                planned_step_id=planned_step_ids.get("execute_artifact_flow", ""),
                execution_step_ids=execution_step_ids,
            )

            review_report = await self._run_stage(
                workflow_run=workflow_run,
                record=record,
                state=WorkflowLifecycleState.REVIEWING,
                step_name="review_artifact_output",
                action=lambda: self._review_execution_result(
                    task_type=task_type,
                    execution_result=execution_result,
                    preferred_formats=requested_artifact_targets,
                    review_strictness=normalized_review_strictness,
                ),
                planned_step_id=planned_step_ids.get("review_artifact_output", ""),
                execution_step_ids=execution_step_ids,
            )
            record.review_report = dict(review_report or {})
            review_verification_id = await self._record_verification(
                record=record,
                execution_step_id=execution_step_ids.get("review_artifact_output", ""),
                method="artifact_review",
                payload=dict(review_report or {}),
                success=str(review_report.get("status") or "") == "passed",
            )
            if str(review_report.get("status") or "") != "passed":
                await self._record_recovery(
                    record=record,
                    verification_id=review_verification_id,
                    decision=str(review_report.get("recommended_action") or "revise"),
                    payload=dict(review_report or {}),
                )
                await self._record_checkpoint(
                    run_id=record.run_id,
                    state=WorkflowLifecycleState.REVIEWING,
                    step_id="review_artifact_output",
                    payload=dict(review_report or {}),
                )
                record.status = WorkflowLifecycleState.FAILED.value
                record.workflow_state = WorkflowLifecycleState.FAILED.value
                record.error = str(review_report.get("recommended_action") or "review failed")
                record.completed_at = time.time()
                try:
                    workflow_run.transition_to(WorkflowState.FAILED, {"reason": "review_failed"})
                except Exception:
                    pass
                await self._persist_record(workflow_run, record)
                per_run_store.write_summary(
                    status="failed",
                    response_text=str(review_report.get("recommended_action") or "review failed"),
                    error=record.error or "",
                    artifacts=list(record.artifacts or []),
                    metadata={"task_type": task_type.value, "workflow_state": WorkflowLifecycleState.FAILED.value},
                )
                return

            if any(stage.state == WorkflowLifecycleState.EXPORTING for stage in template.stages):
                export_payload = await self._run_stage(
                    workflow_run=workflow_run,
                    record=record,
                    state=WorkflowLifecycleState.EXPORTING,
                    step_name="finalize_export_manifest",
                    action=lambda: self._export_payload(task_type=task_type, execution_result=execution_result),
                    planned_step_id=planned_step_ids.get("finalize_export_manifest", ""),
                    execution_step_ids=execution_step_ids,
                )
            else:
                export_payload = self._export_payload(task_type=task_type, execution_result=execution_result)

            record.artifact_path = str(export_payload.get("primary_path") or "")
            record.artifacts = list(export_payload.get("artifacts") or [])
            await self._record_artifact_outputs(
                record=record,
                artifacts=list(record.artifacts or []),
                artifact_root=Path(artifact_root).expanduser(),
                before_inventory=pre_execution_inventory,
            )
            record.completed_at = time.time()
            record.status = WorkflowLifecycleState.COMPLETED.value
            workflow_run.transition_to(WorkflowState.COMPLETED, {"task_type": task_type.value})
            record.workflow_state = WorkflowLifecycleState.COMPLETED.value
            await self._persist_record(workflow_run, record)
            _publish_workflow_activity(
                event_type="workflow_completed",
                channel=task_type.value,
                detail=f"{record.intent} exported and completed",
                success=True,
            )
            _publish_workflow_tool_event(
                stage="end",
                run_id=record.run_id,
                step_name="workflow_completed",
                success=True,
                payload={
                    "task_type": task_type.value,
                    "workflow_state": WorkflowLifecycleState.COMPLETED.value,
                    "artifact_count": len(record.artifacts or []),
                },
            )
            if str(record.metadata.get("thread_id") or "").strip():
                _publish_cowork_event(
                    "cowork.artifact.added",
                    {
                        "thread_id": str(record.metadata.get("thread_id") or "").strip(),
                        "workspace_id": str(record.metadata.get("workspace_id") or "").strip(),
                        "run_id": record.run_id,
                        "artifacts": list(record.artifacts or []),
                        "review_status": str(review_report.get("status") or "passed"),
                    },
                )

            per_run_store.write_evidence(
                steps=list(record.steps),
                artifacts=list(record.artifacts or []),
                metadata={
                    "status": "completed",
                    "task_type": task_type.value,
                    "workflow_state": WorkflowLifecycleState.COMPLETED.value,
                },
            )
            per_run_store.write_summary(
                status="completed",
                response_text=str(execution_result.get("message") or export_payload.get("message") or record.intent),
                artifacts=list(record.artifacts or []),
                metadata={
                    "task_type": task_type.value,
                    "workflow_state": WorkflowLifecycleState.COMPLETED.value,
                    "review_status": str(review_report.get("status") or "passed"),
                },
            )
        except asyncio.CancelledError:
            record.completed_at = time.time()
            record.error = "cancelled_by_operator"
            record.status = "cancelled"
            record.workflow_state = "cancelled"
            await self._persist_record(workflow_run, record)
            _publish_workflow_tool_event(
                stage="cancelled",
                run_id=record.run_id,
                step_name="workflow_cancelled",
                success=False,
                payload={"task_type": task_type.value, "workflow_state": "cancelled"},
            )
            if str(record.metadata.get("thread_id") or "").strip():
                _publish_cowork_event(
                    "cowork.run.state_changed",
                    {
                        "thread_id": str(record.metadata.get("thread_id") or "").strip(),
                        "workspace_id": str(record.metadata.get("workspace_id") or "").strip(),
                        "run_id": record.run_id,
                        "workflow_state": "cancelled",
                        "status": "cancelled",
                    },
                )
            raise
        except Exception as exc:
            logger.error(f"vertical workflow failed for {record.run_id}: {exc}")
            failure_verification_id = await self._record_verification(
                record=record,
                execution_step_id=execution_step_ids.get("workflow_failed", ""),
                method="workflow_exception",
                payload={"error": str(exc), "task_type": task_type.value},
                success=False,
            )
            await self._record_recovery(
                record=record,
                verification_id=failure_verification_id,
                decision="failed",
                payload={"error": str(exc), "task_type": task_type.value},
            )
            await self._record_checkpoint(
                run_id=record.run_id,
                state=WorkflowLifecycleState.FAILED,
                step_id="workflow_failed",
                payload={"error": str(exc), "task_type": task_type.value},
            )
            record.completed_at = time.time()
            record.error = str(exc)
            record.status = WorkflowLifecycleState.FAILED.value
            try:
                workflow_run.transition_to(WorkflowState.FAILED, {"error": str(exc)})
                record.workflow_state = WorkflowLifecycleState.FAILED.value
            except Exception:
                record.workflow_state = WorkflowLifecycleState.FAILED.value
            await self._persist_record(workflow_run, record)
            _publish_workflow_activity(
                event_type="workflow_failed",
                channel=task_type.value,
                detail=f"{record.intent} failed: {exc}",
                success=False,
            )
            _publish_workflow_tool_event(
                stage="error",
                run_id=record.run_id,
                step_name="workflow_failed",
                success=False,
                payload={
                    "task_type": task_type.value,
                    "workflow_state": WorkflowLifecycleState.FAILED.value,
                    "error": str(exc),
                },
            )
            if str(record.metadata.get("thread_id") or "").strip():
                _publish_cowork_event(
                    "cowork.run.state_changed",
                    {
                        "thread_id": str(record.metadata.get("thread_id") or "").strip(),
                        "workspace_id": str(record.metadata.get("workspace_id") or "").strip(),
                        "run_id": record.run_id,
                        "workflow_state": WorkflowLifecycleState.FAILED.value,
                        "status": WorkflowLifecycleState.FAILED.value,
                        "error": str(exc),
                    },
                )
            per_run_store.write_summary(
                status="failed",
                response_text=str(exc),
                error=str(exc),
                artifacts=list(record.artifacts or []),
                metadata={
                    "task_type": task_type.value,
                    "workflow_state": WorkflowLifecycleState.FAILED.value,
                },
            )

    async def _run_stage(
        self,
        *,
        workflow_run,
        record: RunRecord,
        state: WorkflowLifecycleState,
        step_name: str,
        action: Callable[[], Coroutine[Any, Any, dict[str, Any]] | dict[str, Any]],
        planned_step_id: str = "",
        planned_steps: list[dict[str, Any]] | None = None,
        execution_step_ids: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        workflow_run.transition_to(WorkflowState(state.value), {"task_type": record.task_type or ""})
        record.workflow_state = state.value
        record.status = self._status_for_state(state)
        _publish_workflow_activity(
            event_type="workflow_stage",
            channel=record.task_type or "workflow",
            detail=f"{record.intent} → {state.value.replace('_', ' ')}",
            success=True,
        )
        _publish_workflow_tool_event(
            stage="start",
            run_id=record.run_id,
            step_name=step_name,
            payload={"workflow_state": state.value, "task_type": record.task_type or ""},
        )
        if str(record.metadata.get("thread_id") or "").strip():
            _publish_cowork_event(
                "cowork.run.state_changed",
                {
                    "thread_id": str(record.metadata.get("thread_id") or "").strip(),
                    "workspace_id": str(record.metadata.get("workspace_id") or "").strip(),
                    "run_id": record.run_id,
                    "step_name": step_name,
                    "workflow_state": state.value,
                    "status": record.status,
                },
            )
        step = {
            "step_id": f"{record.run_id}_{step_name}",
            "name": step_name,
            "status": "running",
            "started_at": time.time(),
            "dependencies": [],
            "result": None,
            "error": None,
        }
        record.steps.append(step)
        await self._persist_record(workflow_run, record)
        execution_step_id = await self._record_execution_step_start(
            record=record,
            state=state,
            planned_step_id=planned_step_id,
            step_name=step_name,
            payload={"workflow_state": state.value, "task_type": record.task_type or ""},
        )
        if execution_step_ids is not None and execution_step_id:
            execution_step_ids[step_name] = execution_step_id
        if step_name == "build_plan" and planned_steps:
            await self._record_plan(record=record, steps=planned_steps)

        try:
            result = action()
            if asyncio.iscoroutine(result):
                result = await result
            payload = dict(result or {})
            step["status"] = "completed"
            step["completed_at"] = time.time()
            step["result"] = payload
            await self._persist_record(workflow_run, record)
            await self._record_execution_step_complete(
                execution_step_id=execution_step_id,
                payload=payload,
                success=True,
            )
            await self._record_checkpoint(
                run_id=record.run_id,
                state=state,
                step_id=step_name,
                payload=payload,
            )
            _publish_workflow_tool_event(
                stage="end",
                run_id=record.run_id,
                step_name=step_name,
                success=True,
                payload={"workflow_state": state.value, "result_keys": sorted(payload.keys())[:8]},
            )
            if str(record.metadata.get("thread_id") or "").strip():
                event_type = "cowork.review.updated" if state == WorkflowLifecycleState.REVIEWING else "cowork.delta"
                _publish_cowork_event(
                    event_type,
                    {
                        "thread_id": str(record.metadata.get("thread_id") or "").strip(),
                        "workspace_id": str(record.metadata.get("workspace_id") or "").strip(),
                        "run_id": record.run_id,
                        "step_name": step_name,
                        "workflow_state": state.value,
                        "status": "completed",
                        "payload": payload,
                    },
                )
            return payload
        except asyncio.CancelledError:
            step["status"] = "cancelled"
            step["completed_at"] = time.time()
            step["error"] = "cancelled_by_operator"
            record.error = "cancelled_by_operator"
            record.status = "cancelled"
            record.workflow_state = "cancelled"
            await self._persist_record(workflow_run, record)
            await self._record_execution_step_complete(
                execution_step_id=execution_step_id,
                payload={"error": "cancelled_by_operator"},
                success=False,
            )
            raise
        except Exception as exc:
            step["status"] = "failed"
            step["completed_at"] = time.time()
            step["error"] = str(exc)
            record.error = str(exc)
            record.status = WorkflowLifecycleState.FAILED.value
            try:
                workflow_run.transition_to(WorkflowState.FAILED, {"error": str(exc), "stage": state.value})
                record.workflow_state = WorkflowLifecycleState.FAILED.value
            except Exception:
                record.workflow_state = WorkflowLifecycleState.FAILED.value
            await self._persist_record(workflow_run, record)
            await self._record_execution_step_complete(
                execution_step_id=execution_step_id,
                payload={"error": str(exc)},
                success=False,
            )
            verification_id = await self._record_verification(
                record=record,
                execution_step_id=execution_step_id,
                method="stage_execution",
                payload={"error": str(exc), "stage": state.value},
                success=False,
            )
            await self._record_recovery(
                record=record,
                verification_id=verification_id,
                decision="retry",
                payload={"error": str(exc), "stage": state.value},
            )
            await self._record_checkpoint(
                run_id=record.run_id,
                state=WorkflowLifecycleState.FAILED,
                step_id=step_name,
                payload={"error": str(exc), "stage": state.value},
            )
            _publish_workflow_activity(
                event_type="workflow_stage_failed",
                channel=record.task_type or "workflow",
                detail=f"{record.intent} → {step_name} failed",
                success=False,
            )
            _publish_workflow_tool_event(
                stage="error",
                run_id=record.run_id,
                step_name=step_name,
                success=False,
                payload={"workflow_state": state.value, "error": str(exc)},
            )
            if str(record.metadata.get("thread_id") or "").strip():
                _publish_cowork_event(
                    "cowork.run.state_changed",
                    {
                        "thread_id": str(record.metadata.get("thread_id") or "").strip(),
                        "workspace_id": str(record.metadata.get("workspace_id") or "").strip(),
                        "run_id": record.run_id,
                        "step_name": step_name,
                        "workflow_state": WorkflowLifecycleState.FAILED.value,
                        "status": "failed",
                        "error": str(exc),
                    },
                )
            raise

    async def _persist_record(self, workflow_run, record: RunRecord) -> None:
        persisted = replace(record, workflow_history=list(workflow_run.history))
        await get_run_store().record_run(persisted)
        record.workflow_history = list(persisted.workflow_history)
        await self._drain_runtime_outbox()

    @staticmethod
    def _normalize_task_type(task_type: str) -> WorkflowTaskType:
        raw = str(task_type or "").strip().lower()
        try:
            return WorkflowTaskType(raw)
        except Exception as exc:
            raise ValueError(f"unsupported workflow task type: {task_type}") from exc

    @staticmethod
    def _build_title(task_type: WorkflowTaskType, *, title: str, brief: str) -> str:
        explicit = str(title or "").strip()
        if explicit:
            return explicit
        brief_text = str(brief or "").strip()
        excerpt = " ".join(brief_text.split())[:72].strip()
        if excerpt:
            return excerpt
        return f"{task_type.value.title()} workflow"

    @staticmethod
    def _assigned_agents(task_type: WorkflowTaskType) -> List[str]:
        if task_type == WorkflowTaskType.WEBSITE:
            return ["executive", "planner", "code", "review", "security"]
        return ["executive", "planner", "artifact", "review", "security"]

    @staticmethod
    def _collaboration_trace_for_candidate_chain(
        *,
        task_type: WorkflowTaskType,
        routing_profile: str,
        candidate_chain: list[str],
    ) -> list[dict[str, Any]]:
        execution_style = "parallel_synthesis" if str(routing_profile or "").strip().lower() == "quality_first" else "adaptive"
        default_lenses = ["planner", "builder", "critic", "verifier"] if task_type == WorkflowTaskType.WEBSITE else ["planner", "writer", "critic", "verifier"]
        trace: list[dict[str, Any]] = []
        for index, raw in enumerate(list(candidate_chain or [])[:4]):
            token = str(raw or "").strip()
            if not token:
                continue
            provider, _, model = token.partition(":")
            trace.append(
                {
                    "id": f"workflow_model_{index + 1}",
                    "provider": provider.strip().lower(),
                    "model": model.strip(),
                    "lens": default_lenses[index] if index < len(default_lenses) else "support",
                    "status": "planned",
                    "strategy": execution_style,
                    "source": "workflow_candidate_chain",
                    "order": index + 1,
                }
            )
        return trace

    @staticmethod
    def _status_for_state(state: WorkflowLifecycleState) -> str:
        return state.value

    @staticmethod
    def _resolve_artifact_targets(*, task_type: WorkflowTaskType, preferred_formats: Any) -> list[str]:
        if task_type == WorkflowTaskType.WEBSITE:
            return ["react_scaffold"]

        allowed = {"docx", "pdf", "md"} if task_type == WorkflowTaskType.DOCUMENT else {"pptx", "pdf", "md"}
        normalized: list[str] = []

        if isinstance(preferred_formats, str) and preferred_formats.strip():
            preferred_formats = [preferred_formats]

        if isinstance(preferred_formats, (list, tuple, set)):
            for item in preferred_formats:
                token = str(item or "").strip().lower()
                if token == "word":
                    token = "docx"
                elif token in {"presentation", "deck", "slide", "slides"}:
                    token = "pptx"
                if token in allowed and token not in normalized:
                    normalized.append(token)

        return normalized or list(FLOW_TEMPLATES[task_type.value].artifact_targets)

    @staticmethod
    def _normalize_routing_profile(routing_profile: str) -> str:
        raw = str(routing_profile or "").strip().lower()
        if raw in {"local-first", "local"}:
            raw = "local_first"
        elif raw in {"quality-first", "quality"}:
            raw = "quality_first"
        return raw if raw in {"balanced", "local_first", "quality_first"} else "balanced"

    @staticmethod
    def _normalize_review_strictness(review_strictness: str) -> str:
        raw = str(review_strictness or "").strip().lower()
        return raw if raw in {"balanced", "strict"} else "balanced"

    @staticmethod
    def _specialist_key_for_task(task_type: WorkflowTaskType) -> str:
        if task_type == WorkflowTaskType.WEBSITE:
            return "code_agent"
        return "document_agent"

    @classmethod
    def _candidate_chain_for_task(cls, *, task_type: WorkflowTaskType, routing_profile: str) -> list[str]:
        normalized_routing_profile = cls._normalize_routing_profile(routing_profile)
        prefer_local = normalized_routing_profile != "quality_first"
        allow_cloud_fallback = normalized_routing_profile != "local_first"
        try:
            from core.elyan_runtime import get_elyan_runtime
            from core.unified_model_gateway import UnifiedModelRequest

            gateway = getattr(get_elyan_runtime(), "model_gateway", None)
            if gateway is None:
                raise RuntimeError("model gateway unavailable")
            candidates = gateway.build_candidates(
                UnifiedModelRequest(
                    specialist_key=cls._specialist_key_for_task(task_type),
                    role="planning",
                    prefer_local=prefer_local,
                    allow_cloud_fallback=allow_cloud_fallback,
                    cloud_allowed=allow_cloud_fallback,
                    contains_sensitive_data=False,
                    max_models=4,
                )
            )
            chain = [f"{candidate.provider}:{candidate.model}" for candidate in candidates if candidate.provider and candidate.model]
            if chain:
                return chain
        except Exception:
            pass

        if normalized_routing_profile == "local_first":
            return ["ollama:qwen2.5-vl"]
        if task_type == WorkflowTaskType.WEBSITE:
            return ["ollama:qwen2.5-vl", "openai:gpt-4o"]
        if normalized_routing_profile == "quality_first":
            return ["openai:gpt-4o", "anthropic:claude", "ollama:qwen2.5-vl"]
        return ["ollama:qwen2.5-vl", "openai:gpt-4o", "groq:llama-3.3-70b"]

    @staticmethod
    async def _classify_payload(
        *,
        task_type: WorkflowTaskType,
        brief: str,
        title: str,
        routing_profile: str,
        review_strictness: str,
        candidate_chain: list[str],
    ) -> dict[str, Any]:
        return {
            "task_type": task_type.value,
            "title": title,
            "brief_excerpt": " ".join(str(brief or "").split())[:160],
            "risk_level": "low" if task_type != WorkflowTaskType.WEBSITE else "medium",
            "primary_output": "react_scaffold" if task_type == WorkflowTaskType.WEBSITE else ("pptx" if task_type == WorkflowTaskType.PRESENTATION else "docx"),
            "routing_profile": routing_profile,
            "review_strictness": review_strictness,
            "candidate_chain": list(candidate_chain or []),
        }

    @staticmethod
    async def _scope_payload(
        *,
        task_type: WorkflowTaskType,
        title: str,
        brief: str,
        audience: str,
        language: str,
        theme: str,
        stack: str,
        artifact_root: str,
        preferred_formats: list[str],
        project_template_id: str,
        project_name: str,
    ) -> dict[str, Any]:
        return {
            "task_type": task_type.value,
            "title": title,
            "audience": audience,
            "language": language,
            "theme": theme,
            "stack": stack,
            "artifact_root": artifact_root,
            "brief_chars": len(str(brief or "")),
            "preferred_formats": list(preferred_formats or []),
            "objective": VerticalWorkflowRunner._objective_for_task(task_type=task_type, title=title),
            "project_template_id": project_template_id,
            "project_name": project_name,
        }

    @staticmethod
    async def _plan_payload(*, task_type: WorkflowTaskType, preferred_formats: list[str]) -> dict[str, Any]:
        template = FLOW_TEMPLATES[task_type.value]
        step_map = {
            WorkflowTaskType.DOCUMENT: [
                "intake",
                "outline",
                "section_draft",
                "review",
                "export",
            ],
            WorkflowTaskType.PRESENTATION: [
                "audience_analysis",
                "slide_outline",
                "visual_brief",
                "slide_content",
                "review",
                "export",
            ],
            WorkflowTaskType.WEBSITE: [
                "business_analysis",
                "sitemap",
                "section_copy",
                "design_spec",
                "component_tree",
                "scaffold",
                "review",
            ],
        }
        return {
            "task_type": task_type.value,
            "artifact_targets": list(preferred_formats or template.artifact_targets),
            "stages": [stage.state.value for stage in template.stages],
            "owners": [stage.owner.value for stage in template.stages],
            "deliverables": step_map.get(task_type, []),
        }

    @staticmethod
    async def _context_payload(*, task_type: WorkflowTaskType, brief: str, scoped_payload: dict[str, Any]) -> dict[str, Any]:
        keywords = [token.strip(".,:;!?").lower() for token in str(brief or "").split() if len(token.strip(".,:;!?")) > 3]
        return {
            "task_type": task_type.value,
            "keyword_preview": keywords[:8],
            "artifact_root": scoped_payload.get("artifact_root", ""),
            "memory_scope": ["session", "project", "execution", "security"],
        }

    async def _execute_artifact_flow(
        self,
        *,
        task_type: WorkflowTaskType,
        title: str,
        brief: str,
        audience: str,
        language: str,
        theme: str,
        stack: str,
        preferred_formats: list[str],
        artifact_root: str,
    ) -> dict[str, Any]:
        if task_type == WorkflowTaskType.WEBSITE:
            result = await create_web_project_scaffold(
                project_name=title,
                stack=stack or "react",
                theme=theme or "premium",
                output_dir=artifact_root,
                brief=brief,
            )
        elif task_type == WorkflowTaskType.PRESENTATION:
            presentation_formats = list(preferred_formats or ["pptx", "pdf", "md"])
            if "pptx" in presentation_formats and "pdf" not in presentation_formats and "md" not in presentation_formats:
                presentation_formats.append("pdf")
            result = await generate_document_pack(
                topic=title,
                brief=brief,
                audience=audience,
                language=language,
                output_dir=artifact_root,
                preferred_formats=presentation_formats,
            )
            result = self._ensure_presentation_export(result=result, title=title, brief=brief)
        else:
            result = await generate_document_pack(
                topic=title,
                brief=brief,
                audience=audience,
                language=language,
                output_dir=artifact_root,
                preferred_formats=preferred_formats or ["docx", "pdf", "md"],
            )

        if not isinstance(result, dict) or not result.get("success"):
            raise RuntimeError(str((result or {}).get("error") or "artifact generation failed"))
        return dict(result)

    def _ensure_presentation_export(self, *, result: dict[str, Any], title: str, brief: str) -> dict[str, Any]:
        outputs = [str(item).strip() for item in (result.get("outputs") or []) if str(item).strip()]
        if any(item.lower().endswith(".pptx") for item in outputs):
            return result

        raw_pack_dir = str(result.get("pack_dir") or "").strip()
        if not raw_pack_dir:
            return result
        pack_dir = Path(raw_pack_dir).expanduser()
        pack_dir.mkdir(parents=True, exist_ok=True)
        pptx_path = pack_dir / "DOCUMENT.pptx"
        self._write_minimal_pptx(pptx_path, title=title, brief=brief)
        outputs.insert(0, str(pptx_path))
        updated = dict(result)
        updated["path"] = str(pptx_path)
        updated["outputs"] = outputs
        warnings = [str(item) for item in (updated.get("warnings") or []) if str(item).strip()]
        warnings.append("pptx fallback renderer used")
        updated["warnings"] = warnings
        return updated

    @staticmethod
    def _write_minimal_pptx(path: Path, *, title: str, brief: str) -> None:
        bullet_lines = [segment.strip() for segment in str(brief or "").replace("\n", " ").split(".") if segment.strip()]
        bullet_lines = bullet_lines[:4] or [str(brief or title or "Elyan workflow output").strip()]
        bullet_xml = "".join(
            f"<a:p><a:r><a:rPr lang=\"tr-TR\" dirty=\"0\" smtClean=\"0\"/><a:t>{VerticalWorkflowRunner._xml_escape(line)}</a:t></a:r></a:p>"
            for line in bullet_lines
        )

        files = {
            "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
""",
            "_rels/.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
""",
            "docProps/core.xml": f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{VerticalWorkflowRunner._xml_escape(title)}</dc:title>
  <dc:creator>Elyan</dc:creator>
  <cp:lastModifiedBy>Elyan</cp:lastModifiedBy>
</cp:coreProperties>
""",
            "docProps/app.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Elyan</Application>
  <PresentationFormat>Custom</PresentationFormat>
  <Slides>1</Slides>
  <Notes>0</Notes>
  <HiddenSlides>0</HiddenSlides>
  <MMClips>0</MMClips>
</Properties>
""",
            "ppt/presentation.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>
  <p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst>
  <p:sldSz cx="12192000" cy="6858000"/>
  <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>
""",
            "ppt/_rels/presentation.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/>
</Relationships>
""",
            "ppt/slides/slide1.xml": f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr/>
      <p:sp>
        <p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr/>
        <p:txBody>
          <a:bodyPr/>
          <a:lstStyle/>
          <a:p><a:r><a:rPr lang="tr-TR" sz="2400" b="1"/><a:t>{VerticalWorkflowRunner._xml_escape(title)}</a:t></a:r></a:p>
        </p:txBody>
      </p:sp>
      <p:sp>
        <p:nvSpPr><p:cNvPr id="3" name="Content"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr/>
        <p:txBody>
          <a:bodyPr wrap="square"/>
          <a:lstStyle/>
          {bullet_xml}
        </p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>
""",
            "ppt/slides/_rels/slide1.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>
""",
            "ppt/slideLayouts/slideLayout1.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="titleAndContent" preserve="1">
  <p:cSld name="Title and Content"><p:spTree/></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>
""",
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>
""",
            "ppt/slideMasters/slideMaster1.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld name="Master"><p:spTree/></p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
  <p:txStyles/>
</p:sldMaster>
""",
            "ppt/slideMasters/_rels/slideMaster1.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>
""",
            "ppt/theme/theme1.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Elyan Theme">
  <a:themeElements>
    <a:clrScheme name="Elyan">
      <a:dk1><a:srgbClr val="111827"/></a:dk1>
      <a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="1F2937"/></a:dk2>
      <a:lt2><a:srgbClr val="F8FAFC"/></a:lt2>
      <a:accent1><a:srgbClr val="5B7CFF"/></a:accent1>
      <a:accent2><a:srgbClr val="7D98FF"/></a:accent2>
      <a:accent3><a:srgbClr val="0F172A"/></a:accent3>
      <a:accent4><a:srgbClr val="94A3B8"/></a:accent4>
      <a:accent5><a:srgbClr val="CBD5E1"/></a:accent5>
      <a:accent6><a:srgbClr val="E2E8F0"/></a:accent6>
      <a:hlink><a:srgbClr val="2563EB"/></a:hlink>
      <a:folHlink><a:srgbClr val="7C3AED"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="Elyan">
      <a:majorFont><a:latin typeface="Aptos"/></a:majorFont>
      <a:minorFont><a:latin typeface="Aptos"/></a:minorFont>
    </a:fontScheme>
    <a:fmtScheme name="Elyan"><a:fillStyleLst/><a:lnStyleLst/><a:effectStyleLst/><a:bgFillStyleLst/></a:fmtScheme>
  </a:themeElements>
</a:theme>
""",
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, content)

    @staticmethod
    def _xml_escape(value: str) -> str:
        return (
            str(value or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    async def _review_execution_result(
        self,
        *,
        task_type: WorkflowTaskType,
        execution_result: dict[str, Any],
        preferred_formats: list[str],
        review_strictness: str,
    ) -> dict[str, Any]:
        artifacts = self._artifact_rows(task_type=task_type, execution_result=execution_result)
        issues: list[dict[str, str]] = []
        checklist: list[dict[str, str]] = []
        normalized_review_strictness = self._normalize_review_strictness(review_strictness)
        if not artifacts:
            issues.append({"severity": "high", "message": "No artifact path was produced."})
            checklist.append({"label": "artifact_created", "status": "failed"})
        else:
            checklist.append({"label": "artifact_created", "status": "passed"})

        produced_suffixes = {Path(str(item.get("path") or "")).suffix.lower().lstrip(".") for item in artifacts if str(item.get("path") or "").strip()}
        requested_suffixes = {
            str(item or "").strip().lower()
            for item in list(preferred_formats or [])
            if str(item or "").strip().lower() not in {"", "react_scaffold"}
        }
        missing_requested = sorted(item for item in requested_suffixes if item not in produced_suffixes)
        if missing_requested:
            issues.append({"severity": "high", "message": f"Requested outputs missing: {', '.join(missing_requested)}"})
            checklist.append({"label": "requested_outputs", "status": "failed"})
        elif requested_suffixes:
            checklist.append({"label": "requested_outputs", "status": "passed"})

        if task_type == WorkflowTaskType.PRESENTATION and not any(str(item.get("path") or "").lower().endswith(".pptx") for item in artifacts):
            issues.append({"severity": "high", "message": "Presentation flow did not produce a PPTX export."})
            checklist.append({"label": "pptx_export", "status": "failed"})
        elif task_type == WorkflowTaskType.PRESENTATION:
            checklist.append({"label": "pptx_export", "status": "passed"})

        if task_type == WorkflowTaskType.DOCUMENT and not any(
            str(item.get("path") or "").lower().endswith((".docx", ".pdf", ".md")) for item in artifacts
        ):
            issues.append({"severity": "high", "message": "Document flow did not produce an exportable artifact."})
            checklist.append({"label": "document_export", "status": "failed"})
        elif task_type == WorkflowTaskType.DOCUMENT:
            checklist.append({"label": "document_export", "status": "passed"})

        if task_type == WorkflowTaskType.WEBSITE:
            root = Path(str(execution_result.get("project_dir") or execution_result.get("path") or "")).expanduser()
            required_files = [root / "package.json", root / "README.md"]
            missing = [item.name for item in required_files if not item.exists()]
            if missing:
                issues.append({"severity": "high", "message": f"Website scaffold missing required files: {', '.join(missing)}"})
                checklist.append({"label": "scaffold_contract", "status": "failed"})
            else:
                checklist.append({"label": "scaffold_contract", "status": "passed"})
            if normalized_review_strictness == "strict":
                strict_files = [root / "src" / "App.tsx", root / "src" / "main.tsx"]
                if all(item.exists() for item in strict_files):
                    checklist.append({"label": "strict_source_contract", "status": "passed"})
                else:
                    checklist.append({"label": "strict_source_contract", "status": "warning"})

        if normalized_review_strictness == "strict":
            checklist.append({"label": "review_profile", "status": "passed"})
            warnings = [str(item).strip() for item in list(execution_result.get("warnings") or []) if str(item).strip()]
            if warnings:
                checklist.append({"label": "strict_warning_budget", "status": "warning"})
        else:
            checklist.append({"label": "review_profile", "status": "passed"})

        warning_penalty = 0.05 * len([item for item in checklist if item.get("status") == "warning"])
        score = max(
            0.0,
            1.0
            - (0.35 * len([item for item in issues if item.get("severity") == "high"]))
            - (0.15 * len([item for item in issues if item.get("severity") != "high"]))
            - warning_penalty,
        )
        return {
            "status": "passed" if not issues else "failed",
            "issues": issues,
            "recommended_action": "" if not issues else "revise_artifact_output",
            "score": round(score, 2),
            "checklist": checklist,
            "strictness": normalized_review_strictness,
        }

    def _export_payload(self, *, task_type: WorkflowTaskType, execution_result: dict[str, Any]) -> dict[str, Any]:
        artifacts = self._artifact_rows(task_type=task_type, execution_result=execution_result)
        primary_path = ""
        for item in artifacts:
            path = str(item.get("path") or "").strip()
            if path:
                primary_path = path
                break
        return {
            "task_type": task_type.value,
            "primary_path": primary_path,
            "artifacts": artifacts,
            "message": str(execution_result.get("message") or execution_result.get("preview") or primary_path or task_type.value),
        }

    def _artifact_rows(self, *, task_type: WorkflowTaskType, execution_result: dict[str, Any]) -> List[dict[str, Any]]:
        outputs: list[str] = []
        if isinstance(execution_result.get("outputs"), list):
            outputs.extend(str(item).strip() for item in execution_result.get("outputs") if str(item).strip())
        primary = str(
            execution_result.get("path")
            or execution_result.get("project_dir")
            or execution_result.get("pack_dir")
            or ""
        ).strip()
        if primary and primary not in outputs:
            outputs.insert(0, primary)

        rows: list[dict[str, Any]] = []
        for item in outputs:
            path = Path(item).expanduser()
            rows.append(
                {
                    "path": str(path),
                    "label": path.name,
                    "kind": task_type.value,
                    "exists": path.exists(),
                }
            )
        return rows

    async def _record_artifact_outputs(
        self,
        *,
        record: RunRecord,
        artifacts: list[dict[str, Any]],
        artifact_root: Path,
        before_inventory: dict[str, str],
    ) -> None:
        seen_paths: set[str] = set()
        for artifact in list(artifacts or []):
            raw_path = str(artifact.get("path") or "").strip()
            if not raw_path:
                continue
            path = Path(raw_path).expanduser()
            if not path.exists():
                continue
            normalized_path = str(path)
            if normalized_path in seen_paths:
                continue
            seen_paths.add(normalized_path)
            artifact_id = str(artifact.get("artifact_id") or artifact.get("label") or path.name or normalized_path)
            artifact_kind = str(artifact.get("kind") or record.task_type or "artifact")
            if path.is_file():
                await self._record_file_artifact(
                    record=record,
                    artifact_id=artifact_id,
                    path=path,
                    before_inventory=before_inventory,
                    artifact_kind=artifact_kind,
                )
            elif path.is_dir():
                await self._record_directory_artifact(
                    record=record,
                    artifact_id=artifact_id,
                    path=path,
                    before_inventory=before_inventory,
                    artifact_kind=artifact_kind,
                )
        if not artifacts and artifact_root.exists():
            await self._record_directory_artifact(
                record=record,
                artifact_id=f"{record.run_id}_artifact_root",
                path=artifact_root,
                before_inventory=before_inventory,
                artifact_kind=str(record.task_type or "artifact"),
            )

    async def _record_file_artifact(
        self,
        *,
        record: RunRecord,
        artifact_id: str,
        path: Path,
        before_inventory: dict[str, str],
        artifact_kind: str,
    ) -> None:
        normalized_path = str(path)
        before_hash = str(before_inventory.get(normalized_path) or "")
        after_hash = self._hash_path(path)
        change_type = "created" if not before_hash else "updated" if before_hash != after_hash else "unchanged"
        summary = {
            "path": normalized_path,
            "label": path.name,
            "kind": artifact_kind,
            "change_type": change_type,
            "size_bytes": int(path.stat().st_size) if path.exists() else 0,
        }
        await self._exec_db_call(
            "record_artifact_diff",
            run_id=record.run_id,
            artifact_id=str(artifact_id or path.name),
            before_hash=before_hash,
            after_hash=after_hash,
            summary=summary,
        )
        if change_type != "unchanged":
            await self._exec_db_call(
                "record_file_mutation",
                run_id=record.run_id,
                path=normalized_path,
                before_hash=before_hash,
                after_hash=after_hash,
                rollback_available=bool(before_hash),
                summary=summary,
            )

    async def _record_directory_artifact(
        self,
        *,
        record: RunRecord,
        artifact_id: str,
        path: Path,
        before_inventory: dict[str, str],
        artifact_kind: str,
    ) -> None:
        current_files = self._snapshot_existing_files(path)
        path_prefix = f"{path}{os.sep}"
        before_subset = {
            key: value
            for key, value in before_inventory.items()
            if key == str(path) or key.startswith(path_prefix)
        }
        dir_before_hash = self._hash_inventory(before_subset)
        dir_after_hash = self._hash_inventory(current_files)
        created_count = 0
        updated_count = 0
        unchanged_count = 0
        for file_path, after_hash in current_files.items():
            before_hash = str(before_inventory.get(file_path) or "")
            change_type = "created" if not before_hash else "updated" if before_hash != after_hash else "unchanged"
            if change_type == "created":
                created_count += 1
            elif change_type == "updated":
                updated_count += 1
            else:
                unchanged_count += 1
            if change_type == "unchanged":
                continue
            mutation_path = Path(file_path)
            await self._exec_db_call(
                "record_file_mutation",
                run_id=record.run_id,
                path=file_path,
                before_hash=before_hash,
                after_hash=after_hash,
                rollback_available=bool(before_hash),
                summary={
                    "path": file_path,
                    "label": mutation_path.name,
                    "kind": artifact_kind,
                    "change_type": change_type,
                    "parent_artifact_id": artifact_id,
                    "size_bytes": int(mutation_path.stat().st_size) if mutation_path.exists() else 0,
                },
            )
        await self._exec_db_call(
            "record_artifact_diff",
            run_id=record.run_id,
            artifact_id=str(artifact_id or path.name),
            before_hash=dir_before_hash,
            after_hash=dir_after_hash,
            summary={
                "path": str(path),
                "label": path.name,
                "kind": artifact_kind,
                "change_type": "created" if not dir_before_hash else "updated" if dir_before_hash != dir_after_hash else "unchanged",
                "file_count": len(current_files),
                "created_count": created_count,
                "updated_count": updated_count,
                "unchanged_count": unchanged_count,
            },
        )

    @staticmethod
    def _snapshot_existing_files(root: Path) -> dict[str, str]:
        path = Path(root).expanduser()
        if not path.exists():
            return {}
        if path.is_file():
            digest = VerticalWorkflowRunner._hash_path(path)
            return {str(path): digest} if digest else {}
        files: dict[str, str] = {}
        for item in sorted(path.rglob("*")):
            if not item.is_file():
                continue
            digest = VerticalWorkflowRunner._hash_path(item)
            if digest:
                files[str(item)] = digest
        return files

    @staticmethod
    def _hash_path(path: Path) -> str:
        normalized = Path(path).expanduser()
        if not normalized.exists():
            return ""
        if normalized.is_dir():
            return VerticalWorkflowRunner._hash_inventory(VerticalWorkflowRunner._snapshot_existing_files(normalized))
        digest = hashlib.sha256()
        with normalized.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _hash_inventory(items: dict[str, str]) -> str:
        if not items:
            return ""
        digest = hashlib.sha256()
        for key in sorted(items.keys()):
            digest.update(key.encode("utf-8"))
            digest.update(b":")
            digest.update(str(items[key] or "").encode("utf-8"))
            digest.update(b"\n")
        return digest.hexdigest()

    @staticmethod
    def _objective_for_task(*, task_type: WorkflowTaskType, title: str) -> str:
        if task_type == WorkflowTaskType.PRESENTATION:
            return f"Build an export-ready presentation for {title}."
        if task_type == WorkflowTaskType.WEBSITE:
            return f"Generate a runnable React scaffold for {title}."
        return f"Produce a structured document pack for {title}."


_vertical_workflow_runner: Optional[VerticalWorkflowRunner] = None


def get_vertical_workflow_runner() -> VerticalWorkflowRunner:
    global _vertical_workflow_runner
    if _vertical_workflow_runner is None:
        _vertical_workflow_runner = VerticalWorkflowRunner()
    return _vertical_workflow_runner


__all__ = ["VerticalWorkflowRunner", "get_vertical_workflow_runner"]
