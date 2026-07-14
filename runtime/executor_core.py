from __future__ import annotations

import datetime as dt
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from runtime import state_store
from runtime.agent_planning import build_agent_plan
from runtime.capability_registry import capability_metadata, capability_metadata_summary, capability_readiness
from runtime.capability_validation import attach_step_evidence, precondition_error, readback_evidence
from runtime.execution_scheduler import (
    MAX_PARALLEL_READS,
    SchedulerPlanError,
    parallel_read_batch,
    run_parallel,
    schedule_steps,
)

try:
    from langgraph.graph import END, START, StateGraph
except Exception:  # pragma: no cover - optional dependency
    END = START = None
    StateGraph = None

from runtime import litellm_adapter

PLANNER_VERSION = "runtime_v2"


def _utc_now_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _safe_text(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


# ── Adım çıktısı şablonları + forEach ────────────────────────────────────────
# Bir adımın args'ı önceki adımların YAPILANDIRILMIŞ çıktısına referans
# verebilir: {{steps.<id>.result.items[0].href}}. Bir adım "forEach" taşıyorsa
# çözülen liste üzerinde fan-out yapılır; kopyalarda {{item...}} ve {{index}}
# eleman değerleriyle doldurulur. Bu, "5 linki topla, HER BİRİ için indir"
# görevlerinin plan diliyle ifade edilebilmesini sağlar.

_TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z_][\w\.\[\]]*)\s*\}\}")
_WHOLE_TEMPLATE_RE = re.compile(r"^\{\{\s*([a-zA-Z_][\w\.\[\]]*)\s*\}\}$")
_MAX_FOREACH_ITEMS = 20
_TEMPLATE_MISSING = object()


class TemplateResolutionError(ValueError):
    def __init__(self, expression: str) -> None:
        super().__init__(expression)
        self.expression = expression


def _lookup_template_path(root: Any, path: str) -> Any:
    current = root
    for part in re.sub(r"\[(\d+)\]", r".\1", path).split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part, _TEMPLATE_MISSING)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else _TEMPLATE_MISSING
        else:
            return _TEMPLATE_MISSING
        if current is _TEMPLATE_MISSING:
            return _TEMPLATE_MISSING
    return current


def _resolve_templates(value: Any, namespace: dict[str, Any]) -> Any:
    """Args ağacındaki {{...}} şablonlarını çözer. Değerin tamamı tek şablonsa
    tipi korunur (liste/sözlük) — forEach listeleri böyle taşınır."""
    if isinstance(value, dict):
        return {key: _resolve_templates(item, namespace) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_templates(item, namespace) for item in value]
    if not isinstance(value, str) or "{{" not in value:
        return value
    whole = _WHOLE_TEMPLATE_RE.match(value.strip())
    if whole:
        resolved = _lookup_template_path(namespace, whole.group(1))
        if resolved is _TEMPLATE_MISSING:
            raise TemplateResolutionError(whole.group(1))
        return resolved

    def _substitute(match: "re.Match[str]") -> str:
        resolved_part = _lookup_template_path(namespace, match.group(1))
        if resolved_part is _TEMPLATE_MISSING:
            raise TemplateResolutionError(match.group(1))
        return str(resolved_part)

    return _TEMPLATE_RE.sub(_substitute, value)


def _expand_for_each(step: dict[str, Any], step_outputs: dict[str, Any]) -> list[dict[str, Any]]:
    """forEach taşıyan adımı, çözülen listenin her elemanı için bir kopyaya açar."""
    source = step.get("forEach")
    if isinstance(source, str):
        source = _resolve_templates(source, {"steps": step_outputs})
    if not isinstance(source, list):
        raise TemplateResolutionError("forEach bir listeye çözülemedi")
    items = source[:_MAX_FOREACH_ITEMS]
    base_id = str(step.get("id", "") or "step")
    expanded: list[dict[str, Any]] = []
    for position, element in enumerate(items):
        clone = {key: value for key, value in step.items() if key != "forEach"}
        clone["id"] = f"{base_id}_{position + 1}"
        namespace = {"steps": step_outputs, "item": element, "index": position + 1}
        clone["args"] = _resolve_templates(dict(clone.get("args", {}) or {}), namespace)
        description = str(clone.get("description", "") or "")
        if "{{" in description:
            try:
                clone["description"] = str(_resolve_templates(description, namespace))
            except TemplateResolutionError:
                pass
        expanded.append(clone)
    return expanded


@dataclass(frozen=True)
class StepVerificationResult:
    ok: bool
    message: str = ""


