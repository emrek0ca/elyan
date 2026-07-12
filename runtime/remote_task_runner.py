from __future__ import annotations

import contextvars
import datetime as dt
import threading
import time
import uuid
from typing import Any

from runtime import state_store
from runtime.agent_planning import build_agent_plan
from runtime.backend_client import BackendResult
from runtime.capability_registry import capability_display_name, capability_readiness
from runtime.desktop_work_order import validate_payload, verify_result


REMOTE_TASK_RUNNER_VERSION = "remote_task_orchestrator_v1"

# Yerel görev yürütmesi için üst sınır: bir yetenek/LLM çağrısı takılırsa
# görev süresiz "running"da kalıp telefonu bekletmesin. Sınır aşılınca terminal
# bir "zaman aşımı" hatası raporlanır (takıldı bildirimi). Sentinel dönüşü ile
# gerçek None (delege→LLM) sonucundan ayrılır.
REMOTE_TASK_EXECUTION_TIMEOUT_SECONDS = 300.0
# Tarayıcı ajanı / operatör gibi uzun soluklu görevler (gözlem-karar turları +
# sayfa beklemeleri) 5 dk'ya sığmaz; bu görevlere geniş bütçe tanınır.
REMOTE_TASK_LONG_EXECUTION_TIMEOUT_SECONDS = 1200.0
_LONG_RUNNING_CAPABILITY_PREFIXES = ("browser_agent.", "browser_session.", "desktop_operator.")
_EXECUTION_TIMEOUT = object()

# Bir görev için üst üste kaç kez netleştirme sorulabilir. Aşılırsa görev
# güvenle sonlandırılır (sonsuz "sor-cevapla-yine sor" döngüsünü önler).
MAX_CLARIFICATION_ROUNDS = 2

# Mobil "dispatch" açık kullanıcı iradesidir: iş emrinin bildirdiği yeteneklerle
# sınırlı planlar ikinci onaya düşmeden yürütülür. Bu küme istisnadır — geri
# alınamaz / dışa dönük işlemler her zaman açık onay ister.
DISPATCH_AUTO_APPROVE_BLOCKLIST = {
    "email_send",
    "shell_run",
    "file_delete",
    "delete_calendar_event",
    "send_whatsapp_message",
    "save_whatsapp_contact",
    "mcp_call_tool",
    "desktop_operator.run",
    "desktop_operator.execute_action",
}
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


def _desktop_work_order_summary(work_order: dict[str, Any] | None) -> str:
    work_order = work_order if isinstance(work_order, dict) else {}
    goal = work_order.get("goal")
    goal = goal if isinstance(goal, dict) else {}
    return _safe_text(goal.get("summary"), 1000)


def _desktop_work_order_topic(work_order: dict[str, Any] | None) -> str:
    work_order = work_order if isinstance(work_order, dict) else {}
    entities = work_order.get("entities")
    if not isinstance(entities, list):
        return ""
    for entity in entities:
        if not isinstance(entity, dict) or str(entity.get("type", "") or "").strip() != "topic":
            continue
        topic = _safe_text(entity.get("value"), 4000)
        if topic:
            return topic
    return ""


def _normalize_capability(value: Any) -> str:
    text = " ".join(str(value or "").strip().lower().split())
    return text.replace(" ", "_")


def _safe_error_code(value: Any, fallback: str = "REMOTE_TASK_FAILED") -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return fallback
    return "".join(ch if ch.isalnum() else "_" for ch in raw)[:80] or fallback


_MISSING_EVIDENCE_LABELS = {
    "chat_result": "görünür bir sonuç mesajı",
    "artifact": "üretilen dosya",
    "file_update": "dosya güncellemesi",
    "browser_state": "tarayıcıda gerçekleşen etki",
    "system_state": "sistemde gerçekleşen etki",
    "runtime_status": "çalışma durumu",
    "tool_result": "araç sonucu",
    "state_readback": "gerçek durum gözlemi",
}


