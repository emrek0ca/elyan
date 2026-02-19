"""Unit tests for advanced research speed/reliability helpers."""

import asyncio
import importlib
from pathlib import Path

ar = importlib.import_module("tools.research_tools.advanced_research")


def test_advanced_research_writes_quick_report(monkeypatch, tmp_path: Path):
    ar._research_tasks.clear()
    monkeypatch.setattr(ar, "RESEARCH_REPORT_DIR", tmp_path)

    async def _fake_search(query: str, num_results: int, language: str):
        return [
            {"url": "https://example.com/a", "title": "A", "snippet": "A snippet"},
            {"url": "https://example.com/b", "title": "B", "snippet": "B snippet"},
            {"url": "https://example.com/c", "title": "C", "snippet": "C snippet"},
        ]

    async def _fake_findings(_sources, _topic):
        return ["• Köpekler düzenli veteriner kontrolü ile daha sağlıklı yaşar."]

    async def _fake_summary(_topic, _findings, _sources):
        return "Kısa özet"

    monkeypatch.setattr(ar, "_perform_web_search", _fake_search)
    monkeypatch.setattr(ar, "_extract_findings", _fake_findings)
    monkeypatch.setattr(ar, "_generate_summary", _fake_summary)

    out = asyncio.run(
        ar.advanced_research(
            topic="köpekler",
            depth="quick",
            include_evaluation=False,
            generate_report=False,
        )
    )
    assert out["success"] is True
    assert out["report_paths"]
    report_path = Path(out["report_paths"][0])
    assert report_path.exists()
    assert report_path.suffix == ".md"


def test_get_research_result_rejects_non_completed():
    ar._research_tasks.clear()
    rid = "research_test_pending"
    ar._research_tasks[rid] = ar.ResearchResult(
        id=rid,
        topic="test",
        depth=ar.ResearchDepth.STANDARD,
        status="running",
        progress=55,
    )
    out = ar.get_research_result(rid)
    assert out["success"] is False
    assert "henüz tamamlanmadı" in out["error"]