class ExecutorCore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._current: dict[str, dict[str, Any]] = {}
        self._preemption_requests: dict[str, str] = {}
        # Canlı checklist: adım geçişlerinde (conversation_id, task_trace bloğu)
        # ile çağrılır. Bridge bunu unsolicited event olarak masaüstüne akıtır.
        self._progress_emitter: Callable[[str, dict[str, Any]], None] | None = None
        self._metrics = {
            "completed": 0,
            "failed": 0,
            "verificationRetries": 0,
            "fallbacks": 0,
            "retrievalHits": 0,
            "sharedRetrievalHits": 0,
            "retrievalFallbacks": 0,
        }
        self._last_fallback_reason = ""
        self._graph_backend = "langgraph" if StateGraph is not None else "sequential_fallback"
        self._model_router_backend = "litellm" if litellm_adapter.available() else "native_router"
        self._persist()

    def _initial_execution_trace(self, *, summary: str = "", execution_strategy: str = "single_lane") -> dict[str, Any]:
        return {
            "plannerVersion": PLANNER_VERSION,
            "summary": _safe_text(summary),
            "executionStrategy": str(execution_strategy or "single_lane"),
            "stepStates": [],
            "verificationState": {
                "status": "pending",
                "checkedSteps": 0,
                "failedStepId": "",
                "lastReason": "",
            },
            "repair": {
                "attempted": False,
                "repairAttempts": 0,
                "lastStrategy": "",
                "lastReason": "",
            },
            "scheduler": {
                "policyVersion": "p2.v1",
                "orderedStepIds": [],
                "maxParallelReads": MAX_PARALLEL_READS,
            },
            "checkpoints": [],
            "stopReason": "",
        }

    def _step_state(self, current: dict[str, Any], step_id: str) -> dict[str, Any]:
        trace = current.get("executionTrace")
        trace = dict(trace) if isinstance(trace, dict) else self._initial_execution_trace()
        step_states = trace.get("stepStates")
        step_states = step_states if isinstance(step_states, list) else []
        for state in step_states:
            if isinstance(state, dict) and str(state.get("id", "") or "") == step_id:
                current["executionTrace"] = trace
                return state
        state: dict[str, Any] = {"id": step_id}
        step_states.append(state)
        trace["stepStates"] = step_states
        current["executionTrace"] = trace
        return state

    def _record_step_started(
        self,
        execution_id: str,
        *,
        step_id: str,
        capability: str,
        phase: str,
        role: str,
        verification_mode: str,
        attempt: int,
    ) -> None:
        with self._lock:
            current = self._current.get(execution_id)
            if not isinstance(current, dict):
                return
            step_state = self._step_state(current, step_id)
            step_state.update(
                {
                    "id": step_id,
                    "capability": capability,
                    "phase": phase,
                    "role": role,
                    "status": "running",
                    "attemptCount": max(int(step_state.get("attemptCount", 0) or 0), attempt),
                    "startedAt": str(step_state.get("startedAt", "") or _utc_now_iso()),
                    "finishedAt": "",
                    "verificationMode": verification_mode,
                    "verificationStatus": "pending",
                    "errorCode": "",
                    "stopReason": "",
                }
            )
            self._persist()
        self._emit_progress(execution_id)

    def _record_step_result(
        self,
        execution_id: str,
        *,
        step_id: str,
        status: str,
        verification_status: str,
        output_preview: str = "",
        error_code: str = "",
        stop_reason: str = "",
    ) -> None:
        with self._lock:
            current = self._current.get(execution_id)
            if not isinstance(current, dict):
                return
            step_state = self._step_state(current, step_id)
            step_state.update(
                {
                    "status": status,
                    "verificationStatus": verification_status,
                    "outputPreview": _safe_text(output_preview, limit=240) if output_preview else "",
                    "errorCode": error_code,
                    "stopReason": stop_reason,
                    "finishedAt": _utc_now_iso(),
                }
            )
            trace = current.get("executionTrace")
            trace = dict(trace) if isinstance(trace, dict) else self._initial_execution_trace()
            verification = trace.get("verificationState")
            verification = dict(verification) if isinstance(verification, dict) else {}
            verification["checkedSteps"] = int(verification.get("checkedSteps", 0) or 0) + 1
            if verification_status in {"passed", "repaired"}:
                verification["status"] = verification_status
            elif verification_status == "failed":
                verification["status"] = "failed"
                verification["failedStepId"] = step_id
                verification["lastReason"] = stop_reason or output_preview
            trace["verificationState"] = verification
            current["executionTrace"] = trace
            self._persist()
        self._emit_progress(execution_id)

    def _record_repair_attempt(self, execution_id: str, *, strategy: str, reason: str) -> None:
        with self._lock:
            current = self._current.get(execution_id)
            if not isinstance(current, dict):
                return
            trace = current.get("executionTrace")
            trace = dict(trace) if isinstance(trace, dict) else self._initial_execution_trace()
            repair = trace.get("repair")
            repair = dict(repair) if isinstance(repair, dict) else {}
            repair["attempted"] = True
            repair["repairAttempts"] = int(repair.get("repairAttempts", 0) or 0) + 1
            repair["lastStrategy"] = strategy
            repair["lastReason"] = reason
            trace["repair"] = repair
            current["executionTrace"] = trace
            self._persist()

    def _set_stop_reason(self, execution_id: str, reason: str) -> None:
        with self._lock:
            current = self._current.get(execution_id)
            if not isinstance(current, dict):
                return
            trace = current.get("executionTrace")
            trace = dict(trace) if isinstance(trace, dict) else self._initial_execution_trace()
            trace["stopReason"] = str(reason or "").strip()
            current["executionTrace"] = trace
            self._persist()

    def request_preemption(self, execution_id: str, *, reason: str = "higher_priority_ready") -> bool:
        """Request a stop that is consumed only between completed steps."""
        with self._lock:
            if execution_id not in self._current:
                return False
            self._preemption_requests[execution_id] = _safe_text(reason, limit=120) or "higher_priority_ready"
            return True

    def _take_preemption(self, execution_id: str) -> str:
        with self._lock:
            return self._preemption_requests.pop(execution_id, "")

    def _record_checkpoint(self, execution_id: str, step_id: str) -> None:
        with self._lock:
            current = self._current.get(execution_id)
            if not isinstance(current, dict):
                return
            trace = current.get("executionTrace")
            trace = dict(trace) if isinstance(trace, dict) else self._initial_execution_trace()
            checkpoints = trace.get("checkpoints")
            checkpoints = list(checkpoints) if isinstance(checkpoints, list) else []
            checkpoints.append({"stepId": step_id, "completedAt": _utc_now_iso()})
            trace["checkpoints"] = checkpoints[-32:]
            current["executionTrace"] = trace
            self._persist()

    def _record_scheduler_plan(self, execution_id: str, steps: list[dict[str, Any]]) -> None:
        with self._lock:
            current = self._current.get(execution_id)
            if not isinstance(current, dict):
                return
            trace = current.get("executionTrace")
            trace = dict(trace) if isinstance(trace, dict) else self._initial_execution_trace()
            trace["scheduler"] = {
                "policyVersion": "p2.v1",
                "orderedStepIds": [str(step.get("id", "") or "") for step in steps],
                "maxParallelReads": MAX_PARALLEL_READS,
            }
            current["executionTrace"] = trace
            self._persist()

    def set_progress_emitter(self, emitter: Callable[[str, dict[str, Any]], None] | None) -> None:
        """Bridge, canlı checklist için burayı bağlar: her adım geçişinde
        (conversation_id, task_trace bloğu) ile çağrılır."""
        self._progress_emitter = emitter

    _CAPABILITY_LABELS: dict[str, str] = {
        "web_research": "Araştırılıyor",
        "document_write": "Belge yazılıyor",
        "spreadsheet_write": "Tablo hazırlanıyor",
        "presentation_write": "Sunum hazırlanıyor",
        "canvas_write": "Görsel belge oluşturuluyor",
        "chart_generate": "Grafik çiziliyor",
        "image_generate": "Görsel üretiliyor",
        "image_fetch": "Görsel indiriliyor",
        "file_read": "Dosya okunuyor",
        "file_search": "Kod/dosya aranıyor",
        "directory_tree": "Proje taranıyor",
        "file_write": "Dosya yazılıyor",
        "file_patch": "Dosya düzenleniyor",
        "git_status": "Git durumu",
        "git_diff": "Değişiklikler",
        "git_commit": "Commit'leniyor",
        "git_branch": "Branch oluşturuluyor",
        "shell_run": "Komut çalıştırılıyor",
        "open_app": "Uygulama açılıyor",
        "browser_control": "Tarayıcı",
        "web_search": "Web araması",
        "mcp_call_tool": "Uygulama aracı",
    }

    @classmethod
    def _step_label(cls, capability: str, description: str = "") -> str:
        desc = _safe_text(description, limit=48)
        if desc:
            return desc
        return cls._CAPABILITY_LABELS.get(capability, capability or "Adım")

    def _build_task_trace_block(self, current: dict[str, Any], *, final: bool = False) -> dict[str, Any]:
        """execute_plan_steps ilerlemesini task_trace bloğuna çevirir (canlı checklist)."""
        exec_id = str(current.get("id", "") or "")
        trace = current.get("executionTrace")
        trace = trace if isinstance(trace, dict) else {}
        step_states = trace.get("stepStates")
        step_states = step_states if isinstance(step_states, list) else []
        steps: list[dict[str, Any]] = []
        active_step_id = ""
        for state in step_states:
            if not isinstance(state, dict):
                continue
            status = str(state.get("status", "") or "pending")
            # executor status → task_trace status
            mapped = {"running": "running", "completed": "completed", "failed": "failed"}.get(status, "pending")
            step_id = str(state.get("id", "") or f"step_{len(steps) + 1}")
            if mapped == "running":
                active_step_id = step_id
            steps.append(
                {
                    "id": step_id,
                    "label": self._step_label(str(state.get("capability", "") or ""), str(state.get("label", "") or "")),
                    "status": mapped,
                    "capability": str(state.get("capability", "") or ""),
                    "detail": _safe_text(str(state.get("outputPreview", "") or state.get("stopReason", "") or ""), limit=120),
                }
            )
        overall = "running"
        if final:
            overall = "failed" if any(s["status"] == "failed" for s in steps) else "completed"
        return {
            "type": "task_trace",
            "stableBlockId": f"tasktrace_{exec_id}",
            "taskId": exec_id,
            "status": overall,
            "title": _safe_text(str(current.get("summary", "") or ""), limit=80) or "Görev yürütülüyor",
            "activeStepId": active_step_id,
            "steps": steps,
        }

    def _emit_progress(self, execution_id: str, *, final: bool = False) -> None:
        emitter = self._progress_emitter
        if emitter is None:
            return
        with self._lock:
            current = self._current.get(execution_id)
            if not isinstance(current, dict):
                return
            conversation_id = str(current.get("conversationId", "") or "")
            block = self._build_task_trace_block(current, final=final)
        if not block.get("steps"):
            return
        try:
            emitter(conversation_id, block)
        except Exception:
            pass  # ilerleme akışı hiçbir zaman yürütmeyi bozmamalı

    def graph_backend(self) -> str:
        return self._graph_backend

    def model_router_backend(self) -> str:
        return self._model_router_backend

    def begin_execution(
        self,
        *,
        source: str,
        task_id: str = "",
        conversation_id: str = "",
        summary: str = "",
        planned_steps: list[dict[str, Any]] | None = None,
        plan_preview: dict[str, Any] | None = None,
        execution_id: str | None = None,
    ) -> str:
        with self._lock:
            active_id = execution_id or f"exec_{uuid.uuid4().hex[:12]}"
            normalized_steps = [dict(step) for step in (planned_steps or []) if isinstance(step, dict)]
            if not normalized_steps and isinstance(plan_preview, dict):
                preview_steps = plan_preview.get("steps", [])
                if isinstance(preview_steps, list):
                    normalized_steps = [dict(step) for step in preview_steps if isinstance(step, dict)]
            agent_plan = build_agent_plan(normalized_steps, summary=summary)
            self._current[active_id] = {
                "id": active_id,
                "source": str(source or "runtime"),
                "taskId": str(task_id or "").strip(),
                "conversationId": str(conversation_id or "").strip(),
                "summary": _safe_text(summary),
                "stepCount": agent_plan.get("stepCount", 0),
                "stepCapabilities": agent_plan.get("capabilities", []),
                "agentRoles": agent_plan.get("agentRoles", []),
                "agentPlan": agent_plan,
                "stage": "intake",
                "startedAt": _utc_now_iso(),
                "status": "running",
                "provider": "",
                "model": "",
                "routeReason": "",
                "displayStage": "Bakıyor",
                "displayAction": "Bakıyor",
                "verificationUsed": False,
                "executionStrategy": str(agent_plan.get("executionStrategy", "single_lane") or "single_lane"),
                "nativeReadiness": {},
                "degradationReasons": [],
                "executionTrace": self._initial_execution_trace(
                    summary=summary,
                    execution_strategy=str(agent_plan.get("executionStrategy", "single_lane") or "single_lane"),
                ),
            }
            if isinstance(plan_preview, dict):
                self._current[active_id]["planPreview"] = dict(plan_preview)
            self._persist()
            return active_id

    def record_agent_plan(
        self,
        execution_id: str,
        *,
        summary: str = "",
        planned_steps: list[dict[str, Any]] | None = None,
        plan_preview: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            current = self._current.get(execution_id)
            if not isinstance(current, dict):
                return
            normalized_steps = [dict(step) for step in (planned_steps or []) if isinstance(step, dict)]
            if not normalized_steps and isinstance(plan_preview, dict):
                preview_steps = plan_preview.get("steps", [])
                if isinstance(preview_steps, list):
                    normalized_steps = [dict(step) for step in preview_steps if isinstance(step, dict)]
            agent_plan = build_agent_plan(normalized_steps, summary=summary or str(current.get("summary", "") or ""))
            current["summary"] = _safe_text(summary or current.get("summary", ""))
            current["stepCount"] = agent_plan.get("stepCount", current.get("stepCount", 0))
            current["stepCapabilities"] = agent_plan.get("capabilities", current.get("stepCapabilities", []))
            current["agentRoles"] = agent_plan.get("agentRoles", current.get("agentRoles", []))
            current["agentPlan"] = agent_plan
            current["executionStrategy"] = str(agent_plan.get("executionStrategy", current.get("executionStrategy", "single_lane")) or "single_lane")
            trace = current.get("executionTrace")
            trace = dict(trace) if isinstance(trace, dict) else self._initial_execution_trace()
            trace["plannerVersion"] = PLANNER_VERSION
            trace["executionStrategy"] = current["executionStrategy"]
            trace["summary"] = _safe_text(summary or current.get("summary", ""))
            current["executionTrace"] = trace
            if isinstance(plan_preview, dict):
                current["planPreview"] = dict(plan_preview)
            self._persist()

    def record_stage(self, execution_id: str, stage: str, *, detail: str = "", status: str = "running") -> None:
        with self._lock:
            current = self._current.get(execution_id)
            if not isinstance(current, dict):
                return
            current["stage"] = str(stage or "").strip() or current.get("stage", "intake")
            current["status"] = str(status or "").strip() or current.get("status", "running")
            if detail:
                current["detail"] = _safe_text(detail)
            self._apply_display_state(current)
            self._persist()

    def record_model_route(self, execution_id: str, *, provider: str, model: str = "", reason: str = "") -> None:
        with self._lock:
            current = self._current.get(execution_id)
            if not isinstance(current, dict):
                return
            current["provider"] = str(provider or "").strip()
            current["model"] = str(model or "").strip()
            if reason:
                current["routeReason"] = _safe_text(reason)
            self._persist()

    def record_fallback(self, reason: str) -> None:
        with self._lock:
            self._last_fallback_reason = _safe_text(reason, limit=240)
            self._metrics["fallbacks"] += 1
            self._persist()

    def record_retrieval(
        self,
        *,
        retrieval_hits: int = 0,
        shared_retrieval_hits: int = 0,
        fallback: bool = False,
    ) -> None:
        with self._lock:
            if retrieval_hits > 0:
                self._metrics["retrievalHits"] += int(retrieval_hits)
            if shared_retrieval_hits > 0:
                self._metrics["sharedRetrievalHits"] += int(shared_retrieval_hits)
            if fallback:
                self._metrics["retrievalFallbacks"] += 1
            self._persist()

    def finish_execution(self, execution_id: str, *, ok: bool, detail: str = "") -> None:
        final_block: dict[str, Any] | None = None
        conversation_id = ""
        with self._lock:
            self._preemption_requests.pop(execution_id, None)
            current = self._current.pop(execution_id, None)
            if current is None:
                return
            if ok:
                self._metrics["completed"] += 1
            else:
                self._metrics["failed"] += 1
            self._persist(
                last_execution_at=_utc_now_iso(),
                last_detail=detail,
                last_ok=ok,
                last_execution_trace=current.get("executionTrace") if isinstance(current.get("executionTrace"), dict) else None,
            )
            if self._progress_emitter is not None:
                conversation_id = str(current.get("conversationId", "") or "")
                final_block = self._build_task_trace_block(current, final=True)
        # Son checklist durumunu (tamamlandı/başarısız) lock DIŞINDA yayınla.
        if final_block is not None and final_block.get("steps") and self._progress_emitter is not None:
            try:
                self._progress_emitter(conversation_id, final_block)
            except Exception:
                pass

    def _apply_display_state(self, current: dict[str, Any]) -> None:
        stage = str(current.get("stage", "") or "").strip().lower()
        detail = str(current.get("detail", "") or "").strip().lower()
        status = str(current.get("status", "") or "").strip().lower()

        display_stage = "Bakıyor"
        display_action = "Bakıyor"

        if stage in {"planning", "plan_execution", "intake"}:
            display_stage = "Bakıyor"
            display_action = "Bakıyor"
        elif stage == "permission_gate":
            display_stage = "Onay bekliyor"
            display_action = "Onay bekliyor"
        elif stage == "retry_repair":
            display_stage = "Tekrar kontrol ediyor"
            display_action = "Tekrar kontrol ediyor"
            current["verificationUsed"] = True
        elif stage == "verification":
            display_stage = "Kontrol ediyor"
            display_action = "Kontrol ediyor"
            current["verificationUsed"] = True
        elif stage == "finalize" or status == "completed":
            display_stage = "Hazır"
            display_action = "Hazır"
        elif stage == "step_execution":
            if any(token in detail for token in ("retrieve_context", "document_read", "ocr_read", "source.verify", "workspace.answer")):
                display_stage = "Kaynak topluyor"
                display_action = "Kaynak topluyor"
                current["verificationUsed"] = True
            elif any(token in detail for token in ("mcp_call_tool", "mcp.readonly_tool_proxy")):
                display_stage = "Bakıyor"
                display_action = "Bakıyor"
                current["verificationUsed"] = True
            elif any(token in detail for token in ("document_write", "spreadsheet_write", "presentation_write", "canvas_write")):
                display_stage = "Hazırlıyor"
                display_action = "Hazırlıyor"
            else:
                display_stage = "Bakıyor"
                display_action = "Bakıyor"

        current["displayStage"] = display_stage
        current["displayAction"] = display_action

    def status_payload(
        self,
        *,
        state: dict[str, Any],
        runtime_capabilities: list[str],
        local_provider_readiness: dict[str, Any],
        cloud_provider_readiness: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            current = [dict(item) for item in self._current.values()]
            active_agent = current[0] if current else {}
            active_plan = active_agent.get("agentPlan", {})
            active_plan = dict(active_plan) if isinstance(active_plan, dict) else {}
            return {
                "available": True,
                "graphBackend": self._graph_backend,
                "modelRouterBackend": self._model_router_backend,
                "langgraphAvailable": StateGraph is not None,
                "liteLLMAvailable": litellm_adapter.available(),
                "activeExecutionCount": len(current),
                "currentExecutions": current,
                "agentStatus": {
                    "active": bool(current),
                    "displayStage": str(active_agent.get("displayStage", "") or ""),
                    "displayAction": str(active_agent.get("displayAction", "") or ""),
                    "verificationUsed": bool(active_agent.get("verificationUsed", False)),
                    "executionStrategy": str(active_plan.get("executionStrategy", active_agent.get("executionStrategy", "single_lane")) or "single_lane"),
                    "stepCount": int(active_plan.get("stepCount", active_agent.get("stepCount", 0)) or 0),
                    "stepCapabilities": list(active_plan.get("capabilities", active_agent.get("stepCapabilities", [])))
                    if isinstance(active_plan.get("capabilities", active_agent.get("stepCapabilities", [])), list)
                    else [],
                    "agentRoles": list(active_plan.get("agentRoles", active_agent.get("agentRoles", [])))
                    if isinstance(active_plan.get("agentRoles", active_agent.get("agentRoles", [])), list)
                    else [],
                    "laneCount": int(active_plan.get("laneCount", len(active_plan.get("agentRoles", active_agent.get("agentRoles", [])) or [])) or 0),
                    "planSummary": str(active_plan.get("summary", active_agent.get("summary", "")) or ""),
                    "nativeReadiness": dict(active_agent.get("nativeReadiness", {}) or {}) if isinstance(active_agent.get("nativeReadiness"), dict) else {},
                    "degradationReasons": list(active_agent.get("degradationReasons", [])) if isinstance(active_agent.get("degradationReasons"), list) else [],
                },
                "lastFallbackReason": self._last_fallback_reason,
                "metrics": dict(self._metrics),
                "modelRouterReadiness": {
                    "policy": str(state.get("providers", {}).get("routingPolicy", "local_first") if isinstance(state.get("providers"), dict) else "local_first"),
                    "fallbackToCloud": bool(state.get("providers", {}).get("fallbackToCloud", True) if isinstance(state.get("providers"), dict) else True),
                    "localProviders": local_provider_readiness,
                    "cloudProviders": cloud_provider_readiness,
                },
                "capabilityMetadataSummary": capability_metadata_summary(runtime_capabilities),
            }

    def _replan_remaining(
        self,
        replan_fn: Callable[[dict[str, Any]], list[dict[str, Any]]] | None,
        replans_used: int,
        max_replans: int,
        context: dict[str, Any],
    ) -> list[dict[str, Any]] | None:
        """ReAct: bir adım başarısız/doğrulanamaz olduğunda planlayıcıya bağlamı
        geri besleyip kalan planın revizesini ister. Bütçe dolduysa, callback yoksa
        veya geçerli adım dönmezse None döner (çağıran normal iptale düşer)."""
        if replan_fn is None or replans_used >= max_replans:
            return None
        try:
            revised = replan_fn(dict(context))
        except Exception:
            return None
        if not isinstance(revised, list):
            return None
        cleaned = [
            dict(step)
            for step in revised
            if isinstance(step, dict) and str(step.get("capability", "") or "").strip()
        ]
        return cleaned or None

    def _prefetch_read_batch(
        self,
        *,
        execution_id: str,
        batch: list[dict[str, Any]],
        planned_roles: list[dict[str, Any]],
        state_factory: Callable[[], dict[str, Any]],
        execute_step: Callable[[str, dict[str, Any], dict[str, Any], str], tuple[dict[str, Any], list[dict[str, Any]]]],
        source: str,
        previous_output: str,
        previous_result: dict[str, Any] | None,
        previous_artifacts: list[dict[str, Any]],
        authorize_step: Callable[[str, str, dict[str, Any], str, str], dict[str, Any] | None] | None,
        task_id: str,
    ) -> dict[str, dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        for index, step in enumerate(batch, start=1):
            capability = str(step.get("capability", "") or "").strip()
            step_id = str(step.get("id", "") or f"parallel_{index}")
            metadata = capability_metadata(capability)
            step_role = next(
                (
                    candidate for candidate in planned_roles
                    if isinstance(candidate, dict)
                    and str(candidate.get("capability", "") or "").strip() == capability
                ),
                {},
            )
            self._record_step_started(
                execution_id,
                step_id=step_id,
                capability=capability,
                phase=str(step.get("phase", "") or step_role.get("phase", "") or "gather"),
                role=str(step.get("role", "") or step_role.get("role", "") or "observer"),
                verification_mode=str(metadata.get("verificationMode", "tool_result") or "tool_result"),
                attempt=1,
            )
            args = dict(step.get("args", {}) or {})
            args["_confirmed"] = True
            args["_retryAttempt"] = 1
            if previous_output:
                args["_previousOutput"] = previous_output
            if previous_result:
                args["_previousResult"] = dict(previous_result)
            if previous_artifacts:
                args["_previousArtifacts"] = list(previous_artifacts)
            authorization_error: dict[str, Any] | None = None
            if authorize_step is not None:
                try:
                    grant = authorize_step(step_id, capability, args, source, task_id)
                    if isinstance(grant, dict):
                        args["_capabilityGrant"] = grant
                except Exception as exc:
                    authorization_error = {
                        "ok": False,
                        "output": str(getattr(exc, "message", "") or "Görev yetkisi bu adıma uymuyor."),
                        "error": {
                            "code": str(getattr(exc, "code", "CAPABILITY_GRANT_DENIED") or "CAPABILITY_GRANT_DENIED"),
                            "message": str(getattr(exc, "message", "") or "Görev yetkisi bu adıma uymuyor."),
                        },
                    }
            captured_state = state_factory()
            trust_state = captured_state.get("runtime", {}) if isinstance(captured_state, dict) else {}
            trust_state = trust_state if isinstance(trust_state, dict) else {}
            if isinstance(args.get("_capabilityGrant"), dict) and not isinstance(trust_state.get("executionTrust"), dict):
                authorization_error = {
                    "ok": False,
                    "output": "CapabilityGrant güven bağlamı worker için doğrulanamadı.",
                    "error": {
                        "code": "WORK_ORDER_TRUST_MISSING",
                        "message": "CapabilityGrant güven bağlamı worker için doğrulanamadı.",
                    },
                }
            prepared.append({
                "stepId": step_id,
                "capability": capability,
                "args": args,
                "authorizationError": authorization_error,
                "state": captured_state,
            })

        def worker(item: dict[str, Any]) -> dict[str, Any]:
            if isinstance(item.get("authorizationError"), dict):
                return {**item, "toolResult": dict(item["authorizationError"]), "events": []}
            try:
                tool_result, step_events = execute_step(
                    str(item["capability"]),
                    dict(item["args"]),
                    dict(item.get("state", {}) or {}),
                    source,
                )
                if not isinstance(tool_result, dict) or not isinstance(step_events, list):
                    raise TypeError("invalid_step_result")
                return {
                    **item,
                    "toolResult": tool_result,
                    "events": [event for event in step_events if isinstance(event, dict)],
                }
            except Exception:
                return {
                    **item,
                    "toolResult": {
                        "ok": False,
                        "output": "Read adımı güvenli şekilde tamamlanamadı.",
                        "error": {
                            "code": "PARALLEL_READ_FAILED",
                            "message": "Read adımı güvenli şekilde tamamlanamadı.",
                        },
                    },
                    "events": [],
                }

        results = run_parallel(prepared, worker, limit=MAX_PARALLEL_READS)
        return {str(item["stepId"]): item for item in results}

    def execute_plan_steps(
        self,
        *,
        steps: list[dict[str, Any]],
        state_factory: Callable[[], dict[str, Any]],
        execute_step: Callable[[str, dict[str, Any], dict[str, Any], str], tuple[dict[str, Any], list[dict[str, Any]]]],
        source: str,
        task_id: str = "",
        conversation_id: str = "",
        replan_fn: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
        max_replans: int = 2,
        authorize_step: Callable[[str, str, dict[str, Any], str, str], dict[str, Any] | None] | None = None,
        execution_id: str | None = None,
    ) -> tuple[bool, str, list[dict[str, Any]], str, dict[str, Any] | None, list[dict[str, Any]]]:
        execution_id = self.begin_execution(
            source=source,
            task_id=task_id,
            conversation_id=conversation_id,
            summary="; ".join(
                str(step.get("capability", "") or "").strip()
                for step in steps
                if isinstance(step, dict)
            ),
            planned_steps=steps,
            execution_id=execution_id,
        )
        outputs: list[str] = []
        events: list[dict[str, Any]] = []
        error_code = ""
        structured_result: dict[str, Any] | None = None
        artifacts: list[dict[str, Any]] = []
        previous_output = ""
        previous_result: dict[str, Any] | None = None
        previous_artifacts: list[dict[str, Any]] = []
        # Adım kimliği → yapılandırılmış çıktı; {{steps.<id>...}} şablonları ve
        # forEach fan-out buradan beslenir.
        step_outputs: dict[str, dict[str, Any]] = {}
        completed_step_ids: set[str] = set()
        prefetched_results: dict[str, dict[str, Any]] = {}

        try:
            self.record_stage(execution_id, "plan_execution", detail="steps")
            planned_roles = self._current.get(execution_id, {}).get("agentPlan", {}).get("stepRoles", [])
            planned_roles = planned_roles if isinstance(planned_roles, list) else []
            # ReAct: statik plan yerine adım sonucunu değerlendirip kalan planı
            # revize edebilmek için indeks tabanlı, splice edilebilir döngü.
            # `steps` yerel bir kopya; replan_fn kalan adımları yeniden yazabilir.
            scheduler_state = state_factory()
            steps = schedule_steps(
                [dict(step) for step in steps if isinstance(step, dict)],
                metadata_provider=capability_metadata,
                readiness_provider=lambda capability: capability_readiness(capability, state=scheduler_state),
            )
            self._record_scheduler_plan(execution_id, steps)
            replans_used = 0
            step_index = 0
            while step_index < len(steps):
                preemption_reason = self._take_preemption(execution_id) if not prefetched_results else ""
                if preemption_reason:
                    message = "Görev daha yüksek öncelikli iş için güvenli checkpoint sınırında durduruldu."
                    self.record_stage(execution_id, "preempted", detail=preemption_reason, status="preempted")
                    self._set_stop_reason(execution_id, "preempted_at_checkpoint")
                    self.finish_execution(execution_id, ok=False, detail=message)
                    return False, message, events, "EXECUTION_PREEMPTED", structured_result, artifacts
                step = steps[step_index]
                scheduler_facts = step.get("_scheduler") if isinstance(step.get("_scheduler"), dict) else {}
                if scheduler_facts.get("ready") is False:
                    message = "Capability henüz yürütmeye hazır değil; görev güvenli şekilde ertelendi."
                    self._set_stop_reason(execution_id, "capability_not_ready")
                    self.finish_execution(execution_id, ok=False, detail=message)
                    return False, message, events, "CAPABILITY_NOT_READY", structured_result, artifacts
                # forEach fan-out: adım, önceki bir adımın liste çıktısının her
                # elemanı için kopyalanır; döngü aynı indeksten (ilk kopya)
                # devam eder.
                if isinstance(step, dict) and step.get("forEach") is not None:
                    try:
                        expanded = _expand_for_each(step, step_outputs)
                    except TemplateResolutionError as exc:
                        message = f"forEach listesi çözülemedi: {exc.expression}"
                        self._set_stop_reason(execution_id, "template_unresolved")
                        self.finish_execution(execution_id, ok=False, detail=message)
                        return False, message, events, "TEMPLATE_UNRESOLVED", structured_result, artifacts
                    steps = steps[:step_index] + expanded + steps[step_index + 1 :]
                    continue
                if not prefetched_results:
                    batch = parallel_read_batch(
                        steps,
                        step_index,
                        completed_step_ids=completed_step_ids,
                    )
                    if batch:
                        prefetched_results = self._prefetch_read_batch(
                            execution_id=execution_id,
                            batch=batch,
                            planned_roles=planned_roles,
                            state_factory=state_factory,
                            execute_step=execute_step,
                            source=source,
                            previous_output=previous_output,
                            previous_result=previous_result,
                            previous_artifacts=previous_artifacts,
                            authorize_step=authorize_step,
                            task_id=task_id,
                        )
                index = step_index + 1
                step_index += 1
                if not isinstance(step, dict):
                    continue
                capability = str(step.get("capability", "") or "").strip()
                if not capability:
                    continue
                metadata = capability_metadata(capability)
                step_role = next(
                    (
                        candidate for candidate in planned_roles
                        if isinstance(candidate, dict)
                        and str(candidate.get("capability", "") or "").strip() == capability
                    ),
                    {},
                )
                step_id = str(step.get("id", "") or step_role.get("id", "") or f"step_{index}")
                step_phase = str(step.get("phase", "") or step_role.get("phase", "") or "act")
                step_role_name = str(step.get("role", "") or step_role.get("role", "") or "operator")
                self.record_stage(execution_id, "step_execution", detail=capability)
                did_replan = False
                attempt = 0
                prefetched = prefetched_results.pop(step_id, None)
                while True:
                    attempt += 1
                    if attempt == 1 and isinstance(prefetched, dict):
                        args = dict(prefetched.get("args", {}) or {})
                        tool_result = dict(prefetched.get("toolResult", {}) or {})
                        step_events = [
                            event for event in (prefetched.get("events", []) or [])
                            if isinstance(event, dict)
                        ]
                    else:
                        self._record_step_started(
                            execution_id,
                            step_id=step_id,
                            capability=capability,
                            phase=step_phase,
                            role=step_role_name,
                            verification_mode=str(metadata.get("verificationMode", "tool_result") or "tool_result"),
                            attempt=attempt,
                        )
                        args = step.get("args", {})
                        args = dict(args) if isinstance(args, dict) else {}
                        # Önceki adımların yapılandırılmış çıktısına şablon referansı.
                        try:
                            args = _resolve_templates(args, {"steps": step_outputs})
                        except TemplateResolutionError as exc:
                            message = f"Adım argümanındaki referans çözülemedi: {exc.expression}"
                            error_code = "TEMPLATE_UNRESOLVED"
                            self._record_step_result(
                                execution_id,
                                step_id=step_id,
                                status="failed",
                                verification_status="failed",
                                output_preview=message,
                                error_code=error_code,
                                stop_reason=message,
                            )
                            self._set_stop_reason(execution_id, error_code.lower())
                            self.finish_execution(execution_id, ok=False, detail=message)
                            return False, message, events, error_code, structured_result, artifacts
                        args["_confirmed"] = True
                        args["_retryAttempt"] = attempt
                        if previous_output:
                            args["_previousOutput"] = previous_output
                        if previous_result:
                            args["_previousResult"] = previous_result
                        if previous_artifacts:
                            args["_previousArtifacts"] = list(previous_artifacts)
                        if authorize_step is not None:
                            try:
                                grant = authorize_step(step_id, capability, args, source, task_id)
                            except Exception as exc:
                                error_code = str(getattr(exc, "code", "CAPABILITY_GRANT_DENIED") or "CAPABILITY_GRANT_DENIED")
                                message = str(getattr(exc, "message", "") or "Görev yetkisi bu adıma uymuyor.")
                                self._record_step_result(
                                    execution_id,
                                    step_id=step_id,
                                    status="failed",
                                    verification_status="failed",
                                    output_preview=message,
                                    error_code=error_code,
                                    stop_reason=message,
                                )
                                self._set_stop_reason(execution_id, error_code.lower())
                                self.finish_execution(execution_id, ok=False, detail=message)
                                return False, message, events, error_code, structured_result, artifacts
                            if isinstance(grant, dict):
                                args["_capabilityGrant"] = grant
                        # P3: yürütme öncesi ön koşul kapısı — ihlal, araç hiç
                        # çalıştırılmadan tool_failure yoluna (replan dahil) girer.
                        pre_error = precondition_error(capability, args, state_factory())
                        if pre_error is not None:
                            tool_result, step_events = (
                                {
                                    "ok": False,
                                    "tool": capability,
                                    "output": pre_error["message"],
                                    "result": {},
                                    "artifacts": [],
                                    "error": dict(pre_error),
                                },
                                [],
                            )
                        else:
                            tool_result, step_events = execute_step(
                                capability,
                                args,
                                state_factory(),
                                source,
                            )
                    events.extend(step_events)
                    if not tool_result.get("ok"):
                        error = tool_result.get("error") if isinstance(tool_result.get("error"), dict) else {}
                        error_code = str(error.get("code") or "TOOL_EXECUTION_FAILED")
                        message = str(error.get("message") or tool_result.get("output") or "").strip() or "Araç güvenli şekilde tamamlanamadı."
                        self._record_step_result(
                            execution_id,
                            step_id=step_id,
                            status="failed",
                            verification_status="failed",
                            output_preview=message,
                            error_code=error_code,
                            stop_reason=message,
                        )
                        revised = self._replan_remaining(
                            replan_fn,
                            replans_used,
                            max_replans,
                            {
                                "reason": "tool_failure",
                                "failedCapability": capability,
                                "errorCode": error_code,
                                "message": message,
                                "completedOutputs": list(outputs),
                                "failedArgs": {
                                    k: v for k, v in (step.get("args") or {}).items()
                                    if not str(k).startswith("_")
                                },
                                "remainingCapabilities": [
                                    str(s.get("capability", "") or "") for s in steps[step_index:]
                                ],
                                "remainingSteps": [
                                    {key: value for key, value in s.items() if key != "_scheduler"}
                                    for s in steps[step_index:]
                                ],
                            },
                        )
                        if revised is not None:
                            replans_used += 1
                            prefetched_results.clear()
                            revised = schedule_steps(
                                revised,
                                metadata_provider=capability_metadata,
                                readiness_provider=lambda name: capability_readiness(name, state=state_factory()),
                                completed_step_ids=completed_step_ids,
                            )
                            self._record_repair_attempt(execution_id, strategy="replan_remaining", reason=message)
                            self.record_stage(execution_id, "replan", detail=f"{capability}:{error_code}")
                            steps = steps[: step_index - 1] + revised
                            step_index = step_index - 1
                            did_replan = True
                            error_code = ""  # revize edildi; hata kodu temizlenir
                            break
                        self._set_stop_reason(execution_id, error_code.lower())
                        self.finish_execution(execution_id, ok=False, detail=message)
                        return False, message, events, error_code, structured_result, artifacts

                    verification = self._verify_step_result(metadata, args, tool_result)
                    if verification.ok:
                        self._record_step_result(
                            execution_id,
                            step_id=step_id,
                            status="completed",
                            verification_status="repaired" if attempt > 1 else "passed",
                            output_preview=str(tool_result.get("output", "") or ""),
                        )
                        break
                    if not bool(metadata.get("retryable", False)) or attempt >= 2:
                        error_code = "VERIFICATION_FAILED"
                        self._record_step_result(
                            execution_id,
                            step_id=step_id,
                            status="failed",
                            verification_status="failed",
                            output_preview=verification.message,
                            error_code=error_code,
                            stop_reason=verification.message,
                        )
                        revised = self._replan_remaining(
                            replan_fn,
                            replans_used,
                            max_replans,
                            {
                                "reason": "verification_failure",
                                "failedCapability": capability,
                                "errorCode": error_code,
                                "message": verification.message,
                                "completedOutputs": list(outputs),
                                "failedArgs": {
                                    k: v for k, v in (step.get("args") or {}).items()
                                    if not str(k).startswith("_")
                                },
                                "remainingCapabilities": [
                                    str(s.get("capability", "") or "") for s in steps[step_index:]
                                ],
                                "remainingSteps": [
                                    {key: value for key, value in s.items() if key != "_scheduler"}
                                    for s in steps[step_index:]
                                ],
                            },
                        )
                        if revised is not None:
                            replans_used += 1
                            prefetched_results.clear()
                            revised = schedule_steps(
                                revised,
                                metadata_provider=capability_metadata,
                                readiness_provider=lambda name: capability_readiness(name, state=state_factory()),
                                completed_step_ids=completed_step_ids,
                            )
                            self._record_repair_attempt(execution_id, strategy="replan_remaining", reason=verification.message)
                            self.record_stage(execution_id, "replan", detail=f"{capability}:{error_code}")
                            steps = steps[: step_index - 1] + revised
                            step_index = step_index - 1
                            did_replan = True
                            error_code = ""  # revize edildi; hata kodu temizlenir
                            break
                        self._set_stop_reason(execution_id, "verification_failed")
                        self.finish_execution(execution_id, ok=False, detail=verification.message)
                        return False, verification.message or "Doğrulama başarısız oldu.", events, error_code, structured_result, artifacts
                    with self._lock:
                        self._metrics["verificationRetries"] += 1
                        self._persist()
                    self._record_repair_attempt(
                        execution_id,
                        strategy="retry_same_capability",
                        reason=verification.message,
                    )
                    self.record_stage(execution_id, "retry_repair", detail=f"{capability}:{verification.message}")

                # Kalan plan revize edildiyse (ReAct), başarısız adımın çıktısını
                # işleme — döngü yeni adımdan devam etsin.
                if did_replan:
                    continue

                output = str(tool_result.get("output", "") or "").strip()
                if output:
                    outputs.append(output)
                    previous_output = output
                result_payload = tool_result.get("result")
                if isinstance(result_payload, dict):
                    structured_result = dict(result_payload)
                    previous_result = dict(result_payload)
                step_artifacts = tool_result.get("artifacts", [])
                cleaned_artifacts: list[dict[str, Any]] = []
                if isinstance(step_artifacts, list):
                    cleaned_artifacts = [item for item in step_artifacts if isinstance(item, dict)]
                    artifacts.extend(cleaned_artifacts)
                    previous_artifacts = cleaned_artifacts
                step_outputs[step_id] = {
                    "output": output,
                    "result": dict(result_payload) if isinstance(result_payload, dict) else {},
                    "artifacts": cleaned_artifacts,
                }
                completed_step_ids.add(step_id)
                self._record_checkpoint(execution_id, step_id)

            summary = "\n".join(output for output in outputs if output).strip() or "İşlem tamamlandı."
            self.record_stage(execution_id, "finalize", detail=summary, status="completed")
            self._set_stop_reason(execution_id, "completed")
            self.finish_execution(execution_id, ok=True, detail=summary)
            return True, summary, events, error_code, structured_result, artifacts
        except SchedulerPlanError:
            message = "Plan scheduler tarafından güvenli şekilde reddedildi."
            self._set_stop_reason(execution_id, "scheduler_plan_invalid")
            self.finish_execution(execution_id, ok=False, detail=message)
            return False, message, events, "SCHEDULER_PLAN_INVALID", structured_result, artifacts
        except Exception as exc:  # pragma: no cover - defensive safety net
            message = str(exc) or "executor_plan_failed"
            self._set_stop_reason(execution_id, "executor_plan_failed")
            self.finish_execution(execution_id, ok=False, detail=message)
            return False, message, events, "EXECUTOR_PLAN_FAILED", structured_result, artifacts

    def _verify_step_result(self, metadata: dict[str, Any], args: dict[str, Any], tool_result: dict[str, Any]) -> StepVerificationResult:
        mode = str(metadata.get("verificationMode", "tool_result") or "tool_result")
        if mode == "none":
            return StepVerificationResult(True)
        result_payload = tool_result.get("result")
        result_payload = dict(result_payload) if isinstance(result_payload, dict) else {}
        if mode == "foreground_confirmed":
            if bool(result_payload.get("foregroundConfirmed", False)) and str(result_payload.get("appName", "") or "").strip():
                return StepVerificationResult(True)
            return StepVerificationResult(False, "Uygulamanın öne geldiği doğrulanamadı.")
        if mode == "close_confirmed":
            if bool(result_payload.get("closedConfirmed", False)) and str(result_payload.get("appName", "") or "").strip():
                return StepVerificationResult(True)
            return StepVerificationResult(False, "Uygulamanın kapandığı doğrulanamadı.")
        if mode == "browser_handoff":
            action = str(result_payload.get("action", "") or "").strip().lower()
            target_url = str(result_payload.get("targetUrl", "") or "").strip()
            query = str(result_payload.get("query", "") or "").strip()
            handoff = str(result_payload.get("handoff", "") or "").strip()
            verified = bool(result_payload.get("handoffVerified", False))
            if (
                bool(result_payload.get("launched", False))
                and verified
                and handoff
                and ((action == "open_url" and target_url) or (action == "search" and query) or (action == "play_youtube" and (target_url or query)))
            ):
                return StepVerificationResult(True)
            return StepVerificationResult(False, "Tarayıcı handoff doğrulanamadı.")
        if mode == "media_handoff":
            provider = str(result_payload.get("provider", "") or "").strip()
            handoff = str(result_payload.get("handoff", "") or "").strip()
            query = str(result_payload.get("query", "") or "").strip()
            verified = bool(result_payload.get("handoffVerified", False))
            if bool(result_payload.get("launched", False)) and provider and handoff and query and verified:
                return StepVerificationResult(True)
            return StepVerificationResult(False, "Medya yürütmesi doğrulanamadı.")
        if mode == "screen_analysis":
            if (
                bool(result_payload.get("imageCaptured", False))
                and str(result_payload.get("analysis", "") or "").strip()
                and str(result_payload.get("captureSource", "") or "").strip()
            ):
                return StepVerificationResult(True)
            return StepVerificationResult(False, "Ekran analizi doğrulanamadı.")
        if mode == "operator_verified":
            verification = result_payload.get("verification")
            verification = dict(verification) if isinstance(verification, dict) else {}
            if bool(result_payload.get("stopped", False)):
                return StepVerificationResult(False, str(result_payload.get("stopReason", "") or "Operator durduruldu."))
            if bool(verification.get("ok", False)) and str(result_payload.get("status", "") or "").strip().lower() == "completed":
                return StepVerificationResult(True)
            return StepVerificationResult(False, str(verification.get("reason", "") or "Operator doğrulaması başarısız oldu."))
        if mode == "operator_cancelled":
            if bool(result_payload.get("stopped", False)) and str(result_payload.get("status", "") or "").strip().lower() in {"stopped", "idle"}:
                return StepVerificationResult(True)
            return StepVerificationResult(False, "Operator durdurulamadı.")
        if mode == "artifact_exists":
            # P3: varlık kontrolü yeterli değil — diskten bağımsız hash/boyut
            # readback'i gerekir (boş dosya başarı sayılmaz).
            evidence = readback_evidence(str(metadata.get("name", "") or ""), args, tool_result)
            if evidence.get("verified"):
                attach_step_evidence(tool_result, evidence)
                return StepVerificationResult(True)
            return StepVerificationResult(False, "Çıktı dosyası bağımsız doğrulamadan geçemedi (hash/boyut kanıtı yok).")
        # P3: yan etkili adımlar boş olmayan çıktıyla değil, gerçek kanıtla
        # (dosya hash'i, provider ID, gözlemlenen durum) doğrulanır.
        if bool(metadata.get("sideEffect", False)):
            evidence = readback_evidence(str(metadata.get("name", "") or ""), args, tool_result)
            if evidence.get("verified"):
                attach_step_evidence(tool_result, evidence)
                return StepVerificationResult(True)
            return StepVerificationResult(
                False,
                "Yan etkili adım için bağımsız kanıt bulunamadı (dosya hash'i, provider ID veya durum readback'i gerekli).",
            )
        output = str(tool_result.get("output", "") or "").strip()
        artifacts = tool_result.get("artifacts", [])
        if output:
            return StepVerificationResult(True)
        if isinstance(result_payload, dict) and result_payload:
            return StepVerificationResult(True)
        if isinstance(artifacts, list) and any(isinstance(item, dict) for item in artifacts):
            return StepVerificationResult(True)
        return StepVerificationResult(False, "Araç sonucu boş döndü.")

    def _persist(
        self,
        *,
        last_execution_at: str = "",
        last_detail: str = "",
        last_ok: bool | None = None,
        last_execution_trace: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "available": True,
            "graphBackend": self._graph_backend,
            "modelRouterBackend": self._model_router_backend,
            "langgraphAvailable": StateGraph is not None,
            "liteLLMAvailable": litellm_adapter.available(),
            "activeExecutionCount": len(self._current),
            "currentExecutions": [dict(item) for item in self._current.values()],
            "lastFallbackReason": self._last_fallback_reason,
            "metrics": dict(self._metrics),
        }
        if last_execution_at:
            payload["lastExecutionAt"] = last_execution_at
        if last_detail:
            payload["lastExecutionDetail"] = _safe_text(last_detail, limit=240)
        if last_ok is not None:
            payload["lastExecutionOk"] = bool(last_ok)
        if isinstance(last_execution_trace, dict):
            payload["lastExecutionTrace"] = dict(last_execution_trace)
        state_store.update_state({"runtime": {"executor": payload}})
