"""
Enhanced data sources for morning briefing.

Provides:
- Weather data from OpenWeatherMap API
- macOS Calendar events via AppleScript
- Turkish news headlines via RSS feeds
"""

import asyncio
import subprocess
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import httpx
import feedparser
from utils.logger import get_logger
from config.settings import OPENWEATHER_API_KEY

logger = get_logger("briefing_sources")


class WeatherService:
    """Fetch weather data from OpenWeatherMap API"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or OPENWEATHER_API_KEY
        self.base_url = "https://api.openweathermap.org/data/2.5"
    
    async def get_current_weather(self, city: str = "Istanbul") -> Dict[str, Any]:
        """
        Get current weather for a city.
        
        Args:
            city: City name (default: Istanbul)
        
        Returns:
            Weather data dict with temperature, description, etc.
        """
        if not self.api_key:
            logger.warning("OpenWeatherMap API key not configured")
            return {
                "success": False,
                "error": "API key not configured",
                "message": "Hava durumu için API anahtarı gerekli"
            }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                params = {
                    "q": city,
                    "appid": self.api_key,
                    "units": "metric",  # Celsius
                    "lang": "tr"  # Turkish descriptions
                }
                
                response = await client.get(
                    f"{self.base_url}/weather",
                    params=params
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    return {
                        "success": True,
                        "city": data["name"],
                        "temperature": round(data["main"]["temp"]),
                        "feels_like": round(data["main"]["feels_like"]),
                        "description": data["weather"][0]["description"],
                        "humidity": data["main"]["humidity"],
                        "wind_speed": data["wind"]["speed"],
                        "icon": data["weather"][0]["icon"]
                    }
                else:
                    logger.error(f"Weather API error: {response.status_code}")
                    return {
                        "success": False,
                        "error": f"API returned {response.status_code}"
                    }
        
        except Exception as e:
            logger.error(f"Weather fetch error: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_forecast(self, city: str = "Istanbul", days: int = 3) -> Dict[str, Any]:
        """Get weather forecast for next N days"""
        if not self.api_key:
            return {"success": False, "error": "API key not configured"}
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                params = {
                    "q": city,
                    "appid": self.api_key,
                    "units": "metric",
                    "lang": "tr",
                    "cnt": days * 8  # 8 forecasts per day (3-hour intervals)
                }
                
                response = await client.get(
                    f"{self.base_url}/forecast",
                    params=params
                )
                
                if response.status_code == 200:
                    data = response.json()
                    daily_forecasts = []
                    
                    # Group by day
                    for i in range(0, len(data["list"]), 8):
                        day_data = data["list"][i]
                        daily_forecasts.append({
                            "date": datetime.fromtimestamp(day_data["dt"]).strftime("%d %B"),
                            "temp_max": round(max([item["main"]["temp_max"] for item in data["list"][i:i+8]])),
                            "temp_min": round(min([item["main"]["temp_min"] for item in data["list"][i:i+8]])),
                            "description": day_data["weather"][0]["description"]
                        })
                    
                    return {
                        "success": True,
                        "forecasts": daily_forecasts[:days]
                    }
                else:
                    return {"success": False, "error": f"API returned {response.status_code}"}
        
        except Exception as e:
            logger.error(f"Forecast fetch error: {e}")
            return {"success": False, "error": str(e)}


class CalendarService:
    """Fetch events from macOS Calendar via AppleScript"""
    
    async def get_today_events(self) -> Dict[str, Any]:
        """
        Get today's calendar events via AppleScript.
        
        Returns:
            List of events with title, start time, end time
        """
        try:
            # AppleScript to fetch today's events
            script = '''
                tell application "Calendar"
                    set today to current date
                    set beginning of today to today
                    set time of today to 0
                    set end of today to today + (1 * days)
                    
                    set eventList to {}
                    repeat with cal in calendars
                        set calEvents to (every event of cal whose start date is greater than or equal to today and start date is less than end of today)
                        set eventList to eventList & calEvents
                    end repeat
                    
                    set output to ""
                    repeat with evt in eventList
                        set output to output & summary of evt & "|" & (start date of evt as string) & "|" & (end date of evt as string) & "\\n"
                    end repeat
                    
                    return output
                end tell
            '''
            
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                logger.warning(f"Calendar fetch failed: {result.stderr}")
                return {
                    "success": False,
                    "error": "Calendar access failed",
                    "events": []
                }
            
            # Parse output
            events = []
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                
                parts = line.split('|')
                if len(parts) >= 3:
                    events.append({
                        "title": parts[0].strip(),
                        "start": parts[1].strip(),
                        "end": parts[2].strip()
                    })
            
            return {
                "success": True,
                "events": events,
                "count": len(events)
            }
        
        except subprocess.TimeoutExpired:
            logger.error("Calendar fetch timeout")
            return {"success": False, "error": "Timeout", "events": []}
        except Exception as e:
            logger.error(f"Calendar fetch error: {e}")
            return {"success": False, "error": str(e), "events": []}


class NewsService:
    """Fetch Turkish news headlines via RSS"""
    
    TURKISH_NEWS_FEEDS = [
        "https://www.aa.com.tr/tr/rss/default?cat=guncel",  # Anadolu Ajansı
        "https://www.ntv.com.tr/gundem.rss",  # NTV
        "https://www.hurriyet.com.tr/rss/gundem",  # Hürriyet
    ]
    
    async def get_headlines(self, max_items: int = 5) -> Dict[str, Any]:
        """
        Fetch latest Turkish news headlines.
        
        Args:
            max_items: Maximum number of headlines to return
        
        Returns:
            List of news headlines with title, link, published date
        """
        try:
            headlines = []
            
            for feed_url in self.TURKISH_NEWS_FEEDS[:1]:  # Start with first feed
                try:
                    # Run feedparser in thread pool (it's blocking)
                    loop = asyncio.get_event_loop()
                    feed = await loop.run_in_executor(
                        None,
                        feedparser.parse,
                        feed_url
                    )
                    
                    for entry in feed.entries[:max_items]:
                        headlines.append({
                            "title": entry.get("title", ""),
                            "link": entry.get("link", ""),
                            "published": entry.get("published", "")
                        })
                    
                    if headlines:
                        break  # Got headlines, stop
                
                except Exception as e:
                    logger.warning(f"Failed to fetch from {feed_url}: {e}")
                    continue
            
            return {
                "success": len(headlines) > 0,
                "headlines": headlines[:max_items],
                "count": len(headlines)
            }
        
        except Exception as e:
            logger.error(f"News fetch error: {e}")
            return {
                "success": False,
                "error": str(e),
                "headlines": []
            }


# Global service instances
_weather_service: Optional[WeatherService] = None
_calendar_service: Optional[CalendarService] = None
_news_service: Optional[NewsService] = None


def get_weather_service() -> WeatherService:
    """Get singleton weather service instance"""
    global _weather_service
    if _weather_service is None:
        _weather_service = WeatherService()
    return _weather_service


def get_calendar_service() -> CalendarService:
    """Get singleton calendar service instance"""
    global _calendar_service
    if _calendar_service is None:
        _calendar_service = CalendarService()
    return _calendar_service


def get_news_service() -> NewsService:
    """Get singleton news service instance"""
    global _news_service
    if _news_service is None:
        _news_service = NewsService()
    return _news_service
