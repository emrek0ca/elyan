from __future__ import annotations

import datetime as dt
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from runtime import state_store
from runtime.capability_registry import capability_metadata, capability_metadata_summary

try:
    from langgraph.graph import END, START, StateGraph
except Exception:  # pragma: no cover - optional dependency
    END = START = None
    StateGraph = None

from runtime import litellm_adapter


def _utc_now_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _safe_text(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


@dataclass(frozen=True)
class StepVerificationResult:
    ok: bool
    message: str = ""


class ExecutorCore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._current: dict[str, dict[str, Any]] = {}
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
        execution_id: str | None = None,
    ) -> str:
        with self._lock:
            active_id = execution_id or f"exec_{uuid.uuid4().hex[:12]}"
            self._current[active_id] = {
                "id": active_id,
                "source": str(source or "runtime"),
                "taskId": str(task_id or "").strip(),
                "conversationId": str(conversation_id or "").strip(),
                "summary": _safe_text(summary),
                "stage": "intake",
                "startedAt": _utc_now_iso(),
                "status": "running",
                "provider": "",
                "model": "",
                "routeReason": "",
                "displayStage": "Bakıyor",
                "displayAction": "Bakıyor",
                "verificationUsed": False,
                "executionStrategy": "balanced",
            }
            self._persist()
            return active_id

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
        with self._lock:
            current = self._current.pop(execution_id, None)
            if current is None:
                return
            if ok:
                self._metrics["completed"] += 1
            else:
                self._metrics["failed"] += 1
            self._persist(last_execution_at=_utc_now_iso(), last_detail=detail, last_ok=ok)

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
            elif any(token in detail for token in ("document_write", "spreadsheet_write", "presentation_write")):
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
                    "executionStrategy": str(active_agent.get("executionStrategy", "balanced") or "balanced"),
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

    def execute_plan_steps(
        self,
        *,
        steps: list[dict[str, Any]],
        state_factory: Callable[[], dict[str, Any]],
        execute_step: Callable[[str, dict[str, Any], dict[str, Any], str], tuple[dict[str, Any], list[dict[str, Any]]]],
        source: str,
        task_id: str = "",
        conversation_id: str = "",
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
        )
        outputs: list[str] = []
        events: list[dict[str, Any]] = []
        error_code = ""
        structured_result: dict[str, Any] | None = None
        artifacts: list[dict[str, Any]] = []
        previous_output = ""
        previous_result: dict[str, Any] | None = None
        previous_artifacts: list[dict[str, Any]] = []

        try:
            self.record_stage(execution_id, "plan_execution", detail="steps")
            for step in steps:
                if not isinstance(step, dict):
                    continue
                capability = str(step.get("capability", "") or "").strip()
                if not capability:
                    continue
                metadata = capability_metadata(capability)
                self.record_stage(execution_id, "step_execution", detail=capability)
                attempt = 0
                while True:
                    attempt += 1
                    args = step.get("args", {})
                    args = dict(args) if isinstance(args, dict) else {}
                    args["_confirmed"] = True
                    args["_retryAttempt"] = attempt
                    if previous_output:
                        args["_previousOutput"] = previous_output
                    if previous_result:
                        args["_previousResult"] = previous_result
                    if previous_artifacts:
                        args["_previousArtifacts"] = list(previous_artifacts)
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
                        self.finish_execution(execution_id, ok=False, detail=message)
                        return False, message, events, error_code, structured_result, artifacts

                    verification = self._verify_step_result(metadata, args, tool_result)
                    if verification.ok:
                        break
                    if not bool(metadata.get("retryable", False)) or attempt >= 2:
                        error_code = "VERIFICATION_FAILED"
                        self.finish_execution(execution_id, ok=False, detail=verification.message)
                        return False, verification.message or "Doğrulama başarısız oldu.", events, error_code, structured_result, artifacts
                    with self._lock:
                        self._metrics["verificationRetries"] += 1
                        self._persist()
                    self.record_stage(execution_id, "retry_repair", detail=f"{capability}:{verification.message}")

                output = str(tool_result.get("output", "") or "").strip()
                if output:
                    outputs.append(output)
                    previous_output = output
                result_payload = tool_result.get("result")
                if isinstance(result_payload, dict):
                    structured_result = dict(result_payload)
                    previous_result = dict(result_payload)
                step_artifacts = tool_result.get("artifacts", [])
                if isinstance(step_artifacts, list):
                    cleaned_artifacts = [item for item in step_artifacts if isinstance(item, dict)]
                    artifacts.extend(cleaned_artifacts)
                    previous_artifacts = cleaned_artifacts

            summary = "\n".join(output for output in outputs if output).strip() or "İşlem tamamlandı."
            self.record_stage(execution_id, "finalize", detail=summary, status="completed")
            self.finish_execution(execution_id, ok=True, detail=summary)
            return True, summary, events, error_code, structured_result, artifacts
        except Exception as exc:  # pragma: no cover - defensive safety net
            message = str(exc) or "executor_plan_failed"
            self.finish_execution(execution_id, ok=False, detail=message)
            return False, message, events, "EXECUTOR_PLAN_FAILED", structured_result, artifacts

    def _verify_step_result(self, metadata: dict[str, Any], args: dict[str, Any], tool_result: dict[str, Any]) -> StepVerificationResult:
        mode = str(metadata.get("verificationMode", "tool_result") or "tool_result")
        if mode == "none":
            return StepVerificationResult(True)
        if mode == "artifact_exists":
            explicit_output = str(args.get("outputPath", "") or args.get("output_path", "") or "").strip()
            if explicit_output and Path(explicit_output).expanduser().exists():
                return StepVerificationResult(True)
            artifacts = tool_result.get("artifacts", [])
            if isinstance(artifacts, list):
                for artifact in artifacts:
                    if not isinstance(artifact, dict):
                        continue
                    path = str(artifact.get("path", "") or "").strip()
                    if path and Path(path).expanduser().exists():
                        return StepVerificationResult(True)
            return StepVerificationResult(False, "Çıktı dosyası doğrulanamadı.")
        output = str(tool_result.get("output", "") or "").strip()
        result_payload = tool_result.get("result")
        artifacts = tool_result.get("artifacts", [])
        if output:
            return StepVerificationResult(True)
        if isinstance(result_payload, dict) and result_payload:
            return StepVerificationResult(True)
        if isinstance(artifacts, list) and any(isinstance(item, dict) for item in artifacts):
            return StepVerificationResult(True)
        return StepVerificationResult(False, "Araç sonucu boş döndü.")

    def _persist(self, *, last_execution_at: str = "", last_detail: str = "", last_ok: bool | None = None) -> None:
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
        state_store.update_state({"runtime": {"executor": payload}})