def _human_missing_evidence_labels(missing: Any) -> list[str]:
    """verify_result'ın 'output:browser_state' / 'rule:x' kimliklerini kullanıcıya
    okunur etikete çevirir; bilinmeyenleri ham bırakmak yerine atlar."""
    labels: list[str] = []
    for item in missing if isinstance(missing, list) else []:
        raw = str(item or "")
        key = raw.split(":", 1)[1] if ":" in raw else raw
        label = _MISSING_EVIDENCE_LABELS.get(key)
        if label and label not in labels:
            labels.append(label)
    return labels


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

    # Bu süreçte gerçekten yürütülüyor olabilecek durumlar; daemon yeni
    # başladıysa bunlarda kalmış bir görev kesinlikle yarıda kalmıştır.
    _EXECUTING_STATUSES = frozenset({"planning", "readiness_check", "running", "verifying", "repairing", "unknown"})

    def sweep_interrupted_tasks(self) -> int:
        """Daemon (yeniden) başladığında bir kez: yerel gelen kutusunda
        'yürütülüyor' görünen görevler bu süreçte çalışmıyordur — backend'e
        dürüstçe failed raporla, yerelde de kapat. Tepside/mobilde sonsuza dek
        'çalışıyor' görünen hayalet görevleri bitirir."""
        inbox = state_store.get_task_inbox()
        items = inbox.get("items", []) if isinstance(inbox, dict) else []
        swept = 0
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", "") or "").strip().lower()
            if status not in self._EXECUTING_STATUSES:
                continue
            task_id = str(item.get("id", "") or "").strip()
            if not task_id:
                continue
            task_run_id = str(item.get("taskRunId", "") or "").strip() or self._ensure_task_run_id(task_id)
            message = (
                "Görev, masaüstü uygulaması yeniden başladığı için yarıda kaldı. "
                "Lütfen tekrar gönderin."
            )
            try:
                self._fail_safe(
                    task_id,
                    task_run_id,
                    message=message,
                    error_code="task_interrupted_by_restart",
                )
            except Exception:
                pass
            self._upsert_local_task(task_id, status="failed", summary=message)
            swept += 1
        if swept:
            self.host._runtime_diag("interrupted_task_sweep", count=swept)
        return swept

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
                    resolution_answer = self._approval_resolution_notes(approval_request)
                    if resolution_state == "approved":
                        executions.append(self.resume_after_approval(task_id, True, resolution_answer))
                    elif resolution_state == "rejected":
                        executions.append(self.resume_after_approval(task_id, False))
                    elif self._dispatch_consent_covers_pending_link(task_id):
                        # Mobil dispatch onayı bekleyen planı zaten kapsıyor —
                        # (ör. eski sürümde onaya takılmış görev) otomatik sürdür.
                        executions.append(self.resume_after_approval(task_id, True))
                    else:
                        executions.append({"taskId": task_id, "ok": True, "status": "waiting_approval"})
                    continue
                executions.append(self.execute_runtime_task(task, dispatched_via_websocket=False))
            finally:
                self.host._clear_assigned_task_inflight(task_id)

        return {"ok": True, "executions": executions, "fetched": len(tasks)}

    def execute_runtime_task(
        self,
        task: dict[str, Any],
        dispatched_via_websocket: bool = False,
        *,
        prompt_override: str = "",
    ) -> dict[str, Any]:
        task_id = str(task.get("id", "") or "").strip()
        payload = task.get("payload", {})
        payload = payload if isinstance(payload, dict) else {}
        work_order_validation = validate_payload(payload)
        if work_order_validation.errors:
            task_run_id = self._ensure_task_run_id(task_id)
            first_error = work_order_validation.errors[0]
            return self._fail_safe(
                task_id,
                task_run_id,
                message="Görev verisi doğrulanamadı. İşlem güvenli şekilde durduruldu.",
                error_code=first_error.get("code", "WORK_ORDER_INVALID"),
                result_status="failed_closed",
            )
        work_order = work_order_validation.work_order
        title = str(task.get("title", "") or payload.get("title", "") or "Elyan görevi")
        prompt = str(
            _desktop_work_order_topic(work_order)
            or payload.get("prompt", "")
            or _desktop_work_order_summary(work_order)
            or payload.get("message", "")
            or title
        ).strip()
        # Netleştirme sürdürmesi: orijinal görev + kullanıcı yanıtı birleşik
        # prompt olarak gelir; work-order konusundan türetilen prompt'u ezer.
        if str(prompt_override or "").strip():
            prompt = str(prompt_override).strip()
        # Codex modeli: kullanıcı mobil composer'dan "plan modu" seçtiyse
        # metadata.planMode=true gelir → önce plan önizlemesi + onay, sonra
        # adım adım. Seçmediyse doğrudan adım adım yürüt (yalnız blocklist onar).
        mobile_metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        plan_mode = bool(mobile_metadata.get("planMode", False))
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
                    unavailable={
                        "capability": readiness_error.get("capability", ""),
                        "displayName": readiness_error.get("displayName", ""),
                        "degradationReason": readiness_error.get("degradationReason", ""),
                    },
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

        # Canlı adım-adım ilerleme: yürütme boyunca aktif görevi bağlama koy —
        # executor her adım geçişinde backend'e canlı 'running' güncellemesi akıtır.
        progress_token = self.host._begin_active_remote_task(task_id, task_run_id)
        try:
            local_result = self._execute_local_with_timeout(
                task, prompt, title, task_id=task_id, plan_mode=plan_mode
            )
            if local_result is _EXECUTION_TIMEOUT:
                return self._fail_safe(
                    task_id,
                    task_run_id,
                    message=(
                        "Görev zaman aşımına uğradı ve takıldı "
                        f"({int(self._execution_timeout_for(task))} sn); güvenle durduruldu."
                    ),
                    error_code="task_execution_timeout",
                    plan_preview=plan_preview,
                    capability_readiness_payload=readiness,
                )
            local_result = self._augment_local_result(
                local_result,
                task_id=task_id,
                task_run_id=task_run_id,
                plan_preview=plan_preview,
                capability_readiness_payload=readiness,
            )
            # Netleştirme: planlayıcı eksik bilgi için soru döndürdüyse görevi
            # sonlandırmadan DURAKLAT (waiting_approval transport'u) ve soruyu
            # telefona taşı; kullanıcı yanıtı (notes) gelince kaldığı yerden
            # yeniden planlayıp yürüt.
            if self._is_clarification_result(local_result):
                return self._pause_for_clarification(
                    task_id,
                    task_run_id,
                    title,
                    prompt,
                    local_result,
                    dispatched_via_websocket,
                    task=task,
                    work_order=work_order,
                )
            if local_result.get("needsConfirmation") is True and str(local_result.get("pendingPlanId", "") or "").strip():
                # Plan modu VEYA geri-alınamaz (blocklist) adım → plan önizlemesi
                # + kullanıcı onayı. Aksi halde (doğrudan mod, zararsız plan)
                # work-order şeklinden bağımsız hemen adım adım yürüt.
                if plan_mode or self._plan_touches_blocklist(local_result):
                    return self._pause_for_approval(
                        task_id,
                        task_run_id,
                        title,
                        local_result,
                        dispatched_via_websocket,
                        work_order=work_order,
                    )
                auto_result = self._auto_approve_dispatched_plan(task_id, task_run_id, local_result)
                if auto_result is None:
                    return self._pause_for_approval(
                        task_id,
                        task_run_id,
                        title,
                        local_result,
                        dispatched_via_websocket,
                        work_order=work_order,
                    )
                local_result = self._augment_local_result(
                    auto_result,
                    task_id=task_id,
                    task_run_id=task_run_id,
                    plan_preview=plan_preview,
                    capability_readiness_payload=readiness,
                )

            self._report_lifecycle(
                task_id,
                task_run_id,
                "verifying",
                "Görev sonucu doğrulanıyor.",
                task=task,
                plan_preview=local_result.get("planPreview") if isinstance(local_result.get("planPreview"), dict) else plan_preview,
                capability_readiness_payload=readiness,
            )
            if work_order is not None:
                local_result = self._apply_work_order_verification(work_order, local_result)
            result = self.host._report_runtime_task_terminal_result(
                task_id,
                local_result,
                dispatched_via_websocket=dispatched_via_websocket,
            )
            self._mark_link_terminal(task_id, result.get("status", "completed"))
            return result
        finally:
            self.host._end_active_remote_task(progress_token, task_id)
            self.host._set_runtime_task_heartbeat(dispatched_via_websocket, "idle")

    def _execute_local_with_timeout(
        self, task: dict[str, Any], prompt: str, title: str, *, task_id: str, plan_mode: bool = False
    ) -> Any:
        """Yerel yürütmeyi kopyalanmış context içinde bir worker thread'de koşar
        ve zaman aşımı uygular. Context kopyası, canlı ilerleme emitter'ının
        (contextvar tabanlı) worker içinde de doğru göreve yönlenmesini sağlar
        (bkz. _begin_active_remote_task). Zaman aşımında _EXECUTION_TIMEOUT döner;
        worker daemon olduğundan terk edilir — geç biten terminal güncellemeler
        backend'de dedup/geçiş kuralıyla elenir. `_execute_deterministic_remote_task`
        None dönerse (LLM'e delege) gerçek None korunur, sentinel'la karışmaz."""
        box: dict[str, Any] = {}

        def _worker() -> None:
            try:
                # Plan modunda deterministik hız-yolunu atla: LLM planlayıcı
                # her görev için (tek adım bile) plan önizlemesi + onay üretsin.
                result = None
                if not plan_mode:
                    result = self.host._execute_deterministic_remote_task(task, prompt, title)
                if result is None:
                    result = self.host.send_conversation("", prompt, title, plan_mode=plan_mode)
                box["result"] = result
            except BaseException as exc:  # yürütme hatası ana thread'e taşınır
                box["error"] = exc

        ctx = contextvars.copy_context()
        worker = threading.Thread(
            target=lambda: ctx.run(_worker),
            name=f"elyan-task-exec-{str(task_id)[:8]}",
            daemon=True,
        )
        worker.start()
        worker.join(self._execution_timeout_for(task))
        if worker.is_alive():
            self.host._runtime_diag("task_execution_timeout", task_id=task_id)
            return _EXECUTION_TIMEOUT
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def _execution_timeout_for(self, task: dict[str, Any]) -> float:
        """Görev tarayıcı ajanı/operatör içeriyorsa uzun bütçe, aksi halde standart."""
        try:
            payload = task.get("payload", {}) if isinstance(task, dict) else {}
            payload = payload if isinstance(payload, dict) else {}
            capabilities = self.host._remote_task_capabilities(task, payload)
        except Exception:
            capabilities = set()
        for capability in capabilities:
            name = str(capability or "")
            if name.startswith(_LONG_RUNNING_CAPABILITY_PREFIXES):
                return REMOTE_TASK_LONG_EXECUTION_TIMEOUT_SECONDS
        return REMOTE_TASK_EXECUTION_TIMEOUT_SECONDS

    def resume_after_approval(self, task_id: str, approved: bool, answer: str = "") -> dict[str, Any]:
        link = state_store.get_remote_task_link(task_id)
        # Netleştirme duraklaması onay değildir: kullanıcı yanıtıyla (answer)
        # kaldığı yerden yeniden planla.
        if isinstance(link, dict) and bool(link.get("clarificationPending")):
            task_run_id = str(link.get("taskRunId", "") or "").strip() or self._ensure_task_run_id(task_id)
            return self._resume_after_clarification(task_id, task_run_id, link, approved, answer)

        if not approved:
            self.host._cancel_remote_pending_task(task_id)
            self._mark_link_terminal(task_id, "canceled")
            return {"taskId": task_id, "ok": True, "status": "canceled"}

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
        stored_work_order = link.get("desktopWorkOrder")
        work_order: dict[str, Any] | None = None
        if stored_work_order is not None:
            validation = validate_payload({"desktopWorkOrder": stored_work_order})
            if validation.errors or validation.work_order is None:
                first_error = validation.errors[0] if validation.errors else {"code": "WORK_ORDER_INVALID"}
                return self._fail_safe(
                    task_id,
                    task_run_id,
                    message="Onaylanan görevin tipli verisi doğrulanamadı. İşlem güvenli şekilde durduruldu.",
                    error_code=first_error.get("code", "WORK_ORDER_INVALID"),
                    result_status="failed_closed",
                )
            work_order = validation.work_order
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

        progress_token = self.host._begin_active_remote_task(task_id, task_run_id)
        try:
            self._report_lifecycle(task_id, task_run_id, "repairing", "Onaylanan adım yürütülüyor.")
            local_result = self.host._run_with_approved_task_access(
                task_id,
                lambda: self.host.confirm_conversation_plan(conversation_id, pending_plan_id, True),
            )
            local_result = self._augment_local_result(local_result, task_id=task_id, task_run_id=task_run_id)
            self._report_lifecycle(task_id, task_run_id, "verifying", "Görev sonucu doğrulanıyor.")
            if work_order is not None:
                local_result = self._apply_work_order_verification(work_order, local_result)
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
            self.host._end_active_remote_task(progress_token, task_id)
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
            display = capability_display_name(capability)
            code = _safe_error_code(item.get("errorCode"), "CAPABILITY_NOT_READY")
            degradation = str(item.get("degradationReason", "") or "").strip().lower()
            if code == "DEPENDENCY_UNAVAILABLE" and capability.startswith("quantum_"):
                code = "QUANTUM_DEPENDENCY_UNAVAILABLE"
            # Kullanıcı-dostu, net "kullanılamıyor" mesajı — ham slug yerine
            # dostane ad + sebep. Sessizce patlamaz; ne yapılamadığı açık.
            if code == "UNSUPPORTED_PLATFORM":
                message = f"{display} bu işletim sisteminde desteklenmiyor."
            elif code == "OS_PERMISSION_REQUIRED":
                message = f"{display} için işletim sistemi izni gerekiyor. İzin verip tekrar dene."
            elif code == "QUANTUM_DEPENDENCY_UNAVAILABLE":
                message = f"{display} için gerekli bağımlılık (Qiskit/Aer) bu masaüstünde kurulu değil."
            else:
                message = f"{display} şu an kullanılamıyor: gerekli bileşen bu masaüstünde hazır değil."
            return {
                "code": code,
                "message": message,
                "capability": capability,
                "displayName": display,
                "degradationReason": degradation or code.lower(),
            }
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
            # Yerel gelen kutusu (tepsi menüsü + CLI) anlamlı bir ad görsün:
            # başlık yoksa kullanıcının görev metni başlık olur.
            task_payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
            title = _safe_text(
                task.get("title", "")
                or task_payload.get("title", "")
                or task_payload.get("prompt", "")
                or task_payload.get("message", ""),
                200,
            )
            if title:
                payload["title"] = title
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
        unavailable: dict[str, Any] | None = None,
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
        # Graceful degrade: yetenek kullanılamıyorsa yapılandırılmış blok +
        # sonuç alanı — mobil "X şu an kullanılamıyor" kartını net gösterir.
        if isinstance(unavailable, dict) and str(unavailable.get("displayName", "") or "").strip():
            payload["result"]["capabilityUnavailable"] = dict(unavailable)
            payload["result"]["blocks"] = [
                {
                    "type": "capability_unavailable",
                    "capability": str(unavailable.get("capability", "") or ""),
                    "displayName": str(unavailable.get("displayName", "") or ""),
                    "reason": str(unavailable.get("degradationReason", "") or ""),
                    "message": message,
                },
                *(payload["result"].get("blocks", []) if isinstance(payload["result"].get("blocks"), list) else []),
            ]
        report = self.host._report_runtime_task_status(task_id, payload)
        self._mark_link_terminal(task_id, "failed_safe")
        return {
            "taskId": task_id,
            "ok": False,
            "status": result_status,
            "report": report.to_dict() if report else None,
        }

    def _dispatch_consent_covers_plan(
        self,
        work_order: dict[str, Any] | None,
        local_result: dict[str, Any],
    ) -> bool:
        """Mobil dispatch onayı bu planı kapsıyor mu?

        Mobil "dispatch" hedefe açık kullanıcı iradesidir. Güvenlik sınırı
        blocklist'tir (geri alınamaz / dışa dönük işlemler — e-posta gönder,
        shell, dosya sil, WhatsApp, mcp, operator.run): bunlar dispatch'te bile
        açık onay ister. Bunun dışındaki yerel adımlar (uygulama aç/kapat,
        belge/tablo/sunum yaz, tarayıcı, medya…) otomatik yürütülür — plan
        LLM tarafından üretilip iş emrinin bildirdiği yeteneklerden farklı bir
        (yine zararsız) yetenek seçse de kullanıcıyı gereksiz onaya takmayız.
        """
        if not isinstance(work_order, dict):
            return False
        execution = work_order.get("execution")
        execution = execution if isinstance(execution, dict) else {}
        source = str(work_order.get("source", "") or "").strip().lower()
        mode = str(execution.get("mode", "") or "").strip().lower()
        if source != "mobile_chat_dispatch" and mode != "cowork_dispatch":
            return False

        plan_preview = local_result.get("planPreview")
        steps = plan_preview.get("steps", []) if isinstance(plan_preview, dict) else []
        plan_capabilities = {
            _normalize_capability(step.get("capability"))
            for step in steps
            if isinstance(step, dict) and _normalize_capability(step.get("capability"))
        }
        if not plan_capabilities:
            return False
        return not (plan_capabilities & DISPATCH_AUTO_APPROVE_BLOCKLIST)

    @staticmethod
    def _plan_touches_blocklist(local_result: dict[str, Any]) -> bool:
        """Plan, geri-alınamaz/dışa dönük (blocklist) bir yetenek içeriyor mu?

        Doğrudan modda bile bu adımlar açık onay ister (mail gönder, shell,
        dosya sil, WhatsApp, mcp, operator.run…).
        """
        plan_preview = local_result.get("planPreview")
        steps = plan_preview.get("steps", []) if isinstance(plan_preview, dict) else []
        plan_capabilities = {
            _normalize_capability(step.get("capability"))
            for step in steps
            if isinstance(step, dict) and _normalize_capability(step.get("capability"))
        }
        return bool(plan_capabilities & DISPATCH_AUTO_APPROVE_BLOCKLIST)

    def _dispatch_consent_covers_pending_link(self, task_id: str) -> bool:
        """Bekleyen (waiting_approval) görevin kayıtlı linki üzerinden aynı
        dispatch-kapsam kontrolü — yeniden başlatma/eski sürümden kalan
        takılı görevler için."""
        link = state_store.get_remote_task_link(task_id)
        if not isinstance(link, dict):
            return False
        work_order = link.get("desktopWorkOrder")
        pending_plan_id = str(link.get("pendingPlanId", "") or "").strip()
        if not isinstance(work_order, dict) or not pending_plan_id:
            return False
        plan = state_store.get_pending_plan(pending_plan_id)
        if not isinstance(plan, dict):
            return False
        plan_preview = plan.get("planPreview")
        if not isinstance(plan_preview, dict):
            plan_preview = {"steps": plan.get("steps", [])}
        return self._dispatch_consent_covers_plan(work_order, {"planPreview": plan_preview})

    def _auto_approve_dispatched_plan(
        self,
        task_id: str,
        task_run_id: str,
        local_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Dispatch onayı kapsamındaki planı hemen yürüt; olmazsa None (onaya düş)."""
        pending_plan_id = str(local_result.get("pendingPlanId", "") or "").strip()
        conversation_id = str(local_result.get("conversationId", "") or "").strip()
        permission_error = self.host._pending_plan_permission_error(pending_plan_id)
        if permission_error is not None:
            return None
        self._report_lifecycle(
            task_id,
            task_run_id,
            "running",
            "Mobil dispatch onayı planı kapsıyor — adımlar otomatik yürütülüyor.",
        )
        approved = self.host._run_with_approved_task_access(
            task_id,
            lambda: self.host.confirm_conversation_plan(conversation_id, pending_plan_id, True),
        )
        if not isinstance(approved, dict):
            return None
        return approved

    def _pause_for_approval(
        self,
        task_id: str,
        task_run_id: str,
        title: str,
        local_result: dict[str, Any],
        dispatched_via_websocket: bool,
        *,
        work_order: dict[str, Any] | None = None,
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
        if work_order is not None:
            state_store.update_remote_task_link(task_id, {"desktopWorkOrder": dict(work_order)})
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

    @staticmethod
    def _approval_resolution_notes(approval_request: dict[str, Any]) -> str:
        """Onay çözümündeki serbest-metin yanıtı (netleştirme cevabı) çıkarır."""
        request = approval_request if isinstance(approval_request, dict) else {}
        resolution = request.get("resolution", {})
        resolution = resolution if isinstance(resolution, dict) else {}
        for key in ("notes", "answer", "response", "text"):
            value = str(resolution.get(key, "") or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _is_clarification_result(local_result: Any) -> bool:
        """Planlayıcı sonucu, yürütülecek adım yerine netleştirme sorusu mu?"""
        if not isinstance(local_result, dict):
            return False
        if str(local_result.get("clarificationQuestion", "") or "").strip() == "":
            return False
        if bool(local_result.get("clarificationNeeded")):
            return True
        return str(local_result.get("executionMode", "") or "").strip().lower() == "clarification"

    def _pause_for_clarification(
        self,
        task_id: str,
        task_run_id: str,
        title: str,
        prompt: str,
        local_result: dict[str, Any],
        dispatched_via_websocket: bool,
        *,
        task: dict[str, Any] | None = None,
        work_order: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        question = str(local_result.get("clarificationQuestion", "") or "").strip()
        link = state_store.get_remote_task_link(task_id)
        link = link if isinstance(link, dict) else {}
        rounds = int(link.get("clarificationRounds", 0) or 0)
        # Döngü koruması: sıfırdan çok tur netleştirme çözüm getirmiyorsa
        # güvenle sonlandır (soruyu tekrarlayarak).
        if rounds >= MAX_CLARIFICATION_ROUNDS:
            state_store.remove_remote_task_link(task_id)
            return self._fail_safe(
                task_id,
                task_run_id,
                message=f"Netleştirme çözülemedi: {question}",
                error_code="clarification_unresolved",
            )

        # Soruyu onay transport'uyla telefona taşı — mobil approvalRequest'i
        # (kind=clarification) soru metniyle gösterir; kullanıcı yanıtı
        # onay 'notes'u olarak geri gelir.
        approval_request = {
            "id": f"{task_id}_clarification",
            "taskId": task_id,
            "kind": "clarification",
            "title": "Netleştirme gerekli",
            "message": question,
            "summary": question,
            "confirmLabel": "Yanıtla",
            "rejectLabel": "İptal",
        }
        # Orijinal prompt yalnız İLK turda saklanır; sonraki turlarda korunur.
        original_prompt = str(link.get("clarificationPrompt", "") or "").strip() or prompt
        state_store.save_remote_task_link(
            task_id,
            str(link.get("pendingPlanId", "") or ""),
            str(local_result.get("conversationId", "") or link.get("conversationId", "") or ""),
            title=title,
            status="waiting_approval",
            task_run_id=task_run_id,
            remote_task_id=task_id,
            last_backend_status="waiting_approval",
        )
        link_patch: dict[str, Any] = {
            "clarificationPending": True,
            "clarificationPrompt": original_prompt,
            "clarificationQuestion": question,
            "clarificationRounds": rounds + 1,
        }
        if task is not None:
            link_patch["clarificationTask"] = task
        if work_order is not None:
            link_patch["desktopWorkOrder"] = dict(work_order)
        state_store.update_remote_task_link(task_id, link_patch)

        clarification_block = {
            "type": "clarification",
            "taskId": task_id,
            "question": question,
        }
        waiting_result = {
            "assistantMessage": question,
            "conversationId": str(local_result.get("conversationId", "") or ""),
            "taskRunId": task_run_id,
            "approvalRequest": approval_request,
            "clarificationQuestion": question,
            "blocks": [clarification_block],
        }
        payload = self._status_payload(
            task_id,
            task_run_id,
            status="waiting_approval",
            message=question,
            approval_request=approval_request,
        )
        payload["summary"] = question or payload["summary"]
        payload["result"] = {**payload["result"], **waiting_result}
        report = self.host._report_runtime_task_status(task_id, payload)
        self.host._set_runtime_task_heartbeat(dispatched_via_websocket, "idle")
        return {
            "taskId": task_id,
            "ok": bool(report and report.ok),
            "status": "waiting_approval",
            "clarification": True,
            "report": report.to_dict() if report else None,
        }

    def _resume_after_clarification(
        self,
        task_id: str,
        task_run_id: str,
        link: dict[str, Any],
        approved: bool,
        answer: str,
    ) -> dict[str, Any]:
        if not approved:
            self.host._cancel_remote_pending_task(task_id)
            self._mark_link_terminal(task_id, "canceled")
            return {"taskId": task_id, "ok": True, "status": "canceled"}

        answer = str(answer or "").strip()
        question = str(link.get("clarificationQuestion", "") or "").strip()
        if not answer:
            # Mobil henüz serbest-metin yanıtı göndermiyorsa (yalnız 'onayla'),
            # net cevap olmadan döngüye sokmadan güvenle sonlandır; soruyu
            # tekrarla ki kullanıcı daha net bir görev gönderebilsin.
            state_store.remove_remote_task_link(task_id)
            return self._fail_safe(
                task_id,
                task_run_id,
                message=f"Netleştirme yanıtı alınamadı: {question}",
                error_code="clarification_unanswered",
            )

        stored_task = link.get("clarificationTask")
        if not isinstance(stored_task, dict):
            state_store.remove_remote_task_link(task_id)
            return self._fail_safe(
                task_id,
                task_run_id,
                message="Netleştirilen görevin bağlamı bulunamadı. Görev güvenle durduruldu.",
                error_code="clarification_context_missing",
            )
        original_prompt = str(link.get("clarificationPrompt", "") or "").strip()
        combined_prompt = (
            f"{original_prompt}\n\nKullanıcının netleştirmesi: {answer}"
            if original_prompt
            else answer
        )
        # clarificationPending'i temizle ama tur sayacını KORU (tekrar
        # netleştirilirse döngü koruması çalışsın).
        state_store.update_remote_task_link(task_id, {"clarificationPending": False})
        return self.execute_runtime_task(stored_task, prompt_override=combined_prompt)

    def _apply_work_order_verification(
        self,
        work_order: dict[str, Any],
        local_result: dict[str, Any],
    ) -> dict[str, Any]:
        result = dict(local_result)
        verification = verify_result(work_order, result)
        result["verification"] = verification
        trace = result.get("executionTrace")
        if isinstance(trace, dict):
            trace = dict(trace)
            trace["verificationState"] = verification
            result["executionTrace"] = trace
        if verification.get("passed") is not True:
            # Yürütme zaten dürüst, somut bir hatayla bittiyse ("YouTube bu
            # bilgisayarda bulunamadı" gibi) o mesajı kanıt jargonuyla EZME —
            # kullanıcı gerçek nedeni görsün; doğrulama kaydı yine eklendi.
            existing_error = result.get("error") if isinstance(result.get("error"), dict) else {}
            existing_message = str(
                existing_error.get("message", "")
                or (result.get("assistantMessage", "") if result.get("chatOk") is False else "")
                or ""
            ).strip()
            if result.get("chatOk") is False and existing_message:
                return result
            unverified = [
                str(name) for name in verification.get("unverifiedSideEffects", []) if str(name or "").strip()
            ]
            if unverified:
                # Somut dürüstlük: iddia edilip gözlenemeyen yan etkiyi adıyla söyle.
                labels = ", ".join(dict.fromkeys(unverified))
                message = (
                    f"Görev denendi ama etkisi doğrulanamadı ({labels}). "
                    "Gerçekten gerçekleştiği teyit edilemediği için tamamlandı olarak işaretlenmedi."
                )
                error_code = "WORK_ORDER_SIDE_EFFECT_UNVERIFIED"
            else:
                # Teknik jargon değil, insanca: neyin doğrulanamadığını söyle.
                missing_labels = _human_missing_evidence_labels(
                    verification.get("missingEvidence", [])
                )
                detail = f" Doğrulanamayan: {', '.join(missing_labels)}." if missing_labels else ""
                message = (
                    "Görevi çalıştırdım ama sonucun gerçekten oluştuğunu "
                    f"doğrulayamadım; bu yüzden tamamlandı demiyorum.{detail}"
                )
                error_code = "WORK_ORDER_EVIDENCE_MISSING"
            result["chatOk"] = False
            result["assistantMessage"] = message
            result["error"] = {"code": error_code, "message": message}
        return result

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
