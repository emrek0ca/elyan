from __future__ import annotations

from runtime.skill_runtime import _builtin_skill_manifests


def test_builtin_skill_catalog_exposes_library_backed_skills() -> None:
    manifests = _builtin_skill_manifests()
    by_id = {str(item.get("id", "") or ""): item for item in manifests}

    for skill_id in {
        "web.research",
        "ocr.read",
        "browser.search",
        "math.solve",
        "canvas.write",
        "document.summary_and_save",
    }:
        assert skill_id in by_id

    web = by_id["web.research"]
    assert web["adapter"] == "web_research"
    assert "httpx" in web["libraries"]
    assert web["latencyClass"] in {"quick", "medium", "slow"}
    assert "query" in web["expectedInputs"]
    assert "web" in web["intentTags"]

    ocr = by_id["ocr.read"]
    assert ocr["adapter"] == "ocr_read"
    assert "pymupdf" in ocr["libraries"]
    assert ocr["latencyClass"] in {"quick", "medium", "slow"}

    canvas = by_id["canvas.write"]
    assert canvas["adapter"] == "canvas_write"
    assert "reportlab" in canvas["libraries"]
    assert "blocks" in canvas["expectedInputs"]

    summary_and_save = by_id["document.summary_and_save"]
    assert summary_and_save["adapter"] == "document_write"
    assert summary_and_save["requiresConfirmation"] is True
    assert summary_and_save["stepCount"] == 2
    assert "path" in summary_and_save["expectedInputs"]
    assert "text" in summary_and_save["expectedInputs"]


def test_builtin_skill_catalog_exposes_new_compound_skills() -> None:
    manifests = _builtin_skill_manifests()
    by_id = {str(item.get("id", "") or ""): item for item in manifests}

    for skill_id in {
        "research.present",
        "research.report",
        "data.analyze_and_chart",
        "screen.explain",
        "image.describe",
    }:
        assert skill_id in by_id, f"{skill_id} eksik"

    present = by_id["research.present"]
    assert present["adapter"] == "presentation_write"
    assert present["stepCount"] == 2  # web_research -> presentation_write
    assert present["requiresConfirmation"] is True

    report = by_id["research.report"]
    assert report["adapter"] == "document_write"
    assert report["stepCount"] == 2  # web_research -> document_write

    chart = by_id["data.analyze_and_chart"]
    assert chart["stepCount"] == 2  # data_analyze -> chart_generate

    screen = by_id["screen.explain"]
    assert screen["adapter"] == "desktop_operator.observe_screen"
    assert screen["requiresConfirmation"] is False  # gözlem yan etkisiz
