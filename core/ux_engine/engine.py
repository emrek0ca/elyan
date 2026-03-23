"""
UXEngine — Premium User Experience Orchestrator
Manages conversational flow, streaming, suggestions, context continuity, and multi-modal input.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List, AsyncIterator
from datetime import datetime

from .conversation_flow import ConversationFlowManager
from .suggestion_engine import SuggestionEngine
from .context_continuity import ContextContinuityTracker
from .streaming_handler import StreamingHandler


@dataclass
class UXResult:
    """Premium UX execution result."""
    success: bool
    text: str
    response: str = ""
    suggestions: List[str] = None
    streaming_enabled: bool = False
    context_used: Dict[str, Any] = None
    multimodal_inputs: List[str] = None
    timestamp: float = 0.0
    elapsed: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = datetime.now().timestamp()
        if self.suggestions is None:
            self.suggestions = []
        if self.context_used is None:
            self.context_used = {}
        if self.multimodal_inputs is None:
            self.multimodal_inputs = []

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert to JSON."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class UXEngine:
    """
    Premium UX Engine — orchestrates all UX features.
    - Conversational flow (natural language understanding)
    - Real-time streaming feedback
    - Proactive suggestions ("I noticed X, fix Y?")
    - Context continuity (never repeat questions)
    - Multi-modal input handling (voice, text, image, file)
    """

    def __init__(self):
        self.flow_manager = ConversationFlowManager()
        self.suggestion_engine = SuggestionEngine()
        self.context_tracker = ContextContinuityTracker()
        self.streaming_handler = StreamingHandler()
        self._session_cache: Dict[str, Dict[str, Any]] = {}

    async def process_message(
        self,
        user_message: str,
        session_id: str = "default",
        multimodal_inputs: Optional[List[str]] = None,
        enable_streaming: bool = False,
        context_data: Optional[Dict[str, Any]] = None,
    ) -> UXResult | AsyncIterator[str]:
        """
        Process user message with premium UX features.

        Args:
            user_message: The user's input
            session_id: Unique session identifier
            multimodal_inputs: List of file paths (images, audio, etc.)
            enable_streaming: Enable real-time streaming response
            context_data: Additional context dict

        Returns:
            UXResult or AsyncIterator[str] if streaming
        """
        start_time = time.time()
        context_data = context_data or {}

        # 1. Ensure session exists
        if session_id not in self._session_cache:
            self._session_cache[session_id] = {
                "created_at": datetime.now().isoformat(),
                "messages": [],
                "questions_asked": [],
            }

        session = self._session_cache[session_id]

        # 2. Check context continuity — avoid repeating questions
        if self.context_tracker.is_repeat_question(user_message, session_id):
            context_data["repeat_question"] = True

        # 3. Analyze conversational flow
        flow_analysis = self.flow_manager.analyze(user_message, session)

        # 4. Generate proactive suggestions based on context
        suggestions = await self.suggestion_engine.generate_suggestions(
            user_message=user_message,
            session_data=session,
            flow_analysis=flow_analysis,
            context_data=context_data,
        )

        # 5. Handle multi-modal inputs
        multimodal_context = {}
        if multimodal_inputs:
            multimodal_context = await self._process_multimodal(multimodal_inputs)

        # 6. Prepare response
        combined_context = {**context_data, **multimodal_context}
        response_text = self._build_response(
            user_message=user_message,
            flow_analysis=flow_analysis,
            suggestions=suggestions,
            context_data=combined_context,
        )

        # 7. Stream or return result
        elapsed = time.time() - start_time
        result = UXResult(
            success=True,
            text=response_text,
            response=response_text,
            suggestions=suggestions,
            streaming_enabled=enable_streaming,
            context_used=combined_context,
            multimodal_inputs=multimodal_inputs or [],
            elapsed=elapsed,
        )

        # Update session history
        session["messages"].append(
            {
                "timestamp": datetime.now().isoformat(),
                "user": user_message,
                "assistant": response_text,
            }
        )
        session["questions_asked"].append(user_message)
        self.context_tracker.record_question(user_message, session_id)

        if enable_streaming:
            return self.streaming_handler.stream_response(response_text)
        else:
            return result

    async def _process_multimodal(
        self, file_paths: List[str]
    ) -> Dict[str, Any]:
        """
        Process multi-modal inputs (images, audio, documents, video).

        Returns context dict summarizing inputs.
        """
        context = {"multimodal_inputs": []}

        for path in file_paths:
            # Identify media type
            media_info = {
                "path": path,
                "detected_at": datetime.now().isoformat(),
            }

            # Basic type detection
            if path.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                media_info["type"] = "image"
            elif path.lower().endswith((".mp3", ".wav", ".ogg", ".m4a", ".aac")):
                media_info["type"] = "audio"
            elif path.lower().endswith((".mp4", ".avi", ".mov", ".mkv")):
                media_info["type"] = "video"
            elif path.lower().endswith((".pdf", ".doc", ".docx", ".txt")):
                media_info["type"] = "document"
            else:
                media_info["type"] = "unknown"

            context["multimodal_inputs"].append(media_info)

        return context

    def _build_response(
        self,
        user_message: str,
        flow_analysis: Any,
        suggestions: List[str],
        context_data: Dict[str, Any],
    ) -> str:
        """Build conversational response with suggestions."""
        lines = []

        # Primary response
        lines.append(f"✓ İşlenmiş: {user_message[:50]}...")
        lines.append("")

        # Flow analysis insight
        intent = getattr(flow_analysis, "intent", None)
        if intent:
            lines.append(f"📌 Intent: {intent}")

        # Suggestions
        if suggestions:
            lines.append("")
            lines.append("💡 Öneriler:")
            for i, suggestion in enumerate(suggestions, 1):
                lines.append(f"  [{i}] {suggestion}")

        # Context continuity
        if context_data.get("repeat_question"):
            lines.append("")
            lines.append("⚠️ (Bu soruyu daha önce sordunuz — cached yanıt var)")

        # Multi-modal summary
        if context_data.get("multimodal_inputs"):
            lines.append("")
            lines.append("📎 Attachments:")
            for item in context_data["multimodal_inputs"]:
                lines.append(f"  • {item.get('type', 'unknown')}: {item['path']}")

        return "\n".join(lines)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve session data."""
        return self._session_cache.get(session_id)

    def list_sessions(self) -> List[str]:
        """List all active session IDs."""
        return list(self._session_cache.keys())

    def clear_session(self, session_id: str) -> bool:
        """Clear session data."""
        if session_id in self._session_cache:
            del self._session_cache[session_id]
            return True
        return False


__all__ = ["UXEngine", "UXResult"]
