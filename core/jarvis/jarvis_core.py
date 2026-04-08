"""
core/jarvis/jarvis_core.py
───────────────────────────────────────────────────────────────────────────────
JarvisCore — The Brain

Central intelligence that understands intent, decomposes tasks, dispatches
to the right agent team, and synthesizes responses. Works identically
regardless of input channel (Telegram, WhatsApp, iMessage, Desktop, Voice).

Flow:
  ChannelMessage → IntentClassifier → TaskDecomposer → AgentDispatcher → ResponseSynthesizer

Design principles:
  - Stateless per request (session state lives in session_engine)
  - Uses existing Orchestrator + Pipeline — does NOT replace them
  - Adds intent understanding + task decomposition + response formatting
  - Graceful fallback: if classification fails → default to chat mode
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from utils.logger import get_logger

logger = get_logger("jarvis_core")

# ── Ollama helper ─────────────────────────────────────────────────────────────

_OLLAMA_URL = "http://localhost:11434/api/generate"
_OLLAMA_MODEL: str | None = None   # cached after first successful call

_SYSTEM_PROMPT = (
    "Sen Elyan'sın — kullanıcının kişisel asistanı. "
    "Türkçe ve İngilizce anlıyorsun, her zaman Türkçe yanıt veriyorsun. "
    "Kısa, net ve işe yarar yanıtlar ver. Gereksiz uzatma."
)


def _get_ollama_model() -> str:
    """Ollama'dan ilk mevcut modeli al, önbellekte tut."""
    global _OLLAMA_MODEL
    if _OLLAMA_MODEL is None:
        try:
            with urllib.request.urlopen(
                "http://localhost:11434/api/tags", timeout=2
            ) as r:
                tags = json.loads(r.read())
            models = [m["name"] for m in tags.get("models", [])]
            _OLLAMA_MODEL = models[0] if models else "llama3.2:3b"
        except Exception:
            _OLLAMA_MODEL = "llama3.2:3b"
    return _OLLAMA_MODEL


async def _ollama_chat(text: str, max_tokens: int = 400) -> str:
    """Ollama yerel LLM'e asenkron istek atar (stream=False). Başarısızlıkta '' döner."""
    import asyncio

    def _call() -> str:
        payload = json.dumps({
            "model": _get_ollama_model(),
            "prompt": f"{_SYSTEM_PROMPT}\n\nKullanıcı: {text}\n\nElyan:",
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.7},
        }).encode()
        req = urllib.request.Request(
            _OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
                return str(data.get("response", "")).strip()
        except Exception as exc:
            logger.debug(f"Ollama call failed: {exc}")
            return ""

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _call)


