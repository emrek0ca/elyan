"""Unit tests for advanced research speed/reliability helpers."""

import asyncio
import importlib
from pathlib import Path

ar = importlib.import_module("tools.research_tools.advanced_research")


def test_advanced_research_writes_quick_report(monkeypatch, tmp_path: Path):
    ar._research_tasks.clear()
    monkeypatch.setattr(ar, "RESEARCH_REPORT_DIR", tmp_path)
    monkeypatch.setattr(ar, "_last_research_result", None)
    monkeypatch.setattr(ar, "_last_research_topic", None)

    async def _fake_search(query: str, num_results: int, language: str):
        return [
            {"url": "https://example.com/a", "title": "A", "snippet": "A snippet"},
            {"url": "https://example.com/b", "title": "B", "snippet": "B snippet"},
            {"url": "https://example.com/c", "title": "C", "snippet": "C snippet"},
        ]

    async def _fake_findings(_sources, _topic, max_findings=10):
        _ = max_findings
        return ["• Köpekler düzenli veteriner kontrolü ile daha sağlıklı yaşar."]

    async def _fake_summary(_topic, _findings, _sources, **kwargs):
        _ = kwargs
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


def test_generate_summary_is_structured():
    sources = [
        ar.ResearchSource(
            url="https://akc.org/dog-care",
            title="Dog care guide",
            snippet="",
            reliability_score=0.82,
            fetched=True,
        ),
        ar.ResearchSource(
            url="https://example.com/blog",
            title="Blog",
            snippet="",
            reliability_score=0.62,
            fetched=True,
        ),
    ]
    findings = [
        "• Köpeklerde düzenli egzersiz davranışsal problemleri azaltır (Kaynak: akc.org).",
        "• Aşılama ve parazit kontrolü, bulaşıcı hastalık riskini düşürür (Kaynak: akc.org).",
    ]
    text = asyncio.run(ar._generate_summary("köpekler", findings, sources))
    assert "Kısa Özet:" in text
    assert "'köpekler' için 2 kaynak incelendi" in text
    assert "Karar için öne çıkan bulgular:" in text
    assert "Önerilen referans seti:" in text
    assert "Kanıt Matrisi" not in text
    assert "Operasyonel Öneriler" not in text
    assert "Önerilen Devam Adımı" not in text


def test_compact_finding_text_strips_date_and_percent_noise():
    text = ar._compact_finding_text("% 0 24 Oca 2026 by Örnek Yazar AB Yapay Zeka Yasası şirketler için yeni uyum yükümlülükleri getiriyor.")
    assert text.startswith("AB Yapay Zeka Yasası")
    assert "24 Oca 2026 by" not in text


def test_extract_findings_filters_noise():
    sources = [
        ar.ResearchSource(
            url="https://example.com/noisy",
            title="Noisy",
            snippet="Köpek bakımı kampanya ve indirim duyuruları burada.",
            reliability_score=0.4,
            content="Cookie kabul et paylaş yorum yap devamını oku kampanya indirim",
            fetched=True,
        ),
        ar.ResearchSource(
            url="https://akc.org/healthy-dogs",
            title="Healthy Dogs",
            snippet="Köpeklerde düzenli aşı takvimi ve parazit kontrolü önemlidir.",
            reliability_score=0.9,
            content=(
                "Köpeklerde düzenli aşı takvimi uygulanması bulaşıcı hastalık riskini azaltır. "
                "Veteriner kontrolü ile beslenme ve kilo takibi yapıldığında uzun dönem sağlık sonuçları iyileşir."
            ),
            fetched=True,
        ),
    ]
    findings = asyncio.run(ar._extract_findings(sources, "köpek sağlığı"))
    joined = "\n".join(findings).lower()
    assert "aşı" in joined or "asi" in joined
    assert "kampanya" not in joined


def test_extract_findings_prioritizes_reliable_domain():
    sources = [
        ar.ResearchSource(
            url="https://weak.example.com/post",
            title="Weak",
            snippet="Köpek bakımı için en popüler ürünleri hemen satın alabilirsiniz.",
            reliability_score=0.2,
            content="Köpek bakımı için en popüler ürünleri hemen satın alabilirsiniz.",
            fetched=True,
        ),
        ar.ResearchSource(
            url="https://akc.org/health",
            title="AKC",
            snippet="Köpeklerde düzenli veteriner kontrolü ve aşı takvimi hastalık riskini azaltır.",
            reliability_score=0.9,
            content=(
                "Köpeklerde düzenli veteriner kontrolü ve aşı takvimi bulaşıcı hastalık riskini azaltır. "
                "Erken tanı ve koruyucu bakım, uzun dönem sağlık sonuçlarını iyileştirir."
            ),
            fetched=True,
        ),
    ]
    findings = asyncio.run(ar._extract_findings(sources, "köpek sağlığı", max_findings=4))
    assert findings
    assert "akc.org" in findings[0].lower()
    assert "güven:" in findings[0].lower()


