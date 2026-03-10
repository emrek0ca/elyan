"""
Briefing Manager - Proactive intelligence and system status synthesis
"""

import asyncio
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

    async def get_proactive_briefing(self, include_weather=True, include_calendar=True, include_news=True) -> Dict[str, Any]:
        """Generate a comprehensive morning briefing with all data sources"""
        try:
            # 1. Gather system data
            system_info = await self._execute_registry_tool("get_system_info")
            anomalies = self.anomaly_detector.get_anomalies(limit=5)
            
            # 2. Gather external data sources (Phase 12.2)
            weather_data = await self._get_weather() if include_weather else None
            calendar_data = await self._get_calendar() if include_calendar else None
            news_data = await self._get_news() if include_news else None
            
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
                "news": news_data
            }

            # 4. Use LLM to synthesize the briefing
            briefing_text = await self._generate_briefing_text(context)
            
            return {
                "success": True,
                "briefing": briefing_text,
                "metrics": {
                    "health_score": self._calculate_health_score(system_info, anomalies),
                    "cpu": system_info.get("cpu_percent"),
                    "mem": system_info.get("memory_percent")
                },
                "timestamp": datetime.now().isoformat(),
                "data_sources": {
                    "weather": weather_data is not None,
                    "calendar": calendar_data is not None,
                    "news": news_data is not None
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
            return response
        except:
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
