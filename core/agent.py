from typing import Any, Optional
from datetime import datetime
from pathlib import Path
import asyncio
from .llm_client import LLMClient
from .task_executor import TaskExecutor
from .reasoning import ReasoningEngine
from .memory import get_memory
from .context_manager import get_context_manager
from .smart_paths import resolve_path, suggest_path_alternatives
from .tool_health import get_tool_health_manager
from .session_manager import get_session_manager
from .semantic_memory import get_semantic_memory
from .batch_processor import get_batch_processor
from .knowledge_base import get_knowledge_base
from .smart_cache import get_smart_cache
from .request_router import get_request_router
from .connection_pool import get_http_pool
from .learning_engine import get_learning_engine
from .speed_optimizer import get_speed_optimizer
from .advanced_analytics import get_analytics
from .smart_notifications import get_smart_notifications
from .intelligent_planner import get_intelligent_planner
from .predictive_maintenance import get_predictive_maintenance
from .advanced_security import get_advanced_security
from .self_improvement import get_self_improvement
from .fast_response import get_fast_response_system
from .llm_optimizer import get_llm_optimizer
from .response_cache import get_response_cache
from .quick_intent import get_quick_intent_detector
from .response_tone import format_tool_result, format_error_natural
from .user_profile import get_user_profile_store
from .i18n import detect_language
from tools import AVAILABLE_TOOLS
from security.validator import validate_input, sanitize_input
from config.settings import HOME_DIR
from utils.logger import get_logger

logger = get_logger("agent")

# Action -> Tool mapping
ACTION_TO_TOOL = {
    # File operations
    "list_files": "list_files",
    "write_file": "write_file",
    "read_file": "read_file",
    "delete_file": "delete_file",
    "remove_file": "delete_file",
    "search_files": "search_files",
    "find_files": "search_files",
    "move_file": "move_file",
    "tasi": "move_file",
    "dosya_tasi": "move_file",
    "copy_file": "copy_file",
    "kopyala": "copy_file",
    "dosya_kopyala": "copy_file",
    "rename_file": "rename_file",
    "yeniden_adlandir": "rename_file",
    "dosya_adini_degistir": "rename_file",
    "create_folder": "create_folder",
    "klasor_olustur": "create_folder",
    "yeni_klasor": "create_folder",
    "mkdir": "create_folder",
    "create_directory": "create_folder",

    # App control
    "open_app": "open_app",
    "app_control": "open_app",  # Generic app control
    "control_app": "open_app",
    "manage_app": "open_app",
    "open_url": "open_url",
    "close_app": "close_app",
    "quit_app": "close_app",
    "kill_process": "kill_process",
    "get_process_info": "get_process_info",
    "list_processes": "get_process_info",
    "processes": "get_process_info",

    # System tools
    "get_system_info": "get_system_info",
    "system_info": "get_system_info",
    "shutdown_system": "shutdown_system",
    "restart_system": "restart_system",
    "sleep_system": "sleep_system",
    "lock_screen": "lock_screen",
    "run_safe_command": "run_safe_command",
    "run_command": "run_safe_command",
    "terminal": "run_safe_command",
    "execute": "run_safe_command",
    "take_screenshot": "take_screenshot",
    "screenshot": "take_screenshot",
    "read_clipboard": "read_clipboard",
    "clipboard_read": "read_clipboard",
    "write_clipboard": "write_clipboard",
    "clipboard_write": "write_clipboard",
    "set_volume": "set_volume",
    "volume": "set_volume",
    "send_notification": "send_notification",
    "notification": "send_notification",
    "notify": "send_notification",

    # macOS Appearance
    "toggle_dark_mode": "toggle_dark_mode",
    "dark_mode": "toggle_dark_mode",
    "get_appearance": "get_appearance",
    "set_brightness": "set_brightness",
    "brightness": "set_brightness",
    "parlaklık": "set_brightness",
    "parlaklık_aç": "set_brightness",
    "parlaklık_kapat": "set_brightness",
    "get_brightness": "get_brightness",

    # macOS Network
    "wifi_status": "wifi_status",
    "wifi_toggle": "wifi_toggle",
    "wifi_on": "wifi_toggle",
    "wifi_off": "wifi_toggle",
    "bluetooth_status": "bluetooth_status",

    # macOS Calendar & Reminders
    "get_today_events": "get_today_events",
    "today_events": "get_today_events",
    "calendar_events": "get_today_events",
    "create_event": "create_event",
    "add_event": "create_event",
    "get_reminders": "get_reminders",
    "list_reminders": "get_reminders",
    "create_reminder": "create_reminder",
    "add_reminder": "create_reminder",
    "remind": "create_reminder",

    # macOS Spotlight
    "spotlight_search": "spotlight_search",
    "mdfind": "spotlight_search",
    "system_search": "spotlight_search",

    # macOS Preferences
    "get_system_preferences": "get_system_preferences",
    "system_preferences": "get_system_preferences",

    # Office Document Tools
    "read_word": "read_word",
    "write_word": "write_word",
    "read_excel": "read_excel",
    "write_excel": "write_excel",
    "read_pdf": "read_pdf",
    "get_pdf_info": "get_pdf_info",
    "pdf_info": "get_pdf_info",
    "summarize_document": "summarize_document",
    "summarize": "summarize_document",

    # Web Research Tools
    "fetch_page": "fetch_page",
    "web_search": "web_search",
    "search_web": "web_search",
    "internet_search": "web_search",
    "start_research": "start_research",
    "research": "start_research",
    "get_research_status": "get_research_status",
    "research_status": "get_research_status",

    # Advanced AI Tools
    "advanced_research": "advanced_research",
    "deep_research": "advanced_research",
    "comprehensive_research": "advanced_research",
    "smart_summarize": "smart_summarize",
    "intelligent_summary": "smart_summarize",
    "create_smart_file": "create_smart_file",
    "smart_file": "create_smart_file",
    "create_file": "create_smart_file",
    "analyze_document": "analyze_document",
    "document_analysis": "analyze_document",
    "analyze_file": "analyze_document",
    "generate_report": "generate_report",
    "create_report": "generate_report",
    "ai_report": "generate_report",

    # ========================================
    # v3.0 New Actions
    # ========================================

    # Note Taking System
    "create_note": "create_note",
    "yeni_not": "create_note",
    "not_olustur": "create_note",
    "list_notes": "list_notes",
    "notlarim": "list_notes",
    "notlar": "list_notes",
    "my_notes": "list_notes",
    "search_notes": "search_notes",
    "notlarda_ara": "search_notes",
    "not_ara": "search_notes",
    "update_note": "update_note",
    "not_guncelle": "update_note",
    "delete_note": "delete_note",
    "not_sil": "delete_note",
    "get_note": "get_note",
    "not_getir": "get_note",
    "not_oku": "get_note",

    # Task Planning System
    "create_plan": "create_plan",
    "plan_olustur": "create_plan",
    "yeni_plan": "create_plan",
    "execute_plan": "execute_plan",
    "plan_calistir": "execute_plan",
    "plani_yurut": "execute_plan",
    "get_plan_status": "get_plan_status",
    "plan_durumu": "get_plan_status",
    "cancel_plan": "cancel_plan",
    "plan_iptal": "cancel_plan",
    "list_plans": "list_plans",
    "planlar": "list_plans",

    # Document Editing Tools
    "edit_text_file": "edit_text_file",
    "metin_duzenle": "edit_text_file",
    "dosya_duzenle": "edit_text_file",
    "text_edit": "edit_text_file",
    "batch_edit_text": "batch_edit_text",
    "toplu_duzenle": "batch_edit_text",
    "edit_word_document": "edit_word_document",
    "word_duzenle": "edit_word_document",
    "word_edit": "edit_word_document",

    # Document Merging Tools
    "merge_documents": "merge_documents",
    "belge_birlestir": "merge_documents",
    "dosya_birlestir": "merge_documents",
    "merge_pdfs": "merge_pdfs",
    "pdf_birlestir": "merge_pdfs",
    "merge_word_documents": "merge_word_documents",
    "word_birlestir": "merge_word_documents",

    # Advanced Research Tools (v3.0)
    "evaluate_source": "evaluate_source",
    "kaynak_degerlendir": "evaluate_source",
    "quick_research": "quick_research",
    "hizli_arastirma": "quick_research",
    "synthesize_findings": "synthesize_findings",
    "bulgulari_sentezle": "synthesize_findings",
    "sentez": "synthesize_findings",
    "create_research_report": "create_research_report",
    "arastirma_raporu": "create_research_report",
    "rapor_olustur": "create_research_report",

    # Deep Research Engine
    "deep_research": "deep_research",
    "derin_arastirma": "deep_research",
    "cok_kaynakli_arastirma": "deep_research",
    "akademik_arastirma": "deep_research",

    # Document Generator
    "generate_research_document": "generate_research_document",
    "belge_olustur": "generate_research_document",
    "dokuman_olustur": "generate_research_document",
    "rapor_belgesi": "generate_research_document",
}

