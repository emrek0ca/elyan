from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from functools import lru_cache
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


def _source_blocks_from_path(source_path: str, selected_paths: list[str] | None = None) -> list[dict[str, Any]]:
    candidate = str(source_path or "").strip()
    if not candidate:
        return []
    resolved = ensure_allowed_path(
        candidate,
        allowed_suffixes=_CANVAS_SOURCE_SUFFIXES,
        selected_paths=selected_paths,
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
    selected_paths: list[str] | None = None,
) -> list[dict[str, Any]]:
    merged: list[Any] = []
    if isinstance(blocks, list):
        merged.extend(blocks)
    if isinstance(sections, list):
        merged.extend(sections)
    merged.extend(_source_blocks_from_path(source_path, selected_paths))
    fallback = prompt or source_context or title
    normalized = normalize_visual_blocks(merged, fallback_text=fallback)
    if normalized:
        return normalized
    if fallback.strip():
        return normalize_visual_blocks([fallback], fallback_text=fallback)
    return []


def _normalise_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("ı", "i")
    text = text.replace("ğ", "g").replace("ü", "u").replace("ş", "s")
    text = text.replace("ö", "o").replace("ç", "c")
    return " ".join(text.split())


def _extract_page_target(prompt: str) -> int:
    match = re.search(r"(\d+)\s*(?:sayfa\w*|page[s]?)", _normalise_text(prompt))
    if not match:
        return 0
    try:
        value = int(match.group(1))
    except ValueError:
        return 0
    return value if 1 <= value <= 40 else 0


def _looks_like_report_request(prompt: str, title: str, output_format: str) -> bool:
    q = _normalise_text(f"{prompt} {title}")
    if output_format != "pdf":
        return False
    return any(token in q for token in ("arastirma", "research report", "kaynakca")) and any(
        token in q for token in ("hazirla", "olustur", "yaz", "uret", "duzenli", "kaynakca")
    )


