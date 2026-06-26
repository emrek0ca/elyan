from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from actions._read_only_common import summarize_text
from actions._visual_block_common import normalize_visual_blocks, render_chart_block_to_png, table_ensure_width
from actions._write_common import artifact_payload, ensure_allowed_output_path, normalize_source_context
from actions.document_read import _ALLOWED_SUFFIXES as _READ_ALLOWED_SUFFIXES
from actions.document_read import _extract_document_text
from actions._read_only_common import ensure_allowed_path
from runtime.capability_registry import SafeCapabilityError


DEFAULT_CANVAS_WIDTH = 1400
DEFAULT_CANVAS_HEIGHT = 1800
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
_CANVAS_SOURCE_SUFFIXES = _READ_ALLOWED_SUFFIXES | _IMAGE_SUFFIXES


def _workspace_root() -> Path:
    from actions._read_only_common import workspace_root

    return workspace_root()


def _chart_temp_path() -> Path:
    directory = Path(tempfile.gettempdir())
    directory.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=f"elyan-chart-{uuid.uuid4().hex[:8]}-", suffix=".png", dir=str(directory))
    os.close(fd)
    return Path(raw_path)


def _source_blocks_from_path(source_path: str) -> list[dict[str, Any]]:
    candidate = str(source_path or "").strip()
    if not candidate:
        return []
    resolved = ensure_allowed_path(
        candidate,
        allowed_suffixes=_CANVAS_SOURCE_SUFFIXES,
        root_resolver=_workspace_root,
    )
    suffix = resolved.suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return [{"kind": "image", "path": str(resolved), "alt": resolved.name}]
    text, _pages = _extract_document_text(resolved)
    text = str(text or "").strip()
    if text:
        return normalize_visual_blocks([text], fallback_text=text)
    return []


def _resolve_output_format(output_path: str, output_format: str) -> str:
    suffix = str(Path(output_path).suffix or "").lower().lstrip(".")
    candidate = str(output_format or "").strip().lower().lstrip(".")
    if candidate in {"pdf", "png"}:
        return candidate
    if suffix in {"pdf", "png"}:
        return suffix
    return "pdf"


def _parse_dimension(value: Any, default: int) -> int:
    try:
        parsed = int(round(float(value)))
    except Exception:
        parsed = default
    return max(400, parsed)


def _theme_value(theme: dict[str, Any] | None, key: str, default: str) -> str:
    value = theme.get(key) if isinstance(theme, dict) else None
    candidate = str(value or "").strip()
    return candidate or default


def _normalize_canvas_blocks(
    prompt: str,
    title: str,
    blocks: list[dict[str, Any]] | None,
    sections: list[dict[str, Any]] | None,
    source_context: str,
    source_path: str,
) -> list[dict[str, Any]]:
    merged: list[Any] = []
    if isinstance(blocks, list):
        merged.extend(blocks)
    if isinstance(sections, list):
        merged.extend(sections)
    merged.extend(_source_blocks_from_path(source_path))
    fallback = prompt or source_context or title
    normalized = normalize_visual_blocks(merged, fallback_text=fallback)
    if normalized:
        return normalized
    if fallback.strip():
        return normalize_visual_blocks([fallback], fallback_text=fallback)
    return []


