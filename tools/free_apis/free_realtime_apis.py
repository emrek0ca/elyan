"""
tools/free_apis/free_realtime_apis.py
─────────────────────────────────────────────────────────────────────────────
Free Real-Time Data APIs — Zero cost, no API key required.
Open-Meteo (Weather), CoinGecko (Crypto), ExchangeRate (Currency).
"""

import httpx
from utils.logger import get_logger

logger = get_logger("free_realtime_apis")

TIMEOUT = 10


async def get_weather_openmeteo(latitude: float, longitude: float, city_name: str = "") -> dict:
    """
    Open-Meteo üzerinden detaylı hava durumu bilgisi getirir.
    Parametreler: latitude (float), longitude (float), city_name (str, opsiyonel).
    """
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={latitude}&longitude={longitude}"
            f"&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code"
            f"&timezone=auto&forecast_days=3"
        )
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return {"success": False, "error": f"Open-Meteo hatası: {resp.status_code}"}
            
            data = resp.json()
            current = data.get("current", {})
            daily = data.get("daily", {})
            
            weather_codes = {
                0: "☀️ Açık", 1: "🌤️ Hafif bulutlu", 2: "⛅ Parçalı bulutlu",
                3: "☁️ Kapalı", 45: "🌫️ Sisli", 48: "🌫️ Kırağılı sis",
                51: "🌦️ Hafif çiseleme", 53: "🌧️ Orta çiseleme", 55: "🌧️ Yoğun çiseleme",
                61: "🌧️ Hafif yağmur", 63: "🌧️ Orta yağmur", 65: "🌧️ Şiddetli yağmur",
                71: "🌨️ Hafif kar", 73: "🌨️ Orta kar", 75: "❄️ Yoğun kar",
                80: "🌦️ Hafif sağanak", 81: "🌧️ Orta sağanak", 82: "⛈️ Şiddetli sağanak",
                95: "⛈️ Gök gürültülü fırtına",
            }
            
            code = current.get("weather_code", 0)
            return {
                "success": True,
                "city": city_name or f"{latitude},{longitude}",
                "current": {
                    "temperature": current.get("temperature_2m"),
                    "humidity": current.get("relative_humidity_2m"),
                    "wind_speed": current.get("wind_speed_10m"),
                    "condition": weather_codes.get(code, f"Kod: {code}"),
                },
                "forecast": [
                    {
                        "date": daily.get("time", [])[i] if i < len(daily.get("time", [])) else "",
                        "max": daily.get("temperature_2m_max", [])[i] if i < len(daily.get("temperature_2m_max", [])) else None,
                        "min": daily.get("temperature_2m_min", [])[i] if i < len(daily.get("temperature_2m_min", [])) else None,
                        "precipitation": daily.get("precipitation_sum", [])[i] if i < len(daily.get("precipitation_sum", [])) else None,
                    }
                    for i in range(min(3, len(daily.get("time", []))))
                ],
            }
    except Exception as e:
        logger.error(f"Open-Meteo API error: {e}")
        return {"success": False, "error": str(e)}


# Common city coordinates for quick lookup
CITY_COORDS = {
    "istanbul": (41.01, 28.98), "ankara": (39.93, 32.86), "izmir": (38.42, 27.13),
    "antalya": (36.90, 30.70), "bursa": (40.19, 29.06), "adana": (37.00, 35.33),
    "london": (51.51, -0.13), "paris": (48.86, 2.35), "new york": (40.71, -74.01),
    "tokyo": (35.68, 139.69), "berlin": (52.52, 13.41), "dubai": (25.20, 55.27),
    "moskova": (55.76, 37.62), "roma": (41.90, 12.50), "madrid": (40.42, -3.70),
}


async def get_weather_by_city(city: str) -> dict:
    """
    Şehir adıyla hava durumu getirir. Koordinat bilmek gerekmez.
    Parametreler: city (str) — Şehir adı.
    """
    city_lower = city.lower().strip()
    coords = CITY_COORDS.get(city_lower)
    
    if not coords:
        # Try geocoding via Open-Meteo
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                geo_resp = await client.get(
                    f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=tr"
                )
                if geo_resp.status_code == 200:
                    results = geo_resp.json().get("results", [])
                    if results:
                        coords = (results[0]["latitude"], results[0]["longitude"])
                        city = results[0].get("name", city)
        except Exception:
            pass
    
    if not coords:
        return {"success": False, "error": f"Şehir bulunamadı: {city}. Koordinat kullanmayı deneyin."}
    
    return await get_weather_openmeteo(coords[0], coords[1], city_name=city.capitalize())


async def get_crypto_price(coin_ids: str = "bitcoin", vs_currency: str = "usd") -> dict:
    """
    CoinGecko üzerinden kripto para fiyatlarını getirir.
    Parametreler: coin_ids (str, virgülle ayrılmış, ör: 'bitcoin,ethereum'), vs_currency (str, ör: 'usd,try').
    """
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_ids}&vs_currencies={vs_currency}&include_24hr_change=true&include_market_cap=true"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return {"success": False, "error": f"CoinGecko hatası: {resp.status_code}"}
            
            data = resp.json()
            results = {}
            for coin, values in data.items():
                results[coin] = {
                    "price": values.get(vs_currency.split(",")[0]),
                    "change_24h": values.get(f"{vs_currency.split(',')[0]}_24h_change"),
                    "market_cap": values.get(f"{vs_currency.split(',')[0]}_market_cap"),
                }
            
            return {"success": True, "prices": results, "currency": vs_currency}
    except Exception as e:
        logger.error(f"CoinGecko API error: {e}")
        return {"success": False, "error": str(e)}


async def get_exchange_rate(base: str = "USD") -> dict:
    """
    Güncel döviz kurlarını getirir.
    Parametreler: base (str, ör: 'USD', 'EUR', 'TRY').
    """
    try:
        url = f"https://open.er-api.com/v6/latest/{base.upper()}"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return {"success": False, "error": f"ExchangeRate hatası: {resp.status_code}"}
            
            data = resp.json()
            rates = data.get("rates", {})
            
            # Show most useful currencies
            important = ["USD", "EUR", "TRY", "GBP", "JPY", "CHF", "AUD", "CAD", "CNY", "RUB"]
            filtered = {k: v for k, v in rates.items() if k in important}
            
            return {
                "success": True,
                "base": base.upper(),
                "rates": filtered,
                "all_rates_count": len(rates),
                "last_update": data.get("time_last_update_utc", ""),
            }
    except Exception as e:
        logger.error(f"ExchangeRate API error: {e}")
        return {"success": False, "error": str(e)}
