from __future__ import annotations

from actions.document_read import document_read
from runtime.task_router import route_text_to_tool


def test_route_text_to_tool_prefers_summary_save_skill_for_embedded_attachment_text() -> None:
    prompt = (
        "--- rapor.pdf ---\n"
        "Birinci satır\n"
        "İkinci satır\n"
        "--- BELGE SONU: rapor.pdf ---\n\n"
        "bunu özetleyip masaüstüne kaydet"
    )

    routed = route_text_to_tool(prompt)

    assert routed is not None
    assert routed.tool_name == "run_skill"
    assert routed.intent == "document_summary_save"
    assert routed.requires_confirmation is True
    assert routed.is_multi_step is True
    assert routed.args["skillId"] == "document.summary_and_save"

    payload = routed.args["payload"]
    assert payload["text"].startswith("Birinci satır")
    assert payload["outputPath"].endswith(".docx")
    assert "kaydedilecek" in str(routed.plan_preview["summary"])


def test_route_text_to_tool_uses_selected_document_path_for_summary_save() -> None:
    routed = route_text_to_tool(
        "bu pdf'i özetleyip masaüstüne kaydet",
        selected_artifacts=[{"path": "/workspace/reports/aylik-rapor.pdf", "kind": "document"}],
    )

    assert routed is not None
    assert routed.tool_name == "run_skill"
    payload = routed.args["payload"]
    assert payload["path"] == "/workspace/reports/aylik-rapor.pdf"
    assert payload["selectedPaths"] == ["/workspace/reports/aylik-rapor.pdf"]
    assert payload["text"] == ""


def test_document_read_accepts_provided_text() -> None:
    result = document_read(path="", mode="summary", text="Birinci satır\nİkinci satır")

    assert result["result"]["backend"] == "provided_text"
    assert result["result"]["contentType"] == "text/plain"
    assert result["result"]["sourcePath"] == ""
    assert "Birinci satır" in result["result"]["text"]
    assert result["result"]["summary"]
