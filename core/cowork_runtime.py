from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Optional

from core.advanced_checkpoints import CheckpointManager
from core.smart_context_manager import SmartContextManager
from core.tool_usage import get_tool_usage_snapshot
from utils.logger import get_logger

logger = get_logger("cowork_runtime")


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _coerce_user_id(user_id: Any) -> tuple[str, int]:
    raw = str(user_id or "local").strip() or "local"
    try:
        numeric = int(raw)
    except Exception:
        numeric = 0
    return raw, numeric


def _is_greeting_like(text: str) -> bool:
    low = _normalize_text(text)
    if not low:
        return True
    return low in {
        "merhaba",
        "selam",
        "hey",
        "hi",
        "hello",
        "naber",
        "nbr",
        "nasılsın",
        "nasilsin",
        "nasılsınız",
        "nasilsiniz",
        "iyiyim",
        "tesekkurler",
        "teşekkürler",
        "tamam",
        "peki",
    }


def _references_prior_context(text: str) -> bool:
    low = _normalize_text(text)
    if not low:
        return False
    markers = (
        "bunu",
        "şunu",
        "sunu",
        "devam",
        "devam et",
        "önceki",
        "onceki",
        "az önce",
        "az once",
        "yukarıdaki",
        "yukardaki",
        "buradaki",
        "buradakini",
        "onu",
        "onu yap",
    )
    return any(marker in low for marker in markers)


def _looks_like_screen_task(text: str, attachments: list[str] | None = None, capability_domain: str = "") -> bool:
    low = _normalize_text(text)
    domain = str(capability_domain or "").strip().lower()
    if domain in {"screen_operator", "desktop_control", "screen", "browser"}:
        return True
    if isinstance(attachments, list) and any(str(item or "").strip() for item in attachments):
        return True
    if not low:
        return False
    markers = (
        "ekran",
        "screenshot",
        "screen",
        "pano",
        "clipboard",
        "imlec",
        "cursor",
        "mouse",
        "tıkla",
        "tikla",
        "click",
        "yaz",
        "type",
        "sekme",
        "tab",
        "window",
        "pencere",
        "frontmost",
        "ui",
    )
    return any(marker in low for marker in markers)


def _looks_like_browser_task(text: str) -> bool:
    low = _normalize_text(text)
    if not low:
        return False
    markers = (
        "browser",
        "tarayıcı",
        "tarayici",
        "safari",
        "chrome",
        "firefox",
        "arc",
        "url",
        "web",
        "site",
        "sekme",
        "tab",
        "open url",
        "aç url",
    )
    return any(marker in low for marker in markers)


def _looks_like_code_task(text: str) -> bool:
    low = _normalize_text(text)
    if not low:
        return False
    markers = (
        "kod",
        "code",
        "python",
        "javascript",
        "typescript",
        "react",
        "debug",
        "refactor",
        "implement",
        "script",
        "function",
        "class",
    )
    return any(marker in low for marker in markers)


def _looks_like_research_task(text: str) -> bool:
    low = _normalize_text(text)
    if not low:
        return False
    markers = (
        "araştır",
        "arastir",
        "research",
        "incele",
        "rapor",
        "kaynak",
        "makale",
        "literatür",
        "literatur",
        "karşılaştır",
        "karsilastir",
    )
    return any(marker in low for marker in markers)


def _looks_like_file_task(text: str) -> bool:
    low = _normalize_text(text)
    if not low:
        return False
    markers = (
        "dosya",
        "klasör",
        "klasor",
        "kaydet",
        "oku",
        "yaz",
        "sil",
        "listele",
        "folder",
        "file",
    )
    return any(marker in low for marker in markers)