def test_quality_snapshot_counts():
    sources = [
        ar.ResearchSource(url="https://a.com", title="A", snippet="", reliability_score=0.81),
        ar.ResearchSource(url="https://b.com", title="B", snippet="", reliability_score=0.66),
        ar.ResearchSource(url="https://c.com", title="C", snippet="", reliability_score=0.2),
    ]
    q = ar._quality_snapshot(sources, ["x", "y"])
    assert q["total_sources"] == 3
    assert q["reliable_sources"] == 2
    assert q["high_reliability"] == 1


def test_apply_source_policy_prefers_academic_domains():
    raw = [
        {"url": "https://blog.example.com/a", "title": "Blog A", "snippet": "x", "_rank_score": 0.8},
        {"url": "https://mit.edu/paper", "title": "MIT", "snippet": "x", "_rank_score": 0.7},
        {"url": "https://arxiv.org/abs/1234", "title": "Arxiv", "snippet": "x", "_rank_score": 0.9},
    ]
    out = ar._apply_source_policy(raw, "academic", target_sources=2)
    urls = [x["url"] for x in out]
    assert any("mit.edu" in u for u in urls)
    assert any("arxiv.org" in u for u in urls)


def test_apply_source_policy_official_keeps_strict_matches_when_enough_exist():
    raw = [
        {"url": "https://www.tcmb.gov.tr/a", "title": "TCMB", "snippet": "x", "_rank_score": 0.9},
        {"url": "https://data.tuik.gov.tr/b", "title": "TUIK", "snippet": "x", "_rank_score": 0.88},
        {"url": "https://academia.edu/c", "title": "Academia", "snippet": "x", "_rank_score": 0.95},
    ]
    out = ar._apply_source_policy(raw, "official", target_sources=3)
    urls = [x["url"] for x in out]
    assert any("tcmb.gov.tr" in u for u in urls)
    assert any("tuik.gov.tr" in u for u in urls)
    assert all("academia.edu" not in u for u in urls)


def test_build_query_decomposition_for_economy_includes_official_queries():
    plan = ar._build_query_decomposition("Türkiye ekonomisinin son 10 yılı")
    joined = " | ".join(plan["queries"]).lower()
    assert "tuik" in joined
    assert "tcmb" in joined
    assert "world bank" in joined


def test_extract_findings_skips_boilerplate_study_aim_sentence():
    sources = [
        ar.ResearchSource(
            url="https://tcmb.gov.tr/report",
            title="TCMB Raporu",
            snippet="",
            reliability_score=0.9,
            content=(
                "Bu çalışmanın amacı Türkiye ekonomisinin genel bir özetini sunmaktır. "
                "Son on yılda enflasyon ve büyüme görünümü para politikası kararlarını doğrudan etkilemiştir. "
                "TCMB verileri fiyat istikrarı ve finansal istikrar dengesine işaret eder."
            ),
            fetched=True,
        ),
    ]
    findings = asyncio.run(ar._extract_findings(sources, "Türkiye ekonomisinin son 10 yılı", max_findings=3))
    joined = "\n".join(findings).lower()
    assert "bu çalışmanın amacı" not in joined
    assert "enflasyon" in joined or "büyüme" in joined


def test_extract_findings_for_time_horizon_skips_timeless_institution_description():
    sources = [
        ar.ResearchSource(
            url="https://www.tcmb.gov.tr/report",
            title="TCMB",
            snippet="",
            reliability_score=0.9,
            content=(
                "Türkiye Cumhuriyet Merkez Bankası, ülkemizde para ve kur politikalarının yönetilmesinden sorumlu kurumdur. "
                "2022 ve 2023 yıllarında enflasyon görünümü para politikası kararlarını belirgin biçimde etkilemiştir."
            ),
            fetched=True,
        ),
    ]
    findings = asyncio.run(ar._extract_findings(sources, "Türkiye ekonomisinin son 10 yılı", max_findings=3))
    joined = "\n".join(findings).lower()
    assert "sorumlu kurumdur" not in joined
    assert "2022" in joined or "2023" in joined


def test_apply_min_reliability_filters_weak_sources():
    sources = [
        ar.ResearchSource(url="https://a.com", title="A", snippet="", reliability_score=0.9),
        ar.ResearchSource(url="https://b.com", title="B", snippet="", reliability_score=0.82),
        ar.ResearchSource(url="https://c.com", title="C", snippet="", reliability_score=0.4),
    ]
    out = ar._apply_min_reliability(sources, min_reliability=0.8, keep_at_least=2)
    assert len(out) == 2
    assert all(s.reliability_score >= 0.8 for s in out)


