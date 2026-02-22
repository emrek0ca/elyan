from typing import Any, Optional
import asyncio
import inspect
import json
import re as _re
import time
from datetime import datetime
from pathlib import Path
from difflib import get_close_matches
from urllib.parse import quote_plus
from core.kernel import kernel
from core.output_contract import get_contract_engine
from core.neural_router import neural_router
from core.action_lock import action_lock
from core.quick_intent import get_quick_intent_detector, IntentCategory as _IC
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
from core.job_templates import detect_job_type, get_template
from core.pipeline import PipelineContext
from core.cdg_engine import cdg_engine
from core.style_profile import style_profile
from core.constraint_engine import constraint_engine
from core.failure_clustering import failure_clustering
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
from security.validator import validate_input, sanitize_input
from security.privacy_guard import redact_text, sanitize_for_storage, sanitize_object
from security.tool_policy import tool_policy
from core.i18n import detect_language
from utils.logger import get_logger

logger = get_logger("agent")

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
    "random_image": "create_visual_asset_pack",
    "create_calendar_event": "create_event",
    "create_calendar": "create_event",
    "get_calendar": "get_today_events",
    "battery_status": "get_battery_status",
    "get_battery": "get_battery_status",
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
        self.current_user_id = None
        self.file_context = {
            "last_dir": str(Path.home() / "Desktop"),
            "last_path": "",
        }
        # Son başarılı aksiyon — feedback/correction sistemi için
        self._last_action: str = ""

    def _ensure_llm(self) -> bool:
        if self.llm is not None:
            return True
        try:
            candidate = getattr(self.kernel, "llm", None)
        except Exception:
            candidate = None
        if candidate is not None:
            self.llm = candidate
            return True
        return False

    @staticmethod
    def _fallback_chat_without_llm(user_input: str = "") -> str:
        text = str(user_input or "").lower()
        if any(k in text for k in ("durum", "status", "sağlık", "saglik", "health")):
            return "LLM bağlantısı hazır değil. 'elyan models status' ve 'elyan gateway health --json' ile kontrol edebilirsin."
        return "LLM sağlayıcısına şu an erişemiyorum. Model bağlantısını kontrol edip tekrar dener misin?"

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

    async def initialize(self) -> bool:
        await self.kernel.initialize()
        self.llm = self.kernel.llm
        logger.info("Agent Initialized.")
        return True

    async def process(self, user_input: str, notify=None) -> str:
        started_at = time.perf_counter()
        uid = str(self.current_user_id or "local")

        # 0. Quota Check
        quota = quota_manager.check_quota(uid)
        if not quota.get("allowed", True):
            limit_msg = f"\n\nGünlük mesaj sınırına ulaştın ({quota.get('limit')} mesaj). Devam etmek için Pro plana geçebilirsin."
            if quota.get("reason") == "monthly_token_limit_reached":
                limit_msg = f"\n\nAylık token sınırına ulaştın ({quota.get('limit')} token). Devam etmek için Pro plana geçebilirsin."
            
            # Record failed attempt if needed, but usually we just block.
            return f"Üzgünüm, {limit_msg}"

        # 1. Validation
        valid, msg = validate_input(user_input)
        if not valid:
            return f"Hata: {msg}"

        user_id = int(self.current_user_id or 0)
        history = self.kernel.memory.get_recent_conversations(user_id, limit=5)

        # 2. Action-Lock Check
        if action_lock.is_locked:
            if any(kw in user_input.lower() for kw in ["dur", "iptal", "cancel", "stop"]):
                action_lock.unlock()
                return "Üretim modu durduruldu ve kilit açıldı."
            return f"{action_lock.get_status_prefix()}Şu an bir göreve odaklanmış durumdayım. İptal etmek için 'iptal' yazabilirsin."

        status_prefix = action_lock.get_status_prefix()
        
        # 3. Context7 Injection Check
        context_docs = ""
        if "use context7" in user_input.lower():
            tech = "React" if "react" in user_input.lower() else "Python"
            context_docs = await context7_client.fetch_docs(tech)
            user_input = user_input.replace("use context7", "").strip()
            logger.info(f"Context7 docs injected for {tech}")

        user_input = self._normalize_user_input(user_input)
        user_input = sanitize_input(user_input)
        
        # 3c. Context Intelligence - Dynamic Morphing
        ctx_intel = get_context_intelligence()
        op_context = ctx_intel.detect(user_input)
        specialized_prompt = ctx_intel.get_specialized_prompt(op_context)
        preferred_tools = ctx_intel.get_preferred_tools(op_context["domain"])
        
        logger.info(f"Operation Context: {op_context['domain']} (Stack: {op_context['stack']})")
        if specialized_prompt:
            logger.info("Injecting specialized behavior prompt.")

        self._ensure_llm()

        # 3b. Feedback / Correction Detection
        _fb_store = get_feedback_store()
        _fb_detector = get_feedback_detector()
        _is_correction, _corrected_text = _fb_detector.extract_correction_intent(user_input)
        if _is_correction and _corrected_text != user_input:
            if self._last_action:
                _fb_store.record_correction(
                    user_id=user_id,
                    original_input=user_input,
                    wrong_action=self._last_action,
                    correction_text=_corrected_text,
                )
                logger.info(f"[feedback] Correction recorded for action={self._last_action!r}")
            user_input = _corrected_text
        elif _fb_detector.is_positive(user_input) and self._last_action:
            _fb_store.record_positive(
                user_id=user_id,
                original_input=user_input,
                action=self._last_action,
            )

        # Very short/ambiguous controls should not trigger hallucinated side effects.
        short_hint = self._handle_short_ambiguous_input(user_input)
        if short_hint:
            await self._finalize_turn(
                user_input=user_input,
                response_text=short_hint,
                action="clarify",
                success=True,
                started_at=started_at,
                context={"route_role": "clarify", "source": "short_ambiguous_guard"},
            )
            _push("chat", "agent", user_input[:60], success=True)
            return status_prefix + short_hint
        
        # 4. Neural Routing (Role & Complexity Detection)
        route = neural_router.route(user_input)
        role = route["role"]
        logger.info(f"Routed: {role} (complexity: {route['complexity']}) using {route['model']}")

        # Intent parser (deterministic) before chat/planner.
        parsed_intent = self.intent_parser.parse(user_input)
        action_name = str(parsed_intent.get("action", "") or "").lower() if isinstance(parsed_intent, dict) else ""

        # Correction hint: önceki hatalı aksiyona ait ipucu üret
        if isinstance(parsed_intent, dict) and action_name and action_name not in {"", "chat", "unknown"}:
            _hint = _fb_store.build_correction_hint(user_id, action_name)
            if _hint:
                parsed_intent.setdefault("_correction_hint", _hint)
                logger.debug(f"[feedback] Hint injected for action={action_name!r}")

        if action_name in {"chat", "unknown", ""} and not self._is_likely_chat_message(user_input):
            learned_action = self.learning.quick_match(user_input)
            safe_param_free = {
                "take_screenshot",
                "get_system_info",
                "get_battery_status",
                "get_brightness",
                "wifi_status",
                "bluetooth_status",
                "get_today_events",
                "get_running_apps",
                "toggle_dark_mode",
                "read_clipboard",
            }
            if learned_action in safe_param_free:
                parsed_intent = {
                    "action": learned_action,
                    "params": {},
                    "reply": "Öğrenilmiş hızlı eşleşme uygulanıyor...",
                    "confidence": 0.82,
                    "source": "learning_quick_match",
                }
            else:
                multi_intent = self._infer_multi_task_intent(user_input)
                if multi_intent:
                    multi_intent.setdefault("confidence", 0.86)
                    multi_intent.setdefault("source", "general_multi_fallback")
                    parsed_intent = multi_intent
                else:
                    general_intent = self._infer_general_tool_intent(user_input)
                    if general_intent:
                        general_intent.setdefault("confidence", 0.84)
                        general_intent.setdefault("source", "general_fallback")
                        parsed_intent = general_intent
                    else:
                        save_intent = self._infer_save_intent(user_input)
                        if save_intent:
                            save_intent.setdefault("confidence", 0.82)
                            save_intent.setdefault("source", "save_fallback")
                            parsed_intent = save_intent
                        else:
                            skill_intent = self._infer_skill_intent(user_input)
                            if skill_intent:
                                skill_intent.setdefault("confidence", 0.8)
                                skill_intent.setdefault("source", "skill_fallback")
                                parsed_intent = skill_intent

            unresolved_action = str(parsed_intent.get("action", "") or "").lower() if isinstance(parsed_intent, dict) else ""
            if unresolved_action in {"chat", "unknown", ""}:
                llm_intent = await self._infer_llm_tool_intent(user_input, history=history, user_id=uid)
                if llm_intent:
                    llm_intent.setdefault("confidence", 0.72)
                    llm_intent.setdefault("source", "llm_tool_fallback")
                    parsed_intent = llm_intent

        # 5. Production Mode Trigger
        lock_patterns = _re.compile(r'\b(website|proje|uygulama|program|script|geliştir|oluştur)\b', _re.IGNORECASE)
        if lock_patterns.search(user_input) and not action_lock.is_locked:
            action_lock.lock("delivery_task", "Planlama yapılıyor...")

        # 6. Special UI Tools (Canvas/Slidev)
        if any(kw in user_input.lower() for kw in ["görselleştir", "tablo yap", "kanban", "grafik"]):
            view_id = canvas_engine.create_view("kanban" if "kanban" in user_input.lower() else "chart", "Dashboard View", {})
            return f"Görselleştirme hazır: http://localhost:18789/canvas?id={view_id}"

        # 7. Direct deterministic intent execution.
        if self._should_run_direct_intent(parsed_intent, user_input):
            direct_text = await self._run_direct_intent(parsed_intent, user_input, role, history, user_id=uid)
            success = not direct_text.startswith("Hata:")
            action = str(parsed_intent.get("action", "direct") or "direct")
            await self._finalize_turn(
                user_input=user_input,
                response_text=direct_text,
                action=action,
                success=success,
                started_at=started_at,
                context={
                    "route_role": role,
                    "intent_source": parsed_intent.get("source", "intent_parser"),
                    "intent_confidence": parsed_intent.get("confidence"),
                },
            )
            _push("chat" if action == "chat" else "task_done", "agent", user_input[:60], success=success)
            if action_lock.is_locked:
                action_lock.unlock()
            return status_prefix + direct_text

        # 7. Intent Path (Fast vs Slow)
        quick_intent = self.quick_intent.detect(user_input)
        if self._should_route_to_llm_chat(user_input, parsed_intent, quick_intent):
            # Inject context-aware instructions into the final prompt
            context_prefix = f"[MOD: {specialized_prompt}]\n\n" if specialized_prompt else ""
            full_prompt = f"{context_prefix}Docs: {context_docs}\n\nUser: {user_input}" if context_docs else f"{context_prefix}{user_input}"
            
            if self._ensure_llm():
                try:
                    chat_resp = await with_timeout(
                        self.llm.generate(full_prompt, role=role, history=history, user_id=uid),
                        seconds=LLM_TIMEOUT,
                        fallback=friendly_timeout_message("llm"),
                        context="llm_chat",
                    )
                except Exception:
                    chat_resp = self._fallback_chat_without_llm(user_input)
            else:
                chat_resp = self._fallback_chat_without_llm(user_input)
            await self._finalize_turn(
                user_input=user_input,
                response_text=chat_resp,
                action="chat",
                success=True,
                started_at=started_at,
                context={"route_role": role, "quick_intent": str(getattr(quick_intent, "category", "chat"))},
            )
            _push("chat", "agent", user_input[:60])
            return status_prefix + chat_resp

        # 8. Strategic Planning & Execution (Registry-based)
        try:
            # 8a. Resource Health Check
            monitor = get_resource_monitor()
            health = monitor.get_health_snapshot()
            health_notice = ""
            
            if health.status == "critical":
                issues_text = ", ".join(health.issues)
                return f"⚠️ **İşlem Durduruldu:** Sistem kaynakları kritik seviyede ({issues_text}). Lütfen bazı uygulamaları kapatıp tekrar dene."
            
            if health.status == "warning":
                issues_text = ", ".join(health.issues)
                health_notice = f"> 💡 **Sistem Notu:** {issues_text}. İşlem biraz yavaş seyredebilir.\n\n"

            # ── CDG Engine Master Architecture (Phase 3) ──
            job_type = detect_job_type(user_input)
            if job_type != "communication":
                logger.info(f"CDG Engine activated for job: {job_type}")
                cdg_plan = cdg_engine.create_plan(f"job_{int(time.time())}", job_type, user_input)
                
                async def cdg_executor(node):
                    patch_inst = node.params.pop("_auto_patch_instruction", "")
                    if node.action in ("plan", "refine"):
                        prompt = f"{style_profile.to_prompt_lines()}\n\nGirdi: {user_input}\nGörev: {node.name}\nAçıklama: Bu adımda ne yapılmalı planla.{patch_inst}"
                        resp = await self.llm.generate(prompt)
                        return {"output": resp}
                    else:
                        patched_input = user_input + patch_inst if patch_inst else user_input
                        res = await self._execute_tool(node.action, node.params, user_input=patched_input, step_name=node.name)
                        return res if isinstance(res, dict) else {"output": str(res)}
                
                cdg_plan = await cdg_engine.execute(cdg_plan, cdg_executor)
                manifest = cdg_engine.get_evidence_manifest(cdg_plan)
                
                overall_success = cdg_plan.status == "passed"
                tool_results = [n.result for n in cdg_plan.nodes]
                
                if overall_success:
                    base_msg = "✅ İşlem tamamlandı."
                    if manifest["artifacts"]:
                        paths = [a.get("path") for a in manifest["artifacts"] if a.get("path")]
                        base_msg += f"\nÜretilen dosyalar: {', '.join(paths)}"
                else:
                    base_msg = "❌ İşlem sırasında hatalar oluştu."
                
                # Constraint Engine (hard rules update response)
                result_str, violations = constraint_engine.enforce(
                    base_msg,
                    tool_results=tool_results,
                    job_type=job_type,
                    contract_passed=overall_success
                )
                
                # Evidence Gate
                result_str = evidence_gate.enforce(result_str, tool_results)
                
                # Failure Clustering
                if not overall_success:
                    for node in cdg_plan.nodes:
                        if node.state.value == "failed":
                            fail_code = failure_clustering.detect_failure_code(node.error or str(node.result), node.action, str(node.result))
                            failure_clustering.record(fail_code, job_type, node.error or str(node.result))
                            # Add auto-patch playbook suggestion to error
                            suggestion = failure_clustering.suggest_fix(fail_code)
                            result_str += f"\n\n**Hata Analizi ({node.name})**\n{suggestion}"

                await self._finalize_turn(
                    user_input=user_input,
                    response_text=result_str,
                    action="cdg_engine_execution",
                    success=overall_success,
                    started_at=started_at,
                    context={"job_type": job_type, "nodes": len(cdg_plan.nodes)}
                )
                if action_lock.is_locked: action_lock.unlock()
                return status_prefix + health_notice + result_str
            # ── End CDG Engine ──

            plan = await with_timeout(
                self.planner.create_plan(user_input, {}, user_id=uid, preferred_tools=preferred_tools),
                seconds=PLANNER_TIMEOUT,
                fallback=None,
                context="planner",
            )
            
            # --- Multi-Agent Delegation ---
            subtasks = getattr(plan, "subtasks", []) or []
            if len(subtasks) >= 2:
                orchestrator = get_orchestrator(self)
                logger.info(f"Complex task detected with {len(subtasks)} steps. Activating Lead Orchestrator.")
                # BP-001: Add total timeout for multi-agent flow
                result_str = await with_timeout(
                    orchestrator.manage_flow(plan, user_input),
                    seconds=300, # 5 minutes max for factory flow
                    fallback="Üzgünüm, görev çok uzun sürdüğü için zaman aşımına uğradı.",
                    context="orchestrator_factory"
                )
                overall_success = True if "✅" in result_str else False

                # ── Evidence Gate: proof-only delivery ──
                result_str = evidence_gate.enforce(result_str, [])

                await self._finalize_turn(
                    user_input=user_input,
                    response_text=result_str,
                    action="multi_agent_delegation",
                    success=overall_success,
                    started_at=started_at,
                    context={"subtask_count": len(subtasks), "method": "orchestrator"}
                )
                if action_lock.is_locked: action_lock.unlock()
                return status_prefix + health_notice + result_str
            # --- End Multi-Agent Delegation ---
        except asyncio.TimeoutError:
            if action_lock.is_locked:
                action_lock.unlock()
            return status_prefix + friendly_timeout_message("planner")
        
        quality = self.planner.evaluate_plan_quality(getattr(plan, "subtasks", []) or [], user_input)
        if not quality.get("safe_to_run", True):
            # One controlled self-revision pass before rejecting complex tasks.
            revise_fn = getattr(self.planner, "revise_plan", None)
            if callable(revise_fn):
                try:
                    revised_subtasks = await revise_fn(
                        user_input,
                        current_subtasks=getattr(plan, "subtasks", []) or [],
                        context={},
                        failure_feedback="; ".join(quality.get("issues", [])[:8]),
                        llm_client=self.llm,
                        use_llm=True,
                        user_id=uid,
                    )
                    if isinstance(revised_subtasks, list) and revised_subtasks:
                        plan.subtasks = revised_subtasks
                        quality = self.planner.evaluate_plan_quality(getattr(plan, "subtasks", []) or [], user_input)
                except Exception as exc:
                    logger.debug(f"Plan revision skipped due to error: {exc}")

        if not quality.get("safe_to_run", True):
            should_chat_fallback = (
                self._is_information_question(user_input)
                or self._is_likely_chat_message(user_input)
                or action_name in {"", "chat", "unknown"}
            )
            if should_chat_fallback:
                full_prompt = f"Docs: {context_docs}\n\nUser: {user_input}" if context_docs else user_input
                if self._ensure_llm():
                    try:
                        chat_resp = await with_timeout(
                            self.llm.generate(full_prompt, role=role, history=history, user_id=uid),
                            seconds=LLM_TIMEOUT,
                            fallback=friendly_timeout_message("llm"),
                            context="llm_chat_unsafe_plan",
                        )
                    except Exception:
                        chat_resp = self._fallback_chat_without_llm(user_input)
                else:
                    chat_resp = self._fallback_chat_without_llm(user_input)
                await self._finalize_turn(
                    user_input=user_input,
                    response_text=chat_resp,
                    action="chat_fallback_unsafe_plan",
                    success=True,
                    started_at=started_at,
                    context={"route_role": role, "fallback": "unsafe_plan_to_chat"},
                )
                _push("chat", "agent", user_input[:60], success=True)
                if action_lock.is_locked:
                    action_lock.unlock()
                return status_prefix + chat_resp
            if action_lock.is_locked:
                action_lock.unlock()
            # Do not hard-fail with planner jargon on user-facing path.
            return "Bu isteği güvenli şekilde çalıştırmak için biraz daha açık adım gerekiyor. Örn: 'masaüstünde Projects klasörünü listele'."

        final_results = []
        executed_steps = set()
        failed_steps = []
        subtasks = plan.subtasks or []
        pending_steps = list(subtasks)

        # Execution Loop
        while pending_steps and len(executed_steps) < (len(subtasks) + 5):
            # Dependency Resolution
            runnable = [
                s for s in pending_steps
                if all(d in executed_steps for d in (getattr(s, "dependencies", []) or []))
            ]
            if not runnable:
                rescue = self._select_dependency_rescue_step(pending_steps, executed_steps)
                if rescue is None:
                    break
                runnable = [rescue]

            for step in runnable:
                # Update Lock
                progress = (len(executed_steps) + 1) / max(len(subtasks), 1)
                step_name = str(getattr(step, "name", "") or "Adım")
                action_lock.update_status(progress, step_name)
                
                if notify and step_name != "_chat_":
                    await notify(f"🛠️ {step_name}")

                try:
                    step_result_text, step_ok = await self._execute_planned_step_with_recovery(
                        step,
                        user_input=user_input,
                    )
                    final_results.append(step_result_text)
                    step_id = str(getattr(step, "task_id", "") or f"step_{len(executed_steps)+1}")
                    if step_ok:
                        executed_steps.add(step_id)
                    else:
                        failed_steps.append(
                            {
                                "id": step_id,
                                "name": step_name,
                                "action": str(getattr(step, "action", "") or ""),
                                "error": step_result_text[:300],
                            }
                        )
                    pending_steps.remove(step)
                except Exception as e:
                    logger.error(f"Execution error ({getattr(step, 'action', '')}): {e}")
                    failed_steps.append(
                        {
                            "id": str(getattr(step, "task_id", "") or f"step_{len(failed_steps)+1}"),
                            "name": step_name,
                            "action": str(getattr(step, "action", "") or ""),
                            "error": str(e),
                        }
                    )
                    pending_steps.remove(step)

        if action_lock.is_locked: action_lock.unlock()

        # Final fallback for complex tasks: try direct intent once if planner path produced no successful execution.
        if not executed_steps and failed_steps:
            fallback_intent = self._infer_general_tool_intent(user_input)
            if isinstance(fallback_intent, dict) and str(fallback_intent.get("action", "")).strip().lower() not in {"", "chat", "unknown"}:
                try:
                    fallback_text = await self._run_direct_intent(fallback_intent, user_input, role, history)
                    if isinstance(fallback_text, str) and fallback_text.strip():
                        final_results.append(fallback_text)
                        if not self._result_text_is_error(fallback_text):
                            executed_steps.add("fallback_direct")
                except Exception as exc:
                    logger.debug(f"Direct fallback after planner failure failed: {exc}")

        result_lines = [x for x in final_results if x]
        if failed_steps:
            result_lines.append("Başarısız adımlar:")
            for item in failed_steps[:6]:
                result_lines.append(f"- {item['name']} ({item['action']}): {item['error'][:160]}")

        result_str = "\n".join(result_lines).strip() or "Görev tamamlandı, ancak görüntülenecek çıktı üretilmedi."
        overall_success = bool(executed_steps)

        # ── Evidence Gate: proof-only delivery ──
        _tool_evidence = [s.get("result", {}) for s in (subtask_results if 'subtask_results' in dir() else []) if isinstance(s, dict)]
        result_str = evidence_gate.enforce(result_str, _tool_evidence)

        await self._finalize_turn(
            user_input=user_input,
            response_text=result_str,
            action="multi_step",
            success=overall_success,
            started_at=started_at,
            context={
                "route_role": role,
                "subtask_count": len(subtasks),
                "executed_steps": len(executed_steps),
                "failed_steps": len(failed_steps),
            },
        )
        _push("task_done", "agent", user_input[:60], success=overall_success)
        return status_prefix + health_notice + result_str

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

    async def _execute_tool(self, tool_name: str, params: dict, *, user_input: str = "", step_name: str = ""):
        """Execute a tool via the Kernel Registry with Pipeline and Healing support."""
        # ── Pipeline Resolution ──────────────────────────────────────────────
        pipeline = get_pipeline_state()
        params = pipeline.resolve_placeholders(params)
        
        # Normalize params
        safe_params = params if isinstance(params, dict) else {}
        clean_params = {k: v for k, v in safe_params.items() if k not in ("action", "type")}
        mapped_tool = ACTION_TO_TOOL.get(tool_name, tool_name)
        resolved_tool = self._resolve_tool_name(mapped_tool)
        if resolved_tool:
            mapped_tool = resolved_tool
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

        # Special case: Chat action fallback
        uid = str(self.current_user_id or "local")
        
        # --- Intervention Check (Policy-Based) ---
        policy_check = tool_policy.check_access(mapped_tool)
        if policy_check.get("requires_approval"):
            # Smart Approval Check
            should_ask = True
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
                    context={"tool": mapped_tool, "params": clean_params, "policy_reason": policy_check.get("reason")},
                    options=["Onayla", "İptal Et"]
                )
                
                # --- Learning: Record Approval/Rejection ---
                if self.learning:
                    is_approved = (choice == "Onayla")
                    asyncio.create_task(self.learning.record_interaction(
                        user_id=uid,
                        input_text=user_input or f"manual_approval_request_{mapped_tool}",
                        intent="security_approval",
                        action=mapped_tool,
                        success=is_approved,
                        duration_ms=0,
                        context={"params": clean_params, "policy": policy_check},
                        feedback="Explicit Approval" if is_approved else "Explicit Rejection"
                    ))
                # -------------------------------------------

                if choice != "Onayla":
                    err_text = "İşlem kullanıcı tarafından iptal edildi."
                    return {"success": False, "error": err_text, "error_code": "USER_ABORTED"}
        # --- End Intervention ---

        if mapped_tool in ("chat", "respond", "answer"):
            prompt = safe_params.get("message") or user_input
            try:
                if self._ensure_llm():
                    result = await self.llm.generate(prompt, user_id=uid)
                else:
                    result = self._fallback_chat_without_llm(prompt)
                success = True
                return result
            except Exception as exc:
                err_text = str(exc)
                raise
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
            if isinstance(result, dict) and result.get("success") is False:
                err_text = str(result.get("error", "") or "")
                
                # ── Self-Healing Attempt ──────────────────────────────────────
                healing_engine = get_healing_engine()
                diagnosis = healing_engine.diagnose(err_text)
                
                # First check KB for known solution
                kb = get_knowledge_base()
                known_solution = kb.find_solution(mapped_tool, diagnosis.name if diagnosis else err_text)
                
                if known_solution and "params" in known_solution:
                    logger.info(f"Proven solution found in Knowledge Base for '{mapped_tool}'. Retrying with proven params.")
                    retry_result = await self.kernel.tools.execute(mapped_tool, known_solution["params"])
                    if isinstance(retry_result, dict) and retry_result.get("success"):
                        result = retry_result
                        result["_healed"] = True
                        result["_healing_message"] = "Geçmiş deneyimlere dayanarak sorun otomatik giderildi."
                        return result

                if diagnosis:
                    ctx = {"tool_name": mapped_tool, "params": clean_params}
                    plan = await healing_engine.get_healing_plan(diagnosis, err_text, ctx)
                    logger.info(f"Self-Healing: {plan['description']} (Can fix: {plan['can_auto_fix']})")
                    
                    if plan["can_auto_fix"]:
                        # If we can auto-fix (e.g. change path or install module), do it and retry.
                        if "fix_command" in plan:
                            logger.info(f"Executing healing command: {plan['fix_command']}")
                            import subprocess
                            subprocess.run(plan["fix_command"].split(), check=False)
                        
                        retry_params = plan.get("suggested_params", clean_params)
                        retry_result = await self.kernel.tools.execute(mapped_tool, retry_params)
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
                        retry_result = await self.kernel.tools.execute(mapped_tool, repaired_params)
                        result = retry_result
                        clean_params = repaired_params
                        if isinstance(result, dict) and result.get("success") is False:
                            err_text = str(result.get("error", "") or err_text)

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
                        retry_res = await self.kernel.tools.execute(mapped_tool, exec_params)
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
                        repair_res = await self._execute_tool(r_action, exec_r_params, user_input=user_input, step_name=f"Onarım: {r_action}")
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

            success = not (isinstance(result, dict) and result.get("success") is False)
            if success:
                self._update_file_context_after_tool(mapped_tool, clean_params, result)
                # Store in pipeline for subsequent steps
                pipeline = get_pipeline_state()
                pipeline.store(mapped_tool, result)
                if step_name:
                    pipeline.store(step_name, result)
            return result
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
                    return {"success": False, "error": err_text}
            try:
                invoke_params = self._adapt_params_for_tool_signature(
                    tool_func, mapped_tool, clean_params, user_input=user_input, step_name=step_name
                )
                result = await self._invoke_tool_callable(tool_func, invoke_params)
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
                        result = await self._invoke_tool_callable(tool_func, repaired_params)
                        invoke_params = repaired_params
                        if isinstance(result, dict) and result.get("success") is False:
                            err_text = str(result.get("error", "") or err_text)
                success = not (isinstance(result, dict) and result.get("success") is False)
                if isinstance(result, dict) and result.get("success") is False:
                    err_text = str(result.get("error", ""))
                result = self._postprocess_tool_result(used_tool, invoke_params, result, user_input=user_input)
                success = not (isinstance(result, dict) and result.get("success") is False)
                if success:
                    self._update_file_context_after_tool(used_tool, invoke_params, result)
                return result
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
                        result = await self._invoke_tool_callable(tool_func, repaired_params)
                        success = not (isinstance(result, dict) and result.get("success") is False)
                        if isinstance(result, dict) and result.get("success") is False:
                            err_text = str(result.get("error", ""))
                        result = self._postprocess_tool_result(used_tool, repaired_params, result, user_input=user_input)
                        success = not (isinstance(result, dict) and result.get("success") is False)
                        if success:
                            self._update_file_context_after_tool(used_tool, repaired_params, result)
                        return result
                    except Exception as retry_exc:
                        logger.error(f"Fallback tool retry failed ({mapped_tool}): {retry_exc}")
                        err_text = str(retry_exc)
                        return {"success": False, "error": str(retry_exc)}
                friendly_error = self._friendly_missing_argument_error(str(e), tool_name=used_tool)
                if friendly_error:
                    logger.warning(f"Tool invocation missing param ({used_tool}): {friendly_error}")
                    err_text = friendly_error
                    return {"success": False, "error": friendly_error}
                logger.error(f"Fallback tool execution error ({mapped_tool}): {e}")
                err_text = str(e)
                return {"success": False, "error": str(e)}
        except asyncio.TimeoutError:
            err_text = f"Tool '{mapped_tool}' timed out"
            logger.warning(f"[timeout_guard] {err_text}")
            return {"success": False, "error": friendly_timeout_message(mapped_tool)}
        except Exception as exc:
            err_text = str(exc)
            raise
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
        if inspect.iscoroutinefunction(tool_func):
            return await tool_func(**invoke_params)
        return tool_func(**invoke_params)

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
    def _is_creative_writing_request(text: str) -> bool:
        t = str(text or "").lower().strip()
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
        t = str(text or "").strip().lower()
        if not t:
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
        return any(k in text for k in (" ve ", " sonra ", " ardından ", " once ", "önce "))

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
            "delete_file",
            "move_file",
            "copy_file",
            "rename_file",
            "create_folder",
        }:
            candidate = str(
                result.get("destination")
                or result.get("path")
                or params.get("destination")
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
        write_tools = {"write_file", "write_word", "write_excel", "create_web_project_scaffold",
                       "create_software_project_pack", "research_document_delivery"}
        if mapped in write_tools or tool_name in write_tools:
            result = self._attach_artifact_verification(result, params, user_input=user_input)
            # Output Contract: verify deliverable meets done criteria
            try:
                contract_engine = get_contract_engine()
                spec = contract_engine.create_spec(mapped or tool_name, params, user_input)
                if spec:
                    verification = contract_engine.verify(spec)
                    result["_contract_verified"] = verification.get("all_passed", True)
                    if not verification.get("all_passed", True):
                        failed = [a for a in verification.get("artifacts", []) if not a.get("passed")]
                        if failed:
                            issues = "; ".join(f.get("issues", [f"artifact not met"])[0] if f.get("issues") else "criterion not met" for f in failed)
                            result.setdefault("verification_warning", f"Teslimat kriteri karşılanmadı: {issues}")
                        repair = contract_engine.repair_actions(spec, verification)
                        if repair:
                            result["_repair_actions"] = repair
            except Exception:
                pass
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

    @staticmethod
    def _is_likely_chat_message(text: str) -> bool:
        t = str(text or "").lower().strip()
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
    def _extract_terminal_command_from_text(user_input: str) -> str:
        text = str(user_input or "").strip()
        if not text:
            return ""

        if text.startswith("$"):
            return text[1:].strip()

        patterns = (
            r"(?:terminal(?:de)?|shell(?:de)?|konsol(?:da)?|komut satır(?:ı|inda)?)\s*(?:şunu|bunu)?\s*(?:çalıştır|calistir|run|execute)?\s*[:\-]?\s*(.+)$",
            r"(?:çalıştır|calistir|run|execute)\s*(?:şunu|bunu)?\s*(?:terminal(?:de)?|shell(?:de)?|konsol(?:da)?)?\s*[:\-]?\s*(.+)$",
            r"(?:komut(?:u)?|command)\s*[:\-]\s*(.+)$",
        )
        for pattern in patterns:
            m = _re.search(pattern, text, _re.IGNORECASE)
            if not m:
                continue
            cmd = str(m.group(1) or "").strip(" \"'`")
            cmd = _re.sub(r"\s+(?:komutunu?|command)\s*(?:çalıştır|calistir|run|execute)$", "", cmd, flags=_re.IGNORECASE).strip()
            cmd = _re.sub(r"\s+(?:çalıştır|calistir|run|execute)$", "", cmd, flags=_re.IGNORECASE).strip()
            if cmd:
                return cmd

        # Last resort for explicit terminal intent: use tail segment after marker.
        for marker in ("terminal", "shell", "konsol", "komut satırı", "komut satiri"):
            low = text.lower()
            idx = low.find(marker)
            if idx >= 0:
                tail = text[idx + len(marker):].strip(" :,-")
                if tail:
                    return tail
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

        for m in _re.finditer(r"[\"']([^\"']+)[\"']", text):
            raw = str(m.group(1) or "").strip()
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
    def _split_multi_step_text(user_input: str) -> list[str]:
        text = str(user_input or "").strip()
        if not text:
            return []

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
        save_match = _re.search(r"\b(?:kaydet|yaz)\b", low)
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
        return {
            "action": "multi_task",
            "tasks": tasks,
            "reply": "Çok adımlı görev başlatılıyor...",
        }

    def _infer_step_intent(self, text: str) -> Optional[dict[str, Any]]:
        intent = self._infer_general_tool_intent(text) or self._infer_save_intent(text)
        if intent:
            return intent

        low = str(text or "").lower()
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
                    return None
                action = str(intent.get("action", "") or "").strip().lower()
                if not action or action in {"chat", "unknown"}:
                    return None
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
        return {
            "action": "multi_task",
            "tasks": tasks,
            "reply": "Çok adımlı görev başlatılıyor...",
        }

    def _infer_general_tool_intent(self, user_input: str) -> Optional[dict[str, Any]]:
        text = str(user_input or "").strip()
        low = text.lower()
        if not text:
            return None

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

        coding_intent = self._infer_coding_project_intent(text)
        if coding_intent:
            return coding_intent

        research_markers = (
            "araştır", "arastir", "araştırma", "arastirma", "research", "incele", "analiz",
        )
        doc_markers = (
            "belge", "doküman", "dokuman", "rapor", "word", "docx", "excel", "xlsx", "tablo",
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

            include_word = any(k in low for k in ("word", "docx", "belge", "doküman", "dokuman", "rapor"))
            include_excel = any(k in low for k in ("excel", "xlsx", "tablo", "csv"))
            if not include_word and not include_excel:
                include_word = True
                include_excel = True

            needs_delivery = any(k in low for k in deliver_markers)
            return {
                "action": "research_document_delivery",
                "params": {
                    "topic": topic,
                    "brief": text,
                    "depth": depth,
                    "audience": "executive",
                    "language": "tr",
                    "output_dir": "~/Desktop",
                    "include_word": include_word,
                    "include_excel": include_excel,
                    "include_report": True,
                    "source_policy": "trusted",
                    "min_reliability": 0.62,
                    "deliver_copy": needs_delivery,
                },
                "reply": "Araştırma ve belge paketi hazırlanıyor, çıktı dosyaları paylaşılacak...",
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

        project_name = self._extract_topic(text, "")
        if not project_name or project_name == "genel konu":
            project_name = "web-projesi" if project_kind == "website" else "uygulama-projesi"

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
            },
            "reply": f"'{project_name}' için kod projesi hazırlanıyor...",
        }

    @staticmethod
    def _extract_first_json_object(text: str) -> dict[str, Any] | None:
        raw = str(text or "").strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        match = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    async def _infer_llm_tool_intent(self, user_input: str, *, history: list | None = None, user_id: str = "local") -> Optional[dict[str, Any]]:
        if not self.llm:
            return None

        allow_actions = {
            "list_files", "read_file", "write_file", "delete_file", "search_files",
            "move_file", "copy_file", "rename_file", "create_folder",
            "run_safe_command", "open_app", "close_app", "open_url",
            "web_search", "advanced_research", "take_screenshot", "get_system_info", "get_battery_status",
            "create_word_document", "create_excel", "send_notification", "create_reminder",
            "create_web_project_scaffold", "create_software_project_pack", "create_coding_delivery_plan",
            "create_coding_verification_report",
            "research_document_delivery",
            "open_project_in_ide",
            "create_coding_project",
        }
        prompt = (
            "Kullanıcı isteğini tek bir tool aksiyonuna eşle.\n"
            "Sadece geçerli JSON döndür. Ek metin yazma.\n"
            "Format: {\"action\":\"...\",\"params\":{...},\"confidence\":0.0}\n"
            "Kurallar:\n"
            "1) action sadece izinli tool adlarından biri olsun.\n"
            "2) Terminal komutu için action=run_safe_command ve params.command zorunlu.\n"
            "3) Dosya işlemlerinde path/source/destination varsa doldur.\n"
            "4) Emin değilsen action='chat' döndür.\n"
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
        save_markers = (
            "kaydet", "dosya olarak", "bunu kaydet", "masaüstüne kaydet",
            "masaustune kaydet", "word olarak", "excel olarak",
        )
        if not any(m in text for m in save_markers):
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
                            "include_excel": True,
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
            uid = str(self.current_user_id or "0")
            intent_name = str(action or "chat")
            await self.learning.record_interaction(
                user_id=uid,
                input_text=user_input,
                intent=intent_name,
                action=intent_name,
                success=bool(success),
                duration_ms=max(0, int(duration_ms)),
                context=context or {},
            )
        except Exception as exc:
            logger.debug(f"learning record failed: {exc}")

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
        uid = int(self.current_user_id or 0)
        duration_ms = int((time.perf_counter() - started_at) * 1000)

        # Son başarılı aksiyonu sakla (feedback/correction learning için)
        if action and action not in {"chat", "chat_fallback_unsafe_plan", "clarify", ""}:
            self._last_action = action

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
                str(uid),
                language=detect_language(user_input),
                action=str(action or "chat"),
                success=bool(success),
                topic_keywords=keywords,
            )
        except Exception as exc:
            logger.debug(f"user profile update failed: {exc}")

        await self._record_learning(
            user_input=user_input,
            action=action,
            success=success,
            duration_ms=duration_ms,
            context=context or {},
        )

    async def _run_direct_intent(self, intent: dict, user_input: str, role: str, history: list, user_id: str = "local") -> str:
        action = str(intent.get("action", "") or "")
        params = intent.get("params", {}) if isinstance(intent.get("params"), dict) else {}
        low_action = action.lower()

        if low_action == "multi_task":
            tasks = intent.get("tasks") if isinstance(intent.get("tasks"), list) else []
            outputs = []
            previous_output_text = ""
            i = 0
            while i < len(tasks):
                task = tasks[i]
                if not isinstance(task, dict):
                    i += 1
                    continue

                # If a document write step appears before its content-producing step,
                # pull the closest research/summary task forward.
                if self._task_needs_previous_output(task) and not previous_output_text:
                    next_ctx_idx = self._find_next_context_task_index(tasks, start=i + 1)
                    if next_ctx_idx is not None:
                        tasks.insert(i, tasks.pop(next_ctx_idx))
                        task = tasks[i]

                t_action = str(task.get("action", "") or "")
                t_params = task.get("params", {}) if isinstance(task.get("params"), dict) else {}
                t_desc = str(task.get("description", "") or f"Adım {i + 1}")
                t_params = self._hydrate_task_params_from_previous(
                    t_action,
                    t_params,
                    previous_output_text,
                )
                result = await self._execute_tool(
                    t_action,
                    t_params,
                    user_input=user_input,
                    step_name=t_desc,
                )
                text = self._format_result_text(result)
                if isinstance(text, str) and text.strip() and not text.lower().startswith("hata:"):
                    previous_output_text = text.strip()
                outputs.append(f"[{i + 1}] {t_desc}\n{text}")
                i += 1
            return "\n\n".join(outputs) if outputs else "Çok adımlı görev için yürütülebilir adım bulunamadı."

        if low_action == "create_coding_project":
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

            outputs: list[str] = []
            create_result: Any
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

            return "\n".join(x for x in outputs if isinstance(x, str) and x.strip()) or "Kod projesi oluşturuldu."

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
        return self._format_result_text(result)

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

    def _hydrate_task_params_from_previous(self, action: str, params: dict, previous_output: str) -> dict:
        clean = dict(params or {})
        prev = str(previous_output or "").strip()
        if not prev:
            return clean

        mapped = ACTION_TO_TOOL.get(str(action or "").strip(), str(action or "").strip())
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

        return clean

    @staticmethod
    def _extract_inline_write_content(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""

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
            return 0.72
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
        elif tool_name == "create_folder":
            clean["path"] = clean.get("path") or "~/Desktop/yeni_klasor"
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
            if not path:
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
                path = f"~/Desktop/{filename}"
                clean["path"] = path

            inline_content = self._extract_inline_write_content(user_input)
            content = clean.get("content")
            if not isinstance(content, str) or not content.strip():
                content = clean.get("text") or clean.get("body") or clean.get("message") or inline_content or ""
            if not isinstance(content, str) or not content.strip():
                if any(tok in user_input.lower() for tok in ("bunu", "dosya olarak", "kaydet", "masaüst")):
                    content = self._get_recent_research_text()
            if not isinstance(content, str) or not content.strip():
                if any(tok in user_input.lower() for tok in ("bunu", "dosya olarak", "kaydet", "masaüst")):
                    content = self._get_recent_assistant_text(user_input)
            if not isinstance(content, str) or not content.strip():
                content = "İçerik belirtilmedi."
            clean["content"] = content
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
                content = self._get_recent_research_text()
            if not isinstance(content, str) or not content.strip():
                content = self._get_recent_assistant_text(user_input)
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
        elif tool_name == "research_document_delivery":
            topic = clean.get("topic") or clean.get("query") or self._extract_topic(user_input, step_name)
            topic = self._sanitize_research_topic(topic, user_input=user_input, step_name=step_name)
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
                low = f"{step_name} {user_input}".lower()
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

            include_word = clean.get("include_word")
            if include_word is None:
                include_word = True
            include_excel = clean.get("include_excel")
            if include_excel is None:
                include_excel = True
            include_report = clean.get("include_report")
            if include_report is None:
                include_report = True

            clean = {
                "topic": topic,
                "brief": str(clean.get("brief") or user_input or "").strip(),
                "depth": depth_map.get(depth, "comprehensive"),
                "audience": str(clean.get("audience") or "executive").strip() or "executive",
                "language": str(clean.get("language") or "tr").strip() or "tr",
                "output_dir": str(clean.get("output_dir") or "~/Desktop").strip() or "~/Desktop",
                "include_word": bool(include_word),
                "include_excel": bool(include_excel),
                "include_report": bool(include_report),
                "source_policy": source_policy,
                "min_reliability": min_rel_value,
                "deliver_copy": bool(clean.get("deliver_copy", False)),
            }
        elif tool_name == "open_url":
            url = clean.get("url", "")
            if not url:
                q = clean.get("query") or self._extract_topic(user_input, step_name)
                if q:
                    url = f"https://www.google.com/search?q={quote_plus(q)}"
            clean["url"] = url
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

    def _format_result_text(self, result: Any) -> str:
        if isinstance(result, dict):
            if result.get("success") is False:
                return f"Hata: {result.get('error', 'İşlem başarısız.')}"

            if isinstance(result.get("summary"), str) and result.get("summary"):
                return result["summary"]

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