@dataclass
class ToolDecision:
    tool_name: str
    score: float
    risk_level: str = "low"
    requires_approval: bool = False
    estimated_latency_ms: int = 0
    model_tier: str = "inference"
    rationale: list[str] = field(default_factory=list)
    available: bool = True
    source: str = "schema"
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScreenState:
    captured_at: float = field(default_factory=time.time)
    screenshot_path: str = ""
    summary: str = ""
    frontmost_app: str = ""
    active_window: dict[str, Any] = field(default_factory=dict)
    accessibility: list[dict[str, Any]] = field(default_factory=list)
    ocr_text: str = ""
    ocr_lines: list[dict[str, Any]] = field(default_factory=list)
    vision_summary: str = ""
    vision_elements: list[dict[str, Any]] = field(default_factory=list)
    ui_state: dict[str, Any] = field(default_factory=dict)
    clipboard_text: str = ""
    display_info: dict[str, Any] = field(default_factory=dict)
    source_counts: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)
    cursor: dict[str, Any] = field(default_factory=dict)
    selection: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_prompt_block(self, max_elements: int = 8) -> str:
        parts: list[str] = []
        if self.frontmost_app:
            parts.append(f"Frontmost app: {self.frontmost_app}")
        window_title = str((self.active_window or {}).get("title") or "").strip()
        if window_title:
            parts.append(f"Window: {window_title}")
        if self.summary:
            parts.append(f"Summary: {self.summary[:400]}")
        if self.ocr_text:
            parts.append(f"OCR: {self.ocr_text[:300]}")
        if self.clipboard_text:
            parts.append(f"Clipboard: {self.clipboard_text[:220]}")

        elements: list[str] = []
        for item in list(self.accessibility or [])[:max_elements]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("text") or "").strip()
            role = str(item.get("role") or item.get("kind") or "element").strip()
            if label:
                elements.append(f"- {label} [{role}]")
        if elements:
            parts.append("Visible elements:\n" + "\n".join(elements))

        if self.warnings:
            parts.append("Warnings: " + "; ".join(str(item) for item in self.warnings[:3]))
        return "\n".join(part for part in parts if part).strip()

    @classmethod
    def from_observation(
        cls,
        observation: dict[str, Any],
        *,
        clipboard_text: str = "",
        display_info: dict[str, Any] | None = None,
        cursor: dict[str, Any] | None = None,
        selection: dict[str, Any] | None = None,
    ) -> "ScreenState":
        payload = dict(observation or {})
        ui_state = payload.get("ui_state") if isinstance(payload.get("ui_state"), dict) else {}
        window_metadata = payload.get("window_metadata") if isinstance(payload.get("window_metadata"), dict) else {}
        access = payload.get("accessibility") if isinstance(payload.get("accessibility"), dict) else {}
        ocr = payload.get("ocr") if isinstance(payload.get("ocr"), dict) else {}
        vision = payload.get("vision") if isinstance(payload.get("vision"), dict) else {}
        screenshot = payload.get("screenshot") if isinstance(payload.get("screenshot"), dict) else {}

        active_window = dict(ui_state.get("active_window") or {})
        if not active_window and isinstance(window_metadata.get("bounds"), dict):
            active_window = {
                "title": str(window_metadata.get("window_title") or "").strip(),
                "bounds": dict(window_metadata.get("bounds") or {}),
            }

        frontmost_app = str(
            ui_state.get("frontmost_app")
            or window_metadata.get("frontmost_app")
            or payload.get("frontmost_app")
            or ""
        ).strip()
        summary = str(payload.get("summary") or ui_state.get("summary") or vision.get("summary") or "").strip()
        accessibility = [dict(item) for item in list(access.get("elements") or []) if isinstance(item, dict)]
        if not accessibility:
            accessibility = [dict(item) for item in list(ui_state.get("elements") or []) if isinstance(item, dict)]
        vision_elements = [dict(item) for item in list(vision.get("elements") or []) if isinstance(item, dict)]
        ocr_lines = [dict(item) for item in list(ocr.get("lines") or []) if isinstance(item, dict)]
        warnings = [
            str(item).strip()
            for item in (
                payload.get("warning"),
                payload.get("error"),
                vision.get("warning"),
                vision.get("error"),
                ocr.get("error"),
            )
            if str(item or "").strip()
        ]
        confidence = ui_state.get("confidence") if isinstance(ui_state.get("confidence"), (int, float)) else payload.get("confidence", 0.0)
        return cls(
            screenshot_path=str(screenshot.get("path") or payload.get("path") or "").strip(),
            summary=summary,
            frontmost_app=frontmost_app,
            active_window=active_window,
            accessibility=accessibility,
            ocr_text=str(ocr.get("text") or "").strip(),
            ocr_lines=ocr_lines,
            vision_summary=str(vision.get("summary") or vision.get("analysis") or "").strip(),
            vision_elements=vision_elements,
            ui_state=dict(ui_state),
            clipboard_text=str(clipboard_text or "").strip(),
            display_info=dict(display_info or {}),
            source_counts=dict(ui_state.get("source_counts") or {}),
            confidence=float(confidence or 0.0),
            warnings=[item for item in warnings if item],
            cursor=dict(cursor or {}),
            selection=dict(selection or {}),
        )


