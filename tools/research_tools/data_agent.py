"""Structured research data and time-series helpers."""

from __future__ import annotations

import os
import re
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from utils.logger import get_logger

logger = get_logger("research.data_agent")


@dataclass
class TimeSeriesIndicator:
    key: str
    label: str
    provider: str
    code: str
    unit: str = ""


DEFAULT_ECONOMY_INDICATORS: tuple[TimeSeriesIndicator, ...] = (
    TimeSeriesIndicator("gdp_growth", "GSYH büyümesi", "worldbank", "NY.GDP.MKTP.KD.ZG", "%"),
    TimeSeriesIndicator("inflation", "Enflasyon", "worldbank", "FP.CPI.TOTL.ZG", "%"),
    TimeSeriesIndicator("unemployment", "İşsizlik", "worldbank", "SL.UEM.TOTL.ZS", "%"),
    TimeSeriesIndicator("exports", "İhracat", "worldbank", "NE.EXP.GNFS.ZS", "GSYH %"),
)
TCMB_EVDS_SERIES: dict[str, TimeSeriesIndicator] = {
    "policy_rate": TimeSeriesIndicator("policy_rate", "Politika faizi", "tcmb", "TP.FGJ0", "%"),
    "cpi": TimeSeriesIndicator("cpi", "TÜFE", "tcmb", "TP.FE.OKTG01", "endeks"),
}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _extract_year_horizon(topic: str, default_years: int = 10) -> int:
    low = _normalize_text(topic).lower()
    match = re.search(r"\b(?:son|last)?\s*(\d{1,2})\s*y[ıi]l", low)
    if match:
        return max(3, min(20, int(match.group(1))))
    return default_years


def _looks_like_turkey(topic: str) -> bool:
    low = _normalize_text(topic).lower()
    return any(token in low for token in ("türkiye", "turkiye", "turkey"))


def _trend_label(first: float, last: float) -> str:
    delta = last - first
    if abs(delta) < max(abs(first), 1.0) * 0.03:
        return "genel olarak yatay"
    if delta > 0:
        return "genel olarak yukarı yönlü"
    return "genel olarak aşağı yönlü"


def _round_value(value: float) -> str:
    rounded = round(float(value), 2)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.2f}"


def summarize_time_series(label: str, points: list[dict[str, Any]], unit: str = "") -> str:
    valid = [row for row in list(points or []) if row.get("value") is not None]
    if len(valid) < 2:
        return ""
    ordered = sorted(valid, key=lambda row: int(row.get("year") or 0))
    first = float(ordered[0]["value"])
    last = float(ordered[-1]["value"])
    values = [float(row["value"]) for row in ordered]
    avg = sum(values) / len(values)
    peak = max(ordered, key=lambda row: float(row["value"]))
    trough = min(ordered, key=lambda row: float(row["value"]))
    unit_suffix = f" {unit}".rstrip() if unit else ""
    trend = _trend_label(first, last)
    return (
        f"{label} serisi {ordered[0]['year']}-{ordered[-1]['year']} döneminde {trend} seyretti; "
        f"ilk değer {_round_value(first)}{unit_suffix}, son değer {_round_value(last)}{unit_suffix}, "
        f"ortalama {_round_value(avg)}{unit_suffix}. "
        f"En yüksek seviye {peak['year']} yılında {_round_value(float(peak['value']))}{unit_suffix}, "
        f"en düşük seviye {trough['year']} yılında {_round_value(float(trough['value']))}{unit_suffix} olarak görüldü."
    )


