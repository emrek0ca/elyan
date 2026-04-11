"""
Briefing Manager - Proactive intelligence and system status synthesis
"""

import asyncio
import importlib.util
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path
from utils.logger import get_logger
from core.compat.legacy_tool_wrappers import normalize_legacy_tool_payload
from core.llm_client import LLMClient
from core.advanced_features import get_anomaly_detector
from core.task_executor import TaskExecutor
from tools import AVAILABLE_TOOLS

logger = get_logger("briefing_manager")


@dataclass(slots=True)
class MorningDigestItem:
    title: str
    detail: str = ""
    at: str = ""
    source: str = ""
    url: str = ""
    priority: str = "normal"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "detail": self.detail,
            "at": self.at,
            "source": self.source,
            "url": self.url,
            "priority": self.priority,
            "metadata": dict(self.metadata or {}),
        }


@dataclass(slots=True)
class MorningDigest:
    summary: str
    calendar_items: list[MorningDigestItem] = field(default_factory=list)
    email_items: list[MorningDigestItem] = field(default_factory=list)
    news_items: list[MorningDigestItem] = field(default_factory=list)
    system_notes: list[str] = field(default_factory=list)
    proactive_actions: list[str] = field(default_factory=list)
    speech_script: str = ""
    source_trace: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "calendar_items": [item.to_dict() for item in self.calendar_items],
            "email_items": [item.to_dict() for item in self.email_items],
            "news_items": [item.to_dict() for item in self.news_items],
            "system_notes": list(self.system_notes or []),
            "proactive_actions": list(self.proactive_actions or []),
            "speech_script": self.speech_script,
            "source_trace": {key: dict(value or {}) for key, value in dict(self.source_trace or {}).items()},
        }

    def render_terminal(self) -> str:
        lines: list[str] = [self.summary.strip()]
        if self.calendar_items:
            lines.append("")
            lines.append("Takvim")
            for item in self.calendar_items[:3]:
                when = f" ({item.at})" if item.at else ""
                lines.append(f"- {item.title}{when}")
        if self.email_items:
            lines.append("")
            lines.append("E-posta")
            for item in self.email_items[:3]:
                lines.append(f"- {item.title}")
        if self.news_items:
            lines.append("")
            lines.append("Haberler")
            for item in self.news_items[:2]:
                lines.append(f"- {item.title}")
        if self.proactive_actions:
            lines.append("")
            lines.append("Öneriler")
            for item in self.proactive_actions[:3]:
                lines.append(f"- {item}")
        return "\n".join(line for line in lines if line is not None).strip()

    def render_mobile(self) -> str:
        lines = [self.summary.strip()]
        if self.calendar_items:
            lines.append(f"Takvim: {', '.join(item.title for item in self.calendar_items[:2])}")
        if self.email_items:
            lines.append(f"E-posta: {', '.join(item.title for item in self.email_items[:2])}")
        if self.proactive_actions:
            lines.append(f"Öneri: {self.proactive_actions[0]}")
        return "\n".join(line for line in lines if line).strip()


