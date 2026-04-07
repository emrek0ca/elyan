import pytest

from core.internet.reach import InternetReachRuntime


@pytest.mark.asyncio
async def test_search_dedupes_and_infers_platform(monkeypatch):
    runtime = InternetReachRuntime()

    async def _search(query, num_results=5, language="tr"):
        return {
            "success": True,
            "results": [
                {"title": "Repo", "url": "https://github.com/example/repo", "snippet": "github repo"},
                {"title": "Repo dup", "url": "https://github.com/example/repo", "snippet": "dup"},
                {"title": "Video", "url": "https://www.youtube.com/watch?v=1", "snippet": "video"},
            ],
        }

    monkeypatch.setattr("core.internet.reach.web_search", _search)
    hits = await runtime.search("agent tools", platforms=["github", "youtube"], limit=5)
    assert len(hits) == 2
    assert {hit.source_type for hit in hits} == {"github", "youtube"}


@pytest.mark.asyncio
async def test_read_rss_uses_feedparser(monkeypatch):
    runtime = InternetReachRuntime()

    class _Feed:
        title = "Demo Feed"

    class _Parsed:
        feed = _Feed()
        entries = [
            type("Entry", (), {"title": "One", "link": "https://example.com/1", "summary": "Summary one"})(),
            type("Entry", (), {"title": "Two", "link": "https://example.com/2", "summary": "Summary two"})(),
        ]

    monkeypatch.setattr("core.internet.reach.feedparser.parse", lambda url: _Parsed())
    doc = await runtime.read("https://example.com/feed.rss")
    assert doc.source_type == "rss"
    assert "One" in doc.content
    assert doc.provider == "feedparser"


@pytest.mark.asyncio
async def test_discover_reads_pages(monkeypatch):
    runtime = InternetReachRuntime()

    async def _search(query, *, platforms=None, limit=6, language="tr"):
        return [
            type("Hit", (), {"title": "Doc", "url": "https://example.com/doc", "snippet": "snippet", "source_type": "web"})(),
        ]

    async def _read(url, *, source_policy="balanced"):
        return type(
            "Doc",
            (),
            {
                "url": url,
                "title": "Fetched",
                "content": "Long content",
                "source_type": "web",
                "provider": "smart_fetch",
                "metadata": {},
            },
        )()

    monkeypatch.setattr(runtime, "search", _search)
    monkeypatch.setattr(runtime, "read", _read)
    docs = await runtime.discover("test")
    assert len(docs) == 1
    assert docs[0].title == "Fetched"


@pytest.mark.asyncio
async def test_read_failure_sets_taxonomy(monkeypatch):
    runtime = InternetReachRuntime()

    async def _fetch(*args, **kwargs):
        return {"success": False, "error": "network resolve failed"}

    monkeypatch.setattr("core.internet.reach.smart_fetch_page", _fetch)
    with pytest.raises(RuntimeError) as exc:
        await runtime.read("https://example.com/demo")
    assert "dns/network" in str(exc.value)
    assert runtime.get_health_status()["status"] == "degraded"