def test_advanced_research_returns_policy_metadata(monkeypatch, tmp_path: Path):
    ar._research_tasks.clear()
    monkeypatch.setattr(ar, "RESEARCH_REPORT_DIR", tmp_path)
    monkeypatch.setattr(ar, "_last_research_result", None)
    monkeypatch.setattr(ar, "_last_research_topic", None)

    async def _fake_search(_query: str, _num_results: int, _language: str):
        return [
            {"url": "https://mit.edu/a", "title": "MIT A", "snippet": "A", "_rank_score": 0.91},
            {"url": "https://arxiv.org/abs/1", "title": "Arxiv", "snippet": "B", "_rank_score": 0.88},
            {"url": "https://stanford.edu/c", "title": "Stanford", "snippet": "C", "_rank_score": 0.87},
        ]

    async def _fake_eval(url: str, criteria=None):
        _ = criteria
        return {
            "success": True,
            "url": url,
            "domain": url.split("/")[2],
            "reliability_score": 0.85,
            "content_preview": "Köpek sağlığı için düzenli veteriner kontrolü önemlidir.",
        }

    async def _fake_findings(_sources, _topic, max_findings=10):
        _ = max_findings
        return ["• Köpeklerde koruyucu sağlık takibi uzun dönem riskleri azaltır."]

    async def _fake_summary(_topic, _findings, _sources, **kwargs):
        _ = kwargs
        return "Yapılandırılmış özet"

    monkeypatch.setattr(ar, "_perform_web_search", _fake_search)
    monkeypatch.setattr(ar, "evaluate_source", _fake_eval)
    monkeypatch.setattr(ar, "_extract_findings", _fake_findings)
    monkeypatch.setattr(ar, "_generate_summary", _fake_summary)

    out = asyncio.run(
        ar.advanced_research(
            topic="köpek sağlığı",
            depth="quick",
            include_evaluation=True,
            generate_report=False,
            source_policy="academic",
            min_reliability=0.8,
        )
    )
    assert out["success"] is True
    assert out["source_policy"] == "academic"
    assert out["min_reliability"] == 0.8
    assert "source_policy_stats" in out


def test_evaluate_source_returns_fetch_metadata(monkeypatch):
    async def _fake_fetch_page(url, extract_content=True, source_policy="balanced", prefer_browser=False):
        _ = (url, extract_content, source_policy, prefer_browser)
        return {
            "success": True,
            "title": "TCMB",
            "content": "TCMB raporu enflasyon ve büyüme görünümünü değerlendirir. 2024 yılında fiyat istikrarı vurgulanmıştır.",
            "render_mode": "browser",
            "text_density": 0.21,
            "length": 1400,
            "status_code": 200,
        }

    monkeypatch.setattr("tools.web_tools.fetch_page", _fake_fetch_page)

    result = asyncio.run(ar.evaluate_source("https://www.tcmb.gov.tr/report"))
    assert result["success"] is True
    assert result["fetch_mode"] == "browser"
    assert result["fetch_metadata"]["text_density"] == 0.21


def test_advanced_research_includes_structured_data_payload(monkeypatch, tmp_path: Path):
    ar._research_tasks.clear()
    monkeypatch.setattr(ar, "RESEARCH_REPORT_DIR", tmp_path)
    monkeypatch.setattr(ar, "_last_research_result", None)
    monkeypatch.setattr(ar, "_last_research_topic", None)

    async def _fake_search(query: str, num_results: int, language: str):
        _ = (query, num_results, language)
        return [{"url": "https://www.tcmb.gov.tr/report", "title": "TCMB", "snippet": "Makro görünüm", "_rank_score": 0.88}]

    async def _fake_eval(url: str, criteria=None):
        _ = criteria
        return {
            "success": True,
            "url": url,
            "domain": "tcmb.gov.tr",
            "reliability_score": 0.9,
            "content_preview": "TCMB raporu son yıllardaki enflasyon görünümünü özetler.",
            "fetch_mode": "browser",
            "fetch_metadata": {"render_mode": "browser"},
        }

    async def _fake_summary(_topic, _findings, _sources, **kwargs):
        _ = kwargs
        return "Ekonomi özeti"

    async def _fake_fetch_and_summarize(self, topic, years=None, indicators=None):
        _ = (self, topic, years, indicators)
        return {
            "sources": [
                {
                    "url": "https://api.worldbank.org/v2/country/TUR/indicator/FP.CPI.TOTL.ZG",
                    "title": "Enflasyon - WORLDBANK",
                    "snippet": "Enflasyon serisi 2021-2024 döneminde aşağı yönlü seyretti.",
                    "reliability_score": 0.96,
                    "source_type": "structured_data",
                }
            ],
            "findings": ["Enflasyon serisi 2021-2024 döneminde aşağı yönlü seyretti."],
            "series": [{"indicator": "inflation"}],
            "warnings": [],
        }

    monkeypatch.setattr(ar, "_perform_web_search", _fake_search)
    monkeypatch.setattr(ar, "evaluate_source", _fake_eval)
    monkeypatch.setattr(ar, "_generate_summary", _fake_summary)
    monkeypatch.setattr("tools.research_tools.data_agent.TimeSeriesAgent.fetch_and_summarize", _fake_fetch_and_summarize)

    out = asyncio.run(
        ar.advanced_research(
            topic="Türkiye ekonomisinin son 10 yılı",
            depth="quick",
            include_evaluation=True,
            generate_report=False,
            source_policy="official",
        )
    )
    assert out["success"] is True
    assert "structured_data" in out
    assert out["structured_data"]["series"]
    assert any(src.get("source_type") == "structured_data" for src in out["sources"])
