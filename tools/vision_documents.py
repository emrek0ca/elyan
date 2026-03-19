"""Phase 3 document vision pipeline.

This module adds a structured document vision stack for:
- layout analysis
- table extraction
- chart / figure detection
- optional multimodal fallback for image-only pages

The implementation is dependency-safe:
- PyMuPDF (fitz) is the primary document backend
- OCR / multimodal analysis is optional and only used when available
- table exports default to JSON + XLSX and can optionally include CSV

The goal is not to simulate LayoutLMv3/TableTransformer/DETR exactly when
those models are unavailable. Instead, the pipeline provides a deterministic
local fallback and can be upgraded to model-backed execution later without
breaking the public API.
"""

from __future__ import annotations

import asyncio
import csv
import json
import math
import statistics
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import fitz
import numpy as np

from core.storage_paths import resolve_elyan_data_dir
from security.validator import validate_path
from utils.logger import get_logger

logger = get_logger("vision.document")

try:  # Optional dependency only used for richer exports
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pd = None


DEFAULT_OUTPUT_DIR = (resolve_elyan_data_dir() / "vision").resolve()


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _clean_list(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in values or []:
        text = _normalize_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _is_probable_heading(text: str, *, font_size: float, median_font: float, is_first_page: bool, bbox: tuple[float, float, float, float], page_height: float) -> bool:
    clean = _normalize_text(text)
    if not clean:
        return False
    if len(clean) > 120:
        return False
    top_region = bbox[1] <= max(110.0, page_height * 0.22)
    short_and_prominent = font_size >= (median_font * 1.20 if median_font > 0 else 0) and len(clean.split()) <= 12
    title_like = is_first_page and top_region and font_size >= (median_font * 1.35 if median_font > 0 else 0)
    return bool(title_like or short_and_prominent or (clean.isupper() and len(clean) <= 80))


def _is_probable_list_item(text: str) -> bool:
    clean = _normalize_text(text)
    if not clean:
        return False
    return bool(
        clean.startswith(("-", "•", "*"))
        or bool(__import__("re").match(r"^\d+[\.\)]\s+", clean))
    )


def _is_probable_table_text(text: str) -> bool:
    clean = _normalize_text(text)
    if not clean:
        return False
    if "|" in clean or "\t" in clean:
        return True
    parts = [part.strip() for part in __import__("re").split(r"\s{2,}", clean) if part.strip()]
    if len(parts) >= 3 and sum(any(ch.isdigit() for ch in part) for part in parts) >= 1:
        return True
    return False


def _looks_like_chart_hint(text: str) -> bool:
    low = _normalize_text(text).lower()
    return any(marker in low for marker in ("grafik", "chart", "plot", "diagram", "figure", "bar chart", "line chart", "pie chart"))


def _rect_to_tuple(rect: fitz.Rect | tuple[float, float, float, float] | None) -> tuple[float, float, float, float]:
    if rect is None:
        return (0.0, 0.0, 0.0, 0.0)
    if isinstance(rect, fitz.Rect):
        return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
    left, top, right, bottom = rect
    return (float(left), float(top), float(right), float(bottom))


def _tuple_union(rects: Sequence[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    if not rects:
        return (0.0, 0.0, 0.0, 0.0)
    xs0 = [r[0] for r in rects]
    ys0 = [r[1] for r in rects]
    xs1 = [r[2] for r in rects]
    ys1 = [r[3] for r in rects]
    return (min(xs0), min(ys0), max(xs1), max(ys1))


def _nearby_words(words: Sequence[Sequence[Any]], bbox: tuple[float, float, float, float], *, pad_x: float = 24.0, pad_y: float = 24.0) -> list[str]:
    x0, y0, x1, y1 = bbox
    candidate: list[str] = []
    for word in words or []:
        if len(word) < 5:
            continue
        wx0, wy0, wx1, wy1, text = float(word[0]), float(word[1]), float(word[2]), float(word[3]), str(word[4] or "").strip()
        if not text:
            continue
        if wx1 < x0 - pad_x or wx0 > x1 + pad_x or wy1 < y0 - pad_y or wy0 > y1 + pad_y:
            continue
        candidate.append(text)
    return candidate


def _page_text_from_blocks(blocks: Sequence[dict[str, Any]]) -> str:
    lines: list[str] = []
    for block in blocks:
        if int(block.get("type", 0)) != 0:
            continue
        block_lines: list[str] = []
        for line in block.get("lines") or []:
            span_texts: list[str] = []
            for span in line.get("spans") or []:
                text = _normalize_text(span.get("text"))
                if text:
                    span_texts.append(text)
            line_text = _normalize_text(" ".join(span_texts))
            if line_text:
                block_lines.append(line_text)
        block_text = "\n".join(block_lines).strip()
        if block_text:
            lines.append(block_text)
    return "\n\n".join(lines).strip()


def _page_font_sizes(blocks: Sequence[dict[str, Any]]) -> list[float]:
    font_sizes: list[float] = []
    for block in blocks:
        if int(block.get("type", 0)) != 0:
            continue
        for line in block.get("lines") or []:
            for span in line.get("spans") or []:
                size = _safe_float(span.get("size"), 0.0)
                if size > 0:
                    font_sizes.append(size)
    return font_sizes


@dataclass
class LayoutBlock:
    page_number: int
    role: str
    text: str
    bbox: tuple[float, float, float, float]
    font_size: float = 0.0
    line_count: int = 0
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VisionTable:
    page_number: int
    table_index: int
    bbox: tuple[float, float, float, float]
    headers: list[str]
    rows: list[list[str]]
    source: str = "fitz"
    confidence: float = 0.95
    preview: str = ""
    artifact_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["row_count"] = len(self.rows)
        payload["column_count"] = len(self.headers)
        return payload

    def to_records(self) -> list[dict[str, Any]]:
        if not self.rows:
            return []
        headers = list(self.headers or [])
        if not headers:
            width = max(len(row) for row in self.rows) if self.rows else 0
            headers = [f"Column {index + 1}" for index in range(width)]
        records: list[dict[str, Any]] = []
        for row in self.rows:
            padded = list(row) + [""] * max(0, len(headers) - len(row))
            records.append({headers[index]: padded[index] if index < len(padded) else "" for index in range(len(headers))})
        return records


@dataclass
class VisionChart:
    page_number: int
    chart_index: int
    chart_type: str
    title: str
    bbox: tuple[float, float, float, float]
    data_points: list[dict[str, Any]] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    confidence: float = 0.0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["point_count"] = len(self.data_points)
        return payload


@dataclass
class PageVisionAnalysis:
    page_number: int
    width: float
    height: float
    title: str = ""
    text: str = ""
    blocks: list[LayoutBlock] = field(default_factory=list)
    tables: list[VisionTable] = field(default_factory=list)
    charts: list[VisionChart] = field(default_factory=list)
    images: int = 0
    preview_path: str = ""
    multimodal_summary: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "width": self.width,
            "height": self.height,
            "title": self.title,
            "text": self.text,
            "blocks": [block.to_dict() for block in self.blocks],
            "tables": [table.to_dict() for table in self.tables],
            "charts": [chart.to_dict() for chart in self.charts],
            "images": self.images,
            "preview_path": self.preview_path,
            "multimodal_summary": self.multimodal_summary,
            "warnings": list(self.warnings),
        }


@dataclass
class DocumentVisionResult:
    success: bool
    path: str
    filename: str
    document_kind: str
    page_count: int
    pages: list[PageVisionAnalysis] = field(default_factory=list)
    full_text: str = ""
    summary: str = ""
    layout_summary: str = ""
    table_summary: str = ""
    chart_summary: str = ""
    warnings: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    language: str = "tr"

    def to_dict(self) -> dict[str, Any]:
        tables = [table.to_dict() for page in self.pages for table in page.tables]
        charts = [chart.to_dict() for page in self.pages for chart in page.charts]
        return {
            "success": self.success,
            "path": self.path,
            "filename": self.filename,
            "document_kind": self.document_kind,
            "page_count": self.page_count,
            "pages": [page.to_dict() for page in self.pages],
            "tables": tables,
            "table_count": len(tables),
            "charts": charts,
            "chart_count": len(charts),
            "full_text": self.full_text,
            "summary": self.summary,
            "layout_summary": self.layout_summary,
            "table_summary": self.table_summary,
            "chart_summary": self.chart_summary,
            "warnings": list(self.warnings),
            "artifacts": list(self.artifacts),
            "metadata": dict(self.metadata),
            "language": self.language,
            "prompt_block": self.to_prompt_block(),
        }

    def to_prompt_block(self, max_chars: int = 3500) -> str:
        parts = [
            f"Document: {self.filename}",
            f"Kind: {self.document_kind}",
            f"Pages: {self.page_count}",
            f"Summary: {self.summary or self.layout_summary or self.table_summary or self.chart_summary}",
        ]
        if self.layout_summary:
            parts.append(f"Layout: {self.layout_summary}")
        if self.table_summary:
            parts.append(f"Tables: {self.table_summary}")
        if self.chart_summary:
            parts.append(f"Charts: {self.chart_summary}")
        if self.full_text:
            excerpt = _normalize_text(self.full_text)
            parts.append(f"Text: {excerpt[:1200]}")
        prompt = "\n".join(part for part in parts if part).strip()
        if len(prompt) > max_chars:
            prompt = prompt[: max_chars - 1].rstrip() + "…"
        return prompt


class VisionDocumentAgent:
    """Structured document vision orchestrator."""

    def __init__(self, output_dir: str | None = None):
        self.output_dir = Path(output_dir).expanduser().resolve() if output_dir else DEFAULT_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def analyze(
        self,
        path: str | None = None,
        *,
        content: str | None = None,
        title: str | None = None,
        output_dir: str | None = None,
        export_formats: Sequence[str] | None = None,
        export_page_images: bool = False,
        include_tables: bool = True,
        include_charts: bool = True,
        use_multimodal_fallback: bool = True,
        max_pages: int | None = None,
        language: str = "tr",
    ) -> dict[str, Any]:
        """Analyze a document or image into layout/table/chart structures."""
        export_formats = tuple(str(fmt).strip().lower() for fmt in (export_formats or ("json", "xlsx")) if str(fmt).strip())
        destination = Path(output_dir).expanduser().resolve() if output_dir else self.output_dir
        destination.mkdir(parents=True, exist_ok=True)

        if path:
            valid, error, _ = validate_path(path)
            if not valid:
                return {"success": False, "error": error}
            file_path = Path(path).expanduser().resolve()
            if not file_path.exists():
                return {"success": False, "error": f"Dosya bulunamadi: {file_path}"}
        elif content:
            file_path = None
        else:
            return {"success": False, "error": "Dosya yolu veya içerik sağlanmalı"}

        try:
            if file_path is not None:
                result = await self._analyze_file(
                    file_path,
                    destination=destination,
                    export_formats=export_formats,
                    export_page_images=export_page_images,
                    include_tables=include_tables,
                    include_charts=include_charts,
                    use_multimodal_fallback=use_multimodal_fallback,
                    max_pages=max_pages,
                    language=language,
                )
            else:
                result = await self._analyze_text(
                    str(content or ""),
                    title=title or "Metin Belgesi",
                    destination=destination,
                    export_formats=export_formats,
                    language=language,
                )
            return result.to_dict()
        except Exception as exc:
            logger.error("Vision document analysis failed: %s", exc)
            return {"success": False, "error": str(exc)}

    async def extract_tables(
        self,
        path: str,
        *,
        output_dir: str | None = None,
        export_formats: Sequence[str] | None = None,
        language: str = "tr",
    ) -> dict[str, Any]:
        result = await self.analyze(
            path,
            output_dir=output_dir,
            export_formats=export_formats or ("json", "xlsx"),
            include_tables=True,
            include_charts=False,
            use_multimodal_fallback=False,
            language=language,
        )
        if not result.get("success"):
            return result
        result["tables"] = list(result.get("tables") or [])
        return {
            "success": True,
            "path": result.get("path"),
            "filename": result.get("filename"),
            "tables": result.get("tables", []),
            "table_count": len(result.get("tables") or []),
            "artifacts": result.get("artifacts", []),
            "page_count": result.get("page_count", 0),
        }

    async def extract_charts(
        self,
        path: str,
        *,
        output_dir: str | None = None,
        language: str = "tr",
    ) -> dict[str, Any]:
        result = await self.analyze(
            path,
            output_dir=output_dir,
            export_formats=("json",),
            include_tables=False,
            include_charts=True,
            use_multimodal_fallback=True,
            language=language,
        )
        if not result.get("success"):
            return result
        charts = list(result.get("charts") or [])
        return {
            "success": True,
            "path": result.get("path"),
            "filename": result.get("filename"),
            "charts": charts,
            "chart_count": len(charts),
            "artifacts": result.get("artifacts", []),
            "page_count": result.get("page_count", 0),
        }

    async def _analyze_file(
        self,
        file_path: Path,
        *,
        destination: Path,
        export_formats: Sequence[str],
        export_page_images: bool,
        include_tables: bool,
        include_charts: bool,
        use_multimodal_fallback: bool,
        max_pages: int | None,
        language: str,
    ) -> DocumentVisionResult:
        doc = fitz.open(str(file_path))
        try:
            pages: list[PageVisionAnalysis] = []
            tables: list[VisionTable] = []
            charts: list[VisionChart] = []
            all_text_parts: list[str] = []
            warnings: list[str] = []
            artifacts: list[str] = []
            title = file_path.stem
            page_limit = min(max_pages or doc.page_count, doc.page_count)

            for page_index in range(page_limit):
                page = doc[page_index]
                page_result = await self._analyze_page(
                    page,
                    page_number=page_index + 1,
                    file_path=file_path,
                    destination=destination,
                    export_page_images=export_page_images,
                    include_tables=include_tables,
                    include_charts=include_charts,
                    use_multimodal_fallback=use_multimodal_fallback,
                    language=language,
                )
                pages.append(page_result)
                tables.extend(page_result.tables)
                charts.extend(page_result.charts)
                if page_result.title and title == file_path.stem:
                    title = page_result.title
                if page_result.text:
                    all_text_parts.append(page_result.text)
                if page_result.multimodal_summary:
                    all_text_parts.append(page_result.multimodal_summary)
                warnings.extend(page_result.warnings)
                if page_result.preview_path:
                    artifacts.append(page_result.preview_path)

            layout_summary = self._summarize_layout(pages)
            table_summary = self._summarize_tables(tables)
            chart_summary = self._summarize_charts(charts)
            full_text = "\n\n".join(part for part in all_text_parts if part).strip()
            summary = self._build_summary(
                filename=file_path.name,
                page_count=page_limit,
                layout_summary=layout_summary,
                table_summary=table_summary,
                chart_summary=chart_summary,
                full_text=full_text,
            )

            result = DocumentVisionResult(
                success=True,
                path=str(file_path),
                filename=file_path.name,
                document_kind="pdf" if file_path.suffix.lower() == ".pdf" else "image" if file_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"} else "document",
                page_count=page_limit,
                pages=pages,
                full_text=full_text,
                summary=summary,
                layout_summary=layout_summary,
                table_summary=table_summary,
                chart_summary=chart_summary,
                warnings=_clean_list(warnings),
                artifacts=_clean_list(artifacts),
                metadata=self._file_metadata(file_path),
                language=language,
            )

            exported_paths = await self._export_artifacts(
                result=result,
                destination=destination,
                export_formats=export_formats,
                tables=tables,
                charts=charts,
                export_page_images=export_page_images,
            )
            result.artifacts.extend([path for path in exported_paths if path not in result.artifacts])
            return result
        finally:
            doc.close()

    async def _analyze_text(
        self,
        content: str,
        *,
        title: str,
        destination: Path,
        export_formats: Sequence[str],
        language: str,
    ) -> DocumentVisionResult:
        text = _normalize_text(content)
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        blocks: list[LayoutBlock] = []
        for line in lines[:500]:
            role = "paragraph"
            if _is_probable_heading(line, font_size=14.0, median_font=11.0, is_first_page=True, bbox=(0.0, 0.0, 0.0, 0.0), page_height=1000.0):
                role = "heading"
            elif _is_probable_list_item(line):
                role = "list_item"
            elif _is_probable_table_text(line):
                role = "table_text"
            blocks.append(
                LayoutBlock(
                    page_number=1,
                    role=role,
                    text=line,
                    bbox=(0.0, 0.0, 0.0, 0.0),
                    font_size=11.0,
                    line_count=1,
                    confidence=0.75 if role != "paragraph" else 0.55,
                )
            )

        page = PageVisionAnalysis(
            page_number=1,
            width=0.0,
            height=0.0,
            title=title,
            text=text,
            blocks=blocks,
        )
        summary = self._build_summary(
            filename=title,
            page_count=1,
            layout_summary=self._summarize_layout([page]),
            table_summary="",
            chart_summary="",
            full_text=text,
        )
        result = DocumentVisionResult(
            success=True,
            path=str(destination / f"{title}.txt"),
            filename=title,
            document_kind="text",
            page_count=1,
            pages=[page],
            full_text=text,
            summary=summary,
            layout_summary=self._summarize_layout([page]),
            warnings=[],
            artifacts=[],
            metadata={"source": "inline_text", "characters": len(text)},
            language=language,
        )
        return result

    async def _analyze_page(
        self,
        page: fitz.Page,
        *,
        page_number: int,
        file_path: Path,
        destination: Path,
        export_page_images: bool,
        include_tables: bool,
        include_charts: bool,
        use_multimodal_fallback: bool,
        language: str,
    ) -> PageVisionAnalysis:
        page_dict = page.get_text("dict")
        blocks_raw = list(page_dict.get("blocks") or [])
        words = page.get_text("words") or []
        page_text = _page_text_from_blocks(blocks_raw).strip()
        font_sizes = _page_font_sizes(blocks_raw)
        median_font = statistics.median(font_sizes) if font_sizes else 0.0
        page_rect = page.rect
        page_height = float(page_rect.height or 0.0)
        page_width = float(page_rect.width or 0.0)

        blocks: list[LayoutBlock] = []
        title = ""

        # Text and image blocks from PyMuPDF
        for raw_block in blocks_raw:
            block_type = int(raw_block.get("type", 0))
            bbox = _rect_to_tuple(raw_block.get("bbox"))
            if block_type == 1:
                blocks.append(
                    LayoutBlock(
                        page_number=page_number,
                        role="image",
                        text="",
                        bbox=bbox,
                        font_size=0.0,
                        line_count=0,
                        confidence=0.88,
                    )
                )
                continue

            text = _page_text_from_blocks([raw_block])
            if not text:
                continue

            line_count = len(raw_block.get("lines") or [])
            block_font_sizes: list[float] = []
            for line in raw_block.get("lines") or []:
                for span in line.get("spans") or []:
                    size = _safe_float(span.get("size"), 0.0)
                    if size > 0:
                        block_font_sizes.append(size)
            block_font = statistics.mean(block_font_sizes) if block_font_sizes else median_font

            role = "paragraph"
            if _is_probable_heading(text, font_size=block_font, median_font=median_font, is_first_page=page_number == 1, bbox=bbox, page_height=page_height):
                role = "title" if page_number == 1 and not title else "heading"
            elif _is_probable_list_item(text):
                role = "list_item"
            elif _is_probable_table_text(text):
                role = "table_text"

            if role in {"title", "heading"} and not title:
                title = text.splitlines()[0][:120].strip()

            blocks.append(
                LayoutBlock(
                    page_number=page_number,
                    role=role,
                    text=text,
                    bbox=bbox,
                    font_size=round(block_font, 2),
                    line_count=line_count,
                    confidence=0.92 if role in {"title", "heading"} else 0.72 if role == "table_text" else 0.66,
                )
            )

        # Tables from native PDF table finder.
        tables: list[VisionTable] = []
        if include_tables:
            tables.extend(self._extract_tables(page, page_number))

        # Chart/figure detection from drawings and text layout.
        charts: list[VisionChart] = []
        if include_charts:
            charts.extend(self._extract_charts(page, page_number, blocks, tables))

        preview_path = ""
        warnings: list[str] = []

        if export_page_images:
            try:
                preview_path = str(self._render_page_preview(page, destination, file_path.stem, page_number))
            except Exception as exc:  # pragma: no cover - defensive
                warnings.append(f"preview_failed_page_{page_number}:{exc}")

        # Optional multimodal fallback for image-only pages.
        multimodal_summary = ""
        if use_multimodal_fallback and not page_text:
            preview_source = preview_path or str(self._render_page_preview(page, destination, file_path.stem, page_number, temp_only=True))
            try:
                multimodal_summary = await self._multimodal_caption(
                    preview_source,
                    filename=file_path.name,
                    page_number=page_number,
                    language=language,
                )
            except Exception as exc:  # pragma: no cover - optional dependency
                warnings.append(f"multimodal_failed_page_{page_number}:{exc}")
            if not preview_path and preview_source and Path(preview_source).exists() and preview_source.startswith(str(tempfile.gettempdir())):
                try:
                    Path(preview_source).unlink(missing_ok=True)
                except Exception:
                    pass

        if not title and blocks:
            for block in blocks:
                if block.role in {"title", "heading"} and block.text:
                    title = block.text.splitlines()[0][:120].strip()
                    break
        if not title:
            top_texts = [b.text for b in blocks if b.text and b.role != "image"]
            title = top_texts[0].splitlines()[0][:120].strip() if top_texts else f"Page {page_number}"

        # If page has no extracted text, synthesize a minimal readable block.
        if not page_text and multimodal_summary:
            page_text = multimodal_summary.strip()

        return PageVisionAnalysis(
            page_number=page_number,
            width=page_width,
            height=page_height,
            title=title,
            text=page_text,
            blocks=blocks,
            tables=tables,
            charts=charts,
            images=len(page.get_images(full=True) or []),
            preview_path=preview_path,
            multimodal_summary=multimodal_summary,
            warnings=warnings,
        )

    def _extract_tables(self, page: fitz.Page, page_number: int) -> list[VisionTable]:
        tables: list[VisionTable] = []
        try:
            finder = page.find_tables()
            detected = list(getattr(finder, "tables", []) or [])
        except Exception as exc:  # pragma: no cover - fitz may still raise on malformed pages
            logger.debug("page.find_tables failed on page %s: %s", page_number, exc)
            detected = []

        for index, table in enumerate(detected, start=1):
            try:
                raw_rows = table.extract() or []
            except Exception:
                raw_rows = []
            rows = [[_normalize_text(cell) for cell in row] for row in raw_rows if isinstance(row, (list, tuple))]
            headers = _clean_list(getattr(getattr(table, "header", None), "names", []) or [])
            bbox = _rect_to_tuple(getattr(table, "bbox", None))

            if not headers and rows:
                width = max(len(row) for row in rows)
                headers = [f"Column {i + 1}" for i in range(width)]

            if rows and headers and rows[0] == headers:
                data_rows = rows[1:]
            else:
                data_rows = rows

            preview = ""
            if data_rows:
                preview = " | ".join(data_rows[0][: min(len(data_rows[0]), 5)])
            tables.append(
                VisionTable(
                    page_number=page_number,
                    table_index=index,
                    bbox=bbox,
                    headers=headers,
                    rows=data_rows,
                    source="fitz",
                    confidence=0.97,
                    preview=preview,
                )
            )

        # Heuristic table fallback for text-only tables.
        if not tables:
            text_blocks = [block for block in page.get_text("dict").get("blocks") or [] if int(block.get("type", 0)) == 0]
            for block_index, block in enumerate(text_blocks, start=1):
                text = _page_text_from_blocks([block])
                if not _is_probable_table_text(text):
                    continue
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                if len(lines) < 2:
                    continue
                split_rows: list[list[str]] = []
                for line in lines:
                    cells = [cell.strip() for cell in __import__("re").split(r"\s{2,}|\s*\|\s*|\t+", line) if cell.strip()]
                    if len(cells) >= 2:
                        split_rows.append(cells)
                if len(split_rows) < 2:
                    continue
                width = max(len(row) for row in split_rows)
                headers = [f"Column {i + 1}" for i in range(width)]
                preview = " | ".join(split_rows[0][: min(len(split_rows[0]), 5)])
                bbox = _rect_to_tuple(block.get("bbox"))
                tables.append(
                    VisionTable(
                        page_number=page_number,
                        table_index=block_index,
                        bbox=bbox,
                        headers=headers,
                        rows=split_rows,
                        source="heuristic_text",
                        confidence=0.66,
                        preview=preview,
                    )
                )
        return tables

    def _extract_charts(
        self,
        page: fitz.Page,
        page_number: int,
        blocks: list[LayoutBlock],
        tables: list[VisionTable],
    ) -> list[VisionChart]:
        drawings = list(page.get_drawings() or [])
        if not drawings:
            return []

        rects: list[fitz.Rect] = []
        lines: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for drawing in drawings:
            for item in drawing.get("items") or []:
                op = item[0]
                if op == "re":
                    rect = item[1]
                    if isinstance(rect, fitz.Rect):
                        rects.append(rect)
                elif op == "l":
                    start, end = item[1], item[2]
                    lines.append(((float(start.x), float(start.y)), (float(end.x), float(end.y))))

        if not rects and not lines:
            return []

        # Do not misclassify table pages as charts.
        if tables and len(rects) < 2 and len(lines) < 3:
            return []

        chart_bbox = _tuple_union([_rect_to_tuple(rect) for rect in rects])
        if chart_bbox == (0.0, 0.0, 0.0, 0.0):
            line_rects = [
                (min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1]))
                for p1, p2 in lines
            ]
            chart_bbox = _tuple_union(line_rects)

        text_candidates = [block.text for block in blocks if block.text and block.role in {"title", "heading", "paragraph"}]
        title = ""
        for candidate in text_candidates:
            if _looks_like_chart_hint(candidate):
                title = candidate.splitlines()[0][:120].strip()
                break
        if not title:
            title = next((block.text.splitlines()[0][:120].strip() for block in blocks if block.role in {"title", "heading"} and block.text), "Chart")

        words = page.get_text("words") or []
        page_width = float(page.rect.width or 0.0)
        page_height = float(page.rect.height or 0.0)

        bar_rects: list[fitz.Rect] = [rect for rect in rects if rect.width >= 6 and rect.height >= 12]
        line_segments = [segment for segment in lines if abs(segment[0][1] - segment[1][1]) < 4 or abs(segment[0][0] - segment[1][0]) < 4]
        chart_type = "figure"
        confidence = 0.58
        data_points: list[dict[str, Any]] = []
        labels: list[str] = []
        notes = "Drawing-based figure detected."

        if len(bar_rects) >= 2 and len(bar_rects) >= len(line_segments):
            chart_type = "bar_chart"
            confidence = 0.9
            baseline_y = max(rect.y1 for rect in bar_rects)
            max_height = max(max(rect.y1 - rect.y0, 1.0) for rect in bar_rects)
            sorted_bars = sorted(bar_rects, key=lambda rect: rect.x0)
            for bar_index, rect in enumerate(sorted_bars, start=1):
                bar_height = max(rect.y1 - rect.y0, 1.0)
                label_words = _nearby_words(words, _rect_to_tuple(rect), pad_x=40.0, pad_y=36.0)
                candidate_label = ""
                for word in label_words:
                    stripped = _normalize_text(word)
                    if stripped and not stripped.replace(".", "", 1).isdigit():
                        candidate_label = stripped
                        break
                if not candidate_label:
                    candidate_label = f"Bar {bar_index}"
                value_words = [word for word in label_words if _normalize_text(word).replace(".", "", 1).isdigit()]
                numeric_value = None
                if value_words:
                    try:
                        numeric_value = float(_normalize_text(value_words[0]))
                    except Exception:
                        numeric_value = None
                data_points.append(
                    {
                        "label": candidate_label,
                        "value": numeric_value if numeric_value is not None else round((bar_height / max_height) * 100.0, 2),
                        "normalized_height": round(bar_height / max_height, 3),
                        "bbox": _rect_to_tuple(rect),
                    }
                )
                labels.append(candidate_label)
            notes = "Bar chart detected from rectangular drawing primitives."
        elif len(line_segments) >= 3:
            chart_type = "line_chart"
            confidence = 0.82
            unique_points = []
            for start, end in line_segments:
                unique_points.extend([start, end])
            unique_points = sorted({(round(x, 1), round(y, 1)) for x, y in unique_points})
            for index, (x, y) in enumerate(unique_points[:24], start=1):
                data_points.append({"index": index, "x": x, "y": y})
            notes = "Line chart detected from connected line segments."
        elif any(_looks_like_chart_hint(block.text) for block in blocks):
            chart_type = "figure"
            confidence = 0.65
            notes = "Chart/figure keywords found in surrounding text."

        if not data_points and not any(_looks_like_chart_hint(block.text) for block in blocks):
            return []

        return [
            VisionChart(
                page_number=page_number,
                chart_index=1,
                chart_type=chart_type,
                title=title,
                bbox=chart_bbox,
                data_points=data_points,
                labels=labels,
                confidence=confidence,
                notes=notes,
            )
        ]

    async def _multimodal_caption(self, preview_path: str, *, filename: str, page_number: int, language: str) -> str:
        try:
            from tools.vision_tools import analyze_image

            prompt = (
                "Bu sayfayı belge analizi açısından özetle. "
                "Başlık, tablo, grafik, liste ve önemli metin bloklarını belirt. "
                "Kısa ama yapılandırılmış bir özet ver."
            )
            result = await analyze_image(
                image_path=preview_path,
                prompt=prompt,
                analysis_type="document_layout",
                language=language,
            )
            if result.get("success") and result.get("analysis"):
                analysis = _normalize_text(result.get("analysis"))
                if analysis:
                    return analysis
        except Exception as exc:
            logger.debug("Multimodal caption unavailable for %s page %s: %s", filename, page_number, exc)
        return ""

    def _render_page_preview(
        self,
        page: fitz.Page,
        destination: Path,
        stem: str,
        page_number: int,
        *,
        temp_only: bool = False,
    ) -> Path:
        pix = page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), alpha=False)
        if temp_only:
            tmp = Path(tempfile.gettempdir()) / f"elyan_vision_{stem}_p{page_number:03d}.png"
            pix.save(str(tmp))
            return tmp
        preview_dir = destination / "page_previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_path = preview_dir / f"{stem}_p{page_number:03d}.png"
        pix.save(str(preview_path))
        return preview_path

    async def _export_artifacts(
        self,
        *,
        result: DocumentVisionResult,
        destination: Path,
        export_formats: Sequence[str],
        tables: list[VisionTable],
        charts: list[VisionChart],
        export_page_images: bool,
    ) -> list[str]:
        artifacts: list[str] = []
        export_formats = tuple(fmt.lower() for fmt in export_formats)
        result_json_path = destination / f"{Path(result.filename).stem}_vision_analysis.json"

        if "json" in export_formats:
            result_json_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            artifacts.append(str(result_json_path))

        if export_page_images:
            for page in result.pages:
                if page.preview_path:
                    artifacts.append(page.preview_path)

        if tables:
            table_payload: dict[str, list[dict[str, Any]]] = {}
            headers_payload: dict[str, list[str]] = {}
            csv_requested = "csv" in export_formats
            csv_paths: list[str] = []
            for table in tables:
                sheet_name = f"p{table.page_number:02d}_t{table.table_index:02d}"
                table_payload[sheet_name] = table.to_records()
                headers_payload[sheet_name] = list(table.headers or [])
                if csv_requested:
                    csv_path = destination / f"{Path(result.filename).stem}_{sheet_name}.csv"
                    self._write_csv(csv_path, table)
                    csv_paths.append(str(csv_path))
            if "xlsx" in export_formats:
                try:
                    from tools.office_tools.excel_tools import write_excel

                    excel_path = destination / f"{Path(result.filename).stem}_tables.xlsx"
                    xlsx_result = await write_excel(
                        path=str(excel_path),
                        data=table_payload,
                        headers=headers_payload,
                        multi_sheet=True,
                    )
                    if xlsx_result.get("success"):
                        artifacts.append(str(excel_path))
                except Exception as exc:
                    logger.debug("Table export to xlsx failed: %s", exc)
            artifacts.extend(csv_paths)

        if charts and "json" in export_formats:
            chart_path = destination / f"{Path(result.filename).stem}_chart_data.json"
            chart_path.write_text(
                json.dumps([chart.to_dict() for chart in charts], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            artifacts.append(str(chart_path))

        return _clean_list(artifacts)

    @staticmethod
    def _write_csv(path: Path, table: VisionTable) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        headers = list(table.headers or [])
        rows = list(table.rows or [])
        with open(path, "w", encoding="utf-8", newline="") as fp:
            writer = csv.writer(fp)
            writer.writerow(headers)
            for row in rows:
                writer.writerow(list(row) + [""] * max(0, len(headers) - len(row)))

    @staticmethod
    def _summarize_layout(pages: Sequence[PageVisionAnalysis]) -> str:
        titles = [page.title for page in pages if page.title]
        heading_count = sum(1 for page in pages for block in page.blocks if block.role in {"title", "heading"})
        list_count = sum(1 for page in pages for block in page.blocks if block.role == "list_item")
        image_count = sum(page.images for page in pages)
        parts = []
        if titles:
            parts.append(f"Ana başlıklar: {', '.join(_clean_list(titles)[:4])}")
        parts.append(f"{len(pages)} sayfa, {heading_count} başlık/blok, {list_count} liste öğesi, {image_count} görsel blok")
        return " | ".join(parts)

    @staticmethod
    def _summarize_tables(tables: Sequence[VisionTable]) -> str:
        if not tables:
            return ""
        parts = []
        parts.append(f"{len(tables)} tablo algılandı")
        first = tables[0]
        if first.headers:
            parts.append(f"ilk tablo sütunları: {', '.join(first.headers[:6])}")
        if first.preview:
            parts.append(f"örnek satır: {first.preview}")
        return " | ".join(parts)

    @staticmethod
    def _summarize_charts(charts: Sequence[VisionChart]) -> str:
        if not charts:
            return ""
        kinds = _clean_list(chart.chart_type for chart in charts)
        parts = [f"{len(charts)} grafik/figür algılandı"]
        if kinds:
            parts.append(f"tipler: {', '.join(kinds[:4])}")
        if charts and charts[0].title:
            parts.append(f"ilk grafik: {charts[0].title}")
        return " | ".join(parts)

    @staticmethod
    def _build_summary(
        *,
        filename: str,
        page_count: int,
        layout_summary: str,
        table_summary: str,
        chart_summary: str,
        full_text: str,
    ) -> str:
        parts: list[str] = [
            f"{filename} belgesi incelendi.",
            f"{page_count} sayfa tarandı.",
        ]
        if layout_summary:
            parts.append(layout_summary)
        if table_summary:
            parts.append(table_summary)
        if chart_summary:
            parts.append(chart_summary)
        if full_text:
            excerpt = _normalize_text(full_text)
            if excerpt:
                parts.append(f"Metin özeti: {excerpt[:600]}")
        return " ".join(part for part in parts if part).strip()

    @staticmethod
    def _file_metadata(file_path: Path) -> dict[str, Any]:
        stat = file_path.stat()
        return {
            "size_bytes": stat.st_size,
            "modified": stat.st_mtime,
            "created": stat.st_ctime,
            "extension": file_path.suffix.lower(),
        }


_VISION_DOCUMENT_AGENT: VisionDocumentAgent | None = None


def get_document_vision_agent() -> VisionDocumentAgent:
    global _VISION_DOCUMENT_AGENT
    if _VISION_DOCUMENT_AGENT is None:
        _VISION_DOCUMENT_AGENT = VisionDocumentAgent()
    return _VISION_DOCUMENT_AGENT


async def analyze_document_vision(
    path: str | None = None,
    *,
    content: str | None = None,
    title: str | None = None,
    output_dir: str | None = None,
    export_formats: Sequence[str] | None = None,
    export_page_images: bool = False,
    include_tables: bool = True,
    include_charts: bool = True,
    use_multimodal_fallback: bool = True,
    max_pages: int | None = None,
    language: str = "tr",
) -> dict[str, Any]:
    return await get_document_vision_agent().analyze(
        path,
        content=content,
        title=title,
        output_dir=output_dir,
        export_formats=export_formats,
        export_page_images=export_page_images,
        include_tables=include_tables,
        include_charts=include_charts,
        use_multimodal_fallback=use_multimodal_fallback,
        max_pages=max_pages,
        language=language,
    )


async def extract_tables_from_document(
    path: str,
    *,
    output_dir: str | None = None,
    export_formats: Sequence[str] | None = None,
    language: str = "tr",
) -> dict[str, Any]:
    return await get_document_vision_agent().extract_tables(
        path,
        output_dir=output_dir,
        export_formats=export_formats,
        language=language,
    )


async def extract_charts_from_document(
    path: str,
    *,
    output_dir: str | None = None,
    language: str = "tr",
) -> dict[str, Any]:
    return await get_document_vision_agent().extract_charts(
        path,
        output_dir=output_dir,
        language=language,
    )


__all__ = [
    "LayoutBlock",
    "VisionTable",
    "VisionChart",
    "PageVisionAnalysis",
    "DocumentVisionResult",
    "VisionDocumentAgent",
    "analyze_document_vision",
    "extract_tables_from_document",
    "extract_charts_from_document",
    "get_document_vision_agent",
]