async def _ollama_stream(
    text: str,
    on_chunk,  # Callable[[str], Awaitable[None] | None]
    max_tokens: int = 600,
) -> str:
    """Ollama'dan stream=True ile cevap alır; her chunk'ı on_chunk callback'e iletir.

    Tam metni string olarak döner. on_chunk async veya sync olabilir.
    Başarısızlıkta '' döner ve on_chunk çağrılmaz.
    """
    import asyncio
    import socket

    def _stream_sync() -> list[str]:
        """Blocking stream reader — executor'da çalışır."""
        chunks: list[str] = []
        payload = json.dumps({
            "model": _get_ollama_model(),
            "prompt": f"{_SYSTEM_PROMPT}\n\nKullanıcı: {text}\n\nElyan:",
            "stream": True,
            "options": {"num_predict": max_tokens, "temperature": 0.7},
        }).encode()
        req = urllib.request.Request(
            _OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        chunk = obj.get("response", "")
                        if chunk:
                            chunks.append(chunk)
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:
            logger.debug(f"Ollama stream failed: {exc}")
        return chunks

    loop = asyncio.get_event_loop()
    chunks = await loop.run_in_executor(None, _stream_sync)

    full_text = ""
    for chunk in chunks:
        full_text += chunk
        try:
            result = on_chunk(chunk)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            pass

    return full_text


# ── Intent Taxonomy ─────────────────────────────────────────────────────────

class IntentCategory(str, Enum):
    SYSTEM_CONTROL = "system_control"     # ekran, uygulama, dosya, terminal
    INFORMATION = "information"           # araştır, bul, özetle, açıkla
    CREATION = "creation"                 # yaz, oluştur, kodla, tasarla
    COMMUNICATION = "communication"       # e-posta gönder, mesaj at, bildir
    MONITORING = "monitoring"             # izle, uyar, takip et, raporla
    AUTOMATION = "automation"             # her X'te Y yap, otomatikleştir
    CONVERSATION = "conversation"         # sohbet, soru, yardım


class Complexity(str, Enum):
    TRIVIAL = "trivial"     # selam, teşekkür → direkt yanıt
    SIMPLE = "simple"       # tek adım, net → 1 ajan
    MODERATE = "moderate"   # 2-3 adım → ajan zinciri
    COMPLEX = "complex"     # çoklu bağımlı → orchestrator
    EXPERT = "expert"       # araştırma + üretim + doğrulama → tam takım


@dataclass(slots=True)
class ClassifiedIntent:
    """Result of intent classification."""
    category: IntentCategory
    complexity: Complexity
    confidence: float  # [0.0, 1.0]
    sub_intent: str = ""  # e.g. "open_app", "search_web"
    entities: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""


@dataclass(slots=True)
class TaskPlan:
    """Decomposed task plan with steps."""
    intent: ClassifiedIntent
    steps: list[TaskStep] = field(default_factory=list)
    estimated_duration_s: float = 0.0
    requires_approval: bool = False


@dataclass(slots=True)
class TaskStep:
    """Single step in a task plan."""
    step_id: str
    action: str          # e.g. "research", "write_file", "send_telegram"
    owner: str           # specialist key: "researcher", "builder", "ops"
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


@dataclass(slots=True)
class JarvisResponse:
    """Final response to send back to the user."""
    text: str
    channel_format: str = "markdown"  # markdown, plain, html
    attachments: list[dict[str, Any]] = field(default_factory=list)
    buttons: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    duration_s: float = 0.0


# ── Intent Classifier ───────────────────────────────────────────────────────

# Tier 1: Rule-based keyword matching (<5ms)
_INTENT_RULES: list[tuple[list[str], IntentCategory, str]] = [
    # System Control — UZUN eşleşmeler önce (skor = keyword uzunluğu)
    (["ekran görüntüsü", "ekran görüntüsü al", "screenshot al"], IntentCategory.SYSTEM_CONTROL, "screen_capture"),
    (["yeniden başlat", "restart", "reboot"], IntentCategory.SYSTEM_CONTROL, "system_settings"),
    (["ekranı kilitle", "bilgisayarı kilitle", "kilitle", "lock screen"], IntentCategory.SYSTEM_CONTROL, "system_settings"),
    (["uyku modu", "sleep modu", "bekleme modu"], IntentCategory.SYSTEM_CONTROL, "system_settings"),
    (["dark mode", "karanlık mod", "karanlık tema", "parlaklık", "brightness"], IntentCategory.SYSTEM_CONTROL, "system_settings"),
    (["ses seviyesi", "sesi aç", "sesi kapat", "volume"], IntentCategory.SYSTEM_CONTROL, "system_settings"),
    (["ip adresi", "ip adresim", "ip address", "wifi durumu", "wifi bağlantı",
      "bluetooth cihaz", "ağ bağlantı"], IntentCategory.SYSTEM_CONTROL, "network"),
    (["dosya", "klasör", "file", "folder", "indirmeler", "downloads", "masaüstü"], IntentCategory.SYSTEM_CONTROL, "file_ops"),
    (["terminal", "komut çalıştır", "command", "çalıştır", "run"], IntentCategory.SYSTEM_CONTROL, "terminal"),
    (["ekran", "screenshot", "screen", "görüntü al"], IntentCategory.SYSTEM_CONTROL, "screen_capture"),
    (["wifi", "bluetooth", "ağ", "network", "ip"], IntentCategory.SYSTEM_CONTROL, "network"),
    # App control — genel ("aç"/"kapat") en sona, kısa keyword
    (["aç", "kapat", "başlat", "durdur", "open", "close", "launch", "quit"], IntentCategory.SYSTEM_CONTROL, "app_control"),

    # Information
    (["araştır", "bul", "ara", "search", "find", "google"], IntentCategory.INFORMATION, "search"),
    (["özetle", "summarize", "özet", "abstract"], IntentCategory.INFORMATION, "summarize"),
    (["açıkla", "explain", "nedir", "ne demek", "what is"], IntentCategory.INFORMATION, "explain"),
    (["hava", "weather", "sıcaklık"], IntentCategory.INFORMATION, "weather"),
    (["takvim etkinlik", "bugünkü etkinlik", "randevularım", "toplantılarım",
      "takvime ekle", "randevu ekle", "etkinlik oluştur"], IntentCategory.INFORMATION, "calendar"),
    (["takvim", "calendar", "randevu", "toplantı"], IntentCategory.INFORMATION, "calendar"),

    # Creation
    (["yaz", "oluştur", "write", "create", "generate", "üret"], IntentCategory.CREATION, "generate"),
    (["kodla", "code", "program", "script", "fonksiyon"], IntentCategory.CREATION, "code"),
    (["web sitesi", "website", "sayfa", "page", "landing"], IntentCategory.CREATION, "web"),
    (["rapor", "report", "belge", "document", "döküman"], IntentCategory.CREATION, "document"),

    # Communication
    (["telegram'a gönder", "telegram gönder", "telegram yaz", "tg gönder",
      "telegram mesaj", "telegram at"], IntentCategory.COMMUNICATION, "telegram"),
    (["e-posta", "email", "mail gönder", "send email"], IntentCategory.COMMUNICATION, "email"),
    (["mesaj gönder", "send message", "bildir", "notify"], IntentCategory.COMMUNICATION, "message"),

    # Monitoring — UZUN keyword'ler önce gelsin (kazanç skoru: uzunluk)
    (["sistem durumu", "system status", "sistem sağlık"], IntentCategory.MONITORING, "system_health"),
    (["batarya", "battery", "şarj durumu", "pil durumu"], IntentCategory.MONITORING, "system_health"),
    (["cpu kullanımı", "cpu yükü", "işlemci kullanımı"], IntentCategory.MONITORING, "system_health"),
    (["disk alanı", "disk kullanımı", "depolama alanı"], IntentCategory.MONITORING, "system_health"),
    (["ram kullanımı", "bellek kullanımı", "memory usage"], IntentCategory.MONITORING, "system_health"),
    (["izle", "watch", "monitor", "takip", "track"], IntentCategory.MONITORING, "watch"),
    (["uyar", "alert", "bildirim", "notification"], IntentCategory.MONITORING, "alert"),
    (["cpu", "ram", "disk", "battery", "pil", "bellek", "batarya", "şarj"], IntentCategory.MONITORING, "system_health"),

    # Automation
    (["her", "every", "otomatik", "automatic", "zamanla", "schedule", "cron"], IntentCategory.AUTOMATION, "schedule"),
    (["tekrarla", "repeat", "döngü", "loop"], IntentCategory.AUTOMATION, "repeat"),
]

# Complexity estimation keywords
_COMPLEXITY_SIGNALS: dict[Complexity, list[str]] = {
    Complexity.TRIVIAL: ["selam", "merhaba", "hello", "hi", "teşekkür", "thanks", "ok", "tamam"],
    Complexity.SIMPLE: ["aç", "kapat", "göster", "listele", "ne", "kim", "nerede"],
    Complexity.COMPLEX: ["araştır ve yaz", "karşılaştır", "analiz et", "planla"],
    Complexity.EXPERT: ["kapsamlı", "comprehensive", "proje", "project", "sıfırdan", "from scratch"],
}


class IntentClassifier:
    """3-tier intent classification: rules → embedding → LLM."""

    def classify(self, text: str) -> ClassifiedIntent:
        """Classify user intent. Tier 1 (rules) only for now."""
        lower = text.lower().strip()

        # Tier 1: Rule matching
        best_match: tuple[IntentCategory, str, int] | None = None
        for keywords, category, sub_intent in _INTENT_RULES:
            for kw in keywords:
                if kw in lower:
                    match_score = len(kw)
                    if best_match is None or match_score > best_match[2]:
                        best_match = (category, sub_intent, match_score)

        if best_match:
            category, sub_intent, match_len = best_match
            complexity = self._estimate_complexity(lower)
            # Confidence: short keywords (len<4) are ambiguous → lower confidence
            # Long specific keywords (len≥10) are very reliable → high confidence
            confidence = min(0.98, 0.55 + (match_len / 20.0))
            return ClassifiedIntent(
                category=category,
                complexity=complexity,
                confidence=round(confidence, 2),
                sub_intent=sub_intent,
                raw_text=text,
            )

        # Fallback: conversation
        complexity = self._estimate_complexity(lower)
        return ClassifiedIntent(
            category=IntentCategory.CONVERSATION,
            complexity=complexity,
            confidence=0.40,
            sub_intent="chat",
            raw_text=text,
        )

    def _estimate_complexity(self, text: str) -> Complexity:
        """Estimate task complexity from text signals."""
        word_count = len(text.split())

        # Check explicit signals
        for level in [Complexity.EXPERT, Complexity.COMPLEX, Complexity.TRIVIAL, Complexity.SIMPLE]:
            for signal in _COMPLEXITY_SIGNALS.get(level, []):
                if signal in text:
                    return level

        # Heuristic: longer requests tend to be more complex
        if word_count <= 3:
            return Complexity.TRIVIAL
        if word_count <= 10:
            return Complexity.SIMPLE
        if word_count <= 30:
            return Complexity.MODERATE
        return Complexity.COMPLEX


# ── Task Decomposer ─────────────────────────────────────────────────────────

class TaskDecomposer:
    """Decomposes classified intent into executable task steps."""

    def decompose(self, intent: ClassifiedIntent) -> TaskPlan:
        """Create a task plan from the classified intent."""
        if intent.complexity == Complexity.TRIVIAL:
            return TaskPlan(
                intent=intent,
                steps=[TaskStep(step_id="s1", action="chat_response", owner="lead")],
            )

        if intent.category == IntentCategory.SYSTEM_CONTROL:
            return self._plan_system_control(intent)
        if intent.category == IntentCategory.INFORMATION:
            return self._plan_information(intent)
        if intent.category == IntentCategory.CREATION:
            return self._plan_creation(intent)
        if intent.category == IntentCategory.COMMUNICATION:
            return self._plan_communication(intent)
        if intent.category == IntentCategory.MONITORING:
            return self._plan_monitoring(intent)
        if intent.category == IntentCategory.AUTOMATION:
            return self._plan_automation(intent)

        # Default: single chat step
        return TaskPlan(
            intent=intent,
            steps=[TaskStep(step_id="s1", action="chat_response", owner="lead")],
        )

    def _plan_system_control(self, intent: ClassifiedIntent) -> TaskPlan:
        steps = [
            TaskStep(step_id="s1", action=intent.sub_intent, owner="ops",
                     params={"raw_text": intent.raw_text}),
        ]
        if intent.sub_intent in ("terminal", "file_ops"):
            steps.append(TaskStep(
                step_id="s2", action="verify_result", owner="qa",
                depends_on=["s1"],
            ))
        return TaskPlan(intent=intent, steps=steps, requires_approval=intent.sub_intent == "terminal")

    def _plan_information(self, intent: ClassifiedIntent) -> TaskPlan:
        steps = [
            TaskStep(step_id="s1", action="research", owner="researcher",
                     params={"query": intent.raw_text}),
            TaskStep(step_id="s2", action="synthesize", owner="lead",
                     depends_on=["s1"]),
        ]
        return TaskPlan(intent=intent, steps=steps)

    def _plan_creation(self, intent: ClassifiedIntent) -> TaskPlan:
        steps = [
            TaskStep(step_id="s1", action="plan", owner="lead",
                     params={"goal": intent.raw_text}),
            TaskStep(step_id="s2", action="build", owner="builder",
                     depends_on=["s1"]),
            TaskStep(step_id="s3", action="verify", owner="qa",
                     depends_on=["s2"]),
        ]
        return TaskPlan(intent=intent, steps=steps)

    def _plan_communication(self, intent: ClassifiedIntent) -> TaskPlan:
        steps = [
            TaskStep(step_id="s1", action="compose", owner="lead",
                     params={"raw_text": intent.raw_text}),
            TaskStep(step_id="s2", action="send", owner="ops",
                     depends_on=["s1"]),
        ]
        return TaskPlan(intent=intent, steps=steps, requires_approval=True)

    def _plan_monitoring(self, intent: ClassifiedIntent) -> TaskPlan:
        steps = [
            TaskStep(step_id="s1", action="setup_monitor", owner="ops",
                     params={"raw_text": intent.raw_text}),
        ]
        return TaskPlan(intent=intent, steps=steps)

    def _plan_automation(self, intent: ClassifiedIntent) -> TaskPlan:
        steps = [
            TaskStep(step_id="s1", action="parse_schedule", owner="lead",
                     params={"raw_text": intent.raw_text}),
            TaskStep(step_id="s2", action="create_schedule", owner="ops",
                     depends_on=["s1"]),
        ]
        return TaskPlan(intent=intent, steps=steps, requires_approval=True)


# ── Response Synthesizer ────────────────────────────────────────────────────

class ResponseSynthesizer:
    """Converts task results into channel-appropriate responses."""

    def synthesize(
        self,
        results: list[dict[str, Any]],
        intent: ClassifiedIntent,
        channel_type: str = "telegram",
    ) -> JarvisResponse:
        """Merge multiple step results into a single user response."""
        texts: list[str] = []
        attachments: list[dict] = []

        for r in results:
            if isinstance(r, dict):
                if r.get("text"):
                    texts.append(str(r["text"]))
                if r.get("attachments"):
                    attachments.extend(r["attachments"])
            elif isinstance(r, str):
                texts.append(r)

        combined = "\n\n".join(texts) if texts else "Görev tamamlandı."

        # Channel-specific formatting
        fmt = "markdown"
        if channel_type == "imessage":
            fmt = "plain"
            combined = self._strip_markdown(combined)

        # Truncate for channel limits
        max_len = self._channel_max_length(channel_type)
        if len(combined) > max_len:
            combined = combined[:max_len - 20] + "\n\n... (devamı var)"

        return JarvisResponse(
            text=combined,
            channel_format=fmt,
            attachments=attachments,
        )

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Simple markdown stripping for plain-text channels."""
        import re
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
        text = re.sub(r'\*(.*?)\*', r'\1', text)
        text = re.sub(r'`(.*?)`', r'\1', text)
        return text

    @staticmethod
    def _channel_max_length(channel_type: str) -> int:
        limits = {
            "telegram": 4096,
            "whatsapp": 65536,
            "imessage": 20000,
            "discord": 2000,
            "webchat": 100000,
        }
        return limits.get(channel_type, 4096)


# ── JarvisCore ──────────────────────────────────────────────────────────────

class JarvisCore:
    """The Jarvis brain — classifies, decomposes, dispatches, synthesizes."""

    # ── Destructive action guard ─────────────────────────────────────────────
    # Commands that require explicit "evet" confirmation before execution.
    _DESTRUCTIVE_KEYWORDS = frozenset({
        "yeniden başlat", "restart", "reboot",
        "kapat mac", "shutdown", "power off", "kapat bilgisayarı",
    })
    # Per-user pending approval buffer: user_id → (intent, expire_time)
    _pending_approvals: dict[str, tuple["ClassifiedIntent", float]] = {}
    _APPROVAL_TTL = 60.0  # seconds
    _CONFIRM_WORDS = frozenset({"evet", "yes", "onayla", "confirm", "ok", "tamam"})
    _CANCEL_WORDS  = frozenset({"hayır", "no", "iptal", "cancel", "vazgeç"})

    def __init__(self) -> None:
        self.classifier = IntentClassifier()
        self.decomposer = TaskDecomposer()
        self.synthesizer = ResponseSynthesizer()

    def classify_intent(self, text: str) -> ClassifiedIntent:
        """Classify the user's intent."""
        return self.classifier.classify(text)

    def create_plan(self, intent: ClassifiedIntent) -> TaskPlan:
        """Decompose intent into a task plan."""
        return self.decomposer.decompose(intent)

    def format_response(
        self,
        results: list[dict[str, Any]],
        intent: ClassifiedIntent,
        channel_type: str = "telegram",
    ) -> JarvisResponse:
        """Format results for the target channel."""
        return self.synthesizer.synthesize(results, intent, channel_type)

    # ── Sequential command splitter ──────────────────────────────────────────

    _CHAIN_SPLITTERS = re.compile(
        r"\s+(?:ve\s+sonra|ve\s+ardından|sonra|ardından|daha\s+sonra|then|and\s+then)\s+",
        re.IGNORECASE,
    )
    # Simple "ve" only when it connects two verb phrases (heuristic: split on " ve " if both sides >3 words)
    _AND_SPLIT = re.compile(r"\s+ve\s+", re.IGNORECASE)

    def _split_chained_commands(self, text: str) -> list[str]:
        """'X yap ve Y yap' veya 'X yap, sonra Y yap' → ['X yap', 'Y yap']."""
        # Phase 1: strong splitters (sonra/ardından/then)
        parts = self._CHAIN_SPLITTERS.split(text.strip())
        if len(parts) > 1:
            return [p.strip() for p in parts if p.strip()]

        # Phase 2: weak "ve" split — only if each side has 2+ words
        parts = self._AND_SPLIT.split(text.strip())
        if len(parts) == 2:
            left, right = parts
            if len(left.split()) >= 2 and len(right.split()) >= 2:
                return [left.strip(), right.strip()]

        return [text.strip()]

    async def handle(
        self,
        text: str,
        channel_type: str = "desktop",
        user_id: str = "",
    ) -> JarvisResponse:
        """Full Jarvis pipeline: classify → plan → dispatch → synthesize.

        Supports chained commands: 'X yap ve Y yap' → executes both in sequence.
        Wires into the existing AgentOrchestrator for actual task execution.
        Personality + episodic memory inject context into every request.
        """
        t0 = time.time()
        uid = user_id or "default"
        lower = text.strip().lower()

        # ── Pending approval resolution ───────────────────────────────────────
        if uid in self._pending_approvals:
            pending_intent, expire_at = self._pending_approvals[uid]
            if time.time() < expire_at:
                if lower in self._CONFIRM_WORDS:
                    del self._pending_approvals[uid]
                    result = await self._dispatch(pending_intent.raw_text, pending_intent, channel_type, uid)
                    resp = self.synthesizer.synthesize([{"text": result}], pending_intent, channel_type)
                    self._record(uid, channel_type, text, resp.text, "approved", t0)
                    resp.duration_s = round(time.time() - t0, 3)
                    return resp
                if lower in self._CANCEL_WORDS:
                    del self._pending_approvals[uid]
                    resp = JarvisResponse(text="❌ İşlem iptal edildi.", duration_s=round(time.time()-t0,3))
                    return resp
            else:
                del self._pending_approvals[uid]

        # ── Sequential chain detection ────────────────────────────────────────
        segments = self._split_chained_commands(text)
        if len(segments) > 1:
            return await self._handle_chain(segments, channel_type, uid, t0)

        intent = self.classify_intent(text)

        logger.info(
            f"Jarvis intent: {intent.category.value}/{intent.sub_intent} "
            f"complexity={intent.complexity.value} conf={intent.confidence:.2f}"
        )

        # ── Faz 7: personality & memory context ─────────────────────────────
        style_hint = ""
        memory_hint = ""
        try:
            from core.memory.personality_adapter import get_personality_adapter
            profile = get_personality_adapter().get_profile(user_id or "default")
            style_hint = profile.response_style_hint()
            get_personality_adapter().observe_channel(user_id or "default", channel_type)
            get_personality_adapter().observe_message_time(user_id or "default")
        except Exception:
            pass

        try:
            from core.memory.jarvis_memory import get_jarvis_memory
            memory_hint = get_jarvis_memory().build_context_hint(user_id or "default", text)
        except Exception:
            pass

        plan = self.create_plan(intent)

        if plan.requires_approval:
            resp = JarvisResponse(
                text=f"Bu işlem onay gerektiriyor:\n\n"
                     f"**Görev:** {intent.raw_text}\n"
                     f"**Adımlar:** {len(plan.steps)}\n\n"
                     f"Onaylıyor musun? (evet/hayır)",
                metadata={"requires_approval": True, "plan_steps": len(plan.steps)},
                duration_s=round(time.time() - t0, 3),
            )
            self._record(user_id, channel_type, text, resp.text, "pending", t0)
            return resp

        # ── Dispatch to existing orchestrator ────────────────────────────────
        enriched_text = text
        if memory_hint:
            enriched_text = f"[Hafıza bağlamı: {memory_hint}]\n\n{text}"
        if style_hint:
            enriched_text = f"{enriched_text}\n\n[Yanıt stili: {style_hint}]"

        agent_result = await self._dispatch(enriched_text, intent, channel_type, user_id)
        resp = self.synthesizer.synthesize(
            [{"text": agent_result}], intent, channel_type
        )

        # Faz 7: record to memory + observe response length
        self._record(user_id, channel_type, text, resp.text, "ok", t0)
        try:
            from core.memory.personality_adapter import get_personality_adapter
            get_personality_adapter().observe_response_length(
                user_id or "default", len(resp.text)
            )
        except Exception:
            pass

        resp.duration_s = round(time.time() - t0, 3)
        return resp

    async def _dispatch(
        self,
        text: str,
        intent: ClassifiedIntent,
        channel_type: str,
        user_id: str,
    ) -> str:
        """Route to the appropriate handler based on intent + complexity.

        Priority:
          1. IntentExecutor — system_control / monitoring / information / communication
             (fast, direct macOS API calls, no LLM needed)
          2. Quick LLM response — trivial conversation
          3. Full orchestrator — complex multi-step tasks
        """
        # ── 0. Destructive action guard ───────────────────────────────────────
        if intent.sub_intent == "system_settings":
            raw_lower = intent.raw_text.lower()
            if any(kw in raw_lower for kw in self._DESTRUCTIVE_KEYWORDS):
                uid = user_id or "default"
                self._pending_approvals[uid] = (intent, time.time() + self._APPROVAL_TTL)
                return (
                    f"⚠️ **Onay Gerekiyor**\n\n"
                    f"Şu işlemi gerçekleştirmek üzereyim:\n"
                    f"→ `{intent.raw_text}`\n\n"
                    f"Bu işlem **geri alınamaz**. Onaylıyor musun?\n"
                    f"Devam etmek için **'evet'**, iptal için **'hayır'** yaz.\n"
                    f"_(60 saniye içinde yanıt vermezsen iptal edilir)_"
                )

        # ── 1. Direct execution for actionable intents ────────────────────────
        EXECUTABLE = {
            "system_control", "monitoring", "information", "communication"
        }
        if intent.category.value in EXECUTABLE:
            try:
                from core.jarvis.intent_executor import get_intent_executor
                result = await get_intent_executor().execute(intent)
                if result:  # non-empty → executor handled it
                    return result
            except Exception as exc:
                logger.warning(f"IntentExecutor failed, falling through: {exc}")

        # ── 2. Trivial/Simple conversation → quick LLM ────────────────────────
        if intent.complexity in (Complexity.TRIVIAL, Complexity.SIMPLE):
            return await self._quick_response(text, intent)

        # ── 3. Moderate+ → full orchestrator pipeline ─────────────────────────
        try:
            from core.multi_agent.router import agent_router
            agent = await agent_router.route_message(channel_type, user_id)
            if callable(getattr(agent, "process_envelope", None)):
                result = await agent.process_envelope(text)
            elif callable(getattr(agent, "handle_message", None)):
                result = await agent.handle_message(text)
            else:
                result = await self._quick_response(text, intent)
            return str(result or "")
        except Exception as exc:
            logger.warning(f"Orchestrator dispatch failed: {exc}")
            return await self._quick_response(text, intent)

    async def _quick_response(
        self,
        text: str,
        intent: ClassifiedIntent,
        stream_broadcast=None,  # Optional[Callable[[str], None]] — WebSocket push
    ) -> str:
        """LLM call — tries Ollama streaming first, then cloud providers.

        stream_broadcast: if provided, each token chunk is pushed via this callback.
        """
        # Try Ollama — streaming if broadcast available, non-streaming fallback
        if stream_broadcast is not None:
            result = await _ollama_stream(text, on_chunk=stream_broadcast)
        else:
            result = await _ollama_chat(text)
        if result:
            return result

        # Try cloud providers via existing LLM router
        try:
            from core.llm.model_selection_policy import get_model_selection_policy, SelectionContext, TaskType
            policy = get_model_selection_policy()
            ctx = SelectionContext(
                task_type=TaskType.CHAT,
                required_quality=0.4,
                budget_remaining=0.5,
                latency_target_ms=3000,
            )
            decision = policy.select(ctx)
            logger.debug(f"Cloud LLM: {decision.provider}/{decision.model}")
            # Use existing agent pipeline for cloud routing
            from core.multi_agent.router import agent_router
            agent = await agent_router.route_message("desktop", "jarvis_internal")
            if callable(getattr(agent, "process_envelope", None)):
                resp = await agent.process_envelope(text)
                out = str(getattr(resp, "text", resp) or "").strip()
                if out:
                    return out
        except Exception as exc:
            logger.debug(f"Cloud LLM failed: {exc}")

        # No LLM available — honest fallback
        return ("Şu an dil modelim çevrimdışı. Komut tabanlı işlemler (uygulama aç/kapat, "
                "sistem durumu, dosya işlemleri) için hazırım.")

    async def _handle_chain(
        self,
        segments: list[str],
        channel_type: str,
        user_id: str,
        t0: float,
    ) -> JarvisResponse:
        """Execute a list of command segments sequentially and combine results."""
        results: list[str] = []
        for i, seg in enumerate(segments):
            intent = self.classify_intent(seg)
            logger.info(f"Chain step {i+1}/{len(segments)}: '{seg[:60]}' → {intent.category.value}/{intent.sub_intent}")
            try:
                result = await self._dispatch(seg, intent, channel_type, user_id)
                results.append(result)
            except Exception as exc:
                logger.warning(f"Chain step {i+1} failed: {exc}")
                results.append(f"❌ Adım {i+1} başarısız: {exc}")

        combined = "\n\n".join(
            f"**{i+1}. {seg[:40]}{'…' if len(seg)>40 else ''}**\n{r}"
            for i, (seg, r) in enumerate(zip(segments, results))
        )
        resp = self.synthesizer.synthesize([{"text": combined}], self.classify_intent(segments[0]), channel_type)
        self._record(user_id, channel_type, " → ".join(segments), combined, "ok", t0)
        resp.duration_s = round(time.time() - t0, 3)
        return resp

    def _record(
        self, user_id: str, channel: str, inp: str, out: str, outcome: str, t0: float
    ) -> None:
        """Async-safe fire-and-forget memory write."""
        try:
            import asyncio
            from core.memory.jarvis_memory import Interaction, get_jarvis_memory
            ix = Interaction(
                user_id=user_id or "default",
                channel=channel,
                input_text=inp,
                output_text=out,
                outcome=outcome,
                latency_ms=(time.time() - t0) * 1000,
            )
            # Run in thread to avoid blocking event loop
            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, get_jarvis_memory().record, ix)
        except Exception:
            pass


# ── Singleton ───────────────────────────────────────────────────────────────

_instance: JarvisCore | None = None


def get_jarvis_core() -> JarvisCore:
    global _instance
    if _instance is None:
        _instance = JarvisCore()
    return _instance


__all__ = [
    "ClassifiedIntent", "Complexity", "IntentCategory",
    "JarvisCore", "JarvisResponse", "TaskDecomposer",
    "TaskPlan", "TaskStep", "get_jarvis_core",
]
