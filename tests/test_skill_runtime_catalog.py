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