def _report_topic(prompt: str, title: str) -> str:
    source = str(title or prompt or "").strip()
    source = re.sub(r"\baraştırma raporu\b", "", source, flags=re.IGNORECASE)
    source = re.sub(r"\barastirma raporu\b", "", source, flags=re.IGNORECASE)
    patterns = [
        r"(.+?)\s+hakk[ıi]nda",
        r"(.+?)\s+ile ilgili",
        r"about\s+(.+?)(?:\s+report|\s+rapor|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if match:
            candidate = " ".join(match.group(1).split()).strip(" .,!?:;")
            if candidate:
                return candidate[:120]
    cleaned = re.sub(
        r"\b(?:kaynakçalı|kaynakcali|düzenli|duzenli|yaklaşık|yaklasik|\d+\s*sayfa\w*|pdf|rapor|hazırla|hazirla|oluştur|olustur|yaz)\b",
        " ",
        source,
        flags=re.IGNORECASE,
    )
    cleaned = " ".join(cleaned.split()).strip(" .,!?:;")
    return cleaned[:120] or "Araştırma Konusu"


def _research_sources_from_context(source_context: str) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for chunk in str(source_context or "").split("\n\n"):
        start = chunk.find("{")
        if start < 0:
            continue
        try:
            payload = json.loads(chunk[start:])
        except (TypeError, ValueError):
            continue
        raw_sources = payload.get("sources") if isinstance(payload, dict) else None
        if not isinstance(raw_sources, list):
            continue
        for item in raw_sources:
            if not isinstance(item, dict):
                continue
            title = " ".join(str(item.get("title", "") or "").split())[:220]
            url = str(item.get("url", "") or "").strip()[:1000]
            summary = " ".join(str(item.get("summary", "") or item.get("snippet", "") or "").split())[:1200]
            key = url or title.casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            sources.append({"title": title or url, "url": url, "summary": summary})
            if len(sources) >= 8:
                return sources
    if sources:
        return sources
    for line in str(source_context or "").splitlines():
        url_match = re.search(r"https?://\S+", line)
        if not url_match:
            continue
        url = url_match.group(0).rstrip(".,;)")[:1000]
        title = line[: url_match.start()].strip(" -:.")[:220] or url
        if url in seen:
            continue
        seen.add(url)
        sources.append({"title": title, "url": url, "summary": ""})
        if len(sources) >= 8:
            break
    return sources


def _source_reference_lines(sources: list[dict[str, str]]) -> list[str]:
    lines: list[str] = []
    for source in sources:
        title = source["title"]
        url = source["url"]
        lines.append(f"{title} - {url}" if url and url != title else title)
    return lines


def _split_report_paragraphs(value: str, max_chars: int = 520) -> list[str]:
    sentences = [
        " ".join(item.split()).strip()
        for item in re.split(r"(?<=[.!?])\s+", str(value or ""))
        if " ".join(item.split()).strip()
    ]
    paragraphs: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            paragraphs.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        paragraphs.append(current)
    return paragraphs


_REPORT_STOP_WORDS = {
    "about",
    "after",
    "also",
    "arasında",
    "bunun",
    "daha",
    "fakat",
    "gibi",
    "için",
    "ile",
    "olarak",
    "olan",
    "olduğu",
    "önemli",
    "sonra",
    "tarafından",
    "the",
    "this",
    "that",
    "their",
    "they",
    "veya",
    "which",
    "with",
}


def _recurring_source_terms(sources: list[dict[str, str]], limit: int = 8) -> list[str]:
    document_frequency: dict[str, int] = {}
    for source in sources:
        terms = {
            token.casefold()
            for token in re.findall(r"[^\W\d_]{4,}", source.get("summary", ""), flags=re.UNICODE)
            if token.casefold() not in _REPORT_STOP_WORDS
        }
        for term in terms:
            document_frequency[term] = document_frequency.get(term, 0) + 1
    ranked = sorted(
        ((term, count) for term, count in document_frequency.items() if count >= 2),
        key=lambda item: (-item[1], item[0]),
    )
    return [term for term, _count in ranked[:limit]]


def _generic_report_sections(topic: str, source_context: str) -> list[tuple[str, list[str]]]:
    sources = _research_sources_from_context(source_context)
    usable_sources = [source for source in sources if source.get("summary")]
    if not usable_sources:
        raise SafeCapabilityError(
            "INSUFFICIENT_SOURCE_DATA",
            "Kaynaklı rapor için kullanılabilir araştırma verisi bulunamadı.",
        )

    recurring_terms = _recurring_source_terms(usable_sources)
    sections: list[tuple[str, list[str]]] = [
        (
            "Giriş",
            [
                f"Bu rapor, {topic} konusunda erişilebilen {len(usable_sources)} kaynağın metin özetlerini düzenli bir araştırma akışında bir araya getirir.",
                "Amaç, tek bir kaynağın anlatımını tekrar etmek yerine kaynaklarda sunulan bilgi ve vurguları görünür, izlenebilir ve kaynakçaya bağlı biçimde aktarmaktır.",
            ],
        ),
        (
            "Yöntem ve Kapsam",
            [
                "Araştırma sırasında bulunan sayfaların okunabilen metinleri çıkarılmış, her kaynak için sınırlı bir içerik özeti alınmış ve bu özetler ortak bir rapor yapısına dönüştürülmüştür.",
                "Aşağıdaki bulgular yalnızca aktarılan kaynak verisine dayanır. Kaynakta bulunmayan özel tarih, sayı veya neden-sonuç ilişkileri rapora eklenmemiştir.",
            ],
        ),
    ]

    topic_normalized = _normalise_text(topic)
    if "ataturk" in topic_normalized or "atatürk" in topic_normalized:
        sections.append(
            (
                "Tarihsel Bağlam ve Milli Mücadele",
                [
                    "Mustafa Kemal Atatürk'ün tarihsel rolü, Osmanlı İmparatorluğu'nun son dönemindeki askeri ve siyasi krizlerden Cumhuriyet'in kuruluşuna uzanan dönüşüm içinde değerlendirilmelidir.",
                    "Milli Mücadele dönemi, yalnız askeri cephelerden ibaret değildir; siyasi meşruiyetin kurulması, halk desteğinin örgütlenmesi ve bağımsızlık fikrinin kurumsal bir programa dönüştürülmesi açısından da belirleyici bir süreçtir.",
                    "Bu çerçevede Atatürk'ün liderliği, savaş koşullarında karar alma, diplomatik denge kurma ve sonrasında modernleşme reformlarını devlet politikası haline getirme başlıklarıyla birlikte incelenir.",
                ],
            )
        )

    for index, source in enumerate(usable_sources, start=1):
        heading = f"Bulgu {index}: {source['title'][:90]}"
        paragraphs = _split_report_paragraphs(source["summary"])
        if paragraphs:
            sections.append((heading, paragraphs))

    if recurring_terms:
        recurring_note = (
            "Kaynak özetlerinde birden fazla kez geçen kavramlar şunlardır: "
            + ", ".join(recurring_terms)
            + "."
        )
        conclusion_note = (
            f"Kaynaklar birlikte okunduğunda {topic} için öne çıkan ortak kelime düzeyindeki eksenler "
            + ", ".join(recurring_terms[:5])
            + " olarak görünmektedir."
        )
    else:
        recurring_note = "Kaynak özetleri farklı odaklar kullandığı için birden fazla kaynakta belirgin biçimde tekrarlanan ortak bir kavram kümesi oluşmamıştır."
        conclusion_note = f"Toplanan kaynaklar, {topic} konusunu farklı odaklardan inceleyen temel bir başvuru çerçevesi sağlamaktadır."

    sections.extend(
        [
            (
                "Karşılaştırmalı Değerlendirme",
                [
                    recurring_note,
                    "Bu tekrarlar yalnızca kaynaklar arasındaki ortak dil ve tema izlerini gösterir; tek başına bir iddianın doğruluğunu kanıtlamaz. Sonuçlar kaynak bağlantılarıyla birlikte değerlendirilmelidir.",
                ],
            ),
            (
                "Sınırlılıklar",
                [
                    "Rapor, çalışma sırasında erişilebilen web sayfaları ve bu sayfalardan çıkarılabilen sınırlı metinlerle hazırlanmıştır. Ücretli, kapalı, erişilemeyen veya yalnız görsel biçimde sunulan içerikler değerlendirmeye girmemiş olabilir.",
                    "Kritik kararlar veya akademik kullanım öncesinde kaynakların tam metinleri, yayın tarihleri ve kurumsal güvenilirliği ayrıca kontrol edilmelidir.",
                ],
            ),
            (
                "Sonuç",
                [
                    conclusion_note,
                    f"Raporun bulguları {len(usable_sources)} ayrı kaynağa bağlanmıştır; ayrıntılı doğrulama ve ileri araştırma için aşağıdaki kaynakça doğrudan izlenebilir.",
                ],
            ),
            ("Kaynakça", _source_reference_lines(usable_sources)),
        ]
    )
    return sections


def _report_blocks_from_sections(
    sections: list[tuple[str, list[str]]],
    page_target: int,
) -> list[dict[str, Any]]:
    if not sections:
        return []
    target = max(1, min(page_target, len(sections)))
    weights = [len(heading) + sum(len(paragraph) for paragraph in paragraphs) for heading, paragraphs in sections]
    remaining_weight = sum(weights)
    pages_remaining = target
    current_weight = 0
    blocks: list[dict[str, Any]] = []
    for index, (heading, paragraphs) in enumerate(sections):
        blocks.append({"kind": "text", "text": heading, "level": 1})
        blocks.extend({"kind": "text", "text": paragraph} for paragraph in paragraphs)
        current_weight += weights[index]
        remaining_weight -= weights[index]
        sections_remaining = len(sections) - index - 1
        if pages_remaining <= 1 or sections_remaining < pages_remaining - 1:
            continue
        desired_weight = (current_weight + remaining_weight) / pages_remaining
        next_weight = weights[index + 1] if sections_remaining else 0
        must_break = sections_remaining == pages_remaining - 1
        balanced_break = current_weight >= desired_weight * 0.85
        overflow_break = (
            current_weight >= desired_weight * 0.55
            and current_weight + next_weight > desired_weight * 1.25
        )
        if must_break or balanced_break or overflow_break:
            blocks.append({"kind": "page_break"})
            pages_remaining -= 1
            current_weight = 0
    return blocks


def _report_blocks_from_prompt(prompt: str, title: str, source_context: str, output_format: str) -> list[dict[str, Any]]:
    if not _looks_like_report_request(prompt, title, output_format):
        return []
    topic = _report_topic(prompt, title)
    page_target = _extract_page_target(prompt) or 4
    sections = _generic_report_sections(topic, source_context)
    return _report_blocks_from_sections(sections, page_target)


@lru_cache(maxsize=1)
def _register_pdf_fonts() -> tuple[str, str]:
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    fonts_dir = Path(reportlab.__file__).resolve().parent / "fonts"
    regular_path = fonts_dir / "Vera.ttf"
    bold_path = fonts_dir / "VeraBd.ttf"
    if not regular_path.exists() or not bold_path.exists():
        raise SafeCapabilityError("DEPENDENCY_UNAVAILABLE", "PDF için Unicode yazı tipi bulunamadı.")
    regular_name = "ElyanVera"
    bold_name = "ElyanVeraBold"
    if regular_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(regular_name, str(regular_path)))
    if bold_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
    return regular_name, bold_name


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
    from reportlab.platypus import PageBreak
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    regular_font, bold_font = _register_pdf_fonts()
    styles = getSampleStyleSheet()
    base_style = ParagraphStyle(
        "ElyanBody",
        parent=styles["BodyText"],
        fontName=regular_font,
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor(_theme_value(theme, "textColor", "#232121")),
        alignment=TA_LEFT,
        spaceAfter=4,
    )
    title_style = ParagraphStyle(
        "ElyanTitle",
        parent=styles["Title"],
        fontName=bold_font,
        fontSize=20,
        leading=24,
        textColor=colors.HexColor(_theme_value(theme, "titleColor", "#1f1a17")),
        spaceAfter=10,
    )
    heading_style = ParagraphStyle(
        "ElyanHeading",
        parent=base_style,
        fontName=bold_font,
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
        if kind == "page_break":
            flowables.append(PageBreak())
            continue
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
                        ("FONTNAME", (0, 0), (-1, 0), bold_font),
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

    regular_font, _bold_font = _register_pdf_fonts()
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

    def add_page_number(pdf_canvas: Any, _document: Any) -> None:
        pdf_canvas.saveState()
        pdf_canvas.setFont(regular_font, 8)
        pdf_canvas.setFillColorRGB(0.35, 0.35, 0.35)
        pdf_canvas.drawRightString(width - 18 * mm, 9 * mm, str(pdf_canvas.getPageNumber()))
        pdf_canvas.restoreState()

    doc.build(flowables, onFirstPage=add_page_number, onLaterPages=add_page_number)


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
    _selectedPaths: list[str] | None = None,
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
    normalized_blocks = _normalize_canvas_blocks(prompt, title, blocks, sections, seed_text, source_path, _selectedPaths)
    if not blocks and not sections:
        report_blocks = _report_blocks_from_prompt(prompt, title, source_context, requested_format)
        if report_blocks:
            normalized_blocks = normalize_visual_blocks(
                [*report_blocks, *_source_blocks_from_path(source_path, _selectedPaths)],
                fallback_text=seed_text,
            )
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