def _pdf_flowables(
    blocks: list[dict[str, Any]],
    *,
    page_width: int,
    theme: dict[str, Any] | None,
    title: str,
    temp_paths: list[Path] | None = None,
) -> list[Any]:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    styles = getSampleStyleSheet()
    base_style = ParagraphStyle(
        "ElyanBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor(_theme_value(theme, "textColor", "#232121")),
        alignment=TA_LEFT,
        spaceAfter=4,
    )
    title_style = ParagraphStyle(
        "ElyanTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor(_theme_value(theme, "titleColor", "#1f1a17")),
        spaceAfter=10,
    )
    heading_style = ParagraphStyle(
        "ElyanHeading",
        parent=base_style,
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor(_theme_value(theme, "headingColor", "#2b231f")),
        spaceBefore=6,
        spaceAfter=6,
    )

    flowables: list[Any] = []
    if title.strip():
        flowables.append(Paragraph(escape(title.strip()).replace("\n", "<br/>"), title_style))
        flowables.append(Spacer(1, 4 * mm))

    content_width = page_width - 56 * mm
    for block in blocks:
        kind = str(block.get("kind", "") or "").strip().lower()
        if kind == "spacer":
            flowables.append(Spacer(1, max(2, int(block.get("height", 16) or 16)) * mm / 5))
            continue
        if kind == "text":
            text = str(block.get("text", "") or "").strip()
            if not text:
                continue
            level = int(block.get("level", 0) or 0)
            style = heading_style if level > 0 else base_style
            flowables.append(Paragraph(escape(text).replace("\n", "<br/>"), style))
            continue
        if kind == "image":
            path = Path(str(block.get("path", "") or "")).expanduser()
            if not path.exists():
                continue
            try:
                from PIL import Image

                with Image.open(path) as handle:
                    width_px, height_px = handle.size
            except Exception:
                width_px, height_px = 1200, 800
            target_width = min(content_width, float(block.get("width", 0) or 0) or content_width)
            target_height = float(block.get("height", 0) or 0) or target_width * (height_px / max(1, width_px))
            image = RLImage(str(path))
            image.drawWidth = target_width
            image.drawHeight = min(target_height, target_width * (height_px / max(1, width_px)))
            flowables.append(image)
            flowables.append(Spacer(1, 4 * mm))
            continue
        if kind == "chart":
            chart_path = _chart_temp_path()
            try:
                render_chart_block_to_png(block, chart_path)
                if temp_paths is not None:
                    temp_paths.append(chart_path)
            except Exception:
                try:
                    chart_path.unlink(missing_ok=True)
                except Exception:
                    pass
                continue
            try:
                from PIL import Image

                with Image.open(chart_path) as handle:
                    width_px, height_px = handle.size
            except Exception:
                width_px, height_px = 1200, 720
            target_width = min(content_width, float(block.get("width", 0) or 0) or content_width)
            target_height = float(block.get("height", 0) or 0) or target_width * (height_px / max(1, width_px))
            image = RLImage(str(chart_path))
            image.drawWidth = target_width
            image.drawHeight = min(target_height, target_width * (height_px / max(1, width_px)))
            flowables.append(image)
            flowables.append(Spacer(1, 4 * mm))
            continue
        if kind == "table":
            headers, rows = table_ensure_width(
                [str(item) for item in (block.get("headers", []) or [])],
                [[str(cell) for cell in row] for row in (block.get("rows", []) or [])],
            )
            if not rows and not headers:
                continue
            table_data = [headers, *rows]
            total_chars = sum(max(len(str(cell)) for cell in row) if row else 0 for row in table_data) or 1
            column_count = max(1, len(headers))
            col_widths = [content_width / column_count for _ in range(column_count)]
            table = Table(
                [[Paragraph(escape(str(cell)), base_style) for cell in row] for row in table_data],
                colWidths=col_widths,
                repeatRows=1,
            )
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_theme_value(theme, "tableHeaderBg", "#ebe4da"))),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(_theme_value(theme, "tableHeaderText", "#2b231f"))),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                        ("LEADING", (0, 0), (-1, -1), 12),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                            colors.HexColor(_theme_value(theme, "tableRowAlt1", "#faf8f4")),
                            colors.HexColor(_theme_value(theme, "tableRowAlt2", "#f5f1ea")),
                        ]),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(_theme_value(theme, "tableBorder", "#d8cec0"))),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            if str(block.get("title", "") or "").strip():
                flowables.append(Paragraph(escape(str(block.get("title")).strip()), heading_style))
            flowables.append(table)
            flowables.append(Spacer(1, 4 * mm))
            continue
    return flowables


def _render_pdf(
    output_path: Path,
    *,
    title: str,
    blocks: list[dict[str, Any]],
    width: int,
    height: int,
    theme: dict[str, Any] | None,
    temp_paths: list[Path] | None = None,
) -> None:
    from reportlab.lib.pagesizes import portrait
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=portrait((width, height)),
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title or output_path.stem,
        author="Elyan",
    )
    flowables = _pdf_flowables(blocks, page_width=width, theme=theme, title=title, temp_paths=temp_paths)
    doc.build(flowables)


