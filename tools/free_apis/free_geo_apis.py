"""
tools/free_apis/free_geo_apis.py
─────────────────────────────────────────────────────────────────────────────
Free Geolocation & Network APIs — Zero cost, no API key required.
ipapi.co, REST Countries, Zippopotamus.
"""

import httpx
from utils.logger import get_logger

logger = get_logger("free_geo_apis")

TIMEOUT = 8


async def get_ip_geolocation(ip: str = "") -> dict:
    """
    IP adresinden coğrafi konum bilgisi getirir. Boş bırakılırsa kendi IP'nizi kullanır.
    Parametreler: ip (str, opsiyonel).
    """
    try:
        url = f"https://ipapi.co/{ip}/json/" if ip else "https://ipapi.co/json/"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, headers={"User-Agent": "Elyan/1.0"})
            if resp.status_code != 200:
                return {"success": False, "error": f"ipapi hatası: {resp.status_code}"}
            
            data = resp.json()
            if data.get("error"):
                return {"success": False, "error": data.get("reason", "Bilinmeyen hata")}
            
            return {
                "success": True,
                "ip": data.get("ip", ""),
                "city": data.get("city", ""),
                "region": data.get("region", ""),
                "country": data.get("country_name", ""),
                "country_code": data.get("country_code", ""),
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
                "timezone": data.get("timezone", ""),
                "isp": data.get("org", ""),
                "currency": data.get("currency", ""),
            }
    except Exception as e:
        logger.error(f"ipapi error: {e}")
        return {"success": False, "error": str(e)}


async def get_country_info(country_name: str) -> dict:
    """
    Bir ülke hakkında detaylı bilgi getirir (nüfus, başkent, bayrak, dil, para birimi).
    Parametreler: country_name (str).
    """
    try:
        url = f"https://restcountries.com/v3.1/name/{country_name}?fields=name,capital,population,flags,currencies,languages,region,subregion,timezones,borders,area"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return {"success": False, "error": f"Ülke bulunamadı: {country_name}"}
            
            data = resp.json()
            if not data:
                return {"success": False, "error": f"Ülke bulunamadı: {country_name}"}
            
            country = data[0]
            currencies = country.get("currencies", {})
            currency_list = [
                f"{v.get('name', k)} ({v.get('symbol', '')})"
                for k, v in currencies.items()
            ]
            languages = list(country.get("languages", {}).values())
            
            return {
                "success": True,
                "name": country.get("name", {}).get("common", ""),
                "official_name": country.get("name", {}).get("official", ""),
                "capital": country.get("capital", [])[0] if country.get("capital") else "",
                "population": country.get("population", 0),
                "area_km2": country.get("area", 0),
                "region": country.get("region", ""),
                "subregion": country.get("subregion", ""),
                "languages": languages,
                "currencies": currency_list,
                "flag_emoji": country.get("flags", {}).get("alt", ""),
                "flag_url": country.get("flags", {}).get("png", ""),
                "timezones": country.get("timezones", []),
                "borders": country.get("borders", []),
            }
    except Exception as e:
        logger.error(f"REST Countries API error: {e}")
        return {"success": False, "error": str(e)}


async def get_postal_code_info(country_code: str, postal_code: str) -> dict:
    """
    Posta kodundan şehir/bölge bilgisi çözümler.
    Parametreler: country_code (str, ör: 'us', 'tr', 'de'), postal_code (str).
    """
    try:
        url = f"https://api.zippopotam.us/{country_code.lower()}/{postal_code}"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return {"success": False, "error": f"Posta kodu bulunamadı: {country_code}/{postal_code}"}
            
            data = resp.json()
            places = data.get("places", [])
            
            return {
                "success": True,
                "postal_code": data.get("post code", postal_code),
                "country": data.get("country", ""),
                "country_code": data.get("country abbreviation", ""),
                "places": [
                    {
                        "name": p.get("place name", ""),
                        "state": p.get("state", ""),
                        "latitude": p.get("latitude", ""),
                        "longitude": p.get("longitude", ""),
                    }
                    for p in places
                ],
            }
    except Exception as e:
        logger.error(f"Zippopotamus API error: {e}")
        return {"success": False, "error": str(e)}