@dataclass
class CoworkSession:
    session_id: str
    execution_id: str = ""
    user_id: str = "local"
    channel: str = "cli"
    mode: str = "communication"
    objective: str = ""
    objective_kind: str = "communication"
    selected_model: str = "chat"
    selected_provider: str = ""
    budget: dict[str, Any] = field(default_factory=dict)
    verification_policy: dict[str, Any] = field(default_factory=dict)
    memory_policy: dict[str, Any] = field(default_factory=dict)
    active_task: dict[str, Any] = field(default_factory=dict)
    screen_state: ScreenState | None = None
    tool_decision: ToolDecision | None = None
    telemetry: dict[str, Any] = field(default_factory=dict)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    turn_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_user_input: str = ""
    last_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["screen_state"] = self.screen_state.to_dict() if isinstance(self.screen_state, ScreenState) else {}
        payload["tool_decision"] = self.tool_decision.to_dict() if isinstance(self.tool_decision, ToolDecision) else {}
        return payload


class CoworkRuntime:
    def __init__(self):
        self._sessions: dict[str, CoworkSession] = {}
        self._contexts: dict[str, SmartContextManager] = {}
        self._checkpoint_manager: CheckpointManager | None = None

    @staticmethod
    def session_key(user_id: Any, channel: str) -> str:
        raw_user, _ = _coerce_user_id(user_id)
        raw_channel = str(channel or "cli").strip() or "cli"
        return f"{raw_user}::{raw_channel}"

    def _manager(self, session_key: str) -> SmartContextManager:
        manager = self._contexts.get(session_key)
        if manager is None:
            manager = SmartContextManager(max_turns=12, max_tokens=4000)
            self._contexts[session_key] = manager
        return manager

    def _checkpoint_store(self) -> CheckpointManager:
        if self._checkpoint_manager is None:
            self._checkpoint_manager = CheckpointManager()
        return self._checkpoint_manager

    def get_session(self, session_key: str) -> CoworkSession | None:
        return self._sessions.get(session_key)

    def _mode_from_input(
        self,
        user_input: str,
        quick_intent: Any = None,
        attachments: list[str] | None = None,
        capability_domain: str = "",
    ) -> str:
        low = _normalize_text(user_input)
        category = str(getattr(quick_intent, "category", "") or "").strip().lower()
        if category in {"greeting", "chat"} or _is_greeting_like(low):
            return "communication"
        if _looks_like_screen_task(low, attachments=attachments, capability_domain=capability_domain):
            return "screen"
        if _looks_like_research_task(low):
            return "research"
        if _looks_like_code_task(low):
            return "code"
        if _looks_like_file_task(low):
            return "file"
        if _looks_like_browser_task(low):
            return "browser"
        if category == "calculation":
            return "communication"
        return "task"

    def _budget_for_mode(self, mode: str, runtime_policy: dict[str, Any] | None = None) -> dict[str, Any]:
        policy = runtime_policy if isinstance(runtime_policy, dict) else {}
        execution = policy.get("execution", {}) if isinstance(policy.get("execution"), dict) else {}
        base = {
            "communication": {"max_tokens": 300, "max_tool_calls": 0, "max_verify_calls": 0, "deadline_s": 2.0},
            "screen": {"max_tokens": 800, "max_tool_calls": 4, "max_verify_calls": 2, "deadline_s": 20.0},
            "browser": {"max_tokens": 1000, "max_tool_calls": 4, "max_verify_calls": 2, "deadline_s": 25.0},
            "file": {"max_tokens": 800, "max_tool_calls": 4, "max_verify_calls": 2, "deadline_s": 20.0},
            "research": {"max_tokens": 2048, "max_tool_calls": 6, "max_verify_calls": 3, "deadline_s": 45.0},
            "code": {"max_tokens": 2048, "max_tool_calls": 6, "max_verify_calls": 3, "deadline_s": 45.0},
            "task": {"max_tokens": 1200, "max_tool_calls": 5, "max_verify_calls": 2, "deadline_s": 30.0},
        }.get(mode, {"max_tokens": 1200, "max_tool_calls": 5, "max_verify_calls": 2, "deadline_s": 30.0})
        if bool(execution.get("prefer_short_turns", False)):
            base["max_tokens"] = min(int(base["max_tokens"]), 400)
        return base

    def _verification_policy(self, mode: str, runtime_policy: dict[str, Any] | None = None) -> dict[str, Any]:
        policy = runtime_policy if isinstance(runtime_policy, dict) else {}
        execution = policy.get("execution", {}) if isinstance(policy.get("execution"), dict) else {}
        skip_chat = bool(execution.get("skip_verify_for_chat", True))
        return {
            "skip_verify": bool(mode == "communication" and skip_chat),
            "require_verify": bool(mode in {"screen", "browser", "research", "code", "file", "task"}),
            "max_critic_calls": 0 if mode == "communication" else 3,
        }

    def _memory_policy(self, mode: str) -> dict[str, Any]:
        if mode == "communication":
            return {
                "scope": "communication_minimal",
                "include_recent_conversation": False,
                "include_task_history": False,
                "include_knowledge": False,
            }
        return {
            "scope": "task_routed",
            "include_recent_conversation": True,
            "include_task_history": True,
            "include_knowledge": True,
        }

    def _selected_model(self, mode: str, tool_decision: ToolDecision | None = None) -> str:
        if mode == "communication":
            return "chat"
        if mode in {"screen", "browser", "file"}:
            return "inference"
        if mode in {"code", "research"}:
            return "reasoning"
        if tool_decision and (tool_decision.risk_level == "high" or tool_decision.requires_approval):
            return "reasoning"
        return "inference"

    def start_session(
        self,
        *,
        user_id: Any,
        channel: str,
        objective: str,
        run_id: str = "",
        quick_intent: Any = None,
        attachments: list[str] | None = None,
        capability_domain: str = "",
        runtime_policy: dict[str, Any] | None = None,
        active_task: dict[str, Any] | None = None,
        tool_decision: ToolDecision | None = None,
    ) -> CoworkSession:
        key = self.session_key(user_id, channel)
        raw_user, _ = _coerce_user_id(user_id)
        mode = self._mode_from_input(objective, quick_intent=quick_intent, attachments=attachments, capability_domain=capability_domain)
        session = self._sessions.get(key)
        if session is None:
            session = CoworkSession(
                session_id=key,
                execution_id=key,
                user_id=raw_user,
                channel=str(channel or "cli").strip() or "cli",
                mode=mode,
                objective=str(objective or "").strip(),
                objective_kind="communication" if mode == "communication" else "task",
                selected_model=self._selected_model(mode, tool_decision),
                budget=self._budget_for_mode(mode, runtime_policy),
                verification_policy=self._verification_policy(mode, runtime_policy),
                memory_policy=self._memory_policy(mode),
                active_task=dict(active_task or {}),
                tool_decision=tool_decision,
            )
            self._sessions[key] = session
        else:
            session.user_id = raw_user
            session.channel = str(channel or "cli").strip() or "cli"
            session.mode = mode or session.mode
            session.objective = str(objective or session.objective or "").strip()
            session.objective_kind = "communication" if session.mode == "communication" else "task"
            session.selected_model = self._selected_model(session.mode, tool_decision or session.tool_decision)
            session.budget = self._budget_for_mode(session.mode, runtime_policy)
            session.verification_policy = self._verification_policy(session.mode, runtime_policy)
            session.memory_policy = self._memory_policy(session.mode)
            if active_task:
                session.active_task = dict(active_task)
            if tool_decision is not None:
                session.tool_decision = tool_decision
        session.execution_id = key
        session.updated_at = time.time()
        if run_id:
            session.telemetry["last_run_id"] = str(run_id)
        if runtime_policy:
            session.telemetry["runtime_policy_name"] = str(runtime_policy.get("name") or "custom")
        return session

    def update_session(self, session_key: str, **updates: Any) -> CoworkSession | None:
        session = self._sessions.get(session_key)
        if session is None:
            return None
        for key, value in updates.items():
            if not hasattr(session, key):
                continue
            setattr(session, key, value)
        session.updated_at = time.time()
        return session

    def observe_turn(
        self,
        *,
        session_key: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> CoworkSession | None:
        session = self._sessions.get(session_key)
        if session is None:
            return None
        manager = self._manager(session_key)
        manager.add_turn(role, content, metadata or {})
        session.turn_count += 1
        session.updated_at = time.time()
        if role == "user":
            session.last_user_input = str(content or "")
        elif role == "assistant":
            session.last_response = str(content or "")
        session.telemetry["context_summary"] = manager.summarize_context()
        session.telemetry["intent_evolution"] = manager.identify_intent_evolution()
        return session

    def _topic_hint(self, text: str) -> str:
        low = _normalize_text(text)
        if not low:
            return ""
        tokens = [
            token
            for token in re.findall(r"[a-z0-9çğıöşü]+", low)
            if token not in {
                "ve",
                "ile",
                "icin",
                "için",
                "bir",
                "bu",
                "şu",
                "sunu",
                "bana",
                "lütfen",
                "lutfen",
                "göster",
                "goster",
                "yap",
                "et",
                "the",
                "and",
            }
        ]
        return " ".join(tokens[:5]).strip()

    def _render_preferences(self, prefs: dict[str, Any]) -> str:
        if not isinstance(prefs, dict) or not prefs:
            return ""
        lines = ["### USER PREFERENCES"]
        preferred_language = prefs.get("preferred_language")
        if preferred_language:
            lines.append(f"- Preferred language: {preferred_language}")
        top_topics = prefs.get("top_topics")
        if isinstance(top_topics, dict) and top_topics:
            pairs = sorted(top_topics.items(), key=lambda item: item[1], reverse=True)[:5]
            lines.append("- Top topics: " + ", ".join(f"{key}({value})" for key, value in pairs))
        response_bias = prefs.get("response_length_bias")
        if response_bias:
            lines.append(f"- Response bias: {response_bias}")
        return "\n".join(lines).strip()

    def _render_recent_conversations(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return ""
        lines = ["### RECENT CONVERSATION"]
        for row in rows[-4:]:
            role = str(row.get("role") or "user").upper()
            content = str(row.get("content") or row.get("user_message") or "").strip()
            if content:
                lines.append(f"{role}: {content[:240]}")
        return "\n".join(lines).strip()

    async def build_memory_context(
        self,
        *,
        session: CoworkSession,
        user_input: str,
        memory_store: Any = None,
        user_profile: Any = None,
        recent_turns: list[dict[str, Any]] | None = None,
        query_limit: int = 5,
    ) -> dict[str, Any]:
        mode = str(session.mode or "communication").strip().lower()
        raw_user_id, numeric_user_id = _coerce_user_id(session.user_id)
        query = str(user_input or session.objective or "").strip()
        topic_hint = self._topic_hint(query)
        manager = self._manager(session.session_id)
        session_summary = manager.summarize_context()
        topic_shift = bool(
            mode == "communication"
            and not _references_prior_context(query)
            and (_is_greeting_like(query) or len(query.split()) <= 4)
        )
        policy = self._memory_policy(mode)
        policy["topic_shift_detected"] = topic_shift
        policy["topic_hint"] = topic_hint

        if memory_store is None:
            try:
                from core.kernel import kernel

                memory_store = getattr(kernel, "memory", None)
            except Exception:
                memory_store = None

        preferences: dict[str, Any] = {}
        recent_rows: list[dict[str, Any]] = []
        task_rows: list[dict[str, Any]] = []
        knowledge_rows: list[dict[str, Any]] = []
        memory_results: dict[str, Any] = {}
        memory_text_parts: list[str] = []

        if memory_store is not None:
            try:
                if hasattr(memory_store, "get_user_preferences"):
                    preferences = memory_store.get_user_preferences(numeric_user_id) or {}
                elif hasattr(memory_store, "get_all_preferences"):
                    preferences = memory_store.get_all_preferences(numeric_user_id) or {}
            except Exception:
                preferences = {}

            try:
                if hasattr(memory_store, "get_recent_conversations") and not topic_shift:
                    recent_rows = memory_store.get_recent_conversations(numeric_user_id, limit=query_limit or 4) or []
                elif hasattr(memory_store, "get_history") and not topic_shift:
                    recent_rows = memory_store.get_history(numeric_user_id, limit=query_limit or 4, hours=24) or []
            except Exception:
                recent_rows = []

            try:
                if mode != "communication" and hasattr(memory_store, "get_task_history"):
                    task_rows = memory_store.get_task_history(numeric_user_id, limit=query_limit or 4) or []
            except Exception:
                task_rows = []

            try:
                if mode != "communication" and topic_hint and hasattr(memory_store, "query_knowledge"):
                    knowledge_rows = memory_store.query_knowledge(entity=topic_hint) or []
            except Exception:
                knowledge_rows = []

        if mode != "communication":
            try:
                from core.memory.unified import memory as unified_memory
                from core.memory.context_optimizer import context_optimizer

                memory_results = await unified_memory.recall(raw_user_id, query, limit=max(1, int(query_limit or 5)))
                optimized = context_optimizer.optimize(memory_results, query)
                if optimized:
                    memory_text_parts.append(optimized.strip())
            except Exception as exc:
                logger.debug(f"Unified memory recall skipped: {exc}")

        if mode == "communication":
            if not topic_shift and recent_rows:
                memory_text_parts.append(self._render_recent_conversations(recent_rows))
            if session_summary:
                memory_text_parts.append("### ACTIVE SESSION CONTEXT\n" + session_summary)
        else:
            if recent_rows:
                memory_text_parts.append(self._render_recent_conversations(recent_rows))
            if task_rows:
                lines = ["### TASK HISTORY"]
                for row in task_rows[:4]:
                    goal = str(row.get("goal") or "").strip()
                    outcome = str(row.get("outcome") or "").strip()
                    lines.append(f"- {goal[:180]}{f' -> {outcome[:120]}' if outcome else ''}")
                memory_text_parts.append("\n".join(lines).strip())
            if knowledge_rows:
                lines = ["### RELEVANT KNOWLEDGE"]
                for row in knowledge_rows[:4]:
                    value = str(row.get("value") or row.get("content") or "").strip()
                    if value:
                        lines.append(f"- {value[:220]}")
                memory_text_parts.append("\n".join(lines).strip())
            if session_summary:
                memory_text_parts.append("### ACTIVE SESSION CONTEXT\n" + session_summary)

        pref_block = self._render_preferences(preferences)
        if pref_block:
            memory_text_parts.append(pref_block)

        memory_text = "\n\n".join(part for part in memory_text_parts if part).strip()
        session.memory_policy = dict(policy)
        session.telemetry["memory_scope"] = policy.get("scope", "task_routed")
        session.telemetry["topic_shift_detected"] = topic_shift
        session.telemetry["memory_sources"] = {
            "recent_conversations": len(recent_rows),
            "task_history": len(task_rows),
            "knowledge": len(knowledge_rows),
        }
        session.telemetry["memory_results_present"] = bool(memory_results)
        session.updated_at = time.time()

        return {
            "text": memory_text,
            "policy": policy,
            "memory_scope": policy.get("scope", "task_routed"),
            "topic_shift_detected": topic_shift,
            "topic_hint": topic_hint,
            "recent_conversations": recent_rows,
            "task_history": task_rows,
            "knowledge": knowledge_rows,
            "preferences": preferences,
            "memory_results": memory_results,
            "session_summary": session_summary,
        }

    def should_capture_screen(
        self,
        user_input: str,
        *,
        attachments: list[str] | None = None,
        capability_domain: str = "",
    ) -> bool:
        return _looks_like_screen_task(user_input, attachments=attachments, capability_domain=capability_domain)

    async def collect_screen_state(
        self,
        goal: str = "",
        *,
        task_state: dict[str, Any] | None = None,
        screen_operator_runner: Callable[..., Awaitable[dict[str, Any]]] | None = None,
        clipboard_reader: Callable[[], Awaitable[dict[str, Any]]] | None = None,
        display_info_reader: Callable[[], Awaitable[dict[str, Any]]] | None = None,
        window_context_reader: Callable[[], dict[str, Any]] | None = None,
    ) -> ScreenState:
        runner = screen_operator_runner
        if runner is None:
            from core.capabilities.screen_operator.runtime import run_screen_operator

            runner = run_screen_operator

        try:
            observation = await runner(
                instruction=str(goal or "Ekranı yapısal olarak özetle."),
                mode="inspect",
                final_screenshot=True,
                max_actions=1,
                task_state=dict(task_state or {}),
            )
        except Exception as exc:
            observation = {"success": False, "error": str(exc)}

        clipboard_payload: dict[str, Any] = {}
        display_payload: dict[str, Any] = {}
        window_context: dict[str, Any] = {}

        if clipboard_reader is None:
            try:
                from tools.system_tools import read_clipboard

                clipboard_reader = read_clipboard
            except Exception:
                clipboard_reader = None
        if display_info_reader is None:
            try:
                from tools.system_tools import get_display_info

                display_info_reader = get_display_info
            except Exception:
                display_info_reader = None
        if window_context_reader is None:
            try:
                from core.os_adapters.window_manager import get_active_window_context

                window_context_reader = get_active_window_context
            except Exception:
                window_context_reader = None

        async def _read_clipboard() -> dict[str, Any]:
            if clipboard_reader is None:
                return {}
            try:
                return await clipboard_reader()
            except Exception:
                return {}

        async def _read_display_info() -> dict[str, Any]:
            if display_info_reader is None:
                return {}
            try:
                return await display_info_reader()
            except Exception:
                return {}

        if clipboard_reader or display_info_reader:
            clipboard_payload, display_payload = await asyncio.gather(_read_clipboard(), _read_display_info())

        if window_context_reader is not None:
            try:
                window_context = dict(window_context_reader() or {})
            except Exception:
                window_context = {}

        state = ScreenState.from_observation(
            observation if isinstance(observation, dict) else {},
            clipboard_text=str(clipboard_payload.get("text") or ""),
            display_info=display_payload if isinstance(display_payload, dict) else {},
            cursor=window_context.get("cursor") if isinstance(window_context.get("cursor"), dict) else None,
            selection=window_context.get("selection") if isinstance(window_context.get("selection"), dict) else None,
        )
        if not state.frontmost_app and str(window_context.get("app") or "").strip():
            state.frontmost_app = str(window_context.get("app") or "").strip()
        if not state.active_window and str(window_context.get("title") or "").strip():
            state.active_window = {"title": str(window_context.get("title") or "").strip(), "bounds": {}}
        if not state.summary:
            state.summary = str(observation.get("summary") or observation.get("message") or "").strip()
        if not state.screenshot_path:
            state.screenshot_path = str(
                ((observation.get("final_observation") if isinstance(observation.get("final_observation"), dict) else {}) or {})
                .get("screenshot", {})
                .get("path", "")
            ).strip()
        state.warnings.extend(
            [
                str(observation.get("error") or "").strip(),
                str(clipboard_payload.get("error") or "").strip(),
                str(display_payload.get("error") or "").strip(),
            ]
        )
        state.warnings = [item for item in state.warnings if item]
        return state

    def score_tool(
        self,
        tool_name: str,
        *,
        params: dict[str, Any] | None = None,
        user_input: str = "",
        candidate_role: str = "",
        usage_snapshot: dict[str, Any] | None = None,
    ) -> ToolDecision:
        from core.tool_schemas_registry import get_schema_registry

        registry = get_schema_registry()
        schema = registry.get(tool_name)
        usage = usage_snapshot or get_tool_usage_snapshot()
        stats = dict((usage or {}).get("stats", {})).get(tool_name, {})

        score = 0.5
        rationale: list[str] = []
        risk_level = "low"
        requires_approval = False
        estimated_latency_ms = int(float(stats.get("avg_latency_ms", 0.0) or 0.0))

        if schema is None:
            score -= 0.12
            rationale.append("schema_missing")
        else:
            risk_level = str(schema.risk_level or "low").strip().lower() or "low"
            requires_approval = bool(schema.requires_approval)
            risk_penalty = {"low": 0.0, "medium": 0.12, "high": 0.28}.get(risk_level, 0.1)
            score -= risk_penalty
            rationale.append(f"risk={risk_level}")
            if requires_approval:
                score -= 0.2
                rationale.append("requires_approval")

        success_rate = float(stats.get("success_rate", 0.0) or 0.0)
        if success_rate:
            score += min(0.22, success_rate / 100.0 * 0.22)
            rationale.append(f"success_rate={success_rate:.2f}")

        if estimated_latency_ms:
            latency_penalty = min(0.15, estimated_latency_ms / 3000.0 * 0.15)
            score -= latency_penalty
            rationale.append(f"avg_latency_ms={estimated_latency_ms}")

        low = _normalize_text(user_input)
        if tool_name in low:
            score += 0.1
            rationale.append("explicitly_requested")

        if candidate_role:
            rationale.append(f"candidate_role={candidate_role}")

        score = max(0.0, min(1.0, score))
        model_tier = self._selected_model(
            self._mode_from_input(user_input, attachments=params.get("attachments") if isinstance(params, dict) else None),
            tool_decision=ToolDecision(
                tool_name=tool_name,
                score=score,
                risk_level=risk_level,
                requires_approval=requires_approval,
                estimated_latency_ms=estimated_latency_ms,
                model_tier="inference",
            ),
        )

        return ToolDecision(
            tool_name=tool_name,
            score=score,
            risk_level=risk_level,
            requires_approval=requires_approval,
            estimated_latency_ms=estimated_latency_ms,
            model_tier=model_tier,
            rationale=rationale,
            available=schema is not None,
            source="schema+usage",
            params=dict(params or {}),
        )

    def rank_tools(
        self,
        tool_names: list[str],
        *,
        user_input: str = "",
        params_by_tool: dict[str, dict[str, Any]] | None = None,
    ) -> list[ToolDecision]:
        ranked = [
            self.score_tool(
                tool_name,
                params=(params_by_tool or {}).get(tool_name, {}),
                user_input=user_input,
            )
            for tool_name in tool_names
        ]
        return sorted(ranked, key=lambda item: item.score, reverse=True)

    def checkpoint(
        self,
        *,
        session: CoworkSession,
        stage: str,
        state: dict[str, Any],
        step_number: int = 0,
        checkpoint_type: str = "phase_complete",
        progress_percentage: float = 0.0,
        estimated_time_remaining: float = 0.0,
    ) -> str:
        manager = self._checkpoint_store()
        payload = {
            "session": session.to_dict(),
            "stage": str(stage or "").strip(),
            "state": dict(state or {}),
        }
        checkpoint_id = manager.create_checkpoint(
            execution_id=session.execution_id or session.session_id,
            state=payload,
            step_number=int(step_number or session.turn_count or 0),
            checkpoint_type=str(checkpoint_type or "phase_complete"),
            task_id=str(session.active_task.get("task_id") or "") or None,
            group_id=str(session.active_task.get("group_id") or "") or None,
            progress_percentage=float(progress_percentage or 0.0),
            estimated_time_remaining=float(estimated_time_remaining or 0.0),
        )
        session.checkpoints.append(
            {
                "checkpoint_id": checkpoint_id,
                "stage": str(stage or ""),
                "step_number": int(step_number or session.turn_count or 0),
                "created_at": time.time(),
            }
        )
        session.telemetry["latest_checkpoint_id"] = checkpoint_id
        session.updated_at = time.time()
        return checkpoint_id

    def resume_last_checkpoint(self, session_key: str) -> dict[str, Any] | None:
        manager = self._checkpoint_store()
        try:
            state = manager.get_recovery_state(session_key)
            return state if isinstance(state, dict) else None
        except Exception:
            return None

    def finalize_turn(
        self,
        *,
        session_key: str,
        response_text: str,
        success: bool,
        action: str,
        started_at: float,
        metadata: dict[str, Any] | None = None,
    ) -> CoworkSession | None:
        session = self._sessions.get(session_key)
        if session is None:
            return None
        self.observe_turn(
            session_key=session_key,
            role="assistant",
            content=response_text,
            metadata=dict(metadata or {}),
        )
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        session.telemetry["last_turn"] = {
            "action": str(action or "chat"),
            "success": bool(success),
            "duration_ms": duration_ms,
            "metadata": dict(metadata or {}),
        }
        try:
            checkpoint_state = {
                "response_text": str(response_text or ""),
                "success": bool(success),
                "action": str(action or ""),
                "metadata": dict(metadata or {}),
                "telemetry": dict(session.telemetry),
            }
            self.checkpoint(
                session=session,
                stage="turn_complete",
                state=checkpoint_state,
                step_number=session.turn_count,
                checkpoint_type="task_complete" if success else "phase_complete",
                progress_percentage=100.0 if success else 50.0,
                estimated_time_remaining=0.0,
            )
        except Exception as exc:
            logger.debug(f"checkpoint skipped: {exc}")
        return session


_cowork_runtime: CoworkRuntime | None = None


def get_cowork_runtime() -> CoworkRuntime:
    global _cowork_runtime
    if _cowork_runtime is None:
        _cowork_runtime = CoworkRuntime()
    return _cowork_runtime


__all__ = [
    "CoworkRuntime",
    "CoworkSession",
    "ScreenState",
    "ToolDecision",
    "get_cowork_runtime",
]