def _load_font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    candidates = ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf"] if bold else ["DejaVuSans.ttf", "DejaVuSans-Bold.ttf"]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _measure_text(draw: Any, text: str, font: Any, max_width: int) -> tuple[list[str], int]:
    lines: list[str] = []
    current = ""
    for paragraph in str(text or "").splitlines() or [""]:
        parts = paragraph.split(" ")
        for part in parts:
            candidate = f"{current} {part}".strip()
            bbox = draw.textbbox((0, 0), candidate or " ", font=font)
            if bbox[2] - bbox[0] <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = part
        lines.append(current)
        current = ""
    if current:
        lines.append(current)
    if not lines:
        lines = [""]
    ascent, descent = font.getmetrics() if hasattr(font, "getmetrics") else (10, 3)
    line_height = int(ascent + descent + 4)
    return lines, line_height * len(lines)


def _render_png(
    output_path: Path,
    *,
    title: str,
    blocks: list[dict[str, Any]],
    width: int,
    height: int,
    theme: dict[str, Any] | None,
    temp_paths: list[Path] | None = None,
) -> None:
    from PIL import Image, ImageColor, ImageDraw, ImageOps

    bg = ImageColor.getrgb(_theme_value(theme, "backgroundColor", "#f7f1e7"))
    surface = ImageColor.getrgb(_theme_value(theme, "surfaceColor", "#fffaf3"))
    text_color = ImageColor.getrgb(_theme_value(theme, "textColor", "#232121"))
    heading_color = ImageColor.getrgb(_theme_value(theme, "headingColor", "#2b231f"))
    header_bg = ImageColor.getrgb(_theme_value(theme, "tableHeaderBg", "#ebe4da"))
    table_border = ImageColor.getrgb(_theme_value(theme, "tableBorder", "#d8cec0"))
    row_a = ImageColor.getrgb(_theme_value(theme, "tableRowAlt1", "#faf8f4"))
    row_b = ImageColor.getrgb(_theme_value(theme, "tableRowAlt2", "#f5f1ea"))

    margin = 54
    content_width = max(360, width - margin * 2)

    font_body = _load_font(24, bold=False)
    font_heading = _load_font(30, bold=True)
    font_small = _load_font(20, bold=False)
    font_small_bold = _load_font(20, bold=True)

    probe = Image.new("RGB", (width, max(height, 1200)), bg)
    probe_draw = ImageDraw.Draw(probe)
    estimated_height = margin
    if title.strip():
        title_lines, title_h = _measure_text(probe_draw, title.strip(), font_heading, content_width)
        estimated_height += title_h + 28
    for block in blocks:
        kind = str(block.get("kind", "") or "").strip().lower()
        if kind == "spacer":
            estimated_height += max(8, int(block.get("height", 16) or 16))
            continue
        if kind == "text":
            font = font_small_bold if int(block.get("level", 0) or 0) > 0 else font_body
            _, block_h = _measure_text(probe_draw, str(block.get("text", "") or ""), font, content_width)
            estimated_height += block_h + 18
            continue
        if kind == "image":
            path = Path(str(block.get("path", "") or "")).expanduser()
            try:
                with Image.open(path) as handle:
                    img_w, img_h = handle.size
                target_width = min(content_width, int(block.get("width", 0) or 0) or content_width)
                target_height = int(block.get("height", 0) or 0) or int(target_width * (img_h / max(1, img_w)))
            except Exception:
                target_height = 240
            estimated_height += target_height + 18
            continue
        if kind == "chart":
            target_width = int(block.get("width", 0) or 0) or content_width
            target_height = int(block.get("height", 0) or 0) or 360
            estimated_height += max(240, int(target_height)) + 18
            continue
        if kind == "table":
            headers, rows = table_ensure_width(
                [str(item) for item in (block.get("headers", []) or [])],
                [[str(cell) for cell in row] for row in (block.get("rows", []) or [])],
            )
            width_count = max(1, len(headers))
            col_width = content_width // width_count
            row_padding = 16
            estimated_height += 36
            for row in rows:
                row_height = 0
                for cell in row:
                    _, cell_height = _measure_text(probe_draw, cell, font_small, max(80, col_width - row_padding))
                    row_height = max(row_height, cell_height)
                estimated_height += row_height + row_padding
            if str(block.get("title", "") or "").strip():
                estimated_height += 30
            estimated_height += 12

    actual_height = max(height, estimated_height + margin)
    canvas = Image.new("RGB", (width, actual_height), bg)
    draw = ImageDraw.Draw(canvas)
    y = margin

    if title.strip():
        title_lines, title_h = _measure_text(draw, title.strip(), font_heading, content_width)
        draw.rounded_rectangle([margin - 18, y - 14, width - margin + 18, y + title_h + 22], radius=28, fill=surface)
        draw.text((margin, y), "\n".join(title_lines), fill=heading_color, font=font_heading, spacing=6)
        y += title_h + 24

    for block in blocks:
        kind = str(block.get("kind", "") or "").strip().lower()
        if kind == "spacer":
            y += max(8, int(block.get("height", 16) or 16))
            continue
        if kind == "text":
            font = font_small_bold if int(block.get("level", 0) or 0) > 0 else font_body
            text = str(block.get("text", "") or "").strip()
            if not text:
                continue
            lines, text_h = _measure_text(draw, text, font, content_width)
            padding_y = 12
            draw.rounded_rectangle(
                [margin - 10, y - 8, width - margin + 10, y + text_h + padding_y],
                radius=24,
                fill=surface,
            )
            draw.text((margin, y), "\n".join(lines), fill=heading_color if int(block.get("level", 0) or 0) > 0 else text_color, font=font, spacing=6)
            y += text_h + 16
            continue
        if kind == "image":
            path = Path(str(block.get("path", "") or "")).expanduser()
            if not path.exists():
                continue
            try:
                with Image.open(path) as handle:
                    handle = handle.convert("RGB")
                    img_w, img_h = handle.size
                    target_width = min(content_width, int(block.get("width", 0) or 0) or content_width)
                    target_height = int(block.get("height", 0) or 0) or int(target_width * (img_h / max(1, img_w)))
                    target_height = max(80, target_height)
                    resized = ImageOps.contain(handle, (target_width, target_height))
            except Exception:
                continue
            box_h = resized.height + 26
            draw.rounded_rectangle(
                [margin - 10, y - 8, width - margin + 10, y + box_h],
                radius=24,
                fill=surface,
            )
            canvas.paste(resized, (margin, y + 6))
            y += box_h + 6
            continue
        if kind == "chart":
            chart_path = _chart_temp_path()
            try:
                render_chart_block_to_png(block, chart_path)
                if temp_paths is not None:
                    temp_paths.append(chart_path)
            except Exception:
                try:
                    chart_path.unlink(missing_ok=True)
                except Exception:
                    pass
                continue
            try:
                with Image.open(chart_path) as handle:
                    handle = handle.convert("RGB")
                    img_w, img_h = handle.size
                    target_width = min(content_width, int(block.get("width", 0) or 0) or content_width)
                    target_height = int(block.get("height", 0) or 0) or int(target_width * (img_h / max(1, img_w)))
                    target_height = max(80, target_height)
                    resized = ImageOps.contain(handle, (target_width, target_height))
            except Exception:
                continue
            box_h = resized.height + 26
            draw.rounded_rectangle(
                [margin - 10, y - 8, width - margin + 10, y + box_h],
                radius=24,
                fill=surface,
            )
            canvas.paste(resized, (margin, y + 6))
            y += box_h + 6
            continue
        if kind == "table":
            headers, rows = table_ensure_width(
                [str(item) for item in (block.get("headers", []) or [])],
                [[str(cell) for cell in row] for row in (block.get("rows", []) or [])],
            )
            if not rows:
                continue
            if str(block.get("title", "") or "").strip():
                title_lines, title_h = _measure_text(draw, str(block.get("title", "")), font_small_bold, content_width)
                draw.text((margin, y), "\n".join(title_lines), fill=heading_color, font=font_small_bold, spacing=6)
                y += title_h + 10

            column_count = max(1, len(headers))
            column_widths = [content_width // column_count for _ in range(column_count)]
            remainder = content_width - sum(column_widths)
            if remainder:
                column_widths[-1] += remainder
            row_top = y
            header_height = 40
            draw.rounded_rectangle(
                [margin - 10, row_top - 4, width - margin + 10, row_top + header_height],
                radius=18,
                fill=header_bg,
                outline=table_border,
                width=1,
            )
            x = margin
            for index, header in enumerate(headers):
                cell_width = column_widths[index]
                draw.text((x + 10, row_top + 10), header, fill=heading_color, font=font_small_bold)
                x += cell_width
            y += header_height + 4

            for row_index, row in enumerate(rows):
                row_heights: list[int] = []
                wrapped_cells: list[list[str]] = []
                for index, cell in enumerate(row):
                    cell_width = max(80, column_widths[index] - 18)
                    lines, cell_height = _measure_text(draw, cell, font_small, cell_width)
                    wrapped_cells.append(lines)
                    row_heights.append(cell_height)
                current_height = max(row_heights or [24]) + 16
                fill = row_a if row_index % 2 == 0 else row_b
                draw.rounded_rectangle(
                    [margin - 10, y - 2, width - margin + 10, y + current_height],
                    radius=14,
                    fill=fill,
                    outline=table_border,
                    width=1,
                )
                x = margin
                for index, lines in enumerate(wrapped_cells):
                    draw.multiline_text((x + 10, y + 8), "\n".join(lines), fill=text_color, font=font_small, spacing=5)
                    x += column_widths[index]
                y += current_height + 6
            y += 8

    canvas.save(output_path)


def canvas_write(
    prompt: str = "",
    output_path: str = "",
    title: str = "",
    blocks: list[dict[str, Any]] | None = None,
    sections: list[dict[str, Any]] | None = None,
    output_format: str = "",
    width: int | float | str = DEFAULT_CANVAS_WIDTH,
    height: int | float | str = DEFAULT_CANVAS_HEIGHT,
    theme: dict[str, Any] | None = None,
    source_context: str = "",
    source_path: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    requested_format = _resolve_output_format(output_path, output_format)
    extension = f".{requested_format}"
    resolved_output = ensure_allowed_output_path(
        output_path,
        extension=extension,
        overwrite=overwrite,
        hint=title or prompt or "elyan-canvas",
        root_resolver=_workspace_root,
    )
    seed_text = str(source_context or prompt or title or "").strip()
    normalized_blocks = _normalize_canvas_blocks(prompt, title, blocks, sections, seed_text, source_path)
    if not normalized_blocks and not seed_text:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Canvas oluşturmak için içerik veya blok verisi gerekli.")

    canvas_width = _parse_dimension(width, DEFAULT_CANVAS_WIDTH)
    canvas_height = _parse_dimension(height, DEFAULT_CANVAS_HEIGHT)
    output_title = str(title or resolved_output.stem).strip() or "Elyan Canvas"
    temp_paths: list[Path] = []

    try:
        if requested_format == "pdf":
            _render_pdf(
                resolved_output,
                title=output_title,
                blocks=normalized_blocks,
                width=canvas_width,
                height=canvas_height,
                theme=theme,
                temp_paths=temp_paths,
            )
        else:
            _render_png(
                resolved_output,
                title=output_title,
                blocks=normalized_blocks,
                width=canvas_width,
                height=canvas_height,
                theme=theme,
                temp_paths=temp_paths,
            )
    finally:
        for path in temp_paths:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                continue

    summary = summarize_text(seed_text or output_title, max_chars=260)
    return {
        "text": f"Canvas oluşturuldu: {resolved_output.name}",
        "result": {
            "kind": "canvas_write",
            "sourceContext": normalize_source_context(seed_text or output_title),
            "sourcePath": str(source_path or "").strip(),
            "outputPath": str(resolved_output),
            "outputFormat": requested_format,
            "contentType": artifact_payload(resolved_output)["contentType"],
            "created": True,
            "title": output_title,
            "summary": summary,
            "blockCount": len(normalized_blocks),
            "pageWidth": canvas_width,
            "pageHeight": canvas_height,
        },
        "artifacts": [artifact_payload(resolved_output)],
    }
