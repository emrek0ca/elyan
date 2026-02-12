"""
Advanced Features Module
Cutting-edge capabilities: streaming, parallelization, voice, proactive suggestions
"""

import asyncio
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import json
from utils.logger import get_logger

logger = get_logger("advanced_features")


@dataclass
class StreamingResponse:
    """Represents a streaming response with progressive output"""
    request_id: str
    content: str = ""
    chunks: List[str] = None
    completed: bool = False
    timestamp: datetime = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.chunks is None:
            self.chunks = []
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.metadata is None:
            self.metadata = {}

    def add_chunk(self, chunk: str):
        """Add a chunk to streaming response"""
        self.chunks.append(chunk)
        self.content += chunk

    def complete(self):
        """Mark response as complete"""
        self.completed = True


@dataclass
class ProactiveSuggestion:
    """Proactive task suggestion for user"""
    task: str
    description: str
    priority: str  # low, medium, high
    reason: str
    confidence: float  # 0-1
    recommended_time: Optional[datetime] = None


class StreamingProcessor:
    """Handles streaming responses for long operations"""

    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self.active_streams: Dict[str, StreamingResponse] = {}
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def stream_operation(
        self,
        request_id: str,
        operation: Callable,
        on_chunk: Optional[Callable] = None,
        **kwargs
    ) -> StreamingResponse:
        """Execute operation with streaming output"""
        async with self.semaphore:
            response = StreamingResponse(request_id=request_id)
            self.active_streams[request_id] = response

            try:
                async for chunk in operation(**kwargs):
                    response.add_chunk(chunk)
                    if on_chunk:
                        await on_chunk(chunk)

                response.complete()
                logger.info(f"Streaming completed: {request_id}")

            except Exception as e:
                logger.error(f"Streaming error: {e}")
                response.metadata["error"] = str(e)

            finally:
                del self.active_streams[request_id]

            return response

    def get_stream(self, request_id: str) -> Optional[StreamingResponse]:
        """Get active stream by ID"""
        return self.active_streams.get(request_id)

    def get_streams(self) -> Dict[str, StreamingResponse]:
        """Get all active streams"""
        return self.active_streams.copy()


class ParallelExecutor:
    """Executes independent tasks in parallel with rate limiting"""

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.semaphore = asyncio.Semaphore(max_workers)
        self.task_results: Dict[str, Any] = {}

    async def execute_parallel(
        self,
        tasks: List[tuple[str, Callable, Dict[str, Any]]],
        timeout: Optional[int] = 30
    ) -> Dict[str, Any]:
        """
        Execute multiple tasks in parallel

        Args:
            tasks: List of (task_id, callable, kwargs) tuples
            timeout: Global timeout in seconds

        Returns:
            Dict mapping task_id to result
        """
        results = {}

        async def run_task(task_id: str, func: Callable, kwargs: Dict):
            async with self.semaphore:
                try:
                    if asyncio.iscoroutinefunction(func):
                        result = await asyncio.wait_for(
                            func(**kwargs),
                            timeout=timeout
                        )
                    else:
                        result = func(**kwargs)
                    results[task_id] = {"success": True, "result": result}
                except asyncio.TimeoutError:
                    results[task_id] = {
                        "success": False,
                        "error": f"Timeout after {timeout}s"
                    }
                except Exception as e:
                    results[task_id] = {
                        "success": False,
                        "error": str(e)
                    }

        # Create tasks
        coroutines = [
            run_task(task_id, func, kwargs)
            for task_id, func, kwargs in tasks
        ]

        # Run all tasks
        await asyncio.gather(*coroutines, return_exceptions=True)

        self.task_results = results
        return results


