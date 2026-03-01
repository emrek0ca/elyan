from pathlib import Path
import importlib

import pytest

from tools.pro_workflows import (
    create_web_project_scaffold,
    create_coding_delivery_plan,
    create_coding_verification_report,
    create_software_project_pack,
    research_document_delivery,
)


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
    (project_dir / "index.html").write_text("<html></html>", encoding="utf-8")
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
async def test_research_document_delivery_generates_pack(monkeypatch, tmp_path):
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
    assert any(str(x).endswith(".md") for x in outputs)
    assert any(str(x).endswith(".txt") for x in outputs)
    assert any(str(x).endswith(".docx") for x in outputs)
    assert any(str(x).endswith(".xlsx") for x in outputs)
    assert any("DELIVERY_NOTE.txt" in str(x) for x in outputs)
    assert isinstance(result.get("quality_summary"), dict)
    assert "avg_reliability" in result.get("quality_summary", {})

    md_path = next((Path(str(x)) for x in outputs if str(x).endswith(".md")), None)
    assert md_path is not None and md_path.exists()
    md_text = md_path.read_text(encoding="utf-8")
    assert "## Methodology" in md_text
    assert "## Risk & Limitations" in md_text
    assert "## Next Actions" in md_text
