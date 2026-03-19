from pathlib import Path
import importlib
import json
from unittest.mock import AsyncMock

import pytest

from tools.pro_workflows import (
    create_web_project_scaffold,
    create_coding_delivery_plan,
    create_coding_verification_report,
    create_software_project_pack,
    generate_document_pack,
    research_document_delivery,
)
from tools.research_tools.advanced_research import _build_query_decomposition


@pytest.mark.asyncio
async def test_create_web_project_scaffold_generates_counter_template(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    result = await create_web_project_scaffold(
        project_name="Counter Demo",
        stack="vanilla",
        output_dir=str(tmp_path),
        brief="ortasında sayaç butonu olacak. html css js kullan",
    )
    assert result.get("success") is True

    project_dir = Path(str(result.get("project_dir", "")))
    assert project_dir.exists()

    html = (project_dir / "index.html").read_text(encoding="utf-8")
    css = (project_dir / "styles" / "main.css").read_text(encoding="utf-8")
    js = (project_dir / "scripts" / "main.js").read_text(encoding="utf-8")

    assert "counterValue" in html
    assert "counter-actions" in css
    assert "increaseBtn" in js
    assert "decreaseBtn" in js


@pytest.mark.asyncio
async def test_create_web_project_scaffold_applies_brief_features(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    result = await create_web_project_scaffold(
        project_name="Ops Dashboard",
        stack="vanilla",
        output_dir=str(tmp_path),
        brief="dashboard görünümü, todo listesi, arama ve dark mode toggle olsun",
    )
    assert result.get("success") is True

    project_dir = Path(str(result.get("project_dir", "")))
    html = (project_dir / "index.html").read_text(encoding="utf-8")
    js = (project_dir / "scripts" / "main.js").read_text(encoding="utf-8")
    readme = (project_dir / "README.md").read_text(encoding="utf-8")

    assert "todoInput" in html
    assert "searchInput" in html
    assert "themeToggle" in html
    assert "layout: dashboard" in readme.lower()
    assert "todo" in readme.lower()
    assert "search" in readme.lower()
    assert "theme_toggle" in readme.lower()
    assert "Elyan dynamic scaffold ready" in js


@pytest.mark.asyncio
async def test_create_web_project_scaffold_includes_modern_ui_stack(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    result = await create_web_project_scaffold(
        project_name="Portfolio Modern",
        stack="vanilla",
        output_dir=str(tmp_path),
        brief="github portfolyo sitesi, modern animasyon, galeri bölümü ve etkileyici tasarım",
    )
    assert result.get("success") is True

    project_dir = Path(str(result.get("project_dir", "")))
    html = (project_dir / "index.html").read_text(encoding="utf-8")
    js = (project_dir / "scripts" / "main.js").read_text(encoding="utf-8")
    readme = (project_dir / "README.md").read_text(encoding="utf-8")

    assert "cdn.tailwindcss.com" in html
    assert "gsap.min.js" in html
    assert "gallery-grid" in html
    assert "window.gsap" in js
    assert "tailwind" in readme.lower()
    assert "motion" in readme.lower()


@pytest.mark.asyncio
async def test_create_web_project_scaffold_builds_warm_portfolio_layout(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    result = await create_web_project_scaffold(
        project_name="Sunset Portfolio",
        stack="vanilla",
        output_dir=str(tmp_path),
        brief="sari ve turuncu renklerde bir portfolyo sitesi yap",
    )
    assert result.get("success") is True

    project_dir = Path(str(result.get("project_dir", "")))
    html = (project_dir / "index.html").read_text(encoding="utf-8")
    css = (project_dir / "styles" / "main.css").read_text(encoding="utf-8")
    js = (project_dir / "scripts" / "main.js").read_text(encoding="utf-8")

    assert "portfolio-hero" in html
    assert "project-showcase" in html
    assert "#f59e0b" in css
    assert "#f97316" in css
    assert "Space Grotesk" in css
    assert "data-scroll" in html
    assert "scrollIntoView" in js


@pytest.mark.asyncio
async def test_create_web_project_scaffold_blocks_dirty_existing_directory(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    project_dir = tmp_path / "Dirty_Web"
    project_dir.mkdir(parents=True)
    (project_dir / "styles.css").write_text("legacy", encoding="utf-8")

    result = await create_web_project_scaffold(
        project_name="Dirty Web",
        stack="vanilla",
        output_dir=str(tmp_path),
        brief="landing page oluştur",
    )
    assert result.get("success") is False
    assert result.get("error_code") == "PROJECT_DIR_NOT_EMPTY"
    assert "not empty" in str(result.get("error", "")).lower()


@pytest.mark.asyncio
async def test_create_software_project_pack_node_generates_js_entry(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    result = await create_software_project_pack(
        project_name="Node Ops",
        project_type="app",
        stack="node",
        complexity="advanced",
        output_dir=str(tmp_path),
        brief="todo endpointleri olan bir servis",
    )
    assert result.get("success") is True
    pack_dir = Path(str(result.get("pack_dir", "")))
    assert (pack_dir / "src" / "main.js").exists()
    assert (pack_dir / "package.json").exists()
    main_js = (pack_dir / "src" / "main.js").read_text(encoding="utf-8")
    assert "/todos" in main_js


@pytest.mark.asyncio
async def test_create_coding_delivery_plan_generates_professional_docs(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)
    project_dir = tmp_path / "expert-app"
    project_dir.mkdir(parents=True)

    result = await create_coding_delivery_plan(
        project_path=str(project_dir),
        project_name="Expert App",
        project_kind="app",
        stack="python",
        complexity="expert",
        brief="Çok karmaşık ve production seviyesinde teslimat.",
    )
    assert result.get("success") is True
    files = result.get("files_created", [])
    assert len(files) >= 5

    delivery_plan = project_dir / "docs" / "DELIVERY_PLAN.md"
    acceptance = project_dir / "docs" / "ACCEPTANCE_CRITERIA.md"
    runbook = project_dir / "docs" / "RUNBOOK.md"
    assert delivery_plan.exists()
    assert acceptance.exists()
    assert runbook.exists()

    plan_text = delivery_plan.read_text(encoding="utf-8")
    acceptance_text = acceptance.read_text(encoding="utf-8")
    assert "Complexity: expert" in plan_text
    assert "Phase Plan" in plan_text
    assert "Security scan/dependency audit result is recorded." in acceptance_text


@pytest.mark.asyncio
async def test_create_coding_verification_report_scores_project(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)
    project_dir = tmp_path / "counter-app"
    (project_dir / "docs").mkdir(parents=True)
    (project_dir / "styles").mkdir(parents=True)
    (project_dir / "scripts").mkdir(parents=True)

    (project_dir / "README.md").write_text("# Counter App", encoding="utf-8")
    (project_dir / "index.html").write_text(
        """<!doctype html>
<html lang="tr">
  <head>
    <meta charset="utf-8">
    <link rel="stylesheet" href="./styles/main.css">
  </head>
  <body>
    <main>Counter</main>
    <script src="./scripts/main.js"></script>
  </body>
</html>
""",
        encoding="utf-8",
    )
    (project_dir / "styles" / "main.css").write_text("body{}", encoding="utf-8")
    (project_dir / "scripts" / "main.js").write_text("console.log(1)", encoding="utf-8")
    (project_dir / "docs" / "DELIVERY_PLAN.md").write_text("ok", encoding="utf-8")
    (project_dir / "docs" / "TASK_BACKLOG.md").write_text("ok", encoding="utf-8")
    (project_dir / "docs" / "ACCEPTANCE_CRITERIA.md").write_text("ok", encoding="utf-8")
    (project_dir / "docs" / "TEST_STRATEGY.md").write_text("ok", encoding="utf-8")
    (project_dir / "docs" / "RUNBOOK.md").write_text("ok", encoding="utf-8")
    (project_dir / "tests").mkdir()

    result = await create_coding_verification_report(
        project_path=str(project_dir),
        project_name="Counter App",
        project_kind="website",
        stack="vanilla",
        strict=True,
    )
    assert result.get("success") is True
    assert result.get("status") == "ready"
    assert int(result.get("score", 0)) >= 90
    report_path = Path(str(result.get("report_path", "")))
    assert report_path.exists()
    report_text = report_path.read_text(encoding="utf-8")
    assert "Verification Report - Counter App" in report_text


@pytest.mark.asyncio
async def test_create_coding_verification_report_blocks_mixed_web_skeleton(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)
    project_dir = tmp_path / "mixed-web"
    (project_dir / "docs").mkdir(parents=True)
    (project_dir / "styles").mkdir(parents=True)
    (project_dir / "scripts").mkdir(parents=True)
    (project_dir / "tests").mkdir()

    (project_dir / "README.md").write_text("# Mixed Web", encoding="utf-8")
    (project_dir / "index.html").write_text(
        '<!doctype html><html><head><link rel="stylesheet" href="./styles/main.css"></head><body><script src="./scripts/main.js"></script></body></html>',
        encoding="utf-8",
    )
    (project_dir / "styles.css").write_text("body{}", encoding="utf-8")
    (project_dir / "styles" / "main.css").write_text("body{}", encoding="utf-8")
    (project_dir / "scripts" / "main.js").write_text("console.log(1)", encoding="utf-8")
    (project_dir / "docs" / "DELIVERY_PLAN.md").write_text("ok", encoding="utf-8")
    (project_dir / "docs" / "TASK_BACKLOG.md").write_text("ok", encoding="utf-8")
    (project_dir / "docs" / "ACCEPTANCE_CRITERIA.md").write_text("ok", encoding="utf-8")
    (project_dir / "docs" / "TEST_STRATEGY.md").write_text("ok", encoding="utf-8")
    (project_dir / "docs" / "RUNBOOK.md").write_text("ok", encoding="utf-8")

    result = await create_coding_verification_report(
        project_path=str(project_dir),
        project_name="Mixed Web",
        project_kind="website",
        stack="vanilla",
        strict=True,
    )

    assert result.get("success") is True
    assert result.get("status") == "blocked"
    failed_ids = {check["id"] for check in result.get("failed_checks", [])}
    assert "web_layout" in failed_ids
    assert "web_smoke" not in failed_ids


@pytest.mark.asyncio
async def test_research_document_delivery_returns_only_requested_outputs(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    base_report = tmp_path / "base_report.pdf"
    base_report.write_bytes(b"pdf")

    async def _fake_research(**kwargs):
        return {
            "success": True,
            "topic": kwargs.get("topic", "test"),
            "summary": "Kısa özet",
            "findings": ["B1", "B2"],
            "sources": [{"title": "Kaynak 1", "url": "https://example.com", "reliability_score": 0.9}],
            "source_count": 1,
            "report_paths": [str(base_report)],
        }

    async def _fake_write_word(path=None, **kwargs):
        p = Path(str(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"docx")
        return {"success": True, "path": str(p)}

    async def _fake_write_excel(path=None, **kwargs):
        p = Path(str(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"xlsx")
        return {"success": True, "path": str(p)}

    research_mod = importlib.import_module("tools.research_tools.advanced_research")
    word_mod = importlib.import_module("tools.office_tools.word_tools")
    excel_mod = importlib.import_module("tools.office_tools.excel_tools")
    monkeypatch.setattr(research_mod, "advanced_research", _fake_research)
    monkeypatch.setattr(word_mod, "write_word", _fake_write_word)
    monkeypatch.setattr(excel_mod, "write_excel", _fake_write_excel)

    result = await research_document_delivery(
        topic="Köpekler",
        depth="expert",
        output_dir=str(tmp_path),
        include_word=True,
        include_excel=True,
        include_report=True,
    )
    assert result.get("success") is True
    outputs = result.get("outputs", [])
    assert any(str(x).endswith(".docx") for x in outputs)
    assert any(str(x).endswith(".xlsx") for x in outputs)
    assert not any(str(x).endswith(".md") for x in outputs)
    assert not any(str(x).endswith(".txt") for x in outputs)
    assert not any(str(x).endswith(".pdf") for x in outputs)
    assert isinstance(result.get("quality_summary"), dict)
    assert "avg_reliability" in result.get("quality_summary", {})
    assert result.get("claim_coverage") >= 0.0
    assert result.get("critical_claim_coverage") >= 0.0
    assert str(result.get("path", "")).endswith(".docx")
    assert isinstance(result.get("supporting_artifacts"), list)
    assert any(str(item).endswith("claim_map.json") for item in result.get("supporting_artifacts", []))
    assert str(result.get("claim_map_path", "")).endswith("claim_map.json")
    assert result.get("document_profile") == "executive"
    assert result.get("citation_mode") == "none"


@pytest.mark.asyncio
async def test_research_document_delivery_word_only_stays_single_artifact(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    captured = {}

    async def _fake_research(**kwargs):
        return {
            "success": True,
            "topic": kwargs.get("topic", "test"),
            "summary": "Kısa özet\n\nOperasyonel Öneriler:\n- Gürültü olmamalı.",
            "findings": [
                "• Fourier serileri periyodik fonksiyonları sinüs ve kosinüs bileşenleriyle ifade eder. (Kaynak: example.com, Güven: %90)",
                "• Isı denklemi çözümünde klasik kullanım alanlarından biridir. (Kaynak: math.example, Güven: %88)",
            ],
            "sources": [{"title": "Kaynak 1", "url": "https://example.com", "reliability_score": 0.9}],
            "source_count": 1,
            "report_paths": [str(tmp_path / "base_report.md")],
        }

    async def _fake_write_word(path=None, **kwargs):
        captured["content"] = kwargs.get("content")
        p = Path(str(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"docx")
        return {"success": True, "path": str(p)}

    research_mod = importlib.import_module("tools.research_tools.advanced_research")
    word_mod = importlib.import_module("tools.office_tools.word_tools")
    excel_mod = importlib.import_module("tools.office_tools.excel_tools")
    monkeypatch.setattr(research_mod, "advanced_research", _fake_research)
    monkeypatch.setattr(word_mod, "write_word", _fake_write_word)
    monkeypatch.setattr(excel_mod, "write_excel", AsyncMock())

    result = await research_document_delivery(
        topic="Fourier Denklem",
        brief="tek bir düzenli word belgesi hazırla",
        depth="comprehensive",
        output_dir=str(tmp_path),
        include_word=True,
        include_excel=False,
        include_report=True,
    )

    assert result.get("success") is True
    outputs = result.get("outputs", [])
    assert len(outputs) == 1
    assert str(outputs[0]).endswith(".docx")
    assert "Araştırma belgesi hazır:" in str(result.get("message", ""))
    assert "Kısa Özet" not in str(captured.get("content", ""))
    assert "Temel Bulgular" not in str(captured.get("content", ""))
    assert "Kaynak Güven Özeti" not in str(captured.get("content", ""))
    assert "Açık Riskler" not in str(captured.get("content", ""))
    assert "Belirsizlikler" not in str(captured.get("content", ""))
    assert "Operasyonel Öneriler" not in str(captured.get("content", ""))
    assert "BUders" not in str(captured.get("content", ""))
    assert "Denklem 1" not in str(captured.get("content", ""))
    assert "[Kaynak:" not in str(captured.get("content", ""))
    assert "Fourier serileri periyodik fonksiyonları" in str(captured.get("content", ""))


@pytest.mark.asyncio
async def test_research_document_delivery_defaults_to_structured_report_and_hidden_supporting_artifacts(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    captured = {}

    async def _fake_research(**kwargs):
        return {
            "success": True,
            "topic": kwargs.get("topic", "PyTorch"),
            "summary": "PyTorch, derin öğrenme ve otomatik türev alma için geniş kullanılan bir çerçevedir.",
            "findings": [
                "• PyTorch dinamik hesaplama grafiği yaklaşımıyla esnek model geliştirmeyi destekler. (Kaynak: pytorch.org, Güven: %94)",
                "• TorchVision ve TorchText gibi ek paketler görüntü ve metin iş akışlarını hızlandırır. (Kaynak: pytorch.org, Güven: %90)",
                "• PyPI dağıtımı ve resmi dokümantasyon ekosistemi, kurulum ve örnekleri düzenli tutar. (Kaynak: pypi.org, Güven: %88)",
            ],
            "sources": [
                {"title": "PyTorch Docs", "url": "https://pytorch.org/docs/stable/", "reliability_score": 0.96},
                {"title": "PyPI", "url": "https://pypi.org/project/torch/", "reliability_score": 0.89},
            ],
            "source_count": 2,
            "report_paths": [],
        }

    async def _fake_write_word(path=None, **kwargs):
        captured["paragraphs"] = list(kwargs.get("paragraphs") or [])
        captured["content"] = str(kwargs.get("content") or "")
        p = Path(str(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"docx")
        return {"success": True, "path": str(p)}

    research_mod = importlib.import_module("tools.research_tools.advanced_research")
    word_mod = importlib.import_module("tools.office_tools.word_tools")
    monkeypatch.setattr(research_mod, "advanced_research", _fake_research)
    monkeypatch.setattr(word_mod, "write_word", _fake_write_word)

    result = await research_document_delivery(
        topic="PyTorch",
        brief="PyTorch hakkında araştırma yapar mısın",
        depth="comprehensive",
        output_dir=str(tmp_path),
        include_word=True,
        include_excel=False,
        include_report=True,
    )

    assert result.get("success") is True
    assert str(result.get("message", "")).count("\n") == 0
    assert "İstersen bunu genişletip revize edebilirim." in str(result.get("message", ""))
    assert "Kısa Özet" in captured.get("paragraphs", [])
    assert "Temel Bulgular" in captured.get("paragraphs", [])
    assert "Kaynak Güven Özeti" in captured.get("paragraphs", [])
    assert "Açık Riskler" in captured.get("paragraphs", [])
    assert "Belirsizlikler" in captured.get("paragraphs", [])
    assert len(captured.get("content", "")) >= 200
    claim_map_path = Path(str(result.get("claim_map_path", "")))
    manifest_path = Path(str(result.get("office_content_manifest_path", "")))
    assert claim_map_path.parent.name == ".elyan"
    assert manifest_path.parent.name == ".elyan"
    assert all(Path(str(item)).parent.name == ".elyan" for item in result.get("supporting_artifacts", []))


@pytest.mark.asyncio
async def test_research_document_delivery_pdf_only_returns_single_pdf(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    async def _fake_research(**kwargs):
        return {
            "success": True,
            "topic": kwargs.get("topic", "test"),
            "summary": "Fourier dönüşümü sinyalleri frekans bileşenlerine ayırır.",
            "findings": [
                "• Fourier dönüşümü zaman alanındaki bir sinyali frekans alanında ifade etmeyi sağlar. (Kaynak: example.com, Güven: %90)",
            ],
            "sources": [{"title": "Kaynak 1", "url": "https://example.com", "reliability_score": 0.9}],
            "source_count": 1,
            "report_paths": [],
        }

    def _fake_write_pdf(path, title, content):
        p = Path(str(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF-1.4")
        return {"success": True, "path": str(p), "title": title, "content": content}

    research_mod = importlib.import_module("tools.research_tools.advanced_research")
    monkeypatch.setattr(research_mod, "advanced_research", _fake_research)
    monkeypatch.setattr("tools.pro_workflows._write_simple_pdf", _fake_write_pdf)

    result = await research_document_delivery(
        topic="Fourier Dönüşümü",
        brief="tek pdf hazırla",
        depth="comprehensive",
        output_dir=str(tmp_path),
        include_word=False,
        include_excel=False,
        include_pdf=True,
        include_report=True,
    )

    assert result.get("success") is True
    outputs = result.get("outputs", [])
    assert len(outputs) == 1
    assert str(outputs[0]).endswith(".pdf")


@pytest.mark.asyncio
async def test_research_document_delivery_can_emit_presentation_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    async def _fake_research(**kwargs):
        return {
            "success": True,
            "topic": kwargs.get("topic", "test"),
            "summary": "Kısa özet.",
            "findings": [
                "• Temel bulgu, kaynaklı biçimde aktarılır. (Kaynak: example.com, Güven: %90)",
                "• İkinci bulgu, sunum anlatımına uygundur. (Kaynak: example.org, Güven: %88)",
            ],
            "sources": [
                {"title": "Kaynak 1", "url": "https://example.com", "reliability_score": 0.9},
                {"title": "Kaynak 2", "url": "https://example.org", "reliability_score": 0.88},
            ],
            "source_count": 2,
            "quality_summary": {
                "claim_coverage": 1.0,
                "critical_claim_coverage": 1.0,
                "uncertainty_count": 0,
                "status": "pass",
            },
            "report_paths": [],
        }

    async def _fake_pptx(self, document, path):
        p = Path(str(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"pptx")
        return {"success": True, "path": str(p), "format": "pptx", "slides": len(getattr(document, "sections", []) or [])}

    research_mod = importlib.import_module("tools.research_tools.advanced_research")
    pptx_renderer_mod = importlib.import_module("tools.document_tools.output_renderer")
    monkeypatch.setattr(research_mod, "advanced_research", _fake_research)
    monkeypatch.setattr(pptx_renderer_mod.PptxRenderer, "render_to_path", _fake_pptx)

    result = await research_document_delivery(
        topic="Sunum Konusu",
        brief="bu araştırmayı bir sunum halinde hazırla",
        depth="comprehensive",
        output_dir=str(tmp_path),
        include_word=False,
        include_excel=False,
        include_pdf=False,
        include_latex=False,
        include_presentation=True,
        include_report=True,
    )

    assert result.get("success") is True
    outputs = result.get("outputs", [])
    assert len(outputs) == 1
    assert str(outputs[0]).endswith(".pptx")
    assert result.get("include_presentation") is True
    manifest_path = Path(str(result.get("office_content_manifest_path", "")))
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest.get("content_kind") == "research_delivery"
    assert manifest.get("summary", {}).get("outputs")


@pytest.mark.asyncio
async def test_generate_document_pack_defaults_to_single_docx(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)
    captured = {}

    async def _fake_write_word(path=None, **kwargs):
        p = Path(str(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"docx")
        captured["content"] = kwargs.get("content", "")
        return {"success": True, "path": str(p), "content": kwargs.get("content")}

    monkeypatch.setattr("tools.office_tools.word_tools.write_word", _fake_write_word)

    result = await generate_document_pack(
        topic="Onboarding Süreci",
        brief="Yeni çalışanların ilk hafta izleyeceği adımları açıkla.",
        output_dir=str(tmp_path),
    )

    assert result.get("success") is True
    outputs = result.get("outputs", [])
    assert len(outputs) == 1
    assert str(outputs[0]).endswith(".docx")
    assert str(result.get("path", "")).endswith(".docx")
    assert len(str(captured.get("content", ""))) >= 200


@pytest.mark.asyncio
async def test_generate_document_pack_ignores_command_only_brief(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)
    captured = {}

    async def _fake_write_word(path=None, **kwargs):
        p = Path(str(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"docx")
        captured["content"] = kwargs.get("content", "")
        return {"success": True, "path": str(p), "content": kwargs.get("content")}

    monkeypatch.setattr("tools.office_tools.word_tools.write_word", _fake_write_word)

    result = await generate_document_pack(
        topic="Fourier Denklem",
        brief="fourier denklem için sadece word belgesi hazırla",
        output_dir=str(tmp_path),
        preferred_formats=["docx"],
    )

    assert result.get("success") is True
    content = str(captured.get("content", ""))
    assert "sadece word belgesi hazırla" not in content.lower()
    assert len(content) >= 200


@pytest.mark.asyncio
async def test_generate_document_pack_supports_latex(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    result = await generate_document_pack(
        topic="Fourier Denklem",
        brief="latex formatında sade belge hazırla",
        output_dir=str(tmp_path),
        preferred_formats=["tex"],
    )

    assert result.get("success") is True
    outputs = result.get("outputs", [])
    assert len(outputs) == 1
    assert str(outputs[0]).endswith(".tex")
    tex = Path(outputs[0]).read_text(encoding="utf-8")
    assert "\\documentclass" in tex
    assert "Fourier Denklem" in tex


@pytest.mark.asyncio
async def test_research_document_delivery_fails_when_requested_artifact_cannot_be_created(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    async def _fake_research(**kwargs):
        return {
            "success": True,
            "topic": kwargs.get("topic", "test"),
            "summary": "Fourier dönüşümü, bir sinyalin frekans bileşenlerini anlamaya yarar.",
            "findings": [
                "• Fourier dönüşümü, işaretleri frekans uzayında incelemeyi sağlar. (Kaynak: example.com, Güven: %90)",
                "• Mühendislikte filtreleme ve analiz için yaygın biçimde kullanılır. (Kaynak: example.com, Güven: %88)",
            ],
            "sources": [{"title": "Kaynak 1", "url": "https://example.com", "reliability_score": 0.9}],
            "source_count": 1,
            "report_paths": [str(tmp_path / "base_report.md")],
        }

    async def _fake_write_word(path=None, **kwargs):
        return {"success": False, "error": "python-docx kurulu değil."}

    research_mod = importlib.import_module("tools.research_tools.advanced_research")
    word_mod = importlib.import_module("tools.office_tools.word_tools")
    monkeypatch.setattr(research_mod, "advanced_research", _fake_research)
    monkeypatch.setattr(word_mod, "write_word", _fake_write_word)

    result = await research_document_delivery(
        topic="Fourier Denklem",
        brief="tek bir düzenli word belgesi hazırla",
        output_dir=str(tmp_path),
        include_word=True,
        include_excel=False,
        include_pdf=False,
    )

    assert result.get("success") is False
    assert result.get("error") == "Belge oluşturulamadı."
    assert "python-docx kurulu değil." in " ".join(result.get("warnings", []))


@pytest.mark.asyncio
async def test_research_document_delivery_prefers_llm_synthesis_when_available(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)
    captured = {}

    async def _fake_research(**kwargs):
        return {
            "success": True,
            "topic": kwargs.get("topic", "test"),
            "summary": "Ham özet",
            "findings": [
                "• Fourier serileri periyodik fonksiyonların sinüs ve kosinüs bileşenleriyle temsilini sağlar. (Kaynak: example.com, Güven: %90)",
                "• Isı denklemi çözümü Fourier yaklaşımının tarihsel kullanım alanlarından biridir. (Kaynak: math.example, Güven: %88)",
                "• Sinyal işleme uygulamalarında frekans bileşenleri ayrıştırılabilir. (Kaynak: signals.example.edu, Güven: %87)",
            ],
            "sources": [
                {"title": "Kaynak 1", "url": "https://example.com", "reliability_score": 0.9},
                {"title": "Kaynak 2", "url": "https://math.example.edu", "reliability_score": 0.91},
                {"title": "Kaynak 3", "url": "https://signals.example.edu", "reliability_score": 0.87},
            ],
            "source_count": 3,
            "quality_summary": {
                "claim_coverage": 1.0,
                "critical_claim_coverage": 1.0,
                "uncertainty_count": 0,
                "status": "pass",
            },
            "source_policy_stats": {"fallback_used": False},
            "report_paths": [],
        }

    async def _fake_llm_body(**kwargs):
        return (
            "Fourier denklemi ve Fourier serileri, bir fonksiyonun trigonometrik bileşenler üzerinden ifade edilmesini sağlar.\n\n"
            "Bu yaklaşım özellikle periyodik davranışların analizinde ve ısı denklemi gibi problemlerde önem taşır.\n\n"
            "Metnin geri kalanı burada sade araştırma anlatımı olarak devam eder ve konu odağını korur."
        )

    async def _fake_write_word(path=None, **kwargs):
        captured["content"] = kwargs.get("content", "")
        captured["paragraphs"] = list(kwargs.get("paragraphs") or [])
        p = Path(str(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"docx")
        return {"success": True, "path": str(p)}

    research_mod = importlib.import_module("tools.research_tools.advanced_research")
    word_mod = importlib.import_module("tools.office_tools.word_tools")
    monkeypatch.setattr(research_mod, "advanced_research", _fake_research)
    monkeypatch.setattr(word_mod, "write_word", _fake_write_word)
    monkeypatch.setattr("tools.pro_workflows._synthesize_research_body_with_llm", _fake_llm_body)

    result = await research_document_delivery(
        topic="Fourier Denklem",
        brief="tek bir düzenli word belgesi hazırla",
        output_dir=str(tmp_path),
        include_word=True,
        include_excel=False,
        include_pdf=False,
    )

    assert result.get("success") is True
    assert "trigonometrik bileşenler" in str(captured.get("content", ""))


@pytest.mark.asyncio
async def test_research_document_delivery_ignores_llm_synthesis_when_official_research_is_partial(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)
    captured = {}

    async def _fake_research(**kwargs):
        return {
            "success": True,
            "topic": kwargs.get("topic", "test"),
            "summary": "Kısa Özet:\n' Türkiye ekonomisinin son 10 yılı' için 3 kaynak incelendi.",
            "findings": [
                "• TÜİK verilerine göre enflasyon ve büyüme göstergeleri son on yılda belirgin dalgalanma göstermiştir. (Kaynak: tuik.gov.tr, Güven: %90)",
                "• TCMB raporları fiyat istikrarı ve para politikası aktarım mekanizmasına dikkat çeker. (Kaynak: tcmb.gov.tr, Güven: %88)",
                "• Bazı yıllarda dış finansman koşulları büyüme görünümünü sınırlamıştır. (Kaynak: worldbank.org, Güven: %86)",
            ],
            "sources": [
                {"title": "TÜİK", "url": "https://data.tuik.gov.tr/a", "reliability_score": 0.9},
                {"title": "TCMB", "url": "https://www.tcmb.gov.tr/b", "reliability_score": 0.88},
                {"title": "World Bank", "url": "https://worldbank.org/c", "reliability_score": 0.86},
            ],
            "source_count": 3,
            "quality_summary": {
                "claim_coverage": 1.0,
                "critical_claim_coverage": 1.0,
                "uncertainty_count": 1,
                "status": "partial",
            },
            "source_policy_stats": {"fallback_used": True},
            "report_paths": [],
        }

    async def _fake_llm_body(**kwargs):
        return "Türkiye ekonomisi tarih boyunca birçok alanda dönüşmüştür ve sanayi, tarım, teknoloji gibi alanlarda genel bir hikaye sunar."

    async def _fake_write_word(path=None, **kwargs):
        captured["content"] = kwargs.get("content", "")
        captured["paragraphs"] = list(kwargs.get("paragraphs") or [])
        p = Path(str(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"docx")
        return {"success": True, "path": str(p)}

    research_mod = importlib.import_module("tools.research_tools.advanced_research")
    word_mod = importlib.import_module("tools.office_tools.word_tools")
    monkeypatch.setattr(research_mod, "advanced_research", _fake_research)
    monkeypatch.setattr(word_mod, "write_word", _fake_write_word)
    monkeypatch.setattr("tools.pro_workflows._synthesize_research_body_with_llm", _fake_llm_body)

    result = await research_document_delivery(
        topic="Türkiye ekonomisinin son 10 yılı",
        brief="resmi kaynaklarla word rapor hazırla",
        output_dir=str(tmp_path),
        include_word=True,
        include_excel=False,
        include_pdf=False,
        source_policy="official",
    )

    assert result.get("success") is True
    content = str(captured.get("content", ""))
    assert "tarih boyunca birçok alanda dönüşmüştür" not in content
    assert "TÜİK" in content or "TCMB" in content


@pytest.mark.asyncio
async def test_research_document_delivery_generates_claim_map_and_profile_variants(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)
    captured = {}

    async def _fake_research(**kwargs):
        return {
            "success": True,
            "topic": kwargs.get("topic", "test"),
            "summary": "Yönetici özeti benzeri bir ham metin.",
            "findings": [
                "• Birinci bulgu sayısal sonuç içerir ve doğrulanmalıdır. (Kaynak: example.com, Güven: %90)",
                "• İkinci bulgu yöntemin uygulama alanlarını özetler. (Kaynak: math.example.edu, Güven: %88)",
            ],
            "sources": [
                {"title": "Kaynak 1", "url": "https://example.com/report", "reliability_score": 0.9},
                {"title": "Kaynak 2", "url": "https://math.example.edu/paper", "reliability_score": 0.91},
            ],
            "source_count": 2,
            "research_contract": {
                "claim_list": [
                    {
                        "claim_id": "claim_1",
                        "text": "Birinci bulgu sayısal sonuç içerir.",
                        "source_urls": ["https://example.com/report", "https://math.example.edu/paper"],
                        "critical": True,
                        "source_count": 2,
                        "confidence": 0.9,
                    },
                    {
                        "claim_id": "claim_2",
                        "text": "İkinci bulgu uygulama alanlarını özetler.",
                        "source_urls": ["https://math.example.edu/paper"],
                        "critical": False,
                        "source_count": 1,
                        "confidence": 0.82,
                    },
                ],
                "citation_map": {
                    "claim_1": [
                        {"url": "https://example.com/report", "title": "Kaynak 1", "reliability_score": 0.9},
                        {"url": "https://math.example.edu/paper", "title": "Kaynak 2", "reliability_score": 0.91},
                    ],
                    "claim_2": [
                        {"url": "https://math.example.edu/paper", "title": "Kaynak 2", "reliability_score": 0.91},
                    ],
                },
                "critical_claim_ids": ["claim_1"],
                "conflicts": [{"type": "numeric_variation", "claim_ids": ["claim_1"], "detail": "Sayisal ifade manuel teyit gerektirir."}],
                "uncertainty_log": ["claim_1: manuel teyit gerekli."],
            },
            "quality_summary": {
                "avg_reliability": 0.905,
                "claim_coverage": 1.0,
                "critical_claim_coverage": 1.0,
                "uncertainty_count": 2,
                "status": "partial",
            },
            "report_paths": [],
        }

    async def _fake_write_word(path=None, **kwargs):
        captured["content"] = kwargs.get("content", "")
        captured["paragraphs"] = list(kwargs.get("paragraphs") or [])
        p = Path(str(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"docx")
        return {"success": True, "path": str(p)}

    research_mod = importlib.import_module("tools.research_tools.advanced_research")
    word_mod = importlib.import_module("tools.office_tools.word_tools")
    monkeypatch.setattr(research_mod, "advanced_research", _fake_research)
    monkeypatch.setattr(word_mod, "write_word", _fake_write_word)

    result = await research_document_delivery(
        topic="Fourier Denklem",
        brief="analitik briefing notu hazırla",
        output_dir=str(tmp_path),
        include_word=True,
        include_excel=False,
        include_pdf=False,
        document_profile="analytical",
        citation_mode="inline",
    )

    assert result.get("success") is True
    assert result.get("document_profile") == "analytical"
    assert result.get("claim_coverage") == 1.0
    assert result.get("critical_claim_coverage") == 1.0
    claim_map_path = Path(str(result.get("claim_map_path", "")))
    assert claim_map_path.exists()
    claim_map = claim_map_path.read_text(encoding="utf-8")
    assert "\"claim_coverage\": 1.0" in claim_map
    assert len(captured.get("paragraphs", [])) >= 3


@pytest.mark.asyncio
async def test_research_document_delivery_emits_revision_summary_when_previous_claim_map_exists(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    previous_claim_map = {
        "document_profile": "executive",
        "citation_mode": "inline",
        "used_claim_ids": ["claim_1"],
        "quality_summary": {
            "claim_coverage": 1.0,
            "critical_claim_coverage": 0.5,
            "uncertainty_count": 2,
            "conflict_count": 1,
        },
        "sections": [{"title": "Kısa Özet", "paragraphs": [{"text": "Eski özet", "claim_ids": ["claim_1"]}]}],
    }
    previous_path = tmp_path / "claim_map.json"
    previous_path.write_text(json.dumps(previous_claim_map, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _fake_research(**kwargs):
        return {
            "success": True,
            "topic": kwargs.get("topic", "test"),
            "summary": "Yeni özet metni.",
            "findings": ["• Güncel bulgu. (Kaynak: example.com, Güven: %91)"],
            "sources": [{"title": "Kaynak 1", "url": "https://example.com/report", "reliability_score": 0.91}],
            "source_count": 1,
            "research_contract": {
                "claim_list": [
                    {
                        "claim_id": "claim_1",
                        "text": "Güncel bulgu.",
                        "source_urls": ["https://example.com/report", "https://example.com/backup"],
                        "critical": True,
                        "source_count": 2,
                    }
                ],
                "citation_map": {
                    "claim_1": [
                        {"url": "https://example.com/report", "title": "Kaynak 1", "reliability_score": 0.91},
                        {"url": "https://example.com/backup", "title": "Kaynak 2", "reliability_score": 0.87},
                    ]
                },
                "critical_claim_ids": ["claim_1"],
                "conflicts": [],
                "uncertainty_log": [],
            },
            "quality_summary": {
                "claim_coverage": 1.0,
                "critical_claim_coverage": 1.0,
                "uncertainty_count": 0,
                "conflict_count": 0,
                "status": "pass",
            },
            "report_paths": [],
        }

    async def _fake_write_word(path=None, **kwargs):
        p = Path(str(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"docx")
        return {"success": True, "path": str(p)}

    research_mod = importlib.import_module("tools.research_tools.advanced_research")
    word_mod = importlib.import_module("tools.office_tools.word_tools")
    monkeypatch.setattr(research_mod, "advanced_research", _fake_research)
    monkeypatch.setattr(word_mod, "write_word", _fake_write_word)

    result = await research_document_delivery(
        topic="Fourier Denklem",
        brief="bunu daha kısa yap",
        output_dir=str(tmp_path),
        include_word=True,
        include_excel=False,
        include_pdf=False,
        previous_claim_map_path=str(previous_path),
        revision_request="bunu daha kısa yap",
    )

    assert result.get("success") is True
    revision_summary_path = Path(str(result.get("revision_summary_path", "")))
    assert revision_summary_path.exists()
    revision_summary = revision_summary_path.read_text(encoding="utf-8")
    assert "Revision request: bunu daha kısa yap" in revision_summary
    assert "Critical claim coverage: 0.50 -> 1.00" in revision_summary


@pytest.mark.asyncio
async def test_research_document_delivery_preserves_untargeted_sections_from_previous_claim_map(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    previous_claim_map = {
        "document_profile": "executive",
        "citation_mode": "inline",
        "used_claim_ids": ["claim_1", "claim_2"],
        "quality_summary": {"claim_coverage": 1.0, "critical_claim_coverage": 1.0, "uncertainty_count": 0},
        "sections": [
            {"title": "Kısa Özet", "paragraphs": [{"text": "Eski özet", "claim_ids": ["claim_1"]}]},
            {"title": "Temel Bulgular", "paragraphs": [{"text": "Eski bulgu", "claim_ids": ["claim_2"]}]},
        ],
    }
    previous_path = tmp_path / "claim_map.json"
    previous_path.write_text(json.dumps(previous_claim_map, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _fake_research(**kwargs):
        return {
            "success": True,
            "topic": kwargs.get("topic", "test"),
            "summary": "Yeni özet.",
            "findings": ["• Yeni bulgu. (Kaynak: example.com, Güven: %91)"],
            "sources": [{"title": "Kaynak 1", "url": "https://example.com/report", "reliability_score": 0.91}],
            "source_count": 1,
            "research_contract": {
                "claim_list": [
                    {"claim_id": "claim_1", "text": "Yeni özet claim", "source_urls": ["https://example.com/report"], "critical": False},
                    {"claim_id": "claim_2", "text": "Yeni bulgu claim", "source_urls": ["https://example.com/report"], "critical": False},
                ],
                "citation_map": {"claim_1": [{"url": "https://example.com/report", "title": "Kaynak 1"}], "claim_2": [{"url": "https://example.com/report", "title": "Kaynak 1"}]},
                "critical_claim_ids": [],
                "conflicts": [],
                "uncertainty_log": [],
            },
            "quality_summary": {"claim_coverage": 1.0, "critical_claim_coverage": 1.0, "uncertainty_count": 0, "status": "pass"},
            "report_paths": [],
        }

    async def _fake_write_word(path=None, **kwargs):
        p = Path(str(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"docx")
        return {"success": True, "path": str(p)}

    research_mod = importlib.import_module("tools.research_tools.advanced_research")
    word_mod = importlib.import_module("tools.office_tools.word_tools")
    monkeypatch.setattr(research_mod, "advanced_research", _fake_research)
    monkeypatch.setattr(word_mod, "write_word", _fake_write_word)

    result = await research_document_delivery(
        topic="Fourier Denklem",
        brief="yalnızca özeti güncelle",
        output_dir=str(tmp_path),
        include_word=True,
        include_excel=False,
        previous_claim_map_path=str(previous_path),
        revision_request="yalnızca özeti güncelle",
        target_sections=["Kısa Özet"],
    )

    claim_map = json.loads(Path(str(result.get("claim_map_path", ""))).read_text(encoding="utf-8"))
    section_map = {str(item.get("title") or ""): item for item in claim_map.get("sections", [])}
    assert section_map["Kısa Özet"]["paragraphs"][0]["text"] != "Eski özet"
    assert section_map["Temel Bulgular"]["paragraphs"][0]["text"] == "Eski bulgu"


def test_advanced_research_math_query_decomposition_enriches_queries():
    plan = _build_query_decomposition("fourier denklem")
    queries = [str(item).lower() for item in plan.get("queries", [])]
    assert any("formula" in item for item in queries)
    assert any("pdf lecture notes" in item for item in queries)


@pytest.mark.asyncio
async def test_generate_document_pack_respects_pdf_preference(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    def _fake_write_pdf(path, title, content):
        p = Path(str(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF-1.4")
        return {"success": True, "path": str(p), "title": title, "content": content}

    monkeypatch.setattr("tools.pro_workflows._write_simple_pdf", _fake_write_pdf)

    result = await generate_document_pack(
        topic="Onboarding Süreci",
        brief="Bunu sade bir pdf olarak hazırla.",
        output_dir=str(tmp_path),
        preferred_formats=["pdf"],
    )

    assert result.get("success") is True
    outputs = result.get("outputs", [])
    assert len(outputs) == 1
    assert str(outputs[0]).endswith("DOCUMENT.pdf")


@pytest.mark.asyncio
async def test_generate_document_pack_rejects_browser_image_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr("security.validator.FULL_DISK_ACCESS", True)

    result = await generate_document_pack(
        topic="kedi resmi arat",
        brief="kedi resmi arat",
        output_dir=str(tmp_path),
    )

    assert result.get("success") is False
    assert result.get("error_code") == "INVALID_DOCUMENT_BRIEF"
