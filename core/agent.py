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
                skill_intent = self._infer_skill_intent(user_input)
                if skill_intent:
                    skill_intent.setdefault("confidence", 0.8)
                    skill_intent.setdefault("source", "skill_fallback")
                    parsed_intent = skill_intent

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
        if (
            quick_intent.category in (_IC.CHAT, _IC.GREETING)
            or (
                quick_intent.category == _IC.QUESTION
                and (not parsed_intent or parsed_intent.get("action") in {"chat", "show_help"})
            )
        ):
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
            if action_lock.is_locked: action_lock.unlock()
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
            success = not (isinstance(result, dict) and result.get("success") is False)
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
                if inspect.iscoroutinefunction(tool_func):
                    result = await tool_func(**clean_params)
                else:
                    result = tool_func(**clean_params)
                success = not (isinstance(result, dict) and result.get("success") is False)
                if isinstance(result, dict) and result.get("success") is False:
                    err_text = str(result.get("error", ""))
                return result
            except Exception as e:
                logger.error(f"Fallback tool execution error ({mapped_tool}): {e}")
                err_text = str(e)
                return {"success": False, "error": str(e)}
        except Exception as exc:
            err_text = str(exc)
            raise
        finally:
            latency = int((time.perf_counter() - start) * 1000)
            record_tool_usage(used_tool, success=success, latency_ms=latency, source="agent", error=err_text)

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
    def _is_multi_step_request(user_input: str) -> bool:
        text = (user_input or "").lower()
        return any(k in text for k in (" ve ", " sonra ", " ardından ", " once ", "önce "))

    @staticmethod
    def _normalize_user_input(user_input: str) -> str:
        text = str(user_input or "").strip()
        if not text:
            return ""
        low = text.lower()
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
            low = _re.sub(pattern, repl, low, flags=_re.IGNORECASE)
        low = " ".join(low.split())
        return low

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
        }
        if any(w in tool_keywords for w in words):
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
            for i, task in enumerate(tasks, start=1):
                if not isinstance(task, dict):
                    continue
                t_action = str(task.get("action", "") or "")
                t_params = task.get("params", {}) if isinstance(task.get("params"), dict) else {}
                t_desc = str(task.get("description", "") or f"Adım {i}")
                result = await self._execute_tool(
                    t_action,
                    t_params,
                    user_input=user_input,
                    step_name=t_desc,
                )
                text = self._format_result_text(result)
                outputs.append(f"[{i}] {t_desc}\n{text}")
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
            clean["path"] = clean.get("path") or "~/Desktop"
        elif tool_name == "search_files":
            clean["pattern"] = clean.get("pattern") or "*"
            clean["directory"] = clean.get("directory") or "~"
        elif tool_name == "create_folder":
            clean["path"] = clean.get("path") or "~/Desktop/yeni_klasor"
        elif tool_name == "read_file":
            path = str(clean.get("path") or "").strip()
            if not path:
                m = _re.search(r"([\w\-.]+\.[a-z0-9]{2,8})", user_input, _re.IGNORECASE)
                if m:
                    path = f"~/Desktop/{m.group(1)}"
            if path:
                clean["path"] = path
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

            content = clean.get("content")
            if not isinstance(content, str) or not content.strip():
                content = clean.get("text") or clean.get("body") or clean.get("message") or ""
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

            content = clean.get("content")
            if not isinstance(content, str) or not content.strip():
                content = clean.get("text") or clean.get("body") or clean.get("message") or ""
            if not isinstance(content, str) or not content.strip():
                content = self._get_recent_assistant_text(user_input)
            if not isinstance(content, str) or not content.strip():
                content = "İçerik belirtilmedi."
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

            data = clean.get("data")
            if not data:
                text_seed = (
                    clean.get("content")
                    or clean.get("text")
                    or clean.get("message")
                    or self._get_recent_assistant_text(user_input)
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
                return result["message"]

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
                return f"İşlem tamamlandı: {result['path']}"

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
