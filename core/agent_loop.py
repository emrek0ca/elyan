import asyncio
import json
import re
import time
from typing import Dict, Any, Optional, List
from .state_model import AgentState, Goal, TaskStep, GoalStatus, StepStatus
from .llm_client import LLMClient
from .task_executor import TaskExecutor
from .memory import get_memory
from security.audit import get_audit_logger
from security.approval import get_approval_manager, RiskLevel
from .intent_parser import IntentParser
from .error_handler import ErrorHandler, ErrorCategory
from .tool_health import get_tool_health_manager
from .session_manager import get_session_manager
from .semantic_memory import get_semantic_memory
from .request_router import get_request_router
from .smart_cache import get_smart_cache
from .monitoring import get_monitoring, record_tool_execution, record_operation, record_error
from .advanced_features import (
    get_streaming_processor,
    get_parallel_executor,
    get_suggestion_engine,
    get_context_enricher,
    get_anomaly_detector
)
from tools import AVAILABLE_TOOLS
from .reasoning import ReasoningEngine
from .planner import AutonomousPlanner
from .path_memory import get_path_memory
from utils.logger import get_logger
from .response_tone import natural_response, get_varied_greeting, format_tool_result, format_error_natural
from .fuzzy_intent import get_fuzzy_matcher
from .fast_response import get_fast_response_system
from .self_healing import get_self_healing

logger = get_logger("agent_loop")