class ProactiveSuggestionEngine:
    """Suggests tasks based on user patterns and context"""

    def __init__(self, history_file: Optional[Path] = None):
        self.history_file = history_file or Path.home() / ".wiqo" / "suggestions_history.json"
        self.suggestions: List[ProactiveSuggestion] = []
        self.user_patterns: Dict[str, Any] = {}
        self._load_history()

    def _load_history(self):
        """Load suggestion history"""
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    self.user_patterns = data.get("patterns", {})
            except Exception as e:
                logger.warning(f"Could not load suggestion history: {e}")

    def _save_history(self):
        """Save suggestion history"""
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, 'w') as f:
                json.dump({"patterns": self.user_patterns}, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save suggestion history: {e}")

    def analyze_user_behavior(
        self,
        recent_commands: List[str],
        user_preferences: Dict[str, Any]
    ) -> List[ProactiveSuggestion]:
        """
        Analyze user behavior and suggest tasks

        Args:
            recent_commands: List of recent user commands
            user_preferences: User preference dictionary

        Returns:
            List of proactive suggestions
        """
        suggestions = []

        # Pattern 1: Regular research pattern
        if any("arastir" in cmd.lower() for cmd in recent_commands[-5:]):
            suggestions.append(ProactiveSuggestion(
                task="organize_research",
                description="Yakın zamanda yapılan araştırmaları organize et",
                priority="medium",
                reason="Regular research pattern detected",
                confidence=0.7
            ))

        # Pattern 2: Document creation pattern
        doc_commands = [cmd for cmd in recent_commands[-10:] if any(
            x in cmd.lower() for x in ["olustur", "yaz", "ekle", "belge"]
        )]
        if len(doc_commands) > 2:
            suggestions.append(ProactiveSuggestion(
                task="suggest_templates",
                description="Sık kullanılan belge şablonları öner",
                priority="medium",
                reason="Document creation pattern detected",
                confidence=0.65
            ))

        # Pattern 3: File organization pattern
        if any("tas" in cmd.lower() or "klas" in cmd.lower() for cmd in recent_commands[-7:]):
            suggestions.append(ProactiveSuggestion(
                task="organize_files",
                description="Masaüstü ve belgeler klasörünü organize et",
                priority="low",
                reason="File organization pattern detected",
                confidence=0.6
            ))

        # Pattern 4: Notes taking pattern
        if any("not" in cmd.lower() for cmd in recent_commands[-5:]):
            suggestions.append(ProactiveSuggestion(
                task="backup_notes",
                description="Notları yedekle ve organize et",
                priority="medium",
                reason="Note taking pattern detected",
                confidence=0.75
            ))

        # Sort by confidence
        suggestions.sort(key=lambda x: x.confidence, reverse=True)

        self.suggestions = suggestions
        return suggestions

    def get_next_suggestion(self) -> Optional[ProactiveSuggestion]:
        """Get next suggestion in queue"""
        if self.suggestions:
            return self.suggestions.pop(0)
        return None

    def record_suggestion_feedback(
        self,
        task: str,
        accepted: bool,
        feedback: Optional[str] = None
    ):
        """Record user feedback on suggestion"""
        if task not in self.user_patterns:
            self.user_patterns[task] = {"accepted": 0, "rejected": 0}

        if accepted:
            self.user_patterns[task]["accepted"] += 1
        else:
            self.user_patterns[task]["rejected"] += 1

        if feedback:
            self.user_patterns[task]["last_feedback"] = feedback

        self._save_history()


class ContextEnricher:
    """Enriches context with historical and semantic information"""

    def __init__(self):
        self.context_cache: Dict[str, Dict[str, Any]] = {}
        self.relationships: Dict[str, List[str]] = {}

    async def enrich_context(
        self,
        user_input: str,
        recent_history: List[str],
        user_preferences: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Enrich context for better understanding

        Returns:
            Enhanced context dictionary
        """
        enriched = {
            "user_input": user_input,
            "intent_hints": self._extract_intent_hints(user_input),
            "context_history": self._analyze_history(recent_history),
            "user_profile": self._build_user_profile(user_preferences),
            "temporal_context": self._get_temporal_context(),
            "entity_relationships": self._extract_relationships(user_input, recent_history),
        }

        return enriched

    def _extract_intent_hints(self, text: str) -> Dict[str, float]:
        """Extract intent hints from text"""
        hints = {}

        # Keyword-based hints
        keywords = {
            "araştırma": "research",
            "belge": "document",
            "dosya": "file",
            "not": "note",
            "takvim": "calendar",
            "posta": "email",
            "code": "programming",
        }

        for keyword, intent in keywords.items():
            if keyword in text.lower():
                hints[intent] = 0.6

        return hints

    def _analyze_history(self, history: List[str]) -> Dict[str, Any]:
        """Analyze recent history"""
        return {
            "commands_count": len(history),
            "recent_domains": list(set([
                h.split()[0] for h in history[:5] if h.split()
            ])),
            "dominant_pattern": history[-1] if history else None,
        }

    def _build_user_profile(self, preferences: Dict[str, Any]) -> Dict[str, Any]:
        """Build user profile from preferences"""
        return {
            "language": preferences.get("language", "tr"),
            "research_frequency": preferences.get("research_frequency", "low"),
            "document_types": preferences.get("document_types", []),
            "preferred_tools": preferences.get("preferred_tools", []),
        }

    def _get_temporal_context(self) -> Dict[str, Any]:
        """Get temporal context"""
        now = datetime.now()
        return {
            "hour": now.hour,
            "day": now.strftime("%A"),
            "is_working_hours": 9 <= now.hour < 17,
            "is_weekend": now.weekday() >= 5,
        }

    def _extract_relationships(
        self,
        current_input: str,
        history: List[str]
    ) -> Dict[str, List[str]]:
        """Extract entity relationships"""
        # Simple relationship extraction
        relationships = {}

        # Files mentioned
        files = [w for w in current_input.split() if "." in w]
        if files:
            relationships["files"] = files

        # Apps mentioned
        apps = ["safari", "chrome", "finder", "terminal", "notes"]
        mentioned_apps = [app for app in apps if app in current_input.lower()]
        if mentioned_apps:
            relationships["apps"] = mentioned_apps

        return relationships


class VoiceInterface:
    """Voice command and text-to-speech interface"""

    def __init__(self, language: str = "tr"):
        self.language = language
        self.voice_enabled = self._check_voice_support()

    def _check_voice_support(self) -> bool:
        """Check if voice is supported on system"""
        try:
            import pyttsx3
            return True
        except ImportError:
            logger.warning("pyttsx3 not available - voice disabled")
            return False

    async def text_to_speech(self, text: str, voice_id: int = 0) -> bool:
        """Convert text to speech"""
        if not self.voice_enabled:
            return False

        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty('voice', engine.getProperty('voices')[voice_id].id)
            engine.say(text)
            engine.runAndWait()
            return True
        except Exception as e:
            logger.error(f"Text-to-speech error: {e}")
            return False

    async def speech_to_text(self, audio_file: Path) -> Optional[str]:
        """Convert speech to text"""
        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()

            with sr.AudioFile(str(audio_file)) as source:
                audio = recognizer.record(source)

            text = recognizer.recognize_google(audio, language=f"{self.language}-TR")
            return text

        except ImportError:
            logger.warning("speech_recognition not available")
            return None
        except Exception as e:
            logger.error(f"Speech-to-text error: {e}")
            return None


class AnomalyDetector:
    """Detects unusual user behavior patterns"""

    def __init__(self):
        self.baseline: Dict[str, Any] = {}
        self.anomalies: List[Dict[str, Any]] = []

    def update_baseline(
        self,
        commands: List[str],
        execution_times: List[float]
    ):
        """Update baseline from normal behavior"""
        import statistics

        self.baseline = {
            "avg_command_length": statistics.mean(len(c) for c in commands),
            "avg_execution_time": statistics.mean(execution_times),
            "command_variety": len(set(commands)),
            "commands_per_hour": len(commands) / max(1, len(execution_times) / 3600),
        }

    def detect_anomaly(
        self,
        command: str,
        execution_time: float
    ) -> bool:
        """Detect if command is anomalous"""
        if not self.baseline:
            return False

        # Check execution time anomaly
        avg_time = self.baseline.get("avg_execution_time", 0)
        if execution_time > avg_time * 3:  # 3x slower than average
            self.anomalies.append({
                "type": "slow_execution",
                "command": command,
                "time": execution_time,
                "normal_avg": avg_time,
                "timestamp": datetime.now(),
            })
            return True

        # Check command pattern anomaly
        if command.lower().count("delete") > 3:
            self.anomalies.append({
                "type": "bulk_deletion",
                "command": command,
                "timestamp": datetime.now(),
            })
            return True

        return False

    def get_anomalies(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent anomalies"""
        return self.anomalies[-limit:]


# Global instances
_streaming_processor: Optional[StreamingProcessor] = None
_parallel_executor: Optional[ParallelExecutor] = None
_suggestion_engine: Optional[ProactiveSuggestionEngine] = None
_context_enricher: Optional[ContextEnricher] = None
_voice_interface: Optional[VoiceInterface] = None
_anomaly_detector: Optional[AnomalyDetector] = None


def get_streaming_processor() -> StreamingProcessor:
    global _streaming_processor
    if _streaming_processor is None:
        _streaming_processor = StreamingProcessor()
    return _streaming_processor


def get_parallel_executor() -> ParallelExecutor:
    global _parallel_executor
    if _parallel_executor is None:
        _parallel_executor = ParallelExecutor()
    return _parallel_executor


def get_suggestion_engine() -> ProactiveSuggestionEngine:
    global _suggestion_engine
    if _suggestion_engine is None:
        _suggestion_engine = ProactiveSuggestionEngine()
    return _suggestion_engine


def get_context_enricher() -> ContextEnricher:
    global _context_enricher
    if _context_enricher is None:
        _context_enricher = ContextEnricher()
    return _context_enricher


def get_voice_interface() -> VoiceInterface:
    global _voice_interface
    if _voice_interface is None:
        _voice_interface = VoiceInterface()
    return _voice_interface


def get_anomaly_detector() -> AnomalyDetector:
    global _anomaly_detector
    if _anomaly_detector is None:
        _anomaly_detector = AnomalyDetector()
    return _anomaly_detector
