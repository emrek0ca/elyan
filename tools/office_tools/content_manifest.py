"""Structured content manifests for office and research deliverables."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
import unicodedata
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse


def _normalize_text(value: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", raw).strip().lower()


def _clean_text(value: Any) -> str:
    raw = re.sub(r"\s+", " ", str(value or "")).strip()
    return raw


def _unique_strings(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in values or []:
        text = _clean_text(item)
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _domain_from_url(url: str) -> str:
    try:
        host = urlparse(str(url or "")).netloc.lower().strip()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _section_title(section: dict[str, Any], index: int) -> str:
    title = _clean_text(section.get("title") or "")
    return title or f"Bölüm {index}"


def _section_paragraphs(section: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for paragraph in list(section.get("paragraphs") or []):
        if isinstance(paragraph, dict):
            text = _clean_text(paragraph.get("text") or "")
            claim_ids = _unique_strings(paragraph.get("claim_ids") or [])
        else:
            text = _clean_text(paragraph)
            claim_ids = []
        if not text:
            continue
        rows.append({"text": text, "claim_ids": claim_ids})
    return rows


def _section_preview(paragraphs: list[dict[str, Any]], limit: int = 180) -> str:
    if not paragraphs:
        return ""
    text = " ".join(str(item.get("text") or "").strip() for item in paragraphs if str(item.get("text") or "").strip())
    text = _clean_text(text)
    return text[:limit]


def _section_claim_ids(paragraphs: list[dict[str, Any]]) -> list[str]:
    claim_ids: list[str] = []
    for paragraph in paragraphs:
        claim_ids.extend(list(paragraph.get("claim_ids") or []))
    return _unique_strings(claim_ids)


def _source_rows(sources: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, source in enumerate(list(sources or []), start=1):
        if not isinstance(source, dict):
            continue
        url = _clean_text(source.get("url") or "")
        title = _clean_text(source.get("title") or "") or url or f"Kaynak {index}"
        rows.append(
            {
                "No": index,
                "Baslik": title,
                "URL": url,
                "Alan": _domain_from_url(url),
                "Guvenilirlik": round(_coerce_float(source.get("reliability_score", 0.0)), 2),
                "Tur": _clean_text(source.get("source_type") or source.get("provider") or ""),
                "Alindi": bool(source.get("fetched", False)),
            }
        )
    return rows


def _claim_rows(research_contract: dict[str, Any] | None, claim_map: dict[str, Any] | None) -> list[dict[str, Any]]:
    contract = dict(research_contract or {})
    if not contract and isinstance(claim_map, dict):
        contract = dict(claim_map.get("research_contract") or {})
    claim_list = contract.get("claim_list") if isinstance(contract.get("claim_list"), list) else []
    citation_map = contract.get("citation_map") if isinstance(contract.get("citation_map"), dict) else {}
    section_map: dict[str, list[str]] = {}
    if isinstance(claim_map, dict):
        for section in list(claim_map.get("sections") or []):
            if not isinstance(section, dict):
                continue
            title = _clean_text(section.get("title") or "")
            for paragraph in list(section.get("paragraphs") or []):
                if not isinstance(paragraph, dict):
                    continue
                for claim_id in list(paragraph.get("claim_ids") or []):
                    cid = _clean_text(claim_id)
                    if not cid:
                        continue
                    section_map.setdefault(cid, [])
                    if title and title not in section_map[cid]:
                        section_map[cid].append(title)

    rows: list[dict[str, Any]] = []
    for claim in claim_list:
        if not isinstance(claim, dict):
            continue
        claim_id = _clean_text(claim.get("claim_id") or "")
        if not claim_id:
            continue
        source_urls = _unique_strings(claim.get("source_urls") or [])
        if not source_urls and isinstance(citation_map.get(claim_id), list):
            for row in citation_map.get(claim_id) or []:
                if isinstance(row, dict) and _clean_text(row.get("url") or ""):
                    source_urls.append(_clean_text(row.get("url") or ""))
        rows.append(
            {
                "ClaimID": claim_id,
                "Kritik": bool(claim.get("critical", False)),
                "Metin": _clean_text(claim.get("text") or ""),
                "KaynakSayisi": len(source_urls),
                "Guvenc": round(_coerce_float(claim.get("confidence", 0.0)), 2),
                "Kaynaklar": ", ".join(source_urls[:4]),
                "Bolumler": ", ".join(section_map.get(claim_id, [])[:4]),
            }
        )
    return rows


def _quality_rows(quality_summary: dict[str, Any] | None) -> list[dict[str, Any]]:
    summary = dict(quality_summary or {})
    if not summary:
        return []
    rows: list[dict[str, Any]] = []
    for key in (
        "status",
        "avg_reliability",
        "total_sources",
        "reliable_sources",
        "high_reliability",
        "medium_reliability",
        "low_reliability",
        "claim_count",
        "claim_coverage",
        "critical_claim_count",
        "critical_claim_coverage",
        "uncertainty_count",
        "conflict_count",
    ):
        if key not in summary:
            continue
        rows.append({"Metrik": key, "Deger": summary.get(key)})
    return rows


def _manifest_summary(
    *,
    title: str,
    topic: str,
    brief: str,
    audience: str,
    language: str,
    content_kind: str,
    document_profile: str,
    citation_mode: str,
    source_policy: str,
    sections: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    quality_summary: dict[str, Any],
    outputs: list[str],
    supporting_artifacts: list[str],
    notes: list[str],
) -> dict[str, Any]:
    paragraph_count = sum(len(section.get("paragraphs") or []) for section in sections)
    source_domains = _unique_strings(
        _domain_from_url(row.get("URL") or row.get("url") or "")
        for row in sources
        if isinstance(row, dict)
    )
    key_messages = []
    for section in sections[:4]:
        title_text = _clean_text(section.get("title") or "")
        if not title_text:
            continue
        key_messages.append(title_text)
    preview_lines = []
    for section in sections[:2]:
        title_text = _clean_text(section.get("title") or "")
        preview_text = _clean_text(section.get("preview") or "")
        if title_text and preview_text:
            preview_lines.append(f"{title_text}: {preview_text}")
        elif preview_text:
            preview_lines.append(preview_text)
        elif title_text:
            preview_lines.append(title_text)
    if not preview_lines and title:
        preview_lines.append(title)

    quality_contract = []
    kind = _clean_text(content_kind)
    if kind in {"research_delivery", "research"}:
        quality_contract = ["source_traceability", "claim_coverage", "critical_claim_coverage", "uncertainty_log"]
    elif kind in {"presentation", "pptx"}:
        quality_contract = ["slide_outline", "message_clarity", "source_traceability"]
    elif kind in {"spreadsheet", "xlsx"}:
        quality_contract = ["sheet_integrity", "table_structure", "source_traceability"]
    elif kind in {"document_pack", "document"}:
        quality_contract = ["section_structure", "language_quality", "traceability"]
    else:
        quality_contract = ["artifact_traceability"]

    return {
        "title": title,
        "topic": topic,
        "brief": brief,
        "audience": audience,
        "language": language,
        "content_kind": content_kind,
        "document_profile": document_profile,
        "citation_mode": citation_mode,
        "source_policy": source_policy,
        "section_count": len(sections),
        "paragraph_count": paragraph_count,
        "source_count": len(sources),
        "claim_count": int(_coerce_float(quality_summary.get("claim_count", 0), 0)),
        "quality_status": _clean_text(quality_summary.get("status") or ""),
        "claim_coverage": round(_coerce_float(quality_summary.get("claim_coverage", 0.0)), 2),
        "critical_claim_coverage": round(_coerce_float(quality_summary.get("critical_claim_coverage", 0.0)), 2),
        "uncertainty_count": int(_coerce_float(quality_summary.get("uncertainty_count", 0), 0)),
        "conflict_count": int(_coerce_float(quality_summary.get("conflict_count", 0), 0)),
        "source_domains": source_domains,
        "key_sections": key_messages,
        "preview": " | ".join(preview_lines[:3]),
        "quality_contract": quality_contract,
        "outputs": outputs,
        "supporting_artifacts": supporting_artifacts,
        "notes": notes,
    }


@dataclass
class OfficeContentManifest:
    title: str
    topic: str = ""
    brief: str = ""
    audience: str = "executive"
    language: str = "tr"
    content_kind: str = "document"
    document_profile: str = "executive"
    citation_mode: str = "none"
    source_policy: str = "trusted"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    sections: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    quality_summary: dict[str, Any] = field(default_factory=dict)
    claim_map: dict[str, Any] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)
    supporting_artifacts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "topic": self.topic,
            "brief": self.brief,
            "audience": self.audience,
            "language": self.language,
            "content_kind": self.content_kind,
            "document_profile": self.document_profile,
            "citation_mode": self.citation_mode,
            "source_policy": self.source_policy,
            "created_at": self.created_at,
            "sections": list(self.sections or []),
            "sources": list(self.sources or []),
            "quality_summary": dict(self.quality_summary or {}),
            "claim_map": dict(self.claim_map or {}),
            "outputs": list(self.outputs or []),
            "supporting_artifacts": list(self.supporting_artifacts or []),
            "notes": list(self.notes or []),
            "metadata": dict(self.metadata or {}),
            "summary": dict(self.summary or {}),
        }


def build_office_content_manifest(
    *,
    title: str,
    topic: str = "",
    brief: str = "",
    audience: str = "executive",
    language: str = "tr",
    content_kind: str = "document",
    document_profile: str = "executive",
    citation_mode: str = "none",
    source_policy: str = "trusted",
    sections: Sequence[dict[str, Any]] | None = None,
    sources: Sequence[dict[str, Any]] | None = None,
    quality_summary: dict[str, Any] | None = None,
    research_contract: dict[str, Any] | None = None,
    claim_map: dict[str, Any] | None = None,
    outputs: Sequence[str] | None = None,
    supporting_artifacts: Sequence[str] | None = None,
    notes: Sequence[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> OfficeContentManifest:
    normalized_sections: list[dict[str, Any]] = []
    for index, section in enumerate(list(sections or []), start=1):
        if not isinstance(section, dict):
            continue
        paragraphs = _section_paragraphs(section)
        if not paragraphs:
            continue
        normalized_sections.append(
            {
                "index": index,
                "title": _section_title(section, index),
                "paragraphs": paragraphs,
                "paragraph_count": len(paragraphs),
                "claim_ids": _section_claim_ids(paragraphs),
                "preview": _section_preview(paragraphs),
            }
        )

    normalized_sources = _source_rows(list(sources or []))
    quality = dict(quality_summary or {})
    manifest_claim_map = dict(claim_map or {})
    if research_contract and not manifest_claim_map:
        manifest_claim_map = {"research_contract": dict(research_contract or {})}

    manifest_outputs = _unique_strings(outputs or [])
    manifest_supporting = _unique_strings(supporting_artifacts or [])
    manifest_notes = _unique_strings(notes or [])
    summary = _manifest_summary(
        title=_clean_text(title),
        topic=_clean_text(topic),
        brief=_clean_text(brief),
        audience=_clean_text(audience) or "executive",
        language=_clean_text(language) or "tr",
        content_kind=_clean_text(content_kind) or "document",
        document_profile=_clean_text(document_profile) or "executive",
        citation_mode=_clean_text(citation_mode) or "none",
        source_policy=_clean_text(source_policy) or "trusted",
        sections=normalized_sections,
        sources=normalized_sources,
        quality_summary=quality,
        outputs=manifest_outputs,
        supporting_artifacts=manifest_supporting,
        notes=manifest_notes,
    )
    if metadata:
        summary["metadata"] = dict(metadata)

    return OfficeContentManifest(
        title=_clean_text(title),
        topic=_clean_text(topic),
        brief=_clean_text(brief),
        audience=_clean_text(audience) or "executive",
        language=_clean_text(language) or "tr",
        content_kind=_clean_text(content_kind) or "document",
        document_profile=_clean_text(document_profile) or "executive",
        citation_mode=_clean_text(citation_mode) or "none",
        source_policy=_clean_text(source_policy) or "trusted",
        sections=normalized_sections,
        sources=normalized_sources,
        quality_summary=quality,
        claim_map=manifest_claim_map,
        outputs=manifest_outputs,
        supporting_artifacts=manifest_supporting,
        notes=manifest_notes,
        metadata=dict(metadata or {}),
        summary=summary,
    )


def manifest_to_excel_payload(manifest: dict[str, Any] | OfficeContentManifest) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    payload = manifest.to_dict() if isinstance(manifest, OfficeContentManifest) else dict(manifest or {})
    summary = dict(payload.get("summary") or {})
    sections = list(payload.get("sections") or [])
    sources = list(payload.get("sources") or [])
    quality_summary = dict(payload.get("quality_summary") or {})
    claim_map = dict(payload.get("claim_map") or {})
    research_contract = dict(claim_map.get("research_contract") or {}) if isinstance(claim_map, dict) else {}

    overview_rows = [
        {"Alan": "Baslik", "Deger": payload.get("title") or ""},
        {"Alan": "Konu", "Deger": payload.get("topic") or ""},
        {"Alan": "Kısa Açıklama", "Deger": payload.get("brief") or ""},
        {"Alan": "Kitle", "Deger": payload.get("audience") or ""},
        {"Alan": "Dil", "Deger": payload.get("language") or ""},
        {"Alan": "Profil", "Deger": payload.get("document_profile") or ""},
        {"Alan": "Atif Modu", "Deger": payload.get("citation_mode") or ""},
        {"Alan": "Kaynak Politikasi", "Deger": payload.get("source_policy") or ""},
        {"Alan": "Bölüm Sayısı", "Deger": summary.get("section_count", len(sections))},
        {"Alan": "Paragraf Sayısı", "Deger": summary.get("paragraph_count", sum(len(section.get("paragraphs") or []) for section in sections))},
        {"Alan": "Kaynak Sayısı", "Deger": summary.get("source_count", len(sources))},
        {"Alan": "İddia Sayısı", "Deger": summary.get("claim_count", quality_summary.get("claim_count", 0))},
        {"Alan": "Kalite Durumu", "Deger": summary.get("quality_status") or quality_summary.get("status") or ""},
        {"Alan": "Claim Coverage", "Deger": summary.get("claim_coverage", quality_summary.get("claim_coverage", 0.0))},
        {"Alan": "Kritik Claim Coverage", "Deger": summary.get("critical_claim_coverage", quality_summary.get("critical_claim_coverage", 0.0))},
        {"Alan": "Belirsizlik", "Deger": summary.get("uncertainty_count", quality_summary.get("uncertainty_count", 0))},
        {"Alan": "Çelişki", "Deger": summary.get("conflict_count", quality_summary.get("conflict_count", 0))},
        {"Alan": "Önizleme", "Deger": summary.get("preview") or ""},
        {"Alan": "Çıktılar", "Deger": ", ".join(_unique_strings(payload.get("outputs") or []))},
    ]

    section_rows = [
        {
            "No": section.get("index", idx),
            "Bolum": section.get("title") or "",
            "Paragraf Sayisi": section.get("paragraph_count", len(section.get("paragraphs") or [])),
            "Claim Sayisi": len(section.get("claim_ids") or []),
            "Claim ID'leri": ", ".join(list(section.get("claim_ids") or [])[:8]),
            "On Izleme": section.get("preview") or "",
        }
        for idx, section in enumerate(sections, start=1)
    ]

    source_rows = [
        {
            "No": row.get("No"),
            "Baslik": row.get("Baslik") or "",
            "URL": row.get("URL") or "",
            "Alan": row.get("Alan") or "",
            "Guvenilirlik": row.get("Guvenilirlik", 0.0),
            "Tur": row.get("Tur") or "",
            "Alindi": row.get("Alindi", False),
        }
        for row in sources
    ]

    quality_rows = _quality_rows(quality_summary)

    claim_rows = _claim_rows(research_contract, claim_map)

    outputs_rows = [{"Alan": "Çıktı", "Deger": item} for item in _unique_strings(payload.get("outputs") or [])]
    artifact_rows = [{"Alan": "Destek", "Deger": item} for item in _unique_strings(payload.get("supporting_artifacts") or [])]
    note_rows = [{"Alan": "Not", "Deger": item} for item in _unique_strings(payload.get("notes") or [])]
    preview_rows = []
    if summary.get("preview"):
        preview_rows.append({"Alan": "Önizleme", "Deger": summary.get("preview")})
    if summary.get("quality_contract"):
        preview_rows.append({"Alan": "Kalite Sözleşmesi", "Deger": ", ".join(str(item) for item in list(summary.get("quality_contract") or [])[:6])})

    data = {
        "Ozet": overview_rows,
        "Bolumler": section_rows or [{"No": 1, "Bolum": "İçerik", "Paragraf Sayisi": 0, "Claim Sayisi": 0, "Claim ID'leri": "", "On Izleme": ""}],
        "Kaynaklar": source_rows or [{"No": 1, "Baslik": "", "URL": "", "Alan": "", "Guvenilirlik": 0.0, "Tur": "", "Alindi": False}],
        "Kalite": quality_rows or [{"Metrik": "status", "Deger": quality_summary.get("status") or ""}],
    }
    headers = {
        "Ozet": ["Alan", "Deger"],
        "Bolumler": ["No", "Bolum", "Paragraf Sayisi", "Claim Sayisi", "Claim ID'leri", "On Izleme"],
        "Kaynaklar": ["No", "Baslik", "URL", "Alan", "Guvenilirlik", "Tur", "Alindi"],
        "Kalite": ["Metrik", "Deger"],
    }
    if claim_rows:
        data["IddiaHaritasi"] = claim_rows
        headers["IddiaHaritasi"] = ["ClaimID", "Kritik", "Metin", "KaynakSayisi", "Guvenc", "Kaynaklar", "Bolumler"]
    if outputs_rows:
        data["Ciktilar"] = outputs_rows
        headers["Ciktilar"] = ["Alan", "Deger"]
    if artifact_rows:
        data["Destek"] = artifact_rows
        headers["Destek"] = ["Alan", "Deger"]
    if note_rows:
        data["Notlar"] = note_rows
        headers["Notlar"] = ["Alan", "Deger"]
    if preview_rows:
        data["OnIzleme"] = preview_rows
        headers["OnIzleme"] = ["Alan", "Deger"]
    return data, headers


def manifest_to_presentation_sections(manifest: dict[str, Any] | OfficeContentManifest, *, max_sections: int = 5) -> list[dict[str, Any]]:
    payload = manifest.to_dict() if isinstance(manifest, OfficeContentManifest) else dict(manifest or {})
    summary = dict(payload.get("summary") or {})
    sections = list(payload.get("sections") or [])
    sources = list(payload.get("sources") or [])
    quality_summary = dict(payload.get("quality_summary") or {})
    outputs = _unique_strings(payload.get("outputs") or [])
    notes = _unique_strings(payload.get("notes") or [])

    deck_sections: list[dict[str, Any]] = []

    overview_rows = [
        f"Konu: {payload.get('topic') or payload.get('title') or ''}",
        f"Kitle: {payload.get('audience') or 'executive'}",
        f"Profil: {payload.get('document_profile') or 'executive'}",
    ]
    if payload.get("brief"):
        overview_rows.append(f"Odak: {payload.get('brief')}")
    if summary.get("quality_status") or quality_summary.get("status"):
        overview_rows.append(
            f"Kalite durumu: {summary.get('quality_status') or quality_summary.get('status') or 'unknown'}"
        )
    if outputs:
        overview_rows.append(f"Çıktılar: {', '.join(outputs[:4])}")
    if summary.get("preview"):
        overview_rows.append(f"Önizleme: {summary.get('preview')}")
    deck_sections.append(
        {
            "title": "Yönetici Özeti",
            "paragraphs": [{"text": row, "claim_ids": []} for row in overview_rows if row.strip()],
        }
    )

    finding_rows: list[dict[str, Any]] = []
    for section in sections[:max_sections]:
        title = _clean_text(section.get("title") or "")
        paragraphs = list(section.get("paragraphs") or [])
        preview = _section_preview(paragraphs, limit=220)
        if not title and not preview:
            continue
        line = preview or ", ".join(str(item.get("text") or "") for item in paragraphs[:2] if str(item.get("text") or "").strip())
        if title and line:
            text = f"{title}: {line}"
        else:
            text = title or line
        finding_rows.append({"text": text, "claim_ids": list(section.get("claim_ids") or [])})
    if finding_rows:
        deck_sections.append({"title": "Temel Bulgular", "paragraphs": finding_rows})

    quality_rows = []
    for key in ("claim_coverage", "critical_claim_coverage", "uncertainty_count", "conflict_count", "avg_reliability"):
        if key in quality_summary:
            quality_rows.append({"text": f"{key}: {quality_summary.get(key)}", "claim_ids": []})
    if summary.get("quality_contract"):
        quality_rows.append(
            {
                "text": "Kalite sözleşmesi: " + ", ".join(str(item) for item in list(summary.get("quality_contract") or [])[:4]),
                "claim_ids": [],
            }
        )
    if quality_rows:
        deck_sections.append({"title": "Kalite ve Risk", "paragraphs": quality_rows})

    source_rows = []
    for row in sources[:6]:
        title = _clean_text(row.get("Baslik") or row.get("title") or "")
        url = _clean_text(row.get("URL") or row.get("url") or "")
        domain = _clean_text(row.get("Alan") or row.get("domain") or _domain_from_url(url))
        rel = row.get("Guvenilirlik")
        rel_text = f"{_coerce_float(rel, 0.0):.2f}" if rel is not None else ""
        line = " - ".join(part for part in [title or url, url if url and url != title else "", domain, rel_text] if part)
        if line:
            source_rows.append({"text": line, "claim_ids": []})
    if source_rows:
        deck_sections.append({"title": "Kaynaklar", "paragraphs": source_rows})

    if notes:
        deck_sections.append({"title": "Notlar", "paragraphs": [{"text": note, "claim_ids": []} for note in notes[:4]]})

    return deck_sections


def manifest_to_slide_markdown(manifest: dict[str, Any] | OfficeContentManifest) -> str:
    payload = manifest.to_dict() if isinstance(manifest, OfficeContentManifest) else dict(manifest or {})
    title = _clean_text(payload.get("title") or payload.get("topic") or "Elyan Sunum")
    summary = dict(payload.get("summary") or {})
    sections = manifest_to_presentation_sections(payload)
    slides: list[str] = []

    cover_lines = []
    if payload.get("topic"):
        cover_lines.append(f"**Konu:** {payload.get('topic')}")
    if payload.get("audience"):
        cover_lines.append(f"**Kitle:** {payload.get('audience')}")
    if payload.get("document_profile"):
        cover_lines.append(f"**Profil:** {payload.get('document_profile')}")
    if summary.get("quality_status"):
        cover_lines.append(f"**Kalite:** {summary.get('quality_status')}")
    if summary.get("preview"):
        cover_lines.append(f"**Önizleme:** {summary.get('preview')}")
    if payload.get("brief"):
        cover_lines.append(str(payload.get("brief")))
    slides.append(f"# {title}\n\n" + "\n\n".join(cover_lines).strip())

    for section in sections:
        section_title = _clean_text(section.get("title") or "")
        if not section_title:
            continue
        lines = []
        for paragraph in list(section.get("paragraphs") or []):
            text = _clean_text(paragraph.get("text") or "")
            if text:
                lines.append(f"- {text}")
        if not lines:
            continue
        slides.append(f"## {section_title}\n\n" + "\n".join(lines))

    return "\n\n---\n\n".join(slides).strip() + "\n"


__all__ = [
    "OfficeContentManifest",
    "build_office_content_manifest",
    "manifest_to_excel_payload",
    "manifest_to_presentation_sections",
    "manifest_to_slide_markdown",
]
