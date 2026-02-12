"""
Task Engine - Central task processing motor for Wiqo v12.0

This is the single source of truth for task execution.
Both UI and Telegram bot use this engine.

Architecture:
1. Natural language input
2. Intent analysis
3. Task decomposition
4. Dependency & ordering
5. Security validation
6. Execution (filesystem, system, research, reports)
7. Result summarization

Returns: Structured JSON response
"""

import asyncio
import time
import re
import json
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime

from .llm_client import LLMClient
from .task_executor import TaskExecutor
from .intent_parser import IntentParser
from .error_handler import ErrorHandler, ErrorCategory
from .tool_health import get_tool_health_manager
from .monitoring import get_monitoring, record_operation, record_error
# License manager removed - no restrictions
from .memory import get_memory
from .learning_engine import get_learning_engine
from .intelligent_planner import get_intelligent_planner
from .semantic_memory import get_semantic_memory
from config.settings_manager import SettingsPanel
from security.validator import validate_input, sanitize_input
from security.audit import get_audit_logger
from security.approval import get_approval_manager, RiskLevel
from tools import AVAILABLE_TOOLS
from utils.logger import get_logger

logger = get_logger("task_engine")

# LLM'in hallucinate ettiği gerçek tool olmayan action isimleri
# Bu isimler AVAILABLE_TOOLS'da yok → security check'te takılır
# Çözüm: bunları tespit edip chat'e yönlendir
_NON_TOOL_ACTIONS = frozenset({
    "chat", "sohbet", "ask_for_confirmation", "clarify", "confirm",
    "greet", "greeting", "thank", "farewell", "acknowledge",
    "respond", "reply", "conversation", "yanit", "sorgu",
    "ask", "question", "answer", "help", "explain", "unknown",
    "ask_user", "request_info", "get_input", "prompt_user",
    "wait", "pause", "think", "analyze", "process",
})

# Explicit approval is mandatory before these actions are executed.
_EXPLICIT_APPROVAL_ACTIONS = frozenset({
    "shutdown_system",
    "restart_system",
    "sleep_system",
    "lock_screen",
})


@dataclass
class TaskResult:
    """Structured task result"""
    success: bool
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    execution_time_ms: int = 0


@dataclass
class TaskDefinition:
    """Single task definition"""
    id: str
    action: str
    params: Dict[str, Any]
    description: str
    dependencies: List[str] = field(default_factory=list)
    is_risky: bool = False
    requires_approval: bool = False


