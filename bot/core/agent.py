from typing import Any, Optional
import inspect
import json
import re as _re
import time
from datetime import datetime
from pathlib import Path
from difflib import get_close_matches
from urllib.parse import quote_plus
from core.kernel import kernel
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
from security.validator import validate_input, sanitize_input
from security.privacy_guard import redact_text, sanitize_for_storage, sanitize_object
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
    "run_python": "execute_python_code",
    "show_help": "chat",
    "status_snapshot": "take_screenshot",
    "random_image": "create_visual_asset_pack",
    "create_calendar_event": "create_event",
    "get_calendar": "get_today_events",
    "pause_music": "control_music",
    "resume_music": "control_music",
    "next_track": "control_music",
    "prev_track": "control_music",
    "play_music": "control_music",
    # PDF fallback
    "create_pdf": "generate_document_pack",
    "merge_pdfs": "merge_pdfs",
    # Summary handlers are implemented directly in Agent
    "summarize_text": "summarize_text",
    "summarize_file": "summarize_file",
    "summarize_url": "summarize_url",
    "translate": "translate",
}

# Lazy import to avoid circular dependency
def _push(event_type: str, channel: str, detail: str, success: bool = True):
    try:
        from core.gateway.server import push_activity
        push_activity(event_type, channel, detail, success)
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

    async def initialize(self) -> bool:
        await self.kernel.initialize()
        self.llm = self.kernel.llm
        logger.info("Agent Initialized.")
        return True

    async def process(self, user_input: str, notify=None) -> str:
        started_at = time.perf_counter()

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
        
        # 4. Neural Routing (Role & Complexity Detection)
        route = neural_router.route(user_input)
        role = route["role"]
        logger.info(f"Routed: {role} (complexity: {route['complexity']}) using {route['model']}")

        # Intent parser (deterministic) before chat/planner.
        parsed_intent = self.intent_parser.parse(user_input)
        action_name = str(parsed_intent.get("action", "") or "").lower() if isinstance(parsed_intent, dict) else ""

        if action_name in {"chat", "unknown", ""} and not self._is_likely_chat_message(user_input):
            learned_action = self.learning.quick_match(user_input)
            safe_param_free = {
                "take_screenshot",
                "get_system_info",
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
                llm_intent = await self._infer_llm_tool_intent(user_input, history=history)
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
            direct_text = await self._run_direct_intent(parsed_intent, user_input, role, history)
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
            full_prompt = f"Docs: {context_docs}\n\nUser: {user_input}" if context_docs else user_input
            chat_resp = await self.llm.generate(full_prompt, role=role, history=history)
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
        plan = await self.planner.create_plan(user_input, {})
        
        quality = self.planner.evaluate_plan_quality(getattr(plan, "subtasks", []) or [], user_input)
        if not quality.get("safe_to_run", True):
            if self._is_information_question(user_input):
                full_prompt = f"Docs: {context_docs}\n\nUser: {user_input}" if context_docs else user_input
                try:
                    chat_resp = await self.llm.generate(full_prompt, role=role, history=history)
                except Exception:
                    chat_resp = "Bu soruyu şu an yanıtlayamadım, lütfen tekrar dener misin?"
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
            return "Üzgünüm, bu isteği güvenli bir şekilde planlayamadım."

        final_results = []
        executed_steps = set()
        subtasks = plan.subtasks or []
        pending_steps = list(subtasks)

        # Execution Loop
        while pending_steps and len(executed_steps) < (len(subtasks) + 5):
            # Dependency Resolution
            runnable = [s for s in pending_steps if all(d in executed_steps for d in s.dependencies)]
            if not runnable: break

            for step in runnable:
                # Update Lock
                progress = (len(executed_steps) + 1) / max(len(subtasks), 1)
                action_lock.update_status(progress, step.name)
                
                if notify and step.name != "_chat_":
                    await notify(f"🛠️ {step.name}")

                try:
                    # Execute via Kernel/Registry
                    # Step action name must match registry tool name OR be mapped
                    result = await self._execute_tool(
                        step.action,
                        step.params,
                        user_input=user_input,
                        step_name=step.name,
                    )
                    
                    # Convert result to string for display
                    res_text = self._format_result_text(result)

                    if "Hata:" in res_text:
                        # Simple recovery logic
                        logger.warning(f"Step failed: {res_text}")
                        # Could trigger planner recovery here
                    
                    final_results.append(res_text)
                    executed_steps.add(step.task_id)
                    pending_steps.remove(step)
                except Exception as e:
                    logger.error(f"Execution error ({step.action}): {e}")
                    pending_steps.remove(step)

        if action_lock.is_locked: action_lock.unlock()

        result_str = "\n".join(x for x in final_results if x).strip() or "Görev tamamlandı, ancak görüntülenecek çıktı üretilmedi."
        await self._finalize_turn(
            user_input=user_input,
            response_text=result_str,
            action="multi_step",
            success=bool(final_results),
            started_at=started_at,
            context={"route_role": role, "subtask_count": len(subtasks)},
        )
        _push("task_done", "agent", user_input[:60], success=bool(final_results))
        return status_prefix + result_str

    async def _execute_tool(self, tool_name: str, params: dict, *, user_input: str = "", step_name: str = ""):
        """Execute a tool via the Kernel Registry."""
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

        # Special case: Chat action fallback
        if mapped_tool in ("chat", "respond", "answer"):
            prompt = safe_params.get("message") or user_input
            try:
                result = await self.llm.generate(prompt)
                success = True
                return result
            except Exception as exc:
                err_text = str(exc)
                raise
            finally:
                latency = int((time.perf_counter() - start) * 1000)
                record_tool_usage(used_tool, success=success, latency_ms=latency, source="agent", error=err_text)

        clean_params = self._prepare_tool_params(mapped_tool, clean_params, user_input=user_input, step_name=step_name)

        # Registry Execution
        try:
            result = await self.kernel.tools.execute(mapped_tool, clean_params)
            if isinstance(result, dict) and result.get("success") is False:
                err_text = str(result.get("error", "") or "")
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
            success = not (isinstance(result, dict) and result.get("success") is False)
            if success:
                self._update_file_context_after_tool(mapped_tool, clean_params, result)
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
                logger.error(f"Fallback tool execution error ({mapped_tool}): {e}")
                err_text = str(e)
                return {"success": False, "error": str(e)}
        except Exception as exc:
            err_text = str(exc)
            raise
        finally:
            latency = int((time.perf_counter() - start) * 1000)
            record_tool_usage(used_tool, success=success, latency_ms=latency, source="agent", error=err_text)

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
            if not isinstance(message, str) or not message.strip():
                topic = self._extract_topic(user_input, step_name)
                message = topic if topic and topic != "genel konu" else ""
            return message.strip() if isinstance(message, str) and message.strip() else None

        if name in {"title", "subject", "name"}:
            title = merged.get("title") or merged.get("subject")
            if isinstance(title, str) and title.strip():
                return title.strip()
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

        return None

    def _normalize_param_aliases(self, tool_name: str, params: dict) -> dict:
        """Normalize common planner/LLM parameter aliases into canonical tool params."""
        clean = dict(params or {})
        if tool_name in {"open_app", "close_app"}:
            for key in ("app_name", "appname", "application", "app", "name", "appName"):
                value = clean.get(key)
                if isinstance(value, str) and value.strip():
                    clean["app_name"] = value.strip()
                    break
            for key in ("appname", "application", "app", "name", "appName"):
                clean.pop(key, None)
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

        category = getattr(quick_intent, "category", None)
        if category in (_IC.CHAT, _IC.GREETING):
            return True
        if category == _IC.QUESTION and action in {"", "chat", "show_help", "unknown"}:
            return True
        if action in {"", "chat", "unknown"} and Agent._is_information_question(user_input):
            return True
        return False

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
        if mapped in {"write_file", "write_word", "write_excel"}:
            return self._attach_artifact_verification(result, params, user_input=user_input)
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
        output["verified"] = bool(size_bytes != 0)
        if size_bytes >= 0:
            output["size_bytes"] = int(size_bytes)
        if size_bytes == 0:
            output["verification_warning"] = "çıktı dosyası oluşturuldu ancak boş görünüyor"
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
        if basename:
            roots: list[Path] = []
            last_dir = Path(self._get_last_directory()).expanduser()
            desktop_root = Path.home() / "Desktop"
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

        terminal_cmd = self._extract_terminal_command_from_text(text)
        if terminal_cmd:
            return {
                "action": "run_safe_command",
                "params": {"command": terminal_cmd},
                "reply": f"Terminal komutu çalıştırılıyor: {terminal_cmd}",
            }

        tokens = self._extract_path_like_tokens(text)
        file_match = _re.search(r"([\w\-.]+\.[a-z0-9]{2,8})", text, _re.IGNORECASE)
        file_name = str(file_match.group(1)).strip() if file_match else ""
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
        if (file_name or (references_last and last_path)) and any(m in low for m in delete_markers):
            delete_path = str(last_dir / file_name) if file_name else str(last_path)
            return {
                "action": "delete_file",
                "params": {"path": delete_path, "force": False},
                "reply": f"{(file_name or Path(delete_path).name)} siliniyor...",
            }

        read_markers = ("oku", "içinde ne var", "icinde ne var", "içeriğini göster", "icerigini goster", "ne yazıyor")
        if (file_name or (references_last and last_path)) and any(m in low for m in read_markers):
            read_path = str(last_dir / file_name) if file_name else str(last_path)
            return {
                "action": "read_file",
                "params": {"path": read_path},
                "reply": f"{(file_name or Path(read_path).name)} okunuyor...",
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

    async def _infer_llm_tool_intent(self, user_input: str, *, history: list | None = None) -> Optional[dict[str, Any]]:
        if not self.llm:
            return None

        allow_actions = {
            "list_files", "read_file", "write_file", "delete_file", "search_files",
            "move_file", "copy_file", "rename_file", "create_folder",
            "run_safe_command", "open_app", "close_app", "open_url",
            "web_search", "advanced_research", "take_screenshot", "get_system_info",
            "create_word_document", "create_excel", "send_notification", "create_reminder",
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
            raw = await self.llm.generate(prompt, role="reasoning", history=history or [])
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

    async def _run_direct_intent(self, intent: dict, user_input: str, role: str, history: list) -> str:
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
            return (await self.llm.generate(prompt, role=role, history=history)).strip()

        if low_action == "summarize_url":
            url = params.get("url", "")
            page = await self._execute_tool("fetch_page", {"url": url}, user_input=user_input, step_name="URL fetch")
            if not isinstance(page, dict) or not page.get("success"):
                return self._format_result_text(page)
            content = (page.get("content") or "")[:12000]
            prompt = f"Şu metni kısa ve net şekilde özetle:\n\n{content}"
            return (await self.llm.generate(prompt, role=role, history=history)).strip()

        if low_action == "summarize_file":
            path = params.get("path", "")
            doc = await self._execute_tool("read_file", {"path": path}, user_input=user_input, step_name="Dosya oku")
            if not isinstance(doc, dict) or not doc.get("success"):
                return self._format_result_text(doc)
            content = (doc.get("content") or "")[:12000]
            prompt = f"Aşağıdaki dosya içeriğini özetle:\n\n{content}"
            return (await self.llm.generate(prompt, role=role, history=history)).strip()

        if low_action == "summarize_text":
            text = params.get("text") or user_input
            prompt = f"Bu metni kısa özetle:\n\n{text}"
            return (await self.llm.generate(prompt, role=role, history=history)).strip()

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

        cleaned = _re.sub(r"\s+", " ", cleaned).strip(" .,:;-")
        if len(cleaned) < 2:
            cleaned = self._extract_topic(user_input, step_name)
        return cleaned or "genel konu"

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
                clean["path"] = self._resolve_path_with_desktop_fallback(path, user_input=user_input)
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
                clean["path"] = self._resolve_path_with_desktop_fallback(path, user_input=user_input)
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
        elif tool_name == "open_url":
            url = clean.get("url", "")
            if not url:
                q = clean.get("query") or self._extract_topic(user_input, step_name)
                if q:
                    url = f"https://www.google.com/search?q={quote_plus(q)}"
            clean["url"] = url
        elif tool_name == "run_safe_command":
            command = clean.get("command") or clean.get("cmd") or clean.get("query") or ""
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
            command = clean.get("command")
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
            clean["command"] = command
            if command == "play" and not clean.get("query"):
                clean["query"] = self._extract_topic(user_input, step_name)
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

        return clean

    def _format_result_text(self, result: Any) -> str:
        if isinstance(result, dict):
            if result.get("success") is False:
                return f"Hata: {result.get('error', 'İşlem başarısız.')}"

            if isinstance(result.get("summary"), str) and result.get("summary"):
                return result["summary"]

            if isinstance(result.get("message"), str) and result.get("message"):
                msg = result["message"]
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
