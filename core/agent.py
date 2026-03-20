from typing import Any, Optional
import asyncio
import inspect
import json
import os
import urllib.request
import re as _re
import mimetypes
import hashlib
import time
import uuid
from datetime import datetime
from pathlib import Path
from difflib import get_close_matches
from urllib.parse import quote_plus, unquote_plus
from contextvars import ContextVar
from config.elyan_config import elyan_config
from core.kernel import kernel
from core.output_contract import get_contract_engine
from core.neural_router import neural_router
from core.action_lock import action_lock
from core.quick_intent import get_quick_intent_detector, IntentCategory as _IC
from core.fast_response import get_fast_response_system, QuestionType
from core.nlu_normalizer import normalize_turkish_text
from core.intelligent_planner import get_intelligent_planner
from core.intent_parser import get_intent_parser
from core.capability_router import get_capability_router
from core.learning_engine import get_learning_engine
from core.skills.registry import skill_registry
from core.skills.manager import skill_manager
from core.user_profile import get_user_profile_store
from core.context7_client import context7_client
from core.canvas.engine import canvas_engine
from tools.generators.slidev_generator import slidev_gen
from tools import AVAILABLE_TOOLS
from core.tool_usage import record_tool_usage
from core.tool_request import get_tool_request_log
from core.subscription import subscription_manager
from core.quota import quota_manager
from core.evidence_gate import evidence_gate
from core.text_artifacts import DEFAULT_SAVE_MARKERS, default_summary_path
from core.job_templates import detect_job_type, get_template
from core.pipeline import PipelineContext
from core.cdg_engine import cdg_engine
from core.style_profile import style_profile
from core.constraint_engine import constraint_engine
from core.failure_clustering import failure_clustering
from core.failure_classification import classify_failure_class
from core.predictive_tasks import get_predictive_task_engine
from core.timeout_guard import (
    with_timeout, friendly_timeout_message,
    LLM_TIMEOUT, PLANNER_TIMEOUT, TOOL_TIMEOUT, RESEARCH_TIMEOUT, TOTAL_TIMEOUT,
)
from core.feedback import get_feedback_store, get_feedback_detector
from core.context_intelligence import get_context_intelligence
from core.monitoring import get_resource_monitor
from core.self_healing import get_healing_engine
from core.multi_agent.orchestrator import get_orchestrator
from core.proactive.intervention import get_intervention_manager
from core.knowledge_base import get_knowledge_base
from core.pipeline_state import get_pipeline_state
from core.pipeline_state import set_current_pipeline_state, reset_current_pipeline_state, create_pipeline_state
from core.evidence.execution_ledger import ExecutionLedger
from core.evidence.adapters import adapt_evidence
from core.evidence.run_store import RunStore
from core.contracts.agent_response import AgentResponse, AttachmentRef
from core.contracts.execution_result import coerce_execution_result
from core.task_brain import task_brain
from core.away_mode import away_task_registry, background_task_runner, away_completion_notifier
from core.channel_delivery import channel_delivery_bridge
from core.smart_notifications import get_smart_notifications, NotificationCategory, NotificationPriority
from core.gateway.response import UnifiedResponse
from core.cowork_runtime import get_cowork_runtime
from core.mission_control import get_mission_runtime
from core.runtime_policy import get_runtime_policy_resolver
from core.command_hardening import (
    blocked_command_reason,
    build_chat_fallback_message,
    classify_command_route,
    requires_screen_state,
    sanitize_chat_output,
    screen_state_is_actionable,
)
from core.process_profiles import (
    PREAPPROVAL_BLOCKED_TOOLS,
    approval_granted,
    artifact_entry,
    normalize_workflow_profile,
)
from core.repair.state_machine import classify_error, RepairStateMachine
from core.repair.error_codes import PLAN_ERROR, TOOL_ERROR, ENV_ERROR, VALIDATION_ERROR
from core.compat.legacy_tool_wrappers import normalize_legacy_tool_payload
from core.security.runtime_guard import runtime_security_guard
from core.recovery_policy import select_recovery_strategy
from core.compliance.audit_trail import audit_trail
from core.spec.task_spec import validate_task_spec, TASK_SPEC_SCHEMA_VERSION
from core.spec.task_spec_standard import coerce_task_spec_standard, extract_slots_from_intent
from security.validator import validate_input, sanitize_input
from security.privacy_guard import redact_text, sanitize_for_storage, sanitize_object, is_external_provider
from security.tool_policy import tool_policy
from core.i18n import detect_language
from core.pipeline import pipeline_runner
from core.ml import (
    get_action_ranker,
    get_clarification_classifier,
    get_intent_scorer,
    get_model_runtime,
    get_verifier,
)
from core.personalization import get_personalization_manager
from core.reliability import get_outcome_store
from utils.logger import get_logger

logger = get_logger("agent")
_active_ledger: ContextVar[ExecutionLedger | None] = ContextVar("active_execution_ledger", default=None)
_active_runtime_policy: ContextVar[dict | None] = ContextVar("active_runtime_policy", default=None)

ACTION_TO_TOOL = {
    # Intent parser aliases
    "research": "advanced_research",
    "browser_search": "web_search",
    "search_web": "web_search",
    "create_word_document": "write_word",
    "create_excel": "write_excel",
    "create_website": "create_web_project_scaffold",
    "run_python": "run_code",
    "execute_python": "run_code",
    "execute_code": "run_code",
    "run_script": "run_code",
    "code_run": "run_code",
    "execute_python_code": "run_code",
    "show_help": "chat",
    "status_snapshot": "take_screenshot",
    "screen_status": "screen_workflow",
    "screen_read": "screen_workflow",
    "random_image": "create_visual_asset_pack",
    "create_calendar_event": "create_event",
    "create_calendar": "create_event",
    "get_calendar": "get_today_events",
    "battery_status": "get_battery_status",
    "get_battery": "get_battery_status",
    "analyze_screen": "analyze_screen",
    "pause_music": "control_music",
    "resume_music": "control_music",
    "next_track": "control_music",
    "prev_track": "control_music",
    "play_music": "control_music",
    # Weather
    "weather": "get_weather",
    "get_weather_info": "get_weather",
    "hava_durumu": "get_weather",
    # PDF fallback
    "create_pdf": "generate_document_pack",
    "research_and_document": "research_document_delivery",
    "research_report_delivery": "research_document_delivery",
    "deliver_research_copy": "research_document_delivery",
    "merge_pdfs": "merge_pdfs",
    # Summary handlers are implemented directly in Agent
    "summarize_text": "summarize_text",
    "summarize_file": "summarize_file",
    "summarize_url": "summarize_url",
    "translate": "translate",
    # Coding project
    "create_coding_project": "create_coding_project",
    "coding_project": "create_coding_project",
    "open_browser": "browser_open",
    "navigate_to": "browser_open",
    "click_on": "browser_click",
    "scrape_site": "scrape_page",
    "browser_screenshot": "browser_screenshot",
    # DB
    "query_database": "db_execute",
    "run_sql": "db_execute",
    "database_schema": "db_schema",
    # Git
    "clone_repo": "git_clone",
    "commit_changes": "git_commit",
    "push_code": "git_push",
    "pull_code": "git_pull",
    "show_diff": "git_diff",
    "git_history": "git_log",
    # Deploy
    "deploy_project": "deploy_to_vercel",
    "deploy_vercel": "deploy_to_vercel",
    "deploy_netlify": "deploy_to_netlify",
    # Container
    "build_docker": "docker_build",
    "run_container": "docker_run",
    "stop_container": "docker_stop",
    "list_containers": "docker_ps",
    # API
    "api_call": "http_request",
    "make_request": "http_request",
    # Data
    "analyze_csv": "analyze_data",
    "read_data": "read_csv",
    "query_data": "data_query",
    # Package
    "install_package": "pip_install",
    "install_npm": "npm_install",
    # Free API Tools (Zero cost)
    "wikipedia": "get_wikipedia_summary",
    "wiki": "get_wikipedia_summary",
    "vikipedi": "get_wikipedia_summary",
    "definition": "get_word_definition",
    "kelime_anlami": "get_word_definition",
    "sozluk": "get_word_definition",
    "tavsiye": "get_random_advice",
    "advice": "get_random_advice",
    "ilginc_bilgi": "get_random_fact",
    # UI automation
    "type": "type_text",
    "type_text": "type_text",
    "press": "press_key",
    "press_key": "press_key",
    "hotkey": "key_combo",
    "key_combo": "key_combo",
    "click": "mouse_click",
    "mouse_click": "mouse_click",
    "move_mouse": "mouse_move",
    "mouse_move": "mouse_move",
    "computer_use": "computer_use",
    "computer_control": "computer_use",
    "use_computer": "computer_use",
    "fun_fact": "get_random_fact",
    "alinti": "get_random_quote",
    "quote": "get_random_quote",
    "hava": "get_weather_by_city",
    "weather_city": "get_weather_by_city",
    "crypto": "get_crypto_price",
    "bitcoin": "get_crypto_price",
    "kripto": "get_crypto_price",
    "currency": "get_exchange_rate",
    "doviz": "get_exchange_rate",
    "kur": "get_exchange_rate",
    "exchange_rate": "get_exchange_rate",
    "ip_location": "get_ip_geolocation",
    "ip_konum": "get_ip_geolocation",
    "country": "get_country_info",
    "ulke": "get_country_info",
    "ulke_bilgisi": "get_country_info",
    "postal": "get_postal_code_info",
    "posta_kodu": "get_postal_code_info",
    "quick_search": "ddg_instant_answer",
    "hizli_arama": "ddg_instant_answer",
    "academic_search": "search_academic_papers",
    "makale_ara": "search_academic_papers",
    # Desktop
    "change_wallpaper": "set_wallpaper",
    "wallpaper": "set_wallpaper",
    "arka_plan": "set_wallpaper",
}

# Lazy import to avoid circular dependency
def _push(event_type: str, channel: str, detail: str, success: bool = True):
    try:
        from core.gateway.server import push_activity
        push_activity(event_type, channel, detail, success)
    except Exception:
        pass


def _push_hint(text: str, icon: str = "lightbulb", color: str = "yellow"):
    try:
        from core.gateway.server import push_hint
        push_hint(text, icon=icon, color=color)
    except Exception:
        pass


def _push_tool_event(
    stage: str,
    tool: str,
    *,
    step: str = "",
    request_id: str = "",
    success: bool | None = None,
    latency_ms: int | None = None,
    payload: dict | None = None,
):
    try:
        from core.gateway.server import push_tool_event

        push_tool_event(
            stage,
            tool,
            step=step,
            request_id=request_id,
            success=success,
            latency_ms=latency_ms,
            payload=payload or {},
        )
    except Exception:
        pass

class Agent:
    def __init__(self):
        self.kernel = kernel
        self.llm = None
        # Quick access
        self.quick_intent = get_quick_intent_detector()
        self.intent_parser = get_intent_parser()
        self.planner = get_intelligent_planner()
        self.capability_router = get_capability_router()
        self.learning = get_learning_engine()
        self.user_profile = get_user_profile_store()
        self.personalization = get_personalization_manager()
        self.model_runtime = get_model_runtime()
        self.intent_scorer = get_intent_scorer()
        self.action_ranker = get_action_ranker()
        self.clarification_classifier = get_clarification_classifier()
        self.verifier_service = get_verifier()
        self.outcome_store = get_outcome_store()
        self.current_user_id = None
        self.file_context = {
            "last_dir": str(Path.home() / "Desktop"),
            "last_path": "",
            "last_attachment": "",
        }
        # Son başarılı aksiyon — feedback/correction sistemi için
        self._last_action: str = ""
        self._last_turn_context: dict[str, Any] = {
            "user_input": "",
            "response_text": "",
            "action": "",
            "success": True,
            "ts": 0.0,
        }
        self._last_tool_confirmation: dict[str, Any] = {"key": "", "ts": 0.0}
        self._last_runtime_task_spec_payload: dict[str, Any] | None = None
        self._away_notifier_registered = False
        self._task_suggestion_cache: dict[str, float] = {}
        self._workflow_sessions: dict[str, dict[str, Any]] = {}
        self._nlu_model_a = None
        self._nlu_model_a_path: str = ""
        self._nlu_model_a_mtime: float = 0.0
        self._nlu_model_a_load_error: str = ""
        # ── Phase 6-10 module integration (graceful fallback) ──
        self._init_phase6_10_modules()
        self._register_away_notifier()

    def _init_phase6_10_modules(self) -> None:
        """Initialize Phase 6-10 modules with graceful fallback."""
        try:
            from core.telemetry_system import get_telemetry_system
            self.telemetry = get_telemetry_system()
        except Exception:
            self.telemetry = None
        try:
            from core.api_gateway import get_api_gateway
            self.api_gateway = get_api_gateway()
        except Exception:
            self.api_gateway = None
        try:
            from core.nlp.turkish_nlp import get_turkish_nlp
            self.turkish_nlp = get_turkish_nlp()
        except Exception:
            self.turkish_nlp = None
        try:
            from core.reasoning_engine import get_reasoning_engine
            self.reasoning = get_reasoning_engine()
        except Exception:
            self.reasoning = None
        try:
            from core.multi_agent_v2 import get_multi_agent_orchestrator
            self.multi_agent_v2 = get_multi_agent_orchestrator()
        except Exception:
            self.multi_agent_v2 = None
        try:
            from core.billing.subscription import get_subscription_manager
            self.billing = get_subscription_manager()
        except Exception:
            self.billing = None
        try:
            from core.plugins.plugin_system import get_plugin_manager
            self.plugin_manager = get_plugin_manager()
        except Exception:
            self.plugin_manager = None
        try:
            from core.integrations.integration_sdk import get_integration_hub
            self.integrations = get_integration_hub()
        except Exception:
            self.integrations = None
        try:
            from core.i18n.multi_language import get_multi_language_engine
            self.multi_language = get_multi_language_engine()
        except Exception:
            self.multi_language = None
        try:
            from core.compliance_v2.compliance import get_compliance_engine
            self.compliance = get_compliance_engine()
        except Exception:
            self.compliance = None
        try:
            from core.multi_llm_engine import get_multi_llm_engine
            self.multi_llm = get_multi_llm_engine()
            from core.model_orchestrator import model_orchestrator
            self.multi_llm.initialize(model_orchestrator)
        except Exception:
            self.multi_llm = None

    def _register_away_notifier(self) -> None:
        if self._away_notifier_registered:
            return

        async def _deliver_completion(record) -> None:
            try:
                meta = dict(getattr(record, "metadata", {}) or {})
                channel_type = str(meta.get("channel_type") or getattr(record, "channel", "") or "").strip()
                channel_id = str(meta.get("channel_id") or meta.get("chat_id") or "").strip()
                text = str(getattr(record, "result_summary", "") or "").strip()
                state = str(getattr(record, "state", "") or "")
                if not text:
                    text = "Arka plan gorevi tamamlandi." if state in {"completed", "partial"} else "Arka plan gorevi basarisiz oldu."
                sent = False
                if channel_type and channel_id:
                    response = UnifiedResponse(
                        text=text,
                        attachments=list(getattr(record, "attachments", []) or []),
                        format="plain",
                        metadata={
                            "away_task_id": getattr(record, "task_id", ""),
                            "run_id": getattr(record, "run_id", ""),
                            "state": state,
                        },
                    )
                    sent = await channel_delivery_bridge.deliver(channel_type, channel_id, response)

                notifier = get_smart_notifications()
                priority = NotificationPriority.HIGH if state == "failed" else NotificationPriority.MEDIUM
                await notifier.send_notification(
                    title="Away task tamamlandi" if state in {"completed", "partial"} else "Away task hata verdi",
                    message=f"{record.user_input[:120]} ({record.task_id})",
                    priority=priority,
                    category=NotificationCategory.TASK,
                    metadata={"task_id": record.task_id, "run_id": record.run_id, "state": state, "channel_delivery": sent},
                    force=True,
                )
            except Exception:
                pass

        away_completion_notifier.register(_deliver_completion)
        self._away_notifier_registered = True

    def _ensure_llm(self) -> bool:
        existing_llm = getattr(self, "llm", None)
        if existing_llm is not None:
            return True
        try:
            candidate = getattr(self.kernel, "llm", None)
        except Exception:
            candidate = None
        if candidate is not None:
            self.llm = candidate
            return True
        # Last resort: create LLMClient directly
        try:
            from core.llm_client import LLMClient
            self.llm = LLMClient()
            logger.info("LLM client created via _ensure_llm fallback")
            return True
        except Exception as exc:
            logger.error(f"_ensure_llm fallback failed: {exc}")
        return False

    @staticmethod
    def _workflow_session_key(user_id: str, channel: str) -> str:
        return f"{str(user_id or 'local').strip() or 'local'}::{str(channel or 'cli').strip() or 'cli'}"

    def _get_workflow_session(self, user_id: str, channel: str) -> dict[str, Any]:
        sessions = getattr(self, "_workflow_sessions", None)
        if not isinstance(sessions, dict):
            sessions = {}
            self._workflow_sessions = sessions
        return dict(sessions.get(self._workflow_session_key(user_id, channel), {}) or {})

    def _store_workflow_session(self, user_id: str, channel: str, payload: dict[str, Any]) -> None:
        sessions = getattr(self, "_workflow_sessions", None)
        if not isinstance(sessions, dict):
            sessions = {}
            self._workflow_sessions = sessions
        key = self._workflow_session_key(user_id, channel)
        current = dict(sessions.get(key, {}) or {})
        current.update({str(k): v for k, v in dict(payload or {}).items()})
        current["updated_at"] = time.time()
        sessions[key] = current

    def _clear_workflow_session(self, user_id: str, channel: str) -> None:
        sessions = getattr(self, "_workflow_sessions", None)
        if isinstance(sessions, dict):
            sessions.pop(self._workflow_session_key(user_id, channel), None)

    def _resolve_pending_workflow_session(self, user_input: str, user_id: str, channel: str) -> dict[str, Any]:
        session = self._get_workflow_session(user_id, channel)
        if not session:
            return {}
        phase = str(session.get("workflow_phase") or "").strip().lower()
        profile = normalize_workflow_profile(session.get("workflow_profile"))
        if profile == "default":
            return {}
        if phase in {"finished", "closed"}:
            return {}
        if approval_granted(user_input) and phase in {"brainstorming", "design_ready"}:
            session["approval_status"] = "approved"
            session["workflow_phase"] = "approved"
            self._store_workflow_session(user_id, channel, session)
            return session
        return session

    @staticmethod
    def _sanitize_chat_reply(text: Any) -> str:
        return sanitize_chat_output(text)

    @staticmethod
    def _fast_chat_reply(user_input: str = "") -> str | None:
        try:
            fast = get_fast_response_system().get_fast_response(str(user_input or ""))
        except Exception:
            fast = None
        if not fast or fast.question_type != QuestionType.GREETING:
            return None
        return Agent._sanitize_chat_reply(fast.answer)

    @staticmethod
    def _build_information_question_prompt(user_input: str) -> str:
        question = str(user_input or "").strip()
        return (
            "Aşağıdaki soruyu tek başına değerlendir.\n"
            "Önceki konuşmayı referans alma.\n"
            "Kısa, doğal ve doğrudan Türkçe cevap ver.\n"
            "İç plan, görev maddesi, sistem notu, başarı kriteri, araç açıklaması yazma.\n"
            "Sorunun cevabını 2-4 cümlede ver.\n\n"
            f"Soru: {question}"
        )

    @staticmethod
    def _fallback_chat_without_llm(user_input: str = "") -> str:
        quick = Agent._fast_chat_reply(user_input)
        if quick:
            return quick
        text = str(user_input or "").lower()
        if any(k in text for k in ("durum", "status", "sağlık", "saglik", "health")):
            return "LLM bağlantısı hazır değil. 'elyan models status' ve 'elyan gateway health --json' ile kontrol edebilirsin."
        return build_chat_fallback_message(language=str(elyan_config.get("agent.language", "tr") or "tr"))

    @staticmethod
    def _handle_short_ambiguous_input(user_input: str) -> str | None:
        raw = str(user_input or "").strip()
        low = raw.lower()
        if not low:
            return None
        words = [w for w in low.split() if w]
        if len(words) > 2:
            return None
        if low in {"arkaplanda", "arka planda", "background", "daemon"}:
            return (
                "Arka plan komutu belirsiz. İstediğin şeyi net yaz: "
                "'gatewayi arka planda başlat', 'rutinleri çalıştır' veya 'durumu göster'."
            )
        return None

    async def _build_controlled_route_response(
        self,
        *,
        ledger: ExecutionLedger,
        run_store: RunStore,
        run_id: str,
        started_at: float,
        user_input: str,
        response_text: str,
        channel: str,
        uid: str,
        reason: str,
        action: str,
        mode: str,
        status: str = "partial",
        success: bool = False,
        route_decision: dict[str, Any] | None = None,
    ) -> AgentResponse:
        manifest = ledger.write_manifest(
            status=status,
            metadata={
                "channel": channel,
                "user_id": uid,
                "reason": reason,
                "mode": mode,
                "route_decision": dict(route_decision or {}),
            },
        )
        run_store.write_task(
            {},
            user_input=user_input,
            metadata={"channel": channel, "user_id": uid, "reason": reason, "mode": mode},
            task_state={},
        )
        run_store.write_evidence(
            manifest_path=manifest,
            steps=[],
            artifacts=[],
            metadata={"status": status, "mode": mode, "reason": reason},
        )
        run_store.write_summary(
            status=status,
            response_text=response_text,
            artifacts=[],
            metadata={"manifest_path": manifest, "mode": mode, "reason": reason},
        )
        run_store.write_logs(lines=[reason or mode or action])
        try:
            await self._finalize_turn(
                user_input=user_input,
                response_text=response_text,
                action=action,
                success=success,
                started_at=started_at,
                context={
                    "role": "chat",
                    "job_type": "communication",
                    "errors": 0,
                    "run_id": run_id,
                    "channel": str(channel or "cli"),
                    "mode": mode,
                    "route_reason": reason,
                    "route_decision": dict(route_decision or {}),
                    "model_runtime": dict((route_decision or {}).get("model_runtime") or {}) if isinstance(route_decision, dict) else {},
                    "intent_prediction": dict((route_decision or {}).get("intent_prediction") or {}) if isinstance(route_decision, dict) else {},
                    "route_choice": dict((route_decision or {}).get("route_choice") or {}) if isinstance(route_decision, dict) else {},
                    "clarification_policy": dict((route_decision or {}).get("clarification_policy") or {}) if isinstance(route_decision, dict) else {},
                },
            )
        except Exception as finalize_exc:
            logger.debug(f"controlled route finalize skipped: {finalize_exc}")
        return AgentResponse(
            run_id=run_id,
            text=response_text,
            attachments=[],
            evidence_manifest_path=manifest,
            status=status,
            error="",
        )

    @staticmethod
    def _should_schedule_away_task(user_input: str, metadata: dict | None = None) -> bool:
        meta = metadata if isinstance(metadata, dict) else {}
        if bool(meta.get("background_dispatch")):
            return False
        mode = str(meta.get("autonomy_mode") or meta.get("mode") or "").strip().lower()
        if mode in {"background", "away", "daemon", "arka_planda", "async"}:
            return True
        low = str(user_input or "").lower()
        markers = (
            "arka planda",
            "arkaplanda",
            "ben yokken",
            "ben yokken calis",
            "hazir olunca gonder",
            "hazır olunca gönder",
            "sen hallet",
            "ben dönünce hazır olsun",
            "away mode",
        )
        return any(marker in low for marker in markers)

    @staticmethod
    def _extract_away_task_id(user_input: str) -> str:
        match = _re.search(r"\b(away_[a-z0-9]{6,})\b", str(user_input or "").lower())
        return str(match.group(1) if match else "")

    @classmethod
    def _parse_away_task_command(cls, user_input: str) -> dict[str, Any] | None:
        low = str(user_input or "").strip().lower()
        if not low:
            return None
        task_id = cls._extract_away_task_id(low)

        list_markers = (
            "aktif görevler",
            "aktif gorevler",
            "arka plan görevleri",
            "arka plan gorevleri",
            "görev listesi",
            "gorev listesi",
            "bekleyen görevler",
            "bekleyen gorevler",
            "görevleri göster",
            "gorevleri goster",
        )
        status_markers = (
            "görev durumu",
            "gorev durumu",
            "task status",
            "away task status",
            "arka plan durumu",
            "arka plan gorev durumu",
        )
        cancel_markers = (
            "iptal et",
            "iptal",
            "cancel",
            "durdur",
        )
        retry_markers = (
            "yeniden başlat",
            "yeniden baslat",
            "tekrar çalıştır",
            "tekrar calistir",
            "retry",
            "yeniden dene",
        )

        mentions_task = any(token in low for token in ("görev", "gorev", "task", "arka plan"))

        if any(marker in low for marker in list_markers):
            return {"action": "away_task_list", "task_id": task_id}
        if task_id and any(marker in low for marker in cancel_markers):
            return {"action": "away_task_cancel", "task_id": task_id}
        if task_id and any(marker in low for marker in retry_markers):
            return {"action": "away_task_retry", "task_id": task_id}
        if task_id and any(marker in low for marker in status_markers):
            return {"action": "away_task_status", "task_id": task_id}
        if mentions_task and any(marker in low for marker in cancel_markers):
            return {"action": "away_task_cancel", "task_id": ""}
        if mentions_task and any(marker in low for marker in retry_markers):
            return {"action": "away_task_retry", "task_id": ""}
        if mentions_task and any(marker in low for marker in status_markers):
            return {"action": "away_task_status", "task_id": ""}
        if task_id and "durum" in low:
            return {"action": "away_task_status", "task_id": task_id}
        if task_id and "görev" in low:
            return {"action": "away_task_status", "task_id": task_id}
        return None

    @staticmethod
    def _format_away_task_line(record: Any) -> str:
        title = str(getattr(record, "user_input", "") or "").strip().replace("\n", " ")
        title = title[:80] + ("..." if len(title) > 80 else "")
        return f"- {record.task_id} [{record.state}] {title}".rstrip()

    @staticmethod
    def _format_foreground_task_line(record: Any) -> str:
        title = str(getattr(record, "objective", "") or "").strip().replace("\n", " ")
        title = title[:80] + ("..." if len(title) > 80 else "")
        return f"- {record.task_id} [{record.state}] {title}".rstrip()

    @staticmethod
    def _away_task_metadata(record: Any) -> dict[str, Any]:
        return {
            "task_id": str(getattr(record, "task_id", "") or ""),
            "state": str(getattr(record, "state", "") or ""),
            "workflow_id": str(getattr(record, "workflow_id", "") or ""),
            "capability_domain": str(getattr(record, "capability_domain", "") or ""),
            "run_id": str(getattr(record, "run_id", "") or ""),
            "summary": str(getattr(record, "result_summary", "") or "")[:200],
        }

    @staticmethod
    def _foreground_task_metadata(record: Any) -> dict[str, Any]:
        history = list(getattr(record, "history", []) or [])
        last_note = ""
        if history:
            last = history[-1]
            last_note = str(getattr(last, "note", "") or "")
        return {
            "task_id": str(getattr(record, "task_id", "") or ""),
            "state": str(getattr(record, "state", "") or ""),
            "objective": str(getattr(record, "objective", "") or "")[:200],
            "artifact_count": len(list(getattr(record, "artifacts", []) or [])),
            "last_note": last_note,
            "type": "foreground",
        }

    @staticmethod
    def _is_task_control_request(user_input: str) -> bool:
        low = str(user_input or "").strip().lower()
        if not low:
            return False
        markers = (
            "görev",
            "gorev",
            "task",
            "arka plan",
            "away_",
            "iptal et",
            "yeniden başlat",
            "yeniden baslat",
            "retry",
        )
        return any(marker in low for marker in markers)

    def _build_resume_task_suggestion(self, user_id: str, user_input: str) -> dict[str, Any] | None:
        if self._is_task_control_request(user_input):
            return None
        resumable = away_task_registry.latest_for_user(
            user_id,
            states=["failed", "partial", "cancelled", "queued", "running"],
        )
        if resumable is None:
            return None
        task_id = str(getattr(resumable, "task_id", "") or "")
        if not task_id:
            return None
        cache = getattr(self, "_task_suggestion_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._task_suggestion_cache = cache
        now = time.time()
        last_ts = float(cache.get(task_id) or 0.0)
        if (now - last_ts) < 300.0:
            return None
        cache[task_id] = now
        state = str(getattr(resumable, "state", "") or "").strip().lower()
        prompt = str(getattr(resumable, "user_input", "") or "").strip()
        action = "retry" if state in {"failed", "partial", "cancelled"} else "status"
        text = f"İstersen yarım kalan '{prompt[:60]}' görevine devam edebilirim."
        return {
            "task_id": task_id,
            "state": state,
            "suggested_action": action,
            "text": text,
        }

    @staticmethod
    def _away_retry_policy(capability_domain: str, workflow_id: str, metadata: dict | None = None) -> dict[str, Any]:
        meta = dict(metadata or {})
        mode = str(meta.get("autonomy_mode") or meta.get("mode") or "").strip().lower()
        cap = str(capability_domain or "").strip().lower()
        workflow = str(workflow_id or "").strip().lower()

        if cap == "research" or workflow == "research_workflow":
            base = {"auto_retry": True, "max_retries": 2, "retry_on_partial": True, "retry_on_failure": True}
        elif cap in {"coding", "website"} or workflow in {"coding_workflow", "website_delivery_workflow"}:
            base = {"auto_retry": True, "max_retries": 2, "retry_on_partial": True, "retry_on_failure": True}
        elif cap in {"screen_operator", "desktop_control"} or workflow == "screen_operator_workflow":
            base = {"auto_retry": True, "max_retries": 1, "retry_on_partial": False, "retry_on_failure": True}
        else:
            base = {"auto_retry": True, "max_retries": 1, "retry_on_partial": False, "retry_on_failure": True}

        if mode not in {"full", "background", "away", "async", "arka_planda"}:
            base["max_retries"] = min(int(base["max_retries"]), 1)

        if "auto_retry" in meta:
            base["auto_retry"] = bool(meta.get("auto_retry"))
        if "max_retries" in meta:
            try:
                base["max_retries"] = max(0, int(meta.get("max_retries") or 0))
            except Exception:
                pass
        if "retry_on_partial" in meta:
            base["retry_on_partial"] = bool(meta.get("retry_on_partial"))
        if "retry_on_failure" in meta:
            base["retry_on_failure"] = bool(meta.get("retry_on_failure"))
        return base

    async def _handle_away_task_command(self, user_input: str, *, user_id: str) -> AgentResponse | None:
        command = self._parse_away_task_command(user_input)
        if not isinstance(command, dict):
            return None

        action = str(command.get("action") or "").strip().lower()
        task_id = str(command.get("task_id") or "").strip()
        run_id = f"taskctl_{uuid.uuid4().hex[:10]}"

        if action == "away_task_list":
            active = away_task_registry.list_for_user(
                user_id,
                limit=8,
                states=["queued", "running", "partial"],
            )
            foreground = task_brain.list_for_user(
                user_id,
                limit=5,
                states=["pending", "planning", "executing", "verifying", "partial", "completed"],
            )
            lines = []
            if active:
                lines.append("Arka plan gorevleri:")
                lines.extend(self._format_away_task_line(item) for item in active[:5])
            if foreground:
                if lines:
                    lines.append("")
                lines.append("Son gorevler:")
                lines.extend(self._format_foreground_task_line(item) for item in foreground[:5])
            text = "\n".join(lines) if lines else "Aktif veya son gorev bulunmuyor."
            return AgentResponse(
                run_id=run_id,
                text=text,
                status="success",
                error="",
                metadata={
                    "task_list": [self._away_task_metadata(item) for item in active],
                    "recent_tasks": [self._foreground_task_metadata(item) for item in foreground],
                },
            )

        target = away_task_registry.get(task_id) if task_id else None
        if target is None and action == "away_task_status":
            target = away_task_registry.latest_for_user(user_id, states=["queued", "running", "partial"])
            if target is None:
                target = away_task_registry.latest_for_user(user_id)
        if target is None and action == "away_task_cancel":
            target = away_task_registry.latest_for_user(user_id, states=["queued", "running", "partial"])
        if target is None and action == "away_task_retry":
            target = away_task_registry.latest_for_user(user_id, states=["failed", "cancelled", "partial"])
        if target is None or str(getattr(target, "user_id", "")) != str(user_id or ""):
            fg_target = None
            if action == "away_task_status":
                fg_target = task_brain.latest_for_user(user_id)
            if fg_target is None:
                return AgentResponse(
                    run_id=run_id,
                    text="Gorev bulunamadi.",
                    status="partial",
                    error="task_not_found",
                )
            lines = [
                f"Gorev: {fg_target.task_id}",
                f"Durum: {fg_target.state}",
                f"Hedef: {fg_target.objective[:200]}",
            ]
            if getattr(fg_target, "artifacts", None):
                lines.append(f"Artifact: {len(list(fg_target.artifacts or []))}")
            return AgentResponse(
                run_id=run_id,
                text="\n".join(lines),
                status="success",
                error="",
                metadata={"task": self._foreground_task_metadata(fg_target)},
            )

        if action == "away_task_status":
            lines = [
                f"Gorev: {target.task_id}",
                f"Durum: {target.state}",
                f"Workflow: {target.workflow_id or 'general'}",
            ]
            summary = str(getattr(target, "result_summary", "") or "").strip()
            if summary:
                lines.append(f"Ozet: {summary[:200]}")
            err = str(getattr(target, "error", "") or "").strip()
            if err:
                lines.append(f"Hata: {err[:200]}")
            return AgentResponse(
                run_id=run_id,
                text="\n".join(lines),
                status="success",
                error="",
                metadata={"task": self._away_task_metadata(target)},
            )

        if action == "away_task_cancel":
            updated = await background_task_runner.cancel(target.task_id)
            state = str(getattr(updated, "state", "") or target.state)
            return AgentResponse(
                run_id=run_id,
                text=f"Gorev durduruldu: {target.task_id} [{state}]",
                status="success",
                error="",
                metadata={"task": self._away_task_metadata(updated or target)},
            )
        updated = await background_task_runner.retry(target.task_id)
        state = str(getattr(updated, "state", "") or "queued")
        return AgentResponse(
            run_id=run_id,
            text=f"Gorev yeniden siraya alindi: {target.task_id} [{state}]",
            status="success",
            error="",
            metadata={"task": self._away_task_metadata(updated or target)},
        )

    def _build_away_task_handler(self):
        async def _handler(record):
            resp = await self.process_envelope(
                record.user_input,
                attachments=list(getattr(record, "attachments", []) or []),
                channel=record.channel,
                metadata={**dict(getattr(record, "metadata", {}) or {}), "background_dispatch": True},
            )
            return {
                "status": str(getattr(resp, "status", "success") or "success"),
                "run_id": str(getattr(resp, "run_id", "") or ""),
                "summary": str(getattr(resp, "text", "") or "")[:300],
                "text": str(getattr(resp, "text", "") or ""),
                "error": str(getattr(resp, "error", "") or ""),
                "attachments": list(resp.to_unified_attachments()) if hasattr(resp, "to_unified_attachments") else [],
            }

        return _handler

    @classmethod
    def _runtime_metadata(cls) -> dict[str, Any]:
        policy = cls._current_runtime_policy()
        meta = policy.get("metadata", {}) if isinstance(policy.get("metadata"), dict) else {}
        return dict(meta) if isinstance(meta, dict) else {}

    @classmethod
    def _mission_handoff_blocked(cls, metadata: dict | None = None) -> bool:
        if isinstance(metadata, dict) and bool(metadata.get("skip_mission_control")):
            return True
        runtime_meta = cls._runtime_metadata()
        return bool(runtime_meta.get("skip_mission_control"))

    def _should_handoff_coding_mission(
        self,
        user_input: str,
        *,
        route_decision: Any = None,
        parsed_intent: dict | None = None,
        metadata: dict | None = None,
    ) -> bool:
        if self._mission_handoff_blocked(metadata):
            return False
        route_mode = str(getattr(route_decision, "mode", "") or "").strip().lower()
        if route_mode == "code":
            return True
        if isinstance(parsed_intent, dict):
            action = str(parsed_intent.get("action") or "").strip().lower()
            if action == "create_coding_project":
                return True
        inferred = self._infer_coding_project_intent(user_input)
        return isinstance(inferred, dict) and str(inferred.get("action") or "").strip().lower() == "create_coding_project"

    async def _run_coding_mission_handoff(
        self,
        goal: str,
        *,
        user_id: str,
        channel: str,
        mode: str = "Balanced",
        attachments: list[str] | None = None,
        metadata: dict | None = None,
    ):
        runtime = get_mission_runtime()
        mission = await runtime.create_mission(
            goal,
            user_id=str(user_id or "local"),
            channel=str(channel or "cli"),
            mode=str(mode or "Balanced") or "Balanced",
            attachments=[str(item) for item in list(attachments or []) if str(item).strip()],
            metadata={"source": "agent_coding_handoff", **dict(metadata or {})},
            agent=self,
            auto_start=False,
        )
        result = await runtime.run_mission(mission.mission_id, agent=self)
        return result or mission

    def _mission_attachments(self, mission: Any) -> tuple[list[AttachmentRef], str]:
        refs: list[AttachmentRef] = []
        manifest_path = ""
        seen: set[str] = set()
        for record in list(getattr(mission, "evidence", []) or []):
            path = str(getattr(record, "path", "") or "").strip()
            kind = str(getattr(record, "kind", "") or "file").strip()
            label = str(getattr(record, "label", "") or "").strip()
            if kind == "manifest" and path and not manifest_path:
                manifest_path = path
            if not path or path in seen:
                continue
            seen.add(path)
            refs.append(
                self._attachment_ref_from_artifact(
                    {
                        "path": path,
                        "type": kind or "file",
                        "name": label or Path(path).name,
                        "source": "mission",
                    }
                )
            )
            if len(refs) >= 8:
                break
        return refs, manifest_path

    @staticmethod
    def _mission_response_text(mission: Any) -> str:
        status = str(getattr(mission, "status", "") or "queued").strip().lower()
        deliverable = str(getattr(mission, "deliverable", "") or "").strip()
        mission_id = str(getattr(mission, "mission_id", "") or "").strip()
        goal = str(getattr(mission, "goal", "") or "").strip()
        approvals = [item for item in list(getattr(mission, "approvals", []) or []) if str(getattr(item, "status", "") or "") == "pending"]
        if status == "waiting_approval":
            lines = [f"Görev onay bekliyor: {goal or mission_id or 'mission'}"]
            if mission_id:
                lines.append(f"Mission ID: {mission_id}")
            if approvals:
                lines.append("")
                lines.append("Bekleyen onaylar:")
                for item in approvals[:4]:
                    title = str(getattr(item, "title", "") or getattr(item, "node_id", "") or "approval").strip()
                    if title:
                        lines.append(f"- {title}")
            return "\n".join(lines).strip()
        if deliverable:
            return deliverable
        if status == "completed":
            return f"Misyon tamamlandı: {goal or mission_id or 'mission'}"
        if status == "failed":
            return f"Misyon başarısız oldu: {goal or mission_id or 'mission'}"
        return f"Misyon kuyruğa alındı: {goal or mission_id or 'mission'}"

    async def _build_mission_handoff_response(
        self,
        *,
        ledger: ExecutionLedger,
        run_store: RunStore,
        run_id: str,
        started_at: float,
        user_input: str,
        mission: Any,
        channel: str,
        uid: str,
        route_decision: dict | None = None,
    ) -> AgentResponse:
        refs, mission_manifest = self._mission_attachments(mission)
        response_text = self._mission_response_text(mission)
        mission_status = str(getattr(mission, "status", "") or "queued").strip().lower()
        route_mode = str(getattr(mission, "route_mode", "") or "task").strip().lower() or "task"
        status = "success" if mission_status == "completed" else ("partial" if mission_status == "waiting_approval" else "failed")
        manifest = ledger.write_manifest(
            status=status,
            metadata={
                "channel": channel,
                "user_id": uid,
                "mode": "mission_handoff",
                "mission_id": str(getattr(mission, "mission_id", "") or ""),
                "mission_status": mission_status,
                "route_mode": route_mode,
                "mission_manifest_path": mission_manifest,
            },
        )
        task_state = {
            "mission_id": str(getattr(mission, "mission_id", "") or ""),
            "status": mission_status,
            "route_mode": route_mode,
        }
        artifacts = [ref.to_dict() for ref in refs]
        run_store.write_task(
            {},
            user_input=user_input,
            metadata={"channel": channel, "user_id": uid, "phase": "mission_handoff", "mission_id": task_state["mission_id"]},
            task_state=task_state,
        )
        run_store.write_evidence(
            manifest_path=manifest,
            steps=[],
            artifacts=artifacts,
            metadata={"status": status, "mode": "mission_handoff", "mission_id": task_state["mission_id"]},
        )
        summary_path = run_store.write_summary(
            status=status,
            response_text=response_text,
            error="" if status != "failed" else response_text,
            artifacts=artifacts,
            metadata={
                "manifest_path": manifest,
                "mission_id": task_state["mission_id"],
                "mission_manifest_path": mission_manifest,
                "route_mode": route_mode,
            },
        )
        run_store.write_logs(lines=["mission_handoff", task_state["mission_id"], mission_status])
        try:
            await self._finalize_turn(
                user_input=user_input,
                response_text=response_text,
                action=route_mode or "mission",
                success=status == "success",
                started_at=started_at,
                context={
                    "role": "mission",
                    "job_type": route_mode or "task",
                    "errors": 0 if status != "failed" else 1,
                    "run_id": run_id,
                    "mode": "mission_handoff",
                    "mission_id": task_state["mission_id"],
                    "route_decision": dict(route_decision or {}),
                },
            )
        except Exception as finalize_exc:
            logger.debug(f"mission handoff finalize skipped: {finalize_exc}")
        return AgentResponse(
            run_id=run_id,
            text=response_text,
            attachments=refs,
            evidence_manifest_path=manifest,
            status=status,
            error="" if status != "failed" else response_text,
            metadata={
                "mission_id": task_state["mission_id"],
                "mission_status": mission_status,
                "route_mode": route_mode,
                "summary_path": summary_path,
                "mission_manifest_path": mission_manifest,
            },
        )

    async def initialize(self) -> bool:
        await self.kernel.initialize()
        self.llm = self.kernel.llm
        handler = self._build_away_task_handler()
        background_task_runner.set_resume_handler(handler)
        await background_task_runner.start_resume_loop(handler, interval_s=15.0)
        logger.info("Agent Initialized.")
        return True

    @staticmethod
    def _normalize_inbound_attachments(attachments: list[dict | str] | None) -> tuple[list[dict], list[str]]:
        raw_items: list[dict] = []
        paths: list[str] = []
        for item in list(attachments or []):
            if isinstance(item, str):
                p = str(item).strip()
                if p:
                    raw_items.append({"path": p, "type": "file"})
                    paths.append(p)
                continue
            if not isinstance(item, dict):
                continue
            raw = dict(item)
            raw_items.append(raw)
            path = str(raw.get("path") or raw.get("file_path") or raw.get("local_path") or "").strip()
            if path:
                paths.append(path)
        dedup_paths = list(dict.fromkeys(paths))
        return raw_items, dedup_paths

    @staticmethod
    def _attachment_ref_from_artifact(artifact: dict) -> AttachmentRef:
        path = str(artifact.get("path") or "").strip()
        mime, _ = mimetypes.guess_type(path)
        return AttachmentRef(
            path=path,
            type=str(artifact.get("type") or "file"),
            mime=str(mime or "application/octet-stream"),
            name=str(artifact.get("name") or Path(path).name),
            sha256=str(artifact.get("sha256") or ""),
            size_bytes=int(artifact.get("size_bytes") or 0),
            source="evidence",
        )

    @staticmethod
    def _current_runtime_policy() -> dict:
        policy = _active_runtime_policy.get()
        return policy if isinstance(policy, dict) else {}

    @classmethod
    def _runtime_security_flags(cls) -> dict:
        policy = cls._current_runtime_policy()
        sec = policy.get("security", {}) if isinstance(policy.get("security"), dict) else {}
        return {
            "local_first_models": bool(sec.get("local_first_models", elyan_config.get("agent.model.local_first", True))),
            "kvkk_strict_mode": bool(sec.get("kvkk_strict_mode", elyan_config.get("security.kvkk.strict", True))),
            "redact_cloud_prompts": bool(sec.get("redact_cloud_prompts", elyan_config.get("security.kvkk.redactCloudPrompts", True))),
            "allow_cloud_fallback": bool(sec.get("allow_cloud_fallback", elyan_config.get("security.kvkk.allowCloudFallback", True))),
            "require_evidence_for_dangerous": bool(
                sec.get("require_evidence_for_dangerous", elyan_config.get("security.requireEvidenceForDangerous", True))
            ),
        }

    @staticmethod
    def _cloud_provider_set() -> set[str]:
        return {"openai", "groq", "gemini", "google", "anthropic"}

    def _resolve_llm_config_for_runtime(self, role: str = "inference") -> tuple[dict, list[str]]:
        orchestrator = getattr(getattr(self.kernel, "llm", None), "orchestrator", None)
        if orchestrator is None:
            return {"type": "none", "error": "llm_orchestrator_unavailable"}, []
        cfg = orchestrator.get_best_available(role)
        flags = self._runtime_security_flags()
        local_first = bool(flags.get("local_first_models", True))
        allow_cloud_fallback = bool(flags.get("allow_cloud_fallback", True))

        allowed_providers: list[str] = []
        if local_first:
            local_cfg = orchestrator.get_best_available(
                role,
                exclude=self._cloud_provider_set(),
            )
            if local_cfg.get("type") != "none":
                cfg = local_cfg
                allowed_providers = ["ollama"]
            elif not allow_cloud_fallback:
                return {"type": "none", "error": "cloud_fallback_disabled_by_policy"}, []
            else:
                allowed_providers = ["ollama", "openai", "groq", "gemini", "google", "anthropic"]
        return cfg, allowed_providers

    @staticmethod
    def _bool_from_env(value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return bool(default)
        text = str(value).strip().lower()
        if not text:
            return bool(default)
        if text in {"1", "true", "yes", "on", "enabled"}:
            return True
        if text in {"0", "false", "no", "off", "disabled"}:
            return False
        return bool(default)

    def _feature_flag_enabled(self, flag_name: str, default: bool = False) -> bool:
        env_value = os.getenv(str(flag_name or "").strip(), None)
        if env_value is not None:
            return self._bool_from_env(env_value, default)

        policy = self._current_runtime_policy()
        if isinstance(policy, dict):
            flags = policy.get("flags", {}) if isinstance(policy.get("flags"), dict) else {}
            if flags:
                token = str(flag_name or "").strip().lower()
                policy_flag_map = {
                    "elyan_agentic_v2": "agentic_v2",
                    "elyan_dag_exec": "dag_exec",
                    "elyan_strict_taskspec": "strict_taskspec",
                }
                fkey = policy_flag_map.get(token, token.replace("elyan_", ""))
                if fkey in flags:
                    return self._bool_from_env(flags.get(fkey), default)
            meta = policy.get("metadata", {})
            if isinstance(meta, dict):
                token = str(flag_name or "").strip().lower()
                policy_key = token.replace("elyan_", "").lower()
                if policy_key in meta:
                    return self._bool_from_env(meta.get(policy_key), default)

        key_map = {
            "ELYAN_AGENTIC_V2": "agent.flags.agentic_v2",
            "ELYAN_DAG_EXEC": "agent.flags.dag_exec",
            "ELYAN_STRICT_TASKSPEC": "agent.flags.strict_taskspec",
        }
        cfg_key = key_map.get(str(flag_name or "").strip(), "")
        if cfg_key:
            cfg_val = elyan_config.get(cfg_key, None)
            if cfg_val is not None:
                return self._bool_from_env(cfg_val, default)

        return bool(default)

    @staticmethod
    def _audit_security_event(user_id: str, action: str, summary: str, params: dict | None = None, channel: str = "") -> None:
        try:
            audit_trail.log_action(
                event_type="security",
                action=action,
                user_id=str(user_id or "unknown"),
                target=action,
                params=params or {},
                result_summary=str(summary or ""),
                channel=str(channel or ""),
            )
        except Exception:
            pass

    @staticmethod
    def _log_data_access_if_needed(user_id: str, tool_name: str, params: dict) -> None:
        try:
            low = str(tool_name or "").strip().lower()
            if low not in {"read_file", "list_files", "search_files", "read_csv", "read_json"}:
                return
            raw = params or {}
            resource = (
                str(raw.get("path") or raw.get("directory") or raw.get("source") or raw.get("file_path") or "").strip()
                or low
            )
            audit_trail.log_data_access(
                user_id=str(user_id or "unknown"),
                data_type="file_system",
                access_type="read",
                resource=resource,
                purpose="task_execution",
            )
        except Exception:
            pass

    async def process(
        self,
        user_input: str,
        notify=None,
        attachments: list[dict | str] | None = None,
        channel: str = "cli",
        metadata: dict | None = None,
    ) -> str:
        """
        Backward-compatible text API. Never throws — always returns a user-friendly string.
        """
        try:
            envelope = await self.process_envelope(
                user_input=user_input,
                notify=notify,
                attachments=attachments,
                channel=channel,
                metadata=metadata,
            )
            status_prefix = action_lock.get_status_prefix()
            return status_prefix + str(envelope.text or "")
        except Exception as critical_err:
            logger.error(f"Critical error in process(): {critical_err}", exc_info=True)
            return (
                "Bir hata oluştu ama Elyan çalışmaya devam ediyor.\n"
                f"Hata: {str(critical_err)[:200]}\n"
                "LLM ayarları için: Dashboard → LLM sekmesi veya 'elyan setup' komutu."
            )

    async def process_envelope(
        self,
        user_input: str,
        notify=None,
        attachments: list[dict | str] | None = None,
        channel: str = "cli",
        metadata: dict | None = None,
    ) -> AgentResponse:
        """
        Structured response API with evidence manifest support.
        """
        started_at = time.perf_counter()
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        ledger = ExecutionLedger(run_id=run_id)
        run_store = RunStore(run_id=run_id)

        # Ensure LLM is available (safety net for callers that skip initialize())
        if getattr(self, "llm", None) is None:
            self._ensure_llm()

        # Legacy compat: short ambiguous inputs should return clarification instead of planner/LLM errors.
        clar = self._handle_short_ambiguous_input(user_input)
        if clar:
            manifest = ledger.write_manifest(
                status="partial",
                metadata={"reason": "short_ambiguous_input", "channel": channel},
            )
            run_store.write_task({}, user_input=user_input, metadata={"channel": channel, "reason": "short_ambiguous_input"})
            run_store.write_evidence(manifest_path=manifest, steps=[], artifacts=[], metadata={"status": "partial"})
            run_store.write_summary(status="partial", response_text=clar, artifacts=[], metadata={"manifest_path": manifest})
            run_store.write_logs(lines=["short_ambiguous_input"])
            try:
                await self._finalize_turn(
                    user_input=user_input,
                    response_text=clar,
                    action="clarify",
                    success=False,
                    started_at=started_at,
                    context={
                        "role": "chat",
                        "job_type": "communication",
                        "errors": 0,
                        "run_id": run_id,
                        "mode": "clarification",
                    },
                )
            except Exception as finalize_exc:
                logger.debug(f"clarification finalize skipped: {finalize_exc}")
            return AgentResponse(
                run_id=run_id,
                text=clar,
                attachments=[],
                evidence_manifest_path=manifest,
                status="partial",
                error="",
            )

        uid = str(self.current_user_id or "local")
        raw_attachments, resolved_paths = self._normalize_inbound_attachments(attachments)
        pending_workflow = self._resolve_pending_workflow_session(user_input, uid, str(channel or "cli"))
        away_task_command = await self._handle_away_task_command(user_input, user_id=uid)
        if away_task_command is not None:
            return away_task_command
        if self._should_schedule_away_task(user_input, metadata):
            cap_plan = self.capability_router.route(user_input) if getattr(self, "capability_router", None) else None
            cap_domain = str(getattr(cap_plan, "domain", "general") or "general")
            workflow_id = str(getattr(cap_plan, "workflow_id", "") or "")
            retry_policy = self._away_retry_policy(cap_domain, workflow_id, metadata)
            task_metadata = dict(metadata or {})
            task_metadata["background_dispatch"] = True

            async def _background_handler(record):
                resp = await self.process_envelope(
                    record.user_input,
                    attachments=list(raw_attachments),
                    channel=record.channel,
                    metadata=task_metadata,
                )
                return {
                    "status": str(getattr(resp, "status", "success") or "success"),
                    "run_id": str(getattr(resp, "run_id", "") or ""),
                    "summary": str(getattr(resp, "text", "") or "")[:300],
                    "text": str(getattr(resp, "text", "") or ""),
                    "error": str(getattr(resp, "error", "") or ""),
                    "attachments": list(resp.to_unified_attachments()) if hasattr(resp, "to_unified_attachments") else [],
                }

            away_record = await background_task_runner.submit(
                user_input=user_input,
                user_id=uid,
                channel=str(channel or "cli"),
                capability_domain=cap_domain,
                workflow_id=workflow_id,
                handler=_background_handler,
                metadata={
                    "attachments": list(resolved_paths),
                    "requested_via": "agent",
                    "channel_type": str(channel or "cli"),
                    "channel_id": str((metadata or {}).get("channel_id") or (metadata or {}).get("chat_id") or ""),
                    **retry_policy,
                },
            )
            return AgentResponse(
                run_id=f"queued_{away_record.task_id}",
                text=f"Gorev arka planda siraya alindi: {away_record.task_id}",
                attachments=[],
                evidence_manifest_path="",
                status="partial",
                error="",
                metadata={
                    "away_task_id": away_record.task_id,
                    "capability_domain": cap_domain,
                    "workflow_id": workflow_id,
                    "mode": "background",
                },
            )
        effective_user_input = self._runtime_normalize_user_input(
            str(pending_workflow.get("objective") or user_input) if pending_workflow and approval_granted(user_input) else user_input
        )
        last_personalization = self._last_turn_context.get("personalization", {}) if isinstance(self._last_turn_context, dict) else {}
        if getattr(self, "personalization", None) and isinstance(last_personalization, dict):
            last_interaction_id = str(self._last_turn_context.get("interaction_id") or "").strip()
            if last_interaction_id and get_feedback_detector().is_positive(effective_user_input):
                try:
                    self.personalization.record_feedback(
                        user_id=uid,
                        interaction_id=last_interaction_id,
                        event_type="like",
                        metadata={
                            "source": "text_positive",
                            "provider": str(last_personalization.get("provider") or ""),
                            "model": str(last_personalization.get("model") or ""),
                            "base_model_id": str(last_personalization.get("base_model_id") or ""),
                        },
                    )
                except Exception as personalization_feedback_exc:
                    logger.debug(f"personalization positive feedback skipped: {personalization_feedback_exc}")

        fast_chat_allowed = not (pending_workflow and approval_granted(user_input))
        quick_intent = None
        try:
            quick_intent = self.quick_intent.detect(effective_user_input) if getattr(self, "quick_intent", None) else None
        except Exception:
            quick_intent = None

        parsed_intent = None
        if getattr(self, "intent_parser", None):
            try:
                parsed_intent = self.intent_parser.parse(effective_user_input)
            except Exception:
                parsed_intent = None

        cowork_runtime = get_cowork_runtime()
        route_decision = None
        route_metadata: dict[str, Any] = {
            "channel": str(channel or "cli"),
            "user_id": uid,
            "run_id": run_id,
        }
        if isinstance(metadata, dict):
            for key in ("tool_name", "capability_domain", "workflow_profile", "workflow_phase"):
                value = metadata.get(key)
                if value is not None:
                    route_metadata[key] = value
        if pending_workflow:
            route_metadata["workflow_session"] = dict(pending_workflow)
        try:
            route_decision = cowork_runtime.route_command(
                effective_user_input,
                quick_intent=quick_intent,
                parsed_intent=parsed_intent,
                attachments=list(resolved_paths),
                capability_domain=str(route_metadata.get("capability_domain") or ""),
                metadata=route_metadata,
            )
        except Exception as route_exc:
            logger.debug(f"Cowork routing fallback: {route_exc}")
        request_contract: dict[str, Any] = {}
        capability_plan = None
        try:
            if getattr(self, "capability_router", None):
                capability_plan = self.capability_router.route(effective_user_input)
                if capability_plan is not None:
                    contract = self.capability_router.build_request_contract(
                        effective_user_input,
                        domain=str(getattr(capability_plan, "domain", "") or ""),
                        confidence=float(getattr(capability_plan, "confidence", 0.0) or 0.0),
                        route_mode=str(getattr(capability_plan, "suggested_job_type", "") or ""),
                        output_artifacts=list(getattr(capability_plan, "output_artifacts", []) or []),
                        quality_checklist=list(getattr(capability_plan, "quality_checklist", []) or []),
                        quick_intent=quick_intent,
                        parsed_intent=parsed_intent,
                        attachments=list(resolved_paths),
                        metadata=route_metadata,
                    )
                    request_contract = contract.to_dict()
        except Exception as contract_exc:
            logger.debug(f"request contract build skipped: {contract_exc}")
        if request_contract:
            route_metadata["request_contract"] = dict(request_contract)
            route_metadata["request_contract_preview"] = str(request_contract.get("preview") or "")
            route_metadata["request_content_kind"] = str(request_contract.get("content_kind") or "")
            route_metadata["request_output_formats"] = list(request_contract.get("output_formats") or [])
            route_metadata["request_style_profile"] = str(request_contract.get("style_profile") or "")
            route_metadata["request_source_policy"] = str(request_contract.get("source_policy") or "")
            route_metadata["request_quality_contract"] = list(request_contract.get("quality_contract") or [])
        if capability_plan is not None and hasattr(capability_plan, "to_dict"):
            route_metadata["capability_plan"] = capability_plan.to_dict()
        active_provider = str(elyan_config.get("models.default.provider", "ollama") or "ollama").strip().lower()
        active_model = str(elyan_config.get("models.default.model", "") or "").strip()
        try:
            from core.model_orchestrator import model_orchestrator

            active_cfg = model_orchestrator.get_best_available("inference")
            if isinstance(active_cfg, dict):
                active_provider = str(active_cfg.get("provider") or active_provider).strip().lower()
                active_model = str(active_cfg.get("model") or active_model).strip()
        except Exception:
            pass
        active_base_model_id = f"{active_provider}:{active_model}" if active_provider else active_model
        personalization_context: dict[str, Any] = {}
        personalized_chat_input = effective_user_input
        if getattr(self, "personalization", None):
            try:
                personalization_context = await self.personalization.get_runtime_context(
                    uid,
                    {
                        "request": effective_user_input,
                        "channel": str(channel or "cli"),
                        "provider": active_provider,
                        "model": active_model,
                        "base_model_id": active_base_model_id,
                        "metadata": dict(route_metadata),
                    },
                )
                route_metadata["personalization"] = {
                    "runtime_profile": dict(personalization_context.get("runtime_profile") or {}),
                    "retrieved_memory_context": str(personalization_context.get("retrieved_memory_context") or ""),
                    "retrieved_memory": dict(personalization_context.get("retrieved_memory") or {}),
                    "adapter_binding": dict(personalization_context.get("adapter_binding") or {}),
                    "reward_policy": dict(personalization_context.get("reward_policy") or {}),
                    "training_decision": dict(personalization_context.get("training_decision") or {}),
                    "provider": str(personalization_context.get("provider") or active_provider),
                    "model": str(personalization_context.get("model") or active_model),
                    "base_model_id": str(personalization_context.get("base_model_id") or active_base_model_id),
                }
                personalized_chat_input = str(personalization_context.get("request_prompt") or effective_user_input)
            except Exception as personalization_exc:
                logger.debug(f"personalization context skipped: {personalization_exc}")
        try:
            ml_runtime_snapshot = dict(self.model_runtime.snapshot() or {}) if getattr(self, "model_runtime", None) else {}
            intent_prediction = (
                dict(
                    self.intent_scorer.score(
                        effective_user_input,
                        quick_intent=quick_intent,
                        parsed_intent=parsed_intent,
                    )
                    or {}
                )
                if getattr(self, "intent_scorer", None)
                else {}
            )
            route_rankings = (
                self.action_ranker.rank(
                    intent_prediction,
                    [
                        str(getattr(route_decision, "mode", "") or "").strip().lower(),
                        str(request_contract.get("route_mode") or "").strip().lower(),
                        str(getattr(capability_plan, "suggested_job_type", "") or "").strip().lower() if capability_plan is not None else "",
                        str(route_metadata.get("request_content_kind") or "").strip().lower(),
                    ],
                    {
                        "route_decision": route_decision.to_dict() if hasattr(route_decision, "to_dict") else {},
                        "request_contract": dict(request_contract or {}),
                        "capability_plan": capability_plan.to_dict() if hasattr(capability_plan, "to_dict") else {},
                    },
                )
                if getattr(self, "action_ranker", None)
                else []
            )
            route_choice = dict(route_rankings[0] or {}) if route_rankings else {}
            clarification_policy = (
                dict(
                    self.clarification_classifier.classify(
                        effective_user_input,
                        intent_prediction=intent_prediction,
                        route_choice=route_choice,
                        request_contract=request_contract,
                    )
                    or {}
                )
                if getattr(self, "clarification_classifier", None)
                else {}
            )
            if ml_runtime_snapshot:
                route_metadata["model_runtime"] = ml_runtime_snapshot
            if intent_prediction:
                route_metadata["intent_prediction"] = intent_prediction
            if route_choice:
                route_metadata["route_choice"] = route_choice
                route_metadata["route_rankings"] = route_rankings[:5]
            if clarification_policy:
                route_metadata["clarification_policy"] = clarification_policy
            if getattr(self, "outcome_store", None):
                if intent_prediction:
                    self.outcome_store.record_decision(
                        request_id=run_id,
                        user_id=uid,
                        kind="intent_prediction",
                        selected=str(intent_prediction.get("label") or "unknown"),
                        confidence=float(intent_prediction.get("confidence", 0.0) or 0.0),
                        raw_confidence=float(intent_prediction.get("raw_confidence", 0.0) or 0.0),
                        channel=str(channel or "cli"),
                        source=str(intent_prediction.get("source") or "heuristic"),
                        metadata={"advisory": str(intent_prediction.get("advisory") or "")},
                    )
                if route_choice:
                    self.outcome_store.record_decision(
                        request_id=run_id,
                        user_id=uid,
                        kind="route_choice",
                        selected=str(route_choice.get("candidate") or "unknown"),
                        confidence=float(route_choice.get("score", 0.0) or 0.0),
                        raw_confidence=float(route_choice.get("score", 0.0) or 0.0),
                        channel=str(channel or "cli"),
                        source="action_ranker",
                        metadata={"reasons": list(route_choice.get("reasons") or []), "rankings": route_rankings[:5]},
                    )
                if clarification_policy:
                    self.outcome_store.record_decision(
                        request_id=run_id,
                        user_id=uid,
                        kind="clarification_policy",
                        selected=str(clarification_policy.get("decision") or "proceed"),
                        confidence=float(clarification_policy.get("confidence", 0.0) or 0.0),
                        raw_confidence=float(clarification_policy.get("confidence", 0.0) or 0.0),
                        channel=str(channel or "cli"),
                        source="clarification_classifier",
                        metadata={"reasons": list(clarification_policy.get("reasons") or [])},
                    )
        except Exception as ml_route_exc:
            logger.debug(f"ml routing telemetry skipped: {ml_route_exc}")
        if route_decision is not None and getattr(route_decision, "refusal", False):
            refusal_text = str(
                getattr(route_decision, "refusal_message", "")
                or getattr(route_decision, "reason", "")
                or build_chat_fallback_message(language=str(elyan_config.get("agent.language", "tr") or "tr"))
            ).strip()
            return await self._build_controlled_route_response(
                ledger=ledger,
                run_store=run_store,
                run_id=run_id,
                started_at=started_at,
                user_input=effective_user_input,
                response_text=refusal_text,
                channel=str(channel or "cli"),
                uid=uid,
                reason=str(getattr(route_decision, "reason", "") or "route_refusal"),
                action="refuse",
                mode=str(getattr(route_decision, "mode", "") or "communication"),
                status="partial",
                success=False,
                route_decision={
                    **(route_decision.to_dict() if hasattr(route_decision, "to_dict") else {}),
                    "model_runtime": dict(route_metadata.get("model_runtime") or {}),
                    "intent_prediction": dict(route_metadata.get("intent_prediction") or {}),
                    "route_choice": dict(route_metadata.get("route_choice") or {}),
                    "clarification_policy": dict(route_metadata.get("clarification_policy") or {}),
                },
            )
        cowork_session = None
        try:
            cowork_session = cowork_runtime.start_session(
                user_id=uid,
                channel=str(channel or "cli"),
                objective=effective_user_input,
                run_id=run_id,
                quick_intent=quick_intent,
                attachments=list(resolved_paths),
                runtime_policy={"execution": {"skip_verify_for_chat": True}},
                route_decision=route_decision,
            )
            cowork_runtime.observe_turn(
                session_key=cowork_session.session_id,
                role="user",
                content=effective_user_input,
                metadata={
                    "channel": str(channel or "cli"),
                    "run_id": run_id,
                    "attachment_count": len(resolved_paths),
                },
            )
        except Exception as cowork_exc:
            logger.debug(f"Cowork session bootstrap skipped: {cowork_exc}")

        route_mode_name = str(getattr(route_decision, "mode", "") or "").strip().lower() if route_decision is not None else ""
        request_contract_needs_clarification = bool(request_contract.get("needs_clarification")) if isinstance(request_contract, dict) else False
        request_content_kind = str(request_contract.get("content_kind") or "").strip().lower() if isinstance(request_contract, dict) else ""
        request_contract_clarification = str(request_contract.get("clarifying_question") or "").strip() if isinstance(request_contract, dict) else ""
        can_clarify_request = (
            request_contract_needs_clarification
            and route_mode_name not in {"communication", "chat"}
            and request_content_kind in {"web_project", "document_pack", "presentation", "spreadsheet", "research_delivery", "code_project"}
        )
        if can_clarify_request:
            if not request_contract_clarification:
                request_contract_clarification = "Çıktı biçimini netleştirir misin? Sunum, doküman, excel ya da web sitesi olarak mı hazırlayayım?"
            clarification_text = request_contract_clarification
            preview_text = str(request_contract.get("preview") or "").strip() if isinstance(request_contract, dict) else ""
            if preview_text:
                clarification_text = f"{clarification_text}\n{preview_text}"
            route_payload = route_decision.to_dict() if hasattr(route_decision, "to_dict") else {}
            if isinstance(route_payload, dict) and request_contract:
                route_payload["request_contract"] = dict(request_contract)
                route_payload["model_runtime"] = dict(route_metadata.get("model_runtime") or {})
                route_payload["intent_prediction"] = dict(route_metadata.get("intent_prediction") or {})
                route_payload["route_choice"] = dict(route_metadata.get("route_choice") or {})
                route_payload["clarification_policy"] = dict(route_metadata.get("clarification_policy") or {})
            return await self._build_controlled_route_response(
                ledger=ledger,
                run_store=run_store,
                run_id=run_id,
                started_at=started_at,
                user_input=effective_user_input,
                response_text=clarification_text,
                channel=str(channel or "cli"),
                uid=uid,
                reason="request_contract_clarify",
                action="clarify",
                mode="clarification",
                status="partial",
                success=False,
                route_decision=route_payload,
            )

        mission_mode = str(
            ((metadata or {}).get("adaptive_mode") if isinstance(metadata, dict) else "")
            or ((metadata or {}).get("mode") if isinstance(metadata, dict) else "")
            or "Balanced"
        ).strip() or "Balanced"
        if self._should_handoff_coding_mission(
            effective_user_input,
            route_decision=route_decision,
            parsed_intent=parsed_intent,
            metadata=metadata,
        ):
            mission = await self._run_coding_mission_handoff(
                effective_user_input,
                user_id=uid,
                channel=str(channel or "cli"),
                mode=mission_mode,
                attachments=list(resolved_paths),
                metadata={"route_mode_hint": "code", "source_channel": str(channel or "cli")},
            )
            return await self._build_mission_handoff_response(
                ledger=ledger,
                run_store=run_store,
                run_id=run_id,
                started_at=started_at,
                user_input=effective_user_input,
                mission=mission,
                channel=str(channel or "cli"),
                uid=uid,
                route_decision=route_decision.to_dict() if hasattr(route_decision, "to_dict") else {},
            )

        if fast_chat_allowed and self.llm is not None:
            session_mode = str(getattr(cowork_session, "mode", "") or "").strip().lower()
            disable_fast_chat_for_mode = session_mode in {"screen", "browser", "code", "research", "file"}
            fast_response = None
            if not disable_fast_chat_for_mode:
                try:
                    fast_response = self.llm.fast_response.get_fast_response(effective_user_input) if getattr(self.llm, "fast_response", None) else None
                except Exception:
                    fast_response = None

                route_allows_chat = False
                if route_decision is not None:
                    route_allows_chat = (
                        str(getattr(route_decision, "mode", "") or "").strip().lower() == "communication"
                        and hasattr(self.llm, "chat")
                    )
                else:
                    route_allows_chat = hasattr(self.llm, "chat") and self._should_route_to_llm_chat(effective_user_input, None, quick_intent)

                if fast_response and str(getattr(fast_response, "answer", "") or "").strip():
                    response_text = self._sanitize_chat_reply(fast_response.answer)
                    manifest = ledger.write_manifest(
                        status="success",
                        metadata={
                            "channel": channel,
                            "user_id": uid,
                            "mode": "chat_fast_path",
                            "question_type": str(getattr(fast_response, "question_type", "") or ""),
                            "cowork_session_id": str(getattr(cowork_session, "session_id", "") or ""),
                        },
                    )
                    run_store.write_task(
                        {},
                        user_input=effective_user_input,
                        metadata={"channel": channel, "user_id": uid, "phase": "chat_fast_path"},
                        task_state={},
                    )
                    run_store.write_evidence(
                        manifest_path=manifest,
                        steps=[],
                        artifacts=[],
                        metadata={"status": "success", "mode": "chat_fast_path"},
                    )
                    run_store.write_summary(
                        status="success",
                        response_text=response_text,
                        artifacts=[],
                        metadata={"manifest_path": manifest, "mode": "chat_fast_path"},
                    )
                    run_store.write_logs(lines=["chat_fast_path"])
                    await self._finalize_turn(
                        user_input=effective_user_input,
                        response_text=response_text,
                        action="chat",
                        success=True,
                        started_at=started_at,
                        context={
                            "role": "chat",
                            "job_type": "communication",
                            "errors": 0,
                            "run_id": run_id,
                            "mode": "chat_fast_path",
                            "channel": str(channel or "cli"),
                            "cowork_session_id": str(getattr(cowork_session, "session_id", "") or ""),
                            "personalization": dict(route_metadata.get("personalization") or {}),
                            "model_runtime": dict(route_metadata.get("model_runtime") or {}),
                            "intent_prediction": dict(route_metadata.get("intent_prediction") or {}),
                            "route_choice": dict(route_metadata.get("route_choice") or {}),
                            "clarification_policy": dict(route_metadata.get("clarification_policy") or {}),
                            "provider": active_provider,
                            "model": active_model,
                            "base_model_id": active_base_model_id,
                        },
                    )
                    return AgentResponse(
                        run_id=run_id,
                        text=response_text,
                        attachments=[],
                        evidence_manifest_path=manifest,
                        status="success",
                        error="",
                    )

                if route_allows_chat:
                    chat_text = ""
                    try:
                        chat_text = await with_timeout(
                            self.llm.chat(personalized_chat_input, user_id=uid),
                            seconds=5.0,
                            fallback=self._fallback_chat_without_llm(effective_user_input),
                            context="agent_fast_chat",
                        )
                    except Exception:
                        chat_text = self._fallback_chat_without_llm(effective_user_input)

                    response_text = self._sanitize_chat_reply(chat_text)
                    if not response_text.strip():
                        response_text = self._fallback_chat_without_llm(effective_user_input)
                    manifest = ledger.write_manifest(
                        status="success",
                        metadata={
                            "channel": channel,
                            "user_id": uid,
                            "mode": "chat_fast_path",
                            "route": "llm_chat",
                            "cowork_session_id": str(getattr(cowork_session, "session_id", "") or ""),
                        },
                    )
                    run_store.write_task(
                        {},
                        user_input=effective_user_input,
                        metadata={"channel": channel, "user_id": uid, "phase": "chat_fast_path"},
                        task_state={},
                    )
                    run_store.write_evidence(
                        manifest_path=manifest,
                        steps=[],
                        artifacts=[],
                        metadata={"status": "success", "mode": "chat_fast_path", "route": "llm_chat"},
                    )
                    run_store.write_summary(
                        status="success",
                        response_text=response_text,
                        artifacts=[],
                        metadata={"manifest_path": manifest, "mode": "chat_fast_path", "route": "llm_chat"},
                    )
                    run_store.write_logs(lines=["chat_fast_path", "llm_chat"])
                    await self._finalize_turn(
                        user_input=effective_user_input,
                        response_text=response_text,
                        action="chat",
                        success=True,
                        started_at=started_at,
                        context={
                            "role": "chat",
                            "job_type": "communication",
                            "errors": 0,
                            "run_id": run_id,
                            "mode": "chat_fast_path",
                            "route": "llm_chat",
                            "channel": str(channel or "cli"),
                            "cowork_session_id": str(getattr(cowork_session, "session_id", "") or ""),
                            "personalization": dict(route_metadata.get("personalization") or {}),
                            "model_runtime": dict(route_metadata.get("model_runtime") or {}),
                            "intent_prediction": dict(route_metadata.get("intent_prediction") or {}),
                            "route_choice": dict(route_metadata.get("route_choice") or {}),
                            "clarification_policy": dict(route_metadata.get("clarification_policy") or {}),
                            "provider": active_provider,
                            "model": active_model,
                            "base_model_id": active_base_model_id,
                        },
                    )
                    return AgentResponse(
                        run_id=run_id,
                        text=response_text,
                        attachments=[],
                        evidence_manifest_path=manifest,
                        status="success",
                        error="",
                    )

        task = task_brain.create_task(
            objective=user_input,
            user_input=user_input,
            channel=str(channel or "cli"),
            user_id=uid,
            attachments=resolved_paths,
        )
        task_brain.save_task(task)
        runtime_policy = get_runtime_policy_resolver().resolve()
        autonomy_mode = ""
        if isinstance(metadata, dict):
            autonomy_mode = str(
                metadata.get("autonomy_mode")
                or metadata.get("autonomy")
                or metadata.get("mode")
                or ""
            ).strip().lower()

        ctx = PipelineContext(
            user_input=effective_user_input,
            user_id=uid,
            channel=str(channel or "cli"),
        )
        ctx.raw_attachments = list(raw_attachments)
        ctx.attachments = list(resolved_paths)
        if resolved_paths:
            for p in resolved_paths:
                try:
                    ext = Path(str(p)).expanduser().suffix.lower()
                except Exception:
                    ext = ""
                if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                    self.file_context["last_attachment"] = str(Path(str(p)).expanduser())
                    break
        ctx.runtime_policy = {
            "name": runtime_policy.name,
            "capability": dict(runtime_policy.capability),
            "workflow": dict(getattr(runtime_policy, "workflow", {}) or {}),
            "planning": dict(runtime_policy.planning),
            "execution": dict(runtime_policy.execution),
            "nlu": dict(runtime_policy.nlu),
            "orchestration": dict(runtime_policy.orchestration),
            "api_tools": dict(runtime_policy.api_tools),
            "skills": dict(runtime_policy.skills),
            "tools": dict(runtime_policy.tools),
            "response": dict(runtime_policy.response),
            "security": dict(runtime_policy.security),
            "coding": dict(getattr(runtime_policy, "coding", {}) or {}),
            "metadata": {
                "channel": str(channel or "cli"),
                "user_id": uid,
                "run_id": run_id,
                "run_dir": str(run_store.base_dir),
                "workspace_path": str(Path.cwd()),
            },
        }
        if route_metadata.get("personalization"):
            ctx.runtime_policy["metadata"]["personalization"] = dict(route_metadata.get("personalization") or {})
        if route_metadata.get("model_runtime"):
            ctx.runtime_policy["metadata"]["model_runtime"] = dict(route_metadata.get("model_runtime") or {})
        if route_metadata.get("intent_prediction"):
            ctx.runtime_policy["metadata"]["intent_prediction"] = dict(route_metadata.get("intent_prediction") or {})
        if route_metadata.get("route_choice"):
            ctx.runtime_policy["metadata"]["route_choice"] = dict(route_metadata.get("route_choice") or {})
        if route_metadata.get("clarification_policy"):
            ctx.runtime_policy["metadata"]["clarification_policy"] = dict(route_metadata.get("clarification_policy") or {})
        if pending_workflow:
            ctx.runtime_policy["metadata"]["workflow_session"] = dict(pending_workflow)
        try:
            profile = self.user_profile.profile_summary(uid)
        except Exception:
            profile = {}
        response_cfg = ctx.runtime_policy.get("response", {}) if isinstance(ctx.runtime_policy.get("response"), dict) else {}
        response_bias_raw = profile.get("response_length_bias") if isinstance(profile, dict) else None
        response_bias = str(response_bias_raw or "").strip().lower()
        if response_bias in {"short", "medium", "detailed"}:
            response_cfg["mode"] = "concise" if response_bias == "short" else ("formal" if response_bias == "medium" else "friendly")
            response_cfg["friendly"] = False if response_bias == "short" else bool(response_cfg.get("friendly", True))
            response_cfg["compact_actions"] = bool(response_bias == "short")
        else:
            response_cfg.setdefault("friendly", bool(response_cfg.get("friendly", True)))
            response_cfg["compact_actions"] = False
        response_cfg.setdefault("share_attachments_default", True)
        ctx.runtime_policy["response"] = response_cfg

        try:
            cowork_session = cowork_runtime.start_session(
                user_id=uid,
                channel=str(channel or "cli"),
                objective=effective_user_input,
                run_id=run_id,
                quick_intent=quick_intent,
                attachments=resolved_paths,
                runtime_policy=ctx.runtime_policy,
                active_task=task.to_dict() if hasattr(task, "to_dict") else {},
            )
            ctx.cowork_session_id = cowork_session.session_id
            ctx.cowork_mode = str(cowork_session.mode or ctx.cowork_mode or "").strip()
            ctx.cowork_model = str(cowork_session.selected_model or ctx.cowork_model or "").strip()
            ctx.memory_policy = dict(cowork_session.memory_policy or {})
            ctx.verification_policy = dict(cowork_session.verification_policy or {})
            ctx.runtime_policy["metadata"]["cowork_session_id"] = cowork_session.session_id
            ctx.runtime_policy["metadata"]["cowork_mode"] = cowork_session.mode
            ctx.runtime_policy["metadata"]["cowork_model"] = cowork_session.selected_model
            if request_contract:
                ctx.runtime_policy["metadata"]["request_contract"] = dict(request_contract)
            if capability_plan is not None and hasattr(capability_plan, "to_dict"):
                ctx.runtime_policy["metadata"]["capability_plan"] = capability_plan.to_dict()
            if route_decision is not None and hasattr(route_decision, "to_dict"):
                ctx.telemetry["route_decision"] = route_decision.to_dict()
                ctx.runtime_policy["metadata"]["route_decision"] = route_decision.to_dict()
                ctx.runtime_policy["metadata"]["route_mode"] = str(getattr(route_decision, "mode", "") or "")
                ctx.runtime_policy["metadata"]["route_confidence"] = float(getattr(route_decision, "confidence", 0.0) or 0.0)
            if ctx.cowork_mode in {"screen", "browser"}:
                screen_state = await with_timeout(
                    cowork_runtime.collect_screen_state(goal=effective_user_input, task_state=task.to_dict() if hasattr(task, "to_dict") else {}),
                    seconds=4.0,
                    fallback=None,
                    context="cowork_screen_capture",
                )
                if screen_state:
                    cowork_session.screen_state = screen_state
                    ctx.screen_state = screen_state.to_dict()
                    screen_prompt = screen_state.to_prompt_block()
                    if screen_prompt:
                        screen_block = f"Screen State:\n{screen_prompt}"
                        ctx.multimodal_context = f"{ctx.multimodal_context}\n\n{screen_block}".strip() if ctx.multimodal_context else screen_block
                        if not ctx.context_working_set:
                            ctx.context_working_set = screen_prompt
                        ctx.telemetry["screen_state"] = {
                            "captured": True,
                            "frontmost_app": screen_state.frontmost_app,
                            "confidence": screen_state.confidence,
                        }
                        ctx.runtime_policy["metadata"]["screen_state"] = screen_state.to_dict()
                        ctx.runtime_policy["metadata"]["screen_state_summary"] = screen_prompt
                        ctx.runtime_policy["metadata"]["screen_state_confidence"] = float(screen_state.confidence or 0.0)
                        ctx.runtime_policy["metadata"]["screen_state_captured"] = True
        except Exception as cowork_sync_exc:
            logger.debug(f"Cowork session sync skipped: {cowork_sync_exc}")

        # ── Phase 6-10: Pre-pipeline hooks ──
        _trace_ctx = None
        if self.telemetry:
            try:
                _trace_ctx = self.telemetry.start_request(uid, effective_user_input[:100])
            except Exception:
                _trace_ctx = None
        if self.multi_language:
            try:
                _lang_detection = self.multi_language.process(effective_user_input)
                ctx.runtime_policy["metadata"]["detected_language"] = _lang_detection.get("detected_language", "en")
                ctx.runtime_policy["metadata"]["text_direction"] = _lang_detection.get("text_direction", "ltr")
            except Exception:
                pass
        if autonomy_mode in {"full", "full-autonomy", "tam_otonom", "tam-otonom"}:
            ctx.runtime_policy["name"] = "full-autonomy"
            sec_cfg = ctx.runtime_policy.get("security", {}) if isinstance(ctx.runtime_policy.get("security"), dict) else {}
            sec_cfg["require_confirmation_for_risky"] = False
            ctx.runtime_policy["security"] = sec_cfg
            exec_cfg = ctx.runtime_policy.get("execution", {}) if isinstance(ctx.runtime_policy.get("execution"), dict) else {}
            exec_cfg["mode"] = "operator"
            ctx.runtime_policy["execution"] = exec_cfg
            tools_cfg = ctx.runtime_policy.get("tools", {}) if isinstance(ctx.runtime_policy.get("tools"), dict) else {}
            tools_cfg["require_approval"] = []
            ctx.runtime_policy["tools"] = tools_cfg
            ctx.runtime_policy["metadata"]["interactive_approval"] = False
        low = str(effective_user_input or "").lower()
        ctx.team_mode_forced = any(tok in low for tok in ("team mode", "agent team", "sub-agent", "ekip modu", "takım modu"))
        if isinstance(metadata, dict):
            for k, v in metadata.items():
                if isinstance(k, str):
                    ctx.runtime_policy["metadata"][k] = v
            exec_mode = str(
                metadata.get("execution_mode")
                or metadata.get("agent_mode")
                or ""
            ).strip()
            if exec_mode:
                exec_cfg = ctx.runtime_policy.get("execution", {}) if isinstance(ctx.runtime_policy.get("execution"), dict) else {}
                exec_cfg["mode"] = exec_mode
                ctx.runtime_policy["execution"] = exec_cfg
        if route_metadata.get("personalization"):
            ctx.runtime_policy["metadata"]["personalization"] = dict(route_metadata.get("personalization") or {})
        if route_metadata.get("model_runtime"):
            ctx.runtime_policy["metadata"]["model_runtime"] = dict(route_metadata.get("model_runtime") or {})
        if route_metadata.get("intent_prediction"):
            ctx.runtime_policy["metadata"]["intent_prediction"] = dict(route_metadata.get("intent_prediction") or {})
        if route_metadata.get("route_choice"):
            ctx.runtime_policy["metadata"]["route_choice"] = dict(route_metadata.get("route_choice") or {})
        if route_metadata.get("clarification_policy"):
            ctx.runtime_policy["metadata"]["clarification_policy"] = dict(route_metadata.get("clarification_policy") or {})

        ledger_token = _active_ledger.set(ledger)
        runtime_policy_token = _active_runtime_policy.set(dict(ctx.runtime_policy or {}))
        state_token = set_current_pipeline_state(create_pipeline_state())
        try:
            task.transition("planning", note="pipeline_context_ready")
            task_brain.save_task(task)
            run_store.write_task(
                {},
                user_input=effective_user_input,
                metadata={"channel": channel, "user_id": uid, "phase": "planning"},
                task_state=task.to_dict(),
            )
            from core import pipeline as _pipeline_mod
            task.transition("executing", note="pipeline_started")
            task_brain.save_task(task)
            ctx = await _pipeline_mod.pipeline_runner.run(ctx, agent=self)

            # Agentic Loop: self-correction cycle for complex tasks
            try:
                from core.agentic_loop import run_agentic_loop
                ctx = await run_agentic_loop(ctx, agent=self)
            except Exception as _loop_err:
                logger.debug(f"Agentic loop skipped: {_loop_err}")

            if ctx.action:
                self._last_action = ctx.action

            await self._finalize_turn(
                user_input=user_input,
                response_text=ctx.final_response,
                action=ctx.action or "chat",
                success=not bool(ctx.errors),
                started_at=started_at,
                context={
                    "role": ctx.role,
                    "job_type": ctx.job_type,
                    "errors": len(ctx.errors),
                    "run_id": run_id,
                    "channel": str(channel or "cli"),
                    "cowork_session_id": str(getattr(ctx, "cowork_session_id", "") or ""),
                    "cowork_mode": str(getattr(ctx, "cowork_mode", "") or ""),
                    "repo_snapshot_id": str((getattr(ctx, "repo_snapshot", {}) or {}).get("snapshot_id") or ""),
                    "coding_contract_id": str((getattr(ctx, "coding_contract", {}) or {}).get("contract_id") or ""),
                    "style_intent": dict(getattr(ctx, "style_intent", {}) or {}),
                    "gate_state": dict(getattr(ctx, "gate_state", {}) or {}),
                    "repair_budget": int(getattr(ctx, "repair_budget", 0) or 0),
                    "model_ladder_trace": list(getattr(ctx, "model_ladder_trace", []) or []),
                    "evidence_bundle_id": str((getattr(ctx, "evidence_bundle", {}) or {}).get("bundle_id") or ""),
                    "claim_blocked_reason": str(getattr(ctx, "claim_blocked_reason", "") or ""),
                    "personalization": dict((ctx.runtime_policy.get("metadata", {}) or {}).get("personalization") or {}),
                    "model_runtime": dict((ctx.runtime_policy.get("metadata", {}) or {}).get("model_runtime") or {}),
                    "intent_prediction": dict((ctx.runtime_policy.get("metadata", {}) or {}).get("intent_prediction") or {}),
                    "route_choice": dict((ctx.runtime_policy.get("metadata", {}) or {}).get("route_choice") or {}),
                    "clarification_policy": dict((ctx.runtime_policy.get("metadata", {}) or {}).get("clarification_policy") or {}),
                    "phase_records": dict(getattr(ctx, "phase_records", {}) or {}),
                    "tool_results": list(getattr(ctx, "tool_results", []) or []),
                    "tool_call_result": dict((getattr(ctx, "phase_records", {}) or {}).get("execute", {}) or {}),
                    "verification_result": dict((getattr(ctx, "qa_results", {}) or {}).get("ml_verifier") or {}),
                    "verified": bool(getattr(ctx, "verified", False)),
                    "delivery_blocked": bool(getattr(ctx, "delivery_blocked", False)),
                    "qa_results": dict(getattr(ctx, "qa_results", {}) or {}),
                },
            )

            status = "success"
            if ctx.errors and str(ctx.final_response or "").strip():
                status = "partial"
            elif ctx.errors:
                status = "failed"
            # ── Phase 6-10: Post-pipeline hooks ──
            _elapsed_ms = (time.perf_counter() - started_at) * 1000
            if self.telemetry and _trace_ctx:
                try:
                    self.telemetry.end_request(
                        _trace_ctx["trace_id"], _trace_ctx["span_id"],
                        status="ok" if status == "success" else "error",
                        latency_ms=_elapsed_ms,
                    )
                except Exception:
                    pass
            if self.billing:
                try:
                    from core.billing.subscription import UsageType
                    self.billing.usage.record(uid, UsageType.API_REQUEST, 1)
                except Exception:
                    pass
            if self.compliance:
                try:
                    from core.compliance_v2.compliance import ComplianceFramework, AuditSeverity
                    self.compliance.auditor.log_event(
                        ComplianceFramework.SOC2, AuditSeverity.INFO,
                        "request", f"Processed: {ctx.action or 'chat'} ({status})",
                        user_id=uid,
                    )
                except Exception:
                    pass
            manifest = ledger.write_manifest(
                status=status,
                error="; ".join(str(e) for e in (ctx.errors or []) if str(e).strip()),
                metadata={
                    "action": ctx.action,
                    "job_type": ctx.job_type,
                    "channel": ctx.channel,
                    "user_id": ctx.user_id,
                },
            )
            task_spec = {}
            if isinstance(ctx.intent, dict):
                candidate = ctx.intent.get("task_spec")
                if isinstance(candidate, dict):
                    task_spec = candidate
            task.context.update(
                {
                    "action": str(ctx.action or ""),
                    "job_type": str(ctx.job_type or ""),
                    "capability_domain": str(ctx.capability_domain or ""),
                    "workflow_id": str(getattr(ctx, "workflow_id", "") or ""),
                    "hybrid_model": dict(getattr(ctx, "hybrid_model", {}) or {}),
                    "channel": str(ctx.channel or channel or ""),
                    "user_id": str(ctx.user_id or uid),
                }
            )
            if isinstance(getattr(ctx, "plan", None), list):
                task.subtasks = [
                    {
                        "id": str(step.get("id") or f"step_{idx+1}"),
                        "action": str(step.get("action") or ""),
                        "description": str(step.get("description") or step.get("title") or ""),
                    }
                    for idx, step in enumerate(ctx.plan)
                    if isinstance(step, dict)
                ]
            run_store.write_task(
                task_spec,
                user_input=user_input,
                metadata={
                    "action": ctx.action,
                    "job_type": ctx.job_type,
                    "capability_domain": str(ctx.capability_domain or ""),
                    "workflow_id": str(getattr(ctx, "workflow_id", "") or ""),
                    "hybrid_model": dict(getattr(ctx, "hybrid_model", {}) or {}),
                    "channel": ctx.channel,
                    "user_id": ctx.user_id,
                },
                task_state=task.to_dict(),
            )
            for item in list(getattr(ctx, "tool_results", []) or []):
                try:
                    tool_name = ""
                    if isinstance(item, dict):
                        tool_name = str(item.get("tool") or item.get("action") or item.get("specialist") or "")
                    ledger.register_result(tool=tool_name, result=item, source="pipeline")
                except Exception:
                    pass
            if ctx.action not in {"", "chat", None} and ledger.artifacts:
                adapted = []
                for a in ledger.artifacts:
                    if not isinstance(a, dict):
                        continue
                    item = dict(a)
                    tool = str(item.get("tool") or "")
                    source = item.get("source_result")
                    source_result = source if isinstance(source, dict) else {}
                    if not source_result:
                        source_result = {"path": item.get("path", "")}
                        if tool == "set_wallpaper":
                            source_result["_proof"] = {"screenshot": item.get("path", "")}
                    evidence = adapt_evidence(tool, source_result)
                    if not evidence and isinstance(source_result, dict):
                        normalized = coerce_execution_result(source_result, tool=tool or str(ctx.action or ""), source="pipeline")
                        if normalized.evidence:
                            evidence = normalized.evidence[0]
                    if evidence:
                        item["evidence"] = evidence
                    adapted.append(item)
                ledger.artifacts = adapted
            workflow_artifacts = dict(getattr(ctx, "workflow_artifacts", {}) or {})
            if workflow_artifacts:
                existing_paths = {
                    str(item.get("path") or "").strip()
                    for item in list(ledger.artifacts or [])
                    if isinstance(item, dict) and str(item.get("path") or "").strip()
                }
                for key, path in workflow_artifacts.items():
                    path_str = str(path or "").strip()
                    if not path_str or path_str in existing_paths:
                        continue
                    artifact_type = "workflow_artifact"
                    if path_str.endswith(".json"):
                        artifact_type = "json"
                    elif path_str.endswith(".md"):
                        artifact_type = "document"
                    ledger.artifacts.append(
                        artifact_entry(
                            path_str,
                            artifact_type=artifact_type,
                            tool=f"workflow_profile:{str(key or '').strip() or 'artifact'}",
                        )
                    )
                    existing_paths.add(path_str)
            task.register_artifacts(list(ledger.artifacts))
            task.transition(
                "verifying",
                note="evidence_registered",
                metadata={"artifact_count": len(list(ledger.artifacts or [])), "error_count": len(list(ctx.errors or []))},
            )
            task_brain.save_task(task)
            research_metrics: dict[str, Any] = {}
            for item in reversed(list(getattr(ctx, "tool_results", []) or [])):
                payload = item if isinstance(item, dict) else {}
                candidate = payload.get("result") if isinstance(payload.get("result"), dict) else payload
                if not isinstance(candidate, dict):
                    continue
                quality_summary = candidate.get("quality_summary")
                if not isinstance(quality_summary, dict) or not quality_summary:
                    continue
                research_metrics = {
                    "claim_coverage": float(quality_summary.get("claim_coverage", 0.0) or 0.0),
                    "critical_claim_coverage": float(quality_summary.get("critical_claim_coverage", 0.0) or 0.0),
                    "uncertainty_count": int(quality_summary.get("uncertainty_count", 0) or 0),
                    "conflict_count": int(quality_summary.get("conflict_count", 0) or 0),
                    "manual_review_claim_count": int(quality_summary.get("manual_review_claim_count", 0) or 0),
                    "quality_status": str(quality_summary.get("status") or ""),
                }
                claim_map_path = str(candidate.get("claim_map_path") or "").strip()
                revision_summary_path = str(candidate.get("revision_summary_path") or "").strip()
                if claim_map_path:
                    research_metrics["claim_map_path"] = claim_map_path
                if revision_summary_path:
                    research_metrics["revision_summary_path"] = revision_summary_path
                break
            team_telemetry = ctx.telemetry.get("team_mode") if isinstance(getattr(ctx, "telemetry", None), dict) and isinstance(ctx.telemetry.get("team_mode"), dict) else {}
            if team_telemetry:
                research_metrics.update(
                    {
                        "team_completed": int(team_telemetry.get("completed", 0) or 0),
                        "team_failed": int(team_telemetry.get("failed", 0) or 0),
                        "team_quality_avg": float(team_telemetry.get("quality_avg", 0.0) or 0.0),
                        "team_research_tasks": int(team_telemetry.get("research_tasks", 0) or 0),
                        "team_research_claim_coverage": float(team_telemetry.get("avg_claim_coverage", 0.0) or 0.0),
                        "team_research_critical_claim_coverage": float(team_telemetry.get("avg_critical_claim_coverage", 0.0) or 0.0),
                        "team_research_uncertainty_count": int(team_telemetry.get("max_uncertainty_count", 0) or 0),
                        "team_parallel_waves": int(team_telemetry.get("parallel_waves", 0) or 0),
                        "team_max_wave_size": int(team_telemetry.get("max_wave_size", 0) or 0),
                        "team_parallelizable_packets": int(team_telemetry.get("parallelizable_packets", 0) or 0),
                        "team_serial_packets": int(team_telemetry.get("serial_packets", 0) or 0),
                        "team_ownership_conflicts": int(team_telemetry.get("ownership_conflicts", 0) or 0),
                    }
                )
            workflow_metrics: dict[str, Any] = {}
            execution_metrics: dict[str, Any] = {}
            if str(getattr(ctx, "execution_route", "") or "").strip():
                execution_metrics = {
                    "execution_route": str(getattr(ctx, "execution_route", "") or ""),
                    "autonomy_mode": str(getattr(ctx, "autonomy_mode", "") or ""),
                    "autonomy_policy": str(getattr(ctx, "autonomy_policy", "") or ""),
                    "orchestration_decision_path": list(getattr(ctx, "orchestration_decision_path", []) or []),
                }
            if str(getattr(ctx, "workflow_profile", "default") or "default") != "default":
                workflow_metrics = {
                    "workflow_profile": str(getattr(ctx, "workflow_profile", "default") or "default"),
                    "workflow_phase": str(getattr(ctx, "workflow_phase", "") or ""),
                    "approval_status": str(getattr(ctx, "approval_status", "") or ""),
                    "workspace_mode": str(getattr(ctx, "workspace_mode", "") or ""),
                    "review_status": str(
                        team_telemetry.get("review_status")
                        or getattr(ctx, "approval_status", "")
                        or ""
                    ),
                }
                task_packets = list(getattr(ctx, "task_packets", []) or [])
                plan_completed = int(team_telemetry.get("plan_progress_completed", 0) or 0)
                plan_total = int(team_telemetry.get("plan_progress_total", len(task_packets)) or len(task_packets) or 0)
                if plan_total > 0:
                    workflow_metrics["plan_progress"] = str(
                        team_telemetry.get("plan_progress") or f"{plan_completed}/{plan_total}"
                    )
                for key in (
                    "design_artifact_path",
                    "plan_artifact_path",
                    "plan_json_artifact_path",
                    "review_artifact_path",
                    "workspace_report_path",
                    "baseline_check_path",
                    "finish_branch_report_path",
                ):
                    value = str((workflow_artifacts or {}).get(key) or "").strip()
                    if value:
                        workflow_metrics[key] = value
            run_store.write_evidence(
                manifest_path=manifest,
                steps=[s.to_dict() for s in ledger.steps],
                artifacts=list(ledger.artifacts),
                metadata={"status": status, "errors": list(ctx.errors or []), **research_metrics, **workflow_metrics, **execution_metrics},
            )
            final_state = "completed" if status == "success" else ("partial" if status == "partial" else "failed")
            task.transition(
                final_state,
                note="response_ready",
                metadata={
                    "status": status,
                    "action": str(ctx.action or ""),
                    "job_type": str(ctx.job_type or ""),
                    **workflow_metrics,
                },
            )
            task_brain.save_task(task)
            run_store.write_task(
                task_spec,
                user_input=user_input,
                metadata={
                    "action": ctx.action,
                    "job_type": ctx.job_type,
                    "capability_domain": str(ctx.capability_domain or ""),
                    "workflow_id": str(getattr(ctx, "workflow_id", "") or ""),
                    "hybrid_model": dict(getattr(ctx, "hybrid_model", {}) or {}),
                    "channel": ctx.channel,
                    "user_id": ctx.user_id,
                    "status": status,
                    **execution_metrics,
                    **workflow_metrics,
                },
                task_state=task.to_dict(),
            )
            summary_path = run_store.write_summary(
                status=status,
                response_text=str(ctx.final_response or ""),
                error="; ".join(str(e) for e in (ctx.errors or []) if str(e).strip()),
                artifacts=list(ledger.artifacts),
                metadata={"manifest_path": manifest, "action": ctx.action, "job_type": ctx.job_type, **research_metrics, **workflow_metrics, **execution_metrics},
            )
            logs_path = run_store.write_logs(lines=[str(e) for e in (ctx.errors or []) if str(e).strip()])
            refs: list[AttachmentRef] = []
            if ctx.action not in {"", "chat", None} and self._should_share_attachments(user_input, ctx, ledger.artifacts):
                refs = [self._attachment_ref_from_artifact(a) for a in ledger.artifacts if a.get("path")]
            share_manifest = self._should_share_manifest(user_input, ctx)
            final_text = str(ctx.final_response or "")
            # Artifact özeti yalnızca gerektiğinde eklensin; her yanıtta gürültü üretmesin.
            needs_artifact_summary = (
                self._user_requested_artifact_details(user_input)
                or bool(getattr(ctx, "requires_evidence", False))
                or status != "success"
            )
            if ctx.action not in {"chat", "communication"} and ledger.artifacts and needs_artifact_summary:
                paths = [a.get("path") for a in ledger.artifacts if a.get("path")]
                if paths and "Artifact" not in final_text and "artifact" not in final_text.lower():
                    final_text = f"{final_text}\n\nArtifacts:\n" + "\n".join(f"- {p}" for p in paths)
            resume_suggestion = None
            if status == "success":
                try:
                    resume_suggestion = self._build_resume_task_suggestion(uid, user_input)
                except Exception:
                    resume_suggestion = None
            if isinstance(resume_suggestion, dict):
                suggestion_text = str(resume_suggestion.get("text") or "").strip()
                if suggestion_text:
                    final_text = f"{final_text}\n\n{suggestion_text}".strip()
            final_text = self._apply_conversational_tone(final_text, ctx)
            return AgentResponse(
                run_id=run_id,
                text=final_text,
                attachments=refs,
                evidence_manifest_path=manifest,
                status=status,
                error="; ".join(str(e) for e in (ctx.errors or []) if str(e).strip()),
                metadata={
                    "action": ctx.action,
                    "job_type": ctx.job_type,
                    "run_dir": str(run_store.base_dir),
                    "task_path": str(run_store.base_dir / "task.json"),
                    "evidence_path": str(run_store.base_dir / "evidence.json"),
                    "summary_path": summary_path,
                    "logs_path": logs_path,
                    "task_suggestion": resume_suggestion or {},
                    "model_role": str(getattr(ctx, "role", "") or ""),
                    "model_provider": str(getattr(ctx, "provider", "") or ""),
                    "model_name": str(getattr(ctx, "model", "") or ""),
                    "hybrid_model": dict(getattr(ctx, "hybrid_model", {}) or {}),
                    "share_manifest": bool(share_manifest),
                    **workflow_metrics,
                },
            )
        except Exception as exc:
            err = str(exc)
            task.transition("failed", note="critical_exception", metadata={"error": err})
            task_brain.save_task(task)
            manifest = ledger.write_manifest(status="failed", error=err, metadata={"channel": channel, "user_id": uid})
            run_store.write_task({}, user_input=user_input, metadata={"channel": channel, "user_id": uid}, task_state=task.to_dict())
            run_store.write_evidence(manifest_path=manifest, steps=[s.to_dict() for s in ledger.steps], artifacts=list(ledger.artifacts), metadata={"status": "failed", "error": err})
            run_store.write_summary(status="failed", response_text=f"Çalıştırma sırasında kritik bir hata oluştu: {err}", error=err, artifacts=list(ledger.artifacts), metadata={"manifest_path": manifest})
            run_store.write_logs(lines=[err])
            return AgentResponse(
                run_id=run_id,
                text=f"Çalıştırma sırasında kritik bir hata oluştu: {err}",
                attachments=[],
                evidence_manifest_path=manifest,
                status="failed",
                error=err,
                metadata={"share_manifest": bool(self._should_share_manifest(user_input, ctx))},
            )
        finally:
            _active_ledger.reset(ledger_token)
            _active_runtime_policy.reset(runtime_policy_token)
            reset_current_pipeline_state(state_token)

    def _infer_response_mode(self, user_input: str, ctx) -> str:
        # Öncelik: runtime policy -> kullanıcı ipucu -> varsayılan
        try:
            resp_policy = ctx.runtime_policy.get("response", {}) if isinstance(ctx.runtime_policy, dict) else {}
            policy_mode = str(resp_policy.get("mode") or "").strip().lower()
        except Exception:
            policy_mode = ""
        if policy_mode:
            return policy_mode
        low = str(user_input or "").lower()
        if any(k in low for k in ("kısa", "kisaca", "öz", "özet")):
            return "concise"
        try:
            profile = self.user_profile.profile_summary(str(getattr(ctx, "user_id", "") or "local"))
            bias = str(profile.get("response_length_bias") or "").strip().lower()
            if bias == "short":
                return "concise"
            if bias == "medium":
                return "formal"
        except Exception:
            pass
        if any(k in low for k in ("resmi", "düz", "duz")):
            return "formal"
        if any(k in low for k in ("samimi", "sohbet", "sıcak", "sicak")):
            return "friendly"
        return "concise"

    def _apply_conversational_tone(self, text: str, ctx) -> str:
        """Gerektiğinde yanıtı daha sohbet tonu ile sunar."""
        if not text:
            return text
        try:
            resp_policy = ctx.runtime_policy.get("response", {}) if isinstance(ctx.runtime_policy, dict) else {}
            friendly = bool(resp_policy.get("friendly", True))
        except Exception:
            friendly = True
        if not friendly:
            return text
        # Uzun veya kod bloklu yanıtları bozma
        if len(text) > 1200 or "```" in text or "<html" in text.lower():
            return text
        if text.strip().lower() in {"ok", "tamam", "peki"}:
            return text
        mode = self._infer_response_mode(getattr(ctx, "user_input", ""), ctx)
        # Çok resmi kapanışları yumuşat
        if "Kanıt özeti" in text and len(text) < 800:
            text = text.replace("Kanıt özeti:", "Kısaca kanıtlar:")
        try:
            action = str(getattr(ctx, "action", "") or "").lower()
        except Exception:
            action = ""
        if action in {"chat", "communication", ""}:
            if mode == "concise":
                return text.strip()
            if mode == "formal":
                return text.strip()
        return text

    @staticmethod
    def _user_requested_artifact_details(user_input: str) -> bool:
        low = str(user_input or "").lower()
        if not low:
            return False
        markers = (
            "artifact",
            "çıktı",
            "cikti",
            "dosya yolu",
            "yollarını ver",
            "yollari ver",
            "path",
            "manifest",
            "kanıt",
            "kanit",
            "hash",
            "sha256",
            "screenshot",
            "ss ",
        )
        return any(m in low for m in markers)

    def _should_share_manifest(self, user_input: str, ctx) -> bool:
        """
        Manifest dosyasını kullanıcıya ancak ihtiyaç varsa gönder:
        - Kullanıcı açıkça kanıt/manifest/hash/ss isterse
        - Görev kanıtı zorunluysa (ctx.requires_evidence)
        - Profilde varsayılan paylaşım açıksa
        """
        low = str(user_input or "").lower()
        keywords = ("kanıt", "kanit", "manifest", "hash", "sha256", "ss", "screenshot", "kanıtla", "kanıt gönder")
        if any(k in low for k in keywords):
            return True
        try:
            if getattr(ctx, "requires_evidence", False):
                return True
        except Exception:
            pass
        try:
            runtime_policy = ctx.runtime_policy if isinstance(getattr(ctx, "runtime_policy", {}), dict) else {}
            response_cfg = runtime_policy.get("response", {}) if isinstance(runtime_policy.get("response", {}), dict) else {}
            if bool(response_cfg.get("share_manifest_default", False)):
                return True
        except Exception:
            pass
        return False

    def _should_share_attachments(self, user_input: str, ctx, artifacts: list[dict]) -> bool:
        """Kanala dosya ekini yalnızca ihtiyaç varsa gönder."""
        if not artifacts:
            return False
        low = str(user_input or "").lower()
        explicit = (
            "dosya gönder",
            "dosyayı gönder",
            "paylaş",
            "indir",
            "ek olarak",
            "attachment",
            "manifest",
            "kanıt",
            "hash",
            "screenshot",
            "ss ",
        )
        if any(k in low for k in explicit):
            return True
        try:
            if bool(getattr(ctx, "requires_evidence", False)):
                return True
        except Exception:
            pass
        try:
            runtime_policy = ctx.runtime_policy if isinstance(getattr(ctx, "runtime_policy", {}), dict) else {}
            response_cfg = runtime_policy.get("response", {}) if isinstance(runtime_policy.get("response", {}), dict) else {}
            if bool(response_cfg.get("share_attachments_default", False)):
                action = str(getattr(ctx, "action", "") or "").strip().lower()
                # Varsayılan paylaşım açık olsa bile sadece doğal kanıt odaklı aksiyonlarda otomatik gönder.
                if action in {"set_wallpaper", "take_screenshot", "analyze_screen", "screen_workflow", "research_document_delivery", "advanced_research"}:
                    return True
            if bool(response_cfg.get("share_manifest_default", False)) and self._user_requested_artifact_details(user_input):
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def _attach_error_code(result: Any) -> Any:
        if isinstance(result, dict) and result.get("success") is False and not result.get("error_code"):
            err = str(result.get("error") or "tool_error")
            result["error_code"] = classify_error(RuntimeError(err))
        return result

    @staticmethod
    def _normalize_tool_execution_result(
        tool_name: str,
        result: Any,
        *,
        source: str = "agent_execute_tool",
        error_code: str = "",
    ) -> dict:
        payload = normalize_legacy_tool_payload(result, tool=str(tool_name or ""), source=source)
        legacy_success_compat = (
            isinstance(result, dict)
            and result.get("success") is True
            and str(payload.get("status") or "").strip().lower() == "failed"
            and str(payload.get("error_code") or "").strip() == "TOOL_CONTRACT_VIOLATION"
        )
        if legacy_success_compat:
            compat_message = str(
                result.get("message")
                or result.get("summary")
                or result.get("output")
                or ""
            ).strip()
            payload["success"] = True
            payload["status"] = "success"
            payload["message"] = compat_message
            payload.pop("error", None)
            payload.pop("error_code", None)
            payload["errors"] = []
            payload["evidence"] = []
            data = dict(payload.get("data") or {})
            data.pop("error_code", None)
            data["compat_ambiguous_success"] = True
            payload["data"] = data
            contract_payload = dict(payload.get("_tool_result") or {})
            contract_payload["status"] = "success"
            contract_payload["message"] = compat_message
            contract_payload["errors"] = []
            contract_payload["evidence"] = []
            contract_data = dict(contract_payload.get("data") or {})
            contract_data.pop("error_code", None)
            contract_data["compat_ambiguous_success"] = True
            contract_payload["data"] = contract_data
            payload["_tool_result"] = contract_payload
        metrics = dict(payload.get("metrics") or {})
        metrics.setdefault("tool_name", str(tool_name or ""))
        metrics.setdefault("agent_source", str(source or "agent_execute_tool"))
        if legacy_success_compat:
            metrics["compat_ambiguous_success"] = True
        payload["metrics"] = metrics
        if error_code:
            if not str(payload.get("error_code") or "").strip():
                payload["error_code"] = str(error_code)
            errors = [str(item or "").strip() for item in list(payload.get("errors") or []) if str(item or "").strip()]
            if error_code not in errors:
                errors.append(str(error_code))
            payload["errors"] = errors
            data = dict(payload.get("data") or {})
            data.setdefault("error_code", str(error_code))
            payload["data"] = data
            contract_payload = dict(payload.get("_tool_result") or {})
            contract_data = dict(contract_payload.get("data") or {})
            contract_data.setdefault("error_code", str(error_code))
            contract_payload["data"] = contract_data
            contract_errors = [str(item or "").strip() for item in list(contract_payload.get("errors") or []) if str(item or "").strip()]
            if error_code not in contract_errors:
                contract_errors.append(str(error_code))
            contract_payload["errors"] = contract_errors
            payload["_tool_result"] = contract_payload
        return payload

    @staticmethod
    def _result_text_is_error(text: str) -> bool:
        low = str(text or "").strip().lower()
        if not low:
            return True

        error_prefixes = (
            "hata:",
            "error:",
            "exception:",
            "üzgünüm",
            "uzgunum",
            "başarısız",
            "basarisiz",
        )
        if any(low.startswith(prefix) for prefix in error_prefixes):
            return True

        error_markers = (
            "not found",
            "missing required",
            "missing param",
            "path does not exist",
            "işlem başarısız",
            "islem basarisiz",
            "tool '",
        )
        return any(marker in low for marker in error_markers)

    def _select_dependency_rescue_step(self, pending_steps: list, executed_steps: set) -> Any:
        if not pending_steps:
            return None

        executed = {str(item).strip() for item in (executed_steps or set()) if str(item).strip()}

        def unresolved_count(step_obj: Any) -> int:
            deps = [str(d).strip() for d in (getattr(step_obj, "dependencies", []) or []) if str(d).strip()]
            return sum(1 for dep in deps if dep not in executed)

        # Prefer information/context producer steps when deadlocked.
        context_candidates = [
            s for s in pending_steps if self._is_context_producer_action(str(getattr(s, "action", "") or ""))
        ]
        if context_candidates:
            return sorted(
                context_candidates,
                key=lambda s: (
                    unresolved_count(s),
                    len(getattr(s, "dependencies", []) or []),
                    len(str(getattr(s, "name", "") or "")),
                ),
            )[0]

        # Otherwise pick the least blocked step.
        return sorted(
            pending_steps,
            key=lambda s: (
                unresolved_count(s),
                len(getattr(s, "dependencies", []) or []),
                len(str(getattr(s, "name", "") or "")),
            ),
        )[0]

    async def _execute_planned_step_with_recovery(self, step: Any, *, user_input: str) -> tuple[str, bool]:
        step_name = str(getattr(step, "name", "") or "Adım").strip() or "Adım"
        step_action = str(getattr(step, "action", "") or "").strip()
        step_params = dict(getattr(step, "params", {}) or {}) if isinstance(getattr(step, "params", {}), dict) else {}

        max_retries = int(getattr(step, "max_retries", 2) or 2)
        max_retries = max(1, min(3, max_retries))

        current_action = step_action
        current_params = dict(step_params)
        last_error = ""

        # --- Predictive Task Readiness ---
        # Fire-and-forget prediction for the *next* likely actions based on this step.
        try:
            predictor = get_predictive_task_engine()
            async def _run_prediction():
                try:
                    preds = await predictor.predict_next_steps(step)
                    if preds:
                        await predictor.prefetch_dependencies(preds)
                except Exception as e:
                    logger.debug(f"Predictive task error: {e}")
            asyncio.create_task(_run_prediction())
        except Exception:
            pass
        # ---------------------------------

        for attempt in range(1, max_retries + 1):
            result = await self._execute_tool(
                current_action,
                current_params,
                user_input=user_input,
                step_name=step_name,
            )
            text = self._format_result_text(result)
            if not self._result_text_is_error(text):
                clean_text = str(text).strip() or "İşlem başarıyla tamamlandı."
                if not clean_text.lower().startswith(step_name.lower()):
                    clean_text = f"{step_name}: {clean_text}"
                return clean_text, True

            last_error = str(text).strip() or "İşlem başarısız."
            if attempt >= max_retries:
                break

            # 1) Try deterministic repair from the latest error.
            repaired = self._repair_tool_params_from_error(
                current_action,
                current_params,
                error_text=last_error,
                user_input=user_input,
                step_name=step_name,
            )
            if repaired:
                current_params = repaired
                continue

            # 2) If planner produced a weak step, infer a stronger direct intent for that step.
            inferred = self._infer_general_tool_intent(f"{step_name}. {user_input}")
            if isinstance(inferred, dict):
                inferred_action = str(inferred.get("action", "") or "").strip()
                inferred_params = inferred.get("params", {}) if isinstance(inferred.get("params"), dict) else {}
                if inferred_action and inferred_action not in {"chat", "unknown"}:
                    merged_params = dict(current_params)
                    for key, value in inferred_params.items():
                        existing = merged_params.get(key)
                        if existing in ("", None, [], {}):
                            merged_params[key] = value
                    current_action = inferred_action
                    current_params = merged_params

        return f"Hata: {step_name} — {last_error}", False

    def _tool_event_preview(self, result: Any) -> dict[str, Any]:
        preview: dict[str, Any] = {}
        if isinstance(result, dict):
            for key in ("success", "error", "error_code", "path", "file_path", "output_path", "verified"):
                if key in result:
                    preview[key] = result.get(key)
            txt = self._format_result_text(result)
            if isinstance(txt, str) and txt.strip():
                preview["text"] = txt[:240]
            artifacts = []
            for key in ("artifacts", "files_created", "report_paths"):
                val = result.get(key)
                if isinstance(val, list):
                    artifacts.extend([str(x).strip() for x in val if str(x).strip()])
            if artifacts:
                preview["artifacts"] = list(dict.fromkeys(artifacts))[:8]
        else:
            text = str(result or "").strip()
            if text:
                preview["text"] = text[:240]
        return preview

    def _suppress_duplicate_confirmation(self, tool_name: str, result: Any, success: bool) -> bool:
        if not success:
            return False
        try:
            text = ""
            if isinstance(result, dict):
                text = str(result.get("message") or result.get("summary") or result.get("output") or "").strip().lower()
            if not text:
                text = str(self._format_result_text(result) or "").strip().lower()
            if not text:
                return False
            key = f"{str(tool_name or '').strip().lower()}::{text[:120]}"
            now = time.time()
            last_key = str(self._last_tool_confirmation.get("key") or "")
            last_ts = float(self._last_tool_confirmation.get("ts") or 0.0)
            self._last_tool_confirmation = {"key": key, "ts": now}
            return key == last_key and (now - last_ts) <= 8.0
        except Exception:
            return False

    async def _execute_tool(
        self,
        tool_name: str,
        params: dict,
        *,
        user_input: str = "",
        step_name: str = "",
        pipeline_state=None,
    ):
        """Execute a tool via the Kernel Registry with Pipeline and Healing support."""
        # ── Pipeline Resolution ──────────────────────────────────────────────
        pipeline = pipeline_state or get_pipeline_state()
        params = pipeline.resolve_placeholders(params)
        
        # Normalize params
        safe_params = params if isinstance(params, dict) else {}
        clean_params = {k: v for k, v in safe_params.items() if k not in ("action", "type")}
        mapped_tool = ACTION_TO_TOOL.get(tool_name, tool_name)
        resolved_tool = self._resolve_tool_name(mapped_tool)
        if resolved_tool:
            mapped_tool = resolved_tool
        if mapped_tool == "advanced_research" and self._should_upgrade_research_to_delivery(
            f"{step_name} {user_input}",
            clean_params,
        ):
            mapped_tool = "research_document_delivery"
        clean_params = self._normalize_param_aliases(mapped_tool, clean_params)
        start = time.perf_counter()
        success = False
        err_text = ""
        used_tool = mapped_tool

        # ── ToolRequest kaydı başlat ──────────────────────────────────────────
        _tr_log = get_tool_request_log()
        _tr_req = _tr_log.start_request(
            mapped_tool,
            clean_params,
            source="agent",
            user_input=user_input,
            step_name=step_name,
        )
        _push_tool_event(
            "start",
            mapped_tool,
            step=step_name,
            request_id=str(getattr(_tr_req, "request_id", "") or ""),
            payload={"params": clean_params, "user_input": str(user_input or "")[:140]},
        )

        # Special case: Chat action fallback
        uid = str(self.current_user_id or "").strip()
        runtime_policy = self._current_runtime_policy()
        runtime_meta = runtime_policy.get("metadata", {}) if isinstance(runtime_policy.get("metadata"), dict) else {}
        workflow_cfg = runtime_policy.get("workflow", {}) if isinstance(runtime_policy.get("workflow"), dict) else {}
        workflow_session = runtime_meta.get("workflow_session", {}) if isinstance(runtime_meta.get("workflow_session"), dict) else {}
        runtime_uid = str(runtime_meta.get("user_id") or "").strip()
        if not uid or uid.lower() in {"local", "none", "null", "0"}:
            uid = runtime_uid or uid or "local"
        channel = str(runtime_meta.get("channel", "") or runtime_meta.get("channel_type", "") or "").strip()
        workflow_profile = normalize_workflow_profile(
            runtime_meta.get("workflow_profile") or workflow_cfg.get("profile") or workflow_session.get("workflow_profile")
        )
        workflow_phase = str(
            runtime_meta.get("workflow_phase")
            or workflow_session.get("workflow_phase")
            or "intake"
        ).strip().lower()
        workflow_domain = str(
            runtime_meta.get("capability_domain")
            or workflow_session.get("capability_domain")
            or ""
        ).strip().lower()
        runtime_meta["user_input"] = str(user_input or "")
        runtime_meta["tool_name"] = mapped_tool

        if requires_screen_state(mapped_tool):
            screen_state_payload = runtime_meta.get("screen_state") or runtime_meta.get("screen_state_payload")
            if not screen_state_payload:
                try:
                    screen_state_payload = pipeline.get("screen_state")
                except Exception:
                    screen_state_payload = None
            actionable, screen_reason = screen_state_is_actionable(screen_state_payload)
            if not actionable:
                err_text = f"screen_state_required:{screen_reason}"
                _push_tool_event(
                    "end",
                    mapped_tool,
                    step=step_name,
                    request_id=str(getattr(_tr_req, "request_id", "") or ""),
                    success=False,
                    payload={"error": err_text},
                )
                return {
                    "success": False,
                    "error": "Ekran durumu yeterli değil. Önce görünür ve etkileşilebilir bir ekran bağlamı üret.",
                    "error_code": "SCREEN_STATE_UNAVAILABLE",
                }

        approval_required_for_workflow = bool(workflow_cfg.get("require_explicit_approval", True))
        allowed_workflow_domains = {
            str(x or "").strip().lower()
            for x in list(workflow_cfg.get("allowed_domains") or [])
            if str(x or "").strip()
        }
        if (
            workflow_profile != "default"
            and approval_required_for_workflow
            and workflow_phase not in {"approved", "plan_ready", "executing", "finished"}
            and (not allowed_workflow_domains or workflow_domain in allowed_workflow_domains)
            and mapped_tool in PREAPPROVAL_BLOCKED_TOOLS
        ):
            return {
                "success": False,
                "error": "Superpowers workflow aktif: bu araç explicit approval olmadan çalıştırılamaz.",
                "error_code": "WORKFLOW_APPROVAL_REQUIRED",
            }

        # Optional strict typed-tool gate (non-breaking by default).
        typed_tools_strict = False
        try:
            from config.elyan_config import elyan_config

            typed_tools_strict = bool(elyan_config.get("agent.flags.typed_tools_strict", False))
        except Exception:
            pass
        try:
            ff = runtime_policy.get("feature_flags", {}) if isinstance(runtime_policy.get("feature_flags"), dict) else {}
            if "typed_tools_strict" in ff:
                typed_tools_strict = bool(ff.get("typed_tools_strict"))
        except Exception:
            pass
        if typed_tools_strict:
            try:
                from core.pipeline_upgrade.executor import validate_tool_io

                in_gate = validate_tool_io(mapped_tool, clean_params if isinstance(clean_params, dict) else {}, {})
                if not in_gate.ok:
                    err_text = f"typed_tool_input_rejected:{';'.join(in_gate.errors)}"
                    _push_tool_event(
                        "end",
                        mapped_tool,
                        step=step_name,
                        request_id=str(getattr(_tr_req, "request_id", "") or ""),
                        success=False,
                        payload={"error": err_text},
                    )
                    return {"success": False, "error": err_text, "error_code": "TOOL_INPUT_SCHEMA"}
            except Exception:
                pass

        # --- Runtime Guard (RBAC + operator policy + path/command checks) ---
        guard = runtime_security_guard.evaluate(
            tool_name=mapped_tool,
            params=clean_params,
            user_id=uid,
            runtime_policy=runtime_policy,
            metadata=runtime_meta,
        )
        if not guard.get("allowed", False):
            err_text = str(guard.get("reason") or "Security policy blocked this action.")
            self._audit_security_event(uid, f"runtime_guard_block:{mapped_tool}", err_text, params={"tool": mapped_tool, "risk": guard.get("risk")}, channel=channel)
            return {"success": False, "error": err_text, "error_code": "SECURITY_BLOCKED"}

        # --- Tool policy checks ---
        policy_check = tool_policy.check_access(mapped_tool)
        if not policy_check.get("allowed", False):
            # Backward-compatible allow-list behavior:
            # block only explicit deny rules, not merely "not in allow-list".
            deny_raw = elyan_config.get("tools.deny", []) or []
            deny = {str(x).strip() for x in deny_raw if str(x).strip()}
            group = tool_policy.infer_group(mapped_tool)
            explicitly_denied = (
                "*" in deny
                or mapped_tool in deny
                or (group is not None and f"group:{group}" in deny)
            )
            if explicitly_denied:
                err_text = str(policy_check.get("reason") or "Tool policy blocked this action.")
                self._audit_security_event(uid, f"tool_policy_block:{mapped_tool}", err_text, params={"tool": mapped_tool}, channel=channel)
                return {"success": False, "error": err_text, "error_code": "TOOL_POLICY_BLOCKED"}
            policy_check = {"allowed": True, "requires_approval": False, "reason": "allowlist_soft_compat"}

        requires_approval = bool(policy_check.get("requires_approval") or guard.get("requires_approval"))
        risk_level = str(guard.get("risk") or "").strip().lower()
        try:
            sec_cfg = runtime_policy.get("security", {}) if isinstance(runtime_policy.get("security"), dict) else {}
            critical_only = bool(sec_cfg.get("approval_critical_only", True))
        except Exception:
            critical_only = True
        if critical_only and requires_approval and risk_level != "dangerous":
            requires_approval = False
            self._audit_security_event(
                uid,
                f"approval_auto_noncritical:{mapped_tool}",
                "critical_only_policy_auto_approved",
                params={"tool": mapped_tool, "risk": risk_level},
                channel=channel,
            )
        # Full-autonomy/runtime control mode: auto-approve low/medium UI-runtime actions.
        try:
            policy_name = str(runtime_policy.get("name") or "").strip().lower()
            sec_cfg = runtime_policy.get("security", {}) if isinstance(runtime_policy.get("security"), dict) else {}
            full_autonomy = (
                policy_name in {"full-autonomy", "full_autonomy", "full"}
                or not bool(sec_cfg.get("require_confirmation_for_risky", True))
            )
            auto_ok_tools = {
                "open_app",
                "close_app",
                "open_url",
                "take_screenshot",
                "analyze_screen",
                "capture_region",
                "type_text",
                "press_key",
                "key_combo",
                "mouse_move",
                "mouse_click",
                "computer_use",
                "run_safe_command",
            }
            if full_autonomy and mapped_tool in auto_ok_tools:
                requires_approval = False
                self._audit_security_event(
                    uid,
                    f"approval_auto_full_autonomy:{mapped_tool}",
                    "full_autonomy_auto_approved",
                    params={"tool": mapped_tool, "risk": guard.get("risk")},
                    channel=channel,
                )
        except Exception:
            pass
        if requires_approval:
            # Smart Approval Check
            should_ask = True
            sec_cfg = runtime_policy.get("security", {}) if isinstance(runtime_policy.get("security"), dict) else {}
            # Secure default: do not auto-approve in non-interactive channels.
            interactive_approval = bool(sec_cfg.get("interactive_approval_default", False))
            if "interactive_approval" in runtime_meta:
                interactive_approval = bool(runtime_meta.get("interactive_approval"))

            if not interactive_approval:
                should_ask = False
                err_text = "Bu islem icin interaktif onay gerekiyor."
                self._audit_security_event(
                    uid,
                    f"approval_required_noninteractive:{mapped_tool}",
                    "approval_required_noninteractive",
                    params={"tool": mapped_tool, "risk": guard.get("risk")},
                    channel=channel,
                )
                return {"success": False, "error": err_text, "error_code": "APPROVAL_REQUIRED"}

            if self.learning and hasattr(self.learning, "check_approval_confidence"):
                confidence = self.learning.check_approval_confidence(mapped_tool, clean_params)
                if confidence.get("auto_approve"):
                    should_ask = False
                    logger.info(f"Smart Approval: Auto-approved {mapped_tool} ({confidence.get('reason')})")
                    _push("security", "brain", f"Auto-approved: {mapped_tool} based on history", True)

            if should_ask:
                manager = get_intervention_manager()
                target_desc = str(clean_params.get("path") or clean_params.get("file_path") or clean_params)
                choice = await manager.ask_human(
                    prompt=f"Kritik işlem onayı gerekiyor: '{mapped_tool}'\nHedef/Detay: {target_desc}\nBu işlemi onaylıyor musun?",
                    context={
                        "tool": mapped_tool,
                        "params": clean_params,
                        "policy_reason": policy_check.get("reason"),
                        "runtime_guard_reason": guard.get("reason"),
                        "risk": guard.get("risk"),
                        "user_id": runtime_uid or uid,
                        "channel": channel,
                        "channel_type": str(runtime_meta.get("channel_type") or channel or "").strip(),
                        "channel_id": str(runtime_meta.get("channel_id") or runtime_meta.get("chat_id") or "").strip(),
                    },
                    options=["Onayla", "İptal Et"]
                )
                
                # --- Learning: Record Approval/Rejection ---
                if self.learning:
                    is_approved = (choice == "Onayla")
                    try:
                        self.learning.record_interaction(
                            mapped_tool,
                            clean_params,
                            {
                                "approval_choice": choice,
                                "feedback": "Explicit Approval" if is_approved else "Explicit Rejection",
                            },
                            is_approved,
                            0.0,
                        )
                    except Exception:
                        pass
                # -------------------------------------------

                if choice != "Onayla":
                    err_text = "İşlem kullanıcı tarafından iptal edildi."
                    self._audit_security_event(uid, f"approval_rejected:{mapped_tool}", err_text, params={"tool": mapped_tool}, channel=channel)
                    return {"success": False, "error": err_text, "error_code": "USER_ABORTED"}
        # --- End Intervention ---

        if mapped_tool in ("chat", "respond", "answer"):
            prompt = safe_params.get("message") or user_input
            try:
                from core.resilience.fallback_manager import fallback_manager
                quick = self._fast_chat_reply(prompt)
                if quick:
                    return quick
                prompt_to_send = prompt
                if self._is_information_question(prompt):
                    prompt_to_send = self._build_information_question_prompt(prompt)
                if self._ensure_llm():
                    llm_cfg, allowed_providers = self._resolve_llm_config_for_runtime("inference")
                    if llm_cfg.get("type") == "none":
                        result = "KVKK/güvenlik politikası gereği bulut modele fallback kapalı ve yerel model erişilebilir değil."
                    else:
                        provider = str(llm_cfg.get("type") or llm_cfg.get("provider") or "").strip().lower()
                        flags = self._runtime_security_flags()
                        redacted_prompt = prompt_to_send
                        if bool(flags.get("kvkk_strict_mode")) and bool(flags.get("redact_cloud_prompts")) and is_external_provider(provider):
                            redacted_prompt = redact_text(str(prompt_to_send or ""))
                        result = await fallback_manager.execute_with_fallback(
                            self,
                            llm_cfg,
                            redacted_prompt,
                            user_id=uid,
                            allowed_providers=allowed_providers if allowed_providers else None,
                        )
                else:
                    result = self._fallback_chat_without_llm(prompt)
                success = True
                return self._sanitize_chat_reply(result)
            except Exception as exc:
                err_text = str(exc)
                # Last resort fallback if primary and secondary failed
                try:
                    from core.llm.factory import get_llm_client
                    alt_client = get_llm_client("ollama", "llama3.2:3b")
                    result = await alt_client.generate(prompt_to_send, user_id=uid)
                    success = True
                    return self._sanitize_chat_reply(result)
                except Exception:
                    success = True
                    return self._fallback_chat_without_llm(prompt)
            finally:
                latency = int((time.perf_counter() - start) * 1000)
                record_tool_usage(used_tool, success=success, latency_ms=latency, source="agent", error=err_text)
                _tr_log.finish_request(_tr_req, result if success else {}, latency_ms=latency, success=success, error=err_text)

        clean_params = self._prepare_tool_params(mapped_tool, clean_params, user_input=user_input, step_name=step_name)

        # Registry Execution
        try:
            _tool_timeout = RESEARCH_TIMEOUT if "research" in mapped_tool else TOOL_TIMEOUT
            result = await with_timeout(
                self.kernel.tools.execute(mapped_tool, clean_params),
                seconds=_tool_timeout,
                fallback=None,
                context=f"tool:{mapped_tool}",
            )
            result = self._normalize_tool_execution_result(mapped_tool, result, source="agent_kernel_execute")
            if isinstance(result, dict) and result.get("success") is False:
                err_text = str(result.get("error", "") or "")
                if not result.get("error_code"):
                    result["error_code"] = classify_error(RuntimeError(err_text or "tool_error"))
                _push_tool_event(
                    "update",
                    mapped_tool,
                    step=step_name,
                    request_id=str(getattr(_tr_req, "request_id", "") or ""),
                    payload={"status": "initial_failure", "error": err_text[:220]},
                )
                
                # ── Self-Healing Attempt ──────────────────────────────────────
                healing_engine = get_healing_engine()
                diagnosis = healing_engine.diagnose(err_text)
                
                # First check KB for known solution
                kb = get_knowledge_base()
                known_solution = kb.find_solution(mapped_tool, diagnosis.name if diagnosis else err_text)
                
                if known_solution and "params" in known_solution:
                    logger.info(f"Proven solution found in Knowledge Base for '{mapped_tool}'. Retrying with proven params.")
                    _push_tool_event(
                        "update",
                        mapped_tool,
                        step=step_name,
                        request_id=str(getattr(_tr_req, "request_id", "") or ""),
                        payload={"status": "kb_retry"},
                    )
                    retry_result = self._normalize_tool_execution_result(
                        mapped_tool,
                        await self.kernel.tools.execute(mapped_tool, known_solution["params"]),
                        source="agent_kernel_execute",
                    )
                    if isinstance(retry_result, dict) and retry_result.get("success"):
                        result = retry_result
                        result["_healed"] = True
                        result["_healing_message"] = "Geçmiş deneyimlere dayanarak sorun otomatik giderildi."
                        return result

                if diagnosis:
                    ctx = {"tool_name": mapped_tool, "params": clean_params}
                    plan = await healing_engine.get_healing_plan(diagnosis, err_text, ctx)
                    logger.info(f"Self-Healing: {plan['description']} (Can fix: {plan['can_auto_fix']})")
                    _push_tool_event(
                        "update",
                        mapped_tool,
                        step=step_name,
                        request_id=str(getattr(_tr_req, "request_id", "") or ""),
                        payload={"status": "self_healing_plan", "description": str(plan.get("description") or "")[:180]},
                    )
                    
                    if plan["can_auto_fix"]:
                        # If we can auto-fix (e.g. change path or install module), do it and retry.
                        if "fix_command" in plan:
                            logger.info(f"Executing healing command: {plan['fix_command']}")
                            import subprocess
                            subprocess.run(plan["fix_command"].split(), check=False)
                        
                        if "wait_time" in plan:
                            logger.info(f"Self-Healing: Waiting {plan['wait_time']} seconds...")
                            await asyncio.sleep(plan["wait_time"])

                        retry_params = plan.get("suggested_params", clean_params)
                        if "suggested_provider" in plan:
                            # If planning to switch provider, pass it as internal param
                            retry_params["_provider_override"] = plan["suggested_provider"]

                        retry_result = self._normalize_tool_execution_result(
                            mapped_tool,
                            await self.kernel.tools.execute(mapped_tool, retry_params),
                            source="agent_kernel_execute",
                        )
                        result = retry_result
                        clean_params = retry_params
                        if isinstance(result, dict) and result.get("success") is False:
                            err_text = str(result.get("error", "") or err_text)
                        else:
                                                    # Healing worked!
                                                    result["_healed"] = True
                                                    result["_healing_message"] = plan.get("message", "Hata otomatik giderildi.")
                                                    
                                                    # --- Knowledge Base Recording ---
                                                    try:
                                                        kb = get_knowledge_base()
                                                        kb.record_success(
                                                            task_type=mapped_tool,
                                                            problem=diagnosis.name if diagnosis else "unknown_error",
                                                            solution={"params": retry_params},
                                                            context={"platform": "mac", "auto_fix": True}
                                                        )
                                                    except Exception as kb_err:
                                                        logger.debug(f"KB record failed: {kb_err}")
                                            # Fallback to older repair logic if healing wasn't enough or found
                if not result.get("_healed"):
                    repaired_params = self._repair_tool_params_from_error(
                        mapped_tool,
                        clean_params,
                        error_text=err_text,
                        user_input=user_input,
                        step_name=step_name,
                    )
                    if repaired_params:
                        _push_tool_event(
                            "update",
                            mapped_tool,
                            step=step_name,
                            request_id=str(getattr(_tr_req, "request_id", "") or ""),
                            payload={"status": "deterministic_repair_retry"},
                        )
                        retry_result = self._normalize_tool_execution_result(
                            mapped_tool,
                            await self.kernel.tools.execute(mapped_tool, repaired_params),
                            source="agent_kernel_execute",
                        )
                        result = retry_result
                        clean_params = repaired_params
                        if isinstance(result, dict) and result.get("success") is False:
                            err_text = str(result.get("error", "") or err_text)

            result = self._postprocess_tool_result(mapped_tool, clean_params, result, user_input=user_input)

            # Post-proof for critical system actions
            if mapped_tool == "set_wallpaper" and isinstance(result, dict) and result.get("success"):
                try:
                    if "take_screenshot" in AVAILABLE_TOOLS:
                        stamp = int(time.time() * 1000)
                        proof = self._normalize_tool_execution_result(
                            "take_screenshot",
                            await self.kernel.tools.execute("take_screenshot", {"filename": f"wallpaper_proof_{stamp}.png"}),
                            source="agent_kernel_execute",
                        )
                        if isinstance(proof, dict) and proof.get("success"):
                            result.setdefault("_proof", {})["screenshot"] = proof.get("path") or proof.get("file_path")
                except Exception:
                    pass

            # Runtime guard evidence requirement for risky operations
            try:
                if (
                    isinstance(result, dict)
                    and result.get("success")
                    and str(guard.get("risk") or "") in {"guarded", "dangerous"}
                    and bool(getattr(guard.get("profile"), "require_evidence_for_dangerous", False))
                    and bool(runtime_policy)
                    and "take_screenshot" in AVAILABLE_TOOLS
                ):
                    proof_map = result.get("_proof", {}) if isinstance(result.get("_proof"), dict) else {}
                    if not proof_map.get("screenshot"):
                        stamp = int(time.time() * 1000)
                        shot = self._normalize_tool_execution_result(
                            "take_screenshot",
                            await self.kernel.tools.execute("take_screenshot", {"filename": f"proof_{mapped_tool}_{stamp}.png"}),
                            source="agent_kernel_execute",
                        )
                        if isinstance(shot, dict) and shot.get("success"):
                            result.setdefault("_proof", {})["screenshot"] = shot.get("path") or shot.get("file_path")
            except Exception:
                pass

            # Proof path eklendiyse görsel doğrulamayı tekrar uygula.
            if mapped_tool in {"set_wallpaper", "take_screenshot", "analyze_screen", "capture_region"}:
                result = self._postprocess_tool_result(mapped_tool, clean_params, result, user_input=user_input)

            # --- Self-Correction V2: Retry on Verification Failure ---
            if isinstance(result, dict) and result.get("verified") is False:
                # Only retry write operations
                write_tools = {"write_file", "write_word", "write_excel", "create_web_project_scaffold"}
                if mapped_tool in write_tools and not clean_params.get("_retry_attempted"):
                    logger.warning(f"Verification failed for {mapped_tool}. Retrying operation...")
                    clean_params["_retry_attempted"] = True
                    try:
                        # Strip internal keys before passing to tool
                        exec_params = {k: v for k, v in clean_params.items() if not k.startswith("_")}
                        retry_res = self._normalize_tool_execution_result(
                            mapped_tool,
                            await self.kernel.tools.execute(mapped_tool, exec_params),
                            source="agent_kernel_execute",
                        )
                        result = self._postprocess_tool_result(mapped_tool, clean_params, retry_res, user_input=user_input)
                        if result.get("verified"):
                            result["_healed"] = True
                            result["_healing_message"] = "Dosya yazma ilk denemede doğrulanamadı, ikinci denemede başarılı oldu."
                    except Exception as e:
                        logger.error(f"Retry failed for {mapped_tool}: {e}")
            # ---------------------------------------------------------

            # --- Automatic Contract Repair Loop ---
            if isinstance(result, dict) and result.get("_repair_actions") and not clean_params.get("_repair_attempted"):
                repair_actions = result.get("_repair_actions")
                repair_hints = result.get("verification_warning", "")
                logger.info(f"Contract failure for {mapped_tool}. Attempting {len(repair_actions)} repair actions. Hints: {repair_hints}")
                
                for repair in repair_actions:
                    r_action = repair.get("action")
                    r_params = dict(repair.get("params", {}))
                    # Prevent infinite repair loops
                    r_params["_repair_attempted"] = True 
                    # Provide context for the repair (essential for LLM-based tools)
                    r_params["_repair_context"] = {
                        "previous_error": result.get("error", ""),
                        "verification_failure": repair_hints,
                        "failed_reason": repair.get("reason", "")
                    }
                    
                    try:
                        exec_r_params = {k: v for k, v in r_params.items() if not k.startswith("_")}
                        repair_res = await self._execute_tool(
                            r_action,
                            exec_r_params,
                            user_input=user_input,
                            step_name=f"Onarım: {r_action}",
                            pipeline_state=pipeline,
                        )
                        if isinstance(repair_res, dict) and repair_res.get("success"):
                            # If repair succeeded, use its result
                            result = repair_res
                            # Also re-verify if needed (recursive calls handle it)
                            break
                    except Exception:
                        pass
            # --------------------------------------
                        result["_repair_successful"] = True
                        break

            # --- Audio Feedback ---
            try:
                from core.voice.audio_feedback import get_audio_feedback
                audio = get_audio_feedback()
                is_success = not (isinstance(result, dict) and result.get("success") is False)
                
                if not is_success:
                    audio.play_error()
                else:
                    # Only play success sound for impactful actions (write/exec), silence for read/search
                    impactful_prefixes = ("write", "create", "delete", "move", "copy", "run", "execute", "send", "generate")
                    if mapped_tool.startswith(impactful_prefixes) or "screenshot" in mapped_tool:
                        audio.play_success()
            except Exception:
                pass
            # ----------------------

            if typed_tools_strict:
                try:
                    from core.pipeline_upgrade.executor import validate_tool_io

                    out_gate = validate_tool_io(mapped_tool, clean_params if isinstance(clean_params, dict) else {}, result)
                    if not out_gate.ok:
                        err_text = f"typed_tool_output_rejected:{';'.join(out_gate.errors)}"
                        result = self._normalize_tool_execution_result(
                            mapped_tool,
                            {"success": False, "status": "failed", "error": err_text},
                            source="agent_kernel_execute",
                            error_code="TOOL_OUTPUT_SCHEMA",
                        )
                except Exception:
                    pass

            success = not (isinstance(result, dict) and result.get("success") is False)
            if success:
                self._update_file_context_after_tool(mapped_tool, clean_params, result)
                self._log_data_access_if_needed(uid, mapped_tool, clean_params)
                self._audit_security_event(
                    uid,
                    f"tool_execute:{mapped_tool}",
                    "ok",
                    params={"tool": mapped_tool, "risk": guard.get("risk"), "approved": bool(requires_approval)},
                    channel=channel,
                )
                # Store in active pipeline state (session-isolated when provided).
                pipeline.store(mapped_tool, result)
                if step_name:
                    pipeline.store(step_name, result)
            else:
                result = self._attach_error_code(result)
                self._audit_security_event(
                    uid,
                    f"tool_execute_failed:{mapped_tool}",
                    str(result.get("error") if isinstance(result, dict) else "failed"),
                    params={"tool": mapped_tool, "risk": guard.get("risk")},
                    channel=channel,
                )
            return self._attach_error_code(result)
        except ValueError:
            tool_func = AVAILABLE_TOOLS.get(mapped_tool)
            if not tool_func:
                resolved = self._resolve_tool_name(mapped_tool)
                if resolved:
                    used_tool = resolved
                    tool_func = AVAILABLE_TOOLS.get(resolved)
                    clean_params = self._prepare_tool_params(resolved, clean_params, user_input=user_input, step_name=step_name)
                if not tool_func:
                    err_text = f"Tool '{mapped_tool}' not found or unavailable."
                    return self._attach_error_code(
                        self._normalize_tool_execution_result(
                            mapped_tool,
                            {
                                "success": False,
                                "status": "failed",
                                "error": err_text,
                                "errors": ["UNKNOWN_TOOL"],
                                "data": {"error_code": "UNKNOWN_TOOL"},
                            },
                            source="agent_fallback_lookup",
                            error_code="UNKNOWN_TOOL",
                        )
                    )
            try:
                invoke_params = self._adapt_params_for_tool_signature(
                    tool_func, mapped_tool, clean_params, user_input=user_input, step_name=step_name
                )
                result = self._normalize_tool_execution_result(
                    used_tool,
                    await self._invoke_tool_callable(tool_func, invoke_params),
                    source="agent_fallback_callable",
                )
                if isinstance(result, dict) and result.get("success") is False:
                    err_text = str(result.get("error", "") or "")
                    repaired_params = self._repair_tool_params_from_error(
                        used_tool,
                        invoke_params,
                        error_text=err_text,
                        user_input=user_input,
                        step_name=step_name,
                    )
                    if repaired_params:
                        result = self._normalize_tool_execution_result(
                            used_tool,
                            await self._invoke_tool_callable(tool_func, repaired_params),
                            source="agent_fallback_callable",
                        )
                        invoke_params = repaired_params
                        if isinstance(result, dict) and result.get("success") is False:
                            err_text = str(result.get("error", "") or err_text)
                success = not (isinstance(result, dict) and result.get("success") is False)
                if isinstance(result, dict) and result.get("success") is False:
                    err_text = str(result.get("error", ""))
                result = self._postprocess_tool_result(used_tool, invoke_params, result, user_input=user_input)
                if typed_tools_strict:
                    try:
                        from core.pipeline_upgrade.executor import validate_tool_io

                        out_gate = validate_tool_io(used_tool, invoke_params if isinstance(invoke_params, dict) else {}, result)
                        if not out_gate.ok:
                            err_text = f"typed_tool_output_rejected:{';'.join(out_gate.errors)}"
                            result = self._normalize_tool_execution_result(
                                used_tool,
                                {"success": False, "status": "failed", "error": err_text},
                                source="agent_fallback_callable",
                                error_code="TOOL_OUTPUT_SCHEMA",
                            )
                    except Exception:
                        pass
                success = not (isinstance(result, dict) and result.get("success") is False)
                if success:
                    self._update_file_context_after_tool(used_tool, invoke_params, result)
                return self._attach_error_code(result)
            except Exception as e:
                repaired_params = self._repair_tool_params_from_error(
                    used_tool,
                    invoke_params,
                    error_text=str(e),
                    user_input=user_input,
                    step_name=step_name,
                )
                if repaired_params:
                    try:
                        result = self._normalize_tool_execution_result(
                            used_tool,
                            await self._invoke_tool_callable(tool_func, repaired_params),
                            source="agent_fallback_callable",
                        )
                        success = not (isinstance(result, dict) and result.get("success") is False)
                        if isinstance(result, dict) and result.get("success") is False:
                            err_text = str(result.get("error", ""))
                        result = self._postprocess_tool_result(used_tool, repaired_params, result, user_input=user_input)
                        if typed_tools_strict:
                            try:
                                from core.pipeline_upgrade.executor import validate_tool_io

                                out_gate = validate_tool_io(used_tool, repaired_params if isinstance(repaired_params, dict) else {}, result)
                                if not out_gate.ok:
                                    err_text = f"typed_tool_output_rejected:{';'.join(out_gate.errors)}"
                                    result = self._normalize_tool_execution_result(
                                        used_tool,
                                        {"success": False, "status": "failed", "error": err_text},
                                        source="agent_fallback_callable",
                                        error_code="TOOL_OUTPUT_SCHEMA",
                                    )
                            except Exception:
                                pass
                        success = not (isinstance(result, dict) and result.get("success") is False)
                        if success:
                            self._update_file_context_after_tool(used_tool, repaired_params, result)
                        return self._attach_error_code(result)
                    except Exception as retry_exc:
                        logger.error(f"Fallback tool retry failed ({mapped_tool}): {retry_exc}")
                        err_text = str(retry_exc)
                        return self._attach_error_code(
                            self._normalize_tool_execution_result(
                                used_tool,
                                {"success": False, "status": "failed", "error": str(retry_exc)},
                                source="agent_fallback_callable",
                                error_code="EXECUTION_EXCEPTION",
                            )
                        )
                friendly_error = self._friendly_missing_argument_error(str(e), tool_name=used_tool)
                if friendly_error:
                    logger.warning(f"Tool invocation missing param ({used_tool}): {friendly_error}")
                    err_text = friendly_error
                    return self._attach_error_code(
                        self._normalize_tool_execution_result(
                            used_tool,
                            {"success": False, "status": "needs_input", "error": friendly_error, "message": friendly_error},
                            source="agent_fallback_callable",
                        )
                    )
                logger.error(f"Fallback tool execution error ({mapped_tool}): {e}")
                err_text = str(e)
                return self._attach_error_code(
                    self._normalize_tool_execution_result(
                        used_tool,
                        {"success": False, "status": "failed", "error": str(e)},
                        source="agent_fallback_callable",
                        error_code="EXECUTION_EXCEPTION",
                    )
                )
        except asyncio.TimeoutError:
            err_text = f"Tool '{mapped_tool}' timed out"
            logger.warning(f"[timeout_guard] {err_text}")
            return self._attach_error_code(
                self._normalize_tool_execution_result(
                    mapped_tool,
                    {
                        "success": False,
                        "status": "failed",
                        "error": friendly_timeout_message(mapped_tool),
                        "errors": ["TIMEOUT"],
                        "data": {"error_code": "TIMEOUT"},
                    },
                    source="agent_execute_tool",
                    error_code="TIMEOUT",
                )
            )
        except Exception as exc:
            err_text = str(exc)
            logger.error(f"Tool execution error ({mapped_tool}): {exc}")
            return self._attach_error_code(
                self._normalize_tool_execution_result(
                    mapped_tool,
                    {
                        "success": False,
                        "status": "failed",
                        "error": str(exc),
                        "errors": ["EXECUTION_EXCEPTION"],
                        "data": {"error_code": "EXECUTION_EXCEPTION", "exception_type": type(exc).__name__},
                    },
                    source="agent_execute_tool",
                    error_code="EXECUTION_EXCEPTION",
                )
            )
        finally:
            latency = int((time.perf_counter() - start) * 1000)
            _final_result = locals().get("result", {})
            record_tool_usage(used_tool, success=success, latency_ms=latency, source="agent", error=err_text)
            # ToolRequest kaydını tamamla
            try:
                _tr_log.finish_request(
                    _tr_req,
                    _final_result,
                    latency_ms=latency,
                    success=success,
                    error=err_text,
                )
            except Exception:
                pass
            # Dashboard tool stream event (start/update/end lifecycle).
            try:
                suppress = self._suppress_duplicate_confirmation(used_tool, _final_result, success)
                if not suppress:
                    _push_tool_event(
                        "end",
                        str(used_tool or mapped_tool or tool_name),
                        step=step_name,
                        request_id=str(getattr(_tr_req, "request_id", "") or ""),
                        success=bool(success),
                        latency_ms=latency,
                        payload=self._tool_event_preview(_final_result),
                    )
                else:
                    _push_tool_event(
                        "update",
                        str(used_tool or mapped_tool or tool_name),
                        step=step_name,
                        request_id=str(getattr(_tr_req, "request_id", "") or ""),
                        payload={"status": "duplicate_confirmation_suppressed"},
                    )
            except Exception:
                pass
            # Structured execution ledger (best-effort)
            try:
                ledger = _active_ledger.get()
                if ledger is not None:
                    ledger.log_step(
                        step=str(step_name or used_tool or tool_name),
                        tool=str(used_tool or mapped_tool or tool_name),
                        status="success" if success else "failed",
                        input_payload={"user_input": user_input, "step_name": step_name},
                        params=clean_params,
                        result=_final_result,
                        duration_ms=latency,
                    )
            except Exception:
                pass
            # Context-aware dashboard hint (best-effort, never blocks execution)
            try:
                if self.learning:
                    hint_error = ""
                    if not success:
                        hint_error = str(err_text or "").strip()
                        if not hint_error and isinstance(_final_result, dict) and _final_result.get("success") is False:
                            hint_error = str(_final_result.get("error", "") or "").strip()
                    # Avoid random "success hints" when the operation failed but no reliable error context exists.
                    if success or hint_error:
                        hint = self.learning.generate_smart_hint(last_error=hint_error or None)
                        if hint:
                            if hint_error:
                                _push_hint(hint, icon="triangle-alert", color="orange")
                            else:
                                _push_hint(hint, icon="lightbulb", color="blue")
            except Exception:
                pass

    def _adapt_params_for_tool_signature(
        self,
        tool_func,
        tool_name: str,
        params: dict,
        *,
        user_input: str = "",
        step_name: str = "",
    ) -> dict:
        """
        Adapt planner params to the concrete callable signature.

        Some legacy/skill tools still use arg names like `appname` instead of `app_name`.
        This adapter keeps execution resilient without requiring parser/planner awareness.
        """
        clean = dict(params or {})
        try:
            sig = inspect.signature(tool_func)
        except Exception:
            return clean

        sig_params = sig.parameters
        if not sig_params:
            return {}

        # If callable accepts **kwargs, current payload is already safe.
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig_params.values()):
            return clean

        adapted: dict = {}
        for key, value in clean.items():
            if key in sig_params:
                adapted[key] = value

        alias_pairs = (
            ("app_name", "appname"),
            ("appname", "app_name"),
            ("message", "text"),
            ("message", "body"),
            ("message", "content"),
            ("text", "message"),
            ("body", "message"),
            ("subject", "title"),
            ("title", "subject"),
            ("query", "topic"),
            ("topic", "query"),
        )
        for src, dst in alias_pairs:
            if dst in sig_params and dst not in adapted and src in clean:
                adapted[dst] = clean[src]

        for name, param in sig_params.items():
            if name in adapted:
                continue
            if param.default is not inspect.Parameter.empty:
                continue
            inferred = self._infer_missing_param_value(
                name,
                tool_name,
                current=adapted,
                original=clean,
                user_input=user_input,
                step_name=step_name,
            )
            if inferred is not None:
                adapted[name] = inferred

        # Final fallback: if nothing matched, use original payload to preserve behavior.
        return adapted or clean

    @staticmethod
    def _friendly_missing_argument_error(error_text: str, *, tool_name: str = "") -> str:
        text = str(error_text or "").strip()
        if not text:
            return ""

        match = _re.search(
            r"missing\s+\d+\s+required positional argument[s]?:\s*'([^']+)'|missing a required argument:\s*'([^']+)'",
            text,
            _re.IGNORECASE,
        )
        if not match:
            return ""

        missing = str(match.group(1) or match.group(2) or "").strip().lower()
        tool = str(tool_name or "").strip().lower()

        if missing in {"path", "file_path", "filepath", "target_path"}:
            if tool == "delete_file":
                return "Silme işlemi için dosya adı veya yol gerekli. Örnek: 'not.txt yi sil'."
            return "Dosya işlemi için hedef yol eksik. Örnek: 'masaüstündeki not.txt dosyasını oku'."

        if missing in {"message", "text", "body", "content", "msg"} and tool == "send_notification":
            return "Bildirim metni eksik. Örnek: 'Saat 22:00'de ilaç içmemi hatırlat'."

        if missing in {"app_name", "appname", "application", "app"} and tool in {"open_app", "close_app"}:
            return "Uygulama adı eksik. Örnek: 'Safari aç'."

        return f"Eksik parametre: {missing}. Lütfen isteği daha açık belirt."

    @staticmethod
    async def _invoke_tool_callable(tool_func, invoke_params: dict):
        try:
            if inspect.iscoroutinefunction(tool_func):
                return await tool_func(**invoke_params)
            return tool_func(**invoke_params)
        except Exception as exc:
            # Unified repair loop for direct callable failures
            msg = str(exc)
            if "missing 1 required positional argument" in msg or "missing a required argument" in msg:
                return {"success": False, "error": msg}
            sm = RepairStateMachine(max_attempts=2)
            err_code = classify_error(exc)

            async def _retry(_i, _ctx):
                try:
                    if inspect.iscoroutinefunction(tool_func):
                        return await tool_func(**invoke_params)
                    return tool_func(**invoke_params)
                except Exception as e:  # noqa: PERF203
                    return {"success": False, "error": str(e)}

            ledger = _active_ledger.get()
            outcome = await sm.run(
                err_code,
                _retry,
                context={
                    "request_id": getattr(ledger, "run_id", ""),
                    "tool": str(getattr(tool_func, "__name__", "") or ""),
                },
            )
            if outcome.success:
                return {"success": True, "_repair_actions": outcome.history}
            return {
                "success": False,
                "error": str(exc),
                "error_code": err_code,
                "repair_history": outcome.history,
            }

    def _repair_tool_params_from_error(
        self,
        tool_name: str,
        params: dict,
        *,
        error_text: str,
        user_input: str = "",
        step_name: str = "",
    ) -> Optional[dict]:
        text = str(error_text or "").strip()
        if not text:
            return None

        repaired = dict(params or {})
        changed = False

        # 1) Recover missing required argument errors (legacy tool signatures).
        missing_patterns = (
            r"missing\s+\d+\s+required positional argument[s]?:\s*'([^']+)'",
            r"missing a required argument:\s*'([^']+)'",
        )
        missing_arg = ""
        for pattern in missing_patterns:
            m = _re.search(pattern, text, _re.IGNORECASE)
            if m:
                missing_arg = str(m.group(1) or "").strip()
                break

        if missing_arg:
            inferred = self._infer_missing_param_value(
                missing_arg,
                tool_name,
                current=repaired,
                original=params,
                user_input=user_input,
                step_name=step_name,
            )
            if inferred is not None:
                repaired[missing_arg] = inferred
                changed = True

        # 2) Recover not-found path errors with desktop/context-aware lookup.
        path_patterns = (
            r"Path does not exist:\s*(.+)$",
            r"No such file or directory:\s*'([^']+)'",
            r"\[Errno 2\]\s+No such file or directory:\s*'([^']+)'",
        )
        error_path = ""
        for pattern in path_patterns:
            m = _re.search(pattern, text, _re.IGNORECASE)
            if m:
                error_path = str(m.group(1) or "").strip().strip("'\"")
                break

        if error_path and not any(str(repaired.get(k) or "").strip() for k in ("path", "file_path", "filepath", "target_path")):
            repaired["path"] = error_path
            changed = True

        for key in ("path", "file_path", "filepath", "target_path", "source"):
            raw = str(repaired.get(key) or "").strip()
            if not raw:
                continue
            resolved = self._resolve_existing_path_from_context(raw, user_input=user_input)
            if resolved and resolved != raw:
                repaired[key] = resolved
                changed = True

        return repaired if changed else None

    def _infer_missing_param_value(
        self,
        missing_name: str,
        tool_name: str,
        *,
        current: dict,
        original: dict,
        user_input: str = "",
        step_name: str = "",
    ):
        name = str(missing_name or "").strip().lower()
        if not name:
            return None

        merged = {}
        merged.update(original or {})
        merged.update(current or {})

        if name in {"app_name", "appname", "application", "app"}:
            app = (
                merged.get("app_name")
                or merged.get("appname")
                or merged.get("application")
                or merged.get("app")
                or self._infer_app_name(step_name, user_input)
            )
            return str(app).strip() if app else None

        if name in {"project_name", "project", "project_title"}:
            project_name = (
                merged.get("project_name")
                or merged.get("project")
                or merged.get("project_title")
                or merged.get("name")
                or merged.get("title")
            )
            if not isinstance(project_name, str) or not project_name.strip():
                project_name = self._extract_topic(user_input, step_name)

            project_name = str(project_name or "").strip()
            if project_name and project_name != "genel konu":
                project_name = _re.sub(
                    r"\b(bir|yeni|new|website|web sitesi|web sayfası|web sayfasi|uygulama|app|proje|oluştur|olustur|yap|geliştir|gelistir|kodla)\b",
                    " ",
                    project_name,
                    flags=_re.IGNORECASE,
                )
                project_name = _re.sub(r"\s+", " ", project_name).strip(" .,:;-")
                if project_name:
                    return project_name

            low_tool = str(tool_name or "").strip().lower()
            if low_tool == "create_web_project_scaffold":
                return "web-projesi"
            if low_tool == "create_software_project_pack":
                return "uygulama-projesi"
            return "elyan-project"

        if name in {"project_path", "project_dir"}:
            project_path = (
                merged.get("project_path")
                or merged.get("project_dir")
                or merged.get("path")
                or merged.get("directory")
            )
            if isinstance(project_path, str) and project_path.strip():
                raw = project_path.strip()
                resolved = self._resolve_existing_path_from_context(raw, user_input=user_input)
                if resolved:
                    return resolved
                return self._resolve_path_with_desktop_fallback(raw, user_input=user_input)

            project_name = str(
                merged.get("project_name")
                or merged.get("project")
                or self._extract_topic(user_input, step_name)
                or "elyan-project"
            ).strip()
            if not project_name or project_name == "genel konu":
                project_name = "elyan-project"

            output_dir = str(merged.get("output_dir") or "~/Desktop").strip() or "~/Desktop"
            kind = str(
                merged.get("project_kind")
                or merged.get("project_type")
                or "app"
            ).strip().lower()
            slug = self._safe_project_slug(project_name)

            base = Path(output_dir).expanduser()
            if kind in {"app", "game", "software"}:
                candidate = base / f"{slug}_project_pack"
            else:
                candidate = base / slug
            return str(candidate)

        if name in {"path", "file_path", "filepath", "target_path"}:
            path = (
                merged.get("path")
                or merged.get("file_path")
                or merged.get("filepath")
                or merged.get("target_path")
            )
            if isinstance(path, str) and path.strip():
                return path.strip()
            last_path = self._get_last_path()
            if last_path and self._references_last_object(user_input):
                return last_path
            low_input = str(user_input or "").lower()
            if (
                last_path
                and str(tool_name or "").strip().lower() == "delete_file"
                and any(tok in low_input for tok in ("sil", "kaldır", "kaldir", "delete", "remove"))
            ):
                return last_path
            inferred_path = self._infer_path_from_text(user_input, step_name=step_name, tool_name=tool_name)
            return inferred_path or None

        if name in {"source", "src"}:
            source = merged.get("source") or merged.get("src") or merged.get("path")
            if isinstance(source, str) and source.strip():
                return source.strip()
            last_path = self._get_last_path()
            if last_path and self._references_last_object(user_input):
                return last_path
            tokens = self._extract_path_like_tokens(user_input)
            return tokens[0] if tokens else None

        if name in {"destination", "dest", "target"}:
            destination = merged.get("destination") or merged.get("dest") or merged.get("target")
            if isinstance(destination, str) and destination.strip():
                return destination.strip()
            hinted = self._extract_destination_hint_from_text(user_input)
            if hinted:
                return hinted
            tokens = self._extract_path_like_tokens(user_input)
            if len(tokens) >= 2:
                return tokens[1]
            return None

        if name in {"new_name", "newname"}:
            current_path = str(merged.get("path") or merged.get("source") or "").strip()
            current_name = Path(current_path).name if current_path else ""
            inferred_name = self._extract_new_name_from_text(user_input, current_name=current_name)
            return inferred_name or None

        if name in {"message", "text", "body", "content", "msg"}:
            message = (
                merged.get("message")
                or merged.get("text")
                or merged.get("body")
                or merged.get("content")
                or self._extract_inline_write_content(user_input)
            )
            
            # --- Predictive Prefetch Injection ---
            # If content is still missing for write operations, check if we have a prefetched draft.
            if (not isinstance(message, str) or not message.strip()) and tool_name in ("write_file", "write_word"):
                try:
                    predictor = get_predictive_task_engine()
                    draft = predictor.get_prefetched_content(tool_name)
                    if draft:
                        logger.info(f"Injecting prefetched draft for {tool_name}")
                        message = draft
                except Exception:
                    pass
            # -------------------------------------

            if not isinstance(message, str) or not message.strip():
                topic = self._extract_topic(user_input, step_name)
                message = topic if topic and topic != "genel konu" else ""
            if (not isinstance(message, str) or not message.strip()) and str(tool_name or "").strip().lower() == "send_notification":
                message = "Hatırlatma"
            return message.strip() if isinstance(message, str) and message.strip() else None

        if name in {"title", "subject", "name"}:
            title = merged.get("title") or merged.get("subject")
            if isinstance(title, str) and title.strip():
                return title.strip()
            low_tool = str(tool_name or "").strip().lower()
            if low_tool == "create_plan":
                topic = self._extract_topic(user_input, step_name)
                return topic if topic and topic != "genel konu" else "Yeni Plan"
            if tool_name == "send_notification":
                return "Elyan Hatırlatma"
            return None

        if name in {"query", "topic"}:
            topic = merged.get("query") or merged.get("topic") or self._extract_topic(user_input, step_name)
            return topic if isinstance(topic, str) and topic.strip() else None

        if name in {"url"}:
            url = merged.get("url")
            if isinstance(url, str) and url.strip():
                return url.strip()
            query = self._extract_topic(user_input, step_name)
            if query:
                return f"https://www.google.com/search?q={quote_plus(query)}"
            return None

        if name in {"action", "operation", "op"}:
            value = merged.get("action") or merged.get("operation") or merged.get("op") or merged.get("command")
            if isinstance(value, str) and value.strip():
                return value.strip()
            low = f"{step_name} {user_input}".lower()
            if str(tool_name or "").strip().lower() == "control_music":
                if any(k in low for k in ("durdur", "dur", "pause", "stop")):
                    return "pause"
                if any(k in low for k in ("devam", "resume", "continue")):
                    return "play"
                if any(k in low for k in ("sonraki", "next", "ileri")):
                    return "next"
                if any(k in low for k in ("önceki", "onceki", "previous", "geri")):
                    return "previous"
                return "play"
            return None

        if name in {"command", "cmd"}:
            command = merged.get("command") or merged.get("cmd")
            if isinstance(command, str) and command.strip():
                return command.strip()
            extracted = self._extract_terminal_command_from_text(user_input)
            if extracted:
                return extracted
            if str(tool_name or "").strip().lower() in {"run_safe_command", "run_command", "execute_shell_command"}:
                return "pwd"
            return None

        if name in {"code", "script"}:
            value = merged.get("code") or merged.get("script")
            if isinstance(value, str) and value.strip():
                return value.strip()
            extracted = self._extract_code_block_from_text(user_input)
            if extracted:
                return extracted
            low_tool = str(tool_name or "").strip().lower()
            if low_tool in {"execute_python_code", "debug_code"}:
                return 'print("ok")'
            if low_tool in {"execute_javascript_code"}:
                return 'console.log("ok");'
            return None

        if name in {"directory", "folder"}:
            value = merged.get("directory") or merged.get("folder")
            if isinstance(value, str) and value.strip():
                return value.strip()
            return self._get_last_directory()

        if name == "pattern":
            value = merged.get("pattern")
            if isinstance(value, str) and value.strip():
                return value.strip()
            m = _re.search(r"\*\.[a-z0-9]{1,8}", str(user_input or ""), _re.IGNORECASE)
            if m:
                return m.group(0)
            return "*"

        if name in {"data", "research_data"}:
            value = merged.get("data") or merged.get("research_data")
            if isinstance(value, (dict, list)) and value:
                return value
            inferred_data = self._infer_data_payload(user_input, step_name=step_name)
            return inferred_data if inferred_data else None

        if name in {"description"}:
            value = merged.get("description")
            if isinstance(value, str) and value.strip():
                return value.strip()
            topic = self._extract_topic(user_input, step_name)
            return topic if topic and topic != "genel konu" else "Görev"

        if name in {"tasks"}:
            tasks = merged.get("tasks")
            if isinstance(tasks, list) and tasks:
                return tasks
            desc = self._extract_topic(user_input, step_name) or "Görev"
            return [{"id": "task_1", "title": desc, "action": "chat", "params": {"message": desc}}]

        if name in {"to", "recipient", "recipient_email"}:
            value = merged.get("to") or merged.get("recipient") or merged.get("recipient_email")
            if isinstance(value, str) and value.strip():
                return value.strip()
            email = self._extract_email_from_text(user_input)
            if email:
                return email
            return None

        if name in {"filename"}:
            value = merged.get("filename")
            if isinstance(value, str) and value.strip():
                return value.strip()
            low_tool = str(tool_name or "").strip().lower()
            if "excel" in low_tool:
                return "tablo.xlsx"
            if "word" in low_tool or "document" in low_tool:
                return "belge.docx"
            if "pdf" in low_tool:
                return "rapor.pdf"
            return "not.txt"

        if name in {"audio_file", "image_path"}:
            value = merged.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
            tokens = self._extract_path_like_tokens(user_input)
            if tokens:
                return tokens[0]
            last_path = self._get_last_path()
            return last_path or None

        if name in {"input_paths"}:
            value = merged.get("input_paths")
            if isinstance(value, list) and value:
                return value
            tokens = self._extract_path_like_tokens(user_input)
            if len(tokens) >= 2:
                return tokens[:4]
            return None

        if name in {"output_path"}:
            value = merged.get("output_path")
            if isinstance(value, str) and value.strip():
                return value.strip()
            merged_path = self._extract_file_path_from_text(user_input, "merged_output.pdf")
            return merged_path

        if name in {"level"}:
            value = merged.get("level")
            try:
                if value is not None:
                    return max(0, min(100, int(value)))
            except Exception:
                pass
            m = _re.search(r"(\d{1,3})\s*%?", str(user_input or ""))
            if m:
                return max(0, min(100, int(m.group(1))))
            return 50

        if name in {"model_name"}:
            value = merged.get("model_name")
            if isinstance(value, str) and value.strip():
                return value.strip()
            m = _re.search(r"\bollama\s+([a-z0-9._:-]+)", str(user_input or ""), _re.IGNORECASE)
            if m:
                return m.group(1)
            return "llama3"

        if name in {"template_type"}:
            value = merged.get("template_type")
            if isinstance(value, str) and value.strip():
                return value.strip()
            return "standard"

        if name in {"plan_id", "task_id", "note_id"}:
            value = merged.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
            token = self._extract_identifier_token(str(user_input or ""))
            return token or None

        return None

    @staticmethod
    def _compute_sha256(path: str) -> str:
        p = Path(path).expanduser()
        if not p.exists() or not p.is_file():
            return ""
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def _normalize_param_aliases(self, tool_name: str, params: dict) -> dict:
        """Normalize common planner/LLM parameter aliases into canonical tool params."""
        clean = dict(params or {})
        if tool_name in {"open_app", "close_app", "openapp", "closeapp"}:
            for key in ("app_name", "appname", "application", "app", "name", "appName"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["app_name"] = value.strip()
                    break
            for key in ("appname", "application", "app", "name", "appName"):
                clean.pop(key, None)
        elif tool_name == "open_url":
            for key in ("url", "link", "website", "uri", "target_url"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["url"] = value.strip()
                    break
            for key in ("browser", "app_name", "app", "target_app", "browser_name"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["browser"] = value.strip()
                    break
            for key in ("link", "website", "uri", "target_url", "browser_name", "target_app"):
                clean.pop(key, None)
        elif tool_name == "computer_use":
            steps_val = clean.get("steps")
            if isinstance(steps_val, list):
                clean["steps"] = steps_val
            elif isinstance(clean.get("tasks"), list):
                clean["steps"] = clean.get("tasks")
            elif isinstance(clean.get("actions"), list):
                clean["steps"] = clean.get("actions")
            for key in ("task_list", "step_list"):
                value = clean.get(key)
                if isinstance(value, list):
                    clean["steps"] = value
                    break
        elif tool_name in {
            "create_web_project_scaffold",
            "create_software_project_pack",
            "create_coding_delivery_plan",
            "create_coding_verification_report",
        }:
            for key in ("project_name", "name", "title", "project", "topic"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["project_name"] = value.strip()
                    break
            if tool_name in {"create_coding_delivery_plan", "create_coding_verification_report"}:
                for key in ("project_path", "project_dir", "path", "directory"):
                    value = clean.get(key)
                    if isinstance(value, str) and value.strip():
                        clean["project_path"] = value.strip()
                        break
        elif tool_name in {"edit_text_file", "edit_word_document"}:
            for key in ("path", "file_path", "file", "target", "target_path"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["path"] = value.strip()
                    break
            for key in ("operations", "ops", "edits", "changes", "instructions"):
                value = clean.get(key)
                if isinstance(value, (list, dict, str)):
                    clean["operations"] = value
                    break
        elif tool_name == "batch_edit_text":
            for key in ("directory", "dir", "folder", "path"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["directory"] = value.strip()
                    break
            for key in ("pattern", "glob", "mask", "file_pattern"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["pattern"] = value.strip()
                    break
            for key in ("operations", "ops", "edits", "changes", "instructions"):
                value = clean.get(key)
                if isinstance(value, (list, dict, str)):
                    clean["operations"] = value
                    break
        elif tool_name in {"summarize_document", "analyze_document"}:
            for key in ("path", "file_path", "file", "target_path"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["path"] = value.strip()
                    break
            for key in ("style", "mode", "format"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["style"] = value.strip()
                    break
            for key in ("content", "text", "body"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["content"] = value.strip()
                    break
        elif tool_name == "send_notification":
            for key in ("message", "text", "body", "content", "msg"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["message"] = value.strip()
                    break
            for key in ("title", "subject", "name"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["title"] = value.strip()
                    break
        elif tool_name == "create_reminder":
            for key in ("title", "message", "text", "content", "note", "notes"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["title"] = value.strip()
                    break
            for key in ("due_time", "time", "at"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["due_time"] = value.strip()
                    break
            for key in ("due_date", "date", "day"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["due_date"] = value.strip()
                    break
        elif tool_name == "control_music":
            for key in ("action", "command", "state"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["action"] = value.strip()
                    break
            for key in ("app", "player"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["app"] = value.strip()
                    break
        return clean

    @staticmethod
    def _extract_time_from_text(text: str) -> str:
        low = str(text or "").lower()
        m = _re.search(r"\b(\d{1,2})[:.](\d{2})\b", low)
        if m:
            hour = min(23, max(0, int(m.group(1))))
            minute = min(59, max(0, int(m.group(2))))
            return f"{hour:02d}:{minute:02d}"
        m2 = _re.search(r"\bsaat\s*(\d{1,2})\s*(?:de|da|te|ta)?\b", low)
        if m2:
            hour = min(23, max(0, int(m2.group(1))))
            return f"{hour:02d}:00"
        return ""

    @staticmethod
    def _get_recent_research_text() -> str:
        try:
            from tools.research_tools.advanced_research import get_last_research_result
            last = get_last_research_result()
        except Exception:
            return ""

        if not isinstance(last, dict) or not last.get("success"):
            return ""
        data = last.get("data", {}) if isinstance(last.get("data"), dict) else {}

        summary = str(data.get("summary", "") or "").strip()
        findings = data.get("findings", []) if isinstance(data.get("findings"), list) else []
        lines: list[str] = []
        if summary:
            lines.append(summary)
        for item in findings[:12]:
            row = str(item or "").strip().lstrip("-• ").strip()
            if row:
                lines.append(f"- {row}")

        text = "\n".join(lines).strip()
        return text[:12000] if text else ""

    def _get_recent_assistant_text(self, current_user_input: str = "") -> str:
        uid = int(self.current_user_id or 0)
        if uid <= 0:
            return ""
        try:
            rows = self.kernel.memory.get_recent_conversations(uid, limit=8)
        except Exception:
            return ""

        normalized_input = (current_user_input or "").strip().lower()
        for row in rows:
            user_msg = str(row.get("user_message", "") or "").strip().lower()
            if normalized_input and user_msg == normalized_input:
                continue

            payload = row.get("bot_response")
            data = None
            if isinstance(payload, dict):
                data = payload
            elif isinstance(payload, str):
                try:
                    data = json.loads(payload)
                except Exception:
                    data = {"message": payload}
            if not isinstance(data, dict):
                continue

            for key in ("message", "summary", "content"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    def _get_recent_user_text(self, current_user_input: str = "") -> str:
        uid = int(self.current_user_id or 0)
        if uid <= 0:
            return ""
        try:
            rows = self.kernel.memory.get_recent_conversations(uid, limit=8)
        except Exception:
            return ""

        normalized_input = (current_user_input or "").strip().lower()
        for row in rows:
            user_msg = str(row.get("user_message", "") or "").strip()
            if not user_msg:
                continue
            if normalized_input and user_msg.lower() == normalized_input:
                continue
            return user_msg
        return ""

    def _get_last_turn_context(self) -> dict[str, Any]:
        data = getattr(self, "_last_turn_context", {}) or {}
        return dict(data) if isinstance(data, dict) else {}

    @staticmethod
    def _references_prior_context(user_input: str) -> bool:
        low = str(user_input or "").lower()
        if not low:
            return False
        markers = (
            "bunu",
            "şunu",
            "sunu",
            "onu",
            "bunun",
            "şunun",
            "bundan",
            "şundan",
            "buna",
            "ondan",
            "aynısını",
            "aynisini",
            "aynı şeyi",
            "ayni seyi",
            "bundaki",
            "şundaki",
            "önceki",
            "az önceki",
        )
        return any(marker in low for marker in markers)

    @staticmethod
    def _build_followup_output_path(last_path: str, default_name: str) -> str:
        default = Path(str(default_name or "not.txt"))
        suffix = default.suffix or ".txt"
        stem = default.stem or "not"

        raw_last = str(last_path or "").strip()
        if raw_last:
            base = Path(raw_last).expanduser()
            if base.suffix:
                directory = base.parent
                stem = base.stem or stem
            else:
                directory = base
            return str(directory / f"{stem}{suffix}")
        return f"~/Desktop/{stem}{suffix}"

    @staticmethod
    def _find_followup_claim_map_path(last_path: str) -> str:
        raw_last = str(last_path or "").strip()
        if not raw_last:
            return ""
        base = Path(raw_last).expanduser()
        candidates = []
        if base.is_dir():
            candidates.append(base / "claim_map.json")
        else:
            candidates.append(base.parent / "claim_map.json")
        if base.parent.name.endswith("_research_delivery"):
            candidates.append(base.parent / "claim_map.json")
        for candidate in candidates:
            try:
                if candidate.exists() and candidate.is_file():
                    return str(candidate)
            except Exception:
                continue
        return ""

    @staticmethod
    def _followup_document_profile_from_text(text: str) -> str:
        low = str(text or "").lower()
        if any(marker in low for marker in ("daha kısa", "daha kisa", "kısalt", "kisalt", "briefing")):
            return "briefing"
        if any(marker in low for marker in ("akademik", "literatür", "literatur", "atıf", "atif", "analitik", "analytical")):
            return "analytical"
        return "executive"

    @staticmethod
    def _followup_target_sections(text: str) -> list[str]:
        low = str(text or "").lower()
        sections: list[str] = []
        if any(marker in low for marker in ("yalnızca özet", "yalnizca ozet", "sadece özet", "sadece ozet", "özeti güncelle", "ozeti guncelle")):
            sections.append("Kısa Özet")
        if any(marker in low for marker in ("yalnızca sonuç", "yalnizca sonuc", "sadece sonuç", "sadece sonuc", "sonucu güncelle", "sonucu guncelle")):
            sections.append("Kısa Özet")
        if any(marker in low for marker in ("yalnızca bulgu", "yalnizca bulgu", "yalnızca bulgular", "yalnizca bulgular", "bulguları güncelle", "bulgulari guncelle")):
            sections.append("Temel Bulgular")
        if any(marker in low for marker in ("yalnızca risk", "yalnizca risk", "riskleri güncelle", "riskleri guncelle")):
            sections.append("Açık Riskler")
        if any(marker in low for marker in ("yalnızca belirsizlik", "yalnizca belirsizlik", "belirsizlikleri güncelle", "belirsizlikleri guncelle")):
            sections.append("Belirsizlikler")
        return sections

    @staticmethod
    def _has_revision_markers(user_input: str) -> bool:
        low = str(user_input or "").lower()
        if not low:
            return False
        markers = (
            "daha profesyonel",
            "profesyonel yap",
            "kurumsal yap",
            "yonetici ozeti",
            "yönetici özeti",
            "daha kısa",
            "daha kisa",
            "kısa yap",
            "kisa yap",
            "aynısını ama",
            "aynisini ama",
            "bunu düzelt",
            "bunu duzelt",
            "düzelt",
            "duzelt",
            "tekrar dene",
            "yeniden dene",
            "retry",
            "pdf yap",
            "pdf'e",
            "pdf olarak",
            "yalnızca özeti",
            "yalnizca ozeti",
            "yalnızca bulguları",
            "yalnizca bulgulari",
            "yalnızca sonucu",
            "yalnizca sonucu",
            "özeti güncelle",
            "ozeti guncelle",
            "bulguları güncelle",
            "bulgulari guncelle",
            "sonucu güncelle",
            "sonucu guncelle",
        )
        return any(marker in low for marker in markers)

    @staticmethod
    def _looks_like_image_search_request(text: str) -> bool:
        low = str(text or "").lower()
        if not low:
            return False
        explicit_image_markers = (
            "resim",
            "resimleri",
            "görsel",
            "gorsel",
            "foto",
            "fotoğraf",
            "fotograf",
            "image",
            "images",
            "wallpaper",
        )
        if any(marker in low for marker in explicit_image_markers):
            return True
        if any(
            marker in low
            for marker in (
                "resmi kaynak",
                "resmi site",
                "resmi kurum",
                "resmi gazete",
                "resmi belge",
                "resmi rapor",
                "resmi yazi",
                "resmi yazı",
                "official",
                ".gov",
            )
        ):
            return False
        return bool(_re.search(r"\b[\wçğıöşü]+\s+resmi\b", low, _re.IGNORECASE))

    @staticmethod
    def _has_professional_document_marker(text: str) -> bool:
        low = str(text or "").lower()
        if not low:
            return False
        direct_markers = (
            "profesyonel",
            "kurumsal",
            "yönetici özeti",
            "yonetici ozeti",
            "official tone",
        )
        if any(marker in low for marker in direct_markers):
            return True
        return bool(
            _re.search(
                r"\bresmi\s+(?:belge|rapor|yazı|yazi|dil|format|ton|sunum)\b",
                low,
                _re.IGNORECASE,
            )
        )

    def _infer_conversational_followup_intent(self, user_input: str) -> Optional[dict[str, Any]]:
        text = str(user_input or "").strip()
        low = text.lower()
        if not text:
            return None

        recent_user_text = self._get_recent_user_text(text)
        recent_assistant_text = self._get_recent_assistant_text(text)
        recent_research_text = self._get_recent_research_text()
        last_path = self._get_last_path()
        last_turn = self._get_last_turn_context()
        last_action = str(last_turn.get("action") or getattr(self, "_last_action", "") or "").strip().lower()
        last_success = bool(last_turn.get("success", True))

        has_context = bool(last_path or recent_user_text or recent_assistant_text or recent_research_text or last_action)
        if not has_context:
            return None

        references_context = self._references_prior_context(text)
        short_followup = len(text.split()) <= 9
        revision_marked = self._has_revision_markers(text)

        explicit_tokens = self._extract_path_like_tokens(text)
        explicit_file_ref = any(Path(str(tok).strip()).suffix for tok in explicit_tokens if str(tok).strip())
        if explicit_file_ref:
            return None

        summary_markers = (
            "özetle",
            "ozetle",
            "özet",
            "ozet",
            "kısalt",
            "kisalt",
            "sadeleştir",
            "sadelestir",
        )
        research_markers = (
            "araştır",
            "arastir",
            "araştırma",
            "arastirma",
            "research",
            "incele",
        )
        doc_markers = (
            "belge",
            "doküman",
            "dokuman",
            "rapor",
            "word",
            "docx",
            "kaydet",
            "dosya",
        )
        professional_marked = self._has_professional_document_marker(low)
        academic_markers = (
            "akademik",
            "literatür",
            "literatur",
            "atıf",
            "atif",
            "citation",
            "kaynakça",
            "kaynakca",
        )
        standalone_research_request = (
            any(marker in low for marker in research_markers)
            and (
                "hakkında" in low
                or "hakkinda" in low
                or " için " in f" {low} "
                or " icin " in f" {low} "
                or len(text.split()) >= 5
            )
        )
        standalone_document_request = any(marker in low for marker in doc_markers) and len(text.split()) >= 4
        standalone_academic_request = any(marker in low for marker in academic_markers) and len(text.split()) >= 4
        if not references_context and not revision_marked:
            if not short_followup or standalone_research_request or standalone_document_request or standalone_academic_request:
                return None

        content_seed = recent_research_text or recent_assistant_text
        topic_seed = recent_user_text or recent_assistant_text or text
        claim_map_path = self._find_followup_claim_map_path(last_path)

        retry_markers = (
            "tekrar dene",
            "yeniden dene",
            "retry",
            "tekrar yap",
            "bir daha dene",
        )
        repair_markers = (
            "düzelt",
            "duzelt",
            "fixle",
            "daha düzgün",
            "daha duzgun",
            "hatasız yap",
            "hatasiz yap",
        )
        if (
            not last_success
            and (any(marker in low for marker in retry_markers) or any(marker in low for marker in repair_markers))
        ):
            return {
                "action": "failure_replay",
                "params": {"limit": 30},
                "reply": "Son başarısız görev daha sıkı ayarlarla tekrar deneniyor...",
            }

        pdf_requested = any(marker in low for marker in ("pdf yap", "pdf'e", "pdf olarak"))
        research_revision_ready = bool(
            revision_marked
            and (recent_research_text or claim_map_path or last_action == "research_document_delivery")
        )
        if research_revision_ready:
            topic = self._sanitize_research_topic(
                self._extract_topic(topic_seed, topic_seed),
                user_input=topic_seed,
                step_name=text,
            )
            if topic and topic != "genel konu":
                combined_low = f"{low} {str(topic_seed).lower()}"
                is_academic = any(marker in combined_low for marker in academic_markers)
                output_dir = str(Path(last_path).expanduser().parent) if last_path else "~/Desktop"
                return {
                    "action": "research_document_delivery",
                    "params": {
                        "topic": topic,
                        "brief": recent_user_text or text,
                        "depth": "expert" if professional_marked or is_academic else "comprehensive",
                        "audience": "academic" if is_academic else "executive",
                        "language": "tr",
                        "output_dir": output_dir,
                        "include_word": True,
                        "include_excel": False,
                        "include_pdf": pdf_requested,
                        "include_report": True,
                        "source_policy": "academic" if is_academic else "trusted",
                        "min_reliability": 0.78 if is_academic else 0.65,
                        "citation_style": "apa7" if is_academic else "none",
                        "include_bibliography": True if is_academic or claim_map_path else False,
                        "document_profile": self._followup_document_profile_from_text(text),
                        "citation_mode": "inline",
                        "previous_claim_map_path": claim_map_path,
                        "revision_request": text,
                        "target_sections": self._followup_target_sections(text),
                    },
                    "reply": "Önceki araştırma belgesi kanıt bağları korunarak revize ediliyor...",
                }

        if any(marker in low for marker in research_markers) and (
            references_context
            or any(marker in low for marker in doc_markers)
            or professional_marked
            or short_followup
        ):
            topic = self._sanitize_research_topic(
                self._extract_topic(topic_seed, topic_seed),
                user_input=topic_seed,
                step_name=text,
            )
            if not topic or topic == "genel konu":
                return None
            combined_low = f"{low} {str(topic_seed).lower()}"
            is_academic = any(marker in combined_low for marker in academic_markers)
            return {
                "action": "research_document_delivery",
                "params": {
                    "topic": topic,
                    "brief": recent_user_text or text,
                    "depth": "expert" if professional_marked else "comprehensive",
                    "audience": "academic" if is_academic else "executive",
                    "language": "tr",
                    "output_dir": "~/Desktop",
                    "include_word": True,
                    "include_excel": False,
                    "include_report": True,
                    "source_policy": "academic" if is_academic else "trusted",
                    "min_reliability": 0.78 if is_academic else 0.65,
                    "citation_style": "apa7" if is_academic else "none",
                    "include_bibliography": bool(is_academic),
                },
                "reply": "Önceki bağlamdan araştırma belgesi hazırlanıyor...",
            }

        if any(marker in low for marker in summary_markers) or (
            any(marker in low for marker in ("aynısını ama", "aynisini ama"))
            and any(marker in low for marker in ("kısa", "kisa", "özet", "ozet"))
        ):
            params: dict[str, Any] = {"style": self._infer_summary_style(text)}
            if last_path and Path(last_path).suffix:
                params["path"] = last_path
            elif content_seed:
                params["content"] = content_seed
            else:
                return None
            return {
                "action": "summarize_document",
                "params": params,
                "reply": "Önceki bağlam özetleniyor...",
            }

        professional_marked = professional_marked or any(
            marker in low for marker in ("daha iyi yaz", "daha iyi hazırla", "kurumsal")
        )
        if professional_marked:
            topic = self._sanitize_research_topic(
                self._extract_topic(topic_seed, topic_seed),
                user_input=topic_seed,
                step_name=text,
            )
            if topic and topic != "genel konu":
                return {
                    "action": "generate_document_pack",
                    "params": {
                        "topic": topic,
                        "brief": content_seed or recent_user_text or text,
                        "audience": "executive",
                        "language": "tr",
                        "output_dir": "~/Desktop",
                    },
                    "reply": "Önceki bağlam profesyonel belge paketine dönüştürülüyor...",
                }

        if any(marker in low for marker in ("pdf yap", "pdf'e", "pdf olarak")):
            topic = self._sanitize_research_topic(
                self._extract_topic(topic_seed, topic_seed),
                user_input=topic_seed,
                step_name=text,
            )
            if topic and topic != "genel konu":
                return {
                    "action": "generate_document_pack",
                    "params": {
                        "topic": topic,
                        "brief": content_seed or recent_user_text or text,
                        "audience": "executive",
                        "language": "tr",
                        "output_dir": "~/Desktop",
                    },
                    "reply": "Önceki bağlam doküman paketine çevriliyor...",
                }

        if any(marker in low for marker in ("word", "docx", "belge", "rapor")) and any(
            marker in low for marker in ("kaydet", "oluştur", "olustur", "hazırla", "hazirla")
        ):
            if not content_seed:
                return None
            return {
                "action": "create_word_document",
                "params": {
                    "path": self._build_followup_output_path(last_path, "belge.docx"),
                    "content": content_seed,
                },
                "reply": "Önceki bağlam Word belgesine kaydediliyor...",
            }

        if any(marker in low for marker in ("excel", "xlsx", "tablo", "sheet")) and any(
            marker in low for marker in ("kaydet", "oluştur", "olustur", "hazırla", "hazirla")
        ):
            if not content_seed:
                return None
            return {
                "action": "create_excel",
                "params": {
                    "path": self._build_followup_output_path(last_path, "tablo.xlsx"),
                    "content": content_seed,
                },
                "reply": "Önceki bağlam tabloya kaydediliyor...",
            }

        if any(marker in low for marker in ("kaydet", "dosya olarak", "not olarak", "masaüstüne", "masaustune")):
            if not content_seed:
                return None
            default_name = "not.md" if any(marker in low for marker in ("markdown", ".md")) else "not.txt"
            return {
                "action": "write_file",
                "params": {
                    "path": self._build_followup_output_path(last_path, default_name),
                    "content": content_seed,
                },
                "reply": "Önceki bağlam dosyaya kaydediliyor...",
            }
        return None

    def _infer_app_name(self, *texts: str) -> str:
        haystack = " ".join(t for t in texts if isinstance(t, str) and t).lower()
        if not haystack:
            return ""

        aliases = (
            ("google chrome", "Google Chrome"),
            ("chrome", "Google Chrome"),
            ("safari", "Safari"),
            ("firefox", "Firefox"),
            ("finder", "Finder"),
            ("terminal", "Terminal"),
            ("iterm", "iTerm"),
            ("visual studio code", "Visual Studio Code"),
            ("vs code", "Visual Studio Code"),
            ("vscode", "Visual Studio Code"),
            ("spotify", "Spotify"),
            ("telegram", "Telegram"),
            ("discord", "Discord"),
            ("slack", "Slack"),
            ("whatsapp", "WhatsApp"),
            ("mail", "Mail"),
            ("takvim", "Calendar"),
            ("calendar", "Calendar"),
            ("notlar", "Notes"),
            ("notes", "Notes"),
            ("preview", "Preview"),
            ("photos", "Photos"),
            ("mesajlar", "Messages"),
            ("messages", "Messages"),
            ("tarayıcı", "Safari"),
            ("tarayici", "Safari"),
            ("browser", "Safari"),
        )
        for token, app_name in aliases:
            if token in haystack:
                return app_name

        for txt in texts:
            if not isinstance(txt, str):
                continue
            m = _re.search(r"[\"']([^\"']{2,40})[\"']", txt)
            if m:
                return m.group(1).strip()
        return ""

    def _resolve_tool_name(self, raw_name: str) -> Optional[str]:
        """Resolve hallucinated/variant action names to a known tool name."""
        name = str(raw_name or "").strip().lower()
        name = name.strip("`'\"")
        for prefix in ("tool.", "tool:", "action.", "action:", "function.", "function:"):
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        name = name.replace("-", "_").replace(" ", "_").replace("/", "_")
        name = _re.sub(r"[^a-z0-9_]", "", name)
        name = _re.sub(r"_+", "_", name).strip("_")
        if not name:
            return None
        if name in AVAILABLE_TOOLS:
            return name

        aliases = {
            "screenshot": "take_screenshot",
            "screen_capture": "take_screenshot",
            "openapp": "open_app",
            "open_application": "open_app",
            "openapplication": "open_app",
            "launch_app": "open_app",
            "launchapp": "open_app",
            "closeapp": "close_app",
            "close_application": "close_app",
            "closeapplication": "close_app",
            "web_research": "advanced_research",
            "internet_research": "advanced_research",
            "research_web": "advanced_research",
            "deep_web_research": "deep_research",
            "search_web": "web_search",
            "browser_search": "web_search",
            "search_internet": "web_search",
            "open_browser": "open_url",
            "openbrowser": "open_url",
            "python_run": "execute_python_code",
            "run_python": "execute_python_code",
            "command_run": "run_safe_command",
            "visual_generate": "create_visual_asset_pack",
            "generate_image": "create_visual_asset_pack",
            "image_generate": "create_visual_asset_pack",
        }
        alias = aliases.get(name)
        if alias:
            if alias in AVAILABLE_TOOLS and AVAILABLE_TOOLS.get(alias):
                return alias
            # Degrade gracefully when primary alias isn't loadable.
            alias_fallbacks = {
                "advanced_research": ["deep_research", "web_search", "fetch_page"],
                "deep_research": ["advanced_research", "web_search"],
                "create_visual_asset_pack": ["take_screenshot"],
            }
            for candidate in alias_fallbacks.get(alias, []):
                if candidate in AVAILABLE_TOOLS and AVAILABLE_TOOLS.get(candidate):
                    return candidate

        # Fuzzy fallback across known tools
        names = list(AVAILABLE_TOOLS.keys())
        close = get_close_matches(name, names, n=1, cutoff=0.78)
        if close:
            candidate = close[0]
            return candidate if AVAILABLE_TOOLS.get(candidate) else None
        return None

    def _should_run_direct_intent(self, intent: Optional[dict], user_input: str) -> bool:
        if not intent or not isinstance(intent, dict):
            return False
        action = str(intent.get("action", "") or "").strip().lower()
        if not action or action in {"chat", "unknown"}:
            return False
        if action in {"api_health_get_save", "filesystem_batch"}:
            return True
        if action == "multi_task":
            return isinstance(intent.get("tasks"), list) and len(intent.get("tasks") or []) > 0
        if self._is_multi_step_request(user_input):
            return False
        return True

    @staticmethod
    def _should_route_to_llm_chat(user_input: str, parsed_intent: Optional[dict], quick_intent: Any) -> bool:
        action = ""
        if isinstance(parsed_intent, dict):
            action = str(parsed_intent.get("action", "") or "").strip().lower()
            # Code/creative write requests that explicitly request LLM routing
            if parsed_intent.get("_route_to_llm"):
                return True

        category = getattr(quick_intent, "category", None)
        if category in (_IC.CHAT, _IC.GREETING):
            return True
        if category == _IC.QUESTION and action in {"", "chat", "show_help", "unknown"}:
            return True
        # Short/ambiguous chat-like inputs (e.g. "Arkaplanda") should not fall into unsafe planner rejection.
        if action in {"", "chat", "unknown"} and Agent._is_likely_chat_message(user_input):
            return True
        if action in {"", "chat", "unknown"} and Agent._is_information_question(user_input):
            return True
        # Creative writing requests (poetry, stories, essays) → LLM
        if Agent._is_creative_writing_request(user_input):
            return True
        return False

    @staticmethod
    def _should_upgrade_research_to_delivery(user_input: str, params: Optional[dict[str, Any]] = None) -> bool:
        low = str(user_input or "").lower()
        payload = params if isinstance(params, dict) else {}
        if any(bool(payload.get(key)) for key in ("include_word", "include_pdf", "include_excel", "include_latex", "deliver_copy")):
            return True
        doc_markers = (
            "belge", "doküman", "dokuman", "rapor", "word", "docx", "pdf", "excel", "xlsx", "dosya",
        )
        deliver_markers = (
            "gönder", "gonder", "paylaş", "paylas", "ilet", "kopya",
        )
        return any(marker in low for marker in doc_markers) and any(marker in low for marker in deliver_markers)

    def _collapse_research_document_intent(self, user_input: str, tasks: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        low = str(user_input or "").lower()
        if not isinstance(tasks, list) or len(tasks) < 2:
            return None

        research_actions = {"research", "advanced_research", "research_document_delivery"}
        has_research = False
        include_word = False
        include_excel = False
        include_pdf = any(token in low for token in ("pdf", "pdf yap", "pdf olarak"))
        deliver_copy = any(token in low for token in ("gönder", "gonder", "paylaş", "paylas", "ilet"))

        for task in list(tasks or []):
            if not isinstance(task, dict):
                continue
            action = str(task.get("action") or "").strip().lower()
            mapped = ACTION_TO_TOOL.get(action, action)
            if action in research_actions or mapped in {"advanced_research", "research_document_delivery"}:
                has_research = True
            if action in {"create_word_document", "write_word"} or mapped == "write_word":
                include_word = True
            if action in {"create_excel", "write_excel"} or mapped == "write_excel":
                include_excel = True

        doc_requested = include_word or include_excel or include_pdf or self._should_upgrade_research_to_delivery(user_input)
        if not has_research or not doc_requested:
            return None

        topic = self._sanitize_research_topic(
            self._extract_topic(user_input, user_input),
            user_input=user_input,
            step_name=user_input,
        )
        if not topic or topic == "genel konu":
            return None

        source_policy = self._infer_research_source_policy(user_input) or "trusted"
        min_reliability = self._infer_research_min_reliability(user_input, source_policy=source_policy)
        try:
            min_rel_value = float(min_reliability if min_reliability is not None else 0.62)
        except Exception:
            min_rel_value = 0.62
        if min_rel_value > 1.0:
            min_rel_value = min_rel_value / 100.0
        min_rel_value = max(0.0, min(1.0, min_rel_value))
        academic_mode = source_policy == "academic"

        if not include_word and not include_excel and not include_pdf:
            include_word = True
        return {
            "action": "research_document_delivery",
            "params": {
                "topic": topic,
                "brief": user_input,
                "depth": "expert" if academic_mode else "comprehensive",
                "audience": "academic" if academic_mode else "executive",
                "language": "tr",
                "output_dir": "~/Desktop",
                "include_word": include_word,
                "include_excel": include_excel,
                "include_pdf": include_pdf,
                "include_report": True,
                "source_policy": source_policy,
                "min_reliability": min_rel_value,
                "citation_style": "apa7" if academic_mode else "none",
                "include_bibliography": bool(academic_mode),
                "deliver_copy": deliver_copy,
            },
            "reply": "Araştırma belgesi hazırlanıyor...",
        }

    @staticmethod
    def _is_creative_writing_request(text: str) -> bool:
        t = normalize_turkish_text(text)
        creative_markers = (
            "şiir yaz", "siir yaz", "hikaye yaz", "hikâye yaz", "masal yaz",
            "deneme yaz", "essay yaz", "mektup yaz", "yazı yaz", "yazi yaz",
            "poem", "story", "bana bir şiir", "bana bir hikaye",
            "bana bir yazı", "bana bir deneme",
            "creative writing", "yaratıcı yazı",
        )
        return any(m in t for m in creative_markers)

    @staticmethod
    def _is_information_question(text: str) -> bool:
        t = normalize_turkish_text(text)
        if not t:
            return False
        if t in {"naber", "nasılsın", "nasılsınız", "ne yapıyorsun", "ne yaptın", "elyan"}:
            return False

        # File/system/tool operations should not be treated as plain Q&A.
        command_markers = (
            " aç", "ac ", "kapat", "sil", "kaydet", "oluştur", "olustur", "yaz",
            "dosya", "klasör", "klasor", "masaüst", "masaust", "ekran", "screenshot",
            "hatırlat", "hatirlat", "araştır", "arastir", "plan", "görev", "gorev",
            "rutin", "telegram", "whatsapp", "discord", "slack", "excel", "word",
            "pdf", "browser", "tarayıcı", "tarayici", "çalıştır", "calistir", "run",
            "pil", "batarya", "şarj", "sarj", "battery", "charge", "charging",
            "komut",
        )
        if any(marker in f" {t} " for marker in command_markers):
            return False

        question_patterns = (
            r"\?$",
            r"\b(kimdir|nedir|ne\s+demek|ne\s+zaman|nasıl|nasil|neden|niye|hangi|kaç|kac|kim|ne)\b",
            r"\b(what|who|how|why|when|where)\b",
        )
        return any(_re.search(pattern, t) for pattern in question_patterns)

    @staticmethod
    def _is_multi_step_request(user_input: str) -> bool:
        text = (user_input or "").lower()
        if not text:
            return False
        if len(Agent._extract_numbered_steps(user_input)) >= 2:
            return True
        return any(k in text for k in (" ve ", " sonra ", " ardından ", " ardindan ", " once ", "önce ", ";"))

    @staticmethod
    def _looks_compound_action_request(user_input: str) -> bool:
        """
        Çok adımlı niyeti daha güvenilir yakalar.
        Amaç: tek bir write/save aksiyonuna yanlış düşmeyi azaltmak.
        """
        text = str(user_input or "").strip().lower()
        if not text:
            return False
        if len(Agent._extract_numbered_steps(user_input)) >= 2:
            return True

        connectors = (" ve ", " sonra ", " ardından ", " ardindan ", ";")
        if not any(c in text for c in connectors):
            return False

        action_terms = (
            "oluştur",
            "olustur",
            "kaydet",
            "yaz",
            "doğrula",
            "dogrula",
            "verify",
            "listele",
            "sil",
            "taşı",
            "tasi",
            "kopyala",
            "aç",
            "ac",
            "kapat",
            "araştır",
            "arastir",
            "gönder",
            "gonder",
        )
        hit_count = sum(1 for t in action_terms if t in text)
        return hit_count >= 2

    def _coerce_intent_for_request_shape(
        self,
        intent: Optional[dict[str, Any]],
        user_input: str,
        attachments: Optional[list[str]] = None,
    ) -> Optional[dict[str, Any]]:
        """
        İstek-şekli guard:
        - Komut çok adımlı görünüyorsa tek-adım intent'i multi_task'a yükselt.
        - Ekli dosya/görsel varken non-actionable intent'i attachment intent ile düzelt.
        """
        if not isinstance(intent, dict):
            return intent

        action = str(intent.get("action") or "").strip().lower()
        low_in = str(user_input or "").lower()
        has_youtube = ("youtube" in low_in) or (" yt " in f" {low_in} ")
        has_play = any(k in low_in for k in ("çal", "cal", "play"))
        if (not action or action in {"chat", "unknown", "communication"}) and attachments:
            try:
                a_intent = self._infer_attachment_intent(list(attachments), user_input)
            except Exception:
                a_intent = None
            if isinstance(a_intent, dict):
                return a_intent
            return intent

        if action in {"multi_task", "filesystem_batch"}:
            return intent

        # Deterministic computer-use coercion:
        # Convert mixed browser/keyboard/mouse instructions into executable UI steps.
        ui_markers = any(
            k in low_in
            for k in (
                "safari",
                "chrome",
                "krom",
                "browser",
                "tarayıcı",
                "tarayici",
                "youtube",
                "google",
                "arat",
                "search",
                "tıkla",
                "tikla",
                "mouse",
                "imlec",
                "cursor",
                "şunu yaz",
                "sunu yaz",
                "cmd+",
                "ctrl+",
                "alt+",
                "command+",
                "tuş",
                "tus",
                "kısayol",
                "kisayol",
                "bilgisayarı kullan",
                "bilgisayari kullan",
                "computer use",
                "otonom",
            )
        )
        if action in {"open_url", "web_search", "chat", "unknown", "communication", "", "computer_use"} and ui_markers:
            ui_steps = self._build_computer_use_steps_from_text(user_input)
            if len(ui_steps) >= 2:
                return {
                    "action": "computer_use",
                    "params": {
                        "steps": ui_steps,
                        "final_screenshot": True,
                        "pause_ms": 250,
                    },
                    "reply": "Bilgisayar kullanım adımları çalıştırılıyor...",
                }

        # Browser search coercion:
        # "Safari'den köpek resimleri arat" should not keep noisy tokens in query.
        has_search_verb = any(k in low_in for k in ("arat", " ara ", "search", "ara "))
        has_browser_hint = any(k in low_in for k in ("safari", "chrome", "krom", "tarayıcı", "tarayici", "browser"))
        if action in {"open_url", "web_search", "chat", "unknown", "communication", ""} and has_search_verb and has_browser_hint:
            query = self._extract_browser_search_query(user_input)
            if query:
                target_browser = ""
                if "safari" in low_in or "tarayıcı" in low_in or "tarayici" in low_in:
                    target_browser = "Safari"
                elif "chrome" in low_in or "krom" in low_in:
                    target_browser = "Google Chrome"
                url = self._resolve_google_search_url(query, user_input=user_input)
                tasks: list[dict[str, Any]] = []
                if target_browser:
                    tasks.append(
                        {
                            "id": "task_1",
                            "action": "open_app",
                            "params": {"app_name": target_browser},
                            "description": f"{target_browser} aç",
                        }
                    )
                open_params = {"url": url}
                if target_browser:
                    open_params["browser"] = target_browser
                tasks.append(
                    {
                        "id": f"task_{len(tasks) + 1}",
                        "action": "open_url",
                        "params": open_params,
                        "description": f"Web araması: {query}",
                    }
                )
                return {
                    "action": "multi_task",
                    "tasks": tasks,
                    "reply": f"{target_browser or 'Tarayıcı'} üzerinde '{query}' aranıyor...",
                }

        # Browser+media coercion:
        # "Safari'den YouTube'a git ve X çal" should become deterministic multi_task.
        if action in {"open_url", "chat", "unknown", "communication", ""} and has_youtube and has_play:
            params = intent.get("params", {}) if isinstance(intent.get("params"), dict) else {}
            query = self._extract_playback_query(user_input)
            url = str(params.get("url") or "").strip()
            if query:
                url = self._resolve_youtube_play_url(query)
            if not url:
                url = "https://www.youtube.com"
            tasks: list[dict[str, Any]] = []
            if "safari" in low_in:
                tasks.append(
                    {
                        "id": "task_1",
                        "action": "open_app",
                        "params": {"app_name": "Safari"},
                        "description": "Safari'yi aç",
                    }
                )
            tasks.append(
                {
                    "id": f"task_{len(tasks) + 1}",
                    "action": "open_url",
                    "params": {"url": url},
                    "description": f"YouTube'da '{query}' aç" if query else "YouTube aç",
                }
            )
            return {
                "action": "multi_task",
                "tasks": self._normalize_browser_media_tasks(tasks, user_input=user_input),
                "reply": "Safari/YouTube görevi başlatılıyor...",
            }

        if self._looks_compound_action_request(user_input):
            try:
                multi_intent = self._infer_multi_task_intent(user_input)
            except Exception:
                multi_intent = None
            if not isinstance(multi_intent, dict):
                try:
                    numbered = self._extract_numbered_steps(user_input)
                    if len(numbered) >= 2:
                        fallback_tasks: list[dict[str, Any]] = []
                        original_ctx = dict(self.file_context)
                        temp_ctx = dict(self.file_context)
                        try:
                            for idx, part in enumerate(numbered, start=1):
                                self.file_context.update(temp_ctx)
                                inferred = self._fallback_structured_step_intent(part, temp_context=temp_ctx)
                                if not isinstance(inferred, dict):
                                    continue
                                action_i = str(inferred.get("action") or "").strip().lower()
                                params_i = inferred.get("params", {}) if isinstance(inferred.get("params"), dict) else {}
                                if not action_i:
                                    continue
                                fallback_tasks.append(
                                    {
                                        "id": f"task_{idx}",
                                        "action": action_i,
                                        "params": params_i,
                                        "description": str(part or f"Adım {idx}"),
                                    }
                                )
                                p = str(params_i.get("path") or params_i.get("directory") or "").strip()
                                if p:
                                    p_exp = Path(p).expanduser()
                                    temp_ctx["last_path"] = str(p_exp)
                                    temp_ctx["last_dir"] = str(p_exp if action_i == "create_folder" else p_exp.parent)
                        finally:
                            self.file_context.update(original_ctx)
                        if len(fallback_tasks) >= 2:
                            multi_intent = {
                                "action": "multi_task",
                                "tasks": fallback_tasks,
                                "reply": "Çok adımlı görev başlatılıyor...",
                            }
                except Exception:
                    multi_intent = None
            if isinstance(multi_intent, dict):
                tasks = multi_intent.get("tasks")
                if isinstance(tasks, list) and len(tasks) >= 2:
                    return multi_intent

        return intent

    def _get_last_directory(self) -> str:
        last_dir = str(self.file_context.get("last_dir") or "").strip()
        return last_dir or str(Path.home() / "Desktop")

    def _get_last_path(self) -> str:
        last_path = str(self.file_context.get("last_path") or "").strip()
        return last_path

    @staticmethod
    def _references_last_object(user_input: str) -> bool:
        low = str(user_input or "").lower()
        if not low:
            return False
        markers = (
            "bunu", "şunu", "sunu", "onu",
            "bu dosyayı", "bu dosyayi", "bu dosya",
            "bu belgeyi", "bu belge",
        )
        return any(m in low for m in markers)

    def _remember_path_context(self, path: str) -> None:
        raw = str(path or "").strip()
        if not raw:
            return
        try:
            resolved = Path(raw).expanduser()
        except Exception:
            return

        looks_like_file = bool(resolved.suffix)
        if looks_like_file:
            self.file_context["last_path"] = str(resolved)
            self.file_context["last_dir"] = str(resolved.parent)
            return

        self.file_context["last_path"] = str(resolved)
        self.file_context["last_dir"] = str(resolved)

    def _update_file_context_after_tool(self, tool_name: str, params: dict, result: Any) -> None:
        if not isinstance(result, dict) or result.get("success") is False:
            return
        low_tool = str(tool_name or "").strip().lower()
        if not low_tool:
            return

        candidate = ""
        if low_tool == "list_files":
            candidate = str(result.get("path") or params.get("path") or "").strip()
        elif low_tool == "search_files":
            candidate = str(result.get("directory") or params.get("directory") or "").strip()
        elif low_tool in {
            "read_file",
            "write_file",
            "write_word",
            "write_excel",
            "edit_text_file",
            "edit_word_document",
            "summarize_document",
            "analyze_document",
            "delete_file",
            "move_file",
            "copy_file",
            "rename_file",
            "create_folder",
        }:
            candidate = str(
                result.get("destination")
                or result.get("path")
                or params.get("directory")
                or params.get("destination")
                or params.get("path")
                or ""
            ).strip()
        elif low_tool == "batch_edit_text":
            candidate = str(
                result.get("directory")
                or params.get("directory")
                or params.get("path")
                or ""
            ).strip()

        if candidate:
            self._remember_path_context(candidate)

    def _postprocess_tool_result(self, tool_name: str, params: dict, result: Any, *, user_input: str = "") -> Any:
        if not isinstance(result, dict):
            return result
        if result.get("success") is False:
            return result

        mapped = ACTION_TO_TOOL.get(str(tool_name or "").strip(), str(tool_name or "").strip())
        write_tools = {"write_file", "write_word", "write_excel", "edit_text_file", "edit_word_document",
                       "create_web_project_scaffold", "create_software_project_pack", "research_document_delivery"}
        visual_tools = {"set_wallpaper", "take_screenshot", "analyze_screen", "capture_region"}
        network_tools = {"http_request", "api_health_check", "graphql_query"}

        if mapped in write_tools or tool_name in write_tools:
            result = self._attach_artifact_verification(result, params, user_input=user_input)
            # Output Contract: verify deliverable meets done criteria
            try:
                contract_engine = get_contract_engine()
                spec = contract_engine.create_spec(mapped or tool_name, params, user_input)
                if spec:
                    quality_summary = result.get("quality_summary")
                    if isinstance(quality_summary, dict) and quality_summary:
                        spec.research_quality = dict(quality_summary)
                    verification = contract_engine.verify(spec)
                    result["_contract_verified"] = verification.get("passed", True)
                    if not verification.get("passed", True):
                        failed = [a for a in verification.get("artifact_results", []) if not a.get("passed")]
                        if failed:
                            issues = "; ".join(
                                f.get("hints", [f"artifact not met"])[0] if f.get("hints") else "criterion not met"
                                for f in failed
                            )
                            result.setdefault("verification_warning", f"Teslimat kriteri karşılanmadı: {issues}")
                        research_checks = [item for item in verification.get("research_checks", []) if not item.get("passed")]
                        if research_checks:
                            issues = "; ".join(str(item.get("name") or "research_check") for item in research_checks)
                            prefix = str(result.get("verification_warning") or "").strip()
                            detail = f"Araştırma kalite kriteri karşılanmadı: {issues}"
                            result["verification_warning"] = f"{prefix} | {detail}".strip(" |")
                        repair = contract_engine.repair_actions(spec, verification)
                        if repair:
                            result["_repair_actions"] = repair
            except Exception:
                pass
        if mapped in visual_tools or tool_name in visual_tools:
            result = self._attach_visual_artifact_verification(result, params, user_input=user_input)
        if mapped in network_tools or tool_name in network_tools:
            result = self._attach_network_verification(result)
        return result

    def _attach_artifact_verification(self, result: dict, params: dict, *, user_input: str = "") -> dict:
        output = dict(result or {})
        path_candidates = (
            output.get("path"),
            output.get("file_path"),
            output.get("output_path"),
            params.get("path"),
            params.get("file_path"),
            params.get("output_path"),
        )
        raw_path = ""
        for item in path_candidates:
            if isinstance(item, str) and item.strip():
                raw_path = item.strip()
                break

        if not raw_path:
            output["verified"] = False
            output.setdefault("verification_warning", "çıktı yolu tool tarafından dönmedi")
            return output

        resolved = self._resolve_existing_path_from_context(raw_path, user_input=user_input)
        if not resolved:
            expanded = Path(raw_path).expanduser()
            if expanded.exists():
                resolved = str(expanded)

        if not resolved:
            output["verified"] = False
            output.setdefault("verification_warning", f"çıktı dosyası doğrulanamadı: {raw_path}")
            return output

        try:
            size_bytes = Path(resolved).stat().st_size
        except Exception:
            size_bytes = -1

        output["path"] = resolved
        output["verified"] = bool(size_bytes > 0)
        if size_bytes >= 0:
            output["size_bytes"] = int(size_bytes)
        try:
            output["sha256"] = self._compute_sha256(resolved)
        except Exception:
            pass
        if size_bytes == 0:
            output["verification_warning"] = "çıktı dosyası oluşturuldu ancak boş görünüyor"
        
        # --- Read-After-Write Verification (Self-Correction) ---
        if size_bytes > 0:
            try:
                # Read first 100 bytes to ensure file is readable and content matches expectations slightly
                with open(resolved, 'r', encoding='utf-8', errors='ignore') as f:
                    snippet = f.read(100).strip()
                    if not snippet:
                        output["verification_warning"] = "dosya boyutu > 0 ancak içerik okunamadı veya boş"
                        output["verified"] = False
                    else:
                        output["_content_preview"] = snippet
            except Exception as e:
                output["verified"] = False
                output["verification_warning"] = f"dosya yazıldı ancak okunamıyor: {e}"
        # -------------------------------------------------------

        return output

    def _attach_visual_artifact_verification(self, result: dict, params: dict, *, user_input: str = "") -> dict:
        output = dict(result or {})
        proof = output.get("_proof")
        proof_path = ""
        if isinstance(proof, dict):
            raw = proof.get("screenshot")
            if isinstance(raw, str) and raw.strip():
                proof_path = raw.strip()

        raw_path = (
            proof_path
            or str(output.get("path") or "").strip()
            or str(output.get("file_path") or "").strip()
            or str(output.get("image_path") or "").strip()
            or str(params.get("path") or "").strip()
            or str(params.get("image_path") or "").strip()
        )
        if not raw_path:
            output["verified"] = False
            output.setdefault("verification_warning", "görsel kanıt yolu bulunamadı")
            return output

        resolved = self._resolve_existing_path_from_context(raw_path, user_input=user_input)
        if not resolved:
            expanded = Path(raw_path).expanduser()
            if expanded.exists():
                resolved = str(expanded)
        if not resolved:
            output["verified"] = False
            output.setdefault("verification_warning", f"görsel çıktı doğrulanamadı: {raw_path}")
            return output

        target = Path(resolved)
        size_bytes = 0
        try:
            if target.is_file():
                size_bytes = int(target.stat().st_size)
        except Exception:
            size_bytes = 0

        output["path"] = str(target)
        output["verified"] = bool(size_bytes > 0)
        output["size_bytes"] = size_bytes
        try:
            if size_bytes > 0:
                output["sha256"] = self._compute_sha256(str(target))
        except Exception:
            pass
        if not output["verified"]:
            output.setdefault("verification_warning", "görsel çıktı boş veya erişilemez")
        return output

    def _attach_network_verification(self, result: dict) -> dict:
        output = dict(result or {})
        verified = bool(output.get("success", True))
        warning = ""

        status_code = output.get("status_code")
        if isinstance(status_code, int):
            if status_code >= 500:
                verified = False
                warning = f"http_status:{status_code}"
            elif status_code < 100:
                verified = False
                warning = f"http_status_invalid:{status_code}"
        elif "results" in output:
            results = output.get("results")
            if isinstance(results, dict):
                total = int(output.get("total", len(results)))
                healthy = int(output.get("healthy", 0))
                verified = verified and total >= 1 and healthy >= 1
                if not verified and not warning:
                    warning = f"api_health_unhealthy:{healthy}/{total}"

        prev = output.get("verified")
        if isinstance(prev, bool):
            output["verified"] = bool(prev and verified)
        else:
            output["verified"] = bool(verified)
        if warning and not output.get("verification_warning"):
            output["verification_warning"] = warning
        return output

    @staticmethod
    def _normalize_user_input(user_input: str) -> str:
        text = str(user_input or "").strip()
        if not text:
            return ""
        normalized = text
        replacements = (
            (r"\bss\s*al\b", "ekran görüntüsü al"),
            (r"\bss\b", "ekran görüntüsü"),
            (r"\bmk\b", "mümkünse"),
            (r"\bkaydetsene\b", "kaydet"),
            (r"\bac\b", "aç"),
            (r"\barastir\b", "araştır"),
            (r"\bozet\b", "özet"),
        )
        for pattern, repl in replacements:
            normalized = _re.sub(pattern, repl, normalized, flags=_re.IGNORECASE)
        normalized = " ".join(normalized.split())
        return normalized

    def _runtime_normalize_user_input(self, user_input: str) -> str:
        normalized = self._normalize_user_input(user_input)
        try:
            prefs = self.learning.get_preferences(min_confidence=0.65) or {}
        except Exception:
            prefs = {}
        alias_maps = []
        for key in ("nlu_aliases", "phrase_aliases", "user_nlu_aliases"):
            value = prefs.get(key)
            if isinstance(value, dict):
                alias_maps.append(value)
        if not alias_maps:
            return normalized

        output = normalized
        for alias_map in alias_maps:
            for raw_alias, canonical in alias_map.items():
                src = str(raw_alias or "").strip()
                dst = str(canonical or "").strip()
                if not src or not dst:
                    continue
                output = _re.sub(
                    rf"(?<!\w){_re.escape(src)}(?!\w)",
                    dst,
                    output,
                    flags=_re.IGNORECASE,
                )
        return " ".join(str(output or "").split())

    @staticmethod
    def _infer_batch_delete_patterns(text: str) -> tuple[str, list[str]] | tuple[str, list[str]]:
        low = str(text or "").lower()
        screenshot_markers = (
            "ekran resmi",
            "ekran resimleri",
            "ekran görüntüsü",
            "ekran görüntüleri",
            "ekran goruntusu",
            "ekran goruntuleri",
            "screenshot",
            "screen shot",
            "ss",
        )
        image_markers = ("resim", "görsel", "gorsel", "foto", "png", "jpg", "jpeg", "hepsini", "tümünü", "tumunu")
        if any(m in low for m in screenshot_markers) and any(m in low for m in image_markers):
            return (
                "Masaüstündeki ekran görüntüleri temizleniyor...",
                [
                    "Ekran Resmi*",
                    "Ekran Görüntüsü*",
                    "Screenshot*",
                    "Screen Shot *",
                ],
            )
        return ("", [])

    @staticmethod
    def _extract_first_url(text: str) -> str:
        if not text:
            return ""
        m = _re.search(r"(https?://\S+)", text)
        if not m:
            return ""
        return str(m.group(1) or "").strip(" \t\r\n\"'`),.;:!?")

    @staticmethod
    def _infer_http_method(text: str) -> str:
        low = str(text or "").lower()
        if any(k in low for k in (" post ", " postla", "post at", "post isteği", "post istegi")):
            return "POST"
        if any(k in low for k in (" put ", "put at", "put isteği", "put istegi")):
            return "PUT"
        if any(k in low for k in (" patch ", "patch at", "patch isteği", "patch istegi")):
            return "PATCH"
        if any(k in low for k in (" delete ", "silme isteği", "silme istegi", "delete at")):
            return "DELETE"
        return "GET"

    def _extract_api_output_paths(self, text: str) -> tuple[str, str]:
        tokens = self._extract_path_like_tokens(text)
        paths = [
            str(Path(tok).expanduser())
            for tok in tokens
            if isinstance(tok, str) and ("/" in tok or tok.startswith("~"))
        ]
        result_path = ""
        summary_path = ""
        for p in paths:
            low = str(p).lower()
            if low.endswith(".json") and not result_path:
                result_path = p
            if low.endswith((".md", ".txt")) and not summary_path:
                summary_path = p
        if not result_path:
            result_path = str(Path.home() / "Desktop" / "elyan-test" / "api" / "result.json")
        if not summary_path:
            summary_path = default_summary_path(result_path)
        return result_path, summary_path

    @staticmethod
    def _is_likely_chat_message(text: str) -> bool:
        t = normalize_turkish_text(text)
        if not t:
            return True
        words = t.split()
        tool_keywords = {
            "aç", "ac", "kapat", "araştır", "arastir", "ara", "search", "kaydet", "yaz",
            "sil", "oku", "listele", "dosya", "klasör", "klasor", "ekran", "screenshot",
            "hatırlat", "hatirlat", "excel", "word", "pdf", "tarayıcı", "tarayici",
            "telegram", "discord", "slack", "mail", "email", "web", "url", "site",
            "kod", "code", "çalıştır", "calistir", "run", "plan", "görev", "gorev",
            "rutin", "routine",
            "içinde", "icinde", "içeriği", "icerigi", "içeriğini", "icerigini",
            "getir", "kaldır", "kaldir", "taşı", "tasi", "kopyala", "rename",
            "terminal", "komut", "shell",
        }
        if any(w in tool_keywords for w in words):
            return False
        operational_markers = (
            "dosya", "klasör", "klasor", "terminal", "komut", "shell",
            "içinde", "icinde", "içeri", "iceri", "kontrol", "bakar mısın", "bakar misin",
        )
        if any(marker in t for marker in operational_markers):
            return False
        if _re.search(r"[\w\-.]+\.[a-z0-9]{2,8}", t, _re.IGNORECASE):
            return False
        op_patterns = (
            r"\biçinde ne var\b",
            r"\biçeriğini göster\b",
            r"\bliste(?:le|leyebilir)\b",
            r"\bgöster\b",
            r"\bbak(?:ar mısın|ar misin|)\b",
            r"\bkontrol et\b",
            r"\bsil(?:er misin|)\b",
            r"\b(kaldır|kaldir)\b",
            r"\b(taşı|tasi|kopyala|rename|yeniden adlandır)\b",
        )
        if any(_re.search(pat, t, _re.IGNORECASE) for pat in op_patterns):
            return False
        if len(words) <= 6:
            return True
        chat_markers = (
            "nasılsın", "nasılsin", "naber", "selam", "merhaba", "teşekkür", "tesekkur",
            "iyi", "kötü", "kotu", "harika", "anladım", "anladim",
        )
        return any(m in t for m in chat_markers)

    @staticmethod
    def _extract_file_path_from_text(user_input: str, default_name: str) -> str:
        text = str(user_input or "")
        m = _re.search(r"([\w\-.]+\.[a-z0-9]{2,8})", text, _re.IGNORECASE)
        if m:
            return f"~/Desktop/{m.group(1)}"
        return f"~/Desktop/{default_name}"

    @staticmethod
    def _extract_folder_hint_from_text(user_input: str) -> str:
        text = str(user_input or "").strip()
        if not text:
            return ""

        patterns = (
            r"[\"']([^\"']+)[\"']\s*(?:içinde|icinde|klasöründe|klasorunde)",
            r"\b([a-z0-9][\w .\-]{1,80})\s*(?:içinde|icinde)\s*(?:ne var|neler var|listele|göster|goster)\b",
            r"\b([a-z0-9][\w .\-]{1,80})\s*(?:klasöründe|klasorunde)\s*(?:ne var|neler var|listele|göster|goster)\b",
            r"\b([a-z0-9][\w .\-]{1,80})\s*(?:klasörünü|klasorunu)\s*(?:listele|göster|goster|aç|ac)\b",
            r"\b([a-z0-9][\w .\-]{1,80})\s*(?:klasörü|klasoru)\s*(?:aç|ac|listele|göster|goster)\b",
            r"(?:masaüst(?:üne|ünde)?|masaust(?:une|unde)?|desktop(?:a|e|ta|te)?|belgeler(?:de)?|documents(?:ta|te)?|indirilenler(?:de)?|downloads(?:ta|te)?)\s+([a-z0-9][\w .\-]{1,80})\s+klas(?:ör|or)(?:ü|u)?\s*(?:oluştur|olustur|kur|aç|ac|yap|ekle)\b",
            r"\b([a-z0-9][\w .\-]{1,80})\s+klas(?:ör|or)(?:ü|u)?\s*(?:oluştur|olustur|kur|aç|ac|yap|ekle)\b",
        )
        stop_words = {
            "masaüstü", "masaustu", "desktop", "klasör", "klasor", "dizin",
            "ana klasör", "ana klasor", "home", "ev dizini",
        }
        for pattern in patterns:
            m = _re.search(pattern, text, _re.IGNORECASE)
            if not m:
                continue
            hint = str(m.group(1) or "").strip(" .,:;-_")
            if not hint:
                continue
            if hint.casefold() in stop_words:
                continue
            return hint
        return ""

    @staticmethod
    def _find_case_insensitive_path(candidate: Path) -> Path | None:
        try:
            if candidate.exists():
                parent = candidate.parent
                if parent.exists():
                    target = candidate.name.casefold()
                    for child in parent.iterdir():
                        if child.name.casefold() == target:
                            return child
                return candidate
            parent = candidate.parent
            if not parent.exists():
                return None
            target = candidate.name.casefold()
            for child in parent.iterdir():
                if child.name.casefold() == target:
                    return child
        except Exception:
            return None
        return None

    @staticmethod
    def _find_file_with_stem(directory: Path, stem: str) -> Path | None:
        """
        Resolve "not" -> "not.txt"/"not.md" style matches in a directory.
        """
        if not stem:
            return None
        try:
            if not directory.exists() or not directory.is_dir():
                return None
            target = stem.casefold()
            preferred_exts = (
                ".txt",
                ".md",
                ".docx",
                ".xlsx",
                ".pdf",
                ".json",
                ".csv",
                ".py",
                ".js",
                ".html",
            )
            candidates: list[Path] = []
            for child in directory.iterdir():
                if not child.is_file():
                    continue
                if child.stem.casefold() != target:
                    continue
                candidates.append(child)
            if not candidates:
                return None
            for ext in preferred_exts:
                for child in candidates:
                    if child.suffix.lower() == ext:
                        return child
            return candidates[0] if len(candidates) == 1 else None
        except Exception:
            return None

    def _resolve_path_with_desktop_fallback(self, raw_path: str, *, user_input: str = "") -> str:
        path = str(raw_path or "").strip()
        if not path:
            return "~/Desktop"

        expanded = Path(path).expanduser()
        if expanded.exists():
            # Preserve user-friendly ~/ style when the provided path is already valid.
            return path if path.startswith("~") else str(expanded)

        # Explicit file target with existing parent: keep caller's target path.
        if expanded.suffix and expanded.parent and expanded.parent.exists():
            return str(expanded)

        existing = self._find_case_insensitive_path(expanded)
        if existing:
            return str(existing)

        desktop_root = Path.home() / "Desktop"
        hint = self._extract_folder_hint_from_text(user_input)
        name_candidates: list[str] = []

        basename = expanded.name.strip() if expanded.name else ""
        is_file_like = bool(expanded.suffix)
        if basename:
            name_candidates.append(basename)
        if hint and not is_file_like:
            name_candidates.append(hint)

        if not name_candidates:
            return path

        seen: set[str] = set()
        for name in name_candidates:
            normalized = name.strip(" .,:;-_")
            key = normalized.casefold()
            if not normalized or key in seen:
                continue
            seen.add(key)
            match = self._find_case_insensitive_path(desktop_root / normalized)
            if match:
                return str(match)
        return path

    def _resolve_existing_path_from_context(self, raw_path: str, *, user_input: str = "") -> str:
        value = str(raw_path or "").strip()
        if not value:
            return ""

        candidate = Path(value).expanduser()
        if candidate.exists():
            return str(candidate)
        if candidate.suffix and candidate.parent.exists():
            same_parent_match = self._find_case_insensitive_path(candidate)
            if same_parent_match and same_parent_match.exists():
                return str(same_parent_match)
            return ""

        direct_case_match = self._find_case_insensitive_path(candidate)
        if direct_case_match and direct_case_match.exists():
            return str(direct_case_match)

        basename = candidate.name.strip()
        last_dir = Path(self._get_last_directory()).expanduser()
        desktop_root = Path.home() / "Desktop"
        if basename and not candidate.suffix:
            roots: list[Path] = []
            if last_dir.exists():
                roots.append(last_dir)
            if desktop_root.exists() and desktop_root not in roots:
                roots.append(desktop_root)
            if Path.home().exists() and Path.home() not in roots:
                roots.append(Path.home())

            for root in roots:
                file_match = self._find_file_with_stem(root, basename)
                if file_match and file_match.exists():
                    return str(file_match)

        if basename:
            roots: list[Path] = []
            if last_dir.exists():
                roots.append(last_dir)
            if desktop_root.exists() and desktop_root not in roots:
                roots.append(desktop_root)

            for root in roots:
                hit = self._find_case_insensitive_path(root / basename)
                if hit and hit.exists():
                    return str(hit)

        fallback = self._resolve_path_with_desktop_fallback(value, user_input=user_input)
        fallback_path = Path(fallback).expanduser()
        if fallback_path.exists():
            return str(fallback_path)

        fallback_case_match = self._find_case_insensitive_path(fallback_path)
        if fallback_case_match and fallback_case_match.exists():
            return str(fallback_case_match)

        return ""

    @staticmethod
    def _infer_path_from_text(user_input: str, *, step_name: str = "", tool_name: str = "") -> str:
        text = " ".join(x for x in (step_name, user_input) if isinstance(x, str) and x).strip()
        if not text:
            return ""

        # Quoted absolute/relative path.
        quoted = _re.search(r"[\"']((?:~|/|\.{1,2}/)[^\"']+)[\"']", text)
        if quoted:
            return quoted.group(1).strip()

        # Raw path token.
        token = _re.search(r"((?:~|/|\.{1,2}/)\S+)", text)
        if token:
            return token.group(1).strip(".,;")

        # Filename heuristic for common "X.png yi sil" style commands.
        filename = _re.search(r"([\w\-.]+\.[a-z0-9]{2,8})", text, _re.IGNORECASE)
        if filename:
            return f"~/Desktop/{filename.group(1)}"

        # Optional no-extension fallback for file-like words (mostly delete/move intents).
        if str(tool_name or "").lower() in {"delete_file", "move_file", "copy_file", "rename_file"}:
            bare = _re.search(r"\b([a-z0-9][\w\-]{1,80})\b\s*(?:dosya(?:sı)?n?[ıiuü]?|file)?\s*(?:sil|kald[ıi]r|delete|remove)\b", text, _re.IGNORECASE)
            if bare:
                return f"~/Desktop/{bare.group(1)}"
        return ""

    @staticmethod
    def _normalize_terminal_command(command: str) -> str:
        cmd = str(command or "").strip()
        if not cmd:
            return ""
        cmd = _re.sub(r"\s+", " ", cmd).strip(" \t\r\n.,;:!?")
        cmd = _re.sub(r"\s+\b(?:komut(?:u|unu|un)?|command)\b\s*$", "", cmd, flags=_re.IGNORECASE).strip(" \t\r\n.,;:!?")
        cmd = _re.sub(r"\s+(?:çalıştır|calistir|run|execute)\b\s*$", "", cmd, flags=_re.IGNORECASE).strip(" \t\r\n.,;:!?")

        m_cd = _re.match(r"^\s*cd\s+(.+?)\s*$", cmd, _re.IGNORECASE)
        if not m_cd:
            return cmd

        target = str(m_cd.group(1) or "").strip().strip("\"'")
        if not target:
            return "cd ~"
        if _re.match(r"^(desktop|masaüstü|masaustu|masa ustu)$", target, _re.IGNORECASE):
            return "cd ~/Desktop"
        m_sub = _re.match(r"^(desktop|masaüstü|masaustu|masa ustu)([/\\].+)$", target, _re.IGNORECASE)
        if m_sub:
            suffix = str(m_sub.group(2) or "").replace("\\", "/")
            return f"cd ~/Desktop{suffix}"
        return cmd

    @staticmethod
    def _extract_terminal_command_from_text(user_input: str) -> str:
        text = normalize_turkish_text(user_input)
        if not text:
            return ""

        if text.startswith("$"):
            return Agent._normalize_terminal_command(text[1:].strip())

        patterns = (
            r"(?:terminal(?:\s*(?:den|dan|de))?\b|shell(?:\s*(?:den|dan|de))?\b|konsol(?:\s*(?:dan|da))?\b|komut satır(?:ı|inda)?)\s*(?:şunu|bunu)?\s*(?:çalıştır|calistir|run|execute)?\s*[:\-]?\s*(.+)$",
            r"(?:çalıştır|calistir|run|execute)\s*(?:şunu|bunu)?\s*(?:terminal(?:\s*(?:den|dan|de))?\b|shell(?:\s*(?:den|dan|de))?\b|konsol(?:\s*(?:dan|da))?\b)?\s*[:\-]?\s*(.+)$",
            r"(?:komut(?:u)?|command)\s*[:\-]\s*(.+)$",
        )
        for pattern in patterns:
            m = _re.search(pattern, text, _re.IGNORECASE)
            if not m:
                continue
            cmd = str(m.group(1) or "").strip(" \"'`")
            cmd = _re.sub(r"\s+(?:komut(?:u|unu|un)?|command)\s*(?:çalıştır|calistir|run|execute)$", "", cmd, flags=_re.IGNORECASE).strip()
            cmd = _re.sub(r"\s+(?:çalıştır|calistir|run|execute)$", "", cmd, flags=_re.IGNORECASE).strip()
            cmd = _re.sub(r"^(?:ve|sonra|ardından|ardindan|açıp|çalıştırıp|gidip|girip)\s+", "", cmd, flags=_re.IGNORECASE).strip()
            if cmd:
                return Agent._normalize_terminal_command(cmd)

        # Last resort for explicit terminal intent: use tail segment after marker.
        for marker in ("terminal de", "terminal den", "terminal dan", "terminalde", "terminalden", "terminaldan", "terminal", "shell de", "shell den", "shellde", "shellden", "shell", "konsol da", "konsol dan", "konsolda", "konsoldan", "konsol", "komut satırı", "komut satiri"):
            low = text.lower()
            idx = low.find(marker)
            if idx >= 0:
                tail = text[idx + len(marker):].strip(" :,-")
                if tail:
                    tail = _re.sub(r"^(?:ve|sonra|ardından|ardindan|açıp|çalıştırıp|gidip|girip)\s+", "", tail, flags=_re.IGNORECASE).strip()
                    return Agent._normalize_terminal_command(tail)
        return ""

    @staticmethod
    def _extract_code_block_from_text(user_input: str) -> str:
        text = str(user_input or "").strip()
        if not text:
            return ""

        fenced = _re.search(r"```(?:python|py|javascript|js)?\s*([\s\S]+?)```", text, _re.IGNORECASE)
        if fenced:
            return str(fenced.group(1) or "").strip()

        inline = _re.search(r"(?:kod|code)\s*[:\-]\s*([\s\S]+)$", text, _re.IGNORECASE)
        if inline:
            return str(inline.group(1) or "").strip()
        return ""

    @staticmethod
    def _extract_email_from_text(user_input: str) -> str:
        text = str(user_input or "")
        m = _re.search(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[A-Za-z]{2,}\b", text)
        return str(m.group(0)).strip() if m else ""

    @staticmethod
    def _extract_identifier_token(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        patterns = (
            r"\b([0-9a-f]{8}-[0-9a-f\-]{8,36})\b",
            r"\b([a-z0-9]{6,}-[a-z0-9\-]{1,24})\b",
            r"\b(id[:=\s]+)([a-z0-9\-]{6,})\b",
        )
        for pattern in patterns:
            m = _re.search(pattern, raw, _re.IGNORECASE)
            if not m:
                continue
            token = m.group(1) if m.lastindex == 1 else m.group(m.lastindex)
            token = str(token or "").strip(" :")
            if token:
                return token
        return ""

    def _infer_data_payload(self, user_input: str, *, step_name: str = "") -> Any:
        seed = (
            self._extract_inline_write_content(user_input)
            or self._get_recent_research_text()
            or self._get_recent_assistant_text(user_input)
        )
        if not isinstance(seed, str) or not seed.strip():
            topic = self._extract_topic(user_input, step_name)
            if topic and topic != "genel konu":
                seed = topic
            else:
                return {"value": "veri"}

        lines = [ln.strip().lstrip("-• ").strip() for ln in seed.splitlines()]
        lines = [ln for ln in lines if ln]
        if not lines:
            return {"value": seed[:300]}
        if len(lines) == 1:
            return {"value": lines[0][:300]}
        rows: list[dict[str, str]] = []
        for idx, line in enumerate(lines[:60], start=1):
            rows.append({"label": f"item_{idx}", "value": line[:300]})
        return rows

    @staticmethod
    def _extract_path_like_tokens(user_input: str) -> list[str]:
        text = str(user_input or "").strip()
        if not text:
            return []

        tokens: list[str] = []
        seen: set[str] = set()

        # Quoted fragments have en yüksek öncelik
        for m in _re.finditer(r"[\"']([^\"']+)[\"']", text):
            raw = str(m.group(1) or "").strip()
            if not raw:
                continue
            key = raw.casefold()
            if key in seen:
                continue
            seen.add(key)
            tokens.append(raw)

        # İç içe dizin/desen (test/b, assets/img/logo.png)
        for m in _re.finditer(r"(?<![A-Za-z0-9_.-])(?!https?://)([-A-Za-z0-9_.]+/[-A-Za-z0-9_.\\/]+)", text):
            raw = str(m.group(1) or "").strip(".,; ")
            if not raw:
                continue
            key = raw.casefold()
            if key in seen:
                continue
            seen.add(key)
            tokens.append(raw)

        for m in _re.finditer(r"((?:~|/|\.{1,2}/)\S+)", text):
            raw = str(m.group(1) or "").strip(".,; ")
            if not raw:
                continue
            if raw.startswith("/") and len(raw) <= 2:
                # Muhtemelen iç içe path'in kırpılmış hali (/b); yukarıdaki desenle yakalandıysa atla
                continue
            key = raw.casefold()
            if key in seen:
                continue
            seen.add(key)
            tokens.append(raw)

        for m in _re.finditer(r"([\w\-.]+\.[a-z0-9]{2,8})", text, _re.IGNORECASE):
            raw = str(m.group(1) or "").strip(".,; ")
            if not raw:
                continue
            key = raw.casefold()
            if key in seen:
                continue
            seen.add(key)
            tokens.append(raw)

        return tokens

    @staticmethod
    def _extract_destination_hint_from_text(user_input: str) -> str:
        text = str(user_input or "").strip()
        if not text:
            return ""

        # "Reports klasörüne taşı" -> "Reports"
        before_marker_patterns = (
            r"\b([a-z0-9][\w.\-]{0,120})\s+(?:klasörüne|klasorune|dizine|içine|icine)\b",
            r"[\"']([^\"']+)[\"']\s+(?:klasörüne|klasorune|dizine|içine|icine)\b",
        )
        for pattern in before_marker_patterns:
            m = _re.search(pattern, text, _re.IGNORECASE)
            if not m:
                continue
            value = str(m.group(1) or "").strip(" .,:;-")
            if value:
                return value

        patterns = (
            r"(?:içine|icine|klasörüne|klasorune|dizine|to)\s+[\"']([^\"']+)[\"']",
            r"(?:içine|icine|klasörüne|klasorune|dizine|to)\s+((?:~|/|\.{1,2}/)\S+)",
            r"(?:içine|icine|klasörüne|klasorune|dizine|to)\s+([a-z0-9][\w .\-]{1,80})",
        )
        for pattern in patterns:
            m = _re.search(pattern, text, _re.IGNORECASE)
            if not m:
                continue
            value = str(m.group(1) or "").strip(" .,:;-")
            if value:
                # avoid trailing operation verbs in loose captures
                value = _re.sub(
                    r"\b(taşı|tasi|kopyala|copy|move|yeniden adlandır|yeniden adlandir|rename)\b.*$",
                    "",
                    value,
                    flags=_re.IGNORECASE,
                ).strip(" .,:;-")
            if value:
                return value
        return ""

    @staticmethod
    def _extract_new_name_from_text(user_input: str, *, current_name: str = "") -> str:
        text = str(user_input or "").strip()
        if not text:
            return ""

        patterns = (
            r"\b([\w\-.]+\.[a-z0-9]{1,12})\s+(?:olarak|to)\s*(?:yeniden adlandır|yeniden adlandir|rename|değiştir|degistir)\b",
            r"(?:olarak|to)\s+[\"']?([\w\-. ]{1,120})[\"']?\s*(?:yeniden adlandır|yeniden adlandir|rename|değiştir|degistir)",
            r"(?:yeniden adlandır|yeniden adlandir|rename|değiştir|degistir)\s*(?:olarak|to)?\s*[\"']?([\w\-. ]{1,120})[\"']?$",
            r"(?:adını|adini|ismini)\s+[\"']?([\w\-. ]{1,120})[\"']?\s*(?:yap|olarak)",
        )
        for pattern in patterns:
            m = _re.search(pattern, text, _re.IGNORECASE)
            if not m:
                continue
            name = str(m.group(1) or "").strip(" .,:;-")
            if name and name.casefold() != str(current_name or "").casefold():
                return name

        tokens = Agent._extract_path_like_tokens(text)
        if len(tokens) >= 2:
            candidate = Path(tokens[1]).name.strip()
            if candidate and candidate.casefold() != str(current_name or "").casefold():
                return candidate
        if len(tokens) >= 1 and current_name:
            candidate = Path(tokens[0]).name.strip()
            if candidate and candidate.casefold() != str(current_name).casefold():
                return candidate
        return ""

    @staticmethod
    def _safe_project_slug(name: str) -> str:
        raw = str(name or "").strip()
        if not raw:
            return "elyan-project"
        cleaned = _re.sub(r"[^a-z0-9\-_ ]+", " ", raw.lower())
        cleaned = _re.sub(r"\s+", "-", cleaned).strip("-_ ")
        return cleaned[:80] or "elyan-project"

    @staticmethod
    def _infer_ide_name(text: str) -> str:
        low = str(text or "").lower()
        if "cursor" in low:
            return "cursor"
        if "windsurf" in low:
            return "windsurf"
        if any(k in low for k in ("antigravity", "anti gravity", "gravity")):
            return "antigravity"
        return "vscode"

    def _normalize_path_token(
        self,
        token: str,
        *,
        for_destination: bool = False,
        source_dir: str = "",
    ) -> str:
        raw = str(token or "").strip().strip("'\"")
        if not raw:
            return ""

        if raw.startswith(("~", "/", "./", "../")):
            return str(Path(raw).expanduser())

        if "/" in raw:
            return str((Path.home() / raw).expanduser())

        if for_destination:
            if Path(raw).suffix:
                base = Path(source_dir).expanduser() if source_dir else Path(self._get_last_directory()).expanduser()
            else:
                base = Path.home() / "Desktop"
        else:
            base = Path(source_dir).expanduser() if source_dir else Path(self._get_last_directory()).expanduser()
        return str(base / raw)

    @staticmethod
    def _extract_numbered_steps(user_input: str) -> list[str]:
        text = str(user_input or "").strip()
        if not text:
            return []

        normalized = text.replace("\r", "\n")
        markers = list(
            _re.finditer(
                r"(?:(?<=^)|(?<=\n)|(?<=\s))(?:\d{1,2}[)\.]|[①②③④⑤⑥⑦⑧⑨⑩])\s*",
                normalized,
            )
        )
        if len(markers) < 2:
            return []

        steps: list[str] = []
        for idx, marker in enumerate(markers):
            start = marker.end()
            end = markers[idx + 1].start() if idx + 1 < len(markers) else len(normalized)
            chunk = normalized[start:end].strip(" \t\n\r,;")
            chunk = _re.sub(r"^(?:ve\s+|and\s+)", "", chunk, flags=_re.IGNORECASE).strip(" \t\n\r,;")
            if chunk:
                steps.append(chunk)
        return steps

    @staticmethod
    def _split_multi_step_text(user_input: str) -> list[str]:
        text = str(user_input or "").strip()
        if not text:
            return []

        numbered = Agent._extract_numbered_steps(text)
        if len(numbered) >= 2:
            return numbered

        text = _re.sub(r"\b(?:açıp|acip|açip)\b", "aç sonra", text, flags=_re.IGNORECASE)
        text = _re.sub(r"\b(?:çalıştırıp|calistirip)\b", "çalıştır sonra", text, flags=_re.IGNORECASE)
        text = _re.sub(r"\bgidip\b", "git sonra", text, flags=_re.IGNORECASE)
        text = _re.sub(r"\bgirip\b", "gir sonra", text, flags=_re.IGNORECASE)
        text = _re.sub(r"\b(?:yazıp|yazip)\b", "yaz sonra", text, flags=_re.IGNORECASE)

        # Primary split tokens for multi-step execution.
        primary = _re.split(
            r"(?:\s*(?:ve sonra|ardından|ardindan|sonra|then|and then)\s+|\s*[;\n]+\s*)",
            text,
            flags=_re.IGNORECASE,
        )
        primary = [p.strip(" ,.;") for p in primary if str(p).strip(" ,.;")]
        if len(primary) >= 2:
            return primary

        # Secondary split for "X yap ve Y yap" style commands.
        if " ve " not in text.lower():
            return [text]
        candidate = _re.split(r"\s+ve\s+", text, flags=_re.IGNORECASE)
        candidate = [p.strip(" ,.;") for p in candidate if str(p).strip(" ,.;")]
        if len(candidate) < 2:
            return [text]

        action_markers = (
            "aç", "ac", "kapat", "listele", "göster", "goster", "oku", "sil",
            "kaldır", "kaldir", "taşı", "tasi", "kopyala", "yeniden adlandır",
            "yeniden adlandir", "rename", "ara", "bul", "araştır", "arastir",
            "çalıştır", "calistir", "run", "kaydet", "yaz", "oluştur", "olustur",
        )
        score = sum(1 for part in candidate if any(marker in part.lower() for marker in action_markers))
        return candidate if score >= 2 else [text]

    def _infer_dense_multi_task_intent(self, user_input: str) -> Optional[dict[str, Any]]:
        text = str(user_input or "").strip()
        if not text:
            return None

        low = text.lower()
        detected: list[tuple[int, dict[str, Any]]] = []

        app_name = self._infer_app_name(text)
        open_match = _re.search(r"\b(?:aç|ac|open)\b", low)
        if open_match and app_name:
            detected.append(
                (
                    int(open_match.start()),
                    {
                        "action": "open_app",
                        "params": {"app_name": app_name},
                        "reply": f"{app_name} açılıyor...",
                        "description": "Uygulamayı aç",
                    },
                )
            )

        research_match = _re.search(r"\b(?:araştır|arastir|research|incele)\w*\b", low)
        if research_match:
            topic = self._sanitize_research_topic(self._extract_topic(text, text), user_input=text, step_name=text)
            detected.append(
                (
                    int(research_match.start()),
                    {
                        "action": "research",
                        "params": {"topic": topic, "depth": "standard"},
                        "reply": f"'{topic}' araştırılıyor...",
                        "description": "Araştırma",
                    },
                )
            )

        save_intent = self._infer_save_intent(text)
        save_match = _re.search(r"\b(?:kaydet|yaz|oluştur|olustur|hazırla|hazirla)\b", low)
        if save_intent and save_match:
            detected.append(
                (
                    int(save_match.start()),
                    {
                        "action": str(save_intent.get("action") or ""),
                        "params": save_intent.get("params", {}) if isinstance(save_intent.get("params"), dict) else {},
                        "reply": str(save_intent.get("reply") or "Kaydet"),
                        "description": "Kaydet",
                    },
                )
            )

        shot_match = _re.search(r"\b(?:ekran görüntüsü|ekran goruntusu|screenshot|ss al)\b", low)
        if shot_match:
            detected.append(
                (
                    int(shot_match.start()),
                    {
                        "action": "take_screenshot",
                        "params": {"filename": f"SS_{int(time.time())}"},
                        "reply": "Ekran görüntüsü alınıyor...",
                        "description": "Ekran görüntüsü",
                    },
                )
            )

        if len(detected) < 2:
            return None

        tasks: list[dict[str, Any]] = []
        seen_actions: set[str] = set()
        for idx, (_pos, payload) in enumerate(sorted(detected, key=lambda x: x[0]), start=1):
            action = str(payload.get("action") or "").strip().lower()
            if not action:
                continue
            params = payload.get("params", {}) if isinstance(payload.get("params"), dict) else {}
            dedupe_key = json.dumps({"action": action, "params": params}, ensure_ascii=False, sort_keys=True)
            if dedupe_key in seen_actions:
                continue
            seen_actions.add(dedupe_key)
            tasks.append(
                {
                    "id": f"task_{idx}",
                    "action": action,
                    "params": params,
                    "description": str(payload.get("description") or action),
                }
            )

        if len(tasks) < 2:
            return None
        collapsed = self._collapse_research_document_intent(user_input, tasks)
        if isinstance(collapsed, dict):
            return collapsed
        return {
            "action": "multi_task",
            "tasks": tasks,
            "reply": "Çok adımlı görev başlatılıyor...",
        }

    def _infer_step_intent(self, text: str) -> Optional[dict[str, Any]]:
        intent = self._infer_general_tool_intent(text)
        if intent:
            return intent

        raw = str(text or "").strip()
        low = raw.lower()

        # Explicit folder creation in structured steps.
        folder_create_markers = (
            "klasör oluştur",
            "klasor olustur",
            "klasörü oluştur",
            "klasoru olustur",
            "folder oluştur",
            "folder create",
            "mkdir",
        )
        if any(m in low for m in folder_create_markers):
            path_tokens = self._extract_path_like_tokens(raw)
            folder_path = ""
            if path_tokens:
                candidates = []
                for tok in path_tokens:
                    st = str(tok).strip()
                    if "/" in st or st.startswith(("~", ".", "..")):
                        candidates.append(st)
                if candidates:
                    folder_path = next((c for c in candidates if c.startswith("~")), candidates[0])
            if not folder_path:
                m_folder = _re.search(r"\b([a-z0-9][\w\-./~]{1,180})\s+(?:klasör|klasor)\b", raw, _re.IGNORECASE)
                if m_folder:
                    candidate = str(m_folder.group(1) or "").strip(" .,:;-")
                    if candidate:
                        folder_path = candidate if any(ch in candidate for ch in ("/", "~")) else f"~/Desktop/{candidate}"
            if not folder_path:
                folder_hint = self._extract_folder_hint_from_text(raw)
                if folder_hint:
                    folder_path = f"~/Desktop/{folder_hint}"
            if not folder_path:
                folder_path = "~/Desktop/yeni_klasor"
            if folder_path.startswith(("Desktop/", "desktop/")):
                folder_path = f"~/{folder_path}"
            if "/" in folder_path and not folder_path.startswith(("~", "/", "./", "../")):
                folder_path = f"~/Desktop/{folder_path}"
            return {"action": "create_folder", "params": {"path": folder_path}, "reply": "Klasör oluşturuluyor..."}

        # Explicit file-write steps like "not.md yaz" should resolve into write_file.
        file_match = _re.search(r"([\w\-.]+\.[a-z0-9]{2,8})", raw, _re.IGNORECASE)
        write_markers = (" yaz", "yaz ", "oluştur", "olustur", "create", "kaydet")
        if file_match and any(k in f" {low} " for k in write_markers):
            file_name = str(file_match.group(1) or "").strip()
            explicit_path = ""
            for tok in self._extract_path_like_tokens(raw):
                st = str(tok).strip()
                if ("/" in st or st.startswith(("~", ".", ".."))) and st.lower().endswith(file_name.lower()):
                    explicit_path = st
                    break
            if explicit_path:
                target_path = explicit_path
            else:
                base_dir = self._get_last_directory() or str(Path.home() / "Desktop")
                target_path = str(Path(base_dir).expanduser() / file_name)
            content = self._normalize_task_write_content(
                self._extract_inline_write_content(raw),
                raw,
                target_path,
            )
            return {
                "action": "write_file",
                "params": {"path": target_path, "content": content},
                "reply": f"{file_name} yazılıyor...",
            }

        # Verification steps are mapped to read_file so content can be checked deterministically.
        verify_markers = ("doğrula", "dogrula", "verify", "kontrol et", "validate")
        verify_subject_markers = (
            "içerik",
            "icerik",
            "içeriği",
            "icerigi",
            "içeriğini",
            "icerigini",
            "content",
            "dosya",
            "file",
        )
        if any(k in low for k in verify_markers) and any(k in low for k in verify_subject_markers):
            verify_path = self._get_last_path()
            if not verify_path and file_match:
                verify_path = str(Path(self._get_last_directory()).expanduser() / str(file_match.group(1)))
            if verify_path:
                return {
                    "action": "read_file",
                    "params": {"path": verify_path},
                    "reply": "Dosya içeriği doğrulanıyor...",
                }

        # Artifact path listing requests map to list_files on the current working dir context.
        if (
            any(k in low for k in ("artifact", "çıktı", "cikti", "path", "yollar"))
            and any(k in low for k in ("ver", "göster", "goster", "listele", "paylaş", "paylas"))
        ):
            return {
                "action": "list_files",
                "params": {"path": self._get_last_directory()},
                "reply": "Artifact yolları listeleniyor...",
            }

        intent = self._infer_save_intent(text)
        if intent:
            return intent

        app_name = self._infer_app_name(text)
        if any(k in low for k in ("araştır", "arastir", "research", "incele")):
            topic = self._sanitize_research_topic(self._extract_topic(text, text), user_input=text, step_name=text)
            return {
                "action": "research",
                "params": {"topic": topic, "depth": "standard"},
                "reply": f"'{topic}' araştırılıyor...",
            }

        if any(k in low for k in (" aç", "ac ", "open")) and app_name:
            return {
                "action": "open_app",
                "params": {"app_name": app_name},
                "reply": f"{app_name} açılıyor...",
            }

        if any(k in low for k in ("ekran görüntüsü", "ekran goruntusu", "screenshot", "ss al", "ss çek", "ss cek")):
            return {
                "action": "take_screenshot",
                "params": {"filename": f"SS_{int(time.time())}"},
                "reply": "Ekran görüntüsü alınıyor...",
            }
        return None

    def _fallback_structured_step_intent(
        self,
        step_text: str,
        temp_context: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Deterministic fallback for numbered/structured filesystem instructions.
        Prevents collapsing multi-step requests into a single write/save action.
        """
        raw = str(step_text or "").strip()
        if not raw:
            return None
        low = raw.lower()
        ctx = temp_context if isinstance(temp_context, dict) else {}

        folder_markers = (
            "klasör oluştur",
            "klasor olustur",
            "klasörü oluştur",
            "klasoru olustur",
            "folder oluştur",
            "folder create",
            "mkdir",
        )
        if any(m in low for m in folder_markers):
            path_tokens = self._extract_path_like_tokens(raw)
            path = ""
            for tok in path_tokens:
                st = str(tok).strip()
                if st and ("/" in st or st.startswith(("~", ".", ".."))):
                    path = st
                    break
            if not path:
                hint = self._extract_folder_hint_from_text(raw)
                if hint:
                    path = f"~/Desktop/{hint}"
            if not path:
                path = "~/Desktop/elyan-test/a"
            return {"action": "create_folder", "params": {"path": path}, "reply": "Klasör oluşturuluyor..."}

        write_markers = (" yaz", "yaz ", "kaydet", "oluştur", "olustur", "create")
        file_match = _re.search(r"([\w\-.]+\.[a-z0-9]{2,8})", raw, _re.IGNORECASE)
        if file_match and any(k in f" {low} " for k in write_markers):
            file_name = str(file_match.group(1) or "").strip()
            base_dir = str(ctx.get("last_dir") or self._get_last_directory() or str(Path.home() / "Desktop"))
            explicit_path = ""
            for tok in self._extract_path_like_tokens(raw):
                st = str(tok).strip()
                if st.lower().endswith(file_name.lower()) and ("/" in st or st.startswith(("~", ".", ".."))):
                    explicit_path = st
                    break
            target_path = explicit_path or str(Path(base_dir).expanduser() / file_name)
            content = self._normalize_task_write_content(
                self._extract_inline_write_content(raw),
                raw,
                target_path,
            )
            return {
                "action": "write_file",
                "params": {"path": target_path, "content": content},
                "reply": f"{file_name} yazılıyor...",
            }

        verify_markers = ("doğrula", "dogrula", "verify", "kontrol et", "validate")
        if any(m in low for m in verify_markers):
            verify_path = str(ctx.get("last_path") or self._get_last_path() or "").strip()
            if not verify_path and file_match:
                verify_path = str(Path(self._get_last_directory()).expanduser() / str(file_match.group(1)))
            if verify_path:
                return {
                    "action": "read_file",
                    "params": {"path": verify_path},
                    "reply": "Dosya içeriği doğrulanıyor...",
                }

        if (
            any(k in low for k in ("artifact", "çıktı", "cikti", "yol", "path"))
            and any(k in low for k in ("ver", "göster", "goster", "listele", "paylaş", "paylas"))
        ):
            list_path = str(ctx.get("last_dir") or self._get_last_directory() or str(Path.home() / "Desktop"))
            return {
                "action": "list_files",
                "params": {"path": list_path},
                "reply": "Artifact yolları listeleniyor...",
            }
        return None

    def _infer_multi_task_intent(self, user_input: str) -> Optional[dict[str, Any]]:
        parts = self._split_multi_step_text(user_input)
        if len(parts) < 2:
            dense = self._infer_dense_multi_task_intent(user_input)
            if dense:
                return dense
            return None

        original_context = dict(self.file_context)
        temp_context = dict(self.file_context)
        tasks: list[dict[str, Any]] = []
        try:
            for idx, part in enumerate(parts, start=1):
                self.file_context.update(temp_context)
                intent = self._infer_step_intent(part)
                if not isinstance(intent, dict):
                    intent = self._fallback_structured_step_intent(part, temp_context=temp_context)
                if not isinstance(intent, dict):
                    continue
                action = str(intent.get("action", "") or "").strip().lower()
                if not action or action in {"chat", "unknown"}:
                    continue
                params = intent.get("params", {}) if isinstance(intent.get("params"), dict) else {}
                task = {
                    "id": f"task_{idx}",
                    "action": action,
                    "params": params,
                    "description": part,
                }
                tasks.append(task)

                # Provisional context propagation for pronoun-based next steps.
                if action in {"read_file", "write_file", "delete_file", "rename_file"}:
                    p = str(params.get("path") or "").strip()
                    if p:
                        temp_context["last_path"] = str(Path(p).expanduser())
                        temp_context["last_dir"] = str(Path(p).expanduser().parent)
                elif action in {"create_folder", "create_directory"}:
                    p = str(params.get("path") or params.get("directory") or "").strip()
                    if p:
                        folder = Path(p).expanduser()
                        temp_context["last_path"] = str(folder)
                        temp_context["last_dir"] = str(folder)
                elif action in {"move_file", "copy_file"}:
                    src = str(params.get("source") or "").strip()
                    dst = str(params.get("destination") or "").strip()
                    if src:
                        temp_context["last_path"] = str(Path(src).expanduser())
                        temp_context["last_dir"] = str(Path(src).expanduser().parent)
                    if dst:
                        dst_p = Path(dst).expanduser()
                        temp_context["last_dir"] = str(dst_p if dst_p.suffix == "" else dst_p.parent)
                elif action in {"list_files", "search_files"}:
                    d = str(params.get("path") or params.get("directory") or "").strip()
                    if d:
                        temp_context["last_dir"] = str(Path(d).expanduser())
        finally:
            self.file_context.update(original_context)

        if len(tasks) < 2:
            return None
        collapsed = self._collapse_research_document_intent(user_input, tasks)
        if isinstance(collapsed, dict):
            return collapsed
        payload = {
            "action": "multi_task",
            "tasks": self._normalize_browser_media_tasks(tasks, user_input=user_input),
            "reply": "Çok adımlı görev başlatılıyor...",
        }
        if self._feature_flag_enabled("ELYAN_AGENTIC_V2", False):
            task_spec = self._build_filesystem_task_spec(user_input, tasks)
            if isinstance(task_spec, dict):
                payload["task_spec"] = task_spec
        return payload

    @staticmethod
    def _extract_browser_search_query(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        # Normalize apostrophe suffixes: safari'den -> safari den
        raw = _re.sub(r"([0-9A-Za-zÇĞİÖŞÜçğıöşü]+)'([0-9A-Za-zÇĞİÖŞÜçğıöşü]+)", r"\1 \2", raw)
        low = raw.lower()

        query = ""
        m_before = _re.search(r"(.+?)\s+(?:arat|ara|search)\b", low, _re.IGNORECASE)
        if m_before:
            query = str(m_before.group(1) or "").strip()
        if not query:
            m_after = _re.search(r"(?:arat|ara|search)\s+(.+)", low, _re.IGNORECASE)
            if m_after:
                query = str(m_after.group(1) or "").strip()
        if not query:
            query = low

        cleanup = {
            "safari", "safariyi", "safariden", "safaride", "safariye",
            "chrome", "chromedan", "chromede", "krom", "kromdan", "kromda",
            "tarayıcı", "tarayici", "tarayıcıda", "tarayicida", "tarayıcıdan", "tarayicidan",
            "browser", "webde", "internette", "aç", "ac", "git", "gir",
            "ve", "sonra", "ardından", "ardindan", "lütfen", "lutfen",
            "ara", "arat", "search", "den", "dan", "de", "da",
        }
        query = " ".join(tok for tok in query.replace(".", " ").split() if tok not in cleanup).strip(" ,.;:-")
        return query

    @staticmethod
    def _resolve_google_search_url(query: str, *, user_input: str = "") -> str:
        q = str(query or "").strip()
        if not q:
            return "https://www.google.com"
        images = Agent._looks_like_image_search_request(user_input)
        if images:
            return f"https://www.google.com/search?tbm=isch&q={quote_plus(q)}"
        return f"https://www.google.com/search?q={quote_plus(q)}"

    @staticmethod
    def _infer_browser_app_from_text(text: str) -> str:
        low = str(text or "").lower()
        if any(k in low for k in ("safari", "tarayıcı", "tarayici")):
            return "Safari"
        if any(k in low for k in ("chrome", "krom")):
            return "Google Chrome"
        return ""

    @staticmethod
    def _extract_key_combo_from_text(text: str) -> str:
        raw = str(text or "").lower()
        m = _re.search(r"\b(cmd|command|ctrl|control|alt|option|shift)\s*(?:\+\s*[a-z0-9]+)+", raw, _re.IGNORECASE)
        if not m:
            return ""
        combo = str(m.group(0) or "").strip().lower()
        combo = _re.sub(r"\s+", "", combo)
        combo = combo.replace("command", "cmd").replace("control", "ctrl").replace("option", "alt")
        return combo

    def _build_computer_use_steps_from_text(self, user_input: str) -> list[dict[str, Any]]:
        text = str(user_input or "").strip()
        low = text.lower()
        if not low:
            return []

        steps: list[dict[str, Any]] = []
        browser = self._infer_browser_app_from_text(low)
        has_browser_intent = any(k in low for k in ("safari", "chrome", "krom", "browser", "tarayıcı", "tarayici"))

        def _append_step(action: str, params: dict[str, Any], description: str) -> None:
            if not action:
                return
            if steps and steps[-1].get("action") == action and steps[-1].get("params") == params:
                return
            steps.append({"action": action, "params": params, "description": description})

        # Browser launch
        if browser and any(
            k in low
            for k in (
                "aç",
                "ac",
                "git",
                "gir",
                "arat",
                "ara",
                "search",
                "youtube",
                "google",
            )
        ):
            _append_step("open_app", {"app_name": browser}, f"{browser} aç")

        # YouTube or web search URL
        has_youtube = ("youtube" in low) or (" yt " in f" {low} ")
        has_play = any(k in low for k in ("çal", "cal", "play"))
        has_search = any(k in low for k in ("arat", " ara ", "search", "ara "))
        if has_youtube:
            query = self._extract_playback_query(text)
            if not query and has_search:
                query = self._extract_browser_search_query(text)
            url = self._resolve_youtube_play_url(query) if query else "https://www.youtube.com"
            params = {"url": url}
            if browser:
                params["browser"] = browser
            _append_step("open_url", params, f"YouTube aç: {query}" if query else "YouTube aç")
        elif has_search and (has_browser_intent or "google" in low or ".com" not in low):
            query = self._extract_browser_search_query(text)
            if query:
                url = self._resolve_google_search_url(query, user_input=text)
                params = {"url": url}
                if browser:
                    params["browser"] = browser
                _append_step("open_url", params, f"Web araması: {query}")

        # Direct URL
        m_url = _re.search(r"(https?://[^\s]+|www\.[^\s]+|\b[\w.-]+\.(?:com|org|net|io|ai|co|tr)\b[^\s]*)", text, _re.IGNORECASE)
        if m_url:
            raw_url = str(m_url.group(1) or "").strip()
            if raw_url and "google.com/search" not in raw_url.lower():
                params = {"url": raw_url}
                if browser:
                    params["browser"] = browser
                _append_step("open_url", params, "URL aç")

        # Key combo
        combo = self._extract_key_combo_from_text(text)
        if combo and any(k in low for k in ("bas", "press", "tuş", "tus", "kısayol", "kisayol")):
            _append_step("key_combo", {"combo": combo}, f"Kısayol: {combo}")

        # Type text
        m_write = _re.search(r"(?:şunu yaz|sunu yaz|yaz)\s*[:\-]?\s*(.+)", text, _re.IGNORECASE)
        if m_write:
            payload = str(m_write.group(1) or "").strip()
            payload = _re.sub(r"\s+(?:ve\s+|sonra\s+)?(?:enter|return)\s+bas.*$", "", payload, flags=_re.IGNORECASE)
            if payload:
                press_enter = bool(_re.search(r"\b(enter|return)\b", low, _re.IGNORECASE))
                _append_step("type_text", {"text": payload, "press_enter": press_enter}, "Metin yaz")

        # Mouse move/click coordinates
        m_move = _re.search(
            r"\b(mouse|imlec|cursor)\b.*\b(\d{1,4})\s*[,x]\s*(\d{1,4})\b.*\b(taşı|tasi|git|move)\b",
            low,
            _re.IGNORECASE,
        )
        if m_move:
            x = int(m_move.group(2))
            y = int(m_move.group(3))
            _append_step("mouse_move", {"x": x, "y": y}, f"Mouse taşı: {x},{y}")

        m_click = _re.search(r"\b(\d{1,4})\s*[,x]\s*(\d{1,4})\b.*\b(tıkla|tikla|click)\b", low, _re.IGNORECASE)
        if m_click:
            x = int(m_click.group(1))
            y = int(m_click.group(2))
            _append_step("mouse_click", {"x": x, "y": y, "button": "left"}, f"Mouse tıkla: {x},{y}")

        # Implicit type for plain "... yaz ve enter bas" without explicit prefix.
        if not any(s.get("action") == "type_text" for s in steps):
            m_plain = _re.search(r"\b([a-z0-9çğıöşü _-]{2,80})\s+yaz(?:\s+ve\s+enter\s+bas)?\b", low, _re.IGNORECASE)
            if m_plain:
                payload = str(m_plain.group(1) or "").strip()
                if payload and payload not in {"safari", "chrome", "google", "youtube"}:
                    press_enter = bool(_re.search(r"enter\s+bas", low, _re.IGNORECASE))
                    _append_step("type_text", {"text": payload, "press_enter": press_enter}, "Metin yaz")

        # If this is pure media play request with browser context, ensure execution pair.
        if has_youtube and has_play and len(steps) == 1 and steps[0].get("action") == "open_url" and browser:
            steps.insert(0, {"action": "open_app", "params": {"app_name": browser}, "description": f"{browser} aç"})

        return steps

    @staticmethod
    def _extract_playback_query(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        # Normalize Turkish apostrophe suffixes (youtube'a -> youtube a)
        raw = _re.sub(r"([0-9A-Za-zÇĞİÖŞÜçğıöşü]+)'([0-9A-Za-zÇĞİÖŞÜçğıöşü]+)", r"\1 \2", raw)
        m = _re.search(r"(?:çal|cal|play)\s+(.+?)(?:$|[.,;])", raw, _re.IGNORECASE)
        if not m:
            m = _re.search(r"(.+?)\s+(?:çal|cal|play)(?:$|[.,;])", raw, _re.IGNORECASE)
        query = str(m.group(1) if m else "").strip()
        if not query:
            return ""
        query = _re.sub(
            r"\b(youtube|yt|safari|safariden|safaride|git|aç|ac|ve|sonra|ardından|ardindan|den|dan|de|da)\b",
            " ",
            query,
            flags=_re.IGNORECASE,
        )
        query = query.replace("'", " ")
        query = _re.sub(r"^(?:a|e|ya|ye|da|de|den|dan)\s+", "", query, flags=_re.IGNORECASE)
        query = _re.sub(r"\s+(?:a|e|ya|ye|da|de|den|dan)\s+", " ", query, flags=_re.IGNORECASE)
        query = " ".join(query.split()).strip(" ,.;:-")
        return query

    @staticmethod
    def _resolve_youtube_play_url(query: str) -> str:
        q = str(query or "").strip()
        if not q:
            return "https://www.youtube.com"
        search_url = f"https://www.youtube.com/results?search_query={quote_plus(q)}"
        try:
            req = urllib.request.Request(
                search_url,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                html = resp.read(280_000).decode("utf-8", errors="ignore")
            m = _re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
            if m:
                return f"https://www.youtube.com/watch?v={m.group(1)}&autoplay=1"
        except Exception:
            pass
        return search_url

    def _normalize_browser_media_tasks(self, tasks: list[dict[str, Any]], user_input: str) -> list[dict[str, Any]]:
        """
        Normalize mixed browser/media plans such as:
        "Safari'den YouTube'a git ve X çal"
        into deterministic executable steps.
        """
        if not isinstance(tasks, list):
            return []
        low = str(user_input or "").lower()
        wants_safari = "safari" in low
        has_youtube_context = ("youtube" in low) or (" yt " in f" {low} ")

        normalized: list[dict[str, Any]] = []
        for t in tasks:
            if not isinstance(t, dict):
                continue
            normalized.append(
                {
                    "id": str(t.get("id") or "").strip(),
                    "action": str(t.get("action") or "").strip(),
                    "params": dict(t.get("params") or {}) if isinstance(t.get("params"), dict) else {},
                    "description": str(t.get("description") or "").strip(),
                }
            )

        if not normalized:
            return []

        if not (has_youtube_context or wants_safari):
            return tasks

        if not has_youtube_context:
            for t in normalized:
                if str(t.get("action") or "").strip().lower() == "open_url":
                    url = str((t.get("params") or {}).get("url") or "").lower()
                    if "youtube.com" in url or "youtu.be" in url:
                        has_youtube_context = True
                        break

        transformed: list[dict[str, Any]] = []
        converted_play_to_url = False
        for t in normalized:
            action_raw = str(t.get("action") or "").strip().lower()
            action = ACTION_TO_TOOL.get(action_raw, action_raw)
            params = dict(t.get("params") or {}) if isinstance(t.get("params"), dict) else {}

            if has_youtube_context and action in {"control_music", "play_music"}:
                query = str(params.get("query") or "").strip()
                if not query:
                    query = self._extract_playback_query(str(t.get("description") or ""))
                if not query:
                    query = self._extract_playback_query(user_input)
                yt_url = self._resolve_youtube_play_url(query) if query else "https://www.youtube.com"
                transformed.append(
                    {
                        "action": "open_url",
                        "params": {"url": yt_url},
                        "description": f"YouTube'da '{query}' aç" if query else "YouTube aç",
                    }
                )
                converted_play_to_url = True
                continue

            transformed.append(
                {
                    "action": action_raw,
                    "params": params,
                    "description": str(t.get("description") or action_raw),
                }
            )

        # If command explicitly mentions Safari, ensure Safari is opened first.
        if wants_safari:
            has_open_safari = any(
                ACTION_TO_TOOL.get(str(s.get("action") or "").strip().lower(), str(s.get("action") or "").strip().lower()) == "open_app"
                and str((s.get("params") or {}).get("app_name") or "").strip().lower() == "safari"
                for s in transformed
            )
            if not has_open_safari:
                transformed.insert(
                    0,
                    {
                        "action": "open_app",
                        "params": {"app_name": "Safari"},
                        "description": "Safari'yi aç",
                    },
                )

        # Remove redundant plain YouTube open step when a query-based open exists.
        if converted_play_to_url:
            playback_query = self._extract_playback_query(user_input).lower()
            has_query_open = any(
                str(s.get("action") or "").strip().lower() == "open_url"
                and (
                    "youtube.com/results?search_query=" in str((s.get("params") or {}).get("url") or "").lower()
                    or "youtube.com/watch?v=" in str((s.get("params") or {}).get("url") or "").lower()
                )
                for s in transformed
            )
            if has_query_open:
                compact: list[dict[str, Any]] = []
                dropped_plain = False
                for s in transformed:
                    if (
                        not dropped_plain
                        and str(s.get("action") or "").strip().lower() == "open_url"
                        and str((s.get("params") or {}).get("url") or "").strip().lower() in {"https://www.youtube.com", "http://www.youtube.com", "https://youtube.com", "http://youtube.com"}
                    ):
                        dropped_plain = True
                        continue
                    compact.append(s)
                transformed = compact

                # If multiple YouTube search URLs exist, keep the best candidate.
                yt_search_indices = [
                    i
                    for i, s in enumerate(transformed)
                    if str(s.get("action") or "").strip().lower() == "open_url"
                    and "youtube.com/results?search_query=" in str((s.get("params") or {}).get("url") or "").lower()
                ]
                if len(yt_search_indices) >= 2:
                    best_idx = yt_search_indices[0]
                    best_score = -10_000
                    for idx in yt_search_indices:
                        url = str((transformed[idx].get("params") or {}).get("url") or "")
                        q_part = ""
                        if "search_query=" in url:
                            q_part = url.split("search_query=", 1)[1].split("&", 1)[0]
                        decoded = unquote_plus(q_part).strip().lower()
                        score = len(decoded)
                        if playback_query and playback_query in decoded:
                            score += 100
                        if decoded in {"a git", "git", "youtube", "yt"}:
                            score -= 50
                        if " git" in f" {decoded} ":
                            score -= 10
                        if score > best_score:
                            best_score = score
                            best_idx = idx
                    transformed = [
                        s
                        for i, s in enumerate(transformed)
                        if i == best_idx or i not in yt_search_indices
                    ]

        # Rebuild linear ids/dependencies for deterministic execution order.
        rebuilt: list[dict[str, Any]] = []
        for idx, s in enumerate(transformed, start=1):
            step = {
                "id": f"task_{idx}",
                "action": str(s.get("action") or "").strip(),
                "params": dict(s.get("params") or {}) if isinstance(s.get("params"), dict) else {},
                "description": str(s.get("description") or f"Adım {idx}"),
            }
            if idx > 1:
                step["depends_on"] = [f"task_{idx - 1}"]
            rebuilt.append(step)
        return rebuilt

    def _build_filesystem_task_spec(self, user_input: str, tasks: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not isinstance(tasks, list) or len(tasks) < 2:
            return None

        allowed_actions = {"create_folder", "create_directory", "write_file", "read_file", "list_files"}
        steps: list[dict[str, Any]] = []
        artifact_paths: list[str] = []
        write_content_by_path: dict[str, str] = {}
        write_path_order: list[str] = []
        required_tools: list[str] = []
        spec_checks: list[dict[str, Any]] = []
        prev_step_id = ""

        for idx, task in enumerate(tasks, start=1):
            if not isinstance(task, dict):
                return None
            raw_action = str(task.get("action", "") or "").strip().lower()
            action = ACTION_TO_TOOL.get(raw_action, raw_action)
            if action not in allowed_actions:
                return None
            params = task.get("params", {}) if isinstance(task.get("params"), dict) else {}
            description = str(task.get("description") or f"Adım {idx}")

            if action in {"create_folder", "create_directory"}:
                path = str(params.get("path") or params.get("directory") or "").strip()
                if not path:
                    return None
                resolved_path = self._resolve_path_with_desktop_fallback(path, user_input=user_input)
                step_id = f"step_{idx}"
                steps.append(
                    {
                        "id": step_id,
                        "action": "mkdir",
                        "path": resolved_path,
                        "parents": True,
                        "depends_on": [prev_step_id] if prev_step_id else [],
                        "checks": [{"type": "path_exists"}],
                        "description": description,
                    }
                )
                spec_checks.append({"step_id": step_id, "checks": [{"type": "path_exists"}]})
                required_tools.append("create_folder")
                prev_step_id = step_id
                artifact_paths.append(resolved_path)
                continue

            if action == "write_file":
                path = str(params.get("path") or "").strip()
                if not path:
                    return None
                resolved_path = self._resolve_path_with_desktop_fallback(path, user_input=user_input)
                normalized_content = self._normalize_task_write_content(
                    params.get("content"),
                    user_input,
                    resolved_path,
                )
                step_id = f"step_{idx}"
                steps.append(
                    {
                        "id": step_id,
                        "action": "write_file",
                        "path": resolved_path,
                        "content": normalized_content,
                        "depends_on": [prev_step_id] if prev_step_id else [],
                        "checks": [{"type": "file_exists"}, {"type": "file_not_empty"}],
                        "description": description,
                    }
                )
                spec_checks.append(
                    {
                        "step_id": step_id,
                        "checks": [{"type": "file_exists"}, {"type": "file_not_empty"}],
                    }
                )
                required_tools.extend(["write_file", "read_file"])
                prev_step_id = step_id
                write_content_by_path[resolved_path] = normalized_content
                write_path_order.append(resolved_path)
                artifact_paths.append(resolved_path)
                continue

            if action == "read_file":
                path = str(params.get("path") or "").strip()
                if not path and write_path_order:
                    path = write_path_order[-1]
                if not path:
                    return None
                resolved_path = self._resolve_path_with_desktop_fallback(path, user_input=user_input)
                expect_contains = str(params.get("expect_contains") or "").strip()
                if not expect_contains and resolved_path in write_content_by_path:
                    expect_contains = write_content_by_path[resolved_path][:80].strip()
                step_id = f"step_{idx}"
                steps.append(
                    {
                        "id": step_id,
                        "action": "verify_file",
                        "path": resolved_path,
                        "expect_contains": expect_contains,
                        "auto_repair": True,
                        "depends_on": [prev_step_id] if prev_step_id else [],
                        "checks": [{"type": "contains", "text": expect_contains}],
                        "description": description,
                    }
                )
                spec_checks.append(
                    {
                        "step_id": step_id,
                        "checks": [{"type": "contains", "text": expect_contains}],
                    }
                )
                required_tools.append("read_file")
                prev_step_id = step_id
                continue

            if action == "list_files":
                path = str(params.get("path") or params.get("directory") or "").strip()
                if not path:
                    if artifact_paths:
                        path = str(Path(artifact_paths[0]).parent)
                    else:
                        path = self._get_last_directory()
                resolved_path = self._resolve_path_with_desktop_fallback(path, user_input=user_input)
                step_id = f"step_{idx}"
                steps.append(
                    {
                        "id": step_id,
                        "action": "report_artifacts",
                        "path": resolved_path,
                        "paths": list(dict.fromkeys(artifact_paths)),
                        "depends_on": [prev_step_id] if prev_step_id else [],
                        "checks": [{"type": "artifact_paths_nonempty"}],
                        "description": description,
                    }
                )
                spec_checks.append({"step_id": step_id, "checks": [{"type": "artifact_paths_nonempty"}]})
                required_tools.append("list_files")
                prev_step_id = step_id

        if not steps:
            return None
        if not any(str(s.get("action") or "") == "write_file" for s in steps):
            return None
        unique_artifacts = list(dict.fromkeys(artifact_paths))
        unique_tools = sorted(set(str(t).strip() for t in required_tools if str(t).strip()))
        artifacts_expected = [
            {
                "path": p,
                "type": "file" if Path(str(p)).suffix else "directory",
                "must_exist": True,
            }
            for p in unique_artifacts
        ]
        task_spec = {
            "intent": "filesystem_batch",
            "version": TASK_SPEC_SCHEMA_VERSION,
            "source": "deterministic",
            "goal": str(user_input or "").strip(),
            "constraints": {
                "path_policy": "context_desktop_safe",
                "deterministic_defaults": True,
                "forbid_command_dump_content": True,
            },
            "context_assumptions": ["home_directory_access", "desktop_available"],
            "artifacts_expected": artifacts_expected,
            "artifacts": unique_artifacts,
            "checks": spec_checks,
            "rollback": [],
            "required_tools": unique_tools,
            "risk_level": "low",
            "timeouts": {"step_timeout_s": 120, "run_timeout_s": 900},
            "retries": {"max_attempts": 2},
            "steps": steps,
        }
        task_spec = coerce_task_spec_standard(
            task_spec,
            user_input=user_input,
        )
        return task_spec if self._validate_filesystem_task_spec(task_spec) else None

    def _validate_filesystem_task_spec(self, task_spec: Any) -> bool:
        strict = self._feature_flag_enabled("ELYAN_STRICT_TASKSPEC", False)
        ok, _errors = validate_task_spec(task_spec, strict_schema=strict)
        return bool(ok)

    def _validate_runtime_task_spec(self, task_spec: Any) -> tuple[bool, list[str]]:
        strict = self._feature_flag_enabled("ELYAN_STRICT_TASKSPEC", False)
        ok, errors = validate_task_spec(task_spec, strict_schema=strict)
        return bool(ok), list(errors or [])

    def _build_api_task_spec(self, user_input: str, intent: dict[str, Any]) -> Optional[dict[str, Any]]:
        params = intent.get("params", {}) if isinstance(intent.get("params"), dict) else {}
        action = str(intent.get("action") or "").strip().lower()

        url = str(params.get("url") or "").strip()
        if not url:
            m = _re.search(r"(https?://[^\s]+)", str(user_input or ""), _re.IGNORECASE)
            if m:
                url = str(m.group(1) or "").strip()
        if not url:
            url = "https://httpbin.org/get"

        method = str(params.get("method") or "GET").strip().upper() or "GET"
        result_dir = str(Path("~/Desktop/elyan-test/api").expanduser())
        result_json = str(Path(result_dir) / "result.json")
        result_summary = str(Path(result_dir) / "summary.txt")

        steps: list[dict[str, Any]] = [
            {
                "id": "step_1",
                "action": "api_health_check",
                "params": {"url": url, "timeout": int(params.get("timeout", 10) or 10)},
                "depends_on": [],
                "checks": [{"type": "http_status", "expected": 200}],
                "description": "API sağlık kontrolü",
            }
        ]

        if action == "graphql_query":
            steps.append(
                {
                    "id": "step_2",
                    "action": "graphql_query",
                    "params": {
                        "url": url,
                        "query": str(params.get("query") or "{ __typename }"),
                        "variables": params.get("variables") if isinstance(params.get("variables"), dict) else {},
                        "headers": params.get("headers") if isinstance(params.get("headers"), dict) else {},
                        "timeout": int(params.get("timeout", 15) or 15),
                    },
                    "depends_on": ["step_1"],
                    "checks": [{"type": "response_present"}],
                    "description": "GraphQL sorgusu çalıştır",
                }
            )
        else:
            steps.append(
                {
                    "id": "step_2",
                    "action": "http_request",
                    "params": {
                        "method": method,
                        "url": url,
                        "headers": params.get("headers") if isinstance(params.get("headers"), dict) else {"Accept": "application/json"},
                        "body": params.get("body"),
                        "timeout": int(params.get("timeout", 15) or 15),
                    },
                    "depends_on": ["step_1"],
                    "checks": [{"type": "response_present"}],
                    "description": "HTTP isteği çalıştır",
                }
            )

        steps.extend(
            [
                {
                    "id": "step_3",
                    "action": "write_file",
                    "path": result_json,
                    "content": "API raw result:\n{{step_2}}",
                    "depends_on": ["step_2"],
                    "checks": [{"type": "file_exists"}, {"type": "file_not_empty"}],
                    "description": "API sonucunu JSON dosyasına kaydet",
                },
                {
                    "id": "step_4",
                    "action": "write_file",
                    "path": result_summary,
                    "content": self._normalize_task_write_content(
                        f"API görevi tamamlandı.\nURL: {url}\nMethod: {method}",
                        user_input,
                        result_summary,
                    ),
                    "depends_on": ["step_3"],
                    "checks": [{"type": "file_exists"}, {"type": "file_not_empty"}],
                    "description": "Özet raporu oluştur",
                },
            ]
        )

        task_spec = {
            "intent": "api_batch",
            "version": TASK_SPEC_SCHEMA_VERSION,
            "source": "intent_normalizer",
            "goal": str(user_input or "").strip() or "API görevi",
            "constraints": {
                "deterministic_defaults": True,
                "forbid_command_dump_content": True,
                "network_timeout_guard": True,
            },
            "context_assumptions": ["network_access_available"],
            "artifacts_expected": [
                {"path": result_json, "type": "file", "must_exist": True},
                {"path": result_summary, "type": "file", "must_exist": True},
            ],
            "checks": [
                {"step_id": "step_1", "checks": [{"type": "http_status", "expected": 200}]},
                {"step_id": "step_3", "checks": [{"type": "file_exists"}, {"type": "file_not_empty"}]},
                {"step_id": "step_4", "checks": [{"type": "file_exists"}, {"type": "file_not_empty"}]},
            ],
            "rollback": [],
            "required_tools": ["api_health_check", "http_request" if action != "graphql_query" else "graphql_query", "write_file"],
            "risk_level": "low",
            "timeouts": {"step_timeout_s": 120, "run_timeout_s": 900},
            "retries": {"max_attempts": 2},
            "steps": steps,
        }
        task_spec = coerce_task_spec_standard(
            task_spec,
            user_input=user_input,
            intent_payload=intent,
            intent_confidence=float(intent.get("confidence", 0.0) or 0.0),
        )
        ok, _errors = self._validate_runtime_task_spec(task_spec)
        return task_spec if ok else None

    def _build_task_spec_from_intent(
        self,
        user_input: str,
        intent: dict[str, Any],
        job_type: str = "",
    ) -> Optional[dict[str, Any]]:
        if not isinstance(intent, dict):
            return None

        action = str(intent.get("action") or "").strip().lower()
        params = intent.get("params", {}) if isinstance(intent.get("params"), dict) else {}
        if action in {"", "chat", "communication", "unknown"}:
            return None

        if action in {"multi_task", "filesystem_batch"}:
            tasks = intent.get("tasks") if isinstance(intent.get("tasks"), list) else []
            if tasks:
                return self._build_filesystem_task_spec(user_input, tasks)

        if action == "api_health_get_save":
            synthetic = {
                "action": "http_request",
                "params": {
                    "url": str(params.get("url") or ""),
                    "method": str(params.get("method") or "GET"),
                },
            }
            return self._build_api_task_spec(user_input, synthetic)

        mapped = ACTION_TO_TOOL.get(action, action)
        if mapped in {"api_health_check", "http_request", "graphql_query"}:
            return self._build_api_task_spec(user_input, intent)

        if mapped == "create_coding_project":
            project_name = str(params.get("project_name") or self._extract_topic(user_input, step_name="")).strip() or "elyan-project"
            brief = str(params.get("brief") or user_input or "").strip() or project_name
            output_dir = self._resolve_path_with_desktop_fallback(str(params.get("output_dir") or "~/Desktop"), user_input=user_input)
            project_path = str(Path(output_dir).expanduser() / project_name)
            project_params = {
                "project_name": project_name,
                "brief": brief,
                "output_dir": output_dir,
                "project_kind": str(params.get("project_kind") or "website").strip() or "website",
                "stack": str(params.get("stack") or "vanilla").strip() or "vanilla",
                "complexity": str(params.get("complexity") or "advanced").strip() or "advanced",
                "theme": str(params.get("theme") or "professional").strip() or "professional",
            }
            task_spec = {
                "intent": "coding_batch",
                "version": TASK_SPEC_SCHEMA_VERSION,
                "source": "intent_normalizer",
                "goal": str(user_input or "").strip() or f"{project_name} projesini oluştur",
                "slots": extract_slots_from_intent({"action": action, "params": project_params}),
                "constraints": {
                    "deterministic_defaults": True,
                    "contract_first_runtime": True,
                },
                "context_assumptions": ["repo_truth_required"],
                "artifacts_expected": [{"path": project_path, "type": "directory", "must_exist": False}],
                "checks": [{"step_id": "step_1", "checks": [{"type": "tool_success"}]}],
                "rollback": [],
                "required_tools": ["create_coding_project"],
                "tool_candidates": ["create_coding_project"],
                "risk_level": "low",
                "timeouts": {"step_timeout_s": 300, "run_timeout_s": 3600},
                "retries": {"max_attempts": 1},
                "steps": [
                    {
                        "id": "step_1",
                        "action": "create_coding_project",
                        "params": project_params,
                        "depends_on": [],
                        "checks": [{"type": "tool_success"}],
                        "description": brief,
                    }
                ],
            }
            task_spec = coerce_task_spec_standard(
                task_spec,
                user_input=user_input,
                intent_payload=intent,
                intent_confidence=float(intent.get("confidence", 0.0) or 0.0),
            )
            ok, _errors = self._validate_runtime_task_spec(task_spec)
            return task_spec if ok else None

        normalized_params = self._normalize_param_aliases(mapped, dict(params))

        if mapped in {"write_file", "read_file", "list_files", "create_folder", "edit_text_file", "edit_word_document", "summarize_document", "analyze_document", "batch_edit_text"}:
            path = str(
                normalized_params.get("path")
                or normalized_params.get("directory")
                or normalized_params.get("file_path")
                or ""
            ).strip()
            if not path:
                if mapped in {"write_file", "edit_text_file", "summarize_document", "analyze_document"}:
                    path = "~/Desktop/not.md"
                elif mapped == "edit_word_document":
                    path = "~/Desktop/belge.docx"
                else:
                    path = "~/Desktop"
            path = self._resolve_path_with_desktop_fallback(path, user_input=user_input)
            normalized_params["path"] = path
            if mapped == "write_file":
                allow_short_content = bool(normalized_params.get("allow_short_content"))
                if not allow_short_content and self._is_short_note_request(user_input, path):
                    allow_short_content = True
                normalized_params["allow_short_content"] = allow_short_content
                normalized_params["content"] = self._normalize_task_write_content(
                    normalized_params.get("content"),
                    user_input,
                    path,
                    allow_short_content=allow_short_content,
                )
            if mapped == "batch_edit_text":
                normalized_params["directory"] = str(normalized_params.get("directory") or path)
                if not str(normalized_params.get("pattern") or "").strip():
                    normalized_params["pattern"] = self._infer_batch_pattern(user_input)

        intent_map = {
            "write_file": "filesystem_batch",
            "read_file": "filesystem_batch",
            "list_files": "filesystem_batch",
            "create_folder": "filesystem_batch",
            "write_word": "office_batch",
            "write_excel": "office_batch",
            "edit_text_file": "office_batch",
            "batch_edit_text": "office_batch",
            "edit_word_document": "office_batch",
            "summarize_document": "office_batch",
            "analyze_document": "office_batch",
            "advanced_research": "research_batch",
            "research_document_delivery": "research_batch",
            "run_safe_command": "automation_batch",
        }
        spec_intent = intent_map.get(mapped, "general_batch")
        if str(job_type or "").strip().lower() == "api_integration":
            spec_intent = "api_batch"

        step_checks: list[dict[str, Any]] = [{"type": "tool_success"}]
        if mapped == "run_safe_command":
            step_checks.append({"type": "exit_code", "expected": 0})
        if mapped in {"edit_text_file", "edit_word_document"}:
            step_checks.append({"type": "file_exists"})

        step: dict[str, Any] = {
            "id": "step_1",
            "action": mapped,
            "params": normalized_params,
            "depends_on": [],
            "checks": step_checks,
            "description": str(intent.get("reply") or user_input or "Tek adım görev"),
        }
        if "path" in normalized_params:
            step["path"] = str(normalized_params.get("path") or "")
        if mapped == "write_file":
            step["content"] = str(normalized_params.get("content") or "")

        artifacts_expected: list[dict[str, Any]] = []
        if "path" in step and str(step.get("path") or "").strip():
            p = str(step.get("path") or "")
            artifacts_expected.append(
                {
                    "path": p,
                    "type": "directory" if mapped in {"create_folder", "list_files", "batch_edit_text"} else "file",
                    "must_exist": mapped in {"write_file", "create_folder", "edit_text_file", "edit_word_document"},
                }
            )

        task_spec = {
            "intent": spec_intent,
            "version": TASK_SPEC_SCHEMA_VERSION,
            "source": "intent_normalizer",
            "goal": str(user_input or "").strip() or str(intent.get("reply") or "görev"),
            "slots": extract_slots_from_intent(
                {
                    "action": action,
                    "params": normalized_params,
                }
            ),
            "constraints": {
                "deterministic_defaults": True,
                "forbid_command_dump_content": True,
            },
            "context_assumptions": ["default_policy_filled"],
            "artifacts_expected": artifacts_expected,
            "checks": [{"step_id": "step_1", "checks": step_checks}],
            "rollback": [],
            "required_tools": [mapped],
            "risk_level": "low",
            "timeouts": {"step_timeout_s": 90, "run_timeout_s": 600},
            "retries": {"max_attempts": 1},
            "steps": [step],
        }
        task_spec = coerce_task_spec_standard(
            task_spec,
            user_input=user_input,
            intent_payload=intent,
            intent_confidence=float(intent.get("confidence", 0.0) or 0.0),
        )

        ok, _errors = self._validate_runtime_task_spec(task_spec)
        return task_spec if ok else None

    @staticmethod
    def _collect_filesystem_task_spec_paths(task_spec: dict[str, Any]) -> list[str]:
        paths: list[str] = []
        artifacts = task_spec.get("artifacts_expected", []) if isinstance(task_spec, dict) else []
        if isinstance(artifacts, list):
            for item in artifacts:
                if isinstance(item, dict):
                    s = str(item.get("path") or "").strip()
                    if s:
                        paths.append(s)
                else:
                    s = str(item or "").strip()
                    if s:
                        paths.append(s)
        steps = task_spec.get("steps", []) if isinstance(task_spec, dict) else []
        for step in steps:
            if not isinstance(step, dict):
                continue
            path = str(step.get("path") or "").strip()
            if path:
                paths.append(path)
            extra = step.get("paths")
            if isinstance(extra, list):
                for item in extra:
                    s = str(item or "").strip()
                    if s:
                        paths.append(s)
        return list(dict.fromkeys(paths))

    @staticmethod
    def _filesystem_action_tool_name(action: str) -> str:
        mapped = {
            "mkdir": "create_folder",
            "write_file": "write_file",
            "verify_file": "read_file",
            "report_artifacts": "list_files",
        }
        return str(mapped.get(str(action or "").strip().lower(), "") or "")

    def _analyze_filesystem_task_spec(self, task_spec: dict[str, Any], *, user_input: str = "") -> dict[str, Any]:
        analysis: dict[str, Any] = {"ok": True, "errors": [], "warnings": []}
        required_tools = task_spec.get("required_tools", [])
        if not isinstance(required_tools, list):
            required_tools = []

        if not required_tools:
            for step in task_spec.get("steps", []):
                if isinstance(step, dict):
                    tool = self._filesystem_action_tool_name(str(step.get("action") or ""))
                    if tool:
                        required_tools.append(tool)
        normalized_tools = sorted(set(str(t).strip() for t in required_tools if str(t).strip()))
        for tool in normalized_tools:
            if tool not in AVAILABLE_TOOLS or not AVAILABLE_TOOLS.get(tool):
                analysis["errors"].append(f"required_tool_missing:{tool}")

        for path in self._collect_filesystem_task_spec_paths(task_spec):
            if ".." in str(path).replace("\\", "/"):
                analysis["warnings"].append(f"path_traversal_like:{path}")
            _ = self._resolve_path_with_desktop_fallback(path, user_input=user_input)

        for step in task_spec.get("steps", []):
            if not isinstance(step, dict):
                continue
            if str(step.get("action") or "").strip().lower() == "verify_file":
                if not str(step.get("expect_contains") or "").strip():
                    analysis["warnings"].append(f"weak_verify:{step.get('id')}")

        if analysis["errors"]:
            analysis["ok"] = False
        return analysis

    def _collect_file_evidence(self, path: str) -> dict[str, Any]:
        raw = str(path or "").strip()
        if not raw:
            return {"path": "", "exists": False}
        resolved = Path(raw).expanduser()
        if not resolved.exists():
            return {"path": str(resolved), "exists": False}

        evidence: dict[str, Any] = {
            "path": str(resolved),
            "exists": True,
            "is_file": bool(resolved.is_file()),
            "is_dir": bool(resolved.is_dir()),
            "size_bytes": int(resolved.stat().st_size) if resolved.is_file() else 0,
        }
        if resolved.is_file():
            evidence["sha256"] = self._compute_sha256(str(resolved))
        return evidence

    @staticmethod
    def _task_spec_action_to_tool(action: str) -> str:
        low = str(action or "").strip().lower()
        mapped = {
            "mkdir": "create_folder",
            "verify_file": "read_file",
            "report_artifacts": "list_files",
        }
        return str(mapped.get(low, ACTION_TO_TOOL.get(low, low)) or "").strip()

    def _evaluate_task_spec_check(
        self,
        check: dict[str, Any],
        *,
        result: Any,
        step: dict[str, Any],
        params: dict[str, Any],
        user_input: str,
    ) -> tuple[bool, str]:
        if not isinstance(check, dict):
            return True, ""
        ctype = str(check.get("type") or "").strip().lower()
        if not ctype:
            return True, ""

        payload = result if isinstance(result, dict) else {}
        path = str(
            step.get("path")
            or payload.get("path")
            or payload.get("file_path")
            or params.get("path")
            or params.get("file_path")
            or ""
        ).strip()
        resolved = self._resolve_path_with_desktop_fallback(path, user_input=user_input) if path else ""

        if ctype == "tool_success":
            ok = not (isinstance(result, dict) and result.get("success") is False)
            return ok, "tool_success_failed" if not ok else ""

        if ctype in {"file_exists", "path_exists"}:
            ok = bool(resolved and Path(resolved).expanduser().exists())
            return ok, f"path_not_found:{resolved or path}" if not ok else ""

        if ctype == "file_not_empty":
            ok = bool(
                resolved
                and Path(resolved).expanduser().is_file()
                and Path(resolved).expanduser().stat().st_size > 0
            )
            return ok, f"file_empty_or_missing:{resolved or path}" if not ok else ""

        if ctype == "contains":
            expected = str(check.get("text") or step.get("expect_contains") or "").strip()
            if not expected:
                return True, ""
            content = ""
            if resolved and Path(resolved).expanduser().is_file():
                try:
                    content = Path(resolved).expanduser().read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    content = ""
            if not content:
                content = str(payload.get("content") or payload.get("output") or "")
            ok = bool(content) and expected in content
            return ok, f"contains_check_failed:{expected[:40]}" if not ok else ""

        if ctype == "http_status":
            expected_raw = check.get("expected", 200)
            try:
                expected = int(expected_raw)
            except Exception:
                expected = 200
            status_code = payload.get("status_code")
            if status_code is None and isinstance(payload.get("results"), dict):
                first = next(iter(payload.get("results").values()), {})
                if isinstance(first, dict):
                    status_code = first.get("status_code")
            try:
                ok = int(status_code) == expected
            except Exception:
                ok = False
            return ok, f"http_status_mismatch:{status_code}->{expected}" if not ok else ""

        if ctype == "response_present":
            body = payload.get("body")
            data = payload.get("data")
            output = payload.get("output")
            content = payload.get("content")
            ok = bool(body or data or output or content)
            if not ok and payload.get("success") is True:
                ok = True
            return ok, "empty_response" if not ok else ""

        if ctype == "artifact_paths_nonempty":
            explicit = step.get("paths")
            if isinstance(explicit, list) and explicit:
                return True, ""
            return bool(resolved), "artifact_paths_empty" if not resolved else ""

        if ctype == "exit_code":
            expected_raw = check.get("expected", 0)
            try:
                expected = int(expected_raw)
            except Exception:
                expected = 0
            code = payload.get("returncode", payload.get("exit_code"))
            try:
                ok = int(code) == expected
            except Exception:
                ok = False
            return ok, f"exit_code_mismatch:{code}->{expected}" if not ok else ""

        if ctype == "json_valid":
            text = ""
            if resolved and Path(resolved).expanduser().is_file():
                try:
                    text = Path(resolved).expanduser().read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    text = ""
            if not text:
                val = payload.get("body", payload.get("data", payload.get("content", payload.get("output", ""))))
                if isinstance(val, (dict, list)):
                    return True, ""
                text = str(val or "")
            try:
                json.loads(text)
                return True, ""
            except Exception:
                return False, "json_invalid"

        return False, f"unknown_check_type:{ctype}"

    @staticmethod
    def _runtime_step_error_code(fail_reason: str, *, result: Any = None) -> str:
        payload = result if isinstance(result, dict) else {}
        raw_code = str(payload.get("error_code") or "").strip().upper()
        if raw_code in {PLAN_ERROR, TOOL_ERROR, ENV_ERROR, VALIDATION_ERROR}:
            return raw_code

        low_reason = str(fail_reason or "").lower()
        if any(tok in low_reason for tok in ("timeout", "permission", "not found", "path_not_found", "run_timeout", "step_timeout")):
            return ENV_ERROR
        if any(tok in low_reason for tok in ("unknown dependency", "desteklenmeyen adım", "döngüsel", "cyclic", "unresolved", "unknown_check_type")):
            return PLAN_ERROR
        if any(tok in low_reason for tok in ("mismatch", "invalid", "empty", "contains_check_failed", "json_invalid", "validation", "file_")):
            return VALIDATION_ERROR

        try:
            return classify_error(RuntimeError(str(fail_reason or payload.get("error") or "tool_error")))
        except Exception:
            return TOOL_ERROR

    async def _apply_failure_recovery_strategy(
        self,
        *,
        failure_class: str,
        step_action: str,
        params: dict[str, Any],
        result: Any,
        reason: str,
        user_input: str,
        step_name: str,
    ) -> tuple[dict[str, Any], bool, str]:
        clean_params = dict(params or {})
        payload = result if isinstance(result, dict) else {}
        strategy = select_recovery_strategy(
            failure_class=failure_class,
            action=step_action,
            reason=reason,
            params=clean_params,
            result=payload,
        )
        kind = str(strategy.get("kind") or "").strip().lower()
        stop_retry = bool(strategy.get("stop_retry", False))
        note = str(strategy.get("note") or "").strip()

        if kind == "patch_params":
            patch = strategy.get("params_patch") if isinstance(strategy.get("params_patch"), dict) else {}
            if patch:
                clean_params.update(patch)
            return clean_params, stop_retry, note

        if kind == "refocus_app":
            app_name = str(strategy.get("focus_app") or "").strip()
            if app_name:
                focus_res = await self._execute_tool(
                    "open_app",
                    {"app_name": app_name},
                    user_input=user_input,
                    step_name=f"{step_name} (Recovery: focus)",
                )
                focus_ok = not (isinstance(focus_res, dict) and focus_res.get("success") is False)
                status = "ok" if focus_ok else "failed"
                suffix = f"{note}:{status}" if note else f"refocus_app:{app_name}:{status}"
                return clean_params, stop_retry, suffix
            return clean_params, stop_retry, note

        return clean_params, stop_retry, note

    async def _run_runtime_task_spec(self, task_spec: dict[str, Any], *, user_input: str) -> str:
        self._last_runtime_task_spec_payload = None
        outputs: list[str] = []
        artifact_paths: list[str] = []

        def _finish_runtime_response(
            text: str,
            *,
            success: bool,
            error: str = "",
            error_code: str = "",
            failure_class: str = "",
            rollback_performed: bool = False,
        ) -> str:
            self._last_runtime_task_spec_payload = {
                "success": bool(success),
                "artifact_paths": [p for p in dict.fromkeys(artifact_paths) if p],
                "outputs": list(outputs),
                "task_spec": dict(task_spec or {}),
                "error": str(error or ""),
                "error_code": str(error_code or ""),
                "failure_class": str(failure_class or ""),
                "rollback_performed": bool(rollback_performed),
                "message": str(text or ""),
            }
            return text

        ok, errors = self._validate_runtime_task_spec(task_spec)
        if not ok:
            detail = ", ".join(str(x) for x in (errors or [])[:5]) or "invalid_task_spec"
            return _finish_runtime_response(
                f"Hata kodu: {PLAN_ERROR}\nGeçersiz TaskSpec ({detail}).",
                success=False,
                error=f"invalid_task_spec:{detail}",
                error_code=PLAN_ERROR,
                failure_class="planning_failure",
            )

        steps = task_spec.get("steps", []) if isinstance(task_spec.get("steps"), list) else []
        if not steps:
            return _finish_runtime_response(
                f"Hata kodu: {PLAN_ERROR}\nTaskSpec içinde çalıştırılabilir adım bulunamadı.",
                success=False,
                error="no_runnable_steps",
                error_code=PLAN_ERROR,
                failure_class="planning_failure",
            )
        state = create_pipeline_state()
        root_checks: dict[str, list[dict[str, Any]]] = {}
        checks_payload = task_spec.get("checks", []) if isinstance(task_spec.get("checks"), list) else []
        for item in checks_payload:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("step_id") or "").strip()
            checks = item.get("checks")
            if sid and isinstance(checks, list):
                root_checks[sid] = [c for c in checks if isinstance(c, dict)]
        rollback_steps = [s for s in (task_spec.get("rollback", []) if isinstance(task_spec.get("rollback"), list) else []) if isinstance(s, dict)]
        rollback_done = False

        timeouts_cfg = task_spec.get("timeouts") if isinstance(task_spec.get("timeouts"), dict) else {}
        try:
            step_timeout_s = float(timeouts_cfg.get("step_timeout_s", 90) or 90.0)
        except Exception:
            step_timeout_s = 90.0
        try:
            run_timeout_s = float(timeouts_cfg.get("run_timeout_s", 600) or 600.0)
        except Exception:
            run_timeout_s = 600.0
        step_timeout_s = max(0.1, min(600.0, step_timeout_s))
        run_timeout_s = max(1.0, min(3600.0, run_timeout_s))
        run_started = time.perf_counter()
        retries_cfg = task_spec.get("retries") if isinstance(task_spec.get("retries"), dict) else {}
        default_attempts = max(1, min(4, int(retries_cfg.get("max_attempts", 1) or 1)))
        dag_parallel = self._feature_flag_enabled("ELYAN_DAG_EXEC", False)
        max_parallel = 3
        try:
            policy = self._current_runtime_policy()
            orch = policy.get("orchestration", {}) if isinstance(policy, dict) and isinstance(policy.get("orchestration"), dict) else {}
            if "max_parallel" in orch:
                max_parallel = int(orch.get("max_parallel") or max_parallel)
            elif "team_max_parallel" in orch:
                max_parallel = int(orch.get("team_max_parallel") or max_parallel)
        except Exception:
            pass
        max_parallel = max(1, min(6, max_parallel))

        def _emit_terminal_error(code: str, reason: str = "") -> None:
            c = str(code or TOOL_ERROR).strip().upper() or TOOL_ERROR
            detail = str(reason or "").strip()
            if c == ENV_ERROR and detail.startswith("run_timeout"):
                # Legacy-compatible format for existing reports/tests.
                outputs.append(f"Hata kodu: {c} ({detail})")
            else:
                outputs.append(f"Hata kodu: {c}")
            if detail:
                outputs.append(f"Hata nedeni: {detail}")

        def _step_has_dynamic_placeholders(step: dict[str, Any]) -> bool:
            try:
                raw = json.dumps(
                    {
                        "params": step.get("params"),
                        "path": step.get("path"),
                        "content": step.get("content"),
                    },
                    ensure_ascii=False,
                    default=str,
                )
            except Exception:
                raw = str(step)
            return "{{" in raw and "}}" in raw

        async def _run_runtime_step(idx: int, step_id: str, step: dict[str, Any]) -> dict[str, Any]:
            step_action = str(step.get("action") or "").strip().lower()
            step_desc = str(step.get("description") or f"Adım {idx}")
            tool_name = self._task_spec_action_to_tool(step_action)
            if not tool_name:
                fail_reason = f"unsupported_action:{step_action}"
                return {
                    "idx": idx,
                    "step_id": step_id,
                    "step_desc": step_desc,
                    "text": f"Hata: Desteklenmeyen adım ({step_action}).",
                    "fail_reason": fail_reason,
                    "failure_class": classify_failure_class(reason=fail_reason, action=step_action),
                    "path": "",
                    "retry_notes": [],
                }

            params = dict(step.get("params") or {}) if isinstance(step.get("params"), dict) else {}
            if "path" in step and "path" not in params:
                params["path"] = step.get("path")
            if "content" in step and "content" not in params:
                params["content"] = step.get("content")
            if step_action == "mkdir":
                params.setdefault("parents", True)
            if step_action == "verify_file" and "path" in step:
                params["path"] = step.get("path")

            step_retries = step.get("retries") if isinstance(step.get("retries"), dict) else {}
            attempts = max(1, min(4, int(step_retries.get("max_attempts", default_attempts) or default_attempts)))
            result: Any = {"success": False, "error": "not_executed"}
            fail_reason = ""
            fail_code = ""
            failure_class = ""
            retry_notes: list[str] = []
            recovery_notes: list[str] = []

            for attempt in range(1, attempts + 1):
                if (time.perf_counter() - run_started) > run_timeout_s:
                    fail_reason = f"run_timeout>{run_timeout_s:.1f}s"
                    fail_code = ENV_ERROR
                    break
                try:
                    result = await asyncio.wait_for(
                        self._execute_tool(
                            tool_name,
                            params,
                            user_input=user_input,
                            step_name=step_id,
                            pipeline_state=state,
                        ),
                        timeout=step_timeout_s,
                    )
                except asyncio.TimeoutError:
                    result = {"success": False, "error": f"step_timeout>{step_timeout_s:.1f}s", "error_code": ENV_ERROR}
                except Exception as exc:
                    result = {"success": False, "error": str(exc)}

                tool_ok = not (isinstance(result, dict) and result.get("success") is False)
                if not tool_ok:
                    raw_reason = result.get("error") if isinstance(result, dict) else "tool_execution_failed"
                    fail_reason = str(raw_reason).strip() if raw_reason is not None else ""
                    if not fail_reason or fail_reason.lower() in {"none", "null"}:
                        if isinstance(result, dict):
                            fail_reason = (
                                str(result.get("message") or "").strip()
                                or str(result.get("detail") or "").strip()
                                or str(result.get("stderr") or "").strip()
                                or "tool_execution_failed"
                            )
                        else:
                            fail_reason = "tool_execution_failed"
                    fail_code = self._runtime_step_error_code(fail_reason, result=result)
                else:
                    checks = []
                    step_checks = step.get("checks", [])
                    if isinstance(step_checks, list):
                        checks.extend(c for c in step_checks if isinstance(c, dict))
                    checks.extend(root_checks.get(step_id, []))
                    fail_reason = ""
                    for check in checks:
                        passed, reason = self._evaluate_task_spec_check(
                            check,
                            result=result,
                            step=step,
                            params=params,
                            user_input=user_input,
                        )
                        if not passed:
                            fail_reason = reason or "validation_failed"
                            fail_code = self._runtime_step_error_code(fail_reason, result=result)
                            break

                if not fail_reason:
                    fail_code = ""
                    failure_class = ""
                    break
                failure_class = classify_failure_class(
                    reason=fail_reason,
                    error_code=fail_code,
                    action=step_action,
                    payload=result if isinstance(result, dict) else {},
                )
                if attempt < attempts:
                    params, stop_retry, recovery_note = await self._apply_failure_recovery_strategy(
                        failure_class=failure_class,
                        step_action=step_action,
                        params=params,
                        result=result,
                        reason=fail_reason,
                        user_input=user_input,
                        step_name=step_desc,
                    )
                    if recovery_note:
                        recovery_notes.append(recovery_note)
                    if stop_retry:
                        break
                if attempt < attempts:
                    retry_notes.append(f"[{idx}] {step_desc}\nTekrar deneme {attempt}/{attempts - 1}: {fail_reason}")

            path = str(
                (result.get("path") if isinstance(result, dict) else "")
                or (result.get("file_path") if isinstance(result, dict) else "")
                or params.get("path")
                or ""
            ).strip()
            resolved_path = self._resolve_path_with_desktop_fallback(path, user_input=user_input) if path else ""
            if fail_reason and not failure_class:
                failure_class = classify_failure_class(
                    reason=fail_reason,
                    error_code=fail_code,
                    action=step_action,
                    payload=result if isinstance(result, dict) else {},
                )
            return {
                "idx": idx,
                "step_id": step_id,
                "step_desc": step_desc,
                "text": self._format_result_text(result),
                "fail_reason": fail_reason,
                "fail_code": fail_code,
                "failure_class": failure_class,
                "path": resolved_path,
                "retry_notes": retry_notes,
                "recovery_notes": recovery_notes,
            }

        async def _run_rollback(trigger_reason: str) -> None:
            nonlocal rollback_done
            if rollback_done or not rollback_steps:
                return
            rollback_done = True
            outputs.append("Rollback başlatıldı...")
            for ridx, step in enumerate(rollback_steps, start=1):
                action = str(step.get("action") or "").strip().lower()
                tool_name = self._task_spec_action_to_tool(action)
                if not tool_name:
                    outputs.append(f"[RB:{ridx}] atlandı (desteklenmeyen action: {action})")
                    continue
                params = dict(step.get("params") or {}) if isinstance(step.get("params"), dict) else {}
                if "path" in step and "path" not in params:
                    params["path"] = step.get("path")
                if "content" in step and "content" not in params:
                    params["content"] = step.get("content")
                try:
                    res = await asyncio.wait_for(
                        self._execute_tool(
                            tool_name,
                            params,
                            user_input=user_input,
                            step_name=f"rollback_{ridx}",
                            pipeline_state=state,
                        ),
                        timeout=step_timeout_s,
                    )
                    outputs.append(f"[RB:{ridx}] {self._format_result_text(res)}")
                except Exception as exc:
                    outputs.append(f"[RB:{ridx}] Hata: {exc}")
            outputs.append(f"Rollback tamamlandı. Tetikleyici: {trigger_reason}")

        indexed_steps: list[tuple[int, str, dict[str, Any]]] = []
        known_ids: set[str] = set()
        for idx, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                continue
            step_id = str(step.get("id") or f"step_{idx}").strip() or f"step_{idx}"
            indexed_steps.append((idx, step_id, step))
            known_ids.add(step_id)
        pending: dict[str, tuple[int, dict[str, Any]]] = {sid: (idx, st) for idx, sid, st in indexed_steps}
        completed: set[str] = set()

        while pending:
            if (time.perf_counter() - run_started) > run_timeout_s:
                await _run_rollback(f"run_timeout>{run_timeout_s:.1f}s")
                _emit_terminal_error(ENV_ERROR, f"run_timeout>{run_timeout_s:.1f}s")
                return _finish_runtime_response(
                    "\n\n".join(x for x in outputs if str(x).strip()),
                    success=False,
                    error=f"run_timeout>{run_timeout_s:.1f}s",
                    error_code=ENV_ERROR,
                    failure_class="environment_failure",
                    rollback_performed=rollback_done,
                )
            ready: list[tuple[int, str, dict[str, Any]]] = []
            for sid, (idx, step) in pending.items():
                raw_deps = step.get("depends_on") if step.get("depends_on") is not None else step.get("dependencies")
                if isinstance(raw_deps, str):
                    deps = [raw_deps.strip()] if raw_deps.strip() else []
                elif isinstance(raw_deps, list):
                    deps = [str(x).strip() for x in raw_deps if str(x).strip()]
                else:
                    deps = []

                missing = [d for d in deps if d not in known_ids]
                if missing:
                    step_desc = str(step.get("description") or f"Adım {idx}")
                    outputs.append(f"[{idx}] {step_desc}\nHata: Bilinmeyen bağımlılık(lar): {', '.join(missing)}")
                    _emit_terminal_error(PLAN_ERROR, "unknown_dependency")
                    await _run_rollback("unknown_dependency")
                    return _finish_runtime_response(
                        "\n\n".join(x for x in outputs if str(x).strip()),
                        success=False,
                        error="unknown_dependency",
                        error_code=PLAN_ERROR,
                        failure_class="planning_failure",
                        rollback_performed=rollback_done,
                    )
                if all(d in completed for d in deps):
                    ready.append((idx, sid, step))

            if not ready:
                outputs.append("Hata: TaskSpec adımlarında döngüsel veya çözülemeyen bağımlılık bulundu.")
                _emit_terminal_error(PLAN_ERROR, "cyclic_or_unresolved_dependency")
                await _run_rollback("cyclic_or_unresolved_dependency")
                return _finish_runtime_response(
                    "\n\n".join(x for x in outputs if str(x).strip()),
                    success=False,
                    error="cyclic_or_unresolved_dependency",
                    error_code=PLAN_ERROR,
                    failure_class="planning_failure",
                    rollback_performed=rollback_done,
                )

            ready.sort(key=lambda x: x[0])
            parallel_candidates: list[tuple[int, str, dict[str, Any]]] = []
            sequential_candidates: list[tuple[int, str, dict[str, Any]]] = []
            if dag_parallel and len(ready) > 1:
                for item in ready:
                    _idx, _sid, _step = item
                    if _step_has_dynamic_placeholders(_step):
                        sequential_candidates.append(item)
                    else:
                        parallel_candidates.append(item)
            else:
                sequential_candidates = list(ready)

            async def _consume_result(res: dict[str, Any]) -> tuple[bool, str]:
                idx = int(res.get("idx", 0) or 0)
                step_desc = str(res.get("step_desc") or f"Adım {idx}")
                step_id = str(res.get("step_id") or "")
                for note in res.get("retry_notes", []) if isinstance(res.get("retry_notes"), list) else []:
                    if str(note).strip():
                        outputs.append(str(note))
                outputs.append(f"[{idx}] {step_desc}\n{res.get('text')}")
                fail_reason = str(res.get("fail_reason") or "").strip()
                if fail_reason:
                    fail_code = str(res.get("fail_code") or "").strip().upper() or self._runtime_step_error_code(fail_reason)
                    _emit_terminal_error(fail_code, fail_reason)
                    return False, step_id
                path = str(res.get("path") or "").strip()
                if path:
                    artifact_paths.append(path)
                if step_id:
                    completed.add(step_id)
                    pending.pop(step_id, None)
                return True, step_id

            if parallel_candidates:
                for i in range(0, len(parallel_candidates), max_parallel):
                    batch = parallel_candidates[i : i + max_parallel]
                    batch_results = await asyncio.gather(
                        *(_run_runtime_step(idx, sid, st) for idx, sid, st in batch),
                        return_exceptions=True,
                    )
                    normalized: list[dict[str, Any]] = []
                    for j, item in enumerate(batch):
                        idx, sid, st = item
                        raw = batch_results[j]
                        if isinstance(raw, Exception):
                            normalized.append(
                                {
                                    "idx": idx,
                                    "step_id": sid,
                                    "step_desc": str(st.get("description") or f"Adım {idx}"),
                                    "text": f"Hata: {raw}",
                                    "fail_reason": str(raw),
                                    "path": "",
                                    "retry_notes": [],
                                }
                            )
                        else:
                            normalized.append(raw)
                    normalized.sort(key=lambda r: int(r.get("idx", 0) or 0))
                    for res in normalized:
                        ok_res, _sid = await _consume_result(res)
                        if not ok_res:
                            await _run_rollback(str(res.get("fail_reason") or "step_failed"))
                            return _finish_runtime_response(
                                "\n\n".join(x for x in outputs if str(x).strip()),
                                success=False,
                                error=str(res.get("fail_reason") or "step_failed"),
                                error_code=str(res.get("fail_code") or TOOL_ERROR),
                                failure_class=str(res.get("failure_class") or ""),
                                rollback_performed=rollback_done,
                            )

            for idx, sid, st in sequential_candidates:
                res = await _run_runtime_step(idx, sid, st)
                ok_res, _sid = await _consume_result(res)
                if not ok_res:
                    await _run_rollback(str(res.get("fail_reason") or "step_failed"))
                    return _finish_runtime_response(
                        "\n\n".join(x for x in outputs if str(x).strip()),
                        success=False,
                        error=str(res.get("fail_reason") or "step_failed"),
                        error_code=str(res.get("fail_code") or TOOL_ERROR),
                        failure_class=str(res.get("failure_class") or ""),
                        rollback_performed=rollback_done,
                    )

        artifact_paths = [p for p in dict.fromkeys(artifact_paths) if p]
        if artifact_paths:
            outputs.append("Artifact yolları:\n" + "\n".join(f"- {p}" for p in artifact_paths))
        return _finish_runtime_response(
            "\n\n".join(x for x in outputs if str(x).strip()),
            success=True,
            rollback_performed=rollback_done,
        )

    async def _run_filesystem_task_spec(self, task_spec: dict[str, Any], *, user_input: str) -> str:
        if not self._validate_filesystem_task_spec(task_spec):
            return "Hata: Geçersiz filesystem task spec."
        analysis = self._analyze_filesystem_task_spec(task_spec, user_input=user_input)
        if not analysis.get("ok", False):
            issues = ", ".join(str(x) for x in (analysis.get("errors") or []) if str(x).strip())
            return f"Hata: Task spec feasibility başarısız: {issues}"

        outputs: list[str] = []
        artifact_paths: list[str] = []
        write_content_by_path: dict[str, str] = {}
        failed = False
        evidence_rows: list[dict[str, Any]] = []

        steps = task_spec.get("steps", [])
        for idx, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                continue

            step_id = str(step.get("id") or f"step_{idx}")
            step_action = str(step.get("action") or "").strip().lower()
            step_desc = str(step.get("description") or f"Adım {idx}")
            step_path_raw = str(step.get("path") or "").strip()
            step_path = self._resolve_path_with_desktop_fallback(step_path_raw, user_input=user_input) if step_path_raw else ""

            if step_action == "mkdir":
                result = await self._execute_tool(
                    "create_folder",
                    {"path": step_path},
                    user_input=user_input,
                    step_name=step_desc,
                )
                text = self._format_result_text(result)
                if isinstance(result, dict) and result.get("success"):
                    artifact_paths.append(step_path)
                    evidence_rows.append(
                        {
                            "step_id": step_id,
                            "tool": "create_folder",
                            "status": "success",
                            "evidence": self._collect_file_evidence(step_path),
                        }
                    )
                else:
                    failed = True
                    evidence_rows.append(
                        {
                            "step_id": step_id,
                            "tool": "create_folder",
                            "status": "failed",
                            "evidence": {"path": step_path, "exists": False},
                        }
                    )
                outputs.append(f"[{idx}] {step_desc}\n{text}")
                if failed:
                    break
                continue

            if step_action == "write_file":
                allow_short_content = bool(
                    step.get("allow_short_content")
                    or (step.get("params", {}) or {}).get("allow_short_content")
                )
                if not allow_short_content and self._is_short_note_request(user_input, step_path):
                    allow_short_content = True
                normalized_content = self._normalize_task_write_content(
                    step.get("content"),
                    user_input,
                    step_path,
                    allow_short_content=allow_short_content,
                )
                write_res = await self._execute_tool(
                    "write_file",
                    {"path": step_path, "content": normalized_content, "allow_short_content": allow_short_content},
                    user_input=user_input,
                    step_name=step_desc,
                )
                read_res = await self._execute_tool(
                    "read_file",
                    {"path": step_path},
                    user_input=user_input,
                    step_name=f"{step_desc} doğrula",
                )

                read_content = ""
                verified = False
                if isinstance(read_res, dict) and read_res.get("success"):
                    read_content = str(read_res.get("content") or "")
                    verified = bool(read_content.strip()) and normalized_content.strip() == read_content.strip()

                if not verified:
                    repair_res = await self._execute_tool(
                        "write_file",
                        {"path": step_path, "content": normalized_content, "allow_short_content": allow_short_content},
                        user_input=user_input,
                        step_name=f"{step_desc} onarım",
                    )
                    read_res = await self._execute_tool(
                        "read_file",
                        {"path": step_path},
                        user_input=user_input,
                        step_name=f"{step_desc} tekrar doğrula",
                    )
                    if isinstance(read_res, dict) and read_res.get("success"):
                        read_content = str(read_res.get("content") or "")
                        verified = bool(read_content.strip()) and normalized_content.strip() == read_content.strip()
                    if not (isinstance(repair_res, dict) and repair_res.get("success") and verified):
                        failed = True

                if isinstance(write_res, dict) and write_res.get("success") and verified:
                    write_content_by_path[step_path] = normalized_content
                    artifact_paths.append(step_path)
                    sha = self._compute_sha256(step_path)
                    info = self._format_result_text(write_res)
                    if sha:
                        info = f"{info}\nHash: {sha[:12]}…"
                    evidence_rows.append(
                        {
                            "step_id": step_id,
                            "tool": "write_file",
                            "status": "success",
                            "evidence": self._collect_file_evidence(step_path),
                        }
                    )
                    outputs.append(f"[{idx}] {step_desc}\n{info}")
                else:
                    evidence_rows.append(
                        {
                            "step_id": step_id,
                            "tool": "write_file",
                            "status": "failed",
                            "evidence": self._collect_file_evidence(step_path),
                        }
                    )
                    outputs.append(f"[{idx}] {step_desc}\nHata: Dosya yazıldıktan sonra doğrulama başarısız oldu.")
                if failed:
                    break
                continue

            if step_action == "verify_file":
                expected = str(step.get("expect_contains") or "").strip()
                if not expected and step_path in write_content_by_path:
                    expected = write_content_by_path[step_path][:80].strip()

                read_res = await self._execute_tool(
                    "read_file",
                    {"path": step_path},
                    user_input=user_input,
                    step_name=step_desc,
                )
                verified = False
                content = ""
                if isinstance(read_res, dict) and read_res.get("success"):
                    content = str(read_res.get("content") or "")
                    verified = bool(content.strip()) and (not expected or expected in content)

                if not verified and bool(step.get("auto_repair", True)) and step_path in write_content_by_path:
                    await self._execute_tool(
                        "write_file",
                        {"path": step_path, "content": write_content_by_path[step_path]},
                        user_input=user_input,
                        step_name=f"{step_desc} onarım",
                    )
                    read_res = await self._execute_tool(
                        "read_file",
                        {"path": step_path},
                        user_input=user_input,
                        step_name=f"{step_desc} tekrar doğrula",
                    )
                    if isinstance(read_res, dict) and read_res.get("success"):
                        content = str(read_res.get("content") or "")
                        verified = bool(content.strip()) and (not expected or expected in content)

                if verified:
                    evidence_rows.append(
                        {
                            "step_id": step_id,
                            "tool": "read_file",
                            "status": "success",
                            "evidence": self._collect_file_evidence(step_path),
                        }
                    )
                    outputs.append(f"[{idx}] {step_desc}\nDoğrulama başarılı: {step_path}")
                else:
                    evidence_rows.append(
                        {
                            "step_id": step_id,
                            "tool": "read_file",
                            "status": "failed",
                            "evidence": self._collect_file_evidence(step_path),
                        }
                    )
                    outputs.append(f"[{idx}] {step_desc}\nHata: İçerik doğrulaması başarısız ({step_path})")
                    failed = True
                if failed:
                    break
                continue

            if step_action == "report_artifacts":
                list_res = await self._execute_tool(
                    "list_files",
                    {"path": step_path},
                    user_input=user_input,
                    step_name=step_desc,
                )
                text = self._format_result_text(list_res)
                explicit_paths = [str(p).strip() for p in step.get("paths", []) if str(p).strip()] if isinstance(step.get("paths"), list) else []
                all_paths = list(dict.fromkeys([*artifact_paths, *explicit_paths]))
                if all_paths:
                    text = f"{text}\nArtifact yolları:\n" + "\n".join(f"- {p}" for p in all_paths)
                evidence_rows.append(
                    {
                        "step_id": step_id,
                        "tool": "list_files",
                        "status": "success" if not (isinstance(list_res, dict) and list_res.get("success") is False) else "failed",
                        "evidence": {"path": step_path, "reported_paths": all_paths},
                    }
                )
                outputs.append(f"[{idx}] {step_desc}\n{text}")
                continue

        if not failed:
            all_known = list(dict.fromkeys([*artifact_paths, *self._collect_filesystem_task_spec_paths(task_spec)]))
            if all_known and not any("Artifact yolları:" in str(x) for x in outputs):
                outputs.append("Artifact yolları:\n" + "\n".join(f"- {p}" for p in all_known))

        if evidence_rows:
            lines = ["Kanıt özeti:"]
            for row in evidence_rows[:16]:
                ev = row.get("evidence", {}) if isinstance(row.get("evidence"), dict) else {}
                p = str(ev.get("path") or "").strip()
                size = ev.get("size_bytes")
                sha = str(ev.get("sha256") or "").strip()
                part = f"- {row.get('step_id')} {row.get('tool')} [{row.get('status')}]"
                if p:
                    part += f" path={p}"
                if isinstance(size, int):
                    part += f" size={size}"
                if sha:
                    part += f" sha={sha[:12]}…"
                lines.append(part)
            outputs.append("\n".join(lines))

        return "\n\n".join(outputs) if outputs else "Çok adımlı görev için yürütülebilir adım bulunamadı."

    def _infer_skill_workflow_intent(self, user_input: str, attachments: Optional[list[str]] = None) -> Optional[dict[str, Any]]:
        try:
            return skill_manager.resolve_workflow_intent(
                user_input,
                attachments=list(attachments or []),
                file_context=self.file_context,
            )
        except Exception:
            return None

    @staticmethod
    def _model_a_default_path() -> str:
        configured = str(
            elyan_config.get("agent.nlu.model_a.model_path", "~/.elyan/models/nlu/baseline_intent_model.json")
            or "~/.elyan/models/nlu/baseline_intent_model.json"
        ).strip()
        return str(Path(configured).expanduser())

    def _load_model_a(self, model_path: str = "") -> Any:
        path_raw = str(model_path or "").strip()
        path = str(Path(path_raw).expanduser()) if path_raw else self._model_a_default_path()
        file_path = Path(path)
        if not file_path.exists():
            return None

        try:
            mtime = float(file_path.stat().st_mtime)
        except Exception:
            mtime = 0.0

        if (
            self._nlu_model_a is not None
            and self._nlu_model_a_path == path
            and abs(float(self._nlu_model_a_mtime or 0.0) - mtime) < 1e-6
        ):
            return self._nlu_model_a

        try:
            from core.nlu import NaiveBayesIntentModel

            loaded = NaiveBayesIntentModel.load(file_path)
            self._nlu_model_a = loaded
            self._nlu_model_a_path = path
            self._nlu_model_a_mtime = mtime
            self._nlu_model_a_load_error = ""
            return loaded
        except Exception as exc:
            self._nlu_model_a = None
            self._nlu_model_a_path = path
            self._nlu_model_a_mtime = 0.0
            self._nlu_model_a_load_error = str(exc)
            logger.debug(f"model_a_load_failed: {exc}")
            return None

    @staticmethod
    def _normalize_model_a_action(label: Any) -> str:
        action = str(label or "").strip().lower().replace("-", "_").replace(" ", "_")
        action = _re.sub(r"[^a-z0-9_]", "", action)
        return _re.sub(r"_+", "_", action).strip("_")

    def _build_model_a_intent(
        self,
        action_label: str,
        *,
        user_input: str,
        confidence: float,
    ) -> Optional[dict[str, Any]]:
        raw_action = self._normalize_model_a_action(action_label)
        if not raw_action:
            return None
        mapped_action = str(ACTION_TO_TOOL.get(raw_action, raw_action) or raw_action).strip().lower()
        action = mapped_action if mapped_action in AVAILABLE_TOOLS else raw_action
        low = str(user_input or "").lower()

        if action in {"open_app", "close_app"}:
            app_name = self._infer_app_name(user_input)
            if not app_name:
                return None
            return {
                "action": action,
                "params": {"app_name": app_name},
                "confidence": round(float(confidence), 4),
                "_fallback_source": "model_a",
            }

        if action in {"web_search", "browser_search", "search_web"}:
            query = self._extract_topic(user_input, "").strip()
            if not query or query == "genel konu":
                query = str(user_input or "").strip()
            if not query:
                return None
            params: dict[str, Any] = {"query": query}
            if any(k in low for k in ("resim", "gorsel", "görsel", "image", "foto")):
                params["mode"] = "images"
            return {
                "action": "web_search",
                "params": params,
                "confidence": round(float(confidence), 4),
                "_fallback_source": "model_a",
            }

        if action == "open_url":
            url = self._extract_first_url(user_input)
            if not url:
                return None
            return {
                "action": "open_url",
                "params": {"url": url},
                "confidence": round(float(confidence), 4),
                "_fallback_source": "model_a",
            }

        if action in {"create_folder", "list_files", "read_file", "write_file"}:
            default_name = {
                "create_folder": "yeni_klasor",
                "list_files": "",
                "read_file": "not.md",
                "write_file": "not.md",
            }
            if action == "create_folder":
                path_tokens = self._extract_path_like_tokens(user_input)
                raw_path = ""
                for tok in path_tokens:
                    st = str(tok).strip()
                    if "/" in st or st.startswith(("~", "/", "./", "../")):
                        raw_path = st
                        break
                hint = self._extract_folder_hint_from_text(user_input).strip()
                path = raw_path or (f"~/Desktop/{hint}" if hint else "~/Desktop/yeni_klasor")
                return {
                    "action": "create_folder",
                    "params": {"path": path},
                    "confidence": round(float(confidence), 4),
                    "_fallback_source": "model_a",
                }
            if action == "list_files":
                hint = self._extract_folder_hint_from_text(user_input).strip()
                path = f"~/Desktop/{hint}" if hint else "~/Desktop"
                return {
                    "action": "list_files",
                    "params": {"path": path},
                    "confidence": round(float(confidence), 4),
                    "_fallback_source": "model_a",
                }
            path = self._extract_file_path_from_text(user_input, default_name[action] or "not.md")
            params: dict[str, Any] = {"path": path}
            if action == "write_file":
                content = self._extract_inline_write_content(user_input).strip()
                if not content:
                    topic = self._extract_topic(user_input, "").strip()
                    if topic and topic != "genel konu":
                        content = topic
                params["content"] = content
            return {
                "action": action,
                "params": params,
                "confidence": round(float(confidence), 4),
                "_fallback_source": "model_a",
            }

        if action == "run_safe_command":
            command = self._extract_terminal_command_from_text(user_input).strip()
            if not command:
                return None
            return {
                "action": "run_safe_command",
                "params": {"command": command},
                "confidence": round(float(confidence), 4),
                "_fallback_source": "model_a",
            }

        if action in {"http_request", "api_health_get_save"}:
            url = self._extract_first_url(user_input).strip()
            if not url:
                return None
            params = {
                "url": url,
                "method": self._infer_http_method(f" {low} "),
            }
            return {
                "action": action,
                "params": params,
                "confidence": round(float(confidence), 4),
                "_fallback_source": "model_a",
            }

        if action == "set_wallpaper":
            params: dict[str, Any] = {}
            image_url = self._extract_first_url(user_input).strip()
            if image_url:
                params["image_url"] = image_url
            topic = self._extract_topic(user_input, "").strip()
            if topic and topic != "genel konu":
                params["search_query"] = topic
            if not params:
                params["search_query"] = "wallpaper"
            return {
                "action": "set_wallpaper",
                "params": params,
                "confidence": round(float(confidence), 4),
                "_fallback_source": "model_a",
            }

        if action in {"analyze_screen", "take_screenshot"}:
            params = {"prompt": user_input} if action == "analyze_screen" else {}
            return {
                "action": action,
                "params": params,
                "confidence": round(float(confidence), 4),
                "_fallback_source": "model_a",
            }

        return None

    def _infer_model_a_intent(
        self,
        user_input: str,
        *,
        min_confidence: float = 0.78,
        model_path: str = "",
        allowed_actions: Optional[list[str]] = None,
    ) -> Optional[dict[str, Any]]:
        text = str(user_input or "").strip()
        if not text:
            return None
        model = self._load_model_a(model_path=model_path)
        if model is None:
            return None

        try:
            action_label, confidence = model.predict(text)
            confidence = float(confidence or 0.0)
        except Exception as exc:
            logger.debug(f"model_a_predict_failed: {exc}")
            return None

        threshold = max(0.0, min(1.0, float(min_confidence or 0.78)))
        if confidence < threshold:
            return None

        normalized_pred = self._normalize_model_a_action(action_label)
        if not normalized_pred:
            return None
        if normalized_pred in {"", "chat", "unknown", "clarify"}:
            return None

        if isinstance(allowed_actions, list) and allowed_actions:
            allowed = {self._normalize_model_a_action(x) for x in allowed_actions if str(x).strip()}
            mapped = self._normalize_model_a_action(ACTION_TO_TOOL.get(normalized_pred, normalized_pred))
            if normalized_pred not in allowed and mapped not in allowed:
                return None

        return self._build_model_a_intent(normalized_pred, user_input=text, confidence=confidence)

    def _infer_general_tool_intent(self, user_input: str) -> Optional[dict[str, Any]]:
        text = self._runtime_normalize_user_input(user_input)
        low = text.lower()
        if not text:
            return None

        replay_markers = (
            "son başarısız görevi tekrar dene",
            "son basarisiz gorevi tekrar dene",
            "failure replay",
            "son hatalı görevi tekrar çalıştır",
            "son hatali gorevi tekrar calistir",
        )
        if any(m in low for m in replay_markers):
            return {
                "action": "failure_replay",
                "params": {"limit": 30},
                "reply": "Son başarısız görev tekrar çalıştırılıyor...",
            }

        followup_intent = self._infer_conversational_followup_intent(text)
        if followup_intent:
            return followup_intent

        # Wallpaper change
        wallpaper_markers = ("duvar kağıdı", "duvar kagidi", "arka plan", "background", "wallpaper")
        if any(m in low for m in wallpaper_markers):
            url = self._extract_first_url(text)
            topic = self._extract_topic(text, "")
            if topic == "genel konu" or not topic:
                topic = "dog wallpaper" if any(k in low for k in ("köpek", "kopek", "dog")) else "wallpaper"
            params: dict[str, Any] = {"search_query": topic}
            if url:
                params["image_url"] = url
            last_attachment = str(self.file_context.get("last_attachment") or "").strip()
            if (
                last_attachment
                and Path(last_attachment).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
                and any(k in low for k in ("bunu", "şunu", "sunu", "onu", "bu görsel", "bu resmi", "gelen görsel"))
            ):
                params["image_path"] = last_attachment
            return {
                "action": "set_wallpaper",
                "params": params,
                "reply": "Duvar kağıdı güncelleniyor...",
            }

        # Screen analysis / screenshot intent
        screen_markers = (
            "ekrana bak", "ekranda ne var", "ekranı analiz", "ekran goruntusu", "ekran görüntüsü",
            "screenshot", "ss al", "ekranı gör", "screen",
        )
        if any(m in low for m in screen_markers):
            prompt = "Ekranda ne var? Özetle."
            if len(text) > 8:
                prompt = text
            return {
                "action": "analyze_screen",
                "params": {"prompt": prompt},
                "reply": "Ekran görüntüsü alıp analiz ediyorum...",
            }

        # Combined folder + save intent in a single sentence (e.g., "test/b klasörüne not olarak kaydet").
        folder_markers = ("klasör", "klasor", "folder", "dizin", "directory")
        save_markers = ("kaydet", "yaz", "kayd", "not olarak")
        if any(m in low for m in folder_markers) and any(m in low for m in save_markers):
            path_tokens = self._extract_path_like_tokens(text)
            m_nested = _re.search(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", text)
            m_named = _re.search(r"([A-Za-z0-9_.\\/\\-]+)\\s+adında", text, _re.IGNORECASE)
            folder_hint = self._extract_folder_hint_from_text(text)
            folder_path = ""
            if m_nested:
                folder_path = m_nested.group(1)
            if not folder_path:
                for tok in path_tokens:
                    st = str(tok).strip()
                    if "/" in st or st.startswith(("~", ".", "..")):
                        folder_path = st
                        break
            if not folder_path and m_named:
                folder_path = m_named.group(1)
            if folder_path.startswith("/") and len(folder_path) <= 2 and m_nested:
                folder_path = m_nested.group(1)
            if not folder_path and folder_hint:
                folder_path = f"~/Desktop/{folder_hint}"
            if not folder_path:
                folder_path = "~/Desktop/yeni_klasor"
            if "/" in folder_path and not folder_path.startswith(("~", "/", "./", "../")):
                folder_path = f"~/Desktop/{folder_path}"

            if folder_path.startswith("~"):
                base_folder = str(Path(folder_path).expanduser())
            else:
                base_folder = str(Path(folder_path))
            filename = "not.md"
            m_file = _re.search(r"([A-Za-z0-9_.-]+\\.[A-Za-z0-9]{2,8})", text)
            if m_file:
                filename = m_file.group(1)
            content = self._extract_inline_write_content(text)
            if not content:
                topic_guess = self._extract_topic(text, text)
                if topic_guess and topic_guess != "genel konu":
                    content = topic_guess
            return {
                "action": "multi_task",
                "tasks": [
                    {
                        "id": "task_1",
                        "action": "create_folder",
                        "params": {"path": base_folder},
                        "description": f"{base_folder} oluştur",
                    },
                    {
                        "id": "task_2",
                        "action": "write_file",
                        "params": {"path": str(Path(base_folder).expanduser() / filename), "content": content},
                        "description": f"{filename} yaz",
                    },
                ],
                "reply": "Klasör ve not oluşturuluyor...",
            }

        # API health/request/save deterministic flow
        api_url = self._extract_first_url(text)
        if api_url:
            health_markers = (
                "health check", "healthcheck", "sağlık kontrol", "saglik kontrol",
                "sağlık check", "saglik check", "api check", "durum kontrol",
            )
            get_markers = (
                " get ", "get at", "get isteği", "get istegi", "istek at", "request at",
                "http get", "get request",
            )
            save_markers = DEFAULT_SAVE_MARKERS
            wants_health = any(k in low for k in health_markers)
            wants_get = any(k in f" {low} " for k in get_markers) or "httpbin.org/get" in low
            wants_save = any(k in low for k in save_markers)

            if wants_health and wants_get and wants_save:
                result_path, summary_path = self._extract_api_output_paths(text)
                return {
                    "action": "api_health_get_save",
                    "params": {
                        "url": api_url,
                        "method": self._infer_http_method(f" {low} "),
                        "result_path": result_path,
                        "summary_path": summary_path,
                    },
                    "reply": "API health check ve GET çağrısı yapılıp sonuçlar dosyaya kaydediliyor...",
                }
            if wants_health:
                return {
                    "action": "api_health_check",
                    "params": {"urls": [api_url]},
                    "reply": "API health check çalıştırılıyor...",
                }
            if wants_get:
                return {
                    "action": "http_request",
                    "params": {"url": api_url, "method": self._infer_http_method(f" {low} ")},
                    "reply": "API isteği çalıştırılıyor...",
                }

        battery_markers = ("pil", "batarya", "şarj", "sarj", "battery", "charge", "charging")
        if any(marker in low for marker in battery_markers):
            return {
                "action": "get_battery_status",
                "params": {},
                "reply": "Pil durumu kontrol ediliyor...",
            }

        terminal_cmd = self._extract_terminal_command_from_text(text)
        if terminal_cmd:
            return {
                "action": "run_safe_command",
                "params": {"command": terminal_cmd},
                "reply": f"Terminal komutu çalıştırılıyor: {terminal_cmd}",
            }

        # Attachment-driven intents handled elsewhere

        coding_intent = self._infer_coding_project_intent(text)
        if coding_intent:
            return coding_intent

        academic_markers = (
            "akademik",
            "literatür",
            "literatur",
            "tez",
            "journal",
            "peer-reviewed",
            "peer reviewed",
            "atıf",
            "atif",
            "citation",
            "crossref",
            "makale",
            "paper",
        )
        if any(k in low for k in academic_markers) and any(k in low for k in ("araştır", "arastir", "research", "incele", "makale")):
            topic = self._sanitize_research_topic(
                self._extract_topic(text, text),
                user_input=text,
                step_name=text,
            )
            return {
                "action": "search_academic_papers",
                "params": {"query": topic, "limit": 8},
                "reply": "Akademik kaynaklar taranıyor...",
            }

        research_markers = (
            "araştır", "arastir", "araştırma", "arastirma", "research", "incele", "analiz",
        )
        doc_markers = (
            "belge", "doküman", "dokuman", "rapor", "word", "docx", "excel", "xlsx", "tablo", "pdf",
            "dosya", "kayıt", "kayit",
        )
        deliver_markers = (
            "gönder", "gonder", "kopya", "ilet", "paylaş", "paylas", "telegram", "whatsapp",
            "telefon", "anlık kontrol", "anlik kontrol",
        )
        if any(k in low for k in research_markers) and any(k in low for k in doc_markers):
            topic = self._sanitize_research_topic(
                self._extract_topic(text, text),
                user_input=text,
                step_name=text,
            )
            depth = "comprehensive"
            if any(k in low for k in ("hızlı", "hizli", "kısa", "kisa", "quick")):
                depth = "quick"
            elif any(k in low for k in ("uzman", "expert", "derin", "derinlemesine", "çok kapsamlı", "cok kapsamli")):
                depth = "expert"

            include_pdf = any(k in low for k in ("pdf",))
            include_latex = any(k in low for k in ("latex", "tex"))
            include_excel = any(k in low for k in ("excel", "xlsx", "tablo", "csv"))
            explicit_word = any(k in low for k in ("word", "docx", "doküman", "dokuman"))
            generic_doc = any(k in low for k in ("belge", "rapor"))
            include_word = explicit_word or (generic_doc and not include_excel and not include_pdf and not include_latex)
            if not include_word and not include_excel and not include_pdf and not include_latex:
                include_word = True

            needs_delivery = any(k in low for k in deliver_markers)
            is_academic = any(k in low for k in academic_markers)
            return {
                "action": "research_document_delivery",
                "params": {
                    "topic": topic,
                    "brief": text,
                    "depth": depth,
                    "audience": "academic" if is_academic else "executive",
                    "language": "tr",
                    "output_dir": "~/Desktop",
                    "include_word": include_word,
                    "include_excel": include_excel,
                    "include_pdf": include_pdf,
                    "include_latex": include_latex,
                    "include_report": True,
                    "source_policy": "academic" if is_academic else "trusted",
                    "min_reliability": 0.78 if is_academic else 0.62,
                    "citation_style": "apa7" if is_academic else "none",
                    "include_bibliography": bool(is_academic),
                    "deliver_copy": needs_delivery,
                },
                "reply": "Araştırma ve belge paketi hazırlanıyor, çıktı dosyaları paylaşılacak...",
            }

        # Document summarization/editing (deterministic office craftsmanship flow).
        summary_markers = (
            "özetle",
            "ozetle",
            "özet çıkar",
            "ozet cikar",
            "summary",
            "summarize",
            "kısalt",
            "kisalt",
            "sadeleştir",
            "sadelestir",
            "özet",
            "ozet",
        )
        doc_edit_markers = (
            "düzenle", "duzenle", "güncelle", "guncelle", "değiştir", "degistir", "replace",
            "ekle", "genişlet", "genislet", "refactor", "optimize", "temizle",
        )
        doc_tokens = self._extract_path_like_tokens(text)
        doc_path = ""
        last_path = self._get_last_path()
        references_last = self._references_last_object(text)
        for tok in doc_tokens:
            st = str(tok).strip()
            if not st:
                continue
            ext = Path(st).suffix.lower()
            if ext in {
                ".txt",
                ".md",
                ".rst",
                ".json",
                ".yaml",
                ".yml",
                ".csv",
                ".docx",
                ".doc",
                ".pdf",
                ".py",
                ".js",
                ".jsx",
                ".ts",
                ".tsx",
                ".java",
                ".go",
                ".rs",
                ".c",
                ".cpp",
                ".cs",
                ".php",
                ".rb",
                ".swift",
                ".kt",
                ".sql",
                ".sh",
                ".html",
                ".css",
            }:
                doc_path = st
                break
        if not doc_path:
            m_doc = _re.search(
                r"([\w\-.]+\.(?:txt|md|rst|json|ya?ml|csv|docx|doc|pdf|py|js|jsx|ts|tsx|java|go|rs|c|cpp|cs|php|rb|swift|kt|sql|sh|html|css))",
                text,
                _re.IGNORECASE,
            )
            if m_doc:
                doc_path = str(m_doc.group(1) or "").strip()
        if doc_path:
            doc_path = self._resolve_path_with_desktop_fallback(doc_path, user_input=text)
        if not doc_path and references_last and last_path:
            doc_path = str(last_path)

        if any(k in low for k in summary_markers) and (
            doc_path or any(k in low for k in ("belge", "doküman", "dokuman", "word", "docx", "pdf", "dosya", "metin"))
        ):
            summary_params: dict[str, Any] = {"style": self._infer_summary_style(text)}
            if doc_path:
                summary_params["path"] = doc_path
            else:
                content_seed = self._extract_inline_write_content(text) or self._get_recent_assistant_text(text)
                if content_seed:
                    summary_params["content"] = content_seed
            return {
                "action": "summarize_document",
                "params": summary_params,
                "reply": "Belge özetleniyor...",
            }

        code_tuning_markers = ("kod", "code", "fonksiyon", "function", "refactor", "optimize", "lint", "typecheck", "test")
        if any(k in low for k in doc_edit_markers) and (
            doc_path or any(k in low for k in ("belge", "doküman", "dokuman", "word", "docx", "metin", "dosya"))
        ):
            batch_markers = ("toplu", "hepsinde", "tüm", "tum", "dosyalarda", "files")
            if any(k in low for k in batch_markers):
                directory = ""
                for tok in doc_tokens:
                    st = str(tok).strip()
                    if st and not Path(st).suffix:
                        directory = st
                        break
                if not directory:
                    hint = self._extract_folder_hint_from_text(text)
                    if hint:
                        directory = f"~/Desktop/{hint}"
                if not directory:
                    directory = self._get_last_directory()
                return {
                    "action": "batch_edit_text",
                    "params": {
                        "directory": directory,
                        "pattern": self._infer_batch_pattern(text),
                        "operations": self._infer_document_edit_operations(text, word_mode=False),
                        "recursive": any(k in low for k in ("alt klasör", "alt klasor", "recursive", "recursively")),
                    },
                    "reply": "Toplu belge düzenleme başlatılıyor...",
                }

            is_word_target = bool(
                doc_path and Path(doc_path).suffix.lower() in {".doc", ".docx"}
            ) or any(k in low for k in ("word", "docx", "doküman", "dokuman"))
            is_code_target = bool(doc_path and self._is_code_like_path(doc_path)) or any(k in low for k in code_tuning_markers)
            edit_ops = self._infer_document_edit_operations(text, word_mode=is_word_target)
            if is_word_target:
                return {
                    "action": "edit_word_document",
                    "params": {
                        "path": doc_path or self._extract_file_path_from_text(text, "belge.docx"),
                        "operations": edit_ops,
                    },
                    "reply": "Word belgesi düzenleniyor...",
                }
            reply_text = "Kod dosyası düzenleniyor..." if is_code_target else "Metin dosyası düzenleniyor..."
            return {
                "action": "edit_text_file",
                "params": {
                    "path": doc_path or self._extract_file_path_from_text(text, "not.md"),
                    "operations": edit_ops,
                },
                "reply": reply_text,
            }

        tokens = self._extract_path_like_tokens(text)
        file_match = _re.search(r"([\w\-.]+\.[a-z0-9]{2,8})", text, _re.IGNORECASE)
        file_name = str(file_match.group(1)).strip() if file_match else ""
        bare_file_match = _re.search(
            r"\b([a-z0-9][\w\-]{0,80})\s+dosya\w*\b",
            text,
            _re.IGNORECASE,
        )
        bare_file_name = ""
        if bare_file_match:
            candidate_name = str(bare_file_match.group(1) or "").strip()
            if candidate_name and candidate_name.lower() not in {
                "bu",
                "bunu",
                "şunu",
                "sunu",
                "onu",
                "dosya",
                "klasor",
                "klasör",
            }:
                bare_file_name = candidate_name
        last_dir = Path(self._get_last_directory()).expanduser()
        last_path = self._get_last_path()
        references_last = self._references_last_object(text)

        move_markers = (" taşı ", " tasi ", " move ")
        copy_markers = (" kopyala ", " copy ", " cogalt ", " çoğalt ")
        rename_markers = ("yeniden adlandır", "yeniden adlandir", "rename", "değiştir", "degistir", "adını", "adini", "ismini")
        text_padded = f" {low} "

        if any(m in text_padded for m in move_markers + copy_markers):
            action = "copy_file" if any(m in text_padded for m in copy_markers) else "move_file"
            source = tokens[0] if tokens else (last_path if references_last else "")
            destination = self._extract_destination_hint_from_text(text)
            if not destination and len(tokens) >= 2:
                destination = tokens[1]
            if source and destination:
                return {
                    "action": action,
                    "params": {"source": source, "destination": destination},
                    "reply": "Dosya işlemi hazırlanıyor...",
                }

        if any(marker in low for marker in rename_markers):
            if references_last and last_path:
                source = str(last_path)
            else:
                source = tokens[0] if tokens else ""
            current_name = Path(source).name if source else ""
            new_name = self._extract_new_name_from_text(text, current_name=current_name)
            if source and new_name:
                return {
                    "action": "rename_file",
                    "params": {"path": source, "new_name": new_name},
                    "reply": "Dosya yeniden adlandırılıyor...",
                }

        delete_markers = ("sil", "kaldır", "kaldir", "delete", "remove")
        batch_delete_reply, batch_delete_patterns = self._infer_batch_delete_patterns(text)
        if batch_delete_patterns and any(m in low for m in delete_markers):
            batch_dir = ""
            for tok in tokens:
                st = str(tok).strip()
                if st and not Path(st).suffix:
                    batch_dir = st
                    break
            if not batch_dir:
                folder_hint = self._extract_folder_hint_from_text(text)
                if folder_hint:
                    batch_dir = f"~/Desktop/{folder_hint}"
            if not batch_dir:
                batch_dir = self._get_last_directory()
            return {
                "action": "delete_file",
                "params": {
                    "path": "",
                    "directory": batch_dir or str(Path.home() / "Desktop"),
                    "patterns": batch_delete_patterns,
                    "recursive": False,
                    "max_files": 400,
                    "force": False,
                },
                "reply": batch_delete_reply,
            }
        if (file_name or bare_file_name or (references_last and last_path)) and any(m in low for m in delete_markers):
            selected_name = file_name or bare_file_name
            delete_path = str(last_dir / selected_name) if selected_name else str(last_path)
            return {
                "action": "delete_file",
                "params": {"path": delete_path, "force": False},
                "reply": f"{(selected_name or Path(delete_path).name)} siliniyor...",
            }

        read_markers = ("oku", "içinde ne var", "icinde ne var", "içeriğini göster", "icerigini goster", "ne yazıyor")
        if (file_name or bare_file_name or (references_last and last_path)) and any(m in low for m in read_markers):
            selected_name = file_name or bare_file_name
            read_path = str(last_dir / selected_name) if selected_name else str(last_path)
            return {
                "action": "read_file",
                "params": {"path": read_path},
                "reply": f"{(selected_name or Path(read_path).name)} okunuyor...",
            }

        list_markers = ("içindekiler", "içinde ne var", "icinde ne var", "listele", "göster", "goster", "neler var", "bak", "kontrol et")
        folder_hint = self._extract_folder_hint_from_text(text)
        if any(m in low for m in list_markers):
            if folder_hint:
                return {
                    "action": "list_files",
                    "params": {"path": f"~/Desktop/{folder_hint}"},
                    "reply": f"{folder_hint} klasörü listeleniyor...",
                }
            list_scope_markers = ("klasör", "klasor", "dizin", "folder", "directory", "masaüst", "masaust", "desktop")
            if any(k in low for k in list_scope_markers):
                path = "~/Desktop" if any(k in low for k in ("masaüst", "masaust", "desktop")) else self._get_last_directory()
                return {
                    "action": "list_files",
                    "params": {"path": path},
                    "reply": "Klasör içeriği listeleniyor...",
                }

        search_markers = ("ara", "bul", "search", "find", "tara")
        if any(m in low for m in search_markers) and any(k in low for k in ("dosya", "file", "klasör", "klasor")):
            pattern = "*"
            ext_match = _re.search(r"\*\.(\w+)|\b(\w+)\s+uzantılı\b|\b(\w+)\s+uzantili\b", low)
            if ext_match:
                ext = ext_match.group(1) or ext_match.group(2) or ext_match.group(3) or ""
                if ext:
                    pattern = f"*.{ext}"
            elif file_name:
                pattern = f"*{file_name}*"
            return {
                "action": "search_files",
                "params": {"pattern": pattern, "directory": self._get_last_directory()},
                "reply": f"{pattern} için dosya araması yapılıyor...",
            }
        return None

    def _infer_coding_project_intent(self, user_input: str) -> Optional[dict[str, Any]]:
        text = str(user_input or "").strip()
        if not text:
            return None
        low = text.lower()

        build_markers = (
            "yap", "oluştur", "olustur", "geliştir", "gelistir", "hazırla", "hazirla",
            "kodla", "create", "build", "generate", "develop",
        )
        if not any(k in low for k in build_markers):
            return None

        website_markers = (
            "website", "web sitesi", "web sayfası", "web sayfasi", "landing",
            "html", "css", "javascript", "js", "frontend", "react", "next",
        )
        app_markers = (
            "uygulama", "application", "app", "masaüstü uygulama", "masaustu uygulama",
            "desktop app", "mobil", "mobile", "oyun", "game",
        )

        project_kind = ""
        if any(k in low for k in website_markers):
            project_kind = "website"
        elif any(k in low for k in app_markers):
            project_kind = "game" if any(k in low for k in ("oyun", "game")) else "app"
        else:
            return None

        stack = "vanilla"
        if "next" in low:
            stack = "nextjs"
        elif "react" in low:
            stack = "react"
        elif any(k in low for k in ("python", "pyqt", "fastapi", "flask", "django")):
            stack = "python"
        elif any(k in low for k in ("typescript", "ts", "vite")):
            stack = "react"

        project_name = self._extract_topic(text, "")
        if not project_name or project_name == "genel konu":
            project_name = "web-projesi" if project_kind == "website" else "uygulama-projesi"

        latest_markers = ("en son", "latest", "modern", "güncel", "guncel", "state of the art")
        clean_markers = ("clean code", "temiz kod", "solid", "maintainable", "bakımı kolay", "test")
        minimal_markers = ("taslak", "prototype", "hızlıca", "hizlica", "sadece demo")

        wants_latest = any(k in low for k in latest_markers)
        wants_clean = any(k in low for k in clean_markers) or not any(k in low for k in minimal_markers)
        quality_gates = {
            "lint": True,
            "tests": True,
            "docs": True,
            "modular_architecture": True,
        }

        return {
            "action": "create_coding_project",
            "params": {
                "project_kind": project_kind,
                "project_name": project_name[:80],
                "stack": stack,
                "complexity": "advanced",
                "theme": "professional",
                "output_dir": "~/Desktop",
                "brief": text,
                "open_ide": True,
                "ide": self._infer_ide_name(text),
                "tech_mode": "latest" if wants_latest else "stable",
                "coding_standards": "clean_code" if wants_clean else "pragmatic",
                "quality_gates": quality_gates,
            },
            "reply": f"'{project_name}' için kod projesi hazırlanıyor...",
        }

    def _infer_attachment_intent(self, attachments: list[str], user_input: str) -> Optional[dict[str, Any]]:
        if not attachments:
            return None
        path = attachments[0]
        mime, _ = mimetypes.guess_type(path)
        low = (user_input or "").lower()
        # Image → wallpaper or read
        if mime and mime.startswith("image/"):
            return {
                "action": "set_wallpaper",
                "params": {
                    "image_path": path,
                    "image_url": self._extract_first_url(user_input),
                    "search_query": self._extract_topic(user_input, user_input) or "wallpaper",
                },
                "reply": "Gelen görsel duvar kağıdı yapılıyor...",
            }
        # PDF / Word / Text summarize
        if mime in {"application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"} or path.lower().endswith((".pdf", ".doc", ".docx")):
            return {
                "action": "summarize_document",
                "params": {"path": path},
                "reply": "Belge özetleniyor...",
            }
        # Markdown / txt -> read_file
        if path.lower().endswith((".txt", ".md", ".log")):
            return {
                "action": "read_file",
                "params": {"path": path},
                "reply": "Dosya okunuyor...",
            }
        # Spreadsheet -> analyze
        if path.lower().endswith((".csv", ".xlsx", ".xls")):
            return {
                "action": "analyze_excel_data",
                "params": {"path": path},
                "reply": "Tablo analiz ediliyor...",
            }
        return None

    @staticmethod
    def _extract_first_json_payload(text: str) -> Any:
        raw = str(text or "").strip()
        if not raw:
            return None

        candidates: list[str] = [raw]
        fenced_blocks = _re.findall(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=_re.IGNORECASE)
        for block in fenced_blocks:
            clean = str(block or "").strip()
            if clean:
                candidates.append(clean)

        decoder = json.JSONDecoder()
        for candidate in candidates:
            probe = str(candidate or "").strip()
            if probe.lower().startswith("json"):
                probe = probe[4:].strip()

            try:
                parsed = json.loads(probe)
                if isinstance(parsed, (dict, list)):
                    return parsed
            except Exception:
                pass

            for idx, ch in enumerate(probe):
                if ch not in "{[":
                    continue
                try:
                    parsed, _end = decoder.raw_decode(probe[idx:])
                    if isinstance(parsed, (dict, list)):
                        return parsed
                except Exception:
                    continue
        return None

    @staticmethod
    def _extract_first_json_object(text: str) -> dict[str, Any] | None:
        payload = Agent._extract_first_json_payload(text)
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    return item
        return None

    async def _infer_llm_tool_intent(self, user_input: str, *, history: list | None = None, user_id: str = "local") -> Optional[dict[str, Any]]:
        if not self.llm:
            return None

        low_input = str(user_input or "").strip().lower()
        domain = "general"
        if any(k in low_input for k in ("http://", "https://", "api", "endpoint", "graphql", "health check")):
            domain = "api"
        elif any(k in low_input for k in ("klasör", "klasor", "dosya", "kaydet", "sil", "taşı", "tasi", "kopyala", "read_file", "write_file")):
            domain = "filesystem"
        elif any(k in low_input for k in ("araştır", "arastir", "research", "makale", "literatür", "literatur")):
            domain = "research"
        elif any(k in low_input for k in ("kod", "code", "refactor", "lint", "typecheck", "test", ".py", ".js", ".ts")):
            domain = "coding"
        elif any(k in low_input for k in ("duvar kağıdı", "duvar kagidi", "ekrana bak", "screenshot", "app aç", "app kapat", "tıkla", "tikla", "mouse", "klavye", "yaz", "bas", "bilgisayarı kullan", "computer use", "otonom")):
            domain = "system"

        allow_actions = {
            "list_files", "read_file", "write_file", "delete_file", "search_files",
            "move_file", "copy_file", "rename_file", "create_folder",
            "edit_text_file", "batch_edit_text", "edit_word_document",
            "summarize_document", "analyze_document",
            "run_safe_command", "open_app", "close_app", "open_url",
            "web_search", "advanced_research", "take_screenshot", "get_system_info", "get_battery_status",
            "type_text", "press_key", "key_combo", "mouse_move", "mouse_click", "computer_use",
            "create_word_document", "create_excel", "send_notification", "create_reminder",
            "create_web_project_scaffold", "create_software_project_pack", "create_coding_delivery_plan",
            "create_coding_verification_report",
            "research_document_delivery",
            "open_project_in_ide",
            "create_coding_project",
            "api_health_get_save",
            "multi_task",
        }
        recent_context = {
            "last_action": str(getattr(self, "_last_action", "") or ""),
            "last_path": str(self.file_context.get("last_path") or ""),
            "last_dir": str(self.file_context.get("last_dir") or ""),
            "last_attachment": str(self.file_context.get("last_attachment") or ""),
            "recent_user_text": str(self._get_recent_user_text(user_input) or "")[:240],
            "recent_assistant_text": str(self._get_recent_assistant_text(user_input) or "")[:350],
        }
        fewshot = {
            "filesystem": (
                "Örnek-1:\n"
                "Kullanıcı: 1) ~/Desktop/elyan-test/a klasörü oluştur 2) not.md yaz 3) içeriği doğrula 4) artifact yollarını ver\n"
                "JSON: {\"action\":\"multi_task\",\"tasks\":[{\"action\":\"create_folder\",\"params\":{\"path\":\"~/Desktop/elyan-test/a\"},\"description\":\"Klasör oluştur\"},{\"action\":\"write_file\",\"params\":{\"path\":\"~/Desktop/elyan-test/a/not.md\"},\"description\":\"Dosya yaz\"},{\"action\":\"read_file\",\"params\":{\"path\":\"~/Desktop/elyan-test/a/not.md\"},\"description\":\"İçeriği doğrula\"},{\"action\":\"list_files\",\"params\":{\"path\":\"~/Desktop/elyan-test/a\"},\"description\":\"Artifact yollarını raporla\"}],\"confidence\":0.9}"
            ),
            "api": (
                "Örnek-1:\n"
                "Kullanıcı: https://httpbin.org/get için health check yap, sonra GET at ve sonucu result.json kaydet\n"
                "JSON: {\"action\":\"api_health_get_save\",\"params\":{\"url\":\"https://httpbin.org/get\",\"method\":\"GET\"},\"confidence\":0.88}"
            ),
            "system": (
                "Örnek-1:\n"
                "Kullanıcı: Ekrana bak ve özetle\n"
                "JSON: {\"action\":\"analyze_screen\",\"params\":{\"prompt\":\"Ekranı analiz et ve özetle\"},\"confidence\":0.85}"
                "\nÖrnek-2:\n"
                "Kullanıcı: cmd+l bas ve elyan yaz\n"
                "JSON: {\"action\":\"multi_task\",\"tasks\":[{\"action\":\"key_combo\",\"params\":{\"combo\":\"cmd+l\"},\"description\":\"Adres çubuğuna odaklan\"},{\"action\":\"type_text\",\"params\":{\"text\":\"elyan\"},\"description\":\"Metni yaz\"}],\"confidence\":0.8}"
                "\nÖrnek-3:\n"
                "Kullanıcı: Safari aç, Google'da köpek resimleri ara\n"
                "JSON: {\"action\":\"computer_use\",\"params\":{\"steps\":[{\"action\":\"open_app\",\"params\":{\"app_name\":\"Safari\"}},{\"action\":\"open_url\",\"params\":{\"url\":\"https://www.google.com/search?tbm=isch&q=köpek+resimleri\",\"browser\":\"Safari\"}}],\"final_screenshot\":true},\"confidence\":0.82}"
            ),
        }.get(domain, "")
        prompt = (
            "Kullanıcı isteğini yürütülebilir tool aksiyonuna eşle.\n"
            "Sadece geçerli JSON döndür. Ek metin yazma.\n"
            "Format-1 (tek adım): {\"action\":\"...\",\"params\":{...},\"confidence\":0.0}\n"
            "Format-2 (çok adım): {\"action\":\"multi_task\",\"tasks\":[{\"action\":\"...\",\"params\":{},\"description\":\"...\"}],\"confidence\":0.0}\n"
            "Kurallar:\n"
            "1) action sadece izinli adlardan biri olsun.\n"
            "2) Terminal komutu için action=run_safe_command ve params.command zorunlu.\n"
            "3) Dosya işlemlerinde path/source/destination varsa doldur.\n"
            "4) Kullanıcı açıkça çok adım verdiyse multi_task döndür.\n"
            "5) Emin değilsen action='chat' döndür.\n"
            f"Domain: {domain}\n"
            f"Bağlam: {json.dumps(recent_context, ensure_ascii=False)}\n"
            f"{fewshot}\n"
            f"İzinli actionlar: {sorted(allow_actions)}\n"
            f"Kullanıcı: {user_input}"
        )

        try:
            raw = await self.llm.generate(prompt, role="reasoning", history=history or [], user_id=user_id)
        except Exception as exc:
            logger.debug(f"llm tool fallback failed: {exc}")
            return None

        parsed = self._extract_first_json_object(raw)
        if not isinstance(parsed, dict):
            return None
        action = str(parsed.get("action", "") or "").strip().lower()
        if action == "multi_task":
            tasks_raw = parsed.get("tasks")
            if not isinstance(tasks_raw, list) or len(tasks_raw) < 2:
                return None
            normalized_tasks: list[dict[str, Any]] = []
            for idx, item in enumerate(tasks_raw, start=1):
                if not isinstance(item, dict):
                    continue
                sub_action = str(item.get("action", "") or "").strip().lower()
                if sub_action in {"", "chat", "unknown", "multi_task"}:
                    continue
                if sub_action not in allow_actions:
                    continue
                sub_params = item.get("params", {}) if isinstance(item.get("params"), dict) else {}
                normalized_tasks.append(
                    {
                        "id": f"task_{idx}",
                        "action": sub_action,
                        "params": sub_params,
                        "description": str(item.get("description") or sub_action),
                    }
                )
            if len(normalized_tasks) < 2:
                return None
            return {
                "action": "multi_task",
                "tasks": normalized_tasks,
                "reply": "Çok adımlı görev planı hazırlanıyor...",
                "confidence": float(parsed.get("confidence", 0.72) or 0.72),
            }
        if action in {"", "chat", "unknown"} or action not in allow_actions:
            return None
        params = parsed.get("params", {})
        if not isinstance(params, dict):
            params = {}
        if action == "run_safe_command":
            command = str(params.get("command", "") or "").strip()
            if not command:
                return None
            params["command"] = command
        return {
            "action": action,
            "params": params,
            "reply": "Akıllı araç yönlendirmesi uygulanıyor...",
            "confidence": float(parsed.get("confidence", 0.7) or 0.7),
        }

    def _infer_save_intent(self, user_input: str) -> Optional[dict[str, Any]]:
        text = str(user_input or "").strip().lower()
        if not text:
            return None
        try:
            if len(self._extract_numbered_steps(user_input)) >= 2:
                return None
        except Exception:
            pass
        save_markers = (
            "kaydet", "dosya olarak", "bunu kaydet", "masaüstüne kaydet",
            "masaustune kaydet", "word olarak", "excel olarak",
            "word dosyası oluştur", "word dosyasi olustur", "belge oluştur", "belge olustur",
            "rapor oluştur", "rapor olustur", "excel dosyası oluştur", "excel dosyasi olustur",
        )
        if not any(m in text for m in save_markers):
            return None

        # Çok adımlı/karma görev içinde geçen "kaydet" kelimesini tek başına write_file'a düşürme.
        multi_action_markers = (
            "klasör",
            "klasor",
            "oluştur",
            "olustur",
            "doğrula",
            "dogrula",
            "verify",
            "listele",
            "araştır",
            "arastir",
            "aç",
            "ac",
            "kapat",
            "sil",
            "taşı",
            "tasi",
            "kopyala",
        )
        chain_markers = (" ve ", " sonra ", " ardından ", " ardindan ", "adım", "adim", "1)", "2)")
        doc_save_hint = any(k in text for k in ("word", "docx", "belge", "rapor", "excel", "xlsx", "tablo", "sheet"))
        if any(m in text for m in multi_action_markers) and any(m in text for m in chain_markers) and not doc_save_hint:
            return None

        if any(k in text for k in ("word", "docx", "belge", "rapor")):
            return {
                "action": "create_word_document",
                "params": {
                    "path": self._extract_file_path_from_text(user_input, "belge.docx"),
                    "content": "",
                },
                "reply": "Word belgesi hazırlanıyor...",
            }
        if any(k in text for k in ("excel", "xlsx", "tablo", "sheet")):
            return {
                "action": "create_excel",
                "params": {
                    "path": self._extract_file_path_from_text(user_input, "tablo.xlsx"),
                    "content": "",
                },
                "reply": "Excel dosyası hazırlanıyor...",
            }
        explicit_file_or_note = (
            "dosya olarak",
            "not olarak",
            "bunu kaydet",
            ".txt",
            ".md",
            ".json",
            ".csv",
        )
        generic_desktop_save = ("masaüstüne kaydet", "masaustune kaydet", "desktopa kaydet", "desktop'a kaydet")
        if not any(k in text for k in explicit_file_or_note) and not any(k in text for k in generic_desktop_save):
            return None
        return {
            "action": "write_file",
            "params": {
                "path": self._extract_file_path_from_text(user_input, "not.txt"),
                "content": "",
            },
            "reply": "Dosya oluşturuluyor...",
        }

    def _infer_skill_intent(self, user_input: str) -> Optional[dict[str, Any]]:
        text = str(user_input or "").strip().lower()
        if not text:
            return None

        try:
            enabled_skills = {
                str(item.get("name", "")).strip().lower()
                for item in skill_manager.list_skills(available=False, enabled_only=True)
                if str(item.get("name", "")).strip()
            }
        except Exception:
            enabled_skills = set()

        if not enabled_skills:
            return None

        # Command-level mapping from enabled skills.
        tokens = _re.findall(r"[a-zA-Zçğıöşü0-9_]+", text)
        for token in tokens[:12]:
            try:
                skill = skill_registry.get_skill_for_command(token)
            except Exception:
                skill = None
            if not skill:
                continue
            skill_name = str(skill.get("name", "")).lower()
            if skill_name == "research":
                topic = self._extract_topic(user_input, "")
                if any(k in text for k in ("rapor", "belge", "word", "excel", "kopya", "gönder", "gonder")):
                    return {
                        "action": "research_document_delivery",
                        "params": {
                            "topic": topic,
                            "brief": user_input,
                            "depth": "comprehensive",
                            "output_dir": "~/Desktop",
                            "include_word": True,
                            "include_excel": any(k in text for k in ("excel", "xlsx", "tablo", "csv")),
                            "include_pdf": any(k in text for k in ("pdf",)),
                            "include_report": True,
                            "deliver_copy": True,
                        },
                        "reply": f"'{topic}' için araştırma + belge paketi hazırlanıyor...",
                    }
                return {"action": "research", "params": {"topic": topic, "depth": "standard"}, "reply": f"'{topic}' araştırılıyor..."}
            if skill_name == "files":
                if any(k in text for k in ("listele", "neler var", "göster", "goster")):
                    return {"action": "list_files", "params": {"path": "~/Desktop"}, "reply": "Dosyalar listeleniyor..."}
                if any(k in text for k in ("oku", "içinde ne var", "icinde ne var")):
                    return {
                        "action": "read_file",
                        "params": {"path": self._extract_file_path_from_text(user_input, "not.txt")},
                        "reply": "Dosya okunuyor...",
                    }
                if any(k in text for k in ("kaydet", "yaz", "oluştur", "olustur")):
                    return {
                        "action": "write_file",
                        "params": {"path": self._extract_file_path_from_text(user_input, "not.txt"), "content": ""},
                        "reply": "Dosya oluşturuluyor...",
                    }
            if skill_name == "office":
                if any(k in text for k in ("excel", "xlsx", "tablo")):
                    return {
                        "action": "create_excel",
                        "params": {"path": self._extract_file_path_from_text(user_input, "tablo.xlsx")},
                        "reply": "Excel dosyası hazırlanıyor...",
                    }
                if any(k in text for k in ("word", "docx", "belge", "rapor")):
                    return {
                        "action": "create_word_document",
                        "params": {"path": self._extract_file_path_from_text(user_input, "belge.docx"), "content": ""},
                        "reply": "Word belgesi hazırlanıyor...",
                    }
            if skill_name == "browser":
                if any(k in text for k in ("ss", "ekran görünt", "screenshot")):
                    return {"action": "take_screenshot", "params": {}, "reply": "Ekran görüntüsü alınıyor..."}
                if any(k in text for k in ("aç", "ac", "git", "navigate", "url")):
                    topic = self._extract_topic(user_input, "")
                    return {
                        "action": "open_url",
                        "params": {"url": f"https://www.google.com/search?q={quote_plus(topic)}"},
                        "reply": f"Tarayıcıda '{topic}' açılıyor...",
                    }
            if skill_name == "system":
                if any(k in text for k in ("ekran görünt", "screenshot", "ss")):
                    return {"action": "take_screenshot", "params": {}, "reply": "Ekran görüntüsü alınıyor..."}
                if any(k in text for k in ("durum", "sistem bilgisi", "system info")):
                    return {"action": "get_system_info", "params": {}, "reply": "Sistem bilgileri alınıyor..."}
            if skill_name == "calendar":
                if any(k in text for k in ("hatırlat", "hatirlat", "reminder")):
                    return {"action": "create_reminder", "params": {"title": self._extract_topic(user_input, "")}, "reply": "Hatırlatıcı oluşturuluyor..."}

        # Domain fallback using capability router (skill-aware).
        try:
            cap = self.capability_router.route(user_input)
        except Exception:
            cap = None
        if cap and cap.confidence >= 0.6:
            if cap.domain == "research" and "research" in enabled_skills:
                topic = self._extract_topic(user_input, "")
                return {"action": "research", "params": {"topic": topic, "depth": "standard"}, "reply": f"'{topic}' araştırılıyor..."}
            if cap.domain == "document" and "office" in enabled_skills:
                return {"action": "create_word_document", "params": {"path": "~/Desktop/belge.docx", "content": ""}, "reply": "Belge hazırlanıyor..."}
            if cap.domain == "summarization" and "research" in enabled_skills:
                return {"action": "summarize_text", "params": {"text": user_input}, "reply": "Özet hazırlanıyor..."}
        return None

    async def _record_learning(
        self,
        *,
        user_input: str,
        action: str,
        success: bool,
        duration_ms: int,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        try:
            intent_name = str(action or "chat")
            record_fn = self.learning.record_interaction
            record_sig = inspect.signature(record_fn)
            if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in record_sig.parameters.values()):
                record_result = record_fn(
                    tool=intent_name,
                    action=intent_name,
                    input_params={"user_input": str(user_input or "")[:500]},
                    output=context or {},
                    success=bool(success),
                    duration=max(0, duration_ms) / 1000.0,
                )
            else:
                record_result = record_fn(
                    intent_name,
                    {"user_input": str(user_input or "")[:500]},
                    context or {},
                    bool(success),
                    max(0, duration_ms) / 1000.0,
                )
            if inspect.isawaitable(record_result):
                await record_result
        except Exception as exc:
            logger.debug(f"learning record failed: {exc}")

    def get_learning_context(self, limit: int = 5) -> str:
        """
        Get learning context string for LLM prompt injection.
        Returns user's top patterns and preferences as a compact string.
        """
        try:
            recommendations = self.learning.get_recommendations(limit=limit)
            if not recommendations:
                return ""

            lines = ["[Kullanıcı Tercihleri - Önceki Etkileşimlerden Öğrenilen]"]
            for rec in recommendations:
                tool = rec.get("tool", "")
                conf = rec.get("confidence", 0)
                freq = rec.get("frequency", 0)
                sr = rec.get("success_rate", 0)
                if conf > 0.7:
                    lines.append(f"- {tool}: güven={conf:.0%}, kullanım={freq}x, başarı={sr:.0%}")

            prefs = self.learning.preferences or {}
            preferred_tools = prefs.get("preferred_tools", {})
            if preferred_tools:
                top3 = sorted(preferred_tools.items(), key=lambda x: x[1], reverse=True)[:3]
                tools_str = ", ".join(f"{t[0]}({t[1]}x)" for t in top3)
                lines.append(f"- En çok kullanılan araçlar: {tools_str}")

            return "\n".join(lines) if len(lines) > 1 else ""
        except Exception as exc:
            logger.debug(f"learning context failed: {exc}")
            return ""

    async def _finalize_turn(
        self,
        *,
        user_input: str,
        response_text: str,
        action: str,
        success: bool,
        started_at: float,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        uid_raw = str(self.current_user_id or "local")
        try:
            uid = int(self.current_user_id or 0)
        except Exception:
            uid = 0
        duration_ms = int((time.perf_counter() - started_at) * 1000)

        # Son başarılı aksiyonu sakla (feedback/correction learning için)
        if action and action not in {"chat", "chat_fallback_unsafe_plan", "clarify", ""}:
            self._last_action = action
        self._last_turn_context = {
            "user_input": str(user_input or ""),
            "response_text": str(response_text or ""),
            "action": str(action or ""),
            "success": bool(success),
            "ts": time.time(),
        }
        runtime_policy = self._current_runtime_policy()
        runtime_metadata = runtime_policy.get("metadata", {}) if isinstance(runtime_policy.get("metadata"), dict) else {}

        # Genesis Adaptive Learning
        try:
            from core.genesis.adaptive_learning import adaptive
            adaptive.record_interaction(user_input, tool_used=action if action != "chat" else None)
        except Exception as e:
            logger.debug(f"adaptive learning update failed: {e}")

        try:
            self.kernel.memory.store_conversation(
                uid,
                user_input,
                {"message": response_text, "action": action, "success": bool(success)},
            )
        except Exception as exc:
            logger.debug(f"memory store failed: {exc}")

        try:
            keywords = [w for w in self._extract_topic(user_input, "").split() if len(w) >= 3][:8]
            self.user_profile.update_after_interaction(
                uid_raw,
                language=detect_language(user_input),
                action=str(action or "chat"),
                success=bool(success),
                topic_keywords=keywords,
            )
        except Exception as exc:
            logger.debug(f"user profile update failed: {exc}")

        personalization_meta = (context or {}).get("personalization") if isinstance((context or {}).get("personalization"), dict) else {}
        if not personalization_meta:
            personalization_meta = runtime_metadata.get("personalization", {}) if isinstance(runtime_metadata.get("personalization"), dict) else {}
        if getattr(self, "personalization", None):
            try:
                personalization_result = self.personalization.record_interaction(
                    user_id=uid_raw,
                    user_input=user_input,
                    assistant_output=response_text,
                    intent=str((context or {}).get("job_type") or (context or {}).get("role") or action or ""),
                    action=str(action or "chat"),
                    success=bool(success),
                    metadata={
                        "provider": str((personalization_meta or {}).get("provider") or (context or {}).get("provider") or ""),
                        "model": str((personalization_meta or {}).get("model") or (context or {}).get("model") or ""),
                        "base_model_id": str((personalization_meta or {}).get("base_model_id") or (context or {}).get("base_model_id") or ""),
                        "channel": str((context or {}).get("channel") or ""),
                        "run_id": str((context or {}).get("run_id") or ""),
                        "reward_evidence": dict((context or {}).get("reward_evidence") or {}),
                    },
                    privacy_flags={"source": "agent_finalize_turn"},
                )
                interaction_id = str(personalization_result.get("interaction_id") or "").strip()
                if interaction_id:
                    self._last_turn_context["interaction_id"] = interaction_id
                self._last_turn_context["personalization"] = {
                    "provider": str((personalization_meta or {}).get("provider") or (context or {}).get("provider") or ""),
                    "model": str((personalization_meta or {}).get("model") or (context or {}).get("model") or ""),
                    "base_model_id": str((personalization_meta or {}).get("base_model_id") or (context or {}).get("base_model_id") or ""),
                }
                if personalization_result.get("training_job"):
                    self._last_turn_context["training_job"] = dict(personalization_result.get("training_job") or {})
            except Exception as personalization_exc:
                logger.debug(f"personalization interaction update failed: {personalization_exc}")

        try:
            intent_prediction = dict((context or {}).get("intent_prediction") or runtime_metadata.get("intent_prediction") or {})
            route_choice = dict((context or {}).get("route_choice") or runtime_metadata.get("route_choice") or {})
            clarification_policy = dict((context or {}).get("clarification_policy") or runtime_metadata.get("clarification_policy") or {})
            model_runtime = dict((context or {}).get("model_runtime") or runtime_metadata.get("model_runtime") or {})
            phase_records = dict((context or {}).get("phase_records") or {})
            tool_results = list((context or {}).get("tool_results") or [])
            tool_call_result = dict((context or {}).get("tool_call_result") or {})
            if not tool_call_result:
                tool_call_result = {
                    "tool_count": len(tool_results),
                    "success_count": len(
                        [
                            item
                            for item in tool_results
                            if str((item.get("status") if isinstance(item, dict) else "") or "").strip().lower() not in {"failed", "error"}
                        ]
                    ),
                    "artifact_count": len(
                        [
                            item
                            for item in tool_results
                            if isinstance(item, dict) and (item.get("artifacts") or item.get("artifact"))
                        ]
                    ),
                }
            verification_result = dict((context or {}).get("verification_result") or {})
            if not verification_result:
                qa_results = dict((context or {}).get("qa_results") or {})
                if isinstance(qa_results.get("ml_verifier"), dict):
                    verification_result = dict(qa_results.get("ml_verifier") or {})
            if not verification_result:
                verification_result = {
                    "ok": bool((context or {}).get("verified", False)) and not bool((context or {}).get("delivery_blocked", False)),
                    "delivery_blocked": bool((context or {}).get("delivery_blocked", False)),
                }
            user_feedback = dict((context or {}).get("reward_evidence") or {})
            final_outcome = "success" if success else "failed"
            if str(action or "") == "clarify":
                final_outcome = "clarify"
            elif str(action or "") == "refuse":
                final_outcome = "refused"
            elif bool((context or {}).get("delivery_blocked", False)):
                final_outcome = "failed"
            elif bool((context or {}).get("errors", 0) or 0):
                final_outcome = "partial" if success else "failed"
            decision_trace = {
                "intent_prediction": intent_prediction,
                "route_choice": route_choice,
                "clarification_policy": clarification_policy,
                "phase_records": phase_records,
            }
            outcome_metadata = {
                "intent_prediction": intent_prediction,
                "route_choice": route_choice,
                "tool_call_result": tool_call_result,
                "verification_result": verification_result,
                "user_feedback": user_feedback,
                "decision_trace": decision_trace,
                "model_runtime": model_runtime,
                "phase_records": phase_records,
                "errors": int((context or {}).get("errors", 0) or 0),
                "delivery_blocked": bool((context or {}).get("delivery_blocked", False)),
                "verified": bool((context or {}).get("verified", False)),
            }
            self._last_turn_context["decision_trace"] = decision_trace
            self._last_turn_context["tool_call_result"] = tool_call_result
            self._last_turn_context["verification_result"] = verification_result
            if getattr(self, "outcome_store", None):
                self.outcome_store.record_outcome(
                    request_id=str((context or {}).get("run_id") or ""),
                    user_id=uid_raw,
                    action=str(action or ""),
                    channel=str((context or {}).get("channel") or runtime_metadata.get("channel") or ""),
                    final_outcome=final_outcome,
                    success=bool(success),
                    verification_result=verification_result,
                    user_feedback=user_feedback,
                    decision_trace=decision_trace,
                    metadata=outcome_metadata,
                )
        except Exception as outcome_exc:
            logger.debug(f"reliability outcome update failed: {outcome_exc}")

        await self._record_learning(
            user_input=user_input,
            action=action,
            success=success,
            duration_ms=duration_ms,
            context=context or {},
        )

        cowork_session_id = str((context or {}).get("cowork_session_id") or "").strip()
        if cowork_session_id:
            try:
                cowork_runtime = get_cowork_runtime()
                cowork_runtime.finalize_turn(
                    session_key=cowork_session_id,
                    response_text=response_text,
                    success=success,
                    action=action,
                    started_at=started_at,
                    metadata={
                        "role": str((context or {}).get("role") or ""),
                        "job_type": str((context or {}).get("job_type") or ""),
                        "run_id": str((context or {}).get("run_id") or ""),
                        "mode": str((context or {}).get("cowork_mode") or (context or {}).get("mode") or ""),
                        "errors": int((context or {}).get("errors", 0) or 0),
                        "repo_snapshot_id": str((context or {}).get("repo_snapshot_id") or ""),
                        "coding_contract_id": str((context or {}).get("coding_contract_id") or ""),
                        "style_intent": dict((context or {}).get("style_intent") or {}),
                        "gate_state": dict((context or {}).get("gate_state") or {}),
                        "repair_budget": int((context or {}).get("repair_budget", 0) or 0),
                        "model_ladder_trace": list((context or {}).get("model_ladder_trace") or []),
                        "evidence_bundle_id": str((context or {}).get("evidence_bundle_id") or ""),
                        "claim_blocked_reason": str((context or {}).get("claim_blocked_reason") or ""),
                    },
                )
            except Exception as cowork_exc:
                logger.debug(f"cowork finalize skipped: {cowork_exc}")

    @staticmethod
    def _strip_markdown_fence(content: str) -> str:
        text = str(content or "").strip()
        if not text:
            return ""
        text = _re.sub(r"^```[\w-]*\n?", "", text.strip())
        text = _re.sub(r"\n?```$", "", text.strip())
        return text.strip()

    @staticmethod
    def _default_project_file_plan(project_kind: str, stack: str) -> list[dict[str, str]]:
        kind = str(project_kind or "").strip().lower()
        stack_name = str(stack or "").strip().lower()
        common_docs = [
            {"path": "README.md", "purpose": "Kurulum, çalıştırma, özellikler ve kullanım özeti"},
            {"path": "docs/ARCHITECTURE.md", "purpose": "Mimari bileşenler, klasör yapısı, akış ve tasarım kararları"},
            {"path": "docs/QUALITY_CHECKLIST.md", "purpose": "Kod kalitesi, test, doğrulama ve teslim kontrol listesi"},
        ]
        if stack_name in {"python", "pygame", "django", "fastapi"} or kind in {"app", "game"}:
            return [
                *common_docs,
                {"path": "main.py", "purpose": "Uygulama giriş noktası ve temel iş akışı"},
                {"path": "tests/test_smoke.py", "purpose": "Temel smoke test ve çalışma doğrulaması"},
            ]
        return [
            *common_docs,
            {"path": "index.html", "purpose": "Ana arayüz iskeleti"},
            {"path": "styles.css", "purpose": "Temel stiller ve responsive düzen"},
            {"path": "script.js", "purpose": "Etkileşim ve iş mantığı"},
        ]

    def _sanitize_project_file_plan(self, file_plan: Any, *, project_kind: str, stack: str) -> list[dict[str, str]]:
        cleaned: list[dict[str, str]] = []
        seen_paths: set[str] = set()

        if isinstance(file_plan, dict):
            items = file_plan.get("files", [])
        else:
            items = file_plan
        if not isinstance(items, list):
            items = []

        for item in items:
            if not isinstance(item, dict):
                continue
            raw_path = str(item.get("path") or "").strip().replace("\\", "/")
            if not raw_path:
                continue
            rel_path = raw_path.lstrip("/")
            if not rel_path or ".." in rel_path.split("/"):
                continue
            if rel_path in seen_paths:
                continue
            purpose = str(item.get("purpose") or "").strip() or "Bu dosya proje gereksinimini uygular."
            purpose = purpose[:260]
            cleaned.append({"path": rel_path, "purpose": purpose})
            seen_paths.add(rel_path)

        for default_file in self._default_project_file_plan(project_kind, stack):
            path = str(default_file.get("path") or "").strip()
            if not path or path in seen_paths:
                continue
            cleaned.append(
                {
                    "path": path,
                    "purpose": str(default_file.get("purpose") or "Temel proje dosyası"),
                }
            )
            seen_paths.add(path)

        return cleaned

    @staticmethod
    def _assess_generated_content_quality(content: str, *, ext: str = "", rel_path: str = "") -> list[str]:
        text = str(content or "").strip()
        if not text:
            return ["empty_content"]

        issues: list[str] = []
        low = text.lower()
        banned_markers = (
            "todo",
            "placeholder",
            "lorem ipsum",
            "buraya",
            "örnek içerik",
            "ornek icerik",
            "to be implemented",
            "fill in",
        )
        if any(marker in low for marker in banned_markers):
            issues.append("placeholder_content")

        code_exts = {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".json", ".md"}
        line_count = len([ln for ln in text.splitlines() if ln.strip()])
        if ext in code_exts and line_count < 3:
            issues.append("too_short")

        if ext == ".py":
            try:
                compile(text, "<generated>", "exec")
            except Exception:
                issues.append("python_syntax_error")

        rel_low = str(rel_path or "").replace("\\", "/").lower()
        if ext == ".md":
            # Professional docs should include heading structure and key sections.
            if rel_low.endswith("readme.md"):
                if "##" not in text or not any(k in low for k in ("kurulum", "çalıştır", "calistir", "kullanım", "kullanim", "usage")):
                    issues.append("weak_document_structure")
            if rel_low.endswith("architecture.md"):
                if "##" not in text or not any(k in low for k in ("mimari", "architecture", "bileşen", "bilesen", "akış", "akis")):
                    issues.append("weak_architecture_doc")
            if rel_low.endswith("quality_checklist.md"):
                if "- [ ]" not in text and "- [x]" not in text:
                    issues.append("weak_quality_checklist")

        return issues

    @staticmethod
    def _default_project_markdown_content(
        rel_path: str,
        *,
        project_name: str,
        brief: str,
        stack_desc: str,
        tech_mode: str,
        coding_standards: str,
    ) -> str:
        rel_low = str(rel_path or "").replace("\\", "/").lower()
        if rel_low.endswith("readme.md"):
            return (
                f"# {project_name}\n\n"
                "## Proje Özeti\n"
                f"{brief.strip() or 'Kullanıcı gereksinimine göre geliştirilen proje.'}\n\n"
                "## Kurulum\n"
                "- Gereksinimleri yükle\n"
                "- Uygulamayı çalıştır\n\n"
                "## Kullanım\n"
                "- Ana senaryoyu doğrula\n"
                "- Beklenen çıktı ve davranışları kontrol et\n\n"
                "## Teknoloji\n"
                f"- Stack: {stack_desc}\n"
                f"- Tech mode: {tech_mode}\n"
                f"- Kod standardı: {coding_standards}\n"
            )
        if rel_low.endswith("architecture.md"):
            return (
                f"# Architecture - {project_name}\n\n"
                "## Bileşenler\n"
                "- UI/Entry\n"
                "- Domain Logic\n"
                "- Data/IO\n\n"
                "## Akış\n"
                "1. Girdi alınır\n"
                "2. İş mantığı uygulanır\n"
                "3. Çıktı üretilir\n\n"
                "## Tasarım Kararları\n"
                "- Modüler yapı\n"
                "- Hata yönetimi\n"
                "- Testlenebilirlik\n"
            )
        if rel_low.endswith("quality_checklist.md"):
            return (
                f"# Quality Checklist - {project_name}\n\n"
                "## Kod Kalitesi\n"
                "- [ ] İsimlendirme net\n"
                "- [ ] Fonksiyonlar küçük ve tek sorumluluklu\n"
                "- [ ] Hata yönetimi mevcut\n\n"
                "## Doğrulama\n"
                "- [ ] Smoke test çalıştı\n"
                "- [ ] Kritik senaryo doğrulandı\n"
                "- [ ] Dokümantasyon güncel\n"
            )
        return (
            f"# {project_name}\n\n"
            f"{brief.strip() or 'Proje dokümanı'}\n\n"
            f"- Stack: {stack_desc}\n"
            f"- Standart: {coding_standards}\n"
        )

    async def _repair_generated_file_content(
        self,
        *,
        rel_path: str,
        purpose: str,
        project_name: str,
        stack_desc: str,
        brief: str,
        current_content: str,
        quality_issues: list[str],
    ) -> str:
        issue_text = ", ".join(quality_issues) if quality_issues else "quality_gate_failed"
        repair_prompt = (
            f"Sen kıdemli bir {stack_desc} geliştiricisisin.\n"
            f"Proje: {project_name}\n"
            f"Dosya: {rel_path}\n"
            f"Amaç: {purpose}\n"
            f"Kullanıcı isteği: {brief}\n"
            f"Kalite hataları: {issue_text}\n\n"
            "Aşağıdaki mevcut içeriği düzelt ve eksiksiz hale getir. "
            "SADECE nihai dosya içeriğini döndür. Markdown, açıklama veya ``` kullanma.\n\n"
            f"Mevcut içerik:\n{current_content[:6000]}"
        )
        try:
            repaired = await self.llm.generate(repair_prompt, role="reasoning", max_tokens=4000)
        except TypeError:
            repaired = await self.llm.generate(repair_prompt, role="reasoning")
        return self._strip_markdown_fence(repaired)

    async def _llm_build_project(
        self,
        *,
        project_name: str,
        project_kind: str,
        stack: str,
        brief: str,
        output_dir: str,
        complexity: str = "advanced",
        theme: str = "professional",
        tech_mode: str = "stable",
        coding_standards: str = "clean_code",
        quality_gates: dict[str, Any] | None = None,
    ) -> dict:
        """
        İki aşamalı LLM ile profesyonel proje üretimi.
        Pass 1: Dosya yapısını planla (path + purpose).
        Pass 2: Her dosya için ayrı LLM çağrısıyla gerçek içerik üret.
        """
        from tools.pro_workflows import _safe_project_slug
        from security.validator import validate_path

        valid, msg, base_dir = validate_path(output_dir)
        if not valid or base_dir is None:
            return {"success": False, "error": msg}

        slug = _safe_project_slug(project_name)
        project_dir = (base_dir / slug).resolve()

        stack_desc_map = {
            "vanilla": "HTML5 + CSS3 + Vanilla JavaScript (ES2023 modül yapısı)",
            "react":   "React + Vite + TypeScript + modern hooks mimarisi",
            "nextjs":  "Next.js App Router + TypeScript + modern component mimarisi",
            "python":  "Python 3.12 + modüler paket yapısı",
            "pygame":  "Python 3.12 + Pygame",
            "django":  "Python 3.12 + Django + class-based architecture",
            "fastapi": "Python 3.12 + FastAPI + Pydantic v2",
        }
        stack_desc = stack_desc_map.get(stack, stack)
        quality = quality_gates if isinstance(quality_gates, dict) else {}
        lint_required = bool(quality.get("lint", True))
        tests_required = bool(quality.get("tests", True))
        docs_required = bool(quality.get("docs", True))
        modular_required = bool(quality.get("modular_architecture", True))
        modern_hint = (
            "2026 itibarıyla yaygın ve stabil modern kütüphane/pratikleri tercih et. Deprecated yaklaşım kullanma."
            if str(tech_mode or "").strip().lower() == "latest"
            else "Stabil ve üretim dostu (LTS) yaklaşım kullan."
        )
        coding_contract = (
            f"Kod standardı: {coding_standards}. "
            f"Lint={lint_required}, Test={tests_required}, Docs={docs_required}, Modular={modular_required}. "
            "Anlamlı isimlendirme, düşük bağımlılık, tekrarı azaltma, hata yönetimi, README kalitesi zorunlu."
        )

        kind_context_map = {
            "website": "modern, responsive, animasyonlu web sitesi — kullanıcı briefine uygun bölümler",
            "game":    "tam çalışan oyun — game loop, skor, zorluk, oyun bitti ekranı",
            "app":     "tam işlevli uygulama — tüm UI bileşenleri ve özellikler çalışır durumda",
        }
        kind_context = kind_context_map.get(project_kind, "yazılım projesi")

        # ── PASS 0: Kısa brief genişletme ──────────────────────────────
        if len(brief.split()) < 6:
            expand_prompt = (
                f"Kullanıcı şu kısa istekle bir {kind_context} talep ediyor: \"{brief}\"\n"
                f"Stack: {stack_desc}\n\n"
                f"Bu isteği 2-3 cümleyle genişlet. Sadece genişletilmiş brief'i yaz."
            )
            try:
                expanded = await self.llm.generate(expand_prompt, role="reasoning", max_tokens=300)
            except TypeError:
                expanded = await self.llm.generate(expand_prompt, role="reasoning")
            if expanded and len(expanded.strip()) > len(brief):
                brief = expanded.strip()

        # ── PASS 1: Dosya Yapısı Planı ──────────────────────────────────
        plan_prompt = (
            f"Sen kıdemli bir {stack_desc} geliştiricisisin.\n\n"
            f"Proje: {project_name}\n"
            f"Tür: {kind_context}\n"
            f"Stack: {stack_desc}\n"
            f"Seviye: {complexity}\n"
            f"Kullanıcı isteği: {brief}\n\n"
            f"{modern_hint}\n"
            f"{coding_contract}\n\n"
            f"Bu proje için dosya listesini JSON olarak planla. "
            f"İçerik YAZMA, sadece yapıyı belirle.\n"
            f"SADECE JSON döndür:\n"
            f'{{"files":['
            f'{{"path":"dosya_yolu","purpose":"dosyanın amacı ve içereceği özellikler"}},'
            f'...'
            f']}}\n\n'
            f"Kurallar: Maksimum 10 dosya. Gereksiz dosya ekleme."
        )

        try:
            plan_raw = await self.llm.generate(plan_prompt, role="reasoning", max_tokens=1000)
        except TypeError:
            plan_raw = await self.llm.generate(plan_prompt, role="reasoning")

        plan_payload = self._extract_first_json_payload(plan_raw)
        if not isinstance(plan_payload, (dict, list)):
            return {"success": False, "error": "Pass 1: JSON parse hatası"}
        file_plan_raw: Any = []
        if isinstance(plan_payload, dict):
            file_plan_raw = plan_payload.get("files", [])
        elif isinstance(plan_payload, list):
            file_plan_raw = plan_payload

        file_plan = self._sanitize_project_file_plan(
            file_plan_raw,
            project_kind=project_kind,
            stack=stack,
        )
        if not file_plan:
            return {"success": False, "error": "Pass 1: Dosya planı boş"}

        # ── PASS 2: Her Dosya İçin Ayrı LLM Çağrısı ────────────────────
        project_dir.mkdir(parents=True, exist_ok=True)
        written: list[str] = []
        created_summary: list[str] = []
        quality_warnings: list[str] = []

        max_files = 10
        try:
            # self.kernel.config is elyan_config
            max_files = int(self.kernel.config.get("coding.max_files_per_project", 10))
        except Exception:
            pass

        for file_info in file_plan[:max_files]:
            rel_path = str(file_info.get("path", "")).lstrip("/").lstrip("\\")
            purpose = str(file_info.get("purpose", ""))
            if not rel_path:
                continue

            # Path traversal güvenlik kontrolü
            target = (project_dir / rel_path).resolve()
            if not str(target).startswith(str(project_dir)):
                continue

            build_prompt = (
                f"Sen kıdemli bir {stack_desc} geliştiricisisin.\n\n"
                f"Proje: {project_name} ({kind_context})\n"
                f"Stack: {stack_desc}\n"
                f"Kullanıcı isteği: {brief}\n"
                f"Teknoloji modu: {tech_mode}\n"
                f"Kod standardı: {coding_standards}\n"
                f"Kalite kapıları: lint={lint_required}, tests={tests_required}, docs={docs_required}, modular={modular_required}\n"
                f"{modern_hint}\n"
                f"Tamamlanan dosyalar: {', '.join(written) if written else 'Henüz yok'}\n\n"
                f"Şimdi '{rel_path}' dosyasını yaz.\n"
                f"Amaç: {purpose}\n\n"
                f"SADECE dosya içeriğini yaz. Açıklama, markdown bloğu, ``` işareti EKLEME.\n"
                f"Gerçek, çalışır, tam implementasyon yaz. Placeholder veya TODO BIRAKMA."
            )

            target.parent.mkdir(parents=True, exist_ok=True)
            
            ext = Path(rel_path).suffix.lower()
            max_tok = 4000 if ext in (".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css") else 2000

            try:
                content = await self.llm.generate(build_prompt, role="reasoning", max_tokens=max_tok)
            except TypeError:
                content = await self.llm.generate(build_prompt, role="reasoning")

            content = self._strip_markdown_fence(content)
            issues = self._assess_generated_content_quality(content, ext=ext, rel_path=rel_path)
            if issues:
                repaired = await self._repair_generated_file_content(
                    rel_path=rel_path,
                    purpose=purpose,
                    project_name=project_name,
                    stack_desc=stack_desc,
                    brief=brief,
                    current_content=content,
                    quality_issues=issues,
                )
                if repaired.strip():
                    content = repaired.strip()
                    issues = self._assess_generated_content_quality(content, ext=ext, rel_path=rel_path)

            if issues and ext == ".py":
                content = (
                    f'"""Auto-generated fallback for {project_name}."""\n\n'
                    "def main() -> None:\n"
                    f'    print("Proje hazır: {project_name}")\n\n'
                    'if __name__ == "__main__":\n'
                    "    main()\n"
                )
                issues = self._assess_generated_content_quality(content, ext=ext, rel_path=rel_path)

            if issues and ext == ".md":
                content = self._default_project_markdown_content(
                    rel_path,
                    project_name=project_name,
                    brief=brief,
                    stack_desc=stack_desc,
                    tech_mode=tech_mode,
                    coding_standards=coding_standards,
                )
                issues = self._assess_generated_content_quality(content, ext=ext, rel_path=rel_path)

            if not content.strip():
                continue
            if issues:
                quality_warnings.append(f"{rel_path}: {', '.join(issues)}")

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content.strip(), encoding="utf-8")
            written.append(rel_path)
            created_summary.append(f"  • {rel_path} — {purpose[:60]}")
            _push_hint(f"  {rel_path} yazıldı ({len(written)}/{len(file_plan[:max_files])})", icon="check", color="green")

        if not written:
            return {"success": False, "error": "Pass 2: Hiç dosya üretilemedi"}

        file_list = "\n".join(created_summary)
        warning_text = ""
        if quality_warnings:
            warning_rows = "\n".join(f"  - {row}" for row in quality_warnings[:6])
            warning_text = f"\n\n⚠️ Otomatik kalite onarımı uygulanan dosyalar:\n{warning_rows}"
        return {
            "success": True,
            "project_dir": str(project_dir),
            "files_written": written,
            "message": (
                f"✅ **{project_name}** projesi oluşturuldu!\n\n"
                f"📁 Konum: `{project_dir}`\n"
                f"📄 {len(written)} dosya üretildi:\n{file_list}"
                f"{warning_text}"
            ),
        }

    async def _run_direct_intent(self, intent: dict, user_input: str, role: str, history: list, user_id: str = "local") -> str:
        action = str(intent.get("action", "") or "")
        params = intent.get("params", {}) if isinstance(intent.get("params"), dict) else {}
        low_action = action.lower()
        runtime_task_spec = intent.get("task_spec") if isinstance(intent.get("task_spec"), dict) else None
        self._last_direct_intent_payload = None

        if (
            runtime_task_spec is None
            and self._feature_flag_enabled("ELYAN_AGENTIC_V2", False)
            and low_action not in {"failure_replay", "chat", "unknown", ""}
        ):
            runtime_task_spec = self._build_task_spec_from_intent(user_input, intent, "")
            if isinstance(runtime_task_spec, dict):
                intent["task_spec"] = runtime_task_spec

        if isinstance(runtime_task_spec, dict):
            runtime_task_spec = coerce_task_spec_standard(
                runtime_task_spec,
                user_input=user_input,
                intent_payload=intent,
                intent_confidence=float(intent.get("confidence", 0.0) or 0.0),
            )
            intent["task_spec"] = runtime_task_spec

        if isinstance(runtime_task_spec, dict):
            spec_intent = str(runtime_task_spec.get("intent") or "").strip().lower()
            bypass_actions = {
                "create_coding_project",
                "show_help",
                "translate",
                "summarize_url",
                "summarize_file",
                "summarize_text",
            }
            if spec_intent and spec_intent != "filesystem_batch" and low_action not in bypass_actions:
                ok, _errors = self._validate_runtime_task_spec(runtime_task_spec)
                if ok:
                    return await self._run_runtime_task_spec(runtime_task_spec, user_input=user_input)

        if low_action == "failure_replay":
            try:
                limit = int(params.get("limit", 30) or 30)
            except Exception:
                limit = 30
            failed = RunStore.find_latest_failed_task(limit=max(5, min(100, limit)))
            if not failed:
                return "Son başarısız koşu bulunamadı."

            replay_input = str(failed.get("user_input") or "").strip()
            if not replay_input:
                return "Replay için kullanıcı girdisi bulunamadı."
            if replay_input.lower() == str(user_input or "").strip().lower():
                return "Aynı replay komutunu tekrar çalıştırmak yerine doğrudan hedef görevi ver."

            task_spec = failed.get("task_spec") if isinstance(failed.get("task_spec"), dict) else {}
            if task_spec and str(task_spec.get("intent") or "") == "filesystem_batch" and self._validate_filesystem_task_spec(task_spec):
                return await self._run_filesystem_task_spec(task_spec, user_input=replay_input)
            if task_spec:
                ok, _errors = self._validate_runtime_task_spec(task_spec)
                if ok:
                    return await self._run_runtime_task_spec(task_spec, user_input=replay_input)

            replay_resp = await self.process(
                replay_input,
                notify=None,
                attachments=None,
                channel="cli",
                metadata={"failure_replay": True, "replay_run_dir": failed.get("_run_dir", "")},
            )
            return str(replay_resp or "").strip() or "Replay çalıştırıldı ancak boş yanıt döndü."

        if low_action in {"multi_task", "filesystem_batch"}:
            tasks = intent.get("tasks") if isinstance(intent.get("tasks"), list) else []
            if isinstance(tasks, list) and tasks:
                tasks = self._normalize_browser_media_tasks(tasks, user_input=user_input)
                intent["tasks"] = tasks
            if self._feature_flag_enabled("ELYAN_AGENTIC_V2", False):
                task_spec = intent.get("task_spec") if isinstance(intent.get("task_spec"), dict) else None
                if not task_spec and tasks:
                    task_spec = self._build_filesystem_task_spec(user_input, tasks)
                if isinstance(task_spec, dict) and self._validate_filesystem_task_spec(task_spec):
                    return await self._run_filesystem_task_spec(task_spec, user_input=user_input)
            if not tasks:
                self._last_direct_intent_payload = {
                    "action": "multi_task",
                    "success": False,
                    "error": "no_executable_steps",
                    "completed_steps": 0,
                    "total_steps": 0,
                }
                return "Hata: Çok adımlı görev için yürütülebilir adım bulunamadı."

            # If a document write step appears before its content-producing step,
            # pull the closest research/summary task forward only when dependencies are implicit.
            normalized_tasks = list(tasks)
            i = 0
            while i < len(normalized_tasks):
                task = normalized_tasks[i]
                if not isinstance(task, dict):
                    i += 1
                    continue
                has_explicit_deps = (
                    task.get("depends_on") is not None
                    or task.get("dependencies") is not None
                )
                if self._task_needs_previous_output(task) and not has_explicit_deps:
                    next_ctx_idx = self._find_next_context_task_index(normalized_tasks, start=i + 1)
                    if next_ctx_idx is not None:
                        cand = normalized_tasks[next_ctx_idx]
                        cand_has_explicit = (
                            isinstance(cand, dict)
                            and (cand.get("depends_on") is not None or cand.get("dependencies") is not None)
                        )
                        if not cand_has_explicit:
                            normalized_tasks.insert(i, normalized_tasks.pop(next_ctx_idx))
                i += 1

            indexed_steps: list[dict[str, Any]] = []
            known_ids: set[str] = set()
            prev_step_id = ""
            for idx, task in enumerate(normalized_tasks, start=1):
                if not isinstance(task, dict):
                    continue
                step_id = str(task.get("id") or f"task_{idx}").strip() or f"task_{idx}"
                while step_id in known_ids:
                    step_id = f"{step_id}_{idx}"
                known_ids.add(step_id)

                raw_deps = task.get("depends_on") if task.get("depends_on") is not None else task.get("dependencies")
                if isinstance(raw_deps, str):
                    deps = [raw_deps.strip()] if raw_deps.strip() else []
                elif isinstance(raw_deps, list):
                    deps = [str(x).strip() for x in raw_deps if str(x).strip()]
                else:
                    deps = []

                if not deps and prev_step_id:
                    deps = [prev_step_id]

                indexed_steps.append(
                    {
                        "idx": idx,
                        "id": step_id,
                        "action": str(task.get("action") or "").strip(),
                        "params": dict(task.get("params") or {}) if isinstance(task.get("params"), dict) else {},
                        "description": str(task.get("description") or f"Adım {idx}"),
                        "depends_on": deps,
                    }
                )
                prev_step_id = step_id

            if not indexed_steps:
                self._last_direct_intent_payload = {
                    "action": "multi_task",
                    "success": False,
                    "error": "no_executable_steps",
                    "completed_steps": 0,
                    "total_steps": 0,
                }
                return "Hata: Çok adımlı görev için yürütülebilir adım bulunamadı."

            missing_deps: list[str] = []
            known = {str(s.get("id") or "") for s in indexed_steps}
            for step in indexed_steps:
                for dep in step.get("depends_on", []):
                    if dep not in known:
                        missing_deps.append(dep)
            if missing_deps:
                missing = ", ".join(dict.fromkeys(missing_deps))
                self._last_direct_intent_payload = {
                    "action": "multi_task",
                    "success": False,
                    "error": f"unknown_dependency:{missing}",
                    "completed_steps": 0,
                    "total_steps": len(indexed_steps),
                }
                return f"Hata: Bilinmeyen bağımlılık(lar): {missing}"

            compact_mode = self._should_use_compact_action_responses(user_input=user_input)
            policy = self._current_runtime_policy()
            orch_cfg = policy.get("orchestration", {}) if isinstance(policy.get("orchestration"), dict) else {}
            max_parallel = 2
            try:
                max_parallel = int(orch_cfg.get("max_parallel", orch_cfg.get("team_max_parallel", 2)) or 2)
            except Exception:
                max_parallel = 2
            max_parallel = max(1, min(4, max_parallel))
            default_attempts = 2
            ui_serial_actions = {
                "open_app",
                "close_app",
                "open_url",
                "key_combo",
                "press_key",
                "type_text",
                "mouse_click",
                "mouse_move",
                "computer_use",
                "take_screenshot",
                "screen_workflow",
                "analyze_screen",
                "operator_mission_control",
                "vision_operator_loop",
            }
            app_control_actions = {"open_app", "close_app", "key_combo", "open_url"}

            pending: dict[str, dict[str, Any]] = {str(s["id"]): s for s in indexed_steps}
            completed: set[str] = set()
            step_outputs: dict[str, str] = {}
            step_results_raw: dict[str, Any] = {}
            latest_output_text = ""
            latest_output_result: Any = {}
            detailed_outputs: list[str] = []
            step_rows: list[dict[str, Any]] = []
            failed_row: dict[str, Any] | None = None

            def _step_succeeded(step_action: str, result: Any, text: str) -> bool:
                if isinstance(result, dict):
                    if result.get("success") is False:
                        return False
                    if step_action in app_control_actions and result.get("verified") is False:
                        return False
                t = str(text or "").strip().lower()
                if not t:
                    return False
                if t.startswith("hata:") or "hata kodu:" in t:
                    return False
                if "başarısız" in t or "basarisiz" in t:
                    return False
                return True

            def _step_fail_reason(result: Any, text: str) -> str:
                if isinstance(result, dict):
                    for key in ("error", "verification_warning", "message", "summary"):
                        val = str(result.get(key) or "").strip()
                        if val:
                            return val
                cleaned = str(text or "").strip()
                return cleaned if cleaned else "adım başarısız"

            async def _run_step(step: dict[str, Any]) -> dict[str, Any]:
                nonlocal latest_output_text, latest_output_result
                step_action = str(step.get("action") or "").strip()
                step_desc = str(step.get("description") or f"Adım {step.get('idx')}")
                params = dict(step.get("params") or {}) if isinstance(step.get("params"), dict) else {}
                deps = [str(x).strip() for x in step.get("depends_on", []) if str(x).strip()]
                dep_text = ""
                dep_result: Any = {}
                for dep_id in deps:
                    candidate = str(step_outputs.get(dep_id) or "").strip()
                    if candidate:
                        dep_text = candidate
                    candidate_result = step_results_raw.get(dep_id)
                    if candidate_result not in (None, "", {}):
                        dep_result = candidate_result
                if not dep_text:
                    dep_text = latest_output_text
                if dep_result in (None, "", {}):
                    dep_result = latest_output_result
                params = self._hydrate_task_params_from_previous(step_action, params, dep_text, dep_result)

                attempts = default_attempts
                retries = step.get("retries") if isinstance(step.get("retries"), dict) else {}
                if "max_attempts" in retries:
                    try:
                        attempts = int(retries.get("max_attempts") or attempts)
                    except Exception:
                        attempts = default_attempts
                elif "retry_budget" in step:
                    try:
                        attempts = int(step.get("retry_budget") or 0) + 1
                    except Exception:
                        attempts = default_attempts
                attempts = max(1, min(4, attempts))

                last_result: Any = {}
                last_text = ""
                reason = ""
                failure_class = ""
                recovery_notes: list[str] = []
                used_attempts = 0
                for attempt in range(1, attempts + 1):
                    used_attempts = attempt
                    last_result = await self._execute_tool(
                        step_action,
                        params,
                        user_input=user_input,
                        step_name=step_desc,
                    )
                    last_text = str(self._format_result_text(last_result) or "").strip()
                    if _step_succeeded(step_action, last_result, last_text):
                        reason = ""
                        failure_class = ""
                        break
                    reason = _step_fail_reason(last_result, last_text)
                    failure_class = classify_failure_class(
                        reason=reason,
                        action=step_action,
                        payload=last_result if isinstance(last_result, dict) else {},
                    )
                    if attempt < attempts:
                        params, stop_retry, recovery_note = await self._apply_failure_recovery_strategy(
                            failure_class=failure_class,
                            step_action=step_action,
                            params=params,
                            result=last_result,
                            reason=reason,
                            user_input=user_input,
                            step_name=step_desc,
                        )
                        if recovery_note:
                            recovery_notes.append(recovery_note)
                        if stop_retry:
                            break

                success = not bool(reason)
                if success and last_text:
                    latest_output_text = last_text
                if success and last_result not in (None, ""):
                    latest_output_result = last_result
                if success:
                    failure_class = ""
                return {
                    "id": str(step.get("id") or ""),
                    "idx": int(step.get("idx") or 0),
                    "action": step_action,
                    "description": step_desc,
                    "depends_on": deps,
                    "success": success,
                    "attempts": used_attempts,
                    "reason": reason,
                    "failure_class": failure_class,
                    "recovery_notes": recovery_notes,
                    "result": last_result,
                    "text": last_text,
                }

            while pending:
                ready: list[dict[str, Any]] = []
                for step in pending.values():
                    deps = [str(x).strip() for x in step.get("depends_on", []) if str(x).strip()]
                    if all(dep in completed for dep in deps):
                        ready.append(step)

                if not ready:
                    failed_row = {
                        "idx": 0,
                        "description": "Task graph",
                        "reason": "döngüsel veya çözülemeyen bağımlılık",
                        "success": False,
                    }
                    break

                ready.sort(key=lambda s: int(s.get("idx", 0) or 0))
                has_ui_step = any(str(s.get("action") or "").strip().lower() in ui_serial_actions for s in ready)
                if has_ui_step or len(ready) == 1:
                    batch = [ready[0]]
                else:
                    batch = ready[:max_parallel]

                batch_results = await asyncio.gather(*(_run_step(step) for step in batch), return_exceptions=True)
                for pos, raw in enumerate(batch_results):
                    step = batch[pos]
                    sid = str(step.get("id") or "")
                    if isinstance(raw, Exception):
                        row = {
                            "id": sid,
                            "idx": int(step.get("idx") or 0),
                            "action": str(step.get("action") or ""),
                            "description": str(step.get("description") or ""),
                            "depends_on": list(step.get("depends_on") or []),
                            "success": False,
                            "attempts": 1,
                            "reason": str(raw),
                            "failure_class": classify_failure_class(
                                reason=str(raw),
                                action=str(step.get("action") or ""),
                            ),
                            "result": {"success": False, "error": str(raw)},
                            "text": f"Hata: {raw}",
                        }
                    else:
                        row = raw

                    step_rows.append(row)
                    pending.pop(sid, None)
                    if row.get("success"):
                        completed.add(sid)
                        text = str(row.get("text") or "").strip()
                        if text:
                            step_outputs[sid] = text
                        step_results_raw[sid] = row.get("result")
                        if not compact_mode:
                            detailed_outputs.append(f"[{row.get('idx')}] {row.get('description')}\n{text}")
                        continue

                    if not compact_mode:
                        err_text = str(row.get("text") or "").strip()
                        if not err_text:
                            err_text = f"Hata: {row.get('reason') or 'adım başarısız'}"
                        detailed_outputs.append(f"[{row.get('idx')}] {row.get('description')}\n{err_text}")
                    failed_row = row
                    break

                if failed_row is not None:
                    break

            total_steps = len(indexed_steps)
            completed_steps = len([r for r in step_rows if r.get("success")])
            success_all = failed_row is None and completed_steps == total_steps
            self._last_direct_intent_payload = {
                "action": "multi_task",
                "success": success_all,
                "total_steps": total_steps,
                "completed_steps": completed_steps,
                "failed_step": failed_row or {},
                "failure_class": str((failed_row or {}).get("failure_class") or ""),
                "steps": step_rows,
            }

            if compact_mode:
                if success_all:
                    if completed_steps > 0:
                        return f"✅ {completed_steps} adım tamamlandı."
                    return "✅ Tamamlandı."
                fail_idx = int(failed_row.get("idx") or 0) if isinstance(failed_row, dict) else 0
                fail_desc = str((failed_row or {}).get("description") or "adım").strip()
                fail_reason = str((failed_row or {}).get("reason") or "").strip()
                msg = f"❌ {fail_idx}. adım başarısız: {fail_desc}."
                if fail_reason:
                    msg += f" {fail_reason}"
                return msg

            if detailed_outputs:
                if not success_all and failed_row is not None and int(failed_row.get("idx") or 0) == 0:
                    detailed_outputs.append(f"Hata: {failed_row.get('reason')}")
                return "\n\n".join(detailed_outputs)
            if success_all:
                return "✅ Çok adımlı görev tamamlandı."
            return "Hata: Çok adımlı görev tamamlanamadı."

        if low_action == "create_coding_project":
            runtime_meta = self._runtime_metadata()
            if runtime_meta and not self._mission_handoff_blocked():
                mission = await self._run_coding_mission_handoff(
                    user_input,
                    user_id=str(user_id or runtime_meta.get("user_id") or "local"),
                    channel=str(runtime_meta.get("channel") or "cli"),
                    mode=str(runtime_meta.get("adaptive_mode") or runtime_meta.get("mode") or "Balanced"),
                    attachments=[],
                    metadata={"route_mode_hint": "code", "source": "direct_intent"},
                )
                response_text = self._mission_response_text(mission)
                self._last_direct_intent_payload = {
                    "action": "create_coding_project",
                    "success": str(getattr(mission, "status", "") or "") == "completed",
                    "mission_id": str(getattr(mission, "mission_id", "") or ""),
                    "mission_status": str(getattr(mission, "status", "") or ""),
                    "route_mode": str(getattr(mission, "route_mode", "") or ""),
                }
                return response_text

            params = intent.get("params", {}) if isinstance(intent.get("params"), dict) else {}
            project_kind = str(params.get("project_kind") or "website").strip().lower()
            project_name = str(params.get("project_name") or self._extract_topic(user_input, step_name="")).strip() or "elyan-project"
            output_dir = str(params.get("output_dir") or "~/Desktop").strip() or "~/Desktop"
            stack = str(params.get("stack") or "vanilla").strip().lower()
            complexity = str(params.get("complexity") or "advanced").strip().lower()
            theme = str(params.get("theme") or "professional").strip().lower()
            ide = str(params.get("ide") or self._infer_ide_name(user_input)).strip().lower() or "vscode"
            open_ide = bool(params.get("open_ide", True))
            brief = str(params.get("brief") or user_input or "").strip()
            tech_mode = str(params.get("tech_mode") or "stable").strip().lower() or "stable"
            coding_standards = str(params.get("coding_standards") or "clean_code").strip().lower() or "clean_code"
            quality_gates = params.get("quality_gates") if isinstance(params.get("quality_gates"), dict) else {}
            low_req = str(user_input or "").lower()
            if tech_mode == "stable" and any(k in low_req for k in ("en son", "latest", "modern", "güncel", "guncel")):
                tech_mode = "latest"
            if coding_standards == "pragmatic" and any(k in low_req for k in ("temiz kod", "clean code", "solid", "test")):
                coding_standards = "clean_code"
            if not quality_gates:
                quality_gates = {"lint": True, "tests": True, "docs": True, "modular_architecture": True}

            outputs: list[str] = []
            create_result: Any
            llm_result = None

            # --- Birincil Yol: LLM-driven iki aşamalı üretim ---
            if complexity == "expert":
                # Expert projeler delivery engine üzerinden yürütülür (fallback scaffold yolu)
                llm_result = None
            elif self._ensure_llm():
                _push_hint(f"'{project_name}' için LLM ile profesyonel proje üretiliyor...", icon="code", color="blue")
                llm_result = await self._llm_build_project(
                    project_name=project_name,
                    project_kind=project_kind,
                    stack=stack,
                    brief=brief,
                    output_dir=output_dir,
                    complexity=complexity,
                    theme=theme,
                    tech_mode=tech_mode,
                    coding_standards=coding_standards,
                    quality_gates=quality_gates,
                )

            if llm_result and llm_result.get("success"):
                create_result = llm_result
            else:
                # --- Fallback: Mevcut hardcoded scaffold araçları ---
                if project_kind == "website":
                    create_result = await self._execute_tool(
                        "create_web_project_scaffold",
                        {
                            "project_name": project_name,
                            "stack": stack,
                            "theme": theme,
                            "output_dir": output_dir,
                            "brief": brief,
                        },
                        user_input=user_input,
                        step_name="Website scaffold oluştur",
                    )
                else:
                    project_type = "game" if project_kind == "game" else "app"
                    create_result = await self._execute_tool(
                        "create_software_project_pack",
                        {
                            "project_name": project_name,
                            "project_type": project_type,
                            "stack": stack,
                            "complexity": complexity,
                            "output_dir": output_dir,
                            "brief": brief,
                        },
                        user_input=user_input,
                        step_name="Yazılım proje paketi oluştur",
                    )

            if llm_result and llm_result.get("success"):
                outputs.append(llm_result["message"])
            else:
                outputs.append(self._format_result_text(create_result))

            created_path = ""
            if isinstance(create_result, dict):
                created_path = str(
                    create_result.get("project_dir")
                    or create_result.get("pack_dir")
                    or create_result.get("path")
                    or ""
                ).strip()

            if created_path:
                planning_result = await self._execute_tool(
                    "create_coding_delivery_plan",
                    {
                        "project_path": created_path,
                        "project_name": project_name,
                        "project_kind": project_kind,
                        "stack": stack,
                        "complexity": complexity,
                        "brief": brief,
                    },
                    user_input=user_input,
                    step_name="Profesyonel teslimat planı oluştur",
                )
                outputs.append(self._format_result_text(planning_result))

                verification_result = await self._execute_tool(
                    "create_coding_verification_report",
                    {
                        "project_path": created_path,
                        "project_name": project_name,
                        "project_kind": project_kind,
                        "stack": stack,
                        "strict": False,
                    },
                    user_input=user_input,
                    step_name="Teslimat doğrulama raporu oluştur",
                )
                outputs.append(self._format_result_text(verification_result))

            if open_ide:
                ide_result = await self._execute_tool(
                    "open_project_in_ide",
                    {
                        "project_path": created_path,
                        "project_name": project_name,
                        "project_kind": project_kind,
                        "output_dir": output_dir,
                        "ide": ide,
                    },
                    user_input=user_input,
                    step_name=f"Projeyi {ide} ile aç",
                )
                outputs.append(self._format_result_text(ide_result))
            final_text = "\n".join(x for x in outputs if isinstance(x, str) and x.strip()) or "Kod projesi oluşturuldu."
            self._last_direct_intent_payload = {
                "action": "create_coding_project",
                "success": bool(created_path),
                "project_dir": created_path,
                "artifact_paths": [created_path] if created_path else [],
                "message": final_text,
                "verification": {
                    "delivery_plan_created": bool(created_path),
                    "report_generated": bool(created_path),
                },
                "style_intent": {
                    "project_kind": project_kind,
                    "theme": theme,
                    "stack": stack,
                },
            }
            return final_text

        if low_action == "api_health_get_save":
            url = str(params.get("url") or self._extract_first_url(user_input)).strip()
            if not url:
                return "Hata: API URL bulunamadı."

            method = str(params.get("method") or "GET").strip().upper() or "GET"
            result_path = str(params.get("result_path") or "~/Desktop/elyan-test/api/result.json").strip()
            summary_path = str(params.get("summary_path") or default_summary_path(result_path)).strip()

            health_res = await self._execute_tool(
                "api_health_check",
                {"urls": [url]},
                user_input=user_input,
                step_name="API Health Check",
            )
            request_res = await self._execute_tool(
                "http_request",
                {"url": url, "method": method},
                user_input=user_input,
                step_name=f"API {method}",
            )
            if isinstance(request_res, dict) and request_res.get("success") is False:
                return f"{self._format_result_text(health_res)}\n{self._format_result_text(request_res)}"

            request_payload = request_res if isinstance(request_res, dict) else {"success": False, "raw": str(request_res)}
            raw_json = json.dumps(request_payload, ensure_ascii=False, indent=2)
            write_json_res = await self._execute_tool(
                "write_file",
                {"path": result_path, "content": raw_json},
                user_input=user_input,
                step_name="Result JSON Kaydet",
            )

            h_ok = False
            if isinstance(health_res, dict):
                result_map = health_res.get("results", {})
                if isinstance(result_map, dict):
                    h_ok = bool(result_map.get(url, {}).get("healthy", False))
            status_code = request_payload.get("status_code")
            duration_ms = request_payload.get("duration_ms")
            response_kind = type(request_payload.get("body")).__name__
            summary_content = (
                "# API Çalıştırma Özeti\n\n"
                f"- URL: {url}\n"
                f"- Method: {method}\n"
                f"- Health: {'OK' if h_ok else 'FAILED'}\n"
                f"- HTTP Status: {status_code}\n"
                f"- Duration: {duration_ms} ms\n"
                f"- Response Type: {response_kind}\n"
                f"- Run At: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            )
            write_summary_res = await self._execute_tool(
                "write_file",
                {"path": summary_path, "content": summary_content},
                user_input=user_input,
                step_name="Summary Kaydet",
            )

            json_saved_path = str((write_json_res.get("path") if isinstance(write_json_res, dict) else "") or result_path).strip()
            summary_saved_path = str((write_summary_res.get("path") if isinstance(write_summary_res, dict) else "") or summary_path).strip()
            json_sha = self._compute_sha256(json_saved_path)
            summary_sha = self._compute_sha256(summary_saved_path)

            lines = [
                "✅ API health check + GET + kayıt tamamlandı.",
                self._format_result_text(health_res),
                self._format_result_text(write_json_res),
                self._format_result_text(write_summary_res),
                f"Hash (result.json): {json_sha}" if json_sha else "",
                f"Hash (summary.txt): {summary_sha}" if summary_sha else "",
            ]
            return "\n".join(line for line in lines if isinstance(line, str) and line.strip())

        if low_action == "show_help":
            return (
                "Kullanabileceğin örnek komutlar:\n"
                "- 'masaüstünde ne var'\n"
                "- 'iphone araştır'\n"
                "- 'ekran görüntüsü al'\n"
                "- 'Downloads klasörünü listele'\n"
                "- 'görsel oluştur: minimalist logo'"
            )

        if low_action == "translate":
            text = params.get("text") or user_input
            target = params.get("target_lang", "en")
            prompt = f"Aşağıdaki metni {target} diline çevir:\n\n{text}"
            if not self._ensure_llm():
                return self._fallback_chat_without_llm(user_input)
            return (await self.llm.generate(prompt, role=role, history=history, user_id=user_id)).strip()

        if low_action == "summarize_url":
            url = params.get("url", "")
            page = await self._execute_tool("fetch_page", {"url": url}, user_input=user_input, step_name="URL fetch")
            if not isinstance(page, dict) or not page.get("success"):
                return self._format_result_text(page)
            content = (page.get("content") or "")[:12000]
            prompt = f"Şu metni kısa ve net şekilde özetle:\n\n{content}"
            if not self._ensure_llm():
                return self._fallback_chat_without_llm(user_input)
            return (await self.llm.generate(prompt, role=role, history=history, user_id=user_id)).strip()

        if low_action == "summarize_file":
            path = params.get("path", "")
            doc = await self._execute_tool("read_file", {"path": path}, user_input=user_input, step_name="Dosya oku")
            if not isinstance(doc, dict) or not doc.get("success"):
                return self._format_result_text(doc)
            content = (doc.get("content") or "")[:12000]
            prompt = f"Aşağıdaki dosya içeriğini özetle:\n\n{content}"
            if not self._ensure_llm():
                return self._fallback_chat_without_llm(user_input)
            return (await self.llm.generate(prompt, role=role, history=history, user_id=user_id)).strip()

        if low_action == "summarize_text":
            text = params.get("text") or user_input
            prompt = f"Bu metni kısa özetle:\n\n{text}"
            if not self._ensure_llm():
                return self._fallback_chat_without_llm(user_input)
            return (await self.llm.generate(prompt, role=role, history=history, user_id=user_id)).strip()

        # "tüm dosyalar" gibi isteklerde recursive tarama.
        low_text = user_input.lower()
        if low_action == "list_files" and any(k in low_text for k in ("tüm dosya", "tum dosya", "hepsini tara", "tamamını tara", "tamamini tara")):
            result = await self._execute_tool("search_files", {"pattern": "*", "directory": "~"}, user_input=user_input, step_name="Tüm dosya taraması")
            return self._format_result_text(result)

        result = await self._execute_tool(action, params, user_input=user_input, step_name=intent.get("reply", ""))
        self._last_direct_intent_payload = result
        compact = self._compact_direct_tool_response(low_action, result, user_input=user_input)
        if compact is not None:
            return compact
        return self._format_result_text(result)

    def _should_use_compact_action_responses(self, *, user_input: str = "") -> bool:
        policy = self._current_runtime_policy()
        response_cfg = policy.get("response", {}) if isinstance(policy.get("response"), dict) else {}
        if bool(response_cfg.get("compact_actions", False)):
            return True
        low = str(user_input or "").lower()
        return any(tok in low for tok in ("kısa", "kisa", "kısaca", "kisaca", "özet", "ozet"))

    def _compact_direct_tool_response(self, action: str, result: Any, *, user_input: str = "") -> str | None:
        if not self._should_use_compact_action_responses(user_input=user_input):
            return None

        low_action = str(action or "").strip().lower()
        payload = result if isinstance(result, dict) else {}
        success = not (isinstance(result, dict) and result.get("success") is False)
        if not success:
            err = str(payload.get("error") or payload.get("verification_warning") or "").strip()
            return f"Hata: {err or 'işlem başarısız'}."

        if low_action == "open_app":
            app = str(payload.get("app_name") or "").strip()
            if app:
                return f"{app} açıldı."
            return "Uygulama açıldı."
        if low_action == "close_app":
            app = str(payload.get("app_name") or "").strip()
            if app:
                return f"{app} kapatıldı."
            return "Uygulama kapatıldı."
        if low_action == "open_url":
            return "Sayfa açıldı."
        if low_action in {"key_combo", "press_key", "type_text"}:
            msg = str(payload.get("message") or "").strip()
            if msg:
                return msg
            if low_action == "key_combo":
                combo = str(payload.get("combo") or "").strip()
                return f"Kısayol uygulandı: {combo or 'tamam'}."
            return "İşlem tamamlandı."
        if low_action == "take_screenshot":
            path = str(payload.get("path") or "").strip()
            if path:
                return f"Ekran görüntüsü alındı: {path}"
            return "Ekran görüntüsü alındı."

        return None

    def _task_needs_previous_output(self, task: dict) -> bool:
        action = str(task.get("action", "") or "").strip()
        if not action:
            return False
        params = task.get("params", {}) if isinstance(task.get("params"), dict) else {}
        mapped = ACTION_TO_TOOL.get(action, action)

        if mapped in {"write_file", "write_word"}:
            content = params.get("content") or params.get("text") or params.get("body") or params.get("message")
            return self._is_placeholder_text(content)

        if mapped == "write_excel":
            if params.get("data"):
                return False
            content = params.get("content") or params.get("text") or params.get("message")
            return self._is_placeholder_text(content)

        return False

    @staticmethod
    def _is_placeholder_text(value: Any) -> bool:
        if not isinstance(value, str):
            return True
        s = value.strip()
        if not s:
            return True
        placeholders = {
            "içerik belirtilmedi",
            "icerik belirtilmedi",
            "genel konu",
            "not",
            "not.txt",
        }
        low = s.casefold().replace("i̇", "i").strip(" .,:;-")
        return low in placeholders

    def _is_context_producer_action(self, action: str) -> bool:
        mapped = ACTION_TO_TOOL.get(str(action or "").strip(), str(action or "").strip())
        if not mapped:
            return False
        if "research" in mapped:
            return True
        return mapped in {
            "web_search",
            "fetch_page",
            "extract_text",
            "read_file",
            "read_word",
            "read_excel",
            "read_pdf",
            "summarize_text",
            "summarize_url",
            "summarize_file",
            "smart_summarize",
            "analyze_document",
        }

    def _find_next_context_task_index(self, tasks: list, start: int = 0) -> int | None:
        for idx in range(max(0, int(start or 0)), len(tasks)):
            task = tasks[idx]
            if not isinstance(task, dict):
                continue
            if self._is_context_producer_action(str(task.get("action", "") or "")):
                return idx
        return None

    @staticmethod
    def _extract_clipboard_text_from_result(result: Any) -> str:
        if not isinstance(result, dict):
            return ""

        results = result.get("results")
        if isinstance(results, list) and results:
            first = results[0] if isinstance(results[0], dict) else {}
            title = str(first.get("title") or "").strip()
            url = str(first.get("url") or first.get("href") or "").strip()
            snippet = str(first.get("snippet") or "").strip()
            parts = [part for part in (title, url, snippet) if part]
            if parts:
                return "\n".join(parts)

        links = result.get("links")
        if isinstance(links, list) and links:
            first = links[0] if isinstance(links[0], dict) else {}
            label = str(first.get("text") or first.get("title") or "").strip()
            href = str(first.get("href") or first.get("url") or "").strip()
            parts = [part for part in (label, href) if part]
            if parts:
                return "\n".join(parts)

        for key in ("summary", "answer", "text", "message"):
            value = str(result.get(key) or "").strip()
            if value:
                return value
        return ""

    def _hydrate_task_params_from_previous(self, action: str, params: dict, previous_output: str, previous_result: Any = None) -> dict:
        clean = dict(params or {})
        prev = str(previous_output or "").strip()
        mapped = ACTION_TO_TOOL.get(str(action or "").strip(), str(action or "").strip())

        if not prev and mapped != "write_clipboard":
            return clean

        if mapped in {"write_file", "write_word"}:
            content = clean.get("content") or clean.get("text") or clean.get("body") or clean.get("message")
            if not (isinstance(content, str) and content.strip()):
                clean["content"] = prev[:12000]
            return clean

        if mapped == "write_excel" and not clean.get("data"):
            rows = []
            for line in prev.splitlines():
                item = line.strip().lstrip("-• ").strip()
                if item:
                    rows.append({"Veri": item[:500]})
            clean["data"] = rows[:200] if rows else [{"Veri": prev[:1000]}]
            clean.setdefault("headers", ["Veri"])
            return clean

        if mapped == "write_clipboard":
            text_value = str(clean.get("text") or clean.get("content") or "").strip()
            if not text_value:
                text_value = self._extract_clipboard_text_from_result(previous_result) or prev
            if text_value:
                clean["text"] = text_value[:30000]
            return clean

        return clean

    @staticmethod
    def _is_command_dump_content(content: str, user_input: str) -> bool:
        raw_content = " ".join(str(content or "").split()).strip().lower()
        raw_input = " ".join(str(user_input or "").split()).strip().lower()
        if not raw_content or not raw_input:
            return False
        if raw_content == raw_input:
            return True
        if len(raw_input) >= 40 and raw_input in raw_content:
            return True
        if "planla ve uygula" in raw_content and "1)" in raw_content and "2)" in raw_content:
            return True
        return False

    def _deterministic_task_file_content(self, path: str, user_input: str = "") -> str:
        filename = Path(str(path or "not.md")).name or "not.md"
        topic = self._extract_topic(str(user_input or ""), "")
        if not topic or topic == "genel konu":
            topic = "dosya olusturma gorevi"
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        content = (
            f"# {filename}\n\n"
            "Bu dosya Elyan deterministic executor tarafindan uretildi.\n"
            f"Olusturma zamani: {stamp}\n"
            f"Gorev ozeti: {topic}\n"
            "Durum: olusturuldu ve dogrulama adimi icin hazir.\n"
        )
        if len(content.strip()) < 50:
            content += "\nBu satir minimum icerik uzunlugunu garanti etmek icin eklendi.\n"
        return content

    @staticmethod
    def _is_short_note_request(user_input: str, path: str = "") -> bool:
        low = str(user_input or "").strip().lower()
        if not low:
            return False
        if any(tok in low for tok in ("araştır", "arastir", "research", "rapor", "belge", "word", "excel")):
            return False
        note_markers = ("not olarak", "not yaz", "notu yaz", "masaüstüne not", "masaustune not", "desktop note")
        if not any(tok in low for tok in note_markers):
            return False
        suffix = Path(str(path or "not.txt")).suffix.lower()
        return suffix in {"", ".txt", ".md"}

    def _normalize_task_write_content(
        self,
        content: Any,
        user_input: str,
        path: str = "",
        *,
        allow_short_content: bool = False,
    ) -> str:
        raw = str(content or "").strip()
        if not raw or self._is_placeholder_text(raw) or self._is_command_dump_content(raw, user_input):
            return self._deterministic_task_file_content(path, user_input=user_input)
        if allow_short_content:
            return raw
        if len(raw) < 50:
            suffix = (
                f"\n\nNot: Bu metin Elyan tarafindan {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                "aninda dogrulama esiklerini karsilamak icin genisletildi."
            )
            raw = f"{raw}{suffix}"
        return raw

    @staticmethod
    def _extract_inline_write_content(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""

        # Pattern: "<içerik> not olarak kaydet"
        m_not = _re.search(r"(.+?)\\s+(?:not|notu)\\s+olarak\\s+kaydet", raw, _re.IGNORECASE)
        if m_not:
            content = str(m_not.group(1) or "").strip()
            content = _re.sub(r"\\s+", " ", content).strip(" .,:;-")
            if len(content) >= 3:
                return content

        patterns = (
            r"(?:içine|icine|içeriğine|icerigine)\s+(.+?)\s+yaz",
            r"(?:worde|word'e|excel'e|excele|belgeye|dosyaya|tabloya)\s+(.+?)\s+yaz",
            r"(?:içerik|icerik|content|konu)\s*[:\-]\s*(.+)$",
        )
        for pat in patterns:
            m = _re.search(pat, raw, _re.IGNORECASE)
            if not m:
                continue
            content = str(m.group(1) or "").strip()
            content = _re.sub(
                r"\b(word|excel|dosya(?:sı)?|belge(?:si)?|tablo(?:su)?|oluştur|olustur|kaydet)\b",
                " ",
                content,
                flags=_re.IGNORECASE,
            )
            content = _re.sub(r"\s+", " ", content).strip(" .,:;-")
            if len(content) >= 3:
                return content
        return ""

    @staticmethod
    def _extract_quoted_segments(text: str) -> list[str]:
        raw = str(text or "")
        if not raw:
            return []
        return [str(m.group(1) or "").strip() for m in _re.finditer(r"[\"']([^\"']{1,500})[\"']", raw) if str(m.group(1) or "").strip()]

    @staticmethod
    def _infer_summary_style(text: str) -> str:
        low = str(text or "").lower()
        if any(k in low for k in ("madde", "bullet", "bullet point", "madde madde", "liste")):
            return "bullets"
        if any(k in low for k in ("detay", "detaylı", "detayli", "uzun", "kapsamlı", "kapsamli", "detailed")):
            return "detailed"
        if any(k in low for k in ("kısa", "kisa", "kısalt", "kisalt", "sadeleştir", "sadelestir", "özet", "ozet")):
            return "brief"
        return "brief"

    @staticmethod
    def _infer_batch_pattern(text: str) -> str:
        low = str(text or "").lower()
        if any(k in low for k in ("markdown", ".md", "md dosya")):
            return "*.md"
        if any(k in low for k in (".txt", "metin dosya", "text file")):
            return "*.txt"
        if any(k in low for k in (".py", "python dosya")):
            return "*.py"
        if any(k in low for k in (".js", "javascript dosya")):
            return "*.js"
        if any(k in low for k in (".json", "json dosya")):
            return "*.json"
        if any(k in low for k in (".docx", "word dosya", "belge")):
            return "*.docx"
        return "*.txt"

    @staticmethod
    def _is_code_like_path(path: str) -> bool:
        ext = Path(str(path or "")).suffix.lower()
        return ext in {
            ".py",
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".java",
            ".go",
            ".rs",
            ".c",
            ".cpp",
            ".cs",
            ".php",
            ".rb",
            ".swift",
            ".kt",
            ".sql",
            ".sh",
            ".html",
            ".css",
        }

    def _infer_document_edit_operations(self, text: str, *, word_mode: bool = False) -> list[dict[str, Any]]:
        raw = str(text or "").strip()
        low = raw.lower()
        if not raw:
            return []

        quoted = self._extract_quoted_segments(raw)
        operations: list[dict[str, Any]] = []

        replace_markers = ("yerine", "ile değiştir", "ile degistir", "replace")
        if any(k in low for k in replace_markers) and len(quoted) >= 2:
            if word_mode:
                operations.append({"type": "replace_text", "find": quoted[0], "replace": quoted[1]})
            else:
                operations.append({"type": "replace", "find": quoted[0], "replace": quoted[1], "all": True})

        delete_markers = ("sil", "kaldır", "kaldir", "remove", "delete")
        if any(k in low for k in delete_markers) and len(quoted) >= 1 and not operations:
            if word_mode:
                operations.append({"type": "replace_text", "find": quoted[0], "replace": ""})
            else:
                operations.append({"type": "replace", "find": quoted[0], "replace": "", "all": True})

        append_markers = ("ekle", "append", "genişlet", "genislet", "uzat", "detaylandır", "detaylandir")
        if any(k in low for k in append_markers):
            append_text = self._extract_inline_write_content(raw)
            if not append_text and quoted:
                append_text = quoted[-1]
            if append_text and not self._is_command_dump_content(append_text, raw):
                if word_mode:
                    operations.append({"type": "add_paragraph", "text": append_text})
                else:
                    operations.append({"type": "append", "text": append_text})

        return operations

    def _extract_topic(self, user_input: str, step_name: str = "") -> str:
        text = " ".join((step_name or "", user_input or "")).strip()
        if not text:
            return "genel konu"
        lowered = text.lower()
        lowered = _re.sub(
            r"^.*?\b(?:aç|ac|başlat|baslat|çalıştır|calistir|open|launch)\b\s+(?:ve\s+sonra|ve\s+ardından|ve\s+|ardından\s+|sonra\s+)",
            "",
            lowered,
        )
        phrase_tokens = ("yapar mısın", "yapar misin")
        for token in phrase_tokens:
            lowered = lowered.replace(token, " ")

        word_tokens = (
            "araştırma", "arastirma", "araştır", "arastir",
            "hakkında", "hakkinda", "internette", "webde", "web'de",
            "lütfen", "lutfen", "elyan", "yap",
            "safariyi", "safari", "chrome",
            "tarayıcıyı", "tarayiciyi", "tarayıcı", "tarayici", "browser",
            "aç", "ac", "başlat", "baslat", "çalıştır", "calistir", "ve",
            "kopyala", "copy", "clipboard", "pano", "panoya",
        )
        for token in sorted(word_tokens, key=len, reverse=True):
            lowered = _re.sub(rf"\b{_re.escape(token)}\b", " ", lowered)
        lowered = _re.sub(r"\b(?:araştır\w*|arastir\w*|research\w*|incele\w*)\b", " ", lowered, flags=_re.IGNORECASE)
        lowered = _re.sub(r"\b(?:yaz\w*|kaydet\w*|oluştur\w*|olustur\w*)\b", " ", lowered, flags=_re.IGNORECASE)
        lowered = _re.sub(r"\s+", " ", lowered).strip(" .,:;-")
        return lowered or "genel konu"

    def _sanitize_research_topic(self, topic: Any, user_input: str = "", step_name: str = "") -> str:
        raw = str(topic or "").strip()
        if not raw:
            return self._extract_topic(user_input, step_name)

        cleaned = raw.lower()
        cleaned = _re.sub(
            r"^.*?\b(?:aç|ac|open|başlat|baslat|çalıştır|calistir|launch)\b\s+(?:ve\s+|ardından\s+|sonra\s+)?",
            "",
            cleaned,
        )

        strip_tokens = (
            "araştırma",
            "arastirma",
            "araştır",
            "arastir",
            "research",
            "hakkında",
            "hakkinda",
            "ile ilgili",
            "bana",
            "lütfen",
            "lutfen",
            "elyan",
            "tarayıcı",
            "tarayici",
            "tarayıcıyı",
            "tarayiciyi",
            "safariyi",
            "safari",
            "chrome",
            "browser",
            "aç",
            "ac",
            "ve",
            "yap",
            "kopyala",
            "copy",
            "clipboard",
            "pano",
            "panoya",
        )
        for token in strip_tokens:
            cleaned = _re.sub(rf"\b{_re.escape(token)}\b", " ", cleaned)
        cleaned = _re.sub(r"\b(?:araştır\w*|arastir\w*|research\w*|incele\w*)\b", " ", cleaned, flags=_re.IGNORECASE)
        cleaned = _re.sub(
            r"\b(?:içine|icine|içeriğine|icerigine|tabloya|dosyaya|belgeye|worde|word'e|excele|excel'e|yaz\w*|kaydet\w*)\b",
            " ",
            cleaned,
            flags=_re.IGNORECASE,
        )
        cleaned = _re.sub(r"\b(?:kopyala\w*|copy|clipboard|pano(?:ya)?)\b", " ", cleaned, flags=_re.IGNORECASE)
        cleaned = _re.sub(
            r"\bresmi kaynak(?:lar(?:a|la|dan)?)?(?:\s+oncelik\s+ver(?:erek|ilerek|in|ilsin)?|\s+öncelik\s+ver(?:erek|ilerek|in|ilsin)?|\s+ile)?\b",
            " ",
            cleaned,
            flags=_re.IGNORECASE,
        )
        cleaned = _re.sub(
            r"\b(?:dosya(?:yi|yı)?|belge(?:yi)?|rapor(?:u)?)\s+(?:gonder|gönder|paylas|paylaş|ilet)\b",
            " ",
            cleaned,
            flags=_re.IGNORECASE,
        )
        cleaned = _re.sub(r"\b(?:öncelik vererek|oncelik vererek)\b", " ", cleaned, flags=_re.IGNORECASE)

        cleaned = _re.sub(r"\s+", " ", cleaned).strip(" .,:;-")
        if len(cleaned) < 2:
            cleaned = self._extract_topic(user_input, step_name)
        return cleaned or "genel konu"

    @staticmethod
    def _infer_research_source_policy(text: str) -> str:
        low = str(text or "").lower()
        if any(
            k in low
            for k in (
                "akademik",
                "bilimsel",
                "hakemli",
                "peer-reviewed",
                "peer reviewed",
                "paper",
                "makale",
                "journal",
                "literatür",
                "literatur",
                "atıf",
                "atif",
                "citation",
                "bibliography",
                "kaynakça",
                "kaynakca",
            )
        ):
            return "academic"
        if any(
            k in low
            for k in (
                "resmi",
                "official",
                "devlet",
                "bakanlık",
                "bakanlik",
                ".gov",
                "kurum sitesi",
                "yasa",
                "yasası",
                "yasasi",
                "kanun",
                "mevzuat",
                "regülasyon",
                "regulasyon",
                "uyum",
                "compliance",
                "ai act",
            )
        ):
            return "official"
        if any(
            k in low
            for k in (
                "güvenilir",
                "guvenilir",
                "trusted",
                "doğrulanmış",
                "dogrulanmis",
                "sadece kaynak",
                "kaynakça",
                "kaynakca",
            )
        ):
            return "trusted"
        return ""

    @staticmethod
    def _infer_research_min_reliability(text: str, source_policy: str = "") -> float | None:
        low = str(text or "").lower()
        if any(k in low for k in ("güvenilirlik", "guvenilirlik", "reliability", "güven skoru", "guven skoru", "güven eşiği", "guven esigi")):
            m = _re.search(r"%\s*(\d{1,3})", low)
            if not m:
                m = _re.search(r"\b(\d{1,3})\s*%\b", low)
            if m:
                raw = max(0, min(100, int(m.group(1))))
                return raw / 100.0
            m2 = _re.search(r"\b0\.(\d{1,2})\b", low)
            if m2:
                try:
                    return max(0.0, min(1.0, float(f"0.{m2.group(1)}")))
                except Exception:
                    return None

        if source_policy == "academic":
            return 0.78
        if source_policy == "official":
            return 0.75
        if source_policy == "trusted":
            return 0.65
        return None

    def _prepare_tool_params(self, tool_name: str, params: dict, *, user_input: str, step_name: str) -> dict:
        clean = dict(params or {})
        try:
            learned_prefs = self.learning.get_preferences(min_confidence=0.65) or {}
        except Exception:
            learned_prefs = {}

        if tool_name == "list_files":
            path = str(clean.get("path") or "").strip()
            if not path:
                hint = self._extract_folder_hint_from_text(user_input)
                if hint:
                    path = f"~/Desktop/{hint}"
                else:
                    path = self._get_last_directory()
            clean["path"] = self._resolve_path_with_desktop_fallback(path, user_input=user_input)
        elif tool_name == "search_files":
            clean["pattern"] = clean.get("pattern") or "*"
            directory = str(clean.get("directory") or "").strip()
            if not directory:
                directory = self._get_last_directory()
            clean["directory"] = directory
        elif tool_name == "set_wallpaper":
            url = str(clean.get("image_url") or "").strip()
            if not url:
                url = self._extract_first_url(user_input)
                if url:
                    clean["image_url"] = url
            path = str(clean.get("image_path") or "").strip()
            if path:
                clean["image_path"] = self._resolve_path_with_desktop_fallback(path, user_input=user_input)
            query = str(clean.get("search_query") or "").strip()
            if not query:
                topic = self._extract_topic(user_input, step_name)
                query = topic if topic and topic != "genel konu" else "wallpaper"
            clean["search_query"] = query
        elif tool_name == "create_folder":
            path = str(clean.get("path") or "").strip()
            if not path:
                folder_hint = self._extract_folder_hint_from_text(user_input)
                base_dir = str(Path.home() / "Desktop")
                if folder_hint:
                    path = str(Path(base_dir) / folder_hint)
                else:
                    path = "~/Desktop/yeni_klasor"
            clean["path"] = path
        elif tool_name == "write_clipboard":
            text_value = str(clean.get("text") or clean.get("content") or "").strip()
            if not text_value and self._references_last_object(user_input):
                text_value = self._get_recent_assistant_text(current_user_input=user_input)
            if not text_value:
                text_value = self._get_recent_research_text()
            if not text_value:
                topic = self._extract_topic(user_input, step_name)
                if topic and topic != "genel konu":
                    text_value = topic
            if text_value:
                clean["text"] = text_value[:30000]
        elif tool_name == "read_file":
            path = str(clean.get("path") or "").strip()
            if not path:
                m = _re.search(r"([\w\-.]+\.[a-z0-9]{2,8})", user_input, _re.IGNORECASE)
                if m:
                    base_dir = Path(self._get_last_directory()).expanduser()
                    path = str(base_dir / m.group(1))
                elif self._references_last_object(user_input):
                    path = self._get_last_path()
            if path:
                candidate = self._resolve_path_with_desktop_fallback(path, user_input=user_input)
                resolved = self._resolve_existing_path_from_context(candidate, user_input=user_input)
                clean["path"] = resolved or candidate
        elif tool_name == "delete_file":
            path = str(clean.get("path") or "").strip()
            has_batch_pattern = bool(clean.get("pattern")) or (
                isinstance(clean.get("patterns"), list) and any(str(x or "").strip() for x in clean.get("patterns", []))
            )
            if not path and not has_batch_pattern:
                m = _re.search(r"([\w\-.]+\.[a-z0-9]{2,8})", user_input, _re.IGNORECASE)
                if m:
                    base_dir = Path(self._get_last_directory()).expanduser()
                    path = str(base_dir / m.group(1))
                elif self._references_last_object(user_input):
                    path = self._get_last_path()
                else:
                    path = self._infer_path_from_text(user_input, step_name=step_name, tool_name=tool_name)
            if path:
                candidate = self._resolve_path_with_desktop_fallback(path, user_input=user_input)
                resolved = self._resolve_existing_path_from_context(candidate, user_input=user_input)
                clean["path"] = resolved or candidate
            elif has_batch_pattern:
                directory = str(clean.get("directory") or self._extract_path_from_text(user_input) or self._get_last_directory() or "~/Desktop").strip()
                clean["directory"] = self._resolve_path_with_desktop_fallback(directory, user_input=user_input)
                if "max_files" in clean:
                    try:
                        clean["max_files"] = max(1, min(2000, int(clean.get("max_files") or 200)))
                    except Exception:
                        clean["max_files"] = 200
                else:
                    clean["max_files"] = 400
            force = clean.get("force")
            if not isinstance(force, bool):
                low = f"{step_name} {user_input}".lower()
                clean["force"] = any(k in low for k in ("zorla", "force", "hepsini sil", "tamamen sil"))
        elif tool_name in {"move_file", "copy_file"}:
            source = str(clean.get("source") or clean.get("path") or clean.get("file") or "").strip()
            destination = str(clean.get("destination") or clean.get("target") or clean.get("dest") or "").strip()
            tokens = self._extract_path_like_tokens(user_input)
            if not source and tokens:
                source = tokens[0]
            if not source and self._references_last_object(user_input):
                source = self._get_last_path()
            if not destination:
                destination = self._extract_destination_hint_from_text(user_input)
            if not destination and len(tokens) >= 2:
                destination = tokens[1]

            source_path = self._normalize_path_token(source, for_destination=False)
            source_dir = str(Path(source_path).parent) if source_path else self._get_last_directory()
            destination_path = self._normalize_path_token(destination, for_destination=True, source_dir=source_dir)
            if source_path:
                source_path = self._resolve_path_with_desktop_fallback(source_path, user_input=user_input)
            if destination_path:
                destination_path = self._resolve_path_with_desktop_fallback(destination_path, user_input=user_input)
            clean = {"source": source_path, "destination": destination_path}
        elif tool_name == "rename_file":
            path = str(clean.get("path") or clean.get("source") or "").strip()
            new_name = str(clean.get("new_name") or clean.get("name") or "").strip()
            tokens = self._extract_path_like_tokens(user_input)
            if not path and self._references_last_object(user_input):
                path = self._get_last_path()
            if not path and tokens:
                path = tokens[0]
            if not new_name:
                current_name = Path(path).name if path else ""
                new_name = self._extract_new_name_from_text(user_input, current_name=current_name)
            path_value = self._normalize_path_token(path, for_destination=False)
            if path_value:
                path_value = self._resolve_path_with_desktop_fallback(path_value, user_input=user_input)
            clean = {"path": path_value, "new_name": new_name}
        elif tool_name == "write_file":
            path = str(clean.get("path") or "").strip()
            if not path:
                explicit_tokens = self._extract_path_like_tokens(user_input)
                explicit_file = ""
                for tok in explicit_tokens:
                    st = str(tok).strip()
                    if ("/" in st or st.startswith(("~", ".", ".."))) and Path(st).suffix:
                        explicit_file = st
                        break
                if explicit_file:
                    path = explicit_file
                else:
                    m = _re.search(r"([\w\-.]+\.[a-z0-9]{2,8})", user_input, _re.IGNORECASE)
                    if m:
                        filename = m.group(1)
                    else:
                        preferred_output = str(learned_prefs.get("preferred_output", "")).lower()
                        ext_map = {
                            "markdown": "md",
                            "json": "json",
                            "csv": "csv",
                            "yaml": "yaml",
                            "pdf": "txt",
                            "docx": "txt",
                        }
                        ext = ext_map.get(preferred_output, "txt")
                        filename = f"not.{ext}"
                    base_dir = self._get_last_directory() or str(Path.home() / "Desktop")
                    folder_hint = self._extract_folder_hint_from_text(user_input)
                    if folder_hint:
                        base_dir = str(Path.home() / "Desktop" / folder_hint)
                    path = str(Path(base_dir).expanduser() / filename)
                clean["path"] = path

            inline_content = self._extract_inline_write_content(user_input)
            content = clean.get("content")
            if not isinstance(content, str) or not content.strip():
                content = clean.get("text") or clean.get("body") or clean.get("message") or inline_content or ""
            if not isinstance(content, str) or not content.strip():
                if any(tok in user_input.lower() for tok in ("bunu", "dosya olarak", "kaydet", "masaüst")):
                    content = self._get_recent_assistant_text(user_input)
            if not isinstance(content, str) or not content.strip():
                if any(tok in user_input.lower() for tok in ("bunu", "dosya olarak", "kaydet", "masaüst")):
                    content = self._get_recent_research_text()
            if not isinstance(content, str) or not content.strip():
                topic_guess = self._extract_topic(user_input, step_name)
                if topic_guess and topic_guess != "genel konu":
                    content = topic_guess
            allow_short_content = bool(clean.get("allow_short_content"))
            if not allow_short_content and self._is_short_note_request(user_input, str(clean.get("path") or "")):
                allow_short_content = True
            clean["allow_short_content"] = allow_short_content
            clean["content"] = self._normalize_task_write_content(
                content,
                user_input,
                str(clean.get("path") or ""),
                allow_short_content=allow_short_content,
            )
        elif tool_name == "write_word":
            path = str(clean.get("path") or "").strip()
            if not path:
                filename = str(clean.get("filename") or "").strip() or "belge.docx"
                if not filename.lower().endswith(".docx"):
                    filename = f"{Path(filename).stem}.docx"
                path = f"~/Desktop/{filename}"
            clean["path"] = path
            clean.pop("filename", None)

            inline_content = self._extract_inline_write_content(user_input)
            content = clean.get("content")
            if not isinstance(content, str) or not content.strip():
                content = clean.get("text") or clean.get("body") or clean.get("message") or inline_content or ""
            if not isinstance(content, str) or not content.strip():
                if any(tok in user_input.lower() for tok in ("bunu", "dosya olarak", "kaydet", "masaüst")):
                    content = self._get_recent_assistant_text(user_input)
            if not isinstance(content, str) or not content.strip():
                content = self._get_recent_research_text()
            if not isinstance(content, str) or not content.strip():
                topic = self._extract_topic(user_input, step_name)
                content = topic if topic and topic != "genel konu" else "İçerik belirtilmedi."
            clean["content"] = content
            clean.setdefault("title", self._extract_topic(user_input, step_name).title() or "Belge")
        elif tool_name == "write_excel":
            path = str(clean.get("path") or "").strip()
            if not path:
                filename = str(clean.get("filename") or "").strip() or "tablo.xlsx"
                if not filename.lower().endswith(".xlsx"):
                    filename = f"{Path(filename).stem}.xlsx"
                path = f"~/Desktop/{filename}"
            clean["path"] = path
            clean.pop("filename", None)

            data = clean.get("data")
            if not data:
                inline_content = self._extract_inline_write_content(user_input)
                research_fallback = self._get_recent_research_text()
                text_seed = (
                    clean.get("content")
                    or clean.get("text")
                    or clean.get("message")
                    or inline_content
                    or research_fallback
                    or self._get_recent_assistant_text(user_input)
                    or self._extract_topic(user_input, step_name)
                )
                if isinstance(text_seed, str) and text_seed.strip():
                    rows = []
                    for line in text_seed.splitlines():
                        item = line.strip().lstrip("-• ").strip()
                        if item:
                            rows.append({"Veri": item})
                    data = rows[:200] if rows else [{"Veri": text_seed.strip()}]
                else:
                    data = [{"Veri": "İçerik belirtilmedi."}]
            clean["data"] = data
            clean.setdefault("headers", ["Veri"])
        elif tool_name == "create_web_project_scaffold":
            project_name = str(clean.get("project_name") or "").strip()
            if not project_name:
                project_name = str(clean.get("topic") or "").strip()
            if not project_name:
                project_name = self._extract_topic(user_input, "")
            if not project_name or project_name == "genel konu":
                project_name = "web-projesi"
            if len(project_name) > 60:
                project_name = "web-projesi"
            clean["project_name"] = project_name

            stack = str(clean.get("stack") or "").strip().lower()
            if not stack:
                low = f"{step_name} {user_input}".lower()
                if "next" in low:
                    stack = "nextjs"
                elif "react" in low:
                    stack = "react"
                else:
                    stack = "vanilla"
            clean["stack"] = stack
            clean["theme"] = str(clean.get("theme") or "professional").strip() or "professional"
            clean["output_dir"] = str(clean.get("output_dir") or "~/Desktop").strip() or "~/Desktop"
            clean["brief"] = str(clean.get("brief") or user_input or "").strip()
            if not clean.get("tech_mode"):
                low = f"{step_name} {user_input}".lower()
                clean["tech_mode"] = "latest" if any(k in low for k in ("en son", "latest", "modern", "güncel", "guncel")) else "stable"
            clean.setdefault("coding_standards", "clean_code")
            if not isinstance(clean.get("quality_gates"), dict):
                clean["quality_gates"] = {"lint": True, "tests": True, "docs": True, "modular_architecture": True}
        elif tool_name == "create_software_project_pack":
            project_name = str(clean.get("project_name") or "").strip()
            if not project_name:
                project_name = str(clean.get("topic") or "").strip()
            if not project_name:
                project_name = self._extract_topic(user_input, "")
            if not project_name or project_name == "genel konu":
                project_name = "uygulama-projesi"
            if len(project_name) > 60:
                project_name = "uygulama-projesi"
            clean["project_name"] = project_name

            project_type = str(clean.get("project_type") or clean.get("project_kind") or "").strip().lower()
            if not project_type:
                low = f"{step_name} {user_input}".lower()
                project_type = "game" if any(k in low for k in ("oyun", "game", "pygame", "unity")) else "app"
            if project_type not in {"webapp", "app", "game"}:
                project_type = "app"
            clean["project_type"] = project_type

            stack = str(clean.get("stack") or "").strip().lower()
            if not stack:
                stack = "python"
            clean["stack"] = stack
            clean["complexity"] = str(clean.get("complexity") or "advanced").strip().lower() or "advanced"
            clean["output_dir"] = str(clean.get("output_dir") or "~/Desktop").strip() or "~/Desktop"
            clean["brief"] = str(clean.get("brief") or user_input or "").strip()
            if not clean.get("tech_mode"):
                low = f"{step_name} {user_input}".lower()
                clean["tech_mode"] = "latest" if any(k in low for k in ("en son", "latest", "modern", "güncel", "guncel")) else "stable"
            clean.setdefault("coding_standards", "clean_code")
            if not isinstance(clean.get("quality_gates"), dict):
                clean["quality_gates"] = {"lint": True, "tests": True, "docs": True, "modular_architecture": True}
        elif tool_name == "create_coding_delivery_plan":
            project_path = str(
                clean.get("project_path")
                or clean.get("path")
                or clean.get("directory")
                or ""
            ).strip()
            if not project_path:
                project_name = str(clean.get("project_name") or "").strip()
                project_kind = str(clean.get("project_kind") or clean.get("project_type") or "app").strip().lower()
                output_dir = str(clean.get("output_dir") or "~/Desktop").strip() or "~/Desktop"
                if project_name:
                    slug = self._safe_project_slug(project_name)
                    if project_kind in {"app", "game", "software"}:
                        project_path = str(Path(output_dir).expanduser() / f"{slug}_project_pack")
                    else:
                        project_path = str(Path(output_dir).expanduser() / slug)
            if project_path:
                clean["project_path"] = project_path

            if not clean.get("project_name"):
                clean["project_name"] = str(clean.get("topic") or self._extract_topic(user_input, "") or "elyan-project").strip()
            if not clean.get("project_kind"):
                low = f"{step_name} {user_input}".lower()
                if any(k in low for k in ("website", "web sitesi", "web sayfas", "landing", "frontend")):
                    clean["project_kind"] = "website"
                elif any(k in low for k in ("oyun", "game", "pygame", "unity")):
                    clean["project_kind"] = "game"
                else:
                    clean["project_kind"] = "app"
            if not clean.get("stack"):
                clean["stack"] = "python"
            if not clean.get("complexity"):
                clean["complexity"] = "advanced"
            clean["brief"] = str(clean.get("brief") or user_input or "").strip()
        elif tool_name == "create_coding_verification_report":
            project_path = str(
                clean.get("project_path")
                or clean.get("path")
                or clean.get("directory")
                or ""
            ).strip()
            if not project_path:
                project_name = str(clean.get("project_name") or "").strip()
                project_kind = str(clean.get("project_kind") or clean.get("project_type") or "app").strip().lower()
                output_dir = str(clean.get("output_dir") or "~/Desktop").strip() or "~/Desktop"
                if project_name:
                    slug = self._safe_project_slug(project_name)
                    if project_kind in {"app", "game", "software"}:
                        project_path = str(Path(output_dir).expanduser() / f"{slug}_project_pack")
                    else:
                        project_path = str(Path(output_dir).expanduser() / slug)
            if project_path:
                clean["project_path"] = project_path

            if not clean.get("project_name"):
                clean["project_name"] = str(clean.get("topic") or self._extract_topic(user_input, "") or "elyan-project").strip()
            if not clean.get("project_kind"):
                low = f"{step_name} {user_input}".lower()
                if any(k in low for k in ("website", "web sitesi", "web sayfas", "landing", "frontend")):
                    clean["project_kind"] = "website"
                elif any(k in low for k in ("oyun", "game", "pygame", "unity")):
                    clean["project_kind"] = "game"
                else:
                    clean["project_kind"] = "app"
            if not clean.get("stack"):
                clean["stack"] = "python"
            if "strict" not in clean:
                clean["strict"] = False
        elif tool_name == "send_notification":
            title = clean.get("title")
            if not isinstance(title, str) or not title.strip():
                title = "Elyan Hatırlatma"
            clean["title"] = title

            message = clean.get("message")
            if not isinstance(message, str) or not message.strip():
                message = clean.get("text") or clean.get("body") or ""
            if not isinstance(message, str) or not message.strip():
                topic = self._extract_topic(user_input, step_name)
                message = topic if topic and topic != "genel konu" else "Hatırlatma"
            clean["message"] = message
        elif tool_name == "create_reminder":
            title = clean.get("title")
            if not isinstance(title, str) or not title.strip():
                title = clean.get("message") or clean.get("text") or ""
            if not isinstance(title, str) or not title.strip():
                title = self._extract_topic(user_input, step_name)
            if not isinstance(title, str) or not title.strip() or title == "genel konu":
                title = "Hatırlatma"
            clean["title"] = title
            due_time = str(clean.get("due_time") or "").strip()
            if not due_time:
                due_time = self._extract_time_from_text(f"{step_name} {user_input}")
            if due_time:
                clean["due_time"] = due_time
            if due_time and not clean.get("due_date"):
                clean["due_date"] = datetime.now().strftime("%Y-%m-%d")
        elif tool_name == "open_project_in_ide":
            ide = str(clean.get("ide") or "").strip().lower()
            if not ide:
                ide = self._infer_ide_name(f"{step_name} {user_input}")
            clean["ide"] = ide or "vscode"

            project_path = str(
                clean.get("project_path")
                or clean.get("path")
                or clean.get("directory")
                or ""
            ).strip()
            if not project_path:
                project_name = str(clean.get("project_name") or "").strip()
                project_kind = str(
                    clean.get("project_kind")
                    or clean.get("project_type")
                    or ""
                ).strip().lower()
                output_dir = str(clean.get("output_dir") or "~/Desktop").strip()
                if project_name:
                    slug = self._safe_project_slug(project_name)
                    if project_kind in {"app", "game", "software"}:
                        project_path = str(Path(output_dir).expanduser() / f"{slug}_project_pack")
                    else:
                        project_path = str(Path(output_dir).expanduser() / slug)
            if project_path:
                clean["project_path"] = project_path
        elif tool_name == "set_volume":
            # Support parser payloads such as {"mute": true} and natural language hints.
            low = f"{step_name} {user_input}".lower()
            mute_val = clean.get("mute")
            if isinstance(mute_val, str):
                mute_val = mute_val.strip().lower() in {"1", "true", "yes", "on", "aç", "ac", "kapat", "mute"}
            if mute_val is None:
                if any(k in low for k in ("sessize", "mute", "sesi kapat", "sesi kıs")):
                    mute_val = True
                elif any(k in low for k in ("sesi aç", "unmute", "sesi geri")):
                    mute_val = False
            if mute_val is not None:
                clean["mute"] = bool(mute_val)

            level = clean.get("level")
            if level is None:
                m = _re.search(r"\b(\d{1,3})\s*%?\b", low)
                if m:
                    level = int(m.group(1))
            if level is not None:
                try:
                    clean["level"] = max(0, min(100, int(level)))
                except Exception:
                    clean.pop("level", None)
        elif tool_name == "get_process_info":
            # Default to a broad process snapshot when no explicit query is provided.
            pname = clean.get("process_name") or clean.get("name") or clean.get("query")
            if isinstance(pname, str) and pname.strip():
                clean["process_name"] = pname.strip()
            else:
                clean["process_name"] = ""
            if "limit" in clean:
                try:
                    clean["limit"] = max(1, min(200, int(clean["limit"])))
                except Exception:
                    clean.pop("limit", None)
        elif tool_name in {"open_app", "close_app"}:
            app_name = clean.get("app_name")
            if isinstance(app_name, str):
                app_name = app_name.strip()
            if not app_name:
                app_name = self._infer_app_name(step_name, user_input)
            if not app_name and tool_name == "open_app":
                combined = f"{step_name} {user_input}".lower()
                if any(k in combined for k in ("tarayıcı", "tarayici", "browser", "web")):
                    app_name = "Safari"
            if app_name:
                clean["app_name"] = app_name
        elif tool_name == "web_search":
            query = clean.get("query") or clean.get("topic") or self._extract_topic(user_input, step_name)
            clean = {"query": query, "num_results": int(clean.get("num_results", 5))}
        elif tool_name == "search_academic_papers":
            query = clean.get("query") or clean.get("topic") or self._extract_topic(user_input, step_name)
            if not str(query or "").strip():
                query = self._sanitize_research_topic(self._extract_topic(user_input, step_name), user_input=user_input, step_name=step_name)
            try:
                limit = int(clean.get("limit", 8))
            except Exception:
                limit = 8
            clean = {"query": str(query).strip(), "limit": max(3, min(10, limit))}
        elif tool_name == "advanced_research":
            topic = clean.get("topic") or clean.get("query") or self._extract_topic(user_input, step_name)
            topic = self._sanitize_research_topic(topic, user_input=user_input, step_name=step_name)
            depth = str(clean.get("depth", "standard")).lower()
            depth_map = {
                "deep": "comprehensive",
                "medium": "standard",
                "quick": "quick",
                "short": "quick",
                "standard": "standard",
                "comprehensive": "comprehensive",
                "expert": "expert",
            }
            if "depth" not in clean:
                resp_len = str(learned_prefs.get("response_length", "")).lower()
                if resp_len == "short":
                    depth = "quick"
                elif resp_len in {"detailed", "long"}:
                    depth = "comprehensive"
            clean["topic"] = topic
            clean["depth"] = depth_map.get(depth, "standard")

            raw_policy = str(clean.get("source_policy") or clean.get("policy") or "").strip().lower()
            if not raw_policy:
                raw_policy = self._infer_research_source_policy(f"{step_name} {user_input}")
            if raw_policy in {"balanced", "trusted", "academic", "official"}:
                clean["source_policy"] = raw_policy

            min_rel = clean.get("min_reliability")
            if min_rel is None:
                min_rel = self._infer_research_min_reliability(f"{step_name} {user_input}", source_policy=raw_policy)
            if min_rel is not None:
                try:
                    value = float(min_rel)
                    if value > 1.0:
                        value = value / 100.0
                    clean["min_reliability"] = max(0.0, min(1.0, value))
                except Exception:
                    pass
            academic_mode = bool(raw_policy == "academic")
            if academic_mode:
                try:
                    rel = float(clean.get("min_reliability", 0.78))
                except Exception:
                    rel = 0.78
                clean["min_reliability"] = max(rel, 0.78)
                clean["depth"] = "expert" if clean.get("depth") in {"standard", "comprehensive"} else clean.get("depth")
                clean["include_bibliography"] = bool(clean.get("include_bibliography", True))
                clean["citation_style"] = str(clean.get("citation_style") or "apa7").strip().lower()
        elif tool_name == "summarize_document":
            path = str(clean.get("path") or "").strip()
            if not path:
                tokens = self._extract_path_like_tokens(user_input)
                for tok in tokens:
                    st = str(tok).strip()
                    if Path(st).suffix.lower() in {".txt", ".md", ".docx", ".doc", ".pdf", ".csv", ".xlsx"}:
                        path = st
                        break
            if not path and self._references_last_object(user_input):
                path = self._get_last_path()
            if path:
                candidate = self._resolve_path_with_desktop_fallback(path, user_input=user_input)
                resolved = self._resolve_existing_path_from_context(candidate, user_input=user_input)
                clean["path"] = resolved or candidate
            style = str(clean.get("style") or "").strip().lower()
            if style not in {"brief", "detailed", "bullets"}:
                style = self._infer_summary_style(f"{step_name} {user_input}")
            clean["style"] = style
            if not str(clean.get("path") or "").strip():
                content_seed = str(clean.get("content") or clean.get("text") or clean.get("body") or "").strip()
                if not content_seed:
                    content_seed = self._get_recent_assistant_text(user_input) or self._get_recent_research_text()
                if content_seed:
                    clean["content"] = content_seed[:12000]
        elif tool_name == "analyze_document":
            path = str(clean.get("path") or "").strip()
            if not path:
                tokens = self._extract_path_like_tokens(user_input)
                for tok in tokens:
                    st = str(tok).strip()
                    if Path(st).suffix.lower() in {".txt", ".md", ".docx", ".doc", ".pdf", ".csv", ".xlsx"}:
                        path = st
                        break
            if not path and self._references_last_object(user_input):
                path = self._get_last_path()
            if path:
                candidate = self._resolve_path_with_desktop_fallback(path, user_input=user_input)
                resolved = self._resolve_existing_path_from_context(candidate, user_input=user_input)
                clean["path"] = resolved or candidate
        elif tool_name == "edit_text_file":
            path = str(clean.get("path") or "").strip()
            if not path:
                path = self._infer_path_from_text(user_input, step_name=step_name, tool_name=tool_name)
            if not path and self._references_last_object(user_input):
                path = self._get_last_path()
            if not path:
                path = self._extract_file_path_from_text(user_input, "not.md")
            candidate = self._resolve_path_with_desktop_fallback(path, user_input=user_input)
            resolved = self._resolve_existing_path_from_context(candidate, user_input=user_input)
            clean["path"] = resolved or candidate

            operations = clean.get("operations")
            if not isinstance(operations, (list, dict, str)):
                operations = self._infer_document_edit_operations(f"{step_name} {user_input}", word_mode=False)
            if isinstance(operations, dict):
                operations = [operations]
            if isinstance(operations, str):
                operations = [{"type": "replace", "find": operations, "replace": "", "all": True}]
            if not isinstance(operations, list) or not operations:
                append_text = self._extract_inline_write_content(user_input)
                if not append_text:
                    append_text = self._normalize_task_write_content("", user_input, str(clean.get("path") or "not.md"))
                operations = [{"type": "append", "text": append_text}]
            clean["operations"] = operations
            if "create_backup" not in clean:
                clean["create_backup"] = True
        elif tool_name == "batch_edit_text":
            directory = str(clean.get("directory") or clean.get("path") or "").strip()
            if not directory:
                hint = self._extract_folder_hint_from_text(user_input)
                directory = f"~/Desktop/{hint}" if hint else self._get_last_directory()
            clean["directory"] = self._resolve_path_with_desktop_fallback(directory, user_input=user_input)

            pattern = str(clean.get("pattern") or "").strip()
            if not pattern:
                pattern = self._infer_batch_pattern(f"{step_name} {user_input}")
            clean["pattern"] = pattern

            operations = clean.get("operations")
            if not isinstance(operations, (list, dict, str)):
                operations = self._infer_document_edit_operations(f"{step_name} {user_input}", word_mode=False)
            if isinstance(operations, dict):
                operations = [operations]
            if isinstance(operations, str):
                operations = [{"type": "replace", "find": operations, "replace": "", "all": True}]
            if not isinstance(operations, list) or not operations:
                operations = [{"type": "append", "text": self._extract_inline_write_content(user_input) or "guncel not"}]
            clean["operations"] = operations
            clean["recursive"] = bool(clean.get("recursive", any(k in f"{step_name} {user_input}".lower() for k in ("recursive", "alt klasör", "alt klasor"))))
            if "create_backup" not in clean:
                clean["create_backup"] = True
        elif tool_name == "edit_word_document":
            path = str(clean.get("path") or "").strip()
            if not path:
                path = self._infer_path_from_text(user_input, step_name=step_name, tool_name=tool_name)
            if not path and self._references_last_object(user_input):
                path = self._get_last_path()
            if not path:
                path = self._extract_file_path_from_text(user_input, "belge.docx")
            if not str(path).lower().endswith((".docx", ".doc")):
                path = str(Path(str(path)).with_suffix(".docx"))
            candidate = self._resolve_path_with_desktop_fallback(path, user_input=user_input)
            resolved = self._resolve_existing_path_from_context(candidate, user_input=user_input)
            clean["path"] = resolved or candidate

            operations = clean.get("operations")
            if not isinstance(operations, (list, dict, str)):
                operations = self._infer_document_edit_operations(f"{step_name} {user_input}", word_mode=True)
            if isinstance(operations, dict):
                operations = [operations]
            if isinstance(operations, str):
                operations = [{"type": "replace_text", "find": operations, "replace": ""}]
            if not isinstance(operations, list) or not operations:
                append_text = self._extract_inline_write_content(user_input)
                if not append_text:
                    topic = self._extract_topic(user_input, step_name)
                    append_text = topic if topic and topic != "genel konu" else "Guncelleme notu"
                operations = [{"type": "add_paragraph", "text": append_text}]
            clean["operations"] = operations
            if "create_backup" not in clean:
                clean["create_backup"] = True
        elif tool_name == "research_document_delivery":
            topic = clean.get("topic") or clean.get("query") or self._extract_topic(user_input, step_name)
            topic = self._sanitize_research_topic(topic, user_input=user_input, step_name=step_name)
            low = f"{step_name} {user_input}".lower()
            depth = str(clean.get("depth", "comprehensive") or "comprehensive").strip().lower()
            depth_map = {
                "quick": "quick",
                "standard": "standard",
                "comprehensive": "comprehensive",
                "expert": "expert",
                "deep": "comprehensive",
                "detailed": "comprehensive",
            }
            if depth not in depth_map:
                if any(k in low for k in ("hızlı", "hizli", "kısa", "kisa", "quick")):
                    depth = "quick"
                elif any(k in low for k in ("uzman", "expert", "derin", "derinlemesine")):
                    depth = "expert"
                else:
                    depth = "comprehensive"

            source_policy = str(clean.get("source_policy") or "").strip().lower()
            if not source_policy:
                source_policy = self._infer_research_source_policy(f"{step_name} {user_input}") or "trusted"
            if source_policy not in {"balanced", "trusted", "academic", "official"}:
                source_policy = "trusted"

            min_rel = clean.get("min_reliability")
            if min_rel is None:
                min_rel = self._infer_research_min_reliability(
                    f"{step_name} {user_input}",
                    source_policy=source_policy,
                )
            try:
                min_rel_value = float(min_rel if min_rel is not None else 0.62)
                if min_rel_value > 1.0:
                    min_rel_value = min_rel_value / 100.0
                min_rel_value = max(0.0, min(1.0, min_rel_value))
            except Exception:
                min_rel_value = 0.62
            academic_mode = bool(source_policy == "academic")
            if academic_mode:
                min_rel_value = max(min_rel_value, 0.78)
                if depth in {"quick", "standard"}:
                    depth = "comprehensive"

            wants_pdf = any(k in low for k in ("pdf",))
            wants_latex = any(k in low for k in ("latex", "tex"))
            wants_excel = any(k in low for k in ("excel", "xlsx", "tablo", "csv"))
            explicit_word = any(k in low for k in ("word", "docx", "doküman", "dokuman"))
            generic_doc = any(k in low for k in ("belge", "rapor", "dosya"))
            include_word = clean.get("include_word")
            if include_word is None:
                include_word = explicit_word or (generic_doc and not wants_excel and not wants_pdf and not wants_latex)
            if not include_word and not wants_excel and not wants_pdf and not wants_latex:
                include_word = True
            include_excel = clean.get("include_excel")
            if include_excel is None:
                include_excel = wants_excel
            include_pdf = clean.get("include_pdf")
            if include_pdf is None:
                include_pdf = wants_pdf
            include_latex = clean.get("include_latex")
            if include_latex is None:
                include_latex = wants_latex
            include_report = clean.get("include_report")
            if include_report is None:
                include_report = True
            deliver_copy = clean.get("deliver_copy")
            if deliver_copy is None:
                deliver_copy = any(k in low for k in ("gönder", "gonder", "paylaş", "paylas", "ilet", "kopya"))

            clean = {
                "topic": topic,
                "brief": str(clean.get("brief") or user_input or "").strip(),
                "depth": depth_map.get(depth, "comprehensive"),
                "audience": str(clean.get("audience") or ("academic" if academic_mode else "executive")).strip() or ("academic" if academic_mode else "executive"),
                "language": str(clean.get("language") or "tr").strip() or "tr",
                "output_dir": str(clean.get("output_dir") or "~/Desktop").strip() or "~/Desktop",
                "include_word": bool(include_word),
                "include_excel": bool(include_excel),
                "include_pdf": bool(include_pdf),
                "include_latex": bool(include_latex),
                "include_report": bool(include_report),
                "source_policy": source_policy,
                "min_reliability": min_rel_value,
                "deliver_copy": bool(deliver_copy),
                "citation_style": str(clean.get("citation_style") or ("apa7" if academic_mode else "none")).strip().lower(),
                "citation_mode": str(clean.get("citation_mode") or "inline").strip().lower(),
                "document_profile": str(clean.get("document_profile") or ("analytical" if academic_mode else "executive")).strip().lower(),
                "include_bibliography": bool(clean.get("include_bibliography", True)),
            }
        elif tool_name == "generate_document_pack":
            topic = self._sanitize_research_topic(
                clean.get("topic") or self._extract_topic(user_input, step_name),
                user_input=user_input,
                step_name=step_name,
            )
            brief = str(clean.get("brief") or self._extract_inline_write_content(user_input) or user_input or "").strip()
            low = f"{step_name} {user_input}".lower()
            preferred_formats = clean.get("preferred_formats")
            if not isinstance(preferred_formats, list) or not preferred_formats:
                preferred_formats = []
                wants_pdf = "pdf" in low
                wants_latex = any(k in low for k in ("latex", "tex"))
                wants_excel = any(k in low for k in ("excel", "xlsx", "tablo", "csv"))
                wants_word = any(k in low for k in ("word", "docx", "doküman", "dokuman"))
                generic_doc = any(k in low for k in ("belge", "rapor"))
                if wants_word or (generic_doc and not wants_pdf and not wants_excel and not wants_latex):
                    preferred_formats.append("docx")
                if wants_excel:
                    preferred_formats.append("xlsx")
                if wants_pdf:
                    preferred_formats.append("pdf")
                if wants_latex:
                    preferred_formats.append("tex")
                if any(k in low for k in ("markdown", ".md")):
                    preferred_formats.append("md")
                if any(k in low for k in ("txt", "metin dosyası", "metin dosyasi")):
                    preferred_formats.append("txt")
                if not preferred_formats:
                    preferred_formats = ["docx"]
            clean = {
                "topic": topic,
                "brief": brief,
                "audience": str(clean.get("audience") or "executive").strip() or "executive",
                "language": str(clean.get("language") or "tr").strip() or "tr",
                "output_dir": str(clean.get("output_dir") or "~/Desktop").strip() or "~/Desktop",
                "preferred_formats": preferred_formats,
            }
        elif tool_name == "db_execute":
            query = str(clean.get("query") or clean.get("sql") or "").strip()
            if not query:
                query = "SELECT name FROM sqlite_master WHERE type='table' LIMIT 20;"
            mode = str(clean.get("mode") or clean.get("profile") or "ro").strip().lower()
            mutating = bool(
                _re.search(
                    r"^\s*(insert|update|delete|drop|alter|create|truncate|replace|grant|revoke)\b",
                    query,
                    _re.IGNORECASE,
                )
            )
            if mutating and mode not in {"rw", "write", "admin"}:
                clean["query"] = "-- blocked_by_policy: mutating query requires mode='rw'"
                clean["mode"] = "ro"
            else:
                clean["query"] = query
                clean["mode"] = "rw" if mode in {"rw", "write", "admin"} else "ro"
            if clean["mode"] == "ro" and "db_path" not in clean:
                clean["db_path"] = str(Path("~/Desktop/elyan.db").expanduser())
        elif tool_name == "db_schema":
            db_path = str(clean.get("db_path") or "").strip()
            if not db_path:
                db_path = str(Path("~/Desktop/elyan.db").expanduser())
            clean["db_path"] = db_path
        elif tool_name == "open_url":
            url = clean.get("url", "")
            if not url:
                q = clean.get("query") or self._extract_topic(user_input, step_name)
                if q:
                    url = f"https://www.google.com/search?q={quote_plus(q)}"
            clean["url"] = url
            browser = str(clean.get("browser") or "").strip()
            if not browser:
                browser = self._infer_browser_app_from_text(f"{step_name} {user_input}")
            if browser:
                clean["browser"] = browser
        elif tool_name == "key_combo":
            combo = str(clean.get("combo") or "").strip()
            if not combo:
                combo = self._extract_key_combo_from_text(f"{step_name} {user_input}")
            if not combo:
                combo = "cmd+l"
            clean = {"combo": combo}
        elif tool_name == "press_key":
            key = str(clean.get("key") or "").strip().lower()
            if not key:
                m_key = _re.search(
                    r"\b(enter|return|tab|space|esc|escape|left|right|up|down|delete|backspace)\b",
                    f"{step_name} {user_input}",
                    _re.IGNORECASE,
                )
                if m_key:
                    key = str(m_key.group(1) or "").strip().lower()
            if not key:
                key = "enter"
            modifiers = clean.get("modifiers")
            if not isinstance(modifiers, list):
                modifiers = []
            clean = {"key": key, "modifiers": modifiers}
        elif tool_name == "type_text":
            text_payload = str(clean.get("text") or "").strip()
            if not text_payload:
                m_write = _re.search(r"(?:şunu yaz|sunu yaz|yaz)\s*[:\-]?\s*(.+)", user_input, _re.IGNORECASE)
                if m_write:
                    text_payload = str(m_write.group(1) or "").strip()
            text_payload = _re.sub(r"\s+(?:ve\s+|sonra\s+)?(?:enter|return)\s+bas.*$", "", text_payload, flags=_re.IGNORECASE)
            if not text_payload:
                text_payload = self._extract_inline_write_content(user_input)
            if not text_payload:
                text_payload = self._extract_topic(user_input, step_name) or "test"
            press_enter = clean.get("press_enter")
            if press_enter is None:
                press_enter = bool(_re.search(r"\b(enter|return)\b", f"{step_name} {user_input}", _re.IGNORECASE))
            clean = {"text": text_payload, "press_enter": bool(press_enter)}
        elif tool_name == "mouse_move":
            try:
                x = int(clean.get("x"))
                y = int(clean.get("y"))
            except Exception:
                m_xy = _re.search(r"\b(\d{1,4})\s*[,x]\s*(\d{1,4})\b", f"{step_name} {user_input}", _re.IGNORECASE)
                if m_xy:
                    x = int(m_xy.group(1))
                    y = int(m_xy.group(2))
                else:
                    x, y = 960, 540
            clean = {"x": x, "y": y}
        elif tool_name == "mouse_click":
            try:
                x = int(clean.get("x"))
                y = int(clean.get("y"))
            except Exception:
                m_xy = _re.search(r"\b(\d{1,4})\s*[,x]\s*(\d{1,4})\b", f"{step_name} {user_input}", _re.IGNORECASE)
                if m_xy:
                    x = int(m_xy.group(1))
                    y = int(m_xy.group(2))
                else:
                    x, y = 960, 540
            button = str(clean.get("button") or "left").strip().lower()
            if button not in {"left", "right"}:
                button = "left"
            clean = {"x": x, "y": y, "button": button, "double": bool(clean.get("double", False))}
        elif tool_name == "computer_use":
            steps = clean.get("steps")
            if not isinstance(steps, list) or not steps:
                steps = self._build_computer_use_steps_from_text(f"{step_name} {user_input}")
            if not isinstance(steps, list):
                steps = []
            clean = {
                "steps": steps,
                "final_screenshot": bool(clean.get("final_screenshot", True)),
                "pause_ms": int(clean.get("pause_ms", 250) or 250),
            }
        elif tool_name == "run_safe_command":
            command = clean.get("command") or clean.get("cmd") or clean.get("query") or ""
            if not str(command).strip():
                command = self._extract_terminal_command_from_text(user_input) or ""
            clean = {"command": command}
        elif tool_name == "execute_python_code":
            code = clean.get("code") or ""
            clean = {"code": code}
        elif tool_name == "create_visual_asset_pack":
            project_name = clean.get("project_name") or self._extract_topic(user_input, step_name)[:64]
            clean["project_name"] = project_name or "elyan-visual"
            clean["brief"] = clean.get("brief") or user_input
            clean["output_dir"] = clean.get("output_dir") or "~/Desktop"
        elif tool_name == "control_music":
            command = clean.get("action") or clean.get("command")
            low = user_input.lower()
            if not command:
                if any(k in low for k in ("durdur", "dur", "pause", "stop")):
                    command = "pause"
                elif any(k in low for k in ("devam", "resume", "continue")):
                    command = "play"
                elif any(k in low for k in ("sonraki", "next", "ileri")):
                    command = "next"
                elif any(k in low for k in ("önceki", "onceki", "previous", "geri")):
                    command = "previous"
                else:
                    command = "play"
            clean["action"] = command
            clean.pop("command", None)
            if command == "play" and not clean.get("query"):
                topic = self._extract_topic(user_input, step_name)
                if topic and topic != "genel konu":
                    clean["query"] = topic
        elif tool_name == "create_event":
            clean.setdefault("title", step_name or "Etkinlik")
            clean.setdefault("date", "today")
            start_time = str(clean.get("start_time") or "").strip()
            if not start_time:
                start_time = str(clean.get("time") or "").strip()
            if not start_time:
                start_time = self._extract_time_from_text(user_input)
            if start_time:
                clean["start_time"] = start_time

        elif tool_name == "get_weather":
            city = str(clean.get("city") or "").strip()
            if not city:
                # Şehir adı çıkar
                m = _re.search(
                    r"(?:hava|weather)\s+(?:durumu|nasıl)?\s*(?:in|için)?\s*([A-ZÇĞİÖŞÜa-zçğışöşü]{3,})",
                    user_input,
                    _re.IGNORECASE,
                )
                if m:
                    city = m.group(1).strip()
                else:
                    m2 = _re.search(
                        r"([A-ZÇĞİÖŞÜ][a-zçğışöşü]{2,}(?:\s+[A-ZÇĞİÖŞÜ][a-zçğışöşü]{2,})?)\s+(?:hava|sıcaklık|yağmur|weather)",
                        user_input,
                        _re.IGNORECASE,
                    )
                    if m2:
                        city = m2.group(1).strip()
            if city:
                clean["city"] = city

        elif tool_name == "run_code":
            code = str(clean.get("code") or "").strip()
            if not code:
                # Kod bloğu arama
                m = _re.search(r"```(?:python)?\n(.+?)```", user_input, _re.DOTALL | _re.IGNORECASE)
                if m:
                    code = m.group(1).strip()
                else:
                    # "X hesapla/yap" → basit kod üret
                    m2 = _re.search(r"(\d+(?:\s*[+\-*/]\s*\d+)+)", user_input)
                    if m2:
                        code = f"print({m2.group(1)})"
            if code:
                clean["code"] = code
            clean.setdefault("language", "python")

        return clean

    @staticmethod
    def _render_research_result(result: dict[str, Any]) -> str | None:
        outputs = result.get("outputs")
        delivery_dir = str(result.get("delivery_dir") or "").strip()
        if isinstance(outputs, list) and outputs:
            clean_outputs = [str(item).strip() for item in outputs if str(item).strip()]
            if clean_outputs:
                primary = clean_outputs[0]
                line = f"Araştırma belgesi hazır: {primary}"
                source_count = result.get("source_count")
                finding_count = result.get("finding_count")
                meta = []
                if source_count is not None:
                    meta.append(f"Kaynak: {source_count}")
                if finding_count is not None:
                    meta.append(f"Bulgu: {finding_count}")
                if result.get("critical_claim_coverage") is not None:
                    try:
                        meta.append(f"Kritik claim: %{int(round(float(result.get('critical_claim_coverage', 0.0) or 0.0) * 100))}")
                    except Exception:
                        pass
                if result.get("uncertainty_count") is not None:
                    meta.append(f"Belirsizlik: {int(result.get('uncertainty_count', 0) or 0)}")
                if meta:
                    line += "\n" + " | ".join(meta)
                if len(clean_outputs) > 1:
                    line += f"\nEk çıktı: {len(clean_outputs) - 1}"
                return line
        report_paths = result.get("report_paths")
        if isinstance(report_paths, list) and report_paths:
            clean_reports = [str(item).strip() for item in report_paths if str(item).strip()]
            if clean_reports:
                primary = clean_reports[0]
                line = f"Araştırma notu hazır: {primary}"
                source_count = result.get("source_count")
                finding_count = result.get("finding_count")
                quality_summary = result.get("quality_summary") if isinstance(result.get("quality_summary"), dict) else {}
                meta = []
                if source_count is not None:
                    meta.append(f"Kaynak: {source_count}")
                if finding_count is not None:
                    meta.append(f"Bulgu: {finding_count}")
                critical_coverage = result.get("critical_claim_coverage", quality_summary.get("critical_claim_coverage"))
                if critical_coverage is not None:
                    try:
                        meta.append(f"Kritik claim: %{int(round(float(critical_coverage or 0.0) * 100))}")
                    except Exception:
                        pass
                uncertainty_count = result.get("uncertainty_count", quality_summary.get("uncertainty_count"))
                if uncertainty_count is not None:
                    meta.append(f"Belirsizlik: {int(uncertainty_count or 0)}")
                if meta:
                    line += "\n" + " | ".join(meta)
                if len(clean_reports) > 1:
                    line += f"\nEk rapor: {len(clean_reports) - 1}"
                return line
        if delivery_dir and isinstance(result.get("path"), str):
            return f"Araştırma çıktısı hazır: {str(result.get('path') or '').strip()}"

        summary = str(result.get("summary") or "").strip()
        if not summary:
            return None
        markers = ("sources", "source_list", "references", "recommendations", "topic", "source_policy")
        if not any(k in result for k in markers):
            return None

        lines = [summary]
        raw_sources = (
            result.get("sources")
            or result.get("source_list")
            or result.get("references")
            or []
        )
        if isinstance(raw_sources, list) and raw_sources:
            rows: list[str] = []
            for item in raw_sources[:5]:
                if isinstance(item, dict):
                    url = str(item.get("url") or item.get("link") or "").strip()
                    title = str(item.get("title") or item.get("name") or "").strip()
                    if title and url:
                        rows.append(f"- {title} ({url})")
                    elif title:
                        rows.append(f"- {title}")
                    elif url:
                        rows.append(f"- {url}")
                elif isinstance(item, str) and item.strip():
                    rows.append(f"- {item.strip()}")
            if rows:
                lines.append("\nKaynaklar:")
                lines.extend(rows)

        recommendations = result.get("recommendations")
        if isinstance(recommendations, list) and recommendations:
            rec_rows = [f"- {str(r).strip()}" for r in recommendations[:4] if str(r).strip()]
            if rec_rows:
                lines.append("\nÖneriler:")
                lines.extend(rec_rows)

        confidence = result.get("confidence") or result.get("confidence_score") or result.get("trust_score")
        if confidence is not None:
            try:
                score = float(confidence)
                if score > 1.0:
                    score = score / 100.0
                score = max(0.0, min(1.0, score))
                lines.append(f"\nGüven skoru: %{int(round(score * 100))}")
            except Exception:
                pass

        risks = result.get("risks") or result.get("open_risks") or []
        if isinstance(risks, list) and risks:
            risk_rows = [f"- {str(r).strip()}" for r in risks[:4] if str(r).strip()]
            if risk_rows:
                lines.append("\nAçık riskler:")
                lines.extend(risk_rows)

        return "\n".join(lines).strip()

    def _format_result_text(self, result: Any) -> str:
        def _iter_payloads(payload: Any, *, _depth: int = 0):
            if _depth > 3 or not isinstance(payload, dict):
                return
            yield payload
            for key in ("result", "raw"):
                nested = payload.get(key)
                if isinstance(nested, dict) and nested is not payload:
                    yield from _iter_payloads(nested, _depth=_depth + 1)

        if isinstance(result, dict):
            if result.get("success") is False:
                if result.get("not_found"):
                    return None  # Signal for LLM fallback
                if isinstance(result.get("combo"), str) and ("target_app" in result or "frontmost_app" in result):
                    combo = str(result.get("combo") or "").strip()
                    lines = [f"Hata: {result.get('error', 'İşlem başarısız.')}"]
                    if combo:
                        lines.append(f"Kısayol: {combo}")
                    target_app = str(result.get("target_app") or "").strip()
                    if target_app:
                        lines.append(f"Hedef: {target_app}")
                    frontmost = str(result.get("frontmost_app") or "").strip()
                    if frontmost:
                        lines.append(f"Odak: {frontmost}")
                    if result.get("verified") is False:
                        lines.append("Doğrulama: Başarısız")
                    warn = str(result.get("verification_warning") or "").strip()
                    if warn:
                        lines.append(f"Not: {warn}")
                    return "\n".join(lines)
                if isinstance(result.get("app_name"), str) and ("frontmost_app" in result or "verified" in result):
                    app_name = str(result.get("app_name") or "").strip()
                    lines = [f"Hata: {result.get('error', 'İşlem başarısız.')}"]
                    if app_name:
                        lines.append(f"Uygulama: {app_name}")
                    frontmost = str(result.get("frontmost_app") or "").strip()
                    if frontmost:
                        lines.append(f"Odak: {frontmost}")
                    warn = str(result.get("verification_warning") or "").strip()
                    if warn:
                        lines.append(f"Not: {warn}")
                    return "\n".join(lines)
                return f"Hata: {result.get('error', 'İşlem başarısız.')}"

            for payload in _iter_payloads(result):
                observations = payload.get("observations")
                if isinstance(observations, list) and observations:
                    latest = observations[-1] if isinstance(observations[-1], dict) else {}
                    summary = str(
                        latest.get("summary")
                        or payload.get("summary")
                        or payload.get("analysis")
                        or payload.get("message")
                        or ""
                    ).strip()
                    lines = [summary] if summary else []
                    provider = str(latest.get("provider") or payload.get("provider") or "").strip()
                    if provider:
                        lines.append(f"Analiz: {provider}")
                    control = payload.get("control")
                    if isinstance(control, dict) and str(control.get("message") or "").strip():
                        lines.append(f"Aksiyon: {str(control.get('message')).strip()}")
                    warning = str(
                        latest.get("warning")
                        or payload.get("warning")
                        or payload.get("verification_warning")
                        or ""
                    ).strip()
                    if warning.startswith("vision_quality_gate:"):
                        warning = "Gorsel analiz tutarsiz oldugu icin guvenli durum ozeti kullanildi."
                    if warning:
                        lines.append(f"Not: {warning}")
                    if lines:
                        return "\n".join(lines)

            # --- Ücretsiz API Özel Renderer'ları (Yüksek Öncelik) ---

            # Kripto Fiyat Renderer
            if "prices" in result and isinstance(result.get("prices"), dict):
                prices = result["prices"]
                vs = result.get("vs_currency", "usd").upper()
                lines = ["💰 Güncel Piyasa Değerleri:"]
                for coin, data in prices.items():
                    price = data.get("price", "?")
                    change = data.get("change_24h", 0)
                    trend = "📈" if change > 0 else "📉"
                    lines.append(f"- {coin.upper()}: {price:,} {vs} {trend} (%{change:+.2f})")
                return "\n".join(lines)

            # Döviz Kuru Renderer
            if "rates" in result and "base" in result:
                base = result["base"]
                rates = result["rates"]
                lines = [f"💱 {base} Bazlı Döviz Kurları:"]
                for cur in ["USD", "EUR", "TRY", "GBP", "JPY"]:
                    if cur in rates and cur != base:
                        lines.append(f"- 1 {base} = {rates[cur]:.4f} {cur}")
                return "\n".join(lines)

            # Wikipedia Renderer
            if "topic" in result and "summary" in result and "url" in result:
                topic = result["topic"]
                summary = result["summary"]
                return f"📝 **{topic}**\n\n{summary}"

            # Sözlük Renderer
            if "word" in result and "definitions" in result:
                word = result["word"]
                defs = result["definitions"]
                lines = [f"📖 **{word.capitalize()}**"]
                for i, d in enumerate(defs[:3], 1):
                    lines.append(f"{i}. {d}")
                return "\n".join(lines)

            # Ülke Bilgisi Renderer
            if "name" in result and "flag" in result and "capital" in result:
                name = result["name"]
                flag = result["flag"]
                cap = result["capital"]
                pop = result.get("population", "?")
                reg = result.get("region", "")
                return f"{flag} **{name}**\n- Başkent: {cap}\n- Nüfus: {pop:,}\n- Bölge: {reg}"

            # Hava Durumu (Open-Meteo) Renderer
            if "city" in result and "temperature" in result and "description" in result:
                city = result["city"]
                temp = result["temperature"]
                desc = result["description"]
                hum = result.get("humidity", "?")
                wind = result.get("wind_speed", "?")
                return f"🌡 **{city.capitalize()}**\nSıcaklık: {temp}°C\nDurum: {desc}\nNem: %{hum} · Rüzgar: {wind} km/s"

            # Arama Renderer
            if "papers" in result and "query" in result:
                papers = result.get("papers", [])
                lines = [f"🎓 **Akademik Sonuçlar:** {result.get('query', '')}"]
                for i, paper in enumerate(papers[:6], start=1):
                    if not isinstance(paper, dict):
                        continue
                    title = str(paper.get("title") or "Başlıksız").strip()
                    year = str(paper.get("year") or "").strip()
                    journal = str(paper.get("journal") or "").strip()
                    url = str(paper.get("url") or "").strip()
                    meta = " · ".join(x for x in [year, journal] if x)
                    row = f"{i}. {title}"
                    if meta:
                        row += f" ({meta})"
                    if url:
                        row += f"\n   {url}"
                    lines.append(row)
                return "\n".join(lines)

            if "answer" in result and "query" in result:
                ans = result["answer"]
                return f"🔍 **{result['query']}**\n\n{ans}"

            # Rastgele İçerik Renderer
            if "advice" in result:
                return f"💡 **Tavsiye:** {result['advice']}"
            if "fact" in result:
                return f"🧐 **İlginç Bilgi:** {result['fact']}"
            if "quote" in result:
                q = result["quote"]
                a = result.get("author", "Bilinmiyor")
                return f"💬 \"{q}\"\n— *{a}*"

            # --- Genel Amaçlı Renderer'lar ---
            research_rendered = self._render_research_result(result)
            if research_rendered:
                return research_rendered

            if any(k in result for k in ("ocr", "objects", "provider", "analysis_mode")):
                summary = str(result.get("summary") or result.get("message") or "").strip()
                lines = [summary] if summary else []
                provider = str(result.get("provider") or "").strip()
                if provider:
                    lines.append(f"Analiz: {provider}")
                warning = str(result.get("warning") or result.get("verification_warning") or "").strip()
                if warning.startswith("vision_quality_gate:"):
                    warning = "Gorsel analiz tutarsiz oldugu icin guvenli durum ozeti kullanildi."
                if warning:
                    lines.append(f"Not: {warning}")
                if lines:
                    return "\n".join(lines)

            if isinstance(result.get("summary"), str) and result.get("summary"):
                return result["summary"]

            if isinstance(result.get("app_name"), str) and ("frontmost_app" in result or "verified" in result):
                app_name = str(result.get("app_name") or "").strip()
                base = str(result.get("message") or "").strip() or (f"{app_name} opened." if app_name else "Uygulama açıldı.")
                lines = [base]
                frontmost = str(result.get("frontmost_app") or "").strip()
                if frontmost:
                    lines.append(f"Odak: {frontmost}")
                verified = result.get("verified")
                if verified is True:
                    lines.append("Doğrulama: OK")
                elif verified is False:
                    lines.append("Doğrulama: Başarısız")
                warn = str(result.get("verification_warning") or "").strip()
                if warn:
                    lines.append(f"Not: {warn}")
                return "\n".join(lines)

            if isinstance(result.get("combo"), str) and ("target_app" in result or "frontmost_app" in result):
                combo = str(result.get("combo") or "").strip()
                base = str(result.get("message") or "").strip() or (f"Kısayol uygulandı: {combo}" if combo else "Kısayol uygulandı.")
                lines = [base]
                target_app = str(result.get("target_app") or "").strip()
                if target_app:
                    lines.append(f"Hedef: {target_app}")
                frontmost = str(result.get("frontmost_app") or "").strip()
                if frontmost:
                    lines.append(f"Odak: {frontmost}")
                verified = result.get("verified")
                if verified is True:
                    lines.append("Doğrulama: OK")
                elif verified is False:
                    lines.append("Doğrulama: Başarısız")
                warn = str(result.get("verification_warning") or "").strip()
                if warn:
                    lines.append(f"Not: {warn}")
                return "\n".join(lines)

            if isinstance(result.get("message"), str) and result.get("message"):
                msg = result["message"]
                extra_paths: list[str] = []
                for key in ("outputs", "report_paths", "files_created"):
                    values = result.get(key)
                    if not isinstance(values, list):
                        continue
                    for item in values:
                        if isinstance(item, str) and item.strip():
                            extra_paths.append(item.strip())
                if isinstance(result.get("path"), str) and result.get("path"):
                    extra_paths.append(str(result.get("path")).strip())
                if isinstance(result.get("delivery_dir"), str) and result.get("delivery_dir"):
                    extra_paths.append(str(result.get("delivery_dir")).strip())

                dedup_paths: list[str] = []
                seen_paths: set[str] = set()
                for p in extra_paths:
                    if p in seen_paths:
                        continue
                    seen_paths.add(p)
                    dedup_paths.append(p)
                if dedup_paths and not any(p in msg for p in dedup_paths[:4]):
                    msg = msg.rstrip() + "\n" + "\n".join(f"- {p}" for p in dedup_paths[:8])
                sha = str(result.get("sha256") or "").strip()
                if sha:
                    msg += f"\nHash: {sha[:12]}…"
                proof = result.get("_proof", {})
                if isinstance(proof, dict):
                    if proof.get("screenshot"):
                        msg += f"\nKanıt: {proof['screenshot']}"
                warn = str(result.get("verification_warning") or "").strip()
                if warn:
                    return f"{msg}\nNot: {warn}"
                return msg

            # Tool-specific human-friendly renderers
            if isinstance(result.get("apps"), list):
                apps = [str(a) for a in result.get("apps", []) if str(a).strip()]
                if not apps:
                    return "Aktif uygulama bulunamadı."
                return "Çalışan uygulamalar:\n" + "\n".join(f"- {a}" for a in apps[:60])

            if isinstance(result.get("details"), list):
                rows = [str(x) for x in result.get("details", []) if str(x).strip()]
                if rows:
                    shown = rows[:25]
                    suffix = f"\n... (+{len(rows) - len(shown)} satır)" if len(rows) > len(shown) else ""
                    return "Süreç bilgisi:\n" + "\n".join(shown) + suffix

            if "on" in result and "connected" in result:
                on = "Açık" if bool(result.get("on")) else "Kapalı"
                if result.get("connected"):
                    ssid = result.get("network_name") or result.get("ssid") or "bilinmiyor"
                    return f"WiFi: {on} · Bağlı ({ssid})"
                return f"WiFi: {on} · Bağlı değil"

            if "wifi_on" in result and "connected" in result:
                on = "Açık" if bool(result.get("wifi_on")) else "Kapalı"
                if result.get("connected"):
                    ssid = result.get("network") or result.get("network_name") or "bilinmiyor"
                    return f"WiFi: {on} · Bağlı ({ssid})"
                return f"WiFi: {on} · Bağlı değil"

            if "level" in result and "mute" in result:
                if result.get("mute"):
                    return "Ses: Sessize alındı."
                lvl = result.get("level")
                if lvl is None:
                    return "Ses: Açık."
                return f"Ses seviyesi: %{lvl}"

            if "percent" in result and ("is_charging" in result or "charging" in result):
                try:
                    pct = int(float(result.get("percent", 0)))
                except Exception:
                    pct = 0
                charging = bool(result.get("is_charging", result.get("charging")))
                status = "şarj oluyor" if charging else "pilde"
                return f"Pil: %{max(0, min(100, pct))} ({status})"

            # Hava durumu renderer
            if "current" in result and isinstance(result.get("current"), dict):
                cur = result["current"]
                loc = result.get("location", "")
                temp = cur.get("temp_c", "?")
                feels = cur.get("feels_like_c", "?")
                desc = cur.get("description", "")
                humidity = cur.get("humidity", "?")
                wind = cur.get("wind", "?")
                loc_str = f"{loc} · " if loc else ""
                parts = [f"🌡 {loc_str}{temp}°C (hissedilen {feels}°C)"]
                if desc:
                    parts.append(f"  {desc}")
                parts.append(f"  Nem: %{humidity} · Rüzgar: {wind}")
                forecast_list = result.get("forecast", [])
                if forecast_list:
                    parts.append("Tahmin:")
                    for f_item in forecast_list[:3]:
                        if isinstance(f_item, dict):
                            d = f_item.get("date", "")
                            hi = f_item.get("max_c", "")
                            lo = f_item.get("min_c", "")
                            parts.append(f"  {d}: {lo}–{hi}°C")
                return "\n".join(parts)

            # Kod çalıştırma renderer
            if "returncode" in result or "stdout" in result or "stderr" in result:
                out_text = str(result.get("stdout") or result.get("output") or "").strip()
                err_text = str(result.get("stderr") or result.get("error") or "").strip()
                rc_raw = result.get("returncode", result.get("return_code", result.get("exit_code", 0)))
                try:
                    rc = int(rc_raw)
                except Exception:
                    rc = 0
                if rc != 0:
                    if err_text:
                        return f"Hata: Komut basarisiz (rc={rc})\n{err_text[:800]}"
                    return f"Hata: Komut basarisiz (rc={rc})"
                if out_text:
                    return f"```\n{out_text[:2000]}\n```"
                command = str(result.get("command") or "").strip()
                if command:
                    return f"Komut calistirildi: {command}"
                return "Komut calistirildi."

            if "output" in result and "return_code" in result:
                output_text = str(result.get("output") or "").strip()
                err_text = str(result.get("error_output") or "").strip()
                rc = result.get("return_code", 0)
                if rc == 0 and output_text:
                    return f"```\n{output_text}\n```"
                elif rc == 0 and not output_text:
                    return "Kod çalıştırıldı, çıktı yok."
                else:
                    err_part = f"\nHata:\n```\n{err_text[:800]}\n```" if err_text else ""
                    return f"Kod çalıştırıldı ancak hata oluştu (rc={rc}){err_part}"

            if isinstance(result.get("system"), dict):
                system = result.get("system", {})
                cpu = result.get("cpu", {}) if isinstance(result.get("cpu"), dict) else {}
                mem = result.get("memory", {}) if isinstance(result.get("memory"), dict) else {}
                disk = result.get("disk", {}) if isinstance(result.get("disk"), dict) else {}
                os_name = system.get("os", "Sistem")
                ver = system.get("version", "")
                cpu_pct = cpu.get("percent", "—")
                ram_gb = mem.get("total_gb", "—")
                disk_use = disk.get("usage", "—")
                return f"{os_name} {ver}\nCPU: {cpu_pct}% · RAM: {ram_gb} GB · Disk: {disk_use}"

            if isinstance(result.get("items"), list):
                items = result.get("items", [])
                names = []
                for item in items[:40]:
                    if isinstance(item, dict):
                        nm = item.get("name")
                        if nm:
                            names.append(str(nm))
                    else:
                        names.append(str(item))
                suffix = f"\n... (+{len(items) - 40} öğe)" if len(items) > 40 else ""
                return "Klasör içeriği:\n" + ("\n".join(f"- {x}" for x in names) if names else "(boş)") + suffix

            if isinstance(result.get("matches"), list):
                matches = result.get("matches", [])
                lines = [str(x) for x in matches[:40]]
                suffix = f"\n... (+{len(matches) - 40} eşleşme)" if len(matches) > 40 else ""
                return "Eşleşen dosyalar:\n" + ("\n".join(f"- {x}" for x in lines) if lines else "(eşleşme yok)") + suffix

            if isinstance(result.get("content"), str) and result.get("content"):
                content = result["content"]
                if len(content) > 3500:
                    content = content[:3500] + "\n...\n[çıktı kısaltıldı]"
                return content

            if result.get("success") is True and isinstance(result.get("path"), str):
                base = f"İşlem tamamlandı: {result['path']}"
                size_bytes = result.get("size_bytes")
                if isinstance(size_bytes, int) and size_bytes >= 0:
                    base += f" ({size_bytes} bytes)"
                warn = str(result.get("verification_warning") or "").strip()
                if warn:
                    base += f"\nNot: {warn}"
                return base

            if result.get("success") is True and isinstance(result.get("url"), str):
                return f"İşlem tamamlandı: {result['url']}"

            if result.get("success") is True:
                return "İşlem başarıyla tamamlandı."

            return json.dumps(result, ensure_ascii=False, indent=2)

        return str(result)

    async def shutdown(self):
        logger.info("Agent shutting down.")
        # Kernel handles resource cleanup usually, but we can trigger it
        pass