class TaskEngine:
    """
    Central task processing engine.
    Handles all task execution for Wiqo.
    """

    def __init__(self):
        self.llm = None  # Lazy init
        self.executor = None  # Lazy init
        self.intent_parser = IntentParser()
        self.audit = get_audit_logger()
        self.approval = get_approval_manager()
        self.memory = get_memory()
        self.learning = get_learning_engine()
        self.intelligent_planner = get_intelligent_planner()
        self.reasoning = None
        self.planner = None
        self.settings = SettingsPanel()

    async def initialize(self) -> bool:
        """Initialize engine components"""
        try:
            from .llm_client import LLMClient
            from .task_executor import TaskExecutor

            self.llm = LLMClient()
            if not await self.llm.check_model():
                logger.error("LLM model unavailable")
                return False

            self.executor = TaskExecutor()
            
            # Initialize advanced planning components
            from .reasoning import ReasoningEngine
            from .planner import AutonomousPlanner
            self.reasoning = ReasoningEngine(self.llm, self.executor)
            self.planner = AutonomousPlanner(self.llm, self.reasoning)
            
            logger.info("Task Engine and Intelligence engines initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Task Engine initialization failed: {e}")
            return False

    async def execute_task(
        self,
        user_input: str,
        user_id: Optional[str] = None,
        notify_callback = None,
        context: Optional[Dict[str, Any]] = None
    ) -> TaskResult:
        """
        Main entry point for task execution.

        Args:
            user_input: Natural language task description
            user_id: User identifier for auditing
            notify_callback: Optional callback for progress updates
            context: Optional context (history, preferences)

        Returns:
            TaskResult with execution details
        """
        start_time = time.time()

        # 1. Input validation
        valid, validation_msg = validate_input(user_input)
        if not valid:
            return TaskResult(
                success=False,
                message=f"Gecersiz girdi: {validation_msg}",
                error=validation_msg
            )

        user_input = sanitize_input(user_input)
        logger.info(f"[TaskEngine] Processing: {user_input[:50]}...")

        # Audit log
        self.audit.log_action(
            user_id=user_id or "unknown",
            action="task_request",
            details={"input": user_input[:100]}
        )

        try:
            # 2. Intent Analysis
            intent_result = await self._analyze_intent(user_input, context)
            decompose_tried = False
            planner_route_used = False

            if intent_result["type"] == "CHAT":
                # Simple chat response - no execution needed
                response = await self._generate_chat_response(user_input, context)
                elapsed_ms = int((time.time() - start_time) * 1000)
                return TaskResult(
                    success=True,
                    message=response,
                    metadata={"type": "chat", "intent": intent_result},
                    execution_time_ms=elapsed_ms
                )

            # 3. Task Decomposition or Cognitive Bypass (v15.0/v16.0)
            is_complex = self._is_complex_query(user_input)

            if intent_result.get("action") == "multi_task" and isinstance(intent_result.get("tasks"), list):
                logger.info("Cognitive Bypass: Direct-Route active for multi_task")
                tasks = self._build_task_definitions(intent_result.get("tasks", []), max_steps=12)
            elif self._should_force_planning(user_input, intent_result):
                logger.info("Planner route: IntelligentPlanner activated")
                tasks = await self._plan_with_intelligent_planner(user_input, intent_result, context)
                planner_route_used = True
            elif (not is_complex and
                intent_result.get("confidence", 0) >= 0.8 and 
                intent_result.get("action") and 
                intent_result.get("action") != "UNKNOWN"):
                
                logger.info(f"Cognitive Bypass: Direct-Route active for {intent_result['action']}")
                tasks = [TaskDefinition(
                    id="bypass_task_1",
                    action=intent_result["action"],
                    params=intent_result.get("params", {}),
                    description=intent_result.get("reply", f"Executing {intent_result['action']}")
                )]
            else:
                if is_complex and intent_result.get("type") != "CHAT":
                    logger.info("Complex query detected - Forcing LLM decomposition")
                tasks = await self._decompose_tasks(user_input, intent_result, context)

            if not tasks:
                # İlk deneme başarısızsa bir kez daha LLM decomposition dene (zorla)
                if intent_result.get("type") != "CHAT" and not self._is_chat_message(user_input):
                    logger.info("No deterministic tasks -> forcing LLM decomposition")
                    tasks = await self._decompose_tasks(user_input, intent_result, context)
                    decompose_tried = True

                if not tasks:
                    # Görev çıkarılamadı → muhtemelen sohbet mesajı
                    fallback_msg = await self._generate_chat_response(user_input, context)
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    return TaskResult(
                        success=True,
                        message=fallback_msg,
                        metadata={"type": "chat_fallback", "decompose_tried": decompose_tried},
                        execution_time_ms=elapsed_ms
                    )

            # 3.1 Filter out LLM-hallucinated non-tool actions
            real_tasks = [t for t in tasks if t.action.lower() not in _NON_TOOL_ACTIONS]
            if not real_tasks:
                # LLM sadece "chat", "ask_for_confirmation" gibi sahte action'lar döndü
                # Bu aslında bir sohbet mesajı demek
                logger.info(f"All tasks are non-tool actions: {[t.action for t in tasks]} → chat fallback")
                response = await self._generate_chat_response(user_input, context)
                elapsed_ms = int((time.time() - start_time) * 1000)
                return TaskResult(
                    success=True,
                    message=response,
                    metadata={"type": "chat_fallback", "filtered_actions": [t.action for t in tasks]},
                    execution_time_ms=elapsed_ms
                )
            tasks = real_tasks

            # 3.2 Normalize Tasks (Cognitive Precision v14.0)
            tasks = self._normalize_tasks(tasks)

            # 4. Dependency Analysis & Ordering
            ordered_tasks = self._order_tasks_by_dependency(tasks)

            # 5. Security Validation
            security_check = self._security_check(ordered_tasks, user_id)
            if not security_check["allowed"]:
                return TaskResult(
                    success=False,
                    message=f"Guvenlik kontrolu basarisiz: {security_check['reason']}",
                    error=security_check['reason'],
                    metadata={"blocked_tasks": security_check.get("blocked_tasks", [])}
                )

            # 6. Execution (license check removed)
            execution_result = await self._execute_tasks(
                ordered_tasks,
                notify_callback=notify_callback,
                user_id=user_id
            )

            # Auto re-plan once if planner route failed.
            if (
                planner_route_used
                and not execution_result.get("success", False)
                and bool(self.settings.get("auto_replan_enabled", True))
                and int(self.settings.get("auto_replan_max_attempts", 1) or 0) > 0
            ):
                retry_result = await self._retry_with_replan(
                    goal=user_input,
                    original_tasks=ordered_tasks,
                    failed_execution=execution_result,
                    context=context,
                    notify_callback=notify_callback,
                    user_id=user_id,
                )
                if retry_result:
                    execution_result = retry_result
                    if isinstance(retry_result.get("_replanned_tasks"), list):
                        ordered_tasks = retry_result["_replanned_tasks"]

            # 8. Result Summarization
            summary = self._summarize_results(execution_result, ordered_tasks)

            elapsed_ms = int((time.time() - start_time) * 1000)

            # Store in memory
            if user_id:
                self.memory.store_conversation(
                    user_id,
                    user_input,
                    {"action": "task_execution", "result": summary}
                )

                # Store in semantic memory
                semantic = await get_semantic_memory()
                await semantic.add_conversation(
                    user_input=user_input,
                    bot_response=summary,
                    metadata={"user_id": user_id}
                )

            # Record metrics
            monitoring = get_monitoring()
            record_operation(
                operation="task_execution",
                success=execution_result["success"],
                duration_ms=elapsed_ms,
                metadata={"task_count": len(ordered_tasks)}
            )

            return TaskResult(
                success=execution_result["success"],
                message=summary,
                data=execution_result.get("data", {}),
                metadata={
                    "tasks_executed": len(ordered_tasks),
                    "tasks_succeeded": execution_result.get("succeeded", 0),
                    "tasks_failed": execution_result.get("failed", 0)
                },
                execution_time_ms=elapsed_ms
            )

        except Exception as e:
            logger.error(f"Task execution error: {e}")
            record_error(
                component="task_engine",
                error_msg=str(e),
                error_type="task_execution_error"
            )

            elapsed_ms = int((time.time() - start_time) * 1000)
            return TaskResult(
                success=False,
                message=ErrorHandler.format_error_response(str(e)),
                error=str(e),
                execution_time_ms=elapsed_ms
            )

    def _is_complex_query(self, text: str) -> bool:
        """v23.5: Detect if a query contains multiple steps or complexity"""
        text = text.lower()
        # Connectors that strongly imply multi-step tasks
        connectors = [" ve ", " sonra ", " ardından ", " ve ayrıca ", " ve sonra "]
        if any(c in text for c in connectors):
            return True
        
        # Verb count (crude but useful for Turkish)
        if text.count(" ve ") > 0:
            return True
            
        return False

    def _should_force_planning(self, user_input: str, intent: Dict[str, Any]) -> bool:
        """Decide when to escalate to IntelligentPlanner."""
        action = str(intent.get("action", "") or "").strip()
        confidence = float(intent.get("confidence", 0.0) or 0.0)

        # Deterministic direct intents should stay on direct execution path.
        if action and action.lower() not in {"unknown", "chat", "multi_task"} and confidence >= 0.75:
            return False

        # Already a direct tool? skip
        if action in (
            "take_screenshot", "create_folder", "list_files", "write_file",
            "open_url", "open_app", "close_app",
            "shutdown_system", "restart_system", "sleep_system", "lock_screen"
        ):
            return False

        # Very short chat-like? skip
        if self._is_chat_message(user_input):
            return False
        # If explicit multi-step connectors exist
        if self._is_complex_query(user_input):
            return True
        # If intent is UNKNOWN but text is > 6 words, try planning
        words = user_input.strip().split()
        if intent.get("type") == "UNKNOWN" and len(words) >= 6:
            return True
        # If intent source is learning_quick_match, keep fast path
        if intent.get("source") == "learning_quick_match":
            return False
        # Allow user-configured depth
        planning_depth = self.settings.get("task_planning_depth", "adaptive")
        cost_guard = self.settings.get("cost_guard", True)
        if cost_guard and planning_depth == "compact":
            return False
        return planning_depth in {"deep", "adaptive"}

    async def _plan_with_intelligent_planner(
        self,
        goal: str,
        intent: Dict[str, Any],
        context: Optional[Dict[str, Any]]
    ) -> List[TaskDefinition]:
        """Use IntelligentPlanner to create executable tasks."""
        try:
            max_steps = int(self.settings.get("planner_max_steps", 10) or 10)
            if self.settings.get("cost_guard", True):
                max_steps = min(max_steps, 6)
            self.intelligent_planner.max_depth = max(3, min(5, max_steps // 2))
            use_llm = bool(self.llm) and not self.settings.get("cost_guard", True)
            try:
                plan = await self.intelligent_planner.create_plan(goal, context=context or {}, use_llm=use_llm)
            except TypeError:
                # Backward compatibility for planner mocks/older signatures.
                plan = await self.intelligent_planner.create_plan(goal, context=context or {})

            quality = self.intelligent_planner.evaluate_plan_quality(getattr(plan, "subtasks", []) or [], goal)
            if not quality.get("safe_to_run", True):
                feedback = ", ".join(quality.get("issues", [])[:8]) or "quality_below_threshold"
                revised_subtasks = await self.intelligent_planner.revise_plan(
                    goal,
                    current_subtasks=getattr(plan, "subtasks", []) or [],
                    context=context or {},
                    failure_feedback=feedback,
                    use_llm=use_llm,
                )
                plan.subtasks = revised_subtasks

            actions = []
            for idx, t in enumerate((getattr(plan, "subtasks", []) or [])[:max_steps]):
                actions.append({
                    "id": t.task_id or f"task_{idx+1}",
                    "action": t.action or "chat",
                    "params": t.params or {},
                    "description": t.name or f"Adim {idx+1}",
                    "depends_on": getattr(t, "depends_on", []) or getattr(t, "dependencies", [])
                })
            # Normalize unknown actions to chat to avoid blocking
            from core.agent import ACTION_TO_TOOL
            normalized = []
            for a in actions:
                act = a.get("action")
                mapped = ACTION_TO_TOOL.get(act, act)
                if mapped not in AVAILABLE_TOOLS:
                    guess = self._infer_action_from_text(a.get("description", ""), goal)
                    mapped_guess = ACTION_TO_TOOL.get(guess, guess)
                    if mapped_guess in AVAILABLE_TOOLS:
                        a["action"] = guess
                    else:
                        a["action"] = "chat"
                normalized.append(a)
            tasks = self._build_task_definitions(normalized, max_steps=max_steps)
            if not tasks:
                # fallback to simple chat if plan empty
                return []
            return tasks
        except Exception as e:
            logger.error(f"Planner fallback to LLM: {e}")
            return []

    async def _retry_with_replan(
        self,
        *,
        goal: str,
        original_tasks: List[TaskDefinition],
        failed_execution: Dict[str, Any],
        context: Optional[Dict[str, Any]],
        notify_callback=None,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """One-pass automatic replan after failed execution."""
        try:
            failed_rows = [r for r in failed_execution.get("data", {}).get("results", []) if not r.get("success")]
            if not failed_rows:
                return None

            feedback_lines = []
            for row in failed_rows[:6]:
                feedback_lines.append(f"{row.get('task_id')}: {str(row.get('error', 'unknown'))[:120]}")
            failure_feedback = " | ".join(feedback_lines)

            # Build SubTask list from failed plan.
            from core.intelligent_planner import SubTask
            current_subtasks = [
                SubTask(
                    task_id=t.id,
                    name=t.description,
                    action=t.action,
                    params=t.params,
                    dependencies=t.dependencies,
                )
                for t in original_tasks
            ]

            use_llm = bool(self.llm) and not self.settings.get("cost_guard", True)
            revised = await self.intelligent_planner.revise_plan(
                goal,
                current_subtasks=current_subtasks,
                context=context or {},
                failure_feedback=failure_feedback,
                use_llm=use_llm,
            )
            if not revised:
                return None

            actions = []
            for idx, t in enumerate(revised[: int(self.settings.get("planner_max_steps", 10) or 10)]):
                actions.append({
                    "id": t.task_id or f"retry_task_{idx+1}",
                    "action": t.action,
                    "params": t.params or {},
                    "description": t.name or f"Retry Adim {idx+1}",
                    "depends_on": t.dependencies or [],
                })
            retry_tasks = self._build_task_definitions(actions, max_steps=int(self.settings.get("planner_max_steps", 10) or 10))
            if not retry_tasks:
                return None
            retry_tasks = self._normalize_tasks(retry_tasks)
            retry_tasks = self._order_tasks_by_dependency(retry_tasks)

            if notify_callback:
                await notify_callback("Plan revize edildi, ikinci deneme başlatılıyor...")

            retry_exec = await self._execute_tasks(retry_tasks, notify_callback=notify_callback, user_id=user_id)
            retry_exec["_replanned_tasks"] = retry_tasks
            return retry_exec
        except Exception as exc:
            logger.error(f"Auto-replan failed: {exc}")
            return None

    def _infer_action_from_text(self, text: str, goal: str = "") -> str:
        """Heuristic mapping of free-text step to known actions (LLM's unknown)."""
        t = f"{text} {goal}".lower()
        if any(k in t for k in ["safari", "browser", "chrome", "url"]):
            return "open_url"
        if any(k in t for k in ["plan", "parcala", "parçala", "görev", "alt görev", "decompose"]):
            return "create_plan"
        if any(k in t for k in ["araştır", "research", "incele", "detaylı bilgi"]):
            return "advanced_research"
        if any(k in t for k in ["ara ", "arat", "google", "search"]):
            return "web_search"
        if any(k in t for k in ["mail", "e-posta", "email", "gönder"]):
            return "send_email"
        if any(k in t for k in ["klasör", "folder"]):
            return "create_folder"
        if any(k in t for k in ["yaz", "kaydet", "oluştur", "dosya"]):
            return "write_file"
        if any(k in t for k in ["oku", "göster", "read"]):
            return "read_file"
        if any(k in t for k in ["screenshot", "ekran görüntüsü", "ss"]):
            return "take_screenshot"
        return "chat"

    async def _analyze_intent(
        self,
        user_input: str,
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze user intent"""
        try:
            intent = self.intent_parser.parse(user_input)
            if intent:
                # Normalize intent: ensure 'type' field exists
                if "action" in intent and "type" not in intent:
                    intent["type"] = intent["action"].upper()
                return intent
            else:
                # Learned quick-match path (only safe param-free actions)
                learned_action = self.learning.quick_match(user_input)
                if learned_action in {
                    "take_screenshot", "get_system_info", "get_brightness",
                    "wifi_status", "bluetooth_status", "get_today_events",
                    "get_running_apps", "toggle_dark_mode", "read_clipboard"
                }:
                    return {
                        "type": learned_action.upper(),
                        "action": learned_action,
                        "params": {},
                        "confidence": 0.82,
                        "source": "learning_quick_match"
                    }

                # v19.1: Short conversational messages -> CHAT (skip heavy planner)
                if self._is_chat_message(user_input):
                    return {"type": "CHAT", "confidence": 0.7}
                return {"type": "UNKNOWN", "confidence": 0.0}
        except Exception as e:
            logger.error(f"Intent analysis error: {e}")
            return {"type": "UNKNOWN", "confidence": 0.0}

    @staticmethod
    def _normalize_tr(text: str) -> str:
        tr_map = str.maketrans('çğıöşüÇĞİÖŞÜ', 'cgiosuCGIOSU')
        return text.translate(tr_map)

    def _is_chat_message(self, text: str) -> bool:
        """Detect conversational messages that don't need tool execution"""
        t = text.lower().strip()
        tn = self._normalize_tr(t)
        words = tn.split()

        # Word-prefix based tool keyword detection (Turkish suffix-safe)
        tool_prefixes = {
            'ac', 'kapat', 'kis', 'yukselt', 'sil', 'oku', 'yaz',
            'bul', 'tara', 'indir', 'yukle', 'calistir', 'gonder',
            'olustur', 'listele', 'goster', 'screenshot', 'dosya',
            'klasor', 'hatirlat', 'arastir', 'research', 'kopyala', 'tasi',
            'open', 'close', 'delete', 'search', 'find', 'send',
            'volume', 'ses', 'parlaklik', 'wifi', 'bluetooth', 'ekran',
            'kaydet', 'yedekle', 'azalt', 'artir', 'dusur', 'mail', 'email',
        }
        has_tool = any(
            word.startswith(prefix) and (len(word) - len(prefix)) <= 5
            for word in words
            for prefix in tool_prefixes
            if len(prefix) >= 3
        )
        # Short exact-match keywords (2 chars)
        short_tools = {'ac', 'ss', 'al'}
        if not has_tool:
            has_tool = any(word in short_tools for word in words)

        # Short messages without tool keywords -> likely chat
        if len(words) <= 8 and not has_tool:
            return True

        # Common chat patterns (Turkish + ASCII normalized)
        chat_patterns = [
            r'^(iyiyim|kotuyum|idare|fena degil|soyle boyle|super|harika)',
            r'^(tesekkur|sagol|eyvallah|tsk|tmm|tamam|ok|peki|anladim)',
            r'^(guzel|iyi|kotu|hos|haklisin|dogru|evet|hayir|yok)',
            r'^(sen nasilsin|ne yapiyorsun|naber|nasilsin)',
            r'^(gorusuruz|hosca kal|bay bay|bb|bye|iyi geceler|iyi gunler)',
            r'^(haha|lol|cok komik|guldum|bravo|aferin)',
            r'^(merhaba|selam|hey|hi|hello|sa|as|mrb|gunaydin)',
            r'^(ben de|bende|aynen|kesinlikle|tabii|tabi)',
            r'^(ne diyorsun|ne dersin|ne dusunuyorsun|sence)',
            r'^(hmm|himm|sey|ee|yani|vallahi|valla)',
            r'^(olsun|bosver|neyse|gecelim|birak)',
            r'^(emin misin|ciddi misin|gercekten mi|oyle mi)',
            r'^(bilmiyorum|bilmem|hicbir fikrim yok)',
            r'^(merak ettim|sormak istiyorum|bir sorum var)',
            r'(nasil\s*gidiyor|ne\s*yapiyorsun|keyifler\s*nasil)',
            r'\?$',
        ]
        for pattern in chat_patterns:
            if re.search(pattern, tn):
                if has_tool:
                    return False
                return True

        return False

    async def _generate_chat_response(
        self,
        user_input: str,
        context: Optional[Dict[str, Any]]
    ) -> str:
        """Generate chat response for conversational inputs using direct chat API"""
        try:
            # Build context hint from formatted_context (if available)
            context_hint = ""
            if context:
                # Prioritize formatted_context (from context_manager)
                if "formatted_context" in context:
                    context_hint = f"\n\nBaglamdan notlar:\n{context['formatted_context'][:400]}"
                # Fallback to recent_history
                elif context.get("recent_history"):
                    try:
                        for turn in context["recent_history"][-2:]:
                            user_msg = turn.get("user_input", turn.get("input", ""))
                            if user_msg:
                                context_hint += f"\nOnceki soru: {user_msg}"
                    except Exception:
                        pass

            tone = self.settings.get("communication_tone", "professional_friendly")
            length = self.settings.get("response_length", "short")
            expertise = self.settings.get("assistant_expertise", "advanced")

            tone_hint = {
                "professional_friendly": "profesyonel ama samimi",
                "mentor": "rehberlik eden ve destekleyici",
                "formal": "resmi ve kurumsal",
            }.get(tone, "profesyonel ama samimi")

            length_hint = {
                "short": "2-4 cumle",
                "medium": "4-6 cumle",
                "detailed": "6-9 cumle",
            }.get(length, "2-4 cumle")

            expertise_hint = {
                "basic": "Gereksiz teknik derinliğe girme.",
                "advanced": "Gerekirse teknik ayrıntıyı kısa ve anlaşılır ver.",
                "expert": "Teknik doğruluk yüksek olsun, ama anlaşılır kal.",
            }.get(expertise, "Gerekirse teknik ayrıntıyı kısa ve anlaşılır ver.")

            system_prompt = (
                f"Wiqo, {tone_hint} bir Turkce dijital asistansin. "
                f"Kullanicinin sorusuna dogrudan, net ve {length_hint} ile cevap ver. "
                "Sadece Turkce konus. Emoji kullanma. "
                f"{expertise_hint}"
                f"{context_hint}"
            )

            # Use chat() method - no JSON parsing, direct text
            if not self.llm:
                return "Şu an LLM bağlı değil, basit yanıta geçiyorum."

            response = await asyncio.wait_for(
                self.llm.chat(user_input, system_prompt=system_prompt),
                timeout=15.0
            )
            return response.strip() if response else "Anlamadım, biraz daha açar mısın?"

        except Exception as e:
            logger.error(f"Chat response error: {e}", exc_info=True)
            return "Bir sorun olustu, tekrar deneyin."

    async def _decompose_tasks(
        self,
        user_input: str,
        intent: Dict[str, Any],
        context: Optional[Dict[str, Any]]
    ) -> List[TaskDefinition]:
        """v19.2: Tek LLM cagrisiyla gorev ayristirma.
        AutonomousPlanner bypass - CoT overhead yok, token tasarrufu."""

        # Sik kullanilan tool'larin kisa katalogu (token tasarrufu)
        key_tools = [
            "open_app(app_name)", "close_app(app_name)", "open_url(url)",
            "take_screenshot(filename?)", "list_files(path)", "read_file(path)",
            "write_file(path,content)", "delete_file(path)", "move_file(source,destination)",
            "copy_file(source,destination)", "rename_file(path,new_name)",
            "create_folder(path)", "search_files(pattern,directory)",
            "set_volume(level|mute)", "set_brightness(level)", "get_brightness()",
            "get_system_info()", "wifi_status()", "wifi_toggle()",
            "toggle_dark_mode()", "get_running_apps()",
            "web_search(query)", "advanced_research(topic,depth)",
            "create_note(title,content)", "create_reminder(title,due_time)",
            "get_today_events()", "create_event(title,start_time,end_time)",
            "send_notification(title,message)",
            "read_clipboard()", "write_clipboard(content)",
            "send_email(to,subject,body)", "get_unread_emails()",
            "read_word(path)", "read_pdf(path)", "read_excel(path)",
            "create_smart_file(type,title,content,path)",
            "smart_summarize(text|path)", "analyze_document(path)",
            "run_safe_command(command)", "spotlight_search(query)",
            "kill_process(name)", "get_process_info()",
            "ollama_list_models()", "ollama_remove_model(model_name)",
        ]
        catalog = "\n".join(f"  {t}" for t in key_tools)

        # Add context if available (conversation history)
        context_str = ""
        if context and "formatted_context" in context:
            context_str = f"\n\nBaglamdan notlar:\n{context['formatted_context'][:300]}\n"
        if context and isinstance(context.get("user_profile"), dict):
            profile = context["user_profile"]
            profile_parts = []
            lang = profile.get("preferred_language")
            if lang:
                profile_parts.append(f"tercih_dili={lang}")
            topics = profile.get("top_topics", [])
            if isinstance(topics, list) and topics:
                profile_parts.append(f"ilgiler={','.join(str(t) for t in topics[:5])}")
            if profile_parts:
                context_str += f"\nProfil ipucu: {' | '.join(profile_parts)}\n"

        autonomy = self.settings.get("autonomy_level", "Balanced")
        planning_depth = self.settings.get("task_planning_depth", "adaptive")
        max_steps_map = {"Strict": 4, "Balanced": 7, "Flexible": 10}
        max_steps = max_steps_map.get(autonomy, 7)
        if planning_depth == "compact":
            max_steps = min(max_steps, 5)
        elif planning_depth == "deep":
            max_steps = min(12, max_steps + 2)

        # Minimal, token-efficient prompt
        prompt = f"""Gorev: {user_input}{context_str}

Araclar:
{catalog}

KURALLAR:
- SADECE yukaridaki arac isimlerini kullan, baska isim UYDURMA.
- Klasor/dosya isimlerinden "adında", "isimli", "adlı" gibi ekleri TEMIZLE (örn: "test adında" -> "test").
- Dosya yollari MUTLAKA '~/' ile baslamali (örn: '~/Desktop/test'). ASLA '/Desktop' kullanma.
- Dosya yolu belirtilmemisse '~/Desktop' varsay.
- Karmaşık görevi alt görevlere ayır. Tek islem yeterliyse tek adim yaz.
- Her adim icin id ver (task_1, task_2). Bagimli adimlarda depends_on kullan.
- Maksimum {max_steps} adim yaz.
- Sohbet icin tool KULLANMA, bos dizi dondur [].

JSON ciktisi (baska hicbir sey yazma):
[{{"id":"task_1","action":"arac","params":{{}},"description":"aciklama","depends_on":[]}}]"""

        try:
            response = await asyncio.wait_for(
                self.llm.generate(prompt, max_tokens=700),
                timeout=15.0
            )

            # JSON cikarim (robust)
            json_match = re.search(r'\[[\s\S]*?\]', response)
            if json_match:
                json_str = json_match.group(0)
                last_bracket = json_str.rfind(']')
                if last_bracket != -1:
                    json_str = json_str[:last_bracket + 1]
                actions = json.loads(json_str)
                return self._build_task_definitions(actions, max_steps=max_steps)

        except asyncio.TimeoutError:
            logger.error("LLM decomposition timeout (15s)")
        except Exception as e:
            logger.error(f"Task decomposition error: {e}")

        return []

    def _build_task_definitions(self, actions: Any, max_steps: int) -> List[TaskDefinition]:
        """Build normalized task definitions from LLM output."""
        if not isinstance(actions, list):
            return []

        tasks: List[TaskDefinition] = []
        known_ids: List[str] = []

        for idx, a in enumerate(actions[:max_steps]):
            if not isinstance(a, dict):
                continue
            action = str(a.get("action", "")).strip()
            if not action:
                continue
            action = action.split("(")[0].strip()
            task_id = str(a.get("id") or f"task_{idx + 1}")

            depends_on_raw = a.get("depends_on", [])
            if isinstance(depends_on_raw, str):
                depends_on = [depends_on_raw.strip()] if depends_on_raw.strip() else []
            elif isinstance(depends_on_raw, list):
                depends_on = [str(x).strip() for x in depends_on_raw if str(x).strip()]
            else:
                depends_on = []

            # Keep only already-known task ids to avoid forward/cyclic references
            depends_on = [d for d in depends_on if d in known_ids]

            tasks.append(TaskDefinition(
                id=task_id,
                action=action,
                params=a.get("params", {}) if isinstance(a.get("params", {}), dict) else {},
                description=a.get("description", f"Adim {idx + 1}"),
                dependencies=depends_on,
                is_risky=self._is_risky_action(action),
                requires_approval=self._requires_explicit_approval(action),
            ))
            known_ids.append(task_id)

        self._infer_dependencies(tasks)
        return tasks

    def _infer_dependencies(self, tasks: List[TaskDefinition]) -> None:
        """Infer dependencies from placeholder references like {{task_1.result}}."""
        for task in tasks:
            param_text = json.dumps(task.params, ensure_ascii=False)
            refs = re.findall(r"\{\{\s*(task_\d+)\.[^}]+\}\}", param_text)
            for ref in refs:
                if ref != task.id and ref in {t.id for t in tasks} and ref not in task.dependencies:
                    task.dependencies.append(ref)

    def _normalize_tasks(self, tasks: List[TaskDefinition]) -> List[TaskDefinition]:
        """Normalize tool names and parameters to fix hallucinations (v14.0)"""
        from .parameter_extractor import normalize_path, clean_name_string
        
        normalization_map = {
            # Screenshot synonyms
            "snagit": "take_screenshot",
            "snapshot": "take_screenshot",
            "screen_capture": "take_screenshot",
            "capture_screen": "take_screenshot",
            
            # Browser synonyms
            "safari": "open_url",
            "chrome": "open_url",
            "browser": "open_url",
            "google": "web_search",
            
            # File synonyms
            "explorer": "list_files",
            "finder": "list_files",
            "dir": "list_files",
            "ls": "list_files",
            
            # System synonyms
            "remedy": "run_command",
            "terminal": "run_command",
            "shell": "run_command"
        }

        for task in tasks:
            original_action = task.action.lower()
            
            # 1. Direct synonym mapping
            if original_action in normalization_map:
                logger.info(f"Normalizing action: {task.action} -> {normalization_map[original_action]}")
                task.action = normalization_map[original_action]
            
            # 2. Parameter Normalization (v19.4)
            if task.params:
                # Normalize path-like parameters
                for p_key in ["path", "directory", "source", "destination"]:
                    if p_key in task.params and isinstance(task.params[p_key], str):
                        old_path = task.params[p_key]
                        task.params[p_key] = normalize_path(old_path)
                        if old_path != task.params[p_key]:
                            logger.info(f"Normalized parameter {p_key}: {old_path} -> {task.params[p_key]}")
                
                # Clean name-like parameters (handled "adında" fillers)
                for n_key in ["name", "new_name", "title", "app_name"]:
                    if n_key in task.params and isinstance(task.params[n_key], str):
                        task.params[n_key] = clean_name_string(task.params[n_key])

            # 3. Heuristic check: if action looks like an app name but tool doesn't exist
            if task.action not in AVAILABLE_TOOLS and "app" not in task.action:
                # Often LLMs use the app name as the action
                if any(ext in task.action for ext in [".app", "exe"]):
                    task.params["app_name"] = clean_name_string(task.action)
                    task.action = "open_app"
                    logger.info(f"Heuristic normalized {task.action} to open_app")

        return tasks

    def _order_tasks_by_dependency(self, tasks: List[TaskDefinition]) -> List[TaskDefinition]:
        """Order tasks using stable topological sort."""
        if not tasks:
            return tasks

        task_map = {t.id: t for t in tasks}
        indegree = {t.id: 0 for t in tasks}
        children: Dict[str, List[str]] = {t.id: [] for t in tasks}

        for t in tasks:
            valid_deps = [d for d in t.dependencies if d in task_map and d != t.id]
            t.dependencies = valid_deps
            indegree[t.id] = len(valid_deps)
            for d in valid_deps:
                children[d].append(t.id)

        queue = [t.id for t in tasks if indegree[t.id] == 0]
        ordered_ids: List[str] = []

        while queue:
            current = queue.pop(0)
            ordered_ids.append(current)
            for child in children[current]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)

        if len(ordered_ids) != len(tasks):
            logger.warning("Dependency cycle detected, using original task order.")
            return tasks

        return [task_map[tid] for tid in ordered_ids]

    def _security_check(self, tasks: List[TaskDefinition], user_id: Optional[str]) -> Dict[str, Any]:
        """Validate tasks for security"""

        dangerous_commands = [
            "rm -rf", "sudo", "format", "mkfs",
            "dd if=", "curl", "wget"
        ]
        high_risk_actions = {"run_safe_command", "run_command", "execute_command", "terminal", "kill_process"}

        for task in tasks:
            # Only run dangerous pattern scan for high-risk actions
            if task.action in high_risk_actions:
                task_str = str(task.params).lower()
                for cmd in dangerous_commands:
                    if cmd in task_str:
                        self.audit.log_action(
                            user_id=user_id or "unknown",
                            action="security_block",
                            details={"blocked": task_str, "reason": f"Dangerous pattern: {cmd}"}
                        )
                        return {
                            "allowed": False,
                            "reason": f"Blocked dangerous command pattern: {cmd}",
                            "blocked_tasks": [task.id]
                        }

            # Check tool availability - normalize action name first using ACTION_TO_TOOL
            # Import ACTION_TO_TOOL locally to avoid circular import
            from core.agent import ACTION_TO_TOOL
            
            normalized_action = ACTION_TO_TOOL.get(task.action, task.action)
            if normalized_action not in AVAILABLE_TOOLS:
                return {
                    "allowed": False,
                    "reason": f"Tool not available: {task.action} (normalized: {normalized_action})"
                }
            
            # Update task.action to use normalized name for downstream execution
            task.action = normalized_action

        return {"allowed": True}

    def _is_risky_action(self, action: str) -> bool:
        """Determine if action is risky"""
        risky_actions = {
            "delete_file", "run_command", "kill_process",
            "format_disk", "change_password",
            "shutdown_system", "restart_system", "sleep_system", "lock_screen"
        }
        return action in risky_actions

    def _requires_explicit_approval(self, action: str) -> bool:
        """Whether action must be explicitly approved by the user."""
        return action in _EXPLICIT_APPROVAL_ACTIONS

    def _approval_risk_level(self, action: str) -> RiskLevel:
        """Risk level mapping for explicit-approval actions."""
        if action in {"shutdown_system", "restart_system"}:
            return RiskLevel.CRITICAL
        return RiskLevel.HIGH

    async def _request_explicit_approval(
        self,
        task: TaskDefinition,
        user_id: Optional[str]
    ) -> Dict[str, Any]:
        """Request explicit user approval for a high-risk task."""
        try:
            uid = int(user_id) if user_id is not None else 0
        except Exception:
            uid = 0

        descriptions = {
            "shutdown_system": "Bilgisayarı kapatma komutu",
            "restart_system": "Bilgisayarı yeniden başlatma komutu",
            "sleep_system": "Bilgisayarı uyku moduna alma komutu",
            "lock_screen": "Ekranı kilitleme komutu",
        }
        description = descriptions.get(task.action, f"Yüksek riskli işlem: {task.action}")

        try:
            return await self.approval.request_approval(
                operation=task.action,
                risk_level=self._approval_risk_level(task.action),
                description=description,
                params=task.params,
                user_id=uid,
                timeout=180,
            )
        except Exception as exc:
            logger.error(f"Approval request failed for {task.action}: {exc}")
            return {"approved": False, "reason": str(exc)}

    def _format_plan_summary(self, tasks: List[TaskDefinition]) -> str:
        """Format task plan for display"""
        summary = "Execution Plan:\n"
        summary += "=" * 40 + "\n\n"

        for idx, task in enumerate(tasks, 1):
            summary += f"{idx}. {task.description}\n"
            summary += f"   Action: {task.action}\n"
            if task.params:
                summary += f"   Parameters: {task.params}\n"
            summary += "\n"

        return summary

    async def _execute_tasks(
        self,
        tasks: List[TaskDefinition],
        notify_callback = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Execute tasks with optimized parallelism (v14.0)"""
        results = []
        succeeded = 0
        failed = 0
        skipped = 0
        
        # Build dependency graph
        task_map = {t.id: t for t in tasks}
        completed_tasks = set()
        successful_tasks = set()
        failed_tasks = set()
        
        while len(completed_tasks) < len(tasks):
            # Identify tasks ready for execution (all dependencies met)
            ready_tasks = []
            for t in tasks:
                if t.id not in completed_tasks:
                    if any(dep in failed_tasks for dep in t.dependencies):
                        skipped += 1
                        failed += 1
                        completed_tasks.add(t.id)
                        failed_tasks.add(t.id)
                        results.append({
                            "task_id": t.id,
                            "success": False,
                            "skipped": True,
                            "error": f"Dependency failed: {', '.join([d for d in t.dependencies if d in failed_tasks])}"
                        })
                        if notify_callback:
                            await notify_callback(f" {t.description} atlandı (bağımlı adım başarısız).")
                        continue

                    if not t.dependencies or all(dep in successful_tasks for dep in t.dependencies):
                        ready_tasks.append(t)
            
            if not ready_tasks:
                # Circular dependency or unresolved deps
                logger.error("Dependency deadlock detected")
                break
                
            # Execute ready tasks in parallel
            logger.info(f"Executing {len(ready_tasks)} tasks in parallel")
            
            async def run_task(task_def):
                nonlocal succeeded, failed
                try:
                    if self._requires_explicit_approval(task_def.action):
                        if notify_callback:
                            await notify_callback(
                                f" {task_def.description} için açık kullanıcı onayı bekleniyor..."
                            )

                        approval_result = await self._request_explicit_approval(task_def, user_id)
                        if not approval_result.get("approved", False):
                            failed += 1
                            reason = approval_result.get("reason") or "Kullanıcı onayı verilmedi"
                            if notify_callback:
                                await notify_callback(f" {task_def.description} iptal edildi: {reason}")
                            return {
                                "task_id": task_def.id,
                                "action": task_def.action,
                                "success": False,
                                "error": reason,
                                "approval_required": True,
                            }

                    if notify_callback:
                        await notify_callback(f" *{task_def.description}* başlatıldı...")
                    
                    tool_func = AVAILABLE_TOOLS.get(task_def.action)
                    if not tool_func:
                        raise ValueError(f"Tool not found: {task_def.action}")
                        
                    result = await asyncio.wait_for(
                        self.executor.execute(tool_func, task_def.params),
                        timeout=60.0
                    )
                    # If screenshot and notifier exists, send image
                    if notify_callback and task_def.action == "take_screenshot" and result.get("success"):
                        await notify_callback({
                            "type": "screenshot",
                            "path": result.get("path") or result.get("filename"),
                            "message": f"{task_def.description} goruntusu"
                        })
                    
                    if result.get("success"):
                        succeeded += 1
                        if notify_callback:
                            await notify_callback(f" {task_def.description} tamamlandı.")
                    else:
                        failed += 1
                        if notify_callback:
                            await notify_callback(f" {task_def.description} hatası: {result.get('error')}")
                            
                    return {
                        "task_id": task_def.id,
                        "action": task_def.action,
                        "success": result.get("success", False),
                        "data": result,
                        "message": result.get("message"),
                        "error": result.get("error")
                    }
                except Exception as e:
                    failed += 1
                    logger.error(f"Task {task_def.id} failed: {e}")
                    return {"task_id": task_def.id, "action": task_def.action, "success": False, "error": str(e)}

            # Group execution
            batch_results = await asyncio.gather(*(run_task(t) for t in ready_tasks))
            
            for res in batch_results:
                results.append(res)
                completed_tasks.add(res["task_id"])
                if res["success"]:
                    successful_tasks.add(res["task_id"])
                else:
                    failed_tasks.add(res["task_id"])

        # Final progress update
        if notify_callback and succeeded == len(tasks):
            await notify_callback(f"Tum gorevler basariyla tamamlandi.")

        return {
            "success": failed == 0,
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
            "data": {"results": results}
        }

    def _summarize_results(
        self,
        execution_result: Dict[str, Any],
        tasks: List[TaskDefinition]
    ) -> str:
        """Sonuclari ozetle"""
        total = len(tasks)
        succeeded = execution_result.get('succeeded', 0)
        failed_count = execution_result.get('failed', 0)
        skipped_count = execution_result.get('skipped', 0)
        results = execution_result.get("data", {}).get("results", [])

        if total == 1 and execution_result.get("success"):
            first = results[0] if results else {}
            msg = str(first.get("message") or "").strip()
            if msg:
                return msg
            return "İşlem tamamlandı."

        if failed_count == 0:
            return f"Tum islemler tamamlandi ({succeeded}/{total})."

        failed_tasks = [r for r in results if not r.get("success")]
        summary_lines = [f"Tamamlanan: {succeeded}/{total}", f"Basarisiz: {failed_count}"]
        if skipped_count:
            summary_lines.append(f"Atlanan: {skipped_count}")
        if failed_tasks:
            summary_lines.append("Hatalar:")
            for ft in failed_tasks[:5]:
                task_id = ft.get("task_id", "task")
                error = str(ft.get("error", "Bilinmeyen hata"))[:140]
                summary_lines.append(f"- {task_id}: {error}")
            if len(failed_tasks) > 5:
                summary_lines.append(f"- ... +{len(failed_tasks) - 5} hata daha")
        return "\n".join(summary_lines).strip()


# Singleton instance
_task_engine: Optional[TaskEngine] = None


def get_task_engine() -> TaskEngine:
    """Get singleton task engine instance"""
    global _task_engine
    if _task_engine is None:
        _task_engine = TaskEngine()
    return _task_engine
