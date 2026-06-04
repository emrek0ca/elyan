from __future__ import annotations

from pathlib import Path
from typing import Any

from actions._read_only_common import bulletize_text, summarize_text
from actions._write_common import artifact_payload, ensure_allowed_output_path, normalize_source_context
from runtime.capability_registry import SafeCapabilityError


def _workspace_root() -> Path:
    from actions._read_only_common import workspace_root

    return workspace_root()


def _normalize_slides(slides: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(slides, list):
        return normalized
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        normalized.append(
            {
                "title": str(slide.get("title", "") or "").strip(),
                "bullets": [str(item) for item in (slide.get("bullets") or []) if str(item).strip()],
                "body": str(slide.get("body", "") or "").strip(),
            }
        )
    return normalized


def presentation_write(
    prompt: str = "",
    output_path: str = "",
    title: str = "",
    slides: list[dict[str, Any]] | None = None,
    source_context: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    from pptx import Presentation  # type: ignore[reportMissingImports]

    resolved_output = ensure_allowed_output_path(
        output_path,
        extension=".pptx",
        overwrite=overwrite,
        hint=title or prompt or "elyan-presentation",
        root_resolver=_workspace_root,
    )
    seed_text = str(source_context or prompt or "").strip()
    normalized_slides = _normalize_slides(slides)
    if not seed_text and not normalized_slides:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Sunum oluşturmak için içerik veya slayt verisi gerekli.")

    presentation = Presentation()
    title_layout = presentation.slide_layouts[0]
    content_layout = presentation.slide_layouts[1]

    deck_title = str(title or resolved_output.stem).strip() or "Elyan Presentation"
    title_slide = presentation.slides.add_slide(title_layout)
    title_slide.shapes.title.text = deck_title
    subtitle = title_slide.placeholders[1] if len(title_slide.placeholders) > 1 else None
    if subtitle is not None:
        subtitle.text = summarize_text(seed_text or deck_title, max_chars=120)

    if normalized_slides:
        for slide in normalized_slides:
            page = presentation.slides.add_slide(content_layout)
            page.shapes.title.text = slide["title"] or deck_title
            body = page.placeholders[1].text_frame
            if slide["bullets"]:
                body.text = slide["bullets"][0]
                for bullet in slide["bullets"][1:]:
                    body.add_paragraph().text = bullet
            elif slide["body"]:
                body.text = slide["body"]
    else:
        bullets = bulletize_text(seed_text, limit=6)
        page = presentation.slides.add_slide(content_layout)
        page.shapes.title.text = deck_title
        body = page.placeholders[1].text_frame
        if bullets:
            body.text = bullets[0]
            for bullet in bullets[1:]:
                body.add_paragraph().text = bullet
        else:
            body.text = seed_text

    presentation.save(str(resolved_output))
    return {
        "text": f"PPTX oluşturuldu: {resolved_output.name}",
        "result": {
            "kind": "presentation_write",
            "sourceContext": normalize_source_context(seed_text or deck_title),
            "outputPath": str(resolved_output),
            "contentType": artifact_payload(resolved_output)["contentType"],
            "created": True,
            "title": deck_title,
            "slideCount": len(presentation.slides),
            "summary": summarize_text(seed_text or deck_title, max_chars=260),
        },
        "artifacts": [artifact_payload(resolved_output)],
    }