class AgentLoop:
    def __init__(self, llm_client: LLMClient, executor: TaskExecutor):
        self.llm = llm_client
        self.executor = executor
        self.state: Optional[AgentState] = None
        self.audit = get_audit_logger()
        self.approval = get_approval_manager()
        self.memory = get_memory()
        self.session_manager = get_session_manager()
        self.current_user_id = None  # Set during process call
        self.current_session_id = None  # Track current session
        self.intent_parser = IntentParser()
        # Initialize Intelligence Engines
        self.reasoning = ReasoningEngine(self.llm, self.executor)
        self.planner = AutonomousPlanner(self.llm, self.reasoning)
        self.tools_info = self._get_tools_info()
        self.plan_adaptations = 0  # Track adaptation count to prevent loops
        self.path_memory = get_path_memory()
        self.self_healing = get_self_healing()

        # Initialize advanced features
        self.streaming_processor = get_streaming_processor()
        self.parallel_executor = get_parallel_executor()
        self.suggestion_engine = get_suggestion_engine()
        self.context_enricher = get_context_enricher()
        self.anomaly_detector = get_anomaly_detector()
        self.fuzzy_matcher = get_fuzzy_matcher()
        self.fast_response = get_fast_response_system()

        # Initialize learning and speed optimization
        from .learning_engine import get_learning_engine
        from .speed_optimizer import get_speed_optimizer
        from .context_intelligence import get_context_intelligence
        self.learning = get_learning_engine()
        self.speed = get_speed_optimizer()
        self.context_intelligence = get_context_intelligence()
        logger.info("Intelligence, speed, and self-healing systems initialized in agent loop")

    def _get_fast_path(self, user_input: str) -> Optional[List[TaskStep]]:
        """Directly map common colloquialisms to tool steps to skip LLM latency."""
        input_clean = user_input.lower().strip()

        # PHASE 1: Check learning engine for previously learned patterns
        learned_action = self.learning.quick_match(input_clean)
        if learned_action:
            logger.info(f"Learning engine match: '{input_clean}' -> {learned_action}")
            # Convert learned action to TaskStep
            from tools import AVAILABLE_TOOLS
            if learned_action in AVAILABLE_TOOLS:
                return [TaskStep(
                    id="learned_step_1",
                    description=f"Öğrenilmiş: {user_input}",
                    tool_name=learned_action,
                    params={},
                    verification="işlem tamam"
                )]

        # PHASE 2: Normalize common Turkish grammar particles
        input_clean = input_clean.replace(" yi ", " ").replace(" yı ", " ")
        input_clean = input_clean.replace(" i ", " ").replace(" ı ", " ")
        input_clean = input_clean.replace("lütfen", "").replace("please", "")
        input_clean = input_clean.replace("şimdi", "").replace("now", "")
        input_clean = " ".join(input_clean.split())  # Remove extra spaces

        # PHASE 3: Auto-complete partial commands (prevent LLM timeout)
        import re
        partial_completions = {
            r'^(safari|chrome|firefox|terminal|finder|notlar|notes)\s+[aakç]': r'\1 aç',
            r'^(vscode|code|visual studio)\s+[aakç]': 'vscode aç',
            r'^ss\s+[al]': 'ss al',
            r'^ekran\s+[gö]': 'ekran görüntüsü al',
            r'^sesı?\s+[ka]': 'sesi kapat' if 'k' in input_clean else 'sesi aç',
        }

        for pattern, replacement in partial_completions.items():
            if re.match(pattern, input_clean):
                input_clean = re.sub(pattern, replacement, input_clean)
                logger.info(f"Fast path auto-complete: '{user_input}' -> '{input_clean}'")
                break

        # PHASE 3.5: Fuzzy Intent Matcher (New in v18.0)
        fuzzy_match = self.fuzzy_matcher.match(user_input)
        if fuzzy_match and fuzzy_match.confidence >= 0.75:
            logger.info(f"Fuzzy fast match: '{user_input}' -> {fuzzy_match.tool} (conf={fuzzy_match.confidence})")
            return [TaskStep(
                id="fuzzy_step_1",
                description=f"Fuzzy Match: {user_input}",
                tool_name=fuzzy_match.tool,
                params=fuzzy_match.params,
                verification="işlem tamam"
            )]

        # PHASE 4: Massive Fast Path Mapping (100+ commands)
        mapping = {
            "ss al": ("take_screenshot", {}),
            "ss": ("take_screenshot", {}),
            "ekran görüntüsü al": ("take_screenshot", {}),
            "safari aç": ("open_app", {"app_name": "Safari"}),
            "safari": ("open_app", {"app_name": "Safari"}),
            "chrome aç": ("open_app", {"app_name": "Google Chrome"}),
            "chrome": ("open_app", {"app_name": "Google Chrome"}),
            "firefox aç": ("open_app", {"app_name": "Firefox"}),
            "firefox": ("open_app", {"app_name": "Firefox"}),
            "terminal aç": ("open_app", {"app_name": "Terminal"}),
            "terminal": ("open_app", {"app_name": "Terminal"}),
            "finder aç": ("open_app", {"app_name": "Finder"}),
            "finder": ("open_app", {"app_name": "Finder"}),
            "notları aç": ("open_app", {"app_name": "Notes"}),
            "notlar": ("open_app", {"app_name": "Notes"}),
            "hesap makinesi": ("open_app", {"app_name": "Calculator"}),
            "sesi kapat": ("set_volume", {"mute": True}),
            "ses kapat": ("set_volume", {"mute": True}),
            "sessize al": ("set_volume", {"mute": True}),
            "sessiz yap": ("set_volume", {"mute": True}),
            "mute": ("set_volume", {"mute": True}),
            "sesi aç": ("set_volume", {"mute": False}),
            "ses aç": ("set_volume", {"mute": False}),
            "unmute": ("set_volume", {"mute": False}),
            "sesi kıs": ("set_volume", {"level": 30}),
            "ses kıs": ("set_volume", {"level": 30}),
            "sesi azalt": ("set_volume", {"level": 30}),
            "sesi düşür": ("set_volume", {"level": 30}),
            "sesi yükselt": ("set_volume", {"level": 70}),
            "sesi artır": ("set_volume", {"level": 70}),
            "sesi arttır": ("set_volume", {"level": 70}),
            "ses yükselt": ("set_volume", {"level": 70}),
            "sistem bilgisi": ("get_system_info", {}),
            "wifi durumu": ("wifi_status", {}),
            "dark mode": ("toggle_dark_mode", {}),
            "karanlık mod": ("toggle_dark_mode", {}),
            "parlaklığı aç": ("set_brightness", {"level": 75}),
            "parlaklık aç": ("set_brightness", {"level": 75}),
            "parlaklığı kapat": ("set_brightness", {"level": 10}),
            "parlaklık kapat": ("set_brightness", {"level": 10}),
            "parlaklık": ("get_brightness", {}),

            # Additional apps (70+ new entries)
            "vscode": ("open_app", {"app_name": "Visual Studio Code"}),
            "vscode aç": ("open_app", {"app_name": "Visual Studio Code"}),
            "code": ("open_app", {"app_name": "Visual Studio Code"}),
            "code aç": ("open_app", {"app_name": "Visual Studio Code"}),
            "krom": ("open_app", {"app_name": "Google Chrome"}),
            "krom aç": ("open_app", {"app_name": "Google Chrome"}),
            "slack": ("open_app", {"app_name": "Slack"}),
            "slack aç": ("open_app", {"app_name": "Slack"}),
            "discord": ("open_app", {"app_name": "Discord"}),
            "discord aç": ("open_app", {"app_name": "Discord"}),
            "spotify": ("open_app", {"app_name": "Spotify"}),
            "spotify aç": ("open_app", {"app_name": "Spotify"}),
            "music": ("open_app", {"app_name": "Music"}),
            "music aç": ("open_app", {"app_name": "Music"}),
            "müzik": ("open_app", {"app_name": "Music"}),
            "müzik aç": ("open_app", {"app_name": "Music"}),
            "iterm": ("open_app", {"app_name": "iTerm"}),
            "iterm aç": ("open_app", {"app_name": "iTerm"}),
            "zoom": ("open_app", {"app_name": "zoom.us"}),
            "zoom aç": ("open_app", {"app_name": "zoom.us"}),
            "teams": ("open_app", {"app_name": "Microsoft Teams"}),
            "teams aç": ("open_app", {"app_name": "Microsoft Teams"}),
            "word": ("open_app", {"app_name": "Microsoft Word"}),
            "word aç": ("open_app", {"app_name": "Microsoft Word"}),
            "excel": ("open_app", {"app_name": "Microsoft Excel"}),
            "excel aç": ("open_app", {"app_name": "Microsoft Excel"}),
            "powerpoint": ("open_app", {"app_name": "Microsoft PowerPoint"}),
            "powerpoint aç": ("open_app", {"app_name": "Microsoft PowerPoint"}),
            "outlook": ("open_app", {"app_name": "Microsoft Outlook"}),
            "outlook aç": ("open_app", {"app_name": "Microsoft Outlook"}),
            "mail": ("open_app", {"app_name": "Mail"}),
            "mail aç": ("open_app", {"app_name": "Mail"}),
            "posta aç": ("open_app", {"app_name": "Mail"}),
            "mesajlar": ("open_app", {"app_name": "Messages"}),
            "mesajları aç": ("open_app", {"app_name": "Messages"}),
            "mail aç": ("open_app", {"app_name": "Mail"}),
            "takvim": ("open_app", {"app_name": "Calendar"}),
            "takvim aç": ("open_app", {"app_name": "Calendar"}),
            "calendar": ("open_app", {"app_name": "Calendar"}),
            "calendar aç": ("open_app", {"app_name": "Calendar"}),
            "photos": ("open_app", {"app_name": "Photos"}),
            "photos aç": ("open_app", {"app_name": "Photos"}),
            "fotoğraflar": ("open_app", {"app_name": "Photos"}),
            "fotoğraflar aç": ("open_app", {"app_name": "Photos"}),
            "mesajlar": ("open_app", {"app_name": "Messages"}),
            "mesajlar aç": ("open_app", {"app_name": "Messages"}),
            "messages": ("open_app", {"app_name": "Messages"}),
            "messages aç": ("open_app", {"app_name": "Messages"}),
            "facetime": ("open_app", {"app_name": "FaceTime"}),
            "facetime aç": ("open_app", {"app_name": "FaceTime"}),
            "preview": ("open_app", {"app_name": "Preview"}),
            "preview aç": ("open_app", {"app_name": "Preview"}),
            "textedit": ("open_app", {"app_name": "TextEdit"}),
            "textedit aç": ("open_app", {"app_name": "TextEdit"}),
            "ayarlar": ("open_app", {"app_name": "System Preferences"}),
            "ayarlar aç": ("open_app", {"app_name": "System Preferences"}),
            "settings": ("open_app", {"app_name": "System Preferences"}),
            "görev yöneticisi": ("open_app", {"app_name": "Activity Monitor"}),
            "activity monitor": ("open_app", {"app_name": "Activity Monitor"}),

            # URL shortcuts (20+ new entries)
            "google": ("open_url", {"url": "https://google.com"}),
            "google aç": ("open_url", {"url": "https://google.com"}),
            "youtube": ("open_url", {"url": "https://youtube.com"}),
            "youtube aç": ("open_url", {"url": "https://youtube.com"}),
            "gmail": ("open_url", {"url": "https://mail.google.com"}),
            "gmail aç": ("open_url", {"url": "https://mail.google.com"}),
            "github": ("open_url", {"url": "https://github.com"}),
            "github aç": ("open_url", {"url": "https://github.com"}),
            "twitter": ("open_url", {"url": "https://twitter.com"}),
            "twitter aç": ("open_url", {"url": "https://twitter.com"}),
            "instagram": ("open_url", {"url": "https://instagram.com"}),
            "instagram aç": ("open_url", {"url": "https://instagram.com"}),
            "linkedin": ("open_url", {"url": "https://linkedin.com"}),
            "linkedin aç": ("open_url", {"url": "https://linkedin.com"}),
            "facebook": ("open_url", {"url": "https://facebook.com"}),
            "facebook aç": ("open_url", {"url": "https://facebook.com"}),
            "reddit": ("open_url", {"url": "https://reddit.com"}),
            "reddit aç": ("open_url", {"url": "https://reddit.com"}),
            "chatgpt": ("open_url", {"url": "https://chat.openai.com"}),
            "chatgpt aç": ("open_url", {"url": "https://chat.openai.com"}),
            "claude": ("open_url", {"url": "https://claude.ai"}),
            "claude aç": ("open_url", {"url": "https://claude.ai"}),
            "drive": ("open_url", {"url": "https://drive.google.com"}),
            "drive aç": ("open_url", {"url": "https://drive.google.com"}),
            "maps": ("open_url", {"url": "https://maps.google.com"}),
            "maps aç": ("open_url", {"url": "https://maps.google.com"}),
            "harita": ("open_url", {"url": "https://maps.google.com"}),
            "harita aç": ("open_url", {"url": "https://maps.google.com"}),
            "translate": ("open_url", {"url": "https://translate.google.com"}),
            "çeviri": ("open_url", {"url": "https://translate.google.com"}),
            "çeviri aç": ("open_url", {"url": "https://translate.google.com"}),
        }
        
        # Consolidate Phase 4 & 5 (Mapping + Fuzzy)
        if input_clean in mapping:
            tool, params = mapping[input_clean]
            return [TaskStep(
                id="fast_step_1",
                description=f"Hızlı Geçiş: {user_input}",
                tool_name=tool,
                params=params,
                verification="işlem tamam"
            )]

        # PHASE 5: Fuzzy Intent Matching (Legacy block, consolidated into Phase 3.5 above)
        return None

    def _get_tools_info(self) -> str:
        """Returns a formatted string of tools with their technical names and concise descriptions."""
        important_tools = [
            ("open_app", "app_name: str (Örn: 'Safari', 'Notes')"),
            ("open_url", "url: str (Örn: 'google.com')"),
            ("take_screenshot", "filename: str (opsiyonel)"),
            ("list_files", "path: str (Örn: '.')"),
            ("read_file", "path: str"),
            ("write_file", "path: str, content: str"),
            ("delete_file", "path: str"),
            ("move_file", "source: str, destination: str"),
            ("copy_file", "source: str, destination: str"),
            ("search_files", "pattern: str, directory: str (Örn: '*.txt', 'Desktop')"),
            ("get_system_info", ""),
            ("set_volume", "level: int (0-100)"),
        ]
        return "\n".join([f"- {name}({params})" for name, params in important_tools])

    async def process(self, user_input: str, notify=None) -> str:
        """Main entry point for processing user input"""
        self.notify = notify
        logger.info(f"Processing input: {user_input}")

        # === LEVEL 0: FAST RESPONSE (Greetings, Simple Questions) ===
        fast_resp = self.fast_response.get_fast_response(user_input)
        if fast_resp:
            logger.info(f"FastResponse Level 0 hit: {fast_resp.question_type}")
            self.memory.store_conversation(self.current_user_id, user_input, {"action": "fast_chat", "message": fast_resp.answer})
            return fast_resp.answer

        # === INTENT GATING ===
        intent_type, parsed_intent = await self._gate_intent(user_input)

        # CHAT path - minimal overhead, respond fast
        if intent_type == "CHAT":
            logger.info("CHAT path - fast response")
            # Lightweight context (only recent conversations, skip heavy enrichment)
            context = {}
            try:
                semantic_mem = await get_semantic_memory()
                relevant = await semantic_mem.find_relevant(user_input, top_k=1)
                if relevant:
                    context["semantically_similar"] = [
                        {"input": c.user_input, "response": c.bot_response}
                        for c in relevant
                    ]
            except Exception:
                pass

            response = await self._handle_chat(user_input, context)
            self.memory.store_conversation(self.current_user_id, user_input, {"action": "chat", "message": response})

            # Store in semantic memory (background, don't block)
            try:
                semantic_mem = await get_semantic_memory()
                await semantic_mem.add_conversation(
                    user_input=user_input,
                    bot_response=response,
                    metadata={"user_id": self.current_user_id, "type": "chat"}
                )
            except Exception:
                pass

            return response

        # === ACTION PATH: Full processing with all middleware ===
        # 0. Session management
        if self.current_user_id:
            try:
                session = await self.session_manager.get_user_session(self.current_user_id)
                if not session:
                    session = await self.session_manager.create_session(self.current_user_id)
                elif session.status == "crashed":
                    await self.session_manager.recover_session(session.session_id)

                self.current_session_id = session.session_id
                await self.session_manager.update_session(
                    session.session_id,
                    current_operation=user_input[:50],
                    total_steps=0
                )
            except Exception as e:
                logger.warning(f"Session management error: {e}")

        # 1. Get context from memory and semantic search
        recent_convs = self.memory.get_recent_conversations(self.current_user_id, limit=5)
        context = {"recent_history": recent_convs}

        try:
            semantic_mem = await get_semantic_memory()
            relevant_conversations = await semantic_mem.find_relevant(user_input, top_k=2)
            if relevant_conversations:
                context["semantically_similar"] = [
                    {"input": c.user_input, "response": c.bot_response}
                    for c in relevant_conversations
                ]
        except Exception:
            pass

        # 1.5 Enrich context (only for ACTION path)
        try:
            recent_commands = [c[1] for c in recent_convs] if recent_convs else []
            user_preferences = self.memory.get_user_preferences(self.current_user_id) or {}
            enriched_context = await self.context_enricher.enrich_context(
                user_input,
                recent_commands,
                user_preferences
            )
            context.update(enriched_context)
        except Exception as e:
            logger.warning(f"Context enrichment error: {e}")

        # 2. Fast Path Check
        fast_plan = self._get_fast_path(user_input)
        if fast_plan:
            logger.info("Fast path triggered")
            self.state = AgentState(current_goal=Goal(intent="fast_action", definition=user_input, success_criteria=["done"]))
            self.state.plan = fast_plan
            return await self._run_loop()

        # 3. Full Planning Path (Goal + Plan in one go if possible)
        # Reuse parsed intent instead of re-parsing
        goal = await self._formulate_goal(user_input, context, parsed_intent=parsed_intent)
        self.state = AgentState(current_goal=goal)

        # === LEVEL 1: AUTONOMOUS SOLVING (v20.0) ===
        # If the task is complex or involves "autonomous" intent, use ReAct solving
        if self._is_autonomous_required(user_input, goal):
            logger.info("Triggering autonomous solving mode (v20.0)")
            return await self._solve_autonomously(user_input, context)

        # 4. Planning (Linear fallback)
        plan = await self._create_plan(goal, context)
        self.state.plan = plan

        if not plan:
            # Plan oluşturulamadı → muhtemelen sohbet mesajı, LLM chat'e yönlendir
            logger.info(f"Empty plan for: {goal.definition} → chat fallback")
            return await self._handle_chat(user_input, context)

        # 5. Execution Loop
        import time
        start_time = time.time()
        result = await self._run_loop()
        duration_ms = int((time.time() - start_time) * 1000)

        # 6. Learning & Speed Optimization & Context Intelligence
        # Record interaction for learning
        if self.state and self.state.plan:
            success = self.state.current_goal.status == GoalStatus.ACHIEVED
            intent = self.state.current_goal.intent
            action = self.state.plan[0].tool_name if self.state.plan else "unknown"

            await self.learning.record_interaction(
                user_id=self.current_user_id or "anonymous",
                input_text=user_input,
                intent=intent,
                action=action,
                success=success,
                duration_ms=duration_ms,
                context={"session": self.current_session_id},
                feedback=None
            )

            # Record for context intelligence (pattern learning)
            await self.context_intelligence.record_action(
                action=action,
                context={
                    "success": success,
                    "duration_ms": duration_ms,
                    "intent": intent
                },
                user_id=self.current_user_id or "anonymous"
            )

            # Record analytics metrics
            from .advanced_analytics import get_analytics
            analytics = get_analytics()
            analytics.record_timing(f"tool_{action}", duration_ms)
            analytics.increment_counter(f"tool_{action}_executions")
            if success:
                analytics.increment_counter(f"tool_{action}_success")
            else:
                analytics.increment_counter(f"tool_{action}_failures")

            # Cache successful results for speed
            if success and duration_ms > 1000:  # Only cache slow operations
                cache_key = f"{user_input.lower().strip()}:{action}"
                self.speed.cache_result(cache_key, result, ttl=1800)  # 30 min cache

        # Store conversation in semantic memory
        semantic_mem = await get_semantic_memory()
        await semantic_mem.add_conversation(
            user_input=user_input,
            bot_response=result,
            metadata={
                "user_id": self.current_user_id,
                "session_id": self.current_session_id
            }
        )

        return result

    def _is_autonomous_required(self, user_input: str, goal: Goal) -> bool:
        """Heuristics to determine if autonomous/recursive solving is needed"""
        autonomous_keywords = ["bul ve", "tara ve", "arştır ve", "incele ve", "çöz", "hallet", "yap ve bana haber ver"]
        if any(kw in user_input.lower() for kw in autonomous_keywords):
            return True
        
        # Complex multi-step requests
        if self._is_compound_request(user_input):
            return True
            
        return False

    async def _solve_autonomously(self, user_input: str, context: Dict) -> str:
        """Use ReActAgent for recursive, multi-step autonomous solving"""
        if self.notify:
            await self.notify("🔄 Stratejik Otonom Mod Aktif: Görevi analiz ediyorum...")
        
        try:
            # Solve using the reasoning engine's ReAct capability
            result = await self.reasoning.react.solve(user_input)
            
            if result.get("success"):
                final_result = result.get("final_result", {})
                if isinstance(final_result, dict) and final_result.get("success"):
                    self.state.current_goal.status = GoalStatus.ACHIEVED
                    return await self.reasoning.generate_execution_report(user_input, result.get("iterations", []))
                else:
                    return f"İşlem tamamlandı ancak beklenen sonuç alınamadı: {final_result.get('error', 'Bilinmeyen hata')}"
            else:
                # Fallback to normal planning if autonomy fails
                logger.warning("Autonomous solving failed, falling back to standard plan")
                plan = await self._llm_plan(self.state.current_goal)
                self.state.plan = plan
                return await self._run_loop()
                
        except Exception as e:
            logger.error(f"Autonomous solving error: {e}")
            return f"Otonom çözüm sırasında bir hata oluştu: {str(e)}"

    async def _gate_intent(self, user_input: str, context: Optional[Dict] = None):
        """Classify user input as ACTION or CHAT.
        Returns: (intent_type: str, parsed_intent: dict|None)
        """
        input_lower = user_input.lower().strip()

        # 1. Ultra-fast path: Greetings, thanks, polite closures
        greetings = [
            "selam", "merhaba", "hey", "hi", "hello", "günaydın", "iyi akşamlar", "iyi geceler", 
            "sa", "as", "mrb", "naber", "nasılsın", "ne haber", "ne var ne yok",
            "teşekkür", "sağol", "eyvallah", "tşk", "saol", "eyv", "sağolasın",
            "tamam", "ok", "anladım", "peki", "tamamdır", "olur", "valla", "hadi",
            "iyi", "güzel", "süper", "harika", "mükemmel", "naber", "napıyorsun"
        ]
        if any(g == input_lower or input_lower.startswith(g + " ") or input_lower.startswith(g + ",") for g in greetings):
            return "CHAT", None

        # 2. Action keywords - tool tetikleyicileri
        action_keywords = [
            "aç", "kapat", "sil", "yaz", "oluştur", "ekran görüntüsü", "screenshot", "ss al",
            "dosya", "klasör", "indir", "yükle", "kopyala", "taşı", "ara ", "bul ", "listele",
            "wifi", "parlaklık", "ses", "volume", "dark mode", "karanlık mod", "araştır",
            "özetle", "analiz", "rapor", "belge", "yazdır", "hatırlat", "takvim",
            "kıs", "yükselt", "azalt", "artır", "düşür", "kaydet", "yedekle",
        ]
        has_action_keyword = any(kw in input_lower for kw in action_keywords)

        # 3. Fast path check - massive mapping'de varsa kesinlikle ACTION
        fast_plan = self._get_fast_path(user_input)
        if fast_plan:
            return "ACTION", None

        # 3.5 Eger action keyword varsa once IntentParser'a sor
        if has_action_keyword:
            result = self.intent_parser.parse(user_input)
            if result and result.get('action') and result['action'] != 'chat':
                return "ACTION", result
            # Action keyword var ama parser cozemedi → yine de ACTION olarak dene
            return "ACTION", result

        # 4. Try IntentParser (Rule-based detection)
        result = self.intent_parser.parse(user_input)
        if result and result.get('action') and result['action'] != 'chat':
            return "ACTION", result

        # 5. Check for questions / informational queries (CHAT)
        question_keywords = [
            "nedir", "ne demek", "ne anlama", "neden", "niçin", "kim", "kime",
            "nerede", "ne zaman", "hangi", "kaç", "nasıl olur", "ne işe yarar",
            "kimdir", "anlat", "bilgi ver", "hakkında", "tarif et"
        ]
        is_question = any(q in input_lower for q in question_keywords) or input_lower.endswith("?")

        # "Sesi nasıl açarım" → ACTION, "Hava nasıl" → CHAT
        if "nasıl" in input_lower:
            action_context = ["aç", "kapat", "sil", "yaz", "yap", "ayar", "sistem", "wifi", "ses", "parlaklık"]
            if any(ac in input_lower for ac in action_context):
                is_question = False

        if is_question:
            if not any(input_lower.endswith(kw) for kw in ["aç", "sil", "yap", "bul", "getir"]):
                return "CHAT", None

        # 6. Default fallback for short messages (up to 4 words without tool keywords)
        word_count = len(input_lower.split())
        if word_count <= 4 and not has_action_keyword:
            return "CHAT", None

        # 7. IntentParser'in 'chat' dedigine güven
        if result and result.get('action') == 'chat':
            return "CHAT", None

        # 8. Tool keyword yoksa ve uzun mesajsa → CHAT (konuşma dili)
        if not has_action_keyword:
            return "CHAT", None

        # Default: ACTION
        return "ACTION", result

    async def _handle_chat(self, user_input: str, context: Optional[Dict] = None) -> str:
        """Selamlaşma ve basit sorulara doğrudan yanıt ver.
        Uses LLM.chat() for direct text response - no JSON parsing overhead."""
        input_lower = user_input.lower().strip()

        # Instant responses - no LLM needed for common fillers
        if any(word in input_lower for word in ["selam", "merhaba", "hey", "hi", "hello", "sa", "as", "mrb"]):
            return get_varied_greeting()

        if any(word in input_lower for word in ["teşekkür", "sağol", "eyvallah", "tşk", "saol", "eyv", "sağolasın"]):
            return natural_response("thanks_reply")

        if any(word in input_lower for word in ["günaydın", "iyi akşamlar", "iyi geceler"]):
            return get_varied_greeting()

        if input_lower in ["tamam", "ok", "peki", "anladım", "tamamdır", "olur"]:
            return natural_response("acknowledge")

        # Build context for richer answers
        context_hint = ""
        if context and context.get("semantically_similar"):
            similar = context["semantically_similar"][:1]
            if similar:
                input_ex = similar[0].get('input', '')
                resp_ex = similar[0].get('response', '')
                context_hint = f"\n\nBenzer geçmiş konuşma:\nKullanıcı: {input_ex}\nWiqo: {resp_ex}"

        # System prompt for Wiqo persona
        system_prompt = (
            "Wiqo, akıllı, samimi ve profesyonel bir Türkçe asistan. "
            "Kullanıcının sorusuna doğrudan, doğal ve kısa bir cevap ver. "
            "Gereksiz teknik detaylardan kaçın, arkadaşça bir ton kullan. "
            "Sadece Türkçe konuş. Emojiler KULLANMA. "
            f"{context_hint}"
        )

        try:
            # Use LLM.chat() which handles Groq/Gemini/Ollama prioritization
            response = await asyncio.wait_for(
                self.llm.chat(user_input, system_prompt=system_prompt),
                timeout=12.0
            )
            
            if response and len(response.strip()) > 1:
                return response.strip()
            
            return "Anlayamadım, tekrar eder misin?"

        except asyncio.TimeoutError:
            return "Yanıt vermem biraz sürüyor, internet bağlantını kontrol eder misin?"
        except Exception as e:
            logger.error(f"Chat execution failed: {e}")
            return "Bir hata oluştu, lütfen tekrar deneyin."

    async def _formulate_goal(self, user_input: str, context: Optional[Dict] = None, parsed_intent: Optional[Dict] = None) -> Goal:
        """IntentParser ile goal oluştur. Reuse parsed_intent if provided (caching optimization)"""
        # Use provided parsed intent if available (caching optimization to avoid re-parsing)
        parsed = parsed_intent or self.intent_parser.parse(user_input)

        if parsed and parsed.get("action"):
            return Goal(
                intent=parsed.get("action"),
                definition=user_input,
                params=parsed.get("params", {}),
                success_criteria=[f"{parsed.get('action')}_completed"],
                status=GoalStatus.PENDING
            )

        # Fallback goal
        return Goal(
            intent="generic",
            definition=user_input,
            params={},
            success_criteria=["completed"],
            status=GoalStatus.PENDING
        )

    def _is_compound_request(self, text: str) -> bool:
        """Birden fazla intent içerip içermediğini kontrol"""
        connectors = [" ve ", " and ", " sonra ", " then ", " ayrıca ", " also ", " bunun yanı sıra "]
        return any(c in text.lower() for c in connectors)

    async def _create_plan(self, goal: Goal, context: Optional[Dict] = None) -> List[TaskStep]:
        """Plan oluştur — basit tek-adım: rule-based (hızlı), birleşik/bilinmeyen: LLM"""
        from core.agent import ACTION_TO_TOOL

        action = ACTION_TO_TOOL.get(goal.intent, goal.intent)

        # Birleşik istek ("X ve Y", "X sonra Y") → LLM ile çok-adım plan
        if self._is_compound_request(goal.definition):
            return await self._llm_plan(goal)

        # Basit tek-adım: tool varsa doğrudan çalıştır
        if action in AVAILABLE_TOOLS:
            return [TaskStep(
                id="step_1",
                description=goal.definition,
                tool_name=action,
                params=goal.params,
                verification="işlem tamamlandı",
                status=StepStatus.PENDING
            )]

        # Tool bulunamadı → LLM ile plan yap
        return await self._llm_plan(goal)

    async def _llm_plan(self, goal: Goal) -> List[TaskStep]:
        """v19.2: Tek LLM cagrisiyla plan olustur.
        AutonomousPlanner bypass - CoT overhead yok, token tasarrufu."""
        from core.agent import ACTION_TO_TOOL

        # Son kullanilan dosyalar
        recent_paths = ", ".join(self.path_memory.get_recent_paths(limit=3)) or "yok"

        prompt = f"""Gorev: "{goal.definition}"

Araclar:
  open_app(app_name), close_app(app_name), open_url(url)
  take_screenshot(filename?), list_files(path), read_file(path)
  write_file(path,content), delete_file(path), move_file(source,dest)
  copy_file(source,dest), rename_file(path,new_name), create_folder(path)
  search_files(pattern,directory), set_volume(level|mute)
  set_brightness(level), get_system_info(), wifi_status(), wifi_toggle()
  toggle_dark_mode(), web_search(query), advanced_research(topic,depth)
  create_note(title,content), create_reminder(title,due_time)
  get_today_events(), send_notification(title,message)
  read_clipboard(), write_clipboard(content), spotlight_search(query)
  send_email(to,subject,body), get_unread_emails()
  read_word(path), read_pdf(path), smart_summarize(text|path)
  create_smart_file(type,title,content,path), run_safe_command(command)

Son dosyalar: {recent_paths}

KURALLAR:
- SADECE yukaridaki arac isimlerini kullan
- Dosya yolu yoksa Desktop varsay
- Tek islem yeterliyse tek adim
- Maksimum 5 adim, sohbet icin bos dizi []

JSON (baska bir sey YAZMA):
[{{"step":1,"tool":"arac","params":{{}},"desc":"aciklama"}}]"""

        try:
            raw = await asyncio.wait_for(
                self.llm._ask_llm_with_custom_prompt(prompt, temperature=0.05),
                timeout=15.0
            )

            steps: List[TaskStep] = []
            match = re.search(r'\[[\s\S]*?\]', raw)
            if match:
                try:
                    plan_data = json.loads(match.group())
                    for i, s in enumerate(plan_data[:5]):  # Max 5 adim
                        tool = s.get("tool", "").split("(")[0].strip()
                        if not tool:
                            continue
                        resolved = ACTION_TO_TOOL.get(tool, tool)
                        if resolved in AVAILABLE_TOOLS:
                            steps.append(TaskStep(
                                id=f"step_{i + 1}",
                                description=s.get("desc", f"Adim {i + 1}"),
                                tool_name=resolved,
                                params=s.get("params", {}),
                                verification="islem tamamlandi",
                                status=StepStatus.PENDING
                            ))
                except json.JSONDecodeError as je:
                    logger.error(f"LLM plan JSON parse: {je}")

            return steps
        except asyncio.TimeoutError:
            logger.error("LLM plan timeout (15s)")
            return []
        except Exception as e:
            logger.error(f"LLM plan hatasi: {e}")
            return []

    async def _run_loop(self) -> str:
        if not self.state:
            return "Hata: AgentState baslatilmadi."

        self.state.current_goal.status = GoalStatus.IN_PROGRESS
        MAX_RETRIES_PER_STEP = 1       # v19.2: Max 1 retry (dongu onleme)
        RETRY_BACKOFF_BASE = 0.3
        MAX_TOTAL_ITERATIONS = 15      # v19.2: Hard loop guard
        total_iterations = 0

        while self.state.current_step_index < len(self.state.plan):
            total_iterations += 1
            if total_iterations > MAX_TOTAL_ITERATIONS:
                logger.error(f"Hard loop guard: {MAX_TOTAL_ITERATIONS} iterasyon asildi")
                self.state.current_goal.status = GoalStatus.FAILED
                return "Islem cok uzun surdu, iptal edildi."
            # Check for cancellation request
            if self.state.should_cancel:
                logger.info("Operation cancelled by user")
                self.state.current_goal.status = GoalStatus.FAILED
                return "Islem iptal edildi."

            step = self.state.get_current_step()
            logger.info(f"Executing step {step.id}: {step.description} (attempt {step.retry_count + 1}/{MAX_RETRIES_PER_STEP + 1})")

            # Step progress notification (Chief of Staff persona)
            if self.notify and len(self.state.plan) > 1:
                total = len(self.state.plan)
                idx = self.state.current_step_index + 1
                # Fluid, context-aware status updates
                status_patterns = {
                    "advanced_research": "Stratejim doğrultusunda derinlemesine verileri sentezliyorum",
                    "web_search": "Gerekli kaynaklar için ağ taraması yapıyorum",
                    "read_file": f"İlgili dosyayı ({step.params.get('path', 'belge')}) analiz ediyorum",
                    "write_file": "Elde edilen sonuçları raporlaştırıyorum",
                    "take_screenshot": "Sistem durumunu görsel olarak doğruluyorum",
                    "summarize_document": "Belge içeriğini stratejik bir özete dönüştürüyorum"
                }
                status_text = status_patterns.get(step.tool_name, step.description)
                
                # Live Reasoning Integration: Peek into the thought process
                if step.observation: # Using previous observation or current intent
                     await self.notify(f" *Stratejik Düşünce:* Mevcut veriler {step.description} adımını gerektiriyor.")
                     
                await self.notify(f"[{idx}/{total}] {status_text}...")

            step.status = StepStatus.RUNNING

            # AUDIT: Start of step
            start_time = asyncio.get_event_loop().time()

            # SAFETY: Granular Risk Scoring (Ultra-Security v12.0)
            from security.validator import calculate_risk_score
            risk_score = calculate_risk_score(step.tool_name, step.params)
            logger.info(f"Step {step.id} Risk Score: {risk_score}")

            # Determine risk level from score
            if risk_score >= 95:
                risk_level = RiskLevel.CRITICAL
            elif risk_score >= 70:
                risk_level = RiskLevel.HIGH
            elif risk_score >= 40:
                risk_level = RiskLevel.MEDIUM
            else:
                risk_level = RiskLevel.LOW

            if risk_score >= 95:
                # Critical risk: Blocked
                logger.error(f"Critical risk operation blocked: {step.tool_name} (Score: {risk_score})")
                return f"Bu islemi guvenlik nedeniyle yapamiyorum: {step.description}"

            if risk_score >= 70:
                # High risk: Approval required
                logger.warning(f"High-risk operation detected: {step.tool_name}. Requesting approval...")
                step.status = StepStatus.AWAITING_APPROVAL

                # Request approval from user
                approval_result = await self.approval.request_approval(
                    operation=step.tool_name,
                    risk_level=risk_level,
                    description=step.description,
                    params=step.params,
                    user_id=self.current_user_id,
                    timeout=30
                )

                if not approval_result.get("approved"):
                    logger.error(f"High-risk operation {step.tool_name} rejected or timed out")
                    return f"{step.description} islemi reddedildi."

                logger.info(f"High-risk operation {step.tool_name} approved")

            # ACT
            try:
                # Send progress for long operations
                long_ops = ['advanced_research', 'web_search', 'summarize_document',
                           'analyze_document', 'read_pdf', 'read_word']
                if step.tool_name in long_ops:
                    await self._send_progress(f"{step.description}...")

                # Record start time for metrics
                exec_start = time.time()
                result = await self._execute_tool(step.tool_name, step.params)
                exec_duration = (time.time() - exec_start) * 1000  # Convert to ms
                step.result = result

                # Record tool execution metrics
                success = result.get("success", False) if isinstance(result, dict) else True
                record_tool_execution(
                    step.tool_name,
                    success,
                    exec_duration,
                    params_hash=hash(str(step.params))
                )

                # Visual Verification for system state changes
                state_changing_ops = ['open_app', 'open_url', 'write_file', 'write_clipboard', 'set_volume', 'toggle_dark_mode']
                if step.tool_name in state_changing_ops and success:
                    try:
                        # Take autonomous screenshot for proof
                        ss_result = await self._execute_tool("take_screenshot", {"filename": f"proof_{step.id}.png"})
                        if ss_result.get("success") and self.notify:
                            await self.notify({
                                "type": "screenshot",
                                "path": ss_result.get("path"),
                                "message": f"Stratejik doğrulama: {step.description} tamamlandı."
                            })
                    except:
                        pass

                # OBSERVE & VERIFY
                is_verified = await self._verify_step(step)

                # AUDIT: End of step
                duration = asyncio.get_event_loop().time() - start_time
                self.audit.log_operation(
                    user_id=self.current_user_id,
                    operation=step.tool_name,
                    action=step.description,
                    params=step.params,
                    result=result,
                    success=is_verified,
                    duration=duration,
                    risk_level=risk_level.value
                )

                if is_verified:
                    # Success: move to next step
                    step.status = StepStatus.COMPLETED
                    self.state.current_step_index += 1
                    step.retry_count = 0
                else:
                    # Verification failed: handle retry
                    step.status = StepStatus.FAILED

                    if step.retry_count >= MAX_RETRIES_PER_STEP:
                        # Max retries exceeded: skip this step and continue
                        logger.warning(f"Step {step.id} max retry ({MAX_RETRIES_PER_STEP}) exceeded, skipping")
                        self.state.current_step_index += 1
                    else:
                        # Try to adapt and retry
                        should_retry = await self._handle_step_failure(step)
                        if should_retry:
                            # Increment retry counter and retry this step
                            step.retry_count += 1
                            step.status = StepStatus.PENDING
                            logger.info(f"Retrying step {step.id} (retry {step.retry_count}/{MAX_RETRIES_PER_STEP})")
                            # Loop will pick up the same step again
                        else:
                            # No retry suggested: skip to next step
                            logger.info(f"Step {step.id} failed and no retry suggested, moving to next step")
                            self.state.current_step_index += 1

            except Exception as e:
                error_msg = str(e)
                error_type = type(e).__name__
                logger.error(f"Step execution error ({error_type}): {error_msg}")
                
                # SELF-HEALING: Record error and trigger potential fixes
                self.self_healing.record_error(
                    error_type=error_type,
                    error_message=error_msg,
                    context={"tool": step.tool_name, "params": step.params}
                )
                
                step.status = StepStatus.FAILED
                step.result = {"success": False, "error": error_msg}
                step.retry_count += 1

                # Record error in monitoring
                record_error(step.tool_name, error_msg, "tool_execution_error")

                # Categorize and log error
                category = ErrorHandler.categorize_error(error_msg, step.tool_name)
                should_retry = ErrorHandler.should_retry(category) and step.retry_count < MAX_RETRIES_PER_STEP

                if should_retry:
                    # Exponential backoff before retry
                    backoff_seconds = RETRY_BACKOFF_BASE * (2 ** (step.retry_count - 1))
                    logger.info(f"Retrying step {step.id} due to {category.value} in {backoff_seconds:.1f}s (retry {step.retry_count}/{MAX_RETRIES_PER_STEP})")

                    # Notify user of retry attempt
                    if self.notify:
                        await self._send_progress(f" {step.description} yeniden denenecek ({int(backoff_seconds)}s sonra)")

                    await asyncio.sleep(backoff_seconds)
                    step.status = StepStatus.PENDING
                else:
                    # Max retries exceeded or non-retriable error
                    logger.error(f"Step {step.id} failed with {category.value} after {step.retry_count} retries")
                    self.state.current_step_index += 1

        # 5. Final Verification
        is_goal_achieved = await self._verify_goal()

        if is_goal_achieved:
            self.state.current_goal.status = GoalStatus.ACHIEVED
            outcome = "Success"
        else:
            self.state.current_goal.status = GoalStatus.FAILED
            outcome = "Failed final verification"

        # Record in memory
        self.memory.store_task(
            user_id=self.current_user_id,
            goal=self.state.current_goal.definition,
            plan=[{"desc": s.description, "status": s.status.value} for s in self.state.plan],
            outcome=outcome,
            success=is_goal_achieved
        )

        # Update session statistics
        if self.current_session_id:
            session = await self.session_manager.get_session(self.current_session_id)
            if session:
                update_data = {
                    "operations_count": session.operations_count + 1,
                    "successful_operations": session.successful_operations + (1 if is_goal_achieved else 0),
                    "failed_operations": session.failed_operations + (0 if is_goal_achieved else 1),
                }
                await self.session_manager.update_session(self.current_session_id, **update_data)

        return await self._format_response()

    async def _format_response(self) -> str:
        """Format the final response based on plan execution results"""

        # If successfully achieved complex goal, generate a reasoning-based summary
        if self.state.current_goal.status == GoalStatus.ACHIEVED and len(self.state.plan) > 1:
            try:
                results_summary = [{"desc": s.description, "result": s.result} for s in self.state.plan]
                report = await self.reasoning.generate_execution_report(
                    self.state.current_goal.definition,
                    results_summary
                )
                if report:
                    return report
            except Exception as e:
                logger.debug(f"Report generation failed, falling back to basic summary: {e}")

        if len(self.state.plan) == 1:
            step = self.state.plan[0]
            if step.status == StepStatus.FAILED and step.result:
                error_msg = step.result.get('error', 'Bilinmiyor')
                return format_error_natural(error_msg)
            return self._format_step_result(step)

        # Multi-step: show summary of each step
        parts = []
        for i, step in enumerate(self.state.plan, 1):
            if step.status == StepStatus.COMPLETED:
                result_text = self._format_step_result(step)
                parts.append(f"{i}. {result_text}")
            elif step.status == StepStatus.FAILED:
                if step.result and step.result.get('error'):
                    parts.append(f"{i}. Yapamadim: {step.result['error'][:100]}")
                else:
                    parts.append(f"{i}. {step.description} - basarisiz")

        return "\n".join(parts)

    def _format_step_result(self, step) -> str:
        """Format a single step's tool result - delegates to response_tone"""
        result = step.result or {}
        return format_tool_result(step.tool_name, result)

    async def _send_progress(self, message: str):
        """Send progress update to user"""
        if self.notify:
            try:
                await self.notify(f" {message}")
            except Exception as e:
                logger.debug(f"Progress notification failed: {e}")

    async def _execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        from tools import AVAILABLE_TOOLS
        from core.agent import ACTION_TO_TOOL
        from core.smart_paths import resolve_path
        from config.settings import DESKTOP

        # Resolve tool name
        actual_tool_name = ACTION_TO_TOOL.get(tool_name, tool_name)
        tool_func = AVAILABLE_TOOLS.get(actual_tool_name)

        if not tool_func:
            error_msg = f"Tool '{tool_name}' bulunamadı"
            logger.error(f"Tool not found: {tool_name}")
            # Return categorized error instead of generic message
            return {"success": False, "error": error_msg, "category": ErrorCategory.TOOL_NOT_FOUND.value}

        # Data Piping: Resolve placeholders from data_pipe
        # Form: {{key}} or just context-aware defaults
        for k, v in list(params.items()):
            if isinstance(v, str) and v.startswith("{{") and v.endswith("}}"):
                key = v[2:-2].strip()
                if key in self.state.data_pipe:
                    params[k] = self.state.data_pipe[key]
                    logger.info(f"Data Piping: Resolved {k}={params[k]} from pipe[{key}]")

        # Smart path resolution — LLM sıkça yanlış path hallucinate eder
        if "path" in params:
            resolved, _ = resolve_path(params["path"])
            if resolved:
                params["path"] = str(resolved)
            else:
                # Path resolve başarısız → dosya adı varsa Desktop'a default
                from pathlib import Path
                p = Path(params["path"])
                if p.name and not p.exists():
                    params["path"] = str(DESKTOP / p.name)

        # Record path in memory if present in params
        if "path" in params:
            self.path_memory.record_path(params["path"])
        elif "source" in params:
            self.path_memory.record_path(params["source"])
        elif "destination" in params:
            self.path_memory.record_path(params["destination"])

        # Execute tool
        result = await self.executor.execute(tool_func, params)

        # Post-execution Data Piping: Store meaningful results
        if isinstance(result, dict) and result.get("success"):
            if "filename" in result:
                self.state.data_pipe["last_file"] = result["filename"]
            if "path" in result:
                self.state.data_pipe["last_file"] = result["path"]
            self.state.data_pipe[f"step_{self.state.current_step_index + 1}_result"] = result.get("data") or result

        return result

    async def _verify_step(self, step: TaskStep) -> bool:
        """
        Smart verification strategy:
        - Skip LLM for deterministic tools (just check result.success)
        - Always verify for tools that modify system state
        """
        from config.settings import SKIP_VERIFICATION_TOOLS, ALWAYS_VERIFY_TOOLS

        # Quick success check
        if isinstance(step.result, dict):
            has_success_field = "success" in step.result

            # For SKIP_VERIFICATION_TOOLS: just check success flag
            if step.tool_name in SKIP_VERIFICATION_TOOLS:
                if has_success_field:
                    verified = step.result.get("success") is True
                    if verified:
                        logger.debug(f"Skipped LLM verification for {step.tool_name} (deterministic)")
                    return verified
                # If no success field, treat as success if no error
                return step.result.get("error") is None

            # For non-risky, data-returning tools: success check is enough
            if step.result.get("success") is True and step.tool_name not in ALWAYS_VERIFY_TOOLS:
                logger.debug(f"Skipped LLM verification for {step.tool_name} (safe tool)")
                return True

        # For ALWAYS_VERIFY_TOOLS or unknown tools: use LLM verification
        prompt = f"""Step Description: {step.description}
Tool: {step.tool_name}
Tool Result: {json.dumps(step.result)}
Verification Criteria: {step.verification}

Did this step succeed and perform as intended? Answer YES/NO."""
        try:
            response = await asyncio.wait_for(
                self.llm._ask_llm_with_custom_prompt(prompt),
                timeout=10
            )
        except (asyncio.TimeoutError, Exception):
            logger.warning(f"_verify_step LLM call timed out for {step.tool_name} — checking result.success")
            # Fallback to success field
            if isinstance(step.result, dict):
                return step.result.get("success") is True
            return False

        return "YES" in response.upper()

    async def _verify_goal(self) -> bool:
        """v19.2: Hedef dogrulamasi - LLM cagrisi yok, result.success kontrolu yeterli."""
        completed = sum(1 for s in self.state.plan if s.status == StepStatus.COMPLETED)
        total = len(self.state.plan)

        if completed == total:
            return True

        # Cogunluk basariliysa da basarili say
        if total > 1 and completed >= total * 0.5:
            return True

        return False

    async def _handle_step_failure(self, step: TaskStep) -> bool:
        """Reflect on failure and decide whether to retry or adapt the plan"""
        # First, check if there's a known fallback tool
        tool_health = get_tool_health_manager()
        fallback = tool_health.suggest_fallback(step.tool_name)

        if fallback and fallback != step.tool_name:
            logger.info(f"Fallback suggestion: trying {fallback} instead of {step.tool_name}")
            step.tool_name = fallback
            step.status = StepStatus.PENDING
            self.plan_adaptations += 1
            if self.notify:
                await self.notify(f" Plan uyarlandı: {fallback} deneniyor...")
            return True

        # Use advanced SelfReflection if available
        if hasattr(self, 'reasoning') and self.reasoning:
            try:
                error_context = {
                    "step": step.description,
                    "tool": step.tool_name,
                    "params": step.params,
                    "goal": self.state.current_goal.definition,
                    "recent_result": step.result
                }
                reflection = await self.reasoning.reflection.reflect_on_error(
                    error=Exception(step.result.get("error", "Unknown error")),
                    context=error_context
                )
                
                logger.info(f"Self-Reflection result: {reflection}")
                
                if reflection.get("should_retry"):
                    strategy = reflection.get("recovery_strategy", {})
                    modifications = strategy.get("modifications", [])
                    
                    if modifications:
                        # Apply suggested parameter modifications
                        for mod in modifications:
                            if isinstance(mod, dict):
                                step.params.update(mod)
                    
                    approach = strategy.get("approach", "retry")
                    if self.notify:
                        await self.notify(f"Hata fark edildi, tekrar deniyorum: {approach}")
                        
                    step.status = StepStatus.PENDING
                    return True
            except Exception as re:
                logger.error(f"Self-reflection failed: {re}")

        # v19.2: LLM cagrisi yerine basit fallback (token tasarrufu)
        # Tool health'den alternatif varsa dene, yoksa fail
        logger.info(f"Step {step.id} failed, no LLM fallback (token savings)")
        return False

    def _extract_json(self, text: str) -> str:
        """Extract JSON from text, handling common LLM formatting issues."""
        if not text:
            return ""
            
        # Remove any leading/trailing whitespace
        text = text.strip()
        
        # Check for markdown code blocks first
        code_block = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if code_block:
            return code_block.group(1).strip()
            
        generic_block = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
        if generic_block:
            return generic_block.group(1).strip()
            
        # Check for standard JSON start/end
        match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
        if match:
            return match.group(0).strip()
            
        return text