class BriefingManager:
    """Synthesizes system status and proactive suggestions"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()
        self.anomaly_detector = get_anomaly_detector()

    async def _execute_registry_tool(self, tool_name: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        tool = AVAILABLE_TOOLS.get(str(tool_name or "").strip())
        if not callable(tool):
            return normalize_legacy_tool_payload(
                {
                    "success": False,
                    "status": "failed",
                    "error": f"Tool not found: {tool_name}",
                    "errors": ["UNKNOWN_TOOL"],
                    "data": {"error_code": "UNKNOWN_TOOL"},
                },
                tool=str(tool_name or ""),
                source="briefing_manager",
            )
        return await TaskExecutor().execute(tool, dict(params or {}))

    async def get_proactive_briefing(
        self,
        include_weather: bool = True,
        include_calendar: bool = True,
        include_news: bool = True,
        include_email: bool = True,
    ) -> Dict[str, Any]:
        """Generate a comprehensive morning briefing with all data sources"""
        try:
            # 1. Gather system data
            system_info = await self._execute_registry_tool("get_system_info")
            anomalies = self.anomaly_detector.get_anomalies(limit=5)
            
            # 2. Gather external data sources (Phase 12.2)
            weather_data = await self._get_weather() if include_weather else None
            local_calendar_data = await self._get_calendar() if include_calendar else None
            connector_calendar_data = await self._get_google_calendar_digest() if include_calendar else None
            calendar_data = self._merge_calendar_digest(local_calendar_data, connector_calendar_data) if include_calendar else None
            news_data = await self._get_news() if include_news else None
            email_data = await self._get_email_digest() if include_email else None
            
            # 3. Prepare context for LLM
            context = {
                "system": {
                    "cpu": system_info.get("cpu_percent"),
                    "memory": system_info.get("memory_percent"),
                    "disk": system_info.get("disk_usage", {}).get("percent"),
                    "os": system_info.get("os_version")
                },
                "anomalies": anomalies,
                "time": datetime.now().strftime("%H:%M:%S"),
                "date": datetime.now().strftime("%d %B %Y"),
                "weather": weather_data,
                "calendar": calendar_data,
                "news": news_data,
                "email": email_data,
            }

            # 4. Use LLM to synthesize the briefing
            briefing_text = await self._generate_briefing_text(context)
            digest = self._build_digest(context, briefing_text)
            
            return {
                "success": True,
                "briefing": briefing_text,
                "digest": digest.to_dict(),
                "renders": {
                    "terminal": digest.render_terminal(),
                    "mobile": digest.render_mobile(),
                    "speech": digest.speech_script,
                },
                "speech_script": digest.speech_script,
                "mode": "digest",
                "metrics": {
                    "health_score": self._calculate_health_score(system_info, anomalies),
                    "cpu": system_info.get("cpu_percent"),
                    "mem": system_info.get("memory_percent")
                },
                "timestamp": datetime.now().isoformat(),
                "data_sources": {
                    "weather": weather_data is not None,
                    "calendar": calendar_data is not None,
                    "news": news_data is not None,
                    "email": email_data is not None,
                }
            }

        except Exception as e:
            logger.error(f"Briefing generation failed: {e}")
            return {"success": False, "error": str(e)}

    async def _generate_briefing_text(self, context: Dict[str, Any]) -> str:
        """Use LLM to create a comprehensive briefing with all data sources"""
        prompt = f"""Bir yapay zeka asistanı (Elyan) olarak kullanıcıya kapsamlı bir sabah brifingi ver.

VERİLER:
{context}

KURALLAR:
1. Günün saatine göre selamlaşma ile başla.
2. Hava durumu varsa kısaca belirt (sıcaklık ve durum).
3. Takvim etkinlikleri varsa özetle (bugün için).
4. Önemli haber başlıklarından 1-2 tanesini belirt.
5. Sistem sağlığı hakkında kısa bilgi ver.
6. Anomali veya uyarı varsa bildir.
7. 2-3 proaktif öneri sun (örn: "Şemsiye al" veya "Toplantıya 1 saat var").
8. Tonun enerjik, yardımsever ve motive edici olsun.
9. Markdown formatında (bold, emojiler, listeler) döndür.
10. Maksimum 15 satır tut.

