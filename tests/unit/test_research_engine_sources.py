from __future__ import annotations

import pytest

from core.research.engine import ResearchEngine


@pytest.mark.asyncio
async def test_research_merges_local_and_web_sources_with_provenance(monkeypatch):
    engine = ResearchEngine()

    async def fake_web(query: str, depth: str):
        _ = (query, depth)
        return [
            {
                "url": "https://example.com/python",
                "title": "Python Web",
                "snippet": "Python is popular on the web.",
                "source_type": "web",
                "provider": "web",
            }
        ]

    async def fake_local(query: str, paths):
        _ = (query, paths)
        return [
            {
                "url": "file:///tmp/python-notes.txt",
                "title": "python-notes.txt",
                "snippet": "Python notes from local disk.",
                "source_type": "local_document",
                "provider": "document_rag",
                "source_path": "/tmp/python-notes.txt",
            }
        ]

    monkeypatch.setattr(engine, "_fetch_sources", fake_web)
    monkeypatch.setattr(engine, "_fetch_local_sources", fake_local)
    monkeypatch.setattr(engine, "_synthesize_answer", lambda query, sources: fake_answer(query, sources))

    result = await engine.research("Python nedir?", "standard", local_paths=["/tmp/python-notes.txt"])

    assert len(result.citations) == 2
    assert {item.source_type for item in result.citations} == {"web", "local_document"}
    assert any(item.source_path == "/tmp/python-notes.txt" for item in result.citations)


@pytest.mark.asyncio
async def test_research_local_only_skips_web_fetch(monkeypatch):
    engine = ResearchEngine()

    async def fake_local(query: str, paths):
        _ = (query, paths)
        return [
            {
                "url": "file:///tmp/notes.txt",
                "title": "notes.txt",
                "snippet": "Only local evidence.",
                "source_type": "local_document",
                "provider": "document_rag",
                "source_path": "/tmp/notes.txt",
            }
        ]

    async def fail_web(query: str, depth: str):
        raise AssertionError("web fetch should not run")

    monkeypatch.setattr(engine, "_fetch_sources", fail_web)
    monkeypatch.setattr(engine, "_fetch_local_sources", fake_local)
    monkeypatch.setattr(engine, "_synthesize_answer", lambda query, sources: fake_answer(query, sources))

    result = await engine.research(
        "Yerel belgeyi özetle",
        "basic",
        local_paths=["/tmp/notes.txt"],
        include_web=False,
    )

    assert len(result.citations) == 1
    assert result.citations[0].source_type == "local_document"


async def fake_answer(query: str, sources: list[dict]) -> str:
    _ = query
    return " | ".join(source["title"] for source in sources)