class TimeSeriesAgent:
    """Fetch structured macro data and turn it into deterministic findings."""

    WORLD_BANK_BASE = "https://api.worldbank.org/v2"
    TCMB_BASE = "https://evds2.tcmb.gov.tr/service/evds"

    def __init__(self, *, timeout_s: int = 20) -> None:
        self.timeout_s = max(5, int(timeout_s or 20))

    async def _fetch_world_bank_series(
        self,
        *,
        country_code: str,
        indicator: TimeSeriesIndicator,
        years: int,
    ) -> dict[str, Any]:
        end_year = datetime.now().year
        start_year = end_year - max(3, int(years or 10)) - 1
        url = (
            f"{self.WORLD_BANK_BASE}/country/{country_code}/indicator/{indicator.code}"
            f"?format=json&per_page=80&date={start_year}:{end_year}"
        )
        async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=True) as client:
            response = await client.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
            payload = response.json()

        rows = payload[1] if isinstance(payload, list) and len(payload) > 1 and isinstance(payload[1], list) else []
        points = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = row.get("value")
            if value is None:
                continue
            year = row.get("date")
            try:
                points.append({"year": int(year), "value": float(value)})
            except Exception:
                continue
        return {"provider": "worldbank", "url": url, "points": sorted(points, key=lambda item: item["year"])}

    async def _fetch_tcmb_series(
        self,
        *,
        indicator: TimeSeriesIndicator,
        years: int,
    ) -> dict[str, Any]:
        api_key = str(
            os.getenv("TCMB_EVDS_API_KEY")
            or os.getenv("EVDS_API_KEY")
            or ""
        ).strip()
        if not api_key:
            return {"provider": "tcmb", "url": "", "points": [], "warning": "tcmb_api_key_missing"}
        end_year = datetime.now().year
        start_year = end_year - max(3, int(years or 10))
        url = (
            f"{self.TCMB_BASE}/series={indicator.code}&startDate=01-01-{start_year}"
            f"&endDate=31-12-{end_year}&type=json&key={api_key}"
        )
        async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()

        items = payload.get("items") if isinstance(payload, dict) else []
        points = []
        for row in list(items or []):
            if not isinstance(row, dict):
                continue
            date_value = str(row.get("Tarih") or row.get("DATE") or "").strip()
            raw_value = row.get(indicator.code) or row.get(indicator.code.upper()) or row.get(indicator.key)
            if raw_value in (None, ""):
                continue
            year_match = re.search(r"(20\d{2}|19\d{2})", date_value)
            if not year_match:
                continue
            try:
                numeric = float(str(raw_value).replace(",", "."))
            except Exception:
                continue
            points.append({"year": int(year_match.group(1)), "value": numeric})
        dedup = {}
        for point in points:
            dedup[int(point["year"])] = point
        return {"provider": "tcmb", "url": url, "points": sorted(dedup.values(), key=lambda item: item["year"])}

    async def fetch_and_summarize(
        self,
        topic: str,
        *,
        years: int | None = None,
        indicators: list[TimeSeriesIndicator] | None = None,
    ) -> dict[str, Any]:
        if not _looks_like_turkey(topic):
            return {"sources": [], "findings": [], "series": [], "warnings": []}

        years = _extract_year_horizon(topic, default_years=int(years or 10))
        selected = list(indicators or DEFAULT_ECONOMY_INDICATORS)
        findings: list[str] = []
        sources: list[dict[str, Any]] = []
        series_rows: list[dict[str, Any]] = []
        warnings: list[str] = []

        tasks = [self._fetch_world_bank_series(country_code="TUR", indicator=indicator, years=years) for indicator in selected]
        tcmb_indicators: list[TimeSeriesIndicator] = []
        if any(token in _normalize_text(topic).lower() for token in ("faiz", "merkez bankası", "merkez bankasi", "tcmb")):
            tcmb_indicators = [TCMB_EVDS_SERIES["policy_rate"]]
            tasks.extend(self._fetch_tcmb_series(indicator=indicator, years=years) for indicator in tcmb_indicators)

        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_indicators = selected + tcmb_indicators
        for indicator, result in zip(all_indicators, results):
            if isinstance(result, Exception):
                warnings.append(f"{indicator.key}:{result}")
                continue
            points = list(result.get("points") or [])
            if len(points) < 2:
                warning = str(result.get("warning") or "").strip()
                if warning:
                    warnings.append(f"{indicator.key}:{warning}")
                continue

            summary = summarize_time_series(indicator.label, points, unit=indicator.unit)
            if summary:
                findings.append(summary)

            source_url = str(result.get("url") or "").strip()
            provider = str(result.get("provider") or indicator.provider).strip()
            sources.append(
                {
                    "url": source_url or f"{provider}://{indicator.code}",
                    "title": f"{indicator.label} - {provider.upper()}",
                    "snippet": summary,
                    "reliability_score": 0.96 if provider in {"worldbank", "tcmb"} else 0.9,
                    "source_type": "structured_data",
                    "provider": provider,
                    "indicator": indicator.key,
                    "accessed_at": datetime.now().isoformat(),
                }
            )
            series_rows.append(
                {
                    "provider": provider,
                    "indicator": indicator.key,
                    "label": indicator.label,
                    "unit": indicator.unit,
                    "points": points,
                    "summary": summary,
                    "url": source_url,
                }
            )

        return {"sources": sources, "findings": findings, "series": series_rows, "warnings": warnings}


__all__ = [
    "DEFAULT_ECONOMY_INDICATORS",
    "TimeSeriesAgent",
    "TimeSeriesIndicator",
    "summarize_time_series",
]