BRİFİNG:"""
        
        try:
            response = await self.llm.generate(prompt, user_id="system")
            if str(response or "").strip():
                return str(response).strip()
        except Exception as exc:
            logger.warning(f"LLM briefing synthesis failed: {exc}")
        return "Sistem şu an stabil görünüyor. Size nasıl yardımcı olabilirim?"

    async def _get_weather(self) -> Optional[Dict[str, Any]]:
        """Fetch weather data"""
        try:
            from core.proactive.briefing_sources import get_weather_service
            weather_svc = get_weather_service()
            result = await weather_svc.get_current_weather(city="Istanbul")
            return result if result.get("success") else None
        except Exception as e:
            logger.debug(f"Weather fetch skipped: {e}")
            return None
    
    async def _get_calendar(self) -> Optional[Dict[str, Any]]:
        """Fetch calendar events"""
        try:
            from core.proactive.briefing_sources import get_calendar_service
            calendar_svc = get_calendar_service()
            result = await calendar_svc.get_today_events()
            return result if result.get("success") else None
        except Exception as e:
            logger.debug(f"Calendar fetch skipped: {e}")
            return None
    
    async def _get_news(self) -> Optional[Dict[str, Any]]:
        """Fetch news headlines"""
        try:
            from core.proactive.briefing_sources import get_news_service
            news_svc = get_news_service()
            result = await news_svc.get_headlines(max_items=5)
            return result if result.get("success") else None
        except Exception as e:
            logger.debug(f"News fetch skipped: {e}")
            return None

    async def _get_email_digest(self) -> Optional[Dict[str, Any]]:
        local_messages = await self._get_local_mail_digest()
        connector_messages = await self._get_google_mail_digest()
        combined = list(local_messages or [])
        seen = {
            (
                str(item.get("title") or "").strip().lower(),
                str(item.get("detail") or "").strip().lower(),
            )
            for item in combined
        }
        for item in list(connector_messages or []):
            key = (
                str(item.get("title") or "").strip().lower(),
                str(item.get("detail") or "").strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            combined.append(item)
        if not combined:
            return None
        return {
            "success": True,
            "messages": combined[:5],
            "count": len(combined[:5]),
            "local_available": bool(local_messages),
            "connector_available": bool(connector_messages),
        }

    def _merge_calendar_digest(self, local_payload: Optional[dict], connector_payload: Optional[dict]) -> Optional[Dict[str, Any]]:
        events: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for payload in (local_payload, connector_payload):
            if not isinstance(payload, dict):
                continue
            for event in list(payload.get("events") or [])[:5]:
                title = str(event.get("title") or event.get("summary") or "").strip()
                start = str(event.get("start") or event.get("start_time") or "").strip()
                key = (title.lower(), start.lower())
                if key in seen:
                    continue
                seen.add(key)
                events.append(dict(event))
        if not events:
            return None
        return {
            "success": True,
            "events": events[:5],
            "count": len(events[:5]),
            "local_available": bool(local_payload),
            "connector_available": bool(connector_payload),
        }

    async def _get_local_mail_digest(self) -> list[dict[str, Any]]:
        try:
            from core.genesis.preemptive_subconscious import PreemptiveSubconscious

            scanner = PreemptiveSubconscious(agent_instance=None)
            messages = scanner._read_unread_mac_mail()
        except Exception as exc:
            logger.debug(f"Local mail digest skipped: {exc}")
            return []
        normalized: list[dict[str, Any]] = []
        for item in list(messages or [])[:5]:
            sender = str(item.get("sender") or "").strip()
            subject = str(item.get("subject") or "").strip()
            if not sender and not subject:
                continue
            normalized.append(
                {
                    "title": subject or "Yeni e-posta",
                    "detail": sender,
                    "source": "apple_mail",
                }
            )
        return normalized

    def _build_google_connector(self):
        if importlib.util.find_spec("googleapiclient.discovery") is None:
            return None
        try:
            from integrations import oauth_broker
            from integrations.base import (
                AuthStrategy,
                ConnectorState,
                FallbackPolicy,
                IntegrationCapability,
                IntegrationType,
            )
            from integrations.connectors.google import GoogleConnector

            accounts = oauth_broker.list_accounts("google")
            account = next((item for item in accounts if getattr(item, "is_ready", False)), None)
            if account is None:
                return None
            capability = IntegrationCapability(
                name="morning_digest",
                provider="google",
                integration_type=IntegrationType.API,
                required_scopes=["email.read", "calendar.read"],
                auth_strategy=AuthStrategy.OAUTH,
                fallback_policy=FallbackPolicy.WEB,
                connector_name="google",
            )
            if getattr(account, "status", "") != ConnectorState.READY:
                return None
            return GoogleConnector(
                capability=capability,
                auth_account=account,
                provider="google",
                connector_name="google",
            )
        except Exception as exc:
            logger.debug(f"Google connector unavailable for briefing: {exc}")
            return None

    async def _get_google_mail_digest(self) -> list[dict[str, Any]]:
        connector = self._build_google_connector()
        if connector is None:
            return []
        try:
            service = connector._service("gmail", "v1")
            if service is None:
                return []
            listing = service.users().messages().list(userId="me", labelIds=["INBOX"], maxResults=5).execute()
            messages: list[dict[str, Any]] = []
            for item in list(listing.get("messages") or [])[:5]:
                message_id = str(item.get("id") or "").strip()
                if not message_id:
                    continue
                payload = service.users().messages().get(
                    userId="me",
                    id=message_id,
                    format="metadata",
                    metadataHeaders=["Subject", "From"],
                ).execute()
                headers = {
                    str(header.get("name") or "").strip().lower(): str(header.get("value") or "").strip()
                    for header in list(payload.get("payload", {}).get("headers") or [])
                    if isinstance(header, dict)
                }
                messages.append(
                    {
                        "title": headers.get("subject") or "Yeni Gmail mesajı",
                        "detail": headers.get("from") or "",
                        "source": "gmail",
                    }
                )
            return messages
        except Exception as exc:
            logger.debug(f"Gmail digest skipped: {exc}")
            return []

    async def _get_google_calendar_digest(self) -> Optional[Dict[str, Any]]:
        connector = self._build_google_connector()
        if connector is None:
            return None
        try:
            service = connector._service("calendar", "v3")
            if service is None:
                return None
            listing = service.events().list(calendarId="primary", maxResults=5, singleEvents=True, orderBy="startTime").execute()
            events: list[dict[str, Any]] = []
            for item in list(listing.get("items") or [])[:5]:
                start_block = item.get("start") or {}
                end_block = item.get("end") or {}
                events.append(
                    {
                        "title": str(item.get("summary") or "Takvim etkinliği").strip(),
                        "start": str(start_block.get("dateTime") or start_block.get("date") or "").strip(),
                        "end": str(end_block.get("dateTime") or end_block.get("date") or "").strip(),
                        "source": "google_calendar",
                    }
                )
            if not events:
                return None
            return {
                "success": True,
                "events": events,
                "count": len(events),
                "connector_available": True,
            }
        except Exception as exc:
            logger.debug(f"Google Calendar digest skipped: {exc}")
            return None

    def _build_digest(self, context: Dict[str, Any], summary: str) -> MorningDigest:
        calendar_items = self._normalize_calendar_items(context.get("calendar"))
        email_items = self._normalize_email_items(context.get("email"))
        news_items = self._normalize_news_items(context.get("news"))
        system_notes = self._build_system_notes(context)
        proactive_actions = self._build_proactive_actions(context, calendar_items, email_items)
        speech_script = self._build_speech_script(context, calendar_items, email_items, news_items, proactive_actions)
        source_trace = self._build_source_trace(context)
        return MorningDigest(
            summary=str(summary or "").strip(),
            calendar_items=calendar_items,
            email_items=email_items,
            news_items=news_items,
            system_notes=system_notes,
            proactive_actions=proactive_actions,
            speech_script=speech_script,
            source_trace=source_trace,
        )

    def _normalize_calendar_items(self, payload: Any) -> list[MorningDigestItem]:
        events = list((payload or {}).get("events") or [])
        items: list[MorningDigestItem] = []
        for event in events[:5]:
            title = str(event.get("title") or event.get("summary") or "").strip()
            if not title:
                continue
            items.append(
                MorningDigestItem(
                    title=title,
                    detail=str(event.get("description") or "").strip(),
                    at=str(event.get("start") or event.get("start_time") or "").strip(),
                    source="calendar",
                    metadata=dict(event or {}),
                )
            )
        return items

    def _normalize_email_items(self, payload: Any) -> list[MorningDigestItem]:
        messages = list((payload or {}).get("messages") or [])
        items: list[MorningDigestItem] = []
        for message in messages[:5]:
            title = str(message.get("title") or message.get("subject") or "").strip()
            detail = str(message.get("detail") or message.get("from") or message.get("sender") or "").strip()
            if not title and not detail:
                continue
            items.append(
                MorningDigestItem(
                    title=title or "Yeni e-posta",
                    detail=detail,
                    source=str(message.get("source") or "email"),
                    metadata=dict(message or {}),
                )
            )
        return items

    def _normalize_news_items(self, payload: Any) -> list[MorningDigestItem]:
        headlines = list((payload or {}).get("headlines") or [])
        items: list[MorningDigestItem] = []
        for headline in headlines[:5]:
            title = str(headline.get("title") or "").strip()
            if not title:
                continue
            items.append(
                MorningDigestItem(
                    title=title,
                    detail=str(headline.get("published") or "").strip(),
                    source="news",
                    url=str(headline.get("link") or "").strip(),
                    metadata=dict(headline or {}),
                )
            )
        return items

    def _build_system_notes(self, context: Dict[str, Any]) -> list[str]:
        system = dict(context.get("system") or {})
        notes = [
            f"CPU %{system.get('cpu')}" if system.get("cpu") is not None else "",
            f"Bellek %{system.get('memory')}" if system.get("memory") is not None else "",
            f"Disk %{system.get('disk')}" if system.get("disk") is not None else "",
        ]
        notes = [item for item in notes if item]
        anomalies = list(context.get("anomalies") or [])
        for item in anomalies[:2]:
            notes.append(str(item))
        return notes

    def _build_proactive_actions(
        self,
        context: Dict[str, Any],
        calendar_items: list[MorningDigestItem],
        email_items: list[MorningDigestItem],
    ) -> list[str]:
        actions: list[str] = []
        weather = dict(context.get("weather") or {})
        description = str(weather.get("description") or "").lower()
        if any(token in description for token in ("yağ", "rain", "sağanak", "storm")):
            actions.append("Dışarı çıkacaksan şemsiye al.")
        if calendar_items:
            first_event = calendar_items[0]
            if first_event.at:
                actions.append(f"İlk toplantın için {first_event.at} öncesi hazırlık yap.")
        if len(email_items) >= 3:
            actions.append("E-posta kutusunda öncelikli mesajları ilk blokta temizle.")
        if not actions and weather.get("temperature") is not None:
            actions.append("Günü başlatmadan önce en kritik işi tek blokta kapat.")
        return actions[:3]

    def _build_speech_script(
        self,
        context: Dict[str, Any],
        calendar_items: list[MorningDigestItem],
        email_items: list[MorningDigestItem],
        news_items: list[MorningDigestItem],
        proactive_actions: list[str],
    ) -> str:
        parts = ["Günaydın."]
        weather = dict(context.get("weather") or {})
        if weather.get("temperature") is not None:
            parts.append(
                f"Hava {int(weather.get('temperature'))} derece ve {str(weather.get('description') or '').strip()}."
            )
        if calendar_items:
            first = calendar_items[0]
            when = f" saat {first.at}" if first.at else ""
            parts.append(f"Bugün {len(calendar_items)} etkinliğin var. İlk etkinlik{when}: {first.title}.")
        if email_items:
            parts.append(f"Gözden geçirmen gereken {len(email_items)} e-posta özeti hazır.")
        if news_items:
            parts.append(f"Öne çıkan haber: {news_items[0].title}.")
        if proactive_actions:
            parts.append(f"Önerim: {proactive_actions[0]}")
        return " ".join(part for part in parts if part).strip()

    def _build_source_trace(self, context: Dict[str, Any]) -> dict[str, dict[str, Any]]:
        trace: dict[str, dict[str, Any]] = {}
        for name, key in (
            ("weather", "weather"),
            ("calendar", "calendar"),
            ("news", "news"),
            ("email", "email"),
        ):
            payload = context.get(key)
            count = 0
            if isinstance(payload, dict):
                if "events" in payload:
                    count = len(list(payload.get("events") or []))
                elif "messages" in payload:
                    count = len(list(payload.get("messages") or []))
                elif "headlines" in payload:
                    count = len(list(payload.get("headlines") or []))
            trace[name] = {
                "available": payload is not None,
                "item_count": count,
                "mode": "local_or_connector",
            }
        return trace
    
    def _calculate_health_score(self, sys_info: Dict[str, Any], anomalies: List[Any]) -> int:
        """Calculate a 0-100 health score"""
        score = 100
        
        # CPU/MEM penalties
        if sys_info.get("cpu_percent", 0) > 80: score -= 20
        if sys_info.get("memory_percent", 0) > 90: score -= 20
        
        # Anomaly penalties
        score -= (len(anomalies) * 10)
        
        return max(0, min(100, score))

# Global instance
_briefing_manager = None

def get_briefing_manager() -> BriefingManager:
    global _briefing_manager
    if _briefing_manager is None:
        _briefing_manager = BriefingManager()
    return _briefing_manager
