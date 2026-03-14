import asyncio
import importlib
from pathlib import Path

import pytest

from tools.document_tools.output_renderer import DocumentRenderer, sections_to_sectioned_document
from tools.research_tools.data_agent import TimeSeriesAgent, summarize_time_series
from tools.research_tools.research_orchestrator import (
    ResearchOrchestrator,
    ResearchPlanner,
    WebResearchAgent,
)
from tools.research_tools.semantic_retrieval import SemanticRetriever

sf = importlib.import_module("tools.web_tools.smart_fetch")


def test_summarize_time_series_reports_trend():
    summary = summarize_time_series(
        "Enflasyon",
        [
            {"year": 2021, "value": 12.0},
            {"year": 2022, "value": 32.0},
            {"year": 2023, "value": 48.0},
            {"year": 2024, "value": 41.0},
        ],
        unit="%",
    )
    assert "2021-2024" in summary
    assert "Enflasyon serisi" in summary
    assert "En yüksek seviye" in summary


@pytest.mark.asyncio
async def test_smart_fetch_page_falls_back_to_browser(monkeypatch):
    async def _fake_static(url, timeout_s=8):
        _ = (url, timeout_s)
        return {
            "success": True,
            "status_code": 200,
            "url": "https://data.tuik.gov.tr/test",
            "html": "<html><body>Enable JavaScript to run this app</body></html>",
            "headers": {"Content-Type": "text/html"},
            "render_mode": "static",
        }

    async def _fake_browser(url, timeout_s=20):
        _ = (url, timeout_s)
        return {
            "success": True,
            "status_code": 200,
            "url": "https://data.tuik.gov.tr/test",
            "html": "<html><body><main>Rendered economic content with inflation series.</main></body></html>",
            "headers": {},
            "render_mode": "browser",
        }

    monkeypatch.setattr(sf, "_static_fetch_html", _fake_static)
    monkeypatch.setattr(sf, "_browser_fetch_html", _fake_browser)

    result = await sf.smart_fetch_page("https://data.tuik.gov.tr/test", extract_content=True, source_policy="official")
    assert result["success"] is True
    assert result["render_mode"] == "browser"
    assert "Rendered economic content" in result["content"]


@pytest.mark.asyncio
async def test_time_series_agent_fetch_and_summarize_returns_structured_findings(monkeypatch):
    agent = TimeSeriesAgent()

    async def _fake_world_bank_series(*, country_code, indicator, years):
        _ = (country_code, years)
        return {
            "provider": "worldbank",
            "url": f"https://api.worldbank.org/{indicator.code}",
            "points": [
                {"year": 2021, "value": 5.0},
                {"year": 2022, "value": 4.0},
                {"year": 2023, "value": 3.0},
                {"year": 2024, "value": 2.0},
            ],
        }

    monkeypatch.setattr(agent, "_fetch_world_bank_series", _fake_world_bank_series)

    result = await agent.fetch_and_summarize("Türkiye ekonomisinin son 10 yılı")
    assert result["sources"]
    assert result["findings"]
    assert result["series"]
    assert any("worldbank" in src["provider"] for src in result["sources"])


def test_semantic_retriever_lexical_fallback_prioritizes_relevant_passage():
    retriever = SemanticRetriever()
    retriever._model_error = "dependency-missing"

    ranked = retriever.rank_passages(
        "enflasyon baz etkisi",
        [
            "Baz etkisi enflasyon görünümünü kısa vadede etkileyebilir.",
            "Köpeklerde aşılama takvimi bulaşıcı hastalık riskini düşürür.",
            "Kur oynaklığı dış ticaret dengesini etkileyebilir.",
        ],
        top_k=2,
    )
    assert ranked
    assert ranked[0].stage == "lexical"
    assert "enflasyon" in ranked[0].text.lower()


@pytest.mark.asyncio
async def test_research_orchestrator_combines_web_and_structured_sources():
    async def _fake_search(query, num_results, language):
        _ = (query, num_results, language)
        return [{"url": "https://www.tcmb.gov.tr/report", "title": "TCMB", "snippet": "Makro görünüm", "_rank_score": 0.9}]

    async def _fake_evaluate(url):
        return {
            "success": True,
            "url": url,
            "reliability_score": 0.91,
            "content_preview": "TCMB raporu fiyat istikrarı ve büyüme görünümünü değerlendirir.",
            "fetch_mode": "browser",
            "fetch_metadata": {"render_mode": "browser"},
        }

    def _fake_policy(results, policy, target_sources):
        _ = (policy, target_sources)
        return list(results)

    class _FakeDataAgent:
        async def fetch_and_summarize(self, topic, years=None):
            _ = (topic, years)
            return {
                "sources": [
                    {
                        "url": "https://api.worldbank.org/v2/country/TUR/indicator/FP.CPI.TOTL.ZG",
                        "title": "Enflasyon - WORLDBANK",
                        "snippet": "Enflasyon serisi genel olarak aşağı yönlü seyretti.",
                        "reliability_score": 0.96,
                        "provider": "worldbank",
                        "source_type": "structured_data",
                    }
                ],
                "findings": ["Enflasyon serisi genel olarak aşağı yönlü seyretti."],
                "series": [],
                "warnings": [],
            }

    planner = ResearchPlanner(query_builder=lambda topic: {"queries": [topic, f"{topic} tcmb"]})
    web_agent = WebResearchAgent(search_fn=_fake_search, evaluate_fn=_fake_evaluate, policy_filter_fn=_fake_policy)
    orchestrator = ResearchOrchestrator(planner=planner, web_agent=web_agent, data_agent=_FakeDataAgent())

    result = await orchestrator.run(
        topic="Türkiye ekonomisinin son 10 yılı",
        depth="comprehensive",
        language="tr",
        source_policy="official",
        target_sources=4,
        include_evaluation=True,
        evaluation_cap=4,
    )
    urls = [row["url"] for row in result["sources"]]
    assert any("tcmb.gov.tr" in url for url in urls)
    assert any("worldbank.org" in url for url in urls)
    assert result["structured_data"]["findings"]


@pytest.mark.asyncio
async def test_document_renderer_reuses_word_tool(monkeypatch, tmp_path: Path):
    document = sections_to_sectioned_document(
        title="Araştırma Raporu - Test",
        sections=[
            {
                "title": "Kısa Özet",
                "paragraphs": [{"text": "Kısa karar özeti.", "claim_ids": ["claim_1"]}],
            },
            {
                "title": "Temel Bulgular",
                "paragraphs": [{"text": "Birinci bulgu.", "claim_ids": ["claim_1"]}],
            },
        ],
        metadata={"topic": "test"},
    )

    captured = {}

    async def _fake_write_word(path=None, title=None, paragraphs=None, **kwargs):
        _ = kwargs
        captured["path"] = path
        captured["title"] = title
        captured["paragraphs"] = list(paragraphs or [])
        Path(path).write_bytes(b"docx")
        return {"success": True, "path": path}

    monkeypatch.setattr("tools.office_tools.word_tools.write_word", _fake_write_word)

    renderer = DocumentRenderer()
    result = await renderer.render_to_path(document, "docx", str(tmp_path / "report.docx"))
    assert result["success"] is True
    assert captured["title"] == "Araştırma Raporu - Test"
    assert "Kısa Özet" in captured["paragraphs"]
    assert "Birinci bulgu." in captured["paragraphs"]
