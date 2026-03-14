"""Research orchestration primitives for planner/web/data/retrieval flows."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from utils.logger import get_logger

from .data_agent import TimeSeriesAgent

logger = get_logger("research.orchestrator")

SearchFn = Callable[[str, int, str], Awaitable[list[dict[str, Any]]]]
EvaluateFn = Callable[[str], Awaitable[dict[str, Any]]]
PolicyFilterFn = Callable[[list[dict[str, Any]], str, int], list[dict[str, Any]]]
QueryBuilderFn = Callable[[str], dict[str, Any]]


@dataclass
class ResearchPlan:
    topic: str
    depth: str
    source_policy: str
    language: str
    queries: list[str] = field(default_factory=list)
    years: int = 10
    use_structured_data: bool = False
    target_sources: int = 6


@dataclass
class ResearchCritique:
    has_issues: bool
    issues: list[str] = field(default_factory=list)


class ResearchPlanner:
    def __init__(self, query_builder: QueryBuilderFn | None = None) -> None:
        self.query_builder = query_builder

    @staticmethod
    def _extract_year_horizon(topic: str, default_years: int = 10) -> int:
        low = str(topic or "").lower()
        match = re.search(r"\b(?:son|last)?\s*(\d{1,2})\s*y[ıi]l", low)
        if match:
            return max(3, min(20, int(match.group(1))))
        return default_years

    @staticmethod
    def _is_structured_data_topic(topic: str) -> bool:
        low = str(topic or "").lower()
        markers = (
            "ekonomi",
            "economic",
            "economy",
            "gsyh",
            "gdp",
            "enflasyon",
            "inflation",
            "issizlik",
            "işsizlik",
            "büyüme",
            "buyume",
            "faiz",
            "rezerv",
            "dış ticaret",
            "dis ticaret",
        )
        return any(marker in low for marker in markers)

    def create_plan(
        self,
        *,
        topic: str,
        depth: str,
        source_policy: str,
        language: str,
        target_sources: int,
    ) -> ResearchPlan:
        decomposition = self.query_builder(topic) if self.query_builder else {"queries": [topic]}
        queries = [str(item).strip() for item in list(decomposition.get("queries") or []) if str(item).strip()]
        if not queries:
            queries = [str(topic or "").strip()]
        return ResearchPlan(
            topic=str(topic or "").strip(),
            depth=str(depth or "standard").strip().lower(),
            source_policy=str(source_policy or "trusted").strip().lower(),
            language=str(language or "tr").strip() or "tr",
            queries=queries,
            years=self._extract_year_horizon(topic),
            use_structured_data=self._is_structured_data_topic(topic),
            target_sources=max(2, int(target_sources or 6)),
        )


class WebResearchAgent:
    def __init__(
        self,
        *,
        search_fn: SearchFn,
        evaluate_fn: EvaluateFn,
        policy_filter_fn: PolicyFilterFn,
        evaluation_concurrency: int = 4,
    ) -> None:
        self.search_fn = search_fn
        self.evaluate_fn = evaluate_fn
        self.policy_filter_fn = policy_filter_fn
        self.evaluation_concurrency = max(1, int(evaluation_concurrency or 4))

    async def search(self, plan: ResearchPlan) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        query_cap = 6 if plan.use_structured_data else 4
        for query in plan.queries[:query_cap]:
            results = await self.search_fn(query, max(plan.target_sources * 2, 4), plan.language)
            for item in list(results or []):
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").split("#", 1)[0].rstrip("/")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                merged.append(dict(item))
        return self.policy_filter_fn(merged, plan.source_policy, max(plan.target_sources * 2, plan.target_sources + 2))

    async def evaluate(self, results: list[dict[str, Any]], *, cap: int) -> list[dict[str, Any]]:
        semaphore = asyncio.Semaphore(self.evaluation_concurrency)
        enriched: list[dict[str, Any]] = []

        async def _run(item: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                row = dict(item)
                url = str(row.get("url") or "").strip()
                if not url:
                    return row
                try:
                    evaluation = await self.evaluate_fn(url)
                except Exception as exc:
                    evaluation = {"success": False, "error": str(exc)}
                if isinstance(evaluation, dict):
                    row["reliability_score"] = float(evaluation.get("reliability_score", row.get("_rank_score", 0.0)) or 0.0)
                    row["content_preview"] = str(evaluation.get("content_preview") or "")
                    row["fetched"] = bool(evaluation.get("success"))
                    row["fetched_at"] = str(evaluation.get("fetched_at") or "")
                    row["fetch_mode"] = str(evaluation.get("fetch_mode") or "")
                    row["fetch_metadata"] = dict(evaluation.get("fetch_metadata") or {})
                    if evaluation.get("error"):
                        row["error"] = str(evaluation.get("error"))
                return row

        rows = await asyncio.gather(*[_run(item) for item in list(results or [])[: max(1, int(cap or len(results or [])))]], return_exceptions=True)
        for row in rows:
            if isinstance(row, Exception):
                continue
            enriched.append(dict(row))
        return enriched


class ResearchCritic:
    def evaluate(
        self,
        *,
        quality_summary: dict[str, Any],
        research_contract: dict[str, Any],
    ) -> ResearchCritique:
        issues: list[str] = []
        status = str(quality_summary.get("status") or "").strip().lower()
        if status == "fail":
            issues.append("quality_status_fail")
        if float(quality_summary.get("claim_coverage", 0.0) or 0.0) < 1.0:
            issues.append("claim_coverage_incomplete")
        if float(quality_summary.get("critical_claim_coverage", 0.0) or 0.0) < 1.0:
            issues.append("critical_claim_support_missing")
        if not isinstance(research_contract.get("uncertainty_log"), list):
            issues.append("uncertainty_log_missing")
        return ResearchCritique(has_issues=bool(issues), issues=issues)


class ResearchOrchestrator:
    def __init__(
        self,
        *,
        planner: ResearchPlanner,
        web_agent: WebResearchAgent,
        data_agent: TimeSeriesAgent | None = None,
    ) -> None:
        self.planner = planner
        self.web_agent = web_agent
        self.data_agent = data_agent or TimeSeriesAgent()

    @staticmethod
    def _dedupe_sources(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for item in list(items or []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            key = url.split("#", 1)[0].rstrip("/") if url else f"_synthetic_{len(merged)}"
            if key in seen_urls:
                continue
            seen_urls.add(key)
            merged.append(dict(item))
        return merged

    async def run(
        self,
        *,
        topic: str,
        depth: str,
        language: str,
        source_policy: str,
        target_sources: int,
        include_evaluation: bool,
        evaluation_cap: int,
    ) -> dict[str, Any]:
        plan = self.planner.create_plan(
            topic=topic,
            depth=depth,
            source_policy=source_policy,
            language=language,
            target_sources=target_sources,
        )
        web_results = await self.web_agent.search(plan)
        evaluated = list(web_results)
        if include_evaluation and web_results:
            evaluated = await self.web_agent.evaluate(web_results, cap=evaluation_cap)

        structured_data = {"sources": [], "findings": [], "series": [], "warnings": []}
        if plan.use_structured_data:
            try:
                structured_data = await self.data_agent.fetch_and_summarize(topic, years=plan.years)
            except Exception as exc:
                logger.debug("structured_data_fetch_failed:%s", exc)
                structured_data = {"sources": [], "findings": [], "series": [], "warnings": [str(exc)]}

        combined_sources = self._dedupe_sources(list(evaluated or []) + list(structured_data.get("sources") or []))
        return {
            "plan": {
                "topic": plan.topic,
                "depth": plan.depth,
                "source_policy": plan.source_policy,
                "language": plan.language,
                "queries": list(plan.queries),
                "years": plan.years,
                "use_structured_data": plan.use_structured_data,
                "target_sources": plan.target_sources,
            },
            "web_results": list(evaluated or []),
            "structured_data": structured_data,
            "sources": combined_sources[: max(1, int(target_sources or len(combined_sources or [])))],
        }


__all__ = [
    "ResearchCritique",
    "ResearchCritic",
    "ResearchOrchestrator",
    "ResearchPlan",
    "ResearchPlanner",
    "WebResearchAgent",
]