class Agent:
    def __init__(self):
        self.llm = LLMClient()
        self.executor = TaskExecutor()
        self.ui_app = None  # UI application reference

        # Enhanced capabilities
        self.memory = get_memory()
        self.context_manager = get_context_manager()
        self.user_profiles = get_user_profile_store()
        self.learning = get_learning_engine()
        self.speed = get_speed_optimizer()
        self.analytics = get_analytics()
        self.notifications = get_smart_notifications()
        self.intelligent_planner = get_intelligent_planner()
        self.predictive_maintenance = get_predictive_maintenance()
        self.advanced_security = get_advanced_security()
        self.self_improvement = get_self_improvement()

        # Fast Response Systems (v18.0 - Speed Focus)
        self.fast_response = get_fast_response_system()
        self.llm_optimizer = get_llm_optimizer()
        self.response_cache = get_response_cache()
        self.quick_intent = get_quick_intent_detector()
        self.intelligent_planner = get_intelligent_planner()

        self.reasoning = None  # Will be initialized in initialize()
        self.planner = None  # Will be initialized in initialize()
        self.plan_executor = None  # Will be initialized in initialize()
        self.agent_loop = None  # Legacy path (runtime'da kullanilmiyor)
        
        # Operation modes
        self.autonomous_mode = True  # Can plan and execute multi-step tasks
        self.current_user_id = None  # Set during process()

    def connect_ui(self, ui_app):
        """Connect to UI application for real-time updates"""
        self.ui_app = ui_app
        logger.info("UI bağlantısı kuruldu")

    def disconnect_ui(self):
        """Disconnect from UI application"""
        self.ui_app = None
        logger.info("UI bağlantısı kesildi")

    async def initialize(self) -> bool:
        logger.info("Agent başlatılıyor...")
        
        # 1. Critical Base Systems (Sequential as they are foundational)
        if not await self.llm.check_model():
            logger.error("LLM başlatılamadı")
            return False
        
        from .reasoning import ReasoningEngine
        from .planner import AutonomousPlanner
        from .executor import PlanExecutor
        
        self.reasoning = ReasoningEngine(self.llm, self.executor)
        self.planner = AutonomousPlanner(self.llm, self.reasoning)
        self.plan_executor = PlanExecutor(self.executor)
        logger.info("Temel motorlar hazır")

        # 2. Parallel Background Systems (v17.0 Turbo Startup)
        # v18.0 - Background engine initialization (Serialized to prevent macOS segfaults)
        logger.info("🔧 Arka plan servisleri başlatılıyor...")
        
        try:
            # 1. Tool Health
            await get_tool_health_manager().initialize()
            
            # 2. Session Manager
            await get_session_manager().cleanup_stale_sessions(timeout_minutes=120)
            
            # 3. Semantic Memory (Embedding model loading)
            await get_semantic_memory()
            
            # 4. Knowledge Base
            await get_knowledge_base()
            
            # 5. Connection Pools
            from .connection_pool import initialize_pools
            await initialize_pools()
            
            logger.info("✅ Tüm servisler başarıyla aktif edildi.")
        except Exception as e:
            logger.error(f"❌ Arka plan servisleri başlatılırken hata oluştu: {e}")
            # Non-critical failure, continue

        # Request router and cache are fast/synchronous
        get_smart_cache()
        get_request_router()

        logger.info(" Agent hazır - Autonomous mode active")
        return True

    async def process(self, user_input: str, notify=None) -> str:
        """
        Process user input through the central task engine.
        This is the main entry point for both UI and Telegram bot.
        """
        valid, msg = validate_input(user_input)
        if not valid:
            return f"Hata: {msg}"

        user_input = sanitize_input(user_input)
        logger.info(f"İşleniyor: {user_input[:50]}...")

        # === v18.0 FAST RESPONSE PATH ===
        # Try cache first (instant response)
        cached_response = self.response_cache.get(user_input)
        if cached_response:
            logger.info("Cache hit - instant response")
            return cached_response

        # Try fast response system (no LLM needed)
        fast_result = self.fast_response.get_fast_response(user_input)
        if fast_result:
            logger.info(f"Fast response: {fast_result.response_time*1000:.1f}ms")
            # Cache for future use
            self.response_cache.set(user_input, fast_result.answer, ttl=3600)
            return fast_result.answer

        # Quick intent detection for routing
        quick_intent = self.quick_intent.detect(user_input)
        logger.info(
            f"Intent: {quick_intent.category.value} "
            f"(requires_llm={quick_intent.requires_llm}) -> routed_to=task_engine"
        )

        # UI'ye durum güncellemesi gönder
        if self.ui_app and hasattr(self.ui_app, 'update_status'):
            self.ui_app.update_status(f"İşleniyor: {user_input[:30]}...")

        # Configure notify callback
        notify_callback = notify
        if not notify_callback and self.ui_app and hasattr(self.ui_app, 'notify_thought'):
            notify_callback = self.ui_app.notify_thought

        learning_success = False
        learning_duration_ms = 0
        learning_intent = "UNKNOWN"
        learning_action = "unknown"
        learning_context = {"route": "task_engine"}

        try:
            # Get or initialize task engine
            from .task_engine import get_task_engine
            task_engine = get_task_engine()

            if task_engine.llm is None:
                await task_engine.initialize()

            # Build comprehensive context from context_manager
            context_data = await self.context_manager.build_context(
                user_id=self.current_user_id or 0,
                current_message=user_input,
                include_history=True,
                include_preferences=True,
                include_recent_tasks=False  # Skip for performance
            )

            # Format context for LLM prompt
            formatted_context = self.context_manager.format_context_for_prompt(context_data)

            # Build context dict for task engine
            context = {
                "recent_history": context_data.get("conversation_history", []),
                "user_preferences": context_data.get("user_preferences", {}),
                "formatted_context": formatted_context  # For LLM injection
            }
            profile_summary = self.user_profiles.profile_summary(str(self.current_user_id or "local"))
            context["user_profile"] = profile_summary
            context["user_preferences"] = {
                **context.get("user_preferences", {}),
                "adaptive_profile": profile_summary,
            }

            # Execute task through engine
            task_result = await asyncio.wait_for(
                task_engine.execute_task(
                    user_input=user_input,
                    user_id=self.current_user_id,
                    notify_callback=notify_callback,
                    context=context
                ),
                timeout=90.0
            )

            result = task_result.message
            learning_success = bool(task_result.success)
            learning_duration_ms = int(task_result.execution_time_ms or 0)
            metadata = task_result.metadata or {}
            intent_meta = metadata.get("intent", {}) if isinstance(metadata.get("intent", {}), dict) else {}
            learning_intent = str(intent_meta.get("type", metadata.get("type", "UNKNOWN")))
            learning_action = str(intent_meta.get("action", metadata.get("type", "unknown"))).lower()
            learning_context = {
                "route": "task_engine",
                "meta_type": metadata.get("type"),
                "tasks_executed": metadata.get("tasks_executed", 0),
                "tasks_failed": metadata.get("tasks_failed", 0)
            }

            # Cache successful responses
            if result and not result.startswith("Hata:"):
                complexity = self.llm_optimizer.classify_complexity(user_input)
                ttl_map = {"trivial": 7200, "simple": 3600, "moderate": 1800}
                ttl = ttl_map.get(complexity.value, 3600)
                self.response_cache.set(user_input, result, ttl=ttl, confidence=0.9)

        except asyncio.TimeoutError:
            logger.error(f"Process timeout: {user_input[:30]}")
            from core.error_handler import ErrorHandler
            result = ErrorHandler.format_error_response("İşlem zaman aşımına uğradı")
            learning_success = False
            learning_duration_ms = 90000
            learning_intent = "TIMEOUT"
            learning_action = "timeout"
        except Exception as e:
            logger.error(f"Process error: {e}")
            from core.error_handler import ErrorHandler
            result = ErrorHandler.format_error_response(str(e))
            learning_success = False
            learning_duration_ms = 0
            learning_intent = "ERROR"
            learning_action = "error"

        try:
            await self.learning.record_interaction(
                user_id=str(self.current_user_id or "local"),
                input_text=user_input,
                intent=learning_intent,
                action=learning_action,
                success=learning_success,
                duration_ms=learning_duration_ms,
                context=learning_context
            )
            # Keep lightweight long-term profile for personalization.
            self.user_profiles.update_after_interaction(
                user_id=str(self.current_user_id or "local"),
                language=detect_language(user_input),
                action=learning_action,
                success=learning_success,
                topic_keywords=self._extract_keywords(user_input),
            )
            try:
                self.context_manager.learn_from_interaction(
                    user_id=int(self.current_user_id or 0),
                    user_message=user_input,
                    bot_response={
                        "action": learning_action,
                        "success": learning_success,
                    },
                )
            except Exception as inner_exc:
                logger.debug(f"Context learning error: {inner_exc}")
        except Exception as e:
            logger.debug(f"Learning record error: {e}")

        if self.ui_app and hasattr(self.ui_app, 'add_to_history'):
            self.ui_app.add_to_history(user_input, result)
            self.ui_app.update_status("Hazır")

        return result

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        import re
        words = re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ0-9]{3,}", text.lower())
        stop = {
            "ve", "ile", "icin", "için", "ama", "fakat", "gibi", "kadar", "şimdi", "simdi",
            "this", "that", "with", "from", "your", "about", "please",
        }
        output: list[str] = []
        for w in words:
            if w in stop:
                continue
            if w not in output:
                output.append(w)
        return output[:12]

    async def _execute_single_task(self, response: dict) -> str:
        action = response.get("action")
        message = response.get("message", "")

        tool_name = ACTION_TO_TOOL.get(action)
        if not tool_name or tool_name not in AVAILABLE_TOOLS:
            logger.warning(f"Bilinmeyen action: {action}")
            return message or "Bu işlemi yapamıyorum."

        # Parametreleri hazırla
        params = self._prepare_params(action, response)
        
        # Smart path resolution for file operations
        if "path" in params:
            resolved_path, suggestions = resolve_path(params["path"])
            if resolved_path:
                params["path"] = str(resolved_path)
                logger.info(f"Path resolved: {params['path']}")
            elif suggestions:
                # Path bulunamadı ama öneriler var
                suggestion_text = suggest_path_alternatives(params["path"])
                return f" {suggestion_text}"
        
        # Handle fallback paths if provided
        fallback_paths = response.get("fallback_paths", [])

        logger.info(f"Çalıştırılıyor: {tool_name} -> {params}")

        # Tool'u çalıştır
        tool_func = AVAILABLE_TOOLS[tool_name]
        result = await self.executor.execute(tool_func, params)
        
        # If failed and we have fallback paths, try them
        if not result.get("success") and fallback_paths:
            original_error = result.get("error", "")
            for fallback in fallback_paths:
                resolved_fallback, _ = resolve_path(fallback)
                if resolved_fallback:
                    params["path"] = str(resolved_fallback)
                    logger.info(f"Trying fallback path: {params['path']}")
                    result = await self.executor.execute(tool_func, params)
                    if result.get("success"):
                        logger.info(f"Fallback succeeded: {params['path']}")
                        break
            
            # Still failed? Give helpful message
            if not result.get("success"):
                return f" Bu klasör bulunamadı. Şunları denedim: {', '.join(fallback_paths)}\nÖneri: Spotlight ile arayabilirsin: 'projeler klasörünü ara'"

        # Sonucu formatla
        return self._format_result(action, result, message)

    async def _execute_multi_task(self, response: dict) -> str:
        tasks = response.get("tasks", [])
        message = response.get("message", "Görevler yürütülüyor...")

        if not tasks:
            return "Yapılacak görev bulunamadı."

        results = []
        for i, task in enumerate(tasks, 1):
            action = task.get("action")
            if action == "chat":
                continue

            tool_name = ACTION_TO_TOOL.get(action)
            if not tool_name or tool_name not in AVAILABLE_TOOLS:
                results.append(f" Görev {i}: Bilinmeyen işlem")
                continue

            params = self._prepare_params(action, task)

            logger.info(f"Multi-task {i}/{len(tasks)}: {tool_name}")

            tool_func = AVAILABLE_TOOLS[tool_name]
            result = await self.executor.execute(tool_func, params)

            if result.get("success"):
                results.append(f" Görev {i}: {self._short_result(action, result)}")
            else:
                results.append(f" Görev {i}: {result.get('error', 'Hata')}")

        output = f"{message}\n\n"
        output += "\n".join(results)
        return output

    def _prepare_params(self, action: str, response: dict) -> dict:
        params = {}
        pref_lang = "tr"
        try:
            from config.settings_manager import SettingsPanel
            configured_lang = str(SettingsPanel().get("preferred_language", "auto")).lower()
            if configured_lang in {"tr", "en", "es", "de", "fr", "it", "pt", "ar", "ru"}:
                pref_lang = configured_lang
        except Exception:
            pass

        if action == "list_files":
            params["path"] = response.get("path", str(HOME_DIR / "Desktop"))

        elif action == "write_file":
            params["path"] = response.get("path", str(HOME_DIR / "Desktop" / "not.txt"))
            params["content"] = response.get("content", "")

        elif action == "read_file":
            params["path"] = response.get("path", "")

        elif action in ["delete_file", "remove_file"]:
            params["path"] = response.get("path", "")
            params["force"] = response.get("force", False)

        elif action in ["move_file", "tasi", "dosya_tasi"]:
            params["source"] = response.get("source", response.get("path", response.get("kaynak", "")))
            params["destination"] = response.get("destination", response.get("hedef", ""))

        elif action in ["copy_file", "kopyala", "dosya_kopyala"]:
            params["source"] = response.get("source", response.get("path", response.get("kaynak", "")))
            params["destination"] = response.get("destination", response.get("hedef", ""))

        elif action in ["rename_file", "yeniden_adlandir", "dosya_adini_degistir"]:
            params["path"] = response.get("path", response.get("dosya", ""))
            params["new_name"] = response.get("new_name", response.get("yeni_ad", ""))

        elif action in ["create_folder", "klasor_olustur", "yeni_klasor"]:
            params["path"] = response.get("path", response.get("konum", ""))

        elif action == "open_app":
            params["app_name"] = response.get("app_name", "")

        elif action == "open_url":
            params["url"] = response.get("url", "")

        elif action in ["search_files", "find_files"]:
            params["pattern"] = response.get("pattern", "*")
            params["directory"] = response.get("directory", str(HOME_DIR))

        elif action in ["take_screenshot", "screenshot"]:
            params["filename"] = response.get("filename", None)

        elif action in ["write_clipboard", "clipboard_write"]:
            params["text"] = response.get("text", response.get("content", ""))

        elif action in ["close_app", "quit_app"]:
            params["app_name"] = response.get("app", "")

        elif action in ["shutdown_system", "restart_system", "sleep_system", "lock_screen"]:
            pass

        elif action in ["set_volume", "volume"]:
            if "level" in response:
                params["level"] = response.get("level")
            if "mute" in response:
                params["mute"] = response.get("mute")

        elif action in ["send_notification", "notification", "notify"]:
            params["title"] = response.get("title", "Bot Bildirimi")
            params["message"] = response.get("message", response.get("content", ""))

        elif action in ["kill_process"]:
            params["process_name"] = response.get("process", "")

        elif action in ["get_process_info", "list_processes", "processes"]:
            params["process_name"] = response.get("process", None)

        # macOS Brightness
        elif action in ["set_brightness", "brightness", "parlaklık", "parlaklık_aç", "parlaklık_kapat"]:
            params["level"] = response.get("level", 50)

        elif action == "get_brightness":
            pass  # no params needed

        # macOS WiFi
        elif action in ["wifi_toggle", "wifi_on", "wifi_off"]:
            if action == "wifi_on":
                params["enable"] = True
            elif action == "wifi_off":
                params["enable"] = False
            else:
                params["enable"] = response.get("enable", None)

        # macOS Calendar
        elif action in ["create_event", "add_event"]:
            params["title"] = response.get("title", response.get("event", "Etkinlik"))
            params["start_time"] = response.get("start_time", response.get("time"))
            params["end_time"] = response.get("end_time")
            params["date"] = response.get("date")
            params["notes"] = response.get("notes", "")

        # macOS Reminders
        elif action in ["create_reminder", "add_reminder", "remind"]:
            params["title"] = response.get("title", response.get("reminder", response.get("text", "")))
            params["due_date"] = response.get("due_date", response.get("date"))
            params["due_time"] = response.get("due_time", response.get("time"))
            params["list_name"] = response.get("list", response.get("list_name"))
            params["notes"] = response.get("notes", "")

        elif action in ["get_reminders", "list_reminders"]:
            params["list_name"] = response.get("list", response.get("list_name"))

        # macOS Spotlight
        elif action in ["spotlight_search", "mdfind", "system_search"]:
            params["query"] = response.get("query", response.get("search", ""))
            params["file_type"] = response.get("file_type", response.get("type"))
            params["directory"] = response.get("directory")
            params["limit"] = response.get("limit", 50)

        # Office: Word
        elif action == "read_word":
            params["path"] = response.get("path", "")
            params["max_chars"] = response.get("max_chars", 10000)

        elif action == "write_word":
            params["path"] = response.get("path")
            params["content"] = response.get("content", "")
            params["title"] = response.get("title")
            params["paragraphs"] = response.get("paragraphs")

        # Office: Excel
        elif action == "read_excel":
            params["path"] = response.get("path", "")
            params["sheet_name"] = response.get("sheet", response.get("sheet_name"))
            params["max_rows"] = response.get("max_rows", 100)

        elif action == "write_excel":
            params["path"] = response.get("path")
            params["data"] = response.get("data", [])
            params["headers"] = response.get("headers")
            params["sheet_name"] = response.get("sheet", response.get("sheet_name", "Sheet1"))

        # Office: PDF
        elif action == "read_pdf":
            params["path"] = response.get("path", "")
            params["pages"] = response.get("pages")
            params["max_chars"] = response.get("max_chars", 15000)

        elif action in ["get_pdf_info", "pdf_info"]:
            params["path"] = response.get("path", "")

        # Office: Summarize
        elif action in ["summarize_document", "summarize"]:
            params["path"] = response.get("path")
            params["content"] = response.get("content")
            params["style"] = response.get("style", "brief")

        # Web: Fetch Page
        elif action == "fetch_page":
            params["url"] = response.get("url", "")
            params["extract_content"] = response.get("extract_content", True)

        # Web: Search
        elif action in ["web_search", "search_web", "internet_search"]:
            params["query"] = response.get("query", response.get("search", ""))
            params["num_results"] = response.get("num_results", 5)
            params["language"] = response.get("language", pref_lang)

        # Web: Research
        elif action in ["start_research", "research"]:
            params["topic"] = response.get("topic", response.get("query", ""))
            params["depth"] = response.get("depth", "basic")

        elif action in ["get_research_status", "research_status"]:
            params["task_id"] = response.get("task_id", "")

        # ========================================
        # v3.0 New Actions - Parameter Preparation
        # ========================================

        # Note Taking System
        elif action in ["create_note", "yeni_not", "not_olustur"]:
            params["title"] = response.get("title", response.get("baslik", ""))
            params["content"] = response.get("content", response.get("icerik", ""))
            params["tags"] = response.get("tags", response.get("etiketler", []))
            params["category"] = response.get("category", response.get("kategori", "general"))

        elif action in ["list_notes", "notlarim", "notlar", "my_notes"]:
            params["category"] = response.get("category", response.get("kategori"))
            params["tags"] = response.get("tags", response.get("etiketler"))
            params["limit"] = response.get("limit", 50)

        elif action in ["search_notes", "notlarda_ara", "not_ara"]:
            params["query"] = response.get("query", response.get("sorgu", response.get("arama", "")))
            params["search_in"] = response.get("search_in", "all")
            params["category"] = response.get("category")
            params["limit"] = response.get("limit", 20)

        elif action in ["update_note", "not_guncelle"]:
            params["note_id"] = response.get("note_id", response.get("not_id", response.get("id", "")))
            params["title"] = response.get("title", response.get("baslik"))
            params["content"] = response.get("content", response.get("icerik"))
            params["tags"] = response.get("tags", response.get("etiketler"))
            params["category"] = response.get("category", response.get("kategori"))
            params["append"] = response.get("append", response.get("ekle", False))

        elif action in ["delete_note", "not_sil"]:
            params["note_id"] = response.get("note_id", response.get("not_id", response.get("id", "")))
            params["permanent"] = response.get("permanent", response.get("kalici", False))

        elif action in ["get_note", "not_getir", "not_oku"]:
            params["note_id"] = response.get("note_id", response.get("not_id", response.get("id", "")))

        # Task Planning System
        elif action in ["create_plan", "plan_olustur", "yeni_plan"]:
            params["name"] = response.get("name", response.get("ad", "Plan"))
            params["description"] = response.get("description", response.get("aciklama", ""))
            params["tasks"] = response.get("tasks", response.get("gorevler", []))
            params["execution_mode"] = response.get("execution_mode", response.get("mod", "sequential"))

        elif action in ["execute_plan", "plan_calistir", "plani_yurut"]:
            params["plan_id"] = response.get("plan_id", response.get("plan_id", ""))

        elif action in ["get_plan_status", "plan_durumu"]:
            params["plan_id"] = response.get("plan_id", "")

        elif action in ["cancel_plan", "plan_iptal"]:
            params["plan_id"] = response.get("plan_id", "")

        elif action in ["list_plans", "planlar"]:
            params["include_completed"] = response.get("include_completed", False)

        # Document Editing Tools
        elif action in ["edit_text_file", "metin_duzenle", "dosya_duzenle", "text_edit"]:
            params["path"] = response.get("path", response.get("dosya", ""))
            params["operations"] = response.get("operations", response.get("islemler", []))
            params["create_backup"] = response.get("create_backup", response.get("yedek", True))

        elif action in ["batch_edit_text", "toplu_duzenle"]:
            params["directory"] = response.get("directory", response.get("dizin", ""))
            params["pattern"] = response.get("pattern", response.get("desen", "*.txt"))
            params["operations"] = response.get("operations", response.get("islemler", []))
            params["create_backup"] = response.get("create_backup", True)
            params["recursive"] = response.get("recursive", False)

        elif action in ["edit_word_document", "word_duzenle", "word_edit"]:
            params["path"] = response.get("path", response.get("dosya", ""))
            params["operations"] = response.get("operations", response.get("islemler", []))
            params["create_backup"] = response.get("create_backup", True)

        # Document Merging Tools
        elif action in ["merge_documents", "belge_birlestir", "dosya_birlestir"]:
            params["input_paths"] = response.get("input_paths", response.get("dosyalar", response.get("files", [])))
            params["output_path"] = response.get("output_path", response.get("cikti", response.get("output", "")))
            params["output_format"] = response.get("output_format", response.get("format", "auto"))

        elif action in ["merge_pdfs", "pdf_birlestir"]:
            params["input_paths"] = response.get("input_paths", response.get("dosyalar", response.get("files", [])))
            params["output_path"] = response.get("output_path", response.get("cikti", response.get("output", "")))
            params["page_ranges"] = response.get("page_ranges", response.get("sayfa_araliklari"))

        elif action in ["merge_word_documents", "word_birlestir"]:
            params["input_paths"] = response.get("input_paths", response.get("dosyalar", response.get("files", [])))
            params["output_path"] = response.get("output_path", response.get("cikti", response.get("output", "")))

        # Advanced Research Tools (v3.0)
        elif action in ["advanced_research", "deep_research", "comprehensive_research"]:
            params["topic"] = response.get("topic", response.get("konu", ""))
            params["depth"] = response.get("depth", response.get("derinlik", "standard"))
            params["sources"] = response.get("sources", response.get("kaynaklar"))
            params["language"] = response.get("language", response.get("dil", pref_lang))
            params["include_evaluation"] = response.get("include_evaluation", True)

        elif action in ["evaluate_source", "kaynak_degerlendir"]:
            params["url"] = response.get("url", "")
            params["criteria"] = response.get("criteria", response.get("kriterler"))

        elif action in ["quick_research", "hizli_arastirma"]:
            params["topic"] = response.get("topic", response.get("konu", ""))
            params["max_sources"] = response.get("max_sources", 3)

        elif action in ["synthesize_findings", "bulgulari_sentezle", "sentez"]:
            params["research_id"] = response.get("research_id", response.get("arastirma_id"))
            params["findings"] = response.get("findings", response.get("bulgular"))
            params["sources"] = response.get("sources", response.get("kaynaklar"))
            params["synthesis_type"] = response.get("synthesis_type", response.get("sentez_tipi", "summary"))

        elif action in ["create_research_report", "arastirma_raporu", "rapor_olustur"]:
            params["topic"] = response.get("topic", response.get("konu", ""))
            params["research_id"] = response.get("research_id", response.get("arastirma_id"))
            params["findings"] = response.get("findings", response.get("bulgular"))
            params["sources"] = response.get("sources", response.get("kaynaklar"))
            params["output_format"] = response.get("output_format", response.get("format", "markdown"))
            params["output_path"] = response.get("output_path", response.get("cikti"))
            params["include_sources"] = response.get("include_sources", True)

        # Deep Research Engine
        elif action in ["deep_research", "derin_arastirma", "cok_kaynakli_arastirma", "akademik_arastirma"]:
            params["topic"] = response.get("topic", response.get("konu", ""))
            params["depth"] = response.get("depth", response.get("derinlik", "standard"))
            params["language"] = response.get("language", response.get("dil", pref_lang))
            params["focus_areas"] = response.get("focus_areas", response.get("odak_alanlari"))
            params["include_academic"] = response.get("include_academic", response.get("akademik_dahil", True))

        # Document Generator
        elif action in ["generate_research_document", "belge_olustur", "dokuman_olustur", "rapor_belgesi"]:
            params["research_data"] = response.get("research_data", response.get("arastirma_verisi", {}))
            params["format"] = response.get("format", response.get("format", "docx"))
            params["template"] = response.get("template", response.get("sablon", "research_report"))
            params["custom_title"] = response.get("custom_title", response.get("baslik"))
            params["language"] = response.get("language", response.get("dil", pref_lang))

        return params

    def _short_result(self, action: str, result: dict) -> str:
        if action == "list_files":
            count = len(result.get("items", []))
            return f"{count} öğe listelendi"
        elif action == "write_file":
            return f"Dosya oluşturuldu"
        elif action in ["delete_file", "remove_file"]:
            return f"Dosya/klasör silindi"
        elif action == "open_app":
            return f"{result.get('app', 'Uygulama')} açıldı"
        elif action == "open_url":
            return "URL açıldı"
        elif action == "get_system_info":
            return "Sistem bilgisi alındı"
        elif action in ["take_screenshot", "screenshot"]:
            return "Screenshot alındı"
        elif action in ["read_clipboard", "clipboard_read"]:
            return "Pano okundu"
        elif action in ["write_clipboard", "clipboard_write"]:
            return "Panoya kopyalandı"
        elif action in ["close_app", "quit_app"]:
            return f"{result.get('app', 'Uygulama')} kapatıldı"
        elif action == "shutdown_system":
            return "Sistem kapatma komutu gönderildi"
        elif action == "restart_system":
            return "Sistem yeniden başlatma komutu gönderildi"
        elif action == "sleep_system":
            return "Sistem uyku moduna alındı"
        elif action == "lock_screen":
            return "Ekran kilitlendi"
        elif action in ["set_volume", "volume"]:
            return "Ses ayarlandı"
        elif action in ["send_notification", "notification", "notify"]:
            return "Bildirim gönderildi"
        elif action in ["search_files", "find_files"]:
            count = len(result.get("matches", []))
            return f"{count} dosya bulundu"
        elif action == "kill_process":
            return f"Process sonlandırıldı"
        elif action in ["get_process_info", "list_processes", "processes"]:
            count = result.get("count", 0)
            return f"{count} process listelendi"
        elif action in ["run_safe_command", "run_command", "terminal", "execute"]:
            return f"Komut çalıştırıldı"
        # macOS tools
        elif action in ["set_brightness", "brightness", "parlaklık", "parlaklık_aç", "parlaklık_kapat"]:
            return f"Parlaklık %{result.get('level', 0)}"
        elif action == "get_brightness":
            return f"Parlaklık %{result.get('level', 0)}"
        elif action in ["toggle_dark_mode", "dark_mode"]:
            mode = result.get("mode", "")
            return f"{mode} mod aktif"
        elif action in ["wifi_toggle", "wifi_on", "wifi_off"]:
            return result.get("action", "WiFi değiştirildi")
        elif action == "wifi_status":
            return f"WiFi: {'açık' if result.get('wifi_on') else 'kapalı'}"
        elif action in ["get_today_events", "today_events", "calendar_events"]:
            count = result.get("count", 0)
            return f"{count} etkinlik listelendi"
        elif action in ["create_event", "add_event"]:
            return f"Etkinlik oluşturuldu"
        elif action in ["get_reminders", "list_reminders"]:
            count = result.get("count", 0)
            return f"{count} anımsatıcı listelendi"
        elif action in ["create_reminder", "add_reminder", "remind"]:
            return f"Anımsatıcı oluşturuldu"
        elif action in ["spotlight_search", "mdfind", "system_search"]:
            count = result.get("count", 0)
            return f"{count} sonuç bulundu"
        # Office tools
        elif action == "read_word":
            return f"Word dosyası okundu"
        elif action == "write_word":
            return f"Word dosyası oluşturuldu"
        elif action == "read_excel":
            count = result.get("row_count", 0)
            return f"{count} satır okundu"
        elif action == "write_excel":
            count = result.get("row_count", 0)
            return f"{count} satır yazıldı"
        elif action == "read_pdf":
            pages = result.get("pages_read", 0)
            return f"{pages} sayfa okundu"
        elif action in ["get_pdf_info", "pdf_info"]:
            return "PDF bilgisi alındı"
        elif action in ["summarize_document", "summarize"]:
            return "Belge özetlendi"
        # Web tools
        elif action == "fetch_page":
            return "Sayfa içeriği alındı"
        elif action in ["web_search", "search_web", "internet_search"]:
            count = result.get("count", 0)
            return f"{count} sonuç bulundu"
        elif action in ["start_research", "research"]:
            return "Araştırma başlatıldı"
        elif action in ["get_research_status", "research_status"]:
            status = result.get("status", "bilinmiyor")
            return f"Durum: {status}"

        # v3.0 New Actions - Short Results
        # Note Taking
        elif action in ["create_note", "yeni_not", "not_olustur"]:
            return f"Not oluşturuldu: {result.get('title', '')}"
        elif action in ["list_notes", "notlarim", "notlar", "my_notes"]:
            count = result.get("count", 0)
            return f"{count} not listelendi"
        elif action in ["search_notes", "notlarda_ara", "not_ara"]:
            count = result.get("count", 0)
            return f"{count} not bulundu"
        elif action in ["update_note", "not_guncelle"]:
            return f"Not güncellendi"
        elif action in ["delete_note", "not_sil"]:
            return f"Not silindi"
        elif action in ["get_note", "not_getir", "not_oku"]:
            return f"Not getirildi"

        # Task Planning
        elif action in ["create_plan", "plan_olustur", "yeni_plan"]:
            return f"Plan oluşturuldu: {result.get('name', '')}"
        elif action in ["execute_plan", "plan_calistir", "plani_yurut"]:
            return f"Plan tamamlandı"
        elif action in ["get_plan_status", "plan_durumu"]:
            return f"Durum: {result.get('status', '')}"
        elif action in ["cancel_plan", "plan_iptal"]:
            return f"Plan iptal edildi"
        elif action in ["list_plans", "planlar"]:
            count = result.get("count", 0)
            return f"{count} plan listelendi"

        # Document Editing
        elif action in ["edit_text_file", "metin_duzenle", "dosya_duzenle"]:
            return f"Dosya düzenlendi"
        elif action in ["batch_edit_text", "toplu_duzenle"]:
            count = result.get("modified_count", 0)
            return f"{count} dosya düzenlendi"
        elif action in ["edit_word_document", "word_duzenle"]:
            return f"Word düzenlendi"

        # Document Merging
        elif action in ["merge_documents", "belge_birlestir", "dosya_birlestir"]:
            return f"Belgeler birleştirildi"
        elif action in ["merge_pdfs", "pdf_birlestir"]:
            pages = result.get("total_pages", 0)
            return f"PDF birleştirildi: {pages} sayfa"
        elif action in ["merge_word_documents", "word_birlestir"]:
            return f"Word dosyaları birleştirildi"

        # Advanced Research v3.0
        elif action in ["evaluate_source", "kaynak_degerlendir"]:
            return f"Kaynak değerlendirildi"
        elif action in ["quick_research", "hizli_arastirma"]:
            return f"Hızlı araştırma tamamlandı"
        elif action in ["synthesize_findings", "bulgulari_sentezle"]:
            return f"Bulgular sentezlendi"
        elif action in ["create_research_report", "arastirma_raporu"]:
            return f"Araştırma raporu oluşturuldu"

        # Deep Research Engine
        elif action in ["deep_research", "derin_arastirma", "cok_kaynakli_arastirma", "akademik_arastirma"]:
            source_count = result.get("statistics", {}).get("total_sources", 0)
            return f"Derin araştırma tamamlandı: {source_count} kaynak"

        # Document Generator
        elif action in ["generate_research_document", "belge_olustur", "dokuman_olustur", "rapor_belgesi"]:
            filename = result.get("filename", "")
            return f"Belge oluşturuldu: {filename}"

        return "Tamamlandı"

    def _format_result(self, action: str, result: dict, message: str) -> str:
        """Delegates to centralized response_tone.format_tool_result"""
        return format_tool_result(action, result)

    @staticmethod
    def _normalize_tr(text: str) -> str:
        """Turkce karakterleri ASCII'ye donustur (esleme icin)"""
        tr_map = str.maketrans('çğıöşüÇĞİÖŞÜ', 'cgiosuCGIOSU')
        return text.translate(tr_map)

    def _is_likely_chat(self, text: str) -> bool:
        """UNKNOWN intent'ler icin ek sohbet tespiti.
        quick_intent yakalayamadigi ama tool da olmayan mesajlari tespit eder."""
        import re
        t = text.lower().strip()
        tn = self._normalize_tr(t)  # ASCII-normalized version
        words = tn.split()

        # Tool keyword kontrolu - word-prefix matching ile
        # (substring yerine, 'al' gibi kisa keyword'lerin 'valla' icinde eslesmemesi icin)
        tool_prefixes = {
            'ac', 'kapat', 'kis', 'yukselt', 'sil', 'oku', 'yaz',
            'bul', 'tara', 'indir', 'yukle', 'calistir', 'gonder',
            'olustur', 'listele', 'goster', 'screenshot', 'dosya',
            'klasor', 'hatirlat', 'arastir', 'research', 'kopyala', 'tasi',
            'open', 'close', 'delete', 'search', 'find', 'send',
            'volume', 'ses', 'parlaklik', 'wifi', 'bluetooth', 'ekran',
            'kaydet', 'yedekle', 'azalt', 'artir', 'dusur',
        }
        has_tool = any(
            word.startswith(prefix) and (len(word) - len(prefix)) <= 5
            for word in words
            for prefix in tool_prefixes
            if len(prefix) >= 3  # 3+ char prefix = safe word-prefix match
        )
        # Short exact-match keywords (2 chars) - only match full words
        short_tool_words = {'ac', 'ss', 'al'}
        if not has_tool:
            has_tool = any(word in short_tool_words for word in words)
        if has_tool:
            return False

        # Kisa mesajlar (1-6 kelime) tool keyword icermiyorsa → chat
        if len(words) <= 6:
            return True

        # Soru kaliplari (tool icermeyen)
        if t.endswith('?'):
            return True
        if re.search(r'^(ne|nasil|neden|kim|nerede|hangi|kac)', tn):
            return True

        # Genel konusma kaliplari
        chat_signals = [
            'bilmiyorum', 'bilmem', 'fikrim yok', 'emin degil',
            'merak ettim', 'sormak', 'soyler misin', 'anlatir misin',
            'dusunuyorum', 'sanirim', 'galiba', 'herhalde', 'bence',
            'senin fikrin', 'ne dersin', 'ne diyorsun', 'sence',
            'ilginc', 'enteresan', 'vay', 'aaa', 'hmm', 'valla',
        ]
        if any(s in tn for s in chat_signals):
            return True

        return False

    async def shutdown(self):
        """Comprehensive shutdown - cleanup all resources"""
        logger.info("🔴 Agent shutdown başlatılıyor...")

        try:
            # 1. Stop background schedulers first
            try:
                from core.proactive import get_scheduler
                scheduler = get_scheduler()
                if hasattr(scheduler, 'shutdown'):
                    await scheduler.shutdown()
                    logger.info("✓ Scheduler durduruldu")
            except Exception as e:
                logger.debug(f"Scheduler shutdown error: {e}")

            # 2. Close LLM client
            try:
                if hasattr(self.llm, 'close'):
                    await self.llm.close()
                    logger.info("✓ LLM client kapatıldı")
            except Exception as e:
                logger.debug(f"LLM close error: {e}")

            # 3. Shutdown connection pools
            try:
                from core.connection_pool import get_http_pool
                pool = get_http_pool()
                if hasattr(pool, 'close'):
                    await pool.close()
                    logger.info("✓ Connection pool kapatıldı")
            except Exception as e:
                logger.debug(f"Pool close error: {e}")

            # 4. Cleanup model manager (sentence transformers)
            try:
                from core.model_manager import _manager
                _manager._model = None
                logger.info("✓ Model manager temizlendi")
            except Exception as e:
                logger.debug(f"Model cleanup error: {e}")

            # 5. Flush caches
            try:
                if hasattr(self.response_cache, 'clear'):
                    self.response_cache.clear()
                logger.info("✓ Cache temizlendi")
            except Exception as e:
                logger.debug(f"Cache clear error: {e}")

            # 6. Save learning data
            try:
                if hasattr(self.learning, 'save'):
                    self.learning.save()
                logger.info("✓ Learning data kaydedildi")
            except Exception as e:
                logger.debug(f"Learning save error: {e}")

            # 7. Close databases
            try:
                if hasattr(self.memory, 'close'):
                    self.memory.close()
                logger.info("✓ Memory database kapatıldı")
            except Exception as e:
                logger.debug(f"Memory close error: {e}")

            logger.info("✅ Agent tamamen kapatıldı")

        except Exception as e:
            logger.error(f"Shutdown error: {e}", exc_info=True)
