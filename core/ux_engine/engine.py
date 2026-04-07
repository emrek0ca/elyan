"""
Conversation Experience Core.
Shared message-native UX orchestration for desktop and channel surfaces.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

from config.settings_manager import SettingsPanel
from core.accuracy_speed_runtime import get_accuracy_speed_runtime
from core.user_profile import get_user_profile_store

from .context_continuity import ContextContinuityTracker
from .conversation_flow import ConversationFlowManager
from .streaming_handler import StreamingHandler
from .suggestion_engine import SuggestionEngine


@dataclass
class ConversationProfile:
    tone: str = "natural_concise"
    response_length: str = "short"
    privacy_mode: str = "balanced"
    followup_preference: str = "balanced"
    decision_style: str = "direct"
    preferred_name: str = ""
    prefers_brief_answers: bool = True
    channel_tone_overrides: Dict[str, str] = field(default_factory=dict)

    def tone_for_channel(self, channel_type: str) -> str:
        key = str(channel_type or "").strip().lower()
        return str(self.channel_tone_overrides.get(key) or self.tone or "natural_concise")


@dataclass
class DeliveryPlan:
    reply_style: str
    delivery_mode: str
    channel_behavior: str
    user_intent_confidence: float
    followup_suggestion: str = ""
    typing_profile_ms: int = 220
    should_respond: bool = True
    ack_text: str = ""
    suggested_replies: List[str] = field(default_factory=list)
    operator_mode: str = "standard"
    should_offer_method: bool = False
    presence_note: str = ""


@dataclass
class UXResult:
    success: bool
    text: str
    response: str = ""
    suggestions: List[str] = field(default_factory=list)
    streaming_enabled: bool = False
    context_used: Dict[str, Any] = field(default_factory=dict)
    multimodal_inputs: List[str] = field(default_factory=list)
    timestamp: float = 0.0
    elapsed: float = 0.0
    reply_style: str = "normal"
    delivery_mode: str = "immediate"
    channel_behavior: str = "dm"
    user_intent_confidence: float = 0.0
    followup_suggestion: str = ""
    typing_profile_ms: int = 220
    should_respond: bool = True
    suggested_replies: List[str] = field(default_factory=list)
    trust_summary: str = ""
    operator_mode: str = "standard"

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = datetime.now().timestamp()
        if not self.response:
            self.response = self.text

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class UXEngine:
    """Conversation core for message-native and desktop experiences."""

    _DECORATIVE_LINE_RE = re.compile(r"^[=\-]{3,}$")
    _EMOJI_PREFIX_RE = re.compile(r"^[\W_]*[^\w\s]{1,3}\s*")
    _BOILERPLATE_LINES = {
        "premium ux response",
        "öneriler:",
        "intent:",
        "attachments:",
        "context",
    }

    def __init__(self):
        self.flow_manager = ConversationFlowManager()
        self.suggestion_engine = SuggestionEngine()
        self.context_tracker = ContextContinuityTracker()
        self.streaming_handler = StreamingHandler()
        self._session_cache: Dict[str, Dict[str, Any]] = {}
        self._settings = SettingsPanel()
        self._profiles = get_user_profile_store()
        self._speed_runtime = get_accuracy_speed_runtime()

    async def process_message(
        self,
        user_message: str,
        session_id: str = "default",
        multimodal_inputs: Optional[List[str]] = None,
        enable_streaming: bool = False,
        context_data: Optional[Dict[str, Any]] = None,
    ) -> UXResult | AsyncIterator[str]:
        start_time = time.time()
        context_data = dict(context_data or {})
        user_id = str(context_data.get("user_id") or "local")
        channel_type = str(context_data.get("channel_type") or "desktop")
        metadata = dict(context_data.get("metadata") or {})
        attachments = list(multimodal_inputs or context_data.get("attachments") or [])
        multimodal_context = self._process_multimodal(attachments)
        context_data["multimodal_inputs"] = multimodal_context
        result = await self.postprocess_response(
            raw_response=user_message,
            user_message=user_message,
            session_id=session_id,
            user_id=user_id,
            channel_type=channel_type,
            metadata=metadata,
            attachments=attachments,
            elapsed=time.time() - start_time,
        )
        result.context_used["multimodal_inputs"] = multimodal_context
        result.multimodal_inputs = attachments
        if enable_streaming:
            return self.streaming_handler.stream_response(result.response)
        return result

    async def postprocess_response(
        self,
        *,
        raw_response: str,
        user_message: str,
        session_id: str,
        user_id: str = "local",
        channel_type: str = "desktop",
        metadata: Optional[Dict[str, Any]] = None,
        attachments: Optional[List[Any]] = None,
        elapsed: float = 0.0,
    ) -> UXResult:
        started_at = time.time()
        metadata = dict(metadata or {})
        attachments = list(attachments or [])
        session = self._get_or_create_session(session_id)
        profile = self._load_profile(user_id=user_id, channel_type=channel_type)
        context_data = dict(metadata)
        if self.context_tracker.is_repeat_question(user_message, session_id):
            context_data["repeat_question"] = True

        flow_analysis = self.flow_manager.analyze(user_message, session)
        delivery = self._build_delivery_plan(
            user_message=user_message,
            channel_type=channel_type,
            metadata=metadata,
            flow_analysis=flow_analysis,
            profile=profile,
            attachments=attachments,
        )
        suggestions = await self.suggestion_engine.generate_suggestions(
            user_message=user_message,
            session_data=session,
            flow_analysis=flow_analysis,
            context_data=context_data,
        )
        if delivery.suggested_replies:
            merged_suggestions = list(suggestions or [])
            for item in delivery.suggested_replies:
                if item not in merged_suggestions:
                    merged_suggestions.append(item)
            suggestions = merged_suggestions
        response_text = self._naturalize_response(
            raw_response=raw_response,
            user_message=user_message,
            flow_analysis=flow_analysis,
            profile=profile,
            delivery=delivery,
            channel_type=channel_type,
            metadata=metadata,
            attachments=attachments,
        )
        speed = self._speed_runtime.plan_for_text(
            text=user_message,
            request_kind="document" if attachments else "chat",
            channel_type=channel_type,
            privacy_mode=profile.privacy_mode,
            has_attachments=bool(attachments),
            force_verified=bool(metadata.get("verified_mode") or metadata.get("requires_verification")),
        )
        trust_summary = self._trust_summary(profile.privacy_mode, metadata)
        session["messages"].append(
            {
                "timestamp": datetime.now().isoformat(),
                "user": user_message,
                "assistant": response_text,
                "channel_behavior": delivery.channel_behavior,
            }
        )
        session["last_behavior"] = delivery.channel_behavior
        session["last_intent"] = flow_analysis.intent
        session["last_followup"] = delivery.followup_suggestion
        session["open_thread_hint"] = user_message[:120]
        self.context_tracker.record_question(user_message, session_id)
        self._learn_from_turn(
            user_id=user_id,
            channel_type=channel_type,
            metadata=metadata,
            profile=profile,
            user_message=user_message,
            delivery=delivery,
        )
        total_elapsed = elapsed or (time.time() - started_at)
        return UXResult(
            success=True,
            text=response_text,
            response=response_text,
            suggestions=suggestions,
            streaming_enabled=delivery.delivery_mode == "streamed",
            context_used={
                "privacy_mode": profile.privacy_mode,
                "channel_type": channel_type,
                "channel_behavior": delivery.channel_behavior,
                "provider_lane": speed.provider_lane,
            },
            multimodal_inputs=[str(item) for item in attachments if isinstance(item, str)],
            elapsed=total_elapsed,
            reply_style=delivery.reply_style,
            delivery_mode=delivery.delivery_mode,
            channel_behavior=self._channel_behavior_label(delivery.channel_behavior),
            user_intent_confidence=delivery.user_intent_confidence,
            followup_suggestion=delivery.followup_suggestion,
            typing_profile_ms=delivery.typing_profile_ms,
            should_respond=delivery.should_respond,
            suggested_replies=delivery.suggested_replies,
            trust_summary=trust_summary,
            operator_mode=delivery.operator_mode,
        )

    def should_respond(
        self,
        *,
        user_message: str,
        session_id: str,
        channel_type: str,
        metadata: Optional[Dict[str, Any]] = None,
        attachments: Optional[List[Any]] = None,
        user_id: str = "local",
    ) -> DeliveryPlan:
        session = self._get_or_create_session(session_id)
        flow_analysis = self.flow_manager.analyze(user_message, session)
        profile = self._load_profile(user_id=user_id, channel_type=channel_type)
        return self._build_delivery_plan(
            user_message=user_message,
            channel_type=channel_type,
            metadata=dict(metadata or {}),
            flow_analysis=flow_analysis,
            profile=profile,
            attachments=list(attachments or []),
        )

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._session_cache.get(session_id)

    def list_sessions(self) -> List[str]:
        return list(self._session_cache.keys())

    def clear_session(self, session_id: str) -> None:
        self._session_cache.pop(session_id, None)
        self.context_tracker.clear_session(session_id)

    def _get_or_create_session(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self._session_cache:
            self._session_cache[session_id] = {
                "created_at": datetime.now().isoformat(),
                "messages": [],
                "last_behavior": "direct_message",
                "last_intent": "",
                "last_followup": "",
                "open_thread_hint": "",
            }
        return self._session_cache[session_id]

    def _load_profile(self, *, user_id: str, channel_type: str) -> ConversationProfile:
        settings = self._settings
        try:
            settings._load()
        except Exception:
            pass
        stored = self._profiles.get_conversation_profile(user_id)
        safe_memory = self._profiles.get(user_id).get("safe_relational_memory", {})
        return ConversationProfile(
            tone=str(stored.get("tone", "natural_concise") or "natural_concise"),
            response_length=str(stored.get("response_length", settings.get("response_length", "short")) or "short"),
            privacy_mode=str(settings.get("conversation_privacy_mode", "balanced") or "balanced").lower(),
            followup_preference=str(stored.get("followup_preference", "balanced") or "balanced"),
            decision_style=str(stored.get("decision_style", "direct") or "direct"),
            preferred_name=str((safe_memory or {}).get("preferred_name", "") or ""),
            prefers_brief_answers=bool(stored.get("prefers_brief_answers", True)),
            channel_tone_overrides=dict(stored.get("channel_tone_overrides", {}) or {}),
        )

    def _build_delivery_plan(
        self,
        *,
        user_message: str,
        channel_type: str,
        metadata: Dict[str, Any],
        flow_analysis: Any,
        profile: ConversationProfile,
        attachments: List[Any],
    ) -> DeliveryPlan:
        state = self._classify_state(user_message, channel_type, metadata, attachments)
        should_respond = state != "group_idle"
        request_kind = "computer_use" if any(token in str(user_message or "").lower() for token in ("tıkla", "tikla", "click", "ekran", "browser", "ui")) else ("document" if attachments else "chat")
        speed = self._speed_runtime.plan_for_text(
            text=user_message,
            request_kind=request_kind,
            channel_type=channel_type,
            privacy_mode=profile.privacy_mode,
            has_attachments=bool(attachments),
            force_verified=bool(metadata.get("verified_mode") or metadata.get("requires_verification")),
        )
        channel_behavior = {
            "direct_message": "dm",
            "group_mentioned": "group_mention",
            "inline_reply_context": "inline_reply",
            "voice_turn": "voice",
        }.get(state, "dm")
        reply_style = self._reply_style_for(profile, flow_analysis, state)
        response_length = profile.response_length if profile.response_length in {"short", "medium", "detailed"} else "short"
        streamed = speed.response_mode == "staged" or (channel_type in {"desktop", "web", "webchat"} and response_length != "short")
        typing_profile_ms = int(speed.typing_profile_ms or (180 if response_length == "short" else 320 if response_length == "medium" else 420))
        followup = self._followup_suggestion(flow_analysis.intent, profile.followup_preference)
        operator_mode = self._operator_mode_for(user_message, flow_analysis)
        suggestions = self._suggested_replies(flow_analysis.intent, state, operator_mode)
        if speed.provider_lane in {"verified_cloud", "local_verified"} and "Kaynakla doğrula" not in suggestions:
            suggestions = list(suggestions) + ["Kaynakla doğrula"]
        ack_text = str(speed.immediate_ack or self._ack_text(state, flow_analysis.intent, operator_mode))
        return DeliveryPlan(
            reply_style=reply_style,
            delivery_mode="streamed" if streamed else "immediate",
            channel_behavior=channel_behavior,
            user_intent_confidence=float(getattr(flow_analysis, "confidence", 0.7) or 0.7),
            followup_suggestion=followup,
            typing_profile_ms=typing_profile_ms,
            should_respond=should_respond,
            ack_text=ack_text,
            suggested_replies=suggestions,
            operator_mode=operator_mode,
            should_offer_method=operator_mode in {"solver", "blocked_recovery", "planner"},
            presence_note=self._presence_note_for(state, operator_mode),
        )

    def _classify_state(
        self,
        user_message: str,
        channel_type: str,
        metadata: Dict[str, Any],
        attachments: List[Any],
    ) -> str:
        text = str(user_message or "").strip()
        is_group = bool(metadata.get("is_group"))
        if metadata.get("awaiting_confirmation"):
            return "awaiting_confirmation"
        if metadata.get("background_task_followup"):
            return "background_task_followup"
        if metadata.get("is_voice") or str(metadata.get("source") or "").lower().startswith("voice"):
            return "voice_turn"
        if metadata.get("is_inline_reply") or metadata.get("reply_to_message_id"):
            return "inline_reply_context"
        if is_group:
            mentioned = bool(metadata.get("mentioned"))
            explicit_trigger = self._has_explicit_trigger(text, metadata)
            has_media_only = bool(attachments) and not text
            if not mentioned and not explicit_trigger:
                return "group_idle" if has_media_only or text else "group_idle"
            return "group_mentioned"
        return "direct_message"

    @staticmethod
    def _has_explicit_trigger(text: str, metadata: Dict[str, Any]) -> bool:
        lowered = str(text or "").strip().lower()
        if not lowered:
            return False
        bot_name = str(metadata.get("bot_username") or metadata.get("assistant_name") or "elyan").strip().lower()
        return lowered.startswith("/") or (bot_name and f"@{bot_name}" in lowered) or lowered.startswith("elyan")

    def _reply_style_for(self, profile: ConversationProfile, flow_analysis: Any, state: str) -> str:
        tone = profile.tone
        if state == "awaiting_confirmation":
            return "decisive"
        if tone == "warm_operator":
            return "warm"
        if tone == "formal":
            return "normal"
        if tone == "mentor" or getattr(flow_analysis, "intent", "") == "clarification":
            return "normal"
        return "terse"

    @staticmethod
    def _operator_mode_for(user_message: str, flow_analysis: Any) -> str:
        text = str(user_message or "").strip().lower()
        if any(token in text for token in ("burada mısın", "burda mısın", "orada mısın", "hazır mısın", "uyanık mısın", "bende misin")):
            return "presence"
        if any(token in text for token in ("olmadı", "olmadi", "çalışmıyor", "calismiyor", "fix", "hata", "error", "sorun", "takıldı", "takildi")):
            return "blocked_recovery"
        if any(token in text for token in ("plan", "adım", "adim", "strateji", "nasıl ilerleyelim", "yol haritası", "roadmap")):
            return "planner"
        if getattr(flow_analysis, "intent", "") == "command" or any(token in text for token in ("çöz", "coz", "yap", "oluştur", "olustur", "hazırla", "hazirla", "geliştir", "gelistir", "araştır", "arastir")):
            return "solver"
        return "standard"

    @staticmethod
    def _followup_suggestion(intent: str, followup_preference: str) -> str:
        if followup_preference == "low":
            return ""
        if intent == "command":
            return "İstersen buradan sonraki adımı da net çıkarayım."
        if intent == "question":
            return "İstersen bunu kısa örnekle de netleştireyim."
        return "İstersen buradan birlikte ilerleyelim."

    @staticmethod
    def _suggested_replies(intent: str, state: str, operator_mode: str) -> List[str]:
        if state == "voice_turn":
            return ["Biraz daha aç", "Kısaca özetle"]
        if operator_mode == "presence":
            return ["Buradan devam edelim", "Şu işi başlat", "Beni durumdan geçir"]
        if operator_mode == "blocked_recovery":
            return ["Alternatif yol dene", "Takıldığı yeri söyle", "Plan çıkar"]
        if operator_mode == "planner":
            return ["Plan çıkar", "Riskleri söyle", "En kısa yolu seç"]
        if operator_mode == "solver":
            return ["Buradan sen devam et", "Alternatif yol dene", "Önce plan çıkar"]
        if intent == "command":
            return ["Buradan devam et", "Önce göster"]
        if intent == "question":
            return ["Bir örnek ver", "Kısalt"]
        return ["Devam", "Yön değiştir"]

    @staticmethod
    def _ack_text(state: str, intent: str, operator_mode: str) -> str:
        if state == "voice_turn":
            return "Tamam, bakıyorum."
        if operator_mode == "presence":
            return "Buradayım."
        if operator_mode == "blocked_recovery":
            return "Tamam, bunu başka bir açıdan çözeceğim."
        if operator_mode == "solver":
            return "Tamam, üstüne gidiyorum."
        if intent == "command":
            return "Tamam, bunun üstüne gidiyorum."
        return "Bakıyorum."

    @staticmethod
    def _presence_note_for(state: str, operator_mode: str) -> str:
        if operator_mode == "presence":
            return "Yanındayım, buradan birlikte ilerleriz."
        if operator_mode == "blocked_recovery":
            return "Takılırsa yön değiştirip işi açıkta bırakmam."
        if operator_mode == "solver":
            return "Şimdi işi kapatmaya odaklanıyorum."
        if operator_mode == "planner":
            return "Önce net rota, sonra uygulama."
        if state == "voice_turn":
            return "Seni dinliyorum, kısa ve net gidelim."
        return "Hazırım, nereye ağırlık vermem gerektiğini söylemen yeterli."

    def _naturalize_response(
        self,
        *,
        raw_response: str,
        user_message: str,
        flow_analysis: Any,
        profile: ConversationProfile,
        delivery: DeliveryPlan,
        channel_type: str,
        metadata: Dict[str, Any],
        attachments: List[Any],
    ) -> str:
        text = self._strip_heavy_formatting(raw_response)
        if not text:
            text = "Hazır."
        text = self._rewrite_opening(text, profile, delivery)
        text = self._humanize_operator_voice(
            text=text,
            user_message=user_message,
            flow_analysis=flow_analysis,
            delivery=delivery,
        )
        text = self._trim_for_length(text, profile.response_length, voice=delivery.channel_behavior == "voice")
        if attachments and str(metadata.get("attachment_ack_sent") or "").strip() != "1":
            text = self._maybe_prefix_attachment_ack(text, delivery.channel_behavior, bool(metadata.get("is_group")))
        text = self._normalize_punctuation(text)
        return text.strip()

    def _strip_heavy_formatting(self, raw_response: str) -> str:
        lines: list[str] = []
        for line in str(raw_response or "").replace("\r\n", "\n").split("\n"):
            stripped = line.strip()
            if not stripped:
                if lines and lines[-1] != "":
                    lines.append("")
                continue
            stripped = self._EMOJI_PREFIX_RE.sub("", stripped)
            lowered = stripped.lower()
            if self._DECORATIVE_LINE_RE.match(stripped):
                continue
            if lowered in self._BOILERPLATE_LINES or lowered.startswith("premium ux response"):
                continue
            if lowered.startswith("öneriler:") or lowered.startswith("suggestions:"):
                continue
            if lowered.startswith("intent:") or lowered.startswith("context:"):
                continue
            if re.match(r"^\[\d+\]\s+", stripped):
                continue
            lines.append(stripped)
        text = "\n".join(lines).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text

    @staticmethod
    def _process_multimodal(items: List[Any]) -> List[Dict[str, str]]:
        context: List[Dict[str, str]] = []
        for item in items:
            path = str(item or "")
            lowered = path.lower()
            if lowered.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                media_type = "image"
            elif lowered.endswith((".mp3", ".wav", ".ogg", ".m4a", ".aac")):
                media_type = "audio"
            elif lowered.endswith((".mp4", ".avi", ".mov", ".mkv")):
                media_type = "video"
            elif lowered.endswith((".pdf", ".doc", ".docx", ".txt")):
                media_type = "document"
            else:
                media_type = "file"
            context.append({"path": path, "type": media_type})
        return context

    def _rewrite_opening(self, text: str, profile: ConversationProfile, delivery: DeliveryPlan) -> str:
        if not text:
            return text
        lowered_full = text.lower()
        for phrase in (
            "size nasıl yardımcı olabilirim?",
            "nasıl yardımcı olabilirim?",
            "yardımcı olabilirim.",
        ):
            if phrase in lowered_full:
                pattern = re.compile(re.escape(phrase), re.IGNORECASE)
                text = pattern.sub("", text, count=1).strip()
                text = re.sub(r"^\s*[,.!?]+\s*", "", text)
                lowered_full = text.lower()
        first_sentence, sep, rest = text.partition(". ")
        lowered = first_sentence.lower()
        greeting_patterns = (
            "merhaba",
            "selam",
            "tabii",
            "elbette",
            "memnuniyetle",
            "size yardımcı olayım",
        )
        if any(lowered.startswith(pattern) for pattern in greeting_patterns):
            replacement = "Tamam" if delivery.reply_style == "warm" else ""
            rebuilt = f"{replacement}. {rest}".strip(". ").strip() if rest else replacement
            text = rebuilt or rest or text
        if profile.tone == "formal":
            return text
        return text.replace("Lütfen", "İstersen", 1)

    def _humanize_operator_voice(
        self,
        *,
        text: str,
        user_message: str,
        flow_analysis: Any,
        delivery: DeliveryPlan,
    ) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return cleaned

        if delivery.operator_mode == "planner" and not self._has_plan_language(cleaned):
            cleaned = f"Şöyle ilerleyelim: {self._lowercase_sentence_start(cleaned)}"
        elif delivery.operator_mode == "solver" and not self._has_solution_stance(cleaned):
            cleaned = f"Bunu çözelim. {cleaned}"
        elif delivery.operator_mode == "presence" and "buradayım" not in cleaned.lower():
            cleaned = f"Buradayım. {cleaned}"

        if delivery.should_offer_method and self._looks_stuck(cleaned) and not self._offers_alternative(cleaned):
            cleaned = f"{cleaned} Olmazsa alternatif bir yol da çıkarırım."
        elif delivery.operator_mode == "blocked_recovery" and not self._offers_alternative(cleaned):
            cleaned = f"{cleaned} Gerekirse ikinci bir yöntem de deneriz."

        if getattr(flow_analysis, "intent", "") == "question" and self._looks_overly_flat(cleaned):
            cleaned = f"{cleaned} İstersen bunu kısa mantığıyla da açarım."
        if delivery.operator_mode == "standard" and self._sounds_detached(cleaned):
            cleaned = f"Tamam. {cleaned}"

        return cleaned

    @staticmethod
    def _has_plan_language(text: str) -> bool:
        low = str(text or "").lower()
        return any(token in low for token in ("şöyle ilerleyelim", "önce", "sonra", "ilk adım", "plan", "adım"))

    @staticmethod
    def _has_solution_stance(text: str) -> bool:
        low = str(text or "").lower()
        return any(token in low for token in ("çözelim", "halledeceğim", "hallederim", "ilerleyelim", "üstüne gidiyorum", "bunu yapacağım", "şunu yapacağım"))

    @staticmethod
    def _looks_stuck(text: str) -> bool:
        low = str(text or "").lower()
        return any(token in low for token in ("olmadı", "olmadi", "başaramadım", "basaramadim", "yapamadım", "yapamadim", "takıldı", "takildi", "engel", "blocked", "failed", "başarısız", "basarisiz"))

    @staticmethod
    def _offers_alternative(text: str) -> bool:
        low = str(text or "").lower()
        return any(token in low for token in ("alternatif", "başka yol", "ikinci yol", "yöntem", "method", "fallback", "deneyebiliriz", "deneriz"))

    @staticmethod
    def _looks_overly_flat(text: str) -> bool:
        low = str(text or "").strip().lower()
        return len(low.split()) <= 8 and not any(token in low for token in ("çünkü", "çunku", "sebep", "neden", "mantık", "mantik"))

    @staticmethod
    def _sounds_detached(text: str) -> bool:
        low = str(text or "").strip().lower()
        return len(low.split()) <= 6 and not any(token in low for token in ("tamam", "buradayım", "bakıyorum", "halledelim", "çözelim", "ilerleyelim"))

    @staticmethod
    def _lowercase_sentence_start(text: str) -> str:
        value = str(text or "").strip()
        if len(value) <= 1:
            return value.lower()
        return value[:1].casefold() + value[1:]

    @staticmethod
    def _trim_for_length(text: str, response_length: str, voice: bool = False) -> str:
        clean = str(text or "").strip()
        if not clean:
            return ""
        paragraph_limit = 1 if response_length == "short" else 2 if response_length == "medium" else 3
        parts = [part.strip() for part in clean.split("\n") if part.strip()]
        clean = "\n".join(parts[:paragraph_limit])
        sentence_limit = 2 if response_length == "short" else 4 if response_length == "medium" else 6
        if voice:
            sentence_limit = min(sentence_limit, 2)
        sentences = re.split(r"(?<=[.!?])\s+", clean)
        trimmed = " ".join(sentence.strip() for sentence in sentences[:sentence_limit] if sentence.strip())
        return trimmed or clean

    @staticmethod
    def _normalize_punctuation(text: str) -> str:
        value = re.sub(r"[ \t]+", " ", str(text or "").strip())
        value = re.sub(r"\s+([,.!?])", r"\1", value)
        return value

    @staticmethod
    def _maybe_prefix_attachment_ack(text: str, channel_behavior: str, is_group: bool) -> str:
        if is_group and channel_behavior not in {"inline_reply", "group_mention"}:
            return text
        if text.lower().startswith(("aldım", "görüyorum", "bakıyorum")):
            return text
        return f"Aldım, bakıyorum. {text}".strip()

    def _learn_from_turn(
        self,
        *,
        user_id: str,
        channel_type: str,
        metadata: Dict[str, Any],
        profile: ConversationProfile,
        user_message: str,
        delivery: DeliveryPlan,
    ) -> None:
        if str(profile.privacy_mode).lower() == "maximum":
            return
        lowered = str(user_message or "").lower()
        response_length = "short"
        if len(user_message.split()) > 22 or "detay" in lowered or "ayrıntı" in lowered:
            response_length = "medium"
        if any(token in lowered for token in ("kısa", "kisa", "özet", "ozet")):
            response_length = "short"
        self._profiles.update_conversation_profile(
            user_id,
            tone=profile.tone_for_channel(channel_type),
            response_length=response_length,
            channel_type=channel_type,
            channel_tone=profile.tone_for_channel(channel_type),
            followup_preference="balanced",
            decision_style="direct",
            prefers_brief_answers=response_length == "short",
            project_hint=str(metadata.get("workspace_id") or "")[:80] or None,
        )

    @staticmethod
    def _trust_summary(privacy_mode: str, metadata: Dict[str, Any]) -> str:
        if str(privacy_mode).lower() == "maximum":
            return "Maximum Privacy açık. Sohbet içeriği öğrenmeye yazılmıyor."
        if metadata.get("is_group"):
            return "Grup bağlamında özel connector verisi paylaşılmaz."
        return "Dengeli gizlilik açık. Operasyonel öğrenme redacted tutulur."

    @staticmethod
    def _channel_behavior_label(channel_behavior: str) -> str:
        return {
            "dm": "dm",
            "group_mention": "group_mention",
            "inline_reply": "inline_reply",
            "voice": "voice",
        }.get(channel_behavior, "dm")
