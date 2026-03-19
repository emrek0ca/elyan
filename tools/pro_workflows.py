"""
Professional workflow tools for higher-level assistant capabilities.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import unicodedata
from urllib.parse import urlparse

from security.validator import validate_path
from tools.document_tools.output_renderer import DocumentRenderer, sections_to_sectioned_document
from tools.office_tools.content_manifest import build_office_content_manifest
from utils.logger import get_logger

logger = get_logger("tools.pro_workflows")


def _safe_project_slug(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", " ") else " " for ch in str(name or "elyan-project"))
    cleaned = "_".join(cleaned.strip().split())
    return cleaned[:80] or "elyan-project"


def _wants_counter_feature(brief: str) -> bool:
    low = str(brief or "").lower()
    if not low:
        return False
    counter_tokens = ("sayac", "sayaç", "counter")
    button_tokens = ("buton", "button", "btn")
    return any(t in low for t in counter_tokens) and any(t in low for t in button_tokens)


def _escape_html(text: str) -> str:
    s = str(text or "")
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _brief_excerpt(brief: str, *, fallback: str) -> str:
    raw = " ".join(str(brief or "").split()).strip()
    if not raw:
        return fallback
    return raw[:220]


def _normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower()


def _clean_research_sentence(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    value = value.lstrip("•- ").strip()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"(?<=[a-zçğıöşü])(?=[A-ZÇĞİÖŞÜ])", " ", value)
    value = re.sub(r"(?<=[A-Za-zÇĞİÖŞÜçğıöşü])(?=\()", " ", value)
    value = re.sub(r"\s+([,.;:!?])", r"\1", value)
    return value.strip()


def _strip_research_annotation(text: str) -> str:
    value = _clean_research_sentence(text)
    if not value:
        return ""
    value = re.sub(r"\s*\((?:Kaynak|Güven|Guven):[^)]*\)\s*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*\(Kaynak:[^)]*\)\s*$", "", value, flags=re.IGNORECASE)
    return value.strip(" -")


def _strip_research_meta_lines(text: str) -> str:
    if not text:
        return ""
    blocked_patterns = (
        r"^\s*Yönetici Özeti:?\s*$",
        r"^\s*Kısa Özet:?\s*$",
        r"^\s*Ana Bulgular.*$",
        r"^\s*Kanıt Matrisi.*$",
        r"^\s*Araştırma Konusu:.*$",
        r"^\s*Kapsam:.*$",
        r"^\s*Kaynak Profili:.*$",
        r"^\s*Kaynak Politikası:.*$",
        r"^\s*Önerilen referans seti:.*$",
        r"^\s*Not:.*$",
        r"^\s*Öne Çıkan Alan Adları:.*$",
        r"^\s*Operasyonel Öneriler:.*$",
        r"^\s*Sınırlılıklar:.*$",
        r"^\s*Önerilen Devam Adımı:.*$",
    )
    kept: list[str] = []
    for raw in str(text or "").splitlines():
        line = _clean_research_sentence(raw)
        if not line:
            continue
        if any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in blocked_patterns):
            continue
        low = _normalize_text(line)
        if any(token in low for token in ("guvenilirlik", "kaynak orani", "kaynak incelendi", "ortalama guven")):
            continue
        kept.append(line)
    return "\n\n".join(kept).strip()


def _is_low_value_research_statement(text: str) -> bool:
    line = _clean_research_sentence(text)
    if not line:
        return True
    low = _normalize_text(line)
    if len(line) < 60:
        return True
    blocked_tokens = (
        "youtube",
        "video",
        "videosudur",
        "bu ders",
        "buders",
        "guncelleme tarihi",
        "güncelleme tarihi",
        " yazar ",
        "author ",
        "referans seti",
        "ornek soru",
        "örnek soru",
        "sekil",
        "şekil",
        "denklem 1",
        "denklem 2",
        "denklem 3",
        "sx (f)",
        "sx(f)",
        "guven:",
        "kaynak:",
        "kanit matrisi",
    )
    if any(token in low for token in blocked_tokens):
        return True
    if re.search(r"\b\d+\s*ve\s*\d+\b", low) and "denklem" in low:
        return True
    if re.search(r"[A-Za-z]\([A-Za-z]", line):
        return True
    return False


def _domain_from_url(url: str) -> str:
    try:
        host = urlparse(str(url or "")).netloc.lower().strip()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _is_low_value_source(url: str) -> bool:
    low = _normalize_text(url)
    blocked = (
        "youtube.com",
        "youtu.be",
        "instagram.com",
        "tiktok.com",
        "x.com",
        "twitter.com",
        "facebook.com",
        "reddit.com",
        "blogspot.",
        "wordpress.",
    )
    return any(token in low for token in blocked)


def _select_research_sources_for_document(
    sources: list[dict[str, Any]],
    *,
    min_rel: float,
    source_policy: str = "trusted",
    limit: int = 6,
) -> list[dict[str, Any]]:
    ranked: list[tuple[float, dict[str, Any]]] = []
    policy = _normalize_text(source_policy or "trusted")
    for src in list(sources or []):
        if not isinstance(src, dict):
            continue
        url = str(src.get("url") or "").strip()
        if not url or _is_low_value_source(url):
            continue
        domain = _domain_from_url(url)
        if policy == "official":
            is_official = any(
                token in domain
                for token in (
                    ".gov",
                    "europa.eu",
                    "ec.europa.eu",
                    "eurostat.ec.europa.eu",
                    "tuik.gov.tr",
                    "tcmb.gov.tr",
                    "hmb.gov.tr",
                    "sbb.gov.tr",
                    "worldbank.org",
                    "oecd.org",
                    "imf.org",
                )
            )
            if not is_official:
                continue
        try:
            rel = float(src.get("reliability_score", 0.0) or 0.0)
        except Exception:
            rel = 0.0
        if rel < min_rel:
            continue
        bonus = 0.0
        if domain.endswith((".edu", ".gov", ".org", ".ac.tr")):
            bonus += 0.2
        if any(token in domain for token in ("wikipedia.org", "springer", "sciencedirect", "nature", "ankara.edu.tr", "gibtu.edu.tr")):
            bonus += 0.15
        ranked.append((rel + bonus, src))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [dict(item[1]) for item in ranked[:limit]]


def _normalize_document_profile(profile: str, audience: str = "executive") -> str:
    raw = _normalize_text(profile or audience or "executive")
    if raw in {"analytical", "analysis", "academic"}:
        return "analytical"
    if raw in {"briefing", "brief", "operator"}:
        return "briefing"
    return "executive"


def _normalize_citation_mode(citation_mode: str, *, citation_style: str = "", include_bibliography: bool = False) -> str:
    raw = _normalize_text(citation_mode)
    if raw in {"none", "inline", "bibliography"}:
        return raw
    style = _normalize_text(citation_style)
    if style and style != "none":
        return "inline"
    if include_bibliography:
        return "inline"
    return "none"


def _quality_summary_from_research_payload(
    *,
    research_contract: dict[str, Any],
    sources: list[dict[str, Any]],
    findings: list[str],
    source_policy: str,
    min_reliability: float,
) -> dict[str, Any]:
    claim_list = research_contract.get("claim_list") if isinstance(research_contract, dict) else []
    critical_ids = set(research_contract.get("critical_claim_ids") or []) if isinstance(research_contract, dict) else set()
    conflicts = research_contract.get("conflicts") if isinstance(research_contract, dict) else []
    uncertainty_log = research_contract.get("uncertainty_log") if isinstance(research_contract, dict) else []
    reliability_scores: list[float] = []
    top_domains: list[str] = []
    seen_domains: set[str] = set()
    reliable_sources = 0
    high = 0
    medium = 0
    for src in list(sources or []):
        if not isinstance(src, dict):
            continue
        try:
            rel = float(src.get("reliability_score", 0.0) or 0.0)
        except Exception:
            rel = 0.0
        reliability_scores.append(rel)
        if rel >= 0.6:
            reliable_sources += 1
        if rel >= 0.8:
            high += 1
        elif rel >= 0.6:
            medium += 1
        domain = _domain_from_url(str(src.get("url") or ""))
        if domain and domain not in seen_domains and len(top_domains) < 5:
            seen_domains.add(domain)
            top_domains.append(domain)

    claim_count = 0
    covered_claims = 0
    critical_count = 0
    critical_supported = 0
    for claim in claim_list or []:
        if not isinstance(claim, dict):
            continue
        claim_count += 1
        source_urls = [str(url).strip() for url in (claim.get("source_urls") or []) if str(url).strip()]
        if source_urls:
            covered_claims += 1
        claim_id = str(claim.get("claim_id") or "").strip()
        if bool(claim.get("critical")) or claim_id in critical_ids:
            critical_count += 1
            if len(set(source_urls)) >= 2:
                critical_supported += 1

    claim_coverage = covered_claims / max(claim_count, 1) if claim_count else 0.0
    critical_claim_coverage = critical_supported / max(critical_count, 1) if critical_count else 1.0
    uncertainty_count = len([item for item in (uncertainty_log or []) if str(item).strip()]) + len(conflicts or [])
    avg_reliability = sum(reliability_scores) / len(reliability_scores) if reliability_scores else 0.0
    total_sources = len(reliability_scores)
    status = "pass"
    if claim_count == 0 or claim_coverage <= 0.0:
        status = "fail"
    elif critical_claim_coverage < 1.0 or uncertainty_count > 0:
        status = "partial"

    return {
        "avg_reliability": avg_reliability,
        "min_reliability_threshold": float(min_reliability or 0.0),
        "source_policy": str(source_policy or "trusted"),
        "total_sources": total_sources,
        "reliable_sources": reliable_sources,
        "reliability_pct": int((reliable_sources / total_sources) * 100) if total_sources else 0,
        "high_reliability": high,
        "medium_reliability": medium,
        "low_reliability": max(0, total_sources - high - medium),
        "finding_count": len(findings or []),
        "top_domains": top_domains,
        "claim_count": claim_count,
        "claim_coverage": round(claim_coverage, 2),
        "critical_claim_count": critical_count,
        "critical_claim_coverage": round(critical_claim_coverage, 2),
        "uncertainty_count": uncertainty_count,
        "conflict_count": len(conflicts or []),
        "status": status,
    }


def _claim_reference_label(claim_id: str, citations: list[dict[str, Any]], citation_mode: str) -> str:
    clean_mode = _normalize_citation_mode(citation_mode)
    if clean_mode == "none":
        return ""
    domains: list[str] = []
    for row in list(citations or []):
        if not isinstance(row, dict):
            continue
        domain = _domain_from_url(str(row.get("url") or ""))
        title = _clean_research_sentence(str(row.get("title") or "").strip())
        label = domain or title or str(row.get("url") or "").strip()
        if label and label not in domains:
            domains.append(label)
    if not domains:
        return ""
    if clean_mode == "bibliography":
        return f"[{claim_id}]"
    return f" [Kaynak: {', '.join(domains[:2])}]"


def _build_research_document_sections(
    *,
    topic: str,
    brief: str,
    profile: str,
    citation_mode: str,
    summary: str,
    findings: list[str],
    research_contract: dict[str, Any],
    quality_summary: dict[str, Any],
    include_bibliography: bool,
) -> list[dict[str, Any]]:
    normalized_profile = _normalize_document_profile(profile)
    clean_summary = _strip_research_meta_lines(_extract_report_summary(summary, findings, topic))
    if not clean_summary:
        clean_summary = f"{topic} konusu, güvenilir kaynaklardan derlenen doğrulanmış iddialar üzerinden özetlenmiştir."

    claim_list = research_contract.get("claim_list") if isinstance(research_contract, dict) else []
    citation_map = research_contract.get("citation_map") if isinstance(research_contract, dict) else {}
    conflicts = research_contract.get("conflicts") if isinstance(research_contract, dict) else []
    uncertainty_log = research_contract.get("uncertainty_log") if isinstance(research_contract, dict) else []

    overview_tail = {
        "executive": "Metin, karar vermeyi kolaylaştıracak netlikte ve kısa tutulmuştur.",
        "analytical": "Metin, iddiaların kaynağını ve güven düzeyini görünür tutacak şekilde biraz daha ayrıntılı düzenlenmiştir.",
        "briefing": "Metin, hızlı durum değerlendirmesi için kısa ve yönlendirici kalacak şekilde sıkıştırılmıştır.",
    }
    sections: list[dict[str, Any]] = [
        {
            "title": "Kısa Özet",
            "paragraphs": [
                {
                    "text": clean_summary,
                    "claim_ids": [str(item.get("claim_id") or "") for item in (claim_list or [])[: max(1, min(2, len(claim_list or [])))] if str(item.get("claim_id") or "").strip()],
                },
                {
                    "text": overview_tail[normalized_profile],
                    "claim_ids": [],
                },
            ],
        }
    ]

    finding_paragraphs: list[dict[str, Any]] = []
    for claim in list(claim_list or []):
        if not isinstance(claim, dict):
            continue
        claim_id = str(claim.get("claim_id") or "").strip()
        text = _strip_research_annotation(str(claim.get("text") or "").strip())
        if not text:
            continue
        citation_note = _claim_reference_label(claim_id, citation_map.get(claim_id, []), citation_mode)
        finding_paragraphs.append(
            {
                "text": f"{text}{citation_note}".strip(),
                "claim_ids": [claim_id] if claim_id else [],
            }
        )
    if not finding_paragraphs:
        for idx, finding in enumerate(_select_research_document_findings(findings, topic=topic, limit=6), start=1):
            clean = _strip_research_annotation(finding)
            if clean:
                finding_paragraphs.append({"text": clean, "claim_ids": [f"claim_{idx}"]})
    sections.append({"title": "Temel Bulgular", "paragraphs": finding_paragraphs or [{"text": "Doğrudan bağlanabilir bulgu üretilemedi.", "claim_ids": []}]})

    quality_lines = [
        (
            f"Toplam {int(quality_summary.get('total_sources', 0) or 0)} kaynak tarandı; "
            f"ortalama güvenilirlik {float(quality_summary.get('avg_reliability', 0.0) or 0.0):.2f} olarak hesaplandı."
        ),
        (
            f"Claim coverage {float(quality_summary.get('claim_coverage', 0.0) or 0.0):.2f}, "
            f"kritik claim coverage {float(quality_summary.get('critical_claim_coverage', 0.0) or 0.0):.2f} seviyesinde."
        ),
    ]
    sections.append({"title": "Kaynak Güven Özeti", "paragraphs": [{"text": row, "claim_ids": []} for row in quality_lines]})

    risk_paragraphs: list[dict[str, Any]] = []
    if conflicts:
        for conflict in conflicts[:4]:
            detail = _clean_research_sentence(str(conflict.get("detail") or "").strip())
            if detail:
                risk_paragraphs.append({"text": detail, "claim_ids": [str(item) for item in (conflict.get("claim_ids") or []) if str(item).strip()]})
    if float(quality_summary.get("critical_claim_coverage", 0.0) or 0.0) < 1.0:
        risk_paragraphs.append(
            {
                "text": "Bazı kritik iddialar ikinci bağımsız kaynakla doğrulanamadı; sonuçlar dikkatle kullanılmalıdır.",
                "claim_ids": list(research_contract.get("critical_claim_ids") or []),
            }
        )
    if not risk_paragraphs:
        risk_paragraphs.append({"text": "Belirgin çelişki bulunmadı; yine de kritik sayısal ifadeler manuel teyit gerektirebilir.", "claim_ids": []})
    sections.append({"title": "Açık Riskler", "paragraphs": risk_paragraphs})

    uncertainty_paragraphs: list[dict[str, Any]] = []
    for item in uncertainty_log[:6]:
        clean = _clean_research_sentence(str(item or "").strip())
        if clean:
            match = re.search(r"(claim_\d+)", clean)
            display = re.sub(r"^\s*claim_\d+\s*:\s*", "", clean, flags=re.IGNORECASE).strip()
            uncertainty_paragraphs.append({"text": display or clean, "claim_ids": [match.group(1)] if match else []})
    if not uncertainty_paragraphs:
        uncertainty_paragraphs.append({"text": "Belirgin belirsizlik kaydı oluşmadı; bu bölüm izlenebilirlik için korunur.", "claim_ids": []})
    sections.append({"title": "Belirsizlikler", "paragraphs": uncertainty_paragraphs})

    if include_bibliography:
        bibliography_rows: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for claim_id, citations in list((citation_map or {}).items())[:12]:
            for row in list(citations or []):
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or "").strip()
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                title = _clean_research_sentence(str(row.get("title") or "").strip()) or url
                bibliography_rows.append({"text": f"[{claim_id}] {title} - {url}", "claim_ids": [claim_id]})
        if bibliography_rows:
            sections.append({"title": "Kaynakça", "paragraphs": bibliography_rows})

    return sections


def _is_generic_document_paragraph(text: str) -> bool:
    clean = _clean_research_sentence(text)
    if not clean:
        return True
    low = _normalize_text(clean)
    generic_prefixes = (
        "toplam ",
        "claim coverage ",
        "kritik claim coverage ",
    )
    generic_exact = {
        _normalize_text("Metin, karar vermeyi kolaylaştıracak netlikte ve kısa tutulmuştur."),
        _normalize_text("Metin, iddiaların kaynağını ve güven düzeyini görünür tutacak şekilde biraz daha ayrıntılı düzenlenmiştir."),
        _normalize_text("Metin, hızlı durum değerlendirmesi için kısa ve yönlendirici kalacak şekilde sıkıştırılmıştır."),
        _normalize_text("Doğrudan bağlanabilir bulgu üretilemedi."),
        _normalize_text("Belirgin çelişki bulunmadı; yine de kritik sayısal ifadeler manuel teyit gerektirebilir."),
        _normalize_text("Belirgin belirsizlik kaydı oluşmadı; bu bölüm izlenebilirlik için korunur."),
        _normalize_text("Bazı kritik iddialar ikinci bağımsız kaynakla doğrulanamadı; sonuçlar dikkatle kullanılmalıdır."),
    }
    if low in generic_exact:
        return True
    if any(low.startswith(prefix) for prefix in generic_prefixes):
        return True
    return False


def _renderable_research_document_sections(
    *,
    sections: list[dict[str, Any]],
    profile: str,
    brief: str,
    include_bibliography: bool,
) -> list[dict[str, Any]]:
    normalized_profile = _normalize_document_profile(profile)
    low_brief = _normalize_text(brief)
    explicit_detail = any(
        marker in low_brief
        for marker in (
            "risk",
            "uyari",
            "uyarı",
            "belirsizlik",
            "kaynakca",
            "kaynakça",
            "citation",
            "atif",
            "atıf",
            "analitik",
            "analytical",
        )
    )
    preferred_titles = {"Kısa Özet", "Temel Bulgular"}
    preferred_titles.update({"Kaynak Güven Özeti", "Açık Riskler", "Belirsizlikler"})
    if normalized_profile == "briefing" and ("risk" in low_brief or "uyari" in low_brief or "uyarı" in low_brief):
        preferred_titles.add("Açık Riskler")
    if include_bibliography and (normalized_profile == "analytical" or explicit_detail):
        preferred_titles.add("Kaynakça")

    render_sections: list[dict[str, Any]] = []
    for section in list(sections or []):
        if not isinstance(section, dict):
            continue
        title = _clean_research_sentence(str(section.get("title") or "").strip())
        if not title or title not in preferred_titles:
            continue
        allow_generic_paragraphs = title in {"Kaynak Güven Özeti", "Açık Riskler", "Belirsizlikler"}
        paragraphs: list[dict[str, Any]] = []
        for paragraph in list(section.get("paragraphs") or []):
            if isinstance(paragraph, dict):
                text = _clean_research_sentence(str(paragraph.get("text") or "").strip())
                claim_ids = [str(item).strip() for item in list(paragraph.get("claim_ids") or []) if str(item).strip()]
            else:
                text = _clean_research_sentence(str(paragraph or "").strip())
                claim_ids = []
            if not text:
                continue
            if not allow_generic_paragraphs and _is_generic_document_paragraph(text):
                continue
            paragraphs.append({"text": text, "claim_ids": claim_ids})
        if paragraphs:
            render_sections.append({"title": title, "paragraphs": paragraphs})

    if not render_sections:
        fallback_texts: list[str] = []
        for section in list(sections or []):
            if not isinstance(section, dict):
                continue
            for paragraph in list(section.get("paragraphs") or []):
                text = _clean_research_sentence(str((paragraph.get("text") if isinstance(paragraph, dict) else paragraph) or "").strip())
                if text and not _is_generic_document_paragraph(text):
                    fallback_texts.append(text)
        if fallback_texts:
            render_sections = [
                {
                    "title": "İçerik",
                    "paragraphs": [{"text": text, "claim_ids": []} for text in fallback_texts[:8]],
                }
            ]

    return render_sections


def _content_only_research_sections(
    *,
    topic: str,
    summary: str,
    findings: list[str],
    llm_body: str = "",
) -> list[dict[str, Any]]:
    paragraphs: list[str] = []

    if llm_body and _research_body_seems_relevant(topic, llm_body):
        paragraphs.extend(_extract_plain_paragraphs(llm_body))
    else:
        intro = _strip_research_meta_lines(_extract_report_summary(summary, findings, topic))
        intro_rows = _extract_plain_paragraphs(intro)
        if intro_rows:
            paragraphs.append(intro_rows[0])
        elif intro:
            paragraphs.append(_clean_research_sentence(intro))
        paragraphs.extend(_select_research_document_findings(findings, topic=topic, limit=4))

    cleaned_rows: list[str] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        clean = _strip_research_annotation(paragraph)
        if not clean or _is_generic_document_paragraph(clean) or _is_low_value_research_statement(clean):
            continue
        key = _normalize_text(clean)
        if key in seen:
            continue
        seen.add(key)
        cleaned_rows.append(clean)

    if not cleaned_rows:
        fallback = _strip_research_meta_lines(summary) or f"{topic} başlığı için yeterli kalitede araştırma özeti üretilemedi."
        cleaned_rows = _extract_plain_paragraphs(fallback) or [_clean_research_sentence(fallback)]

    return [
        {
            "title": "",
            "paragraphs": [{"text": row, "claim_ids": []} for row in cleaned_rows[:6] if row],
        }
    ]


def _sections_to_document_text(title: str, sections: list[dict[str, Any]]) -> str:
    lines = [title]
    for section in list(sections or []):
        heading = _clean_research_sentence(str(section.get("title") or "").strip())
        if heading:
            lines.extend(["", heading])
        for paragraph in list(section.get("paragraphs") or []):
            if isinstance(paragraph, dict):
                text = _clean_research_sentence(str(paragraph.get("text") or "").strip())
            else:
                text = _clean_research_sentence(str(paragraph or "").strip())
            if text:
                lines.extend(["", text])
    return "\n".join(lines).strip()


def _build_claim_map_artifact(
    *,
    topic: str,
    sections: list[dict[str, Any]],
    research_contract: dict[str, Any],
    quality_summary: dict[str, Any],
    profile: str,
    citation_mode: str,
) -> dict[str, Any]:
    claim_list = research_contract.get("claim_list") if isinstance(research_contract, dict) else []
    claim_ids = {str(item.get("claim_id") or "").strip() for item in claim_list if isinstance(item, dict)}
    used_claim_ids: set[str] = set()
    section_rows: list[dict[str, Any]] = []
    for section in list(sections or []):
        title = _clean_research_sentence(str(section.get("title") or "").strip())
        paragraphs = []
        for paragraph in list(section.get("paragraphs") or []):
            if not isinstance(paragraph, dict):
                continue
            paragraph_claim_ids = [str(item).strip() for item in (paragraph.get("claim_ids") or []) if str(item).strip()]
            used_claim_ids.update(paragraph_claim_ids)
            paragraphs.append(
                {
                    "text": str(paragraph.get("text") or "").strip(),
                    "claim_ids": paragraph_claim_ids,
                }
            )
        section_rows.append({"title": title, "paragraphs": paragraphs})

    coverage = len(used_claim_ids & claim_ids) / max(len(claim_ids), 1) if claim_ids else 0.0
    return {
        "topic": topic,
        "document_profile": _normalize_document_profile(profile),
        "citation_mode": _normalize_citation_mode(citation_mode),
        "generated_at": datetime.now().isoformat(),
        "claim_coverage": round(coverage, 2),
        "used_claim_ids": sorted(used_claim_ids),
        "quality_summary": dict(quality_summary or {}),
        "research_contract": dict(research_contract or {}),
        "sections": section_rows,
    }


def _load_json_payload(path: str) -> dict[str, Any]:
    candidate = Path(str(path or "")).expanduser()
    if not candidate.exists() or not candidate.is_file():
        return {}
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_claim_map_revision_summary(
    *,
    previous_claim_map: dict[str, Any],
    current_claim_map: dict[str, Any],
    revision_request: str,
) -> str:
    prev_quality = previous_claim_map.get("quality_summary") if isinstance(previous_claim_map.get("quality_summary"), dict) else {}
    curr_quality = current_claim_map.get("quality_summary") if isinstance(current_claim_map.get("quality_summary"), dict) else {}
    prev_used = {
        str(item).strip()
        for item in list(previous_claim_map.get("used_claim_ids") or [])
        if str(item).strip()
    }
    curr_used = {
        str(item).strip()
        for item in list(current_claim_map.get("used_claim_ids") or [])
        if str(item).strip()
    }
    prev_sections = {
        str(item.get("title") or "").strip()
        for item in list(previous_claim_map.get("sections") or [])
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    }
    curr_sections = {
        str(item.get("title") or "").strip()
        for item in list(current_claim_map.get("sections") or [])
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    }
    lines = [
        "# Revision Summary",
        "",
        f"- Revision request: {str(revision_request or '').strip() or '-'}",
        f"- Previous profile: {previous_claim_map.get('document_profile') or '-'}",
        f"- Current profile: {current_claim_map.get('document_profile') or '-'}",
        f"- Previous citation mode: {previous_claim_map.get('citation_mode') or '-'}",
        f"- Current citation mode: {current_claim_map.get('citation_mode') or '-'}",
        f"- Claim coverage: {float(prev_quality.get('claim_coverage', 0.0) or 0.0):.2f} -> {float(curr_quality.get('claim_coverage', 0.0) or 0.0):.2f}",
        f"- Critical claim coverage: {float(prev_quality.get('critical_claim_coverage', 0.0) or 0.0):.2f} -> {float(curr_quality.get('critical_claim_coverage', 0.0) or 0.0):.2f}",
        f"- Uncertainty count: {int(prev_quality.get('uncertainty_count', 0) or 0)} -> {int(curr_quality.get('uncertainty_count', 0) or 0)}",
        f"- Conflict count: {int(prev_quality.get('conflict_count', 0) or 0)} -> {int(curr_quality.get('conflict_count', 0) or 0)}",
        "",
        "## Structural Changes",
        "",
        f"- Added sections: {', '.join(sorted(curr_sections - prev_sections)) if curr_sections - prev_sections else '-'}",
        f"- Removed sections: {', '.join(sorted(prev_sections - curr_sections)) if prev_sections - curr_sections else '-'}",
        f"- Added claims: {', '.join(sorted(curr_used - prev_used)) if curr_used - prev_used else '-'}",
        f"- Removed claims: {', '.join(sorted(prev_used - curr_used)) if prev_used - curr_used else '-'}",
    ]
    return "\n".join(lines).strip() + "\n"


def _normalize_section_token(title: str) -> str:
    return re.sub(r"\s+", " ", str(title or "").strip().lower())


def _merge_sections_with_previous_claim_map(
    *,
    previous_claim_map: dict[str, Any],
    current_sections: list[dict[str, Any]],
    target_sections: list[str],
) -> list[dict[str, Any]]:
    targets = {
        _normalize_section_token(title)
        for title in list(target_sections or [])
        if str(title or "").strip()
    }
    if not targets:
        return list(current_sections or [])

    previous_sections = previous_claim_map.get("sections") if isinstance(previous_claim_map, dict) else []
    if not isinstance(previous_sections, list) or not previous_sections:
        return list(current_sections or [])

    current_map = {
        _normalize_section_token(str(section.get("title") or "").strip()): dict(section)
        for section in list(current_sections or [])
        if isinstance(section, dict) and str(section.get("title") or "").strip()
    }

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for section in previous_sections:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        key = _normalize_section_token(title)
        if not key:
            continue
        seen.add(key)
        if key in targets and key in current_map:
            merged.append(dict(current_map[key]))
        else:
            paragraphs = []
            for paragraph in list(section.get("paragraphs") or []):
                if isinstance(paragraph, dict):
                    paragraphs.append(
                        {
                            "text": str(paragraph.get("text") or "").strip(),
                            "claim_ids": [
                                str(item).strip()
                                for item in list(paragraph.get("claim_ids") or [])
                                if str(item).strip()
                            ],
                        }
                    )
            merged.append({"title": title, "paragraphs": paragraphs})

    for section in list(current_sections or []):
        if not isinstance(section, dict):
            continue
        key = _normalize_section_token(str(section.get("title") or "").strip())
        if key and key not in seen:
            merged.append(dict(section))
    return merged


def _topic_terms(topic: str) -> list[str]:
    return [token for token in re.findall(r"[a-zA-ZğüşöçıİĞÜŞÖÇ0-9]+", str(topic or "").lower()) if len(token) >= 3]


def _sanitize_research_topic(topic: Any, *, user_input: str = "", step_name: str = "") -> str:
    raw = str(topic or "").strip()
    if not raw:
        raw = " ".join(part for part in [step_name, user_input] if part).strip()
    cleaned = _clean_research_sentence(raw).lower()
    if not cleaned:
        cleaned = _clean_research_sentence(user_input or step_name).lower()

    cleaned = re.sub(
        r"^.*?\b(?:aç|ac|open|başlat|baslat|çalıştır|calistir|launch)\b\s+(?:ve\s+|ardından\s+|sonra\s+)?",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    strip_tokens = (
        "elyan",
        "araştırma",
        "arastirma",
        "araştır",
        "arastir",
        "research",
        "incele",
        "hakkında",
        "hakkinda",
        "ile ilgili",
        "bana",
        "lütfen",
        "lutfen",
        "yap",
        "yapar mısın",
        "yapar misin",
        "sadece",
        "tek bir",
        "tek sayfa",
        "word",
        "docx",
        "pdf",
        "excel",
        "xlsx",
        "tablo",
        "rapor",
        "belge",
        "dosya",
        "özet",
        "ozet",
        "brief",
        "summary",
    )
    for token in strip_tokens:
        cleaned = re.sub(rf"\b{re.escape(token)}\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;-")
    return cleaned or _clean_research_sentence(user_input or step_name) or "genel konu"


def _research_body_seems_relevant(topic: str, body: str) -> bool:
    text = str(body or "").strip()
    if len(text) < 180:
        return False
    terms = _topic_terms(topic)
    if not terms:
        return len(text) >= 180
    matches = sum(1 for token in set(terms) if token in text.lower())
    return matches >= max(1, min(2, len(set(terms))))


def _should_use_llm_research_body(
    *,
    topic: str,
    llm_body: str,
    quality_summary: dict[str, Any],
    source_policy_stats: dict[str, Any],
    source_policy: str,
    findings: list[str],
    sources: list[dict[str, Any]],
) -> bool:
    if not llm_body or not _research_body_seems_relevant(topic, llm_body):
        return False
    if _normalize_text(source_policy) == "official":
        return False
    if bool(source_policy_stats.get("fallback_used")):
        return False
    if str(quality_summary.get("status") or "").strip().lower() != "pass":
        return False
    if len(list(findings or [])) < 2:
        return False
    if len(list(sources or [])) < 3:
        return False
    return True


async def _synthesize_research_body_with_llm(
    *,
    topic: str,
    brief: str,
    findings: list[str],
    sources: list[dict[str, Any]],
    language: str = "tr",
) -> str:
    if not findings or not sources:
        return ""
    try:
        from core.llm_client import LLMClient

        llm = LLMClient()
        source_lines = []
        for idx, src in enumerate(sources[:6], start=1):
            title = _clean_research_sentence(str(src.get("title") or "").strip()) or "Kaynak"
            url = str(src.get("url") or "").strip()
            rel = float(src.get("reliability_score", 0.0) or 0.0)
            source_lines.append(f"{idx}. {title} | {url} | reliability={rel:.2f}")

        finding_lines = []
        for idx, finding in enumerate(findings[:6], start=1):
            finding_lines.append(f"{idx}. {_strip_research_annotation(finding)}")

        prompt = (
            "Aşağıdaki doğrulanmış araştırma girdilerinden kullanıcıya verilecek belge metnini üret.\n"
            "Kurallar:\n"
            "- Yalnızca verilen bulgular ve kaynaklara dayan.\n"
            "- Türkçe yaz.\n"
            "- Düz paragraf üret; markdown başlığı, madde işareti, tablo, güven skoru, metodoloji, sınırlılıklar, öneriler yazma.\n"
            "- Konuyu gerçekten açıkla; komut metnini tekrar etme.\n"
            "- Emin olmadığın bilgiyi ekleme.\n"
            "- 5 ile 7 paragraf arasında kal.\n"
            "- Matematik konusuysa tanım, mantık ve kullanım bağlamını sade şekilde anlat.\n"
            "- Sadece nihai belge metnini döndür.\n\n"
            f"Konu: {topic}\n"
            f"Kullanıcı odağı: {brief or topic}\n\n"
            "Temiz bulgular:\n"
            + "\n".join(finding_lines)
            + "\n\nKaynaklar:\n"
            + "\n".join(source_lines)
        )
        response = await llm.generate(
            prompt,
            role="research_worker",
            temperature=0.2,
            disable_collaboration=True,
        )
        text = str(response or "").strip().strip("`")
        text = re.sub(r"^#+\s.*$", "", text, flags=re.MULTILINE).strip()
        if _research_body_seems_relevant(topic, text):
            return text
    except Exception as exc:
        logger.debug("llm_research_synthesis_failed: %s", exc)
    return ""


def _latex_escape(text: str) -> str:
    s = str(text or "")
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    return s


def _build_latex_document(title: str, paragraphs: list[str]) -> str:
    body = "\n\n".join(_latex_escape(p) + "\n" for p in paragraphs if str(p).strip())
    return (
        "\\documentclass[12pt]{article}\n"
        "\\usepackage[utf8]{inputenc}\n"
        "\\usepackage[T1]{fontenc}\n"
        "\\usepackage[turkish]{babel}\n"
        "\\usepackage[a4paper,margin=1in]{geometry}\n"
        "\\begin{document}\n"
        f"\\title{{{_latex_escape(title)}}}\n"
        "\\date{}\n"
        "\\maketitle\n\n"
        f"{body}\n"
        "\\end{document}\n"
    )


def _topic_stems(topic: str) -> list[str]:
    stems: list[str] = []
    for token in _topic_terms(topic):
        norm = _normalize_text(token).strip()
        if len(norm) < 3:
            continue
        stem = norm[:5] if len(norm) > 5 else norm
        if stem and stem not in stems:
            stems.append(stem)
    return stems


def _finding_topic_match_score(topic: str, text: str) -> int:
    low = _normalize_text(text)
    if not low:
        return 0
    return sum(1 for stem in _topic_stems(topic) if stem and stem in low)


def _select_research_document_findings(findings: list[str], *, topic: str = "", limit: int = 5) -> list[str]:
    selected: list[str] = []
    seen_findings: set[str] = set()
    for item in findings:
        clean = _strip_research_annotation(item)
        if not clean or _is_low_value_research_statement(clean):
            continue
        key = _normalize_text(clean)[:120]
        if key in seen_findings:
            continue
        seen_findings.add(key)
        selected.append(clean)
    if not topic:
        return selected[:limit]

    scored = [(item, _finding_topic_match_score(topic, item)) for item in selected]
    stems = _topic_stems(topic)
    strong_threshold = min(2, len(stems)) if stems else 1
    strong = [item for item, score in scored if score >= strong_threshold]
    if len(strong) >= min(2, limit):
        return strong[:limit]

    medium = [item for item, score in scored if score >= 1]
    if medium:
        return medium[:limit]
    return selected[:limit]


def _extract_report_summary(summary: str, findings: list[str], topic: str) -> str:
    blocked_exact = {
        "yonetici ozeti",
        "yonetici ozeti:",
        "kisa ozet",
        "kisa ozet:",
        "ana bulgular (kanit odakli):",
        "ana bulgular",
        "kanit matrisi (ilk 5 kaynak):",
        "operasyonel oneriler:",
        "sinirliliklar:",
    }
    blocked_prefixes = (
        "arastirma konusu:",
        "kapsam:",
        "kaynak profili:",
        "kaynak politikasi:",
        "onerilen referans seti:",
        "not:",
        "one cikan alan adlari:",
        "onerilen devam adimi:",
    )
    lines = []
    for raw in str(summary or "").splitlines():
        clean = _clean_research_sentence(raw)
        if not clean:
            continue
        low = _normalize_text(clean)
        if low in blocked_exact:
            continue
        if any(prefix in low for prefix in blocked_prefixes):
            continue
        if any(token in low for token in ("guvenilirlik", "kaynak orani", "kaynak incelendi", "ortalama guven")):
            continue
        if low.startswith(("-", "1.", "2.", "3.", "4.", "5.", "6.")):
            continue
        lines.append(clean)
        if len(lines) >= 3:
            break
    if lines:
        return "\n\n".join(lines)

    clean_findings = [_strip_research_annotation(item) for item in findings if _strip_research_annotation(item)]
    if clean_findings:
        lead = clean_findings[:2]
        return (
            f"Bu rapor {topic} başlığını temel kaynaklar üzerinden özetler.\n\n"
            + " ".join(lead)
        ).strip()
    return f"Bu rapor {topic} başlığını güvenilir kaynaklar üzerinden kısa ve düzenli biçimde özetler."


def _extract_plain_paragraphs(text: str) -> list[str]:
    raw = str(text or "").replace("\r\n", "\n")
    parts = []
    for chunk in re.split(r"\n\s*\n", raw):
        clean = _clean_research_sentence(chunk)
        if not clean:
            continue
        if len(clean) < 12:
            continue
        parts.append(clean)
    return parts


def _normalize_document_instruction(text: str) -> str:
    value = _clean_research_sentence(text)
    if not value:
        return ""
    low = _normalize_text(value)
    command_markers = (
        "hazirla",
        "hazirlar misin",
        "olustur",
        "uret",
        "yaz",
        "rapor",
        "belge",
        "dokuman",
        "dokumani",
        "word",
        "docx",
        "pdf",
        "excel",
        "xlsx",
        "tek bir",
        "sadece",
    )
    if sum(1 for marker in command_markers if marker in low) >= 2:
        return ""
    return value


def _brief_requests_reference_detail(brief: str, profile: str) -> bool:
    low = _normalize_text(brief)
    if _normalize_document_profile(profile) == "analytical":
        return True
    markers = (
        "kaynakca",
        "kaynakça",
        "kaynak",
        "citation",
        "cite",
        "atif",
        "atıf",
        "bibliography",
        "reference",
        "dipnot",
        "footnote",
    )
    return any(marker in low for marker in markers)


def _brief_requests_structured_sections(brief: str, profile: str) -> bool:
    low = _normalize_text(brief)
    if _normalize_document_profile(profile) == "analytical":
        return True
    markers = (
        "risk",
        "uyari",
        "uyarı",
        "belirsizlik",
        "analitik",
        "analytical",
        "briefing",
        "kaynakca",
        "kaynakça",
        "citation",
        "atif",
        "atıf",
    )
    return any(marker in low for marker in markers)


def _brief_requests_compact_research_report(brief: str, profile: str) -> bool:
    if _normalize_document_profile(profile) == "briefing":
        return True
    low = _normalize_text(brief)
    if not low:
        return False
    markers = (
        "tek bir",
        "tek sayfa",
        "kısa",
        "kisa",
        "özet",
        "ozet",
        "summary",
        "brief",
        "yalın",
        "yalin",
        "sade",
        "minimal",
        "özetle",
        "ozetle",
        "özet rapor",
        "ozet rapor",
    )
    return any(marker in low for marker in markers)


def _infer_requested_document_formats(
    topic: str,
    brief: str,
    preferred_formats: Any = None,
) -> list[str]:
    explicit: list[str] = []
    if isinstance(preferred_formats, str) and preferred_formats.strip():
        preferred_formats = [preferred_formats]
    if isinstance(preferred_formats, (list, tuple, set)):
        for item in preferred_formats:
            value = _normalize_text(str(item or ""))
            if value in {"docx", "word"} and "docx" not in explicit:
                explicit.append("docx")
            elif value in {"xlsx", "excel", "csv"} and "xlsx" not in explicit:
                explicit.append("xlsx")
            elif value == "pdf" and "pdf" not in explicit:
                explicit.append("pdf")
            elif value in {"latex", "tex"} and "tex" not in explicit:
                explicit.append("tex")
            elif value in {"markdown", "md"} and "md" not in explicit:
                explicit.append("md")
            elif value in {"txt", "text"} and "txt" not in explicit:
                explicit.append("txt")
            elif value in {"html", "htm"} and "html" not in explicit:
                explicit.append("html")
            elif value in {"pptx", "ppt", "presentation", "slide", "slides", "deck", "sunum"} and "pptx" not in explicit:
                explicit.append("pptx")

    low = _normalize_text(f"{topic} {brief}")
    marker_map = [
        ("pdf", "pdf"),
        ("latex", "tex"),
        ("tex", "tex"),
        ("word", "docx"),
        ("docx", "docx"),
        ("excel", "xlsx"),
        ("xlsx", "xlsx"),
        ("csv", "xlsx"),
        ("tablo", "xlsx"),
        ("markdown", "md"),
        ("md", "md"),
        ("txt", "txt"),
        ("metin", "txt"),
        ("html", "html"),
        ("htm", "html"),
        ("pptx", "pptx"),
        ("ppt", "pptx"),
        ("sunum", "pptx"),
        ("presentation", "pptx"),
        ("slide", "pptx"),
        ("slides", "pptx"),
        ("deck", "pptx"),
    ]
    for marker, fmt in marker_map:
        if marker in low and fmt not in explicit:
            explicit.append(fmt)

    return explicit or ["docx"]


def _build_plain_document_paragraphs(topic: str, brief: str, audience: str = "executive") -> list[str]:
    paragraphs = _extract_plain_paragraphs(_normalize_document_instruction(brief))
    topic_clean = str(topic or "").strip() or "Bu konu"
    fallback_paragraphs = [
        (
            f"{topic_clean} bu belgede açık, düzenli ve doğrudan bir dille ele alınır. "
            f"Metin, kavramın ne olduğunu, neden önemli olduğunu ve hangi bağlamlarda kullanıldığını kullanıcı açısından anlaşılır hale getirmeyi hedefler."
        ),
        (
            f"İlk bölümde {topic_clean.lower()} konusunun temel çerçevesi kurulurken, devamında öne çıkan bileşenler, "
            f"uygulama alanları ve dikkat edilmesi gereken noktalar sade bir akışla açıklanır. "
            f"Bu yapı özellikle {audience} odaklı okunabilirlik için kısa ama yoğun paragraflar üretir."
        ),
        (
            f"Belgenin sonunda konuya dair pratik bir toparlama yapılır; böylece okuyucu {topic_clean.lower()} başlığını "
            f"sadece tanımsal olarak değil, kullanım ve karar verme bağlamında da kavramış olur."
        ),
    ]
    if not paragraphs:
        return fallback_paragraphs
    if len("\n\n".join(paragraphs)) >= 200:
        return paragraphs[:12]
    return paragraphs[:3] + fallback_paragraphs


def _build_plain_document_text(topic: str, brief: str, audience: str = "executive") -> str:
    paragraphs = _build_plain_document_paragraphs(topic, brief, audience=audience)
    return "\n\n".join(paragraphs).strip()


def _build_excel_document_payload(topic: str, brief: str, audience: str = "executive") -> dict[str, list[dict[str, Any]]]:
    paragraphs = _build_plain_document_paragraphs(topic, brief, audience=audience)
    overview = [
        {"Alan": "Konu", "Deger": str(topic or "").strip() or "Belge"},
        {"Alan": "Hedef Kitle", "Deger": audience},
        {"Alan": "Paragraf Sayisi", "Deger": len(paragraphs)},
    ]
    content_rows = [
        {"No": idx, "Metin": paragraph}
        for idx, paragraph in enumerate(paragraphs, start=1)
    ]
    return {
        "Ozet": overview,
        "Icerik": content_rows or [{"No": 1, "Metin": str(topic or "").strip() or "Belge içeriği"}],
    }


def _write_simple_pdf(path: str, title: str, content: str) -> dict[str, Any]:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    except Exception as exc:
        return {"success": False, "error": f"PDF oluşturma bağımlılığı hazır değil: {exc}"}

    file_path = Path(path).expanduser().resolve()
    file_path.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name="PlainDocTitle",
        parent=styles["Heading1"],
        fontSize=18,
        spaceAfter=18,
    )
    body_style = ParagraphStyle(
        name="PlainDocBody",
        parent=styles["Normal"],
        leading=16,
        spaceAfter=10,
    )

    story = [Paragraph(_escape_html(title), title_style), Spacer(1, 0.2 * inch)]
    for para in _extract_plain_paragraphs(content) or [str(content or "").strip()]:
        text = _escape_html(para).replace("\n", "<br/>")
        if text:
            story.append(Paragraph(text, body_style))
            story.append(Spacer(1, 0.1 * inch))

    try:
        doc = SimpleDocTemplate(str(file_path), pagesize=A4, rightMargin=56, leftMargin=56, topMargin=56, bottomMargin=56)
        doc.build(story)
        return {"success": True, "path": str(file_path), "filename": file_path.name}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _build_research_word_content(
    *,
    topic: str,
    brief: str,
    audience: str,
    depth: str,
    policy: str,
    min_rel: float,
    summary: str,
    findings: list[str],
    sources: list[dict[str, Any]],
    source_count: int,
    avg_reliability: float,
    include_bibliography: bool,
) -> str:
    clean_findings = _select_research_document_findings(findings, topic=topic, limit=5)

    intro = _strip_research_meta_lines(_extract_report_summary(summary, clean_findings, topic))
    if not intro:
        intro = (
            f"{topic} konusu için temel kaynaklar taranmış ve belge, konuya doğrudan giriş sağlayacak sade bir araştırma metni olarak düzenlenmiştir."
        )
    scope_note = _normalize_document_instruction(brief)
    source_rows = []
    for idx, src in enumerate(sources[:8], start=1):
        if not isinstance(src, dict):
            continue
        title = _clean_research_sentence(str(src.get("title") or "").strip()) or "Başlıksız kaynak"
        url = str(src.get("url") or "").strip()
        rel_raw = src.get("reliability_score", 0.0)
        try:
            rel = float(rel_raw or 0.0)
        except Exception:
            rel = 0.0
        line = f"{idx}. {title}"
        if url:
            line += f" - {url}"
        source_rows.append(line)

    body_paragraphs = []
    try:
        from tools.research_tools.document_rag import build_research_narrative

        body_paragraphs = build_research_narrative(
            topic=topic,
            findings=clean_findings,
            sources=sources,
            brief=brief,
            summary=summary,
            include_bibliography=include_bibliography,
            max_paragraphs=8,
        )
    except Exception as exc:
        logger.debug("research_narrative_build_failed: %s", exc)

    if not body_paragraphs:
        body_paragraphs = [
            intro,
            (
                f"{topic} konusu için temel literatür ve açıklayıcı kaynaklar karşılaştırıldı. "
                f"Metin, aynı konuyu tekrarlayan dağınık cümleler yerine doğrudan anlaşılabilir bir araştırma özeti sunacak şekilde düzenlendi."
            ),
        ]
        if scope_note and _normalize_text(scope_note) not in _normalize_text(intro):
            body_paragraphs.append(f"Bu belge şu odakla hazırlandı: {scope_note}.")
        if clean_findings:
            body_paragraphs.extend(clean_findings)
        else:
            body_paragraphs.append("Doğrudan kullanılabilir bulgu sınırlı kaldığı için ikinci tur kaynak taraması önerilir.")

        conclusion = (
            f"Sonuç olarak {topic.lower()} başlığı, hem temel kavramsal çerçevesi hem de uygulama mantığıyla birlikte okunabilir bir bütün oluşturur."
            if source_count >= 3
            else f"Sonuç olarak {topic.lower()} başlığı için çekirdek çerçeve kurulmuştur; daha fazla kaynakla metin genişletilebilir."
        )
        body_paragraphs.append(conclusion)
        if include_bibliography and source_rows:
            body_paragraphs.append("Kaynakça:\n" + "\n".join(source_rows))
    elif scope_note and _normalize_text(scope_note) not in _normalize_text(" ".join(body_paragraphs)):
        body_paragraphs.insert(1, f"Bu belge şu odakla hazırlandı: {scope_note}.")

    return "\n\n".join(part for part in body_paragraphs if str(part).strip()).strip()


def _mix_hex(color_a: str, color_b: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, float(ratio)))
    a = color_a.lstrip("#")
    b = color_b.lstrip("#")
    if len(a) != 6 or len(b) != 6:
        return f"#{a or b or '000000'}"[:7]
    blended = []
    for idx in range(0, 6, 2):
        av = int(a[idx:idx + 2], 16)
        bv = int(b[idx:idx + 2], 16)
        blended.append(f"{int(round((av * ratio) + (bv * (1.0 - ratio)))):02x}")
    return f"#{''.join(blended)}"


def _requested_palette(brief: str, theme: str) -> dict[str, str] | None:
    low = _normalize_text(f"{brief} {theme}")
    if not low:
        return None

    warm_combo = (("sari" in low or "yellow" in low) and ("turuncu" in low or "orange" in low))
    mono_combo = (("siyah" in low or "black" in low) and ("beyaz" in low or "white" in low))
    if warm_combo:
        return {
            "accent": "#f59e0b",
            "accent2": "#f97316",
            "bg1": "#fff4cc",
            "bg2": "#ffd7a8",
        }
    if mono_combo:
        return {
            "accent": "#111827",
            "accent2": "#475569",
            "bg1": "#f8fafc",
            "bg2": "#e2e8f0",
        }

    color_map = [
        (("sari", "yellow"), "#f59e0b"),
        (("turuncu", "orange"), "#f97316"),
        (("kirmizi", "red"), "#ef4444"),
        (("mavi", "blue"), "#2563eb"),
        (("yesil", "green"), "#16a34a"),
        (("mor", "purple"), "#7c3aed"),
        (("pembe", "pink"), "#ec4899"),
        (("siyah", "black"), "#111827"),
        (("beyaz", "white"), "#f8fafc"),
    ]
    colors: list[str] = []
    for aliases, hex_value in color_map:
        if any(alias in low for alias in aliases):
            colors.append(hex_value)
    if not colors:
        return None

    accent = colors[0]
    accent2 = colors[1] if len(colors) > 1 else _mix_hex(accent, "#7c2d12", 0.45)
    return {
        "accent": accent,
        "accent2": accent2,
        "bg1": _mix_hex(accent, "#fff9f0", 0.16),
        "bg2": _mix_hex(accent2, "#fff1df", 0.22),
    }


def _contains_term(text: str, term: str) -> bool:
    haystack = f" {_normalize_text(text)} "
    needle = _normalize_text(term).strip()
    if not needle:
        return False
    if " " in needle or "-" in needle:
        return needle in haystack
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(_contains_term(text, term) for term in terms)


def _looks_like_non_document_request(topic: str, brief: str) -> bool:
    low = f"{str(topic or '').lower()} {str(brief or '').lower()}".strip()
    if not low:
        return True
    browser_markers = (
        "safari",
        "chrome",
        "browser",
        "tarayıcı",
        "tarayici",
        "google",
        "web",
        "site",
        "sayfa",
        "url",
        "arat",
        "ara",
        "search",
        "aç",
        "ac",
        "git",
    )
    image_markers = (
        "resim",
        "resimleri",
        "görsel",
        "gorsel",
        "foto",
        "image",
        "images",
        "wallpaper",
    )
    doc_markers = (
        "belge",
        "doküman",
        "dokuman",
        "rapor",
        "brief",
        "summary",
        "özet",
        "ozet",
        "kurumsal",
        "profesyonel",
        "executive",
        "analysis",
        "analiz",
        "risk",
        "aksiyon",
    )
    singular_image_phrase = " resmi " in f" {low} "
    looks_browser_like = any(marker in low for marker in browser_markers) and (
        any(marker in low for marker in image_markers) or singular_image_phrase
    )
    if looks_browser_like and not any(marker in low for marker in doc_markers):
        return True
    meaningful = [token for token in low.replace(",", " ").split() if token.strip()]
    return len(meaningful) < 3 and not any(marker in low for marker in doc_markers)


def _derive_web_profile(project_name: str, brief: str, theme: str) -> dict[str, Any]:
    low = str(brief or "").lower()
    layout = "landing"
    if _contains_any_term(brief, ("dashboard", "panel", "analitik", "kpi", "rapor ekrani", "rapor ekrani")):
        layout = "dashboard"
    elif _contains_any_term(brief, ("e-ticaret", "ecommerce", "shop", "store", "urun", "sepet")):
        layout = "commerce"
    elif _contains_any_term(brief, ("portfolio", "portfolyo", "portfoy", "cv", "ozgecmis")):
        layout = "portfolio"
    elif _contains_any_term(brief, ("blog", "makale", "yazi")):
        layout = "blog"

    style = str(theme or "").strip().lower() or "professional"
    if _contains_any_term(brief, ("minimal", "clean", "sade")):
        style = "minimal"
    elif _contains_any_term(brief, ("neon", "cyber", "futuristic", "futuristik")):
        style = "futuristic"
    elif _contains_any_term(brief, ("enterprise", "kurumsal", "corporate", "b2b")):
        style = "corporate"
    elif style not in {"professional", "minimal", "futuristic", "corporate"}:
        style = "professional"

    palette = {
        "professional": {"accent": "#2563eb", "accent2": "#0ea5e9", "bg1": "#f8fafc", "bg2": "#e2e8f0"},
        "minimal": {"accent": "#111827", "accent2": "#374151", "bg1": "#ffffff", "bg2": "#f3f4f6"},
        "futuristic": {"accent": "#06b6d4", "accent2": "#8b5cf6", "bg1": "#0b1020", "bg2": "#101827"},
        "corporate": {"accent": "#1d4ed8", "accent2": "#0369a1", "bg1": "#eef2ff", "bg2": "#e0e7ff"},
    }[style]
    palette_override = _requested_palette(brief, theme)
    if palette_override:
        palette = dict(palette_override)

    features = {
        "counter": _wants_counter_feature(brief),
        "todo": _contains_any_term(brief, ("todo", "to do", "yapilacak", "task list")),
        "search": _contains_any_term(brief, ("arama", "search", "filtre", "filter")),
        "contact_form": _contains_any_term(brief, ("form", "iletisim", "contact", "lead")),
        "theme_toggle": _contains_any_term(brief, ("dark mode", "tema", "theme")) or style == "futuristic",
        "timer": _contains_any_term(brief, ("timer", "pomodoro", "sure", "zamanlayici")),
        "tailwind": _contains_any_term(brief, ("tailwind", "modern css", "utility first", "responsive ui")),
        "motion": _contains_any_term(brief, ("animation", "animasyon", "gsap", "framer", "scroll reveal")),
        "gallery_mode": _contains_any_term(brief, ("galeri", "gallery", "portfolio", "portfolyo", "portfoy")),
    }
    # Default modern UI on web scaffold; keeps baseline quality higher.
    if not features["tailwind"]:
        features["tailwind"] = True
    if not features["motion"]:
        features["motion"] = True

    if layout == "dashboard":
        sections = ["Genel Görünüm", "KPI Kartları", "Aktivite Akışı", "Aksiyon Listesi"]
    elif layout == "commerce":
        sections = ["Öne Çıkan Ürünler", "Kategori Izgarası", "Kampanyalar", "Sık Sorulanlar"]
    elif layout == "portfolio":
        sections = ["Hakkımda", "Projeler", "Yetenekler", "İletişim"]
    elif layout == "blog":
        sections = ["Öne Çıkan Yazı", "Kategori Akışı", "Bülten", "Yazar Notu"]
    else:
        sections = ["Değer Önerisi", "Özellikler", "Süreç", "SSS"]

    title = str(project_name or "Elyan Web App").strip() or "Elyan Web App"
    subtitle = _brief_excerpt(brief, fallback=f"{title} için özelleştirilmiş web uygulaması")
    cta = "Hemen Basla"
    if layout == "portfolio":
        cta = "Projeleri Incele"
    elif layout == "commerce":
        cta = "Koleksiyonu Kesfet"
    elif layout == "dashboard":
        cta = "Pano'yu Ac"

    return {
        "layout": layout,
        "style": style,
        "palette": palette,
        "features": features,
        "sections": sections,
        "title": title,
        "subtitle": subtitle,
        "cta": cta,
    }


def _build_portfolio_assets(profile: dict[str, Any]) -> tuple[str, str, str]:
    palette = profile["palette"]
    features = profile["features"]
    title = _escape_html(profile["title"])
    subtitle = _escape_html(profile["subtitle"])
    skill_chips = "".join(
        f"<span class=\"skill-chip\">{_escape_html(item)}</span>"
        for item in [
            "Brand Systems",
            "UI Direction",
            "Motion Language",
            "Responsive Frontend",
            "Case Studies",
            "Launch Support",
        ]
    )

    project_cards = "".join(
        [
            (
                "<article class=\"project-card reveal\">"
                "<p class=\"project-tag\">Signature Build</p>"
                "<h3>Warm Identity System</h3>"
                "<p>Hero, color choreography ve editorial ritimle ilk izlenimi guclendirir.</p>"
                "<ul class=\"project-meta\"><li>Visual system</li><li>Responsive grid</li><li>CTA hierarchy</li></ul>"
                "</article>"
            ),
            (
                "<article class=\"project-card reveal alt\">"
                "<p class=\"project-tag\">Featured Work</p>"
                "<h3>Story-Driven Case Study</h3>"
                "<p>Is akisini sadece gostermek yerine neden-sonuc iliskisiyle anlatan kart yapisi.</p>"
                "<ul class=\"project-meta\"><li>Process framing</li><li>Outcome metrics</li><li>Scroll pacing</li></ul>"
                "</article>"
            ),
            (
                "<article class=\"project-card reveal tone\">"
                "<p class=\"project-tag\">Client Funnel</p>"
                "<h3>Contact Conversion</h3>"
                "<p>Iletisim bolumu ziyaretciyi kaybetmeden net bir sonraki adima tasir.</p>"
                "<ul class=\"project-meta\"><li>Trust layer</li><li>Offer clarity</li><li>Inquiry path</li></ul>"
                "</article>"
            ),
        ]
    )

    gallery_block = ""
    if features.get("gallery_mode"):
        gallery_block = """
    <section class="gallery-grid reveal" aria-label="Portfolio gallery">
      <figure class="gallery-item"><img src="https://images.unsplash.com/photo-1516321318423-f06f85e504b3?auto=format&fit=crop&w=1200&q=80" alt="Creative workspace" loading="lazy" /><figcaption>Concept direction</figcaption></figure>
      <figure class="gallery-item"><img src="https://images.unsplash.com/photo-1517245386807-bb43f82c33c4?auto=format&fit=crop&w=1200&q=80" alt="Project wall" loading="lazy" /><figcaption>Launch-ready compositions</figcaption></figure>
      <figure class="gallery-item"><img src="https://images.unsplash.com/photo-1524758631624-e2822e304c36?auto=format&fit=crop&w=1200&q=80" alt="Studio detail" loading="lazy" /><figcaption>Warm editorial detail</figcaption></figure>
    </section>
"""

    contact_body = (
        """
        <form id="leadForm" class="lead-form">
          <input name="name" type="text" placeholder="Ad Soyad" required />
          <input name="email" type="email" placeholder="E-posta" required />
          <textarea name="message" rows="4" placeholder="Proje hedefinizi kisaca yazin"></textarea>
          <button type="submit" class="btn primary">Gorusme Talebi Gonder</button>
          <p id="leadStatus" class="contact-note"></p>
        </form>
"""
        if features.get("contact_form")
        else """
        <div class="contact-stack">
          <a class="contact-link" href="mailto:hello@example.com">hello@example.com</a>
          <p class="contact-note">Brief, zamanlama ve beklentiyle gelin. Ilk yanit yapisi 24 saat icinde hazir.</p>
        </div>
"""
    )

    theme_toggle = ""
    if features.get("theme_toggle"):
        theme_toggle = '<button id="themeToggle" type="button" class="btn ghost small">Tema Degistir</button>'

    tailwind_cdn = ""
    gsap_cdn = ""
    if features.get("tailwind"):
        tailwind_cdn = '  <script src="https://cdn.tailwindcss.com"></script>\n'
    if features.get("motion"):
        gsap_cdn = (
            '  <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"></script>\n'
            '  <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/ScrollTrigger.min.js"></script>\n'
        )

    html = f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <meta name="description" content="{subtitle}">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
{tailwind_cdn}{gsap_cdn}  <link rel="stylesheet" href="./styles/main.css">
</head>
<body data-style="{_escape_html(profile['style'])}">
  <div class="page-orb orb-left"></div>
  <div class="page-orb orb-right"></div>

  <header class="site-header">
    <nav class="topbar reveal" aria-label="Primary">
      <a href="#top" class="brand-mark">Portfolio Atelier</a>
      <div class="nav-links">
        <a href="#about" data-scroll>Hakkimda</a>
        <a href="#projects" data-scroll>Projeler</a>
        <a href="#skills" data-scroll>Yetenekler</a>
        <a href="#contact" data-scroll>Iletisim</a>
      </div>
    </nav>

    <section class="portfolio-hero" id="top">
      <div class="hero-copy reveal">
        <p class="eyebrow">Warm, editorial, conversion-focused</p>
        <h1>{title}</h1>
        <p class="lead">{subtitle}</p>
        <div class="hero-actions">
          {theme_toggle}
          <a href="#projects" data-scroll class="btn primary">{_escape_html(profile['cta'])}</a>
          <a href="#contact" data-scroll class="btn secondary">Iletisime Gec</a>
        </div>
        <div class="hero-metrics">
          <article class="metric-card">
            <span>Focus</span>
            <strong>Portfolio clarity</strong>
          </article>
          <article class="metric-card">
            <span>Palette</span>
            <strong>Custom brief colors</strong>
          </article>
          <article class="metric-card">
            <span>Build</span>
            <strong>Responsive static site</strong>
          </article>
        </div>
      </div>

      <aside class="hero-panel reveal">
        <p class="panel-kicker">Selected profile</p>
        <h2>Intentional first impression</h2>
        <p>Bu duzen, tek bir placeholder baslik yerine kim oldugunuzu, nasil calistiginizi ve ne sundugunuzu ayni ekranda anlatir.</p>
        <div class="panel-stripes">
          <span></span>
          <span></span>
          <span></span>
        </div>
      </aside>
    </section>
  </header>

  <main class="container">
    <section class="section-shell about-shell reveal" id="about">
      <div>
        <p class="section-label">About</p>
        <h2>Kimlik, yetenek ve sonuc ayni anlatida toplandi.</h2>
      </div>
      <p class="section-copy">Klasik portfolyo bloklari yerine daha net bir akis kullanildi: giris, secilen isler, yetenek bandi ve iletisim gecisi. Renk karari brief'ten cekilir, duzen responsive kalir.</p>
    </section>

    <section class="section-shell project-showcase" id="projects">
      <div class="section-heading reveal">
        <p class="section-label">Featured Work</p>
        <h2>Portfolyo istediginizde artik gercekten portfolyo uretiliyor.</h2>
      </div>
      <div class="project-grid">
        {project_cards}
      </div>
    </section>

    <section class="section-shell skills-shell reveal" id="skills">
      <div class="section-heading">
        <p class="section-label">Capabilities</p>
        <h2>Sunum, arayuz ve teslimat dili ayni sistemde.</h2>
      </div>
      <div class="skill-cloud">
        {skill_chips}
      </div>
    </section>
{gallery_block}
    <section class="section-shell contact-shell reveal" id="contact">
      <div class="section-heading">
        <p class="section-label">Contact</p>
        <h2>Bir sonraki proje icin net bir cikis yolu.</h2>
      </div>
      {contact_body}
    </section>
  </main>

  <footer class="site-footer">
    <p>Generated as a high-signal portfolio scaffold.</p>
  </footer>

  <script src="./scripts/main.js"></script>
</body>
</html>
"""

    css = f""":root {{
  --bg-start: {palette['bg1']};
  --bg-end: {palette['bg2']};
  --surface: rgba(255, 255, 255, 0.72);
  --surface-strong: rgba(255, 255, 255, 0.9);
  --surface-muted: rgba(255, 247, 237, 0.7);
  --text: #1f160d;
  --muted: #6b5b4d;
  --line: rgba(120, 85, 46, 0.16);
  --accent: {palette['accent']};
  --accent-2: {palette['accent2']};
  --shadow: 0 28px 80px rgba(74, 39, 14, 0.14);
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  min-height: 100vh;
  position: relative;
  overflow-x: hidden;
  font-family: "Manrope", "Segoe UI", sans-serif;
  color: var(--text);
  background:
    radial-gradient(circle at top left, rgba(255, 255, 255, 0.82), transparent 32%),
    linear-gradient(145deg, var(--bg-start) 0%, #fff8ef 38%, var(--bg-end) 100%);
}}
body[data-theme="dark"] {{
  --surface: rgba(24, 16, 10, 0.78);
  --surface-strong: rgba(31, 20, 12, 0.92);
  --surface-muted: rgba(48, 30, 17, 0.78);
  --text: #f7ecdf;
  --muted: #dbc5af;
  --line: rgba(255, 214, 170, 0.18);
  --shadow: 0 28px 80px rgba(0, 0, 0, 0.34);
}}
a {{ color: inherit; text-decoration: none; }}
.page-orb {{
  position: fixed;
  width: 36rem;
  height: 36rem;
  border-radius: 999px;
  pointer-events: none;
  filter: blur(18px);
  opacity: 0.34;
  z-index: 0;
}}
.orb-left {{
  top: -12rem;
  left: -10rem;
  background: radial-gradient(circle, var(--accent) 0%, transparent 68%);
}}
.orb-right {{
  right: -12rem;
  top: 18rem;
  background: radial-gradient(circle, var(--accent-2) 0%, transparent 68%);
}}
.site-header,
.container,
.site-footer {{
  position: relative;
  z-index: 1;
  max-width: 1180px;
  margin: 0 auto;
  padding-left: 28px;
  padding-right: 28px;
}}
.topbar {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding-top: 24px;
}}
.brand-mark {{
  font-family: "Space Grotesk", "Segoe UI", sans-serif;
  font-size: 0.95rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}}
.nav-links {{
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  color: var(--muted);
  font-size: 0.96rem;
}}
.portfolio-hero {{
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(300px, 0.9fr);
  gap: 24px;
  padding: 44px 0 28px;
  align-items: stretch;
}}
.hero-copy,
.hero-panel,
.section-shell {{
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 28px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(16px);
}}
.hero-copy {{
  padding: 34px;
}}
.eyebrow,
.section-label,
.panel-kicker,
.project-tag {{
  margin: 0;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  font-size: 0.76rem;
  color: var(--muted);
}}
.hero-copy h1,
.section-heading h2,
.about-shell h2,
.hero-panel h2 {{
  margin: 12px 0 0;
  font-family: "Space Grotesk", "Segoe UI", sans-serif;
  line-height: 0.96;
}}
.hero-copy h1 {{
  font-size: clamp(3.6rem, 10vw, 7rem);
  max-width: 10ch;
}}
.lead,
.section-copy,
.hero-panel p {{
  font-size: 1.05rem;
  line-height: 1.7;
  color: var(--muted);
}}
.hero-actions {{
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 28px;
}}
.hero-metrics {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-top: 32px;
}}
.metric-card {{
  padding: 14px 16px;
  border-radius: 20px;
  background: var(--surface-strong);
  border: 1px solid var(--line);
}}
.metric-card span {{
  display: block;
  color: var(--muted);
  font-size: 0.82rem;
  margin-bottom: 10px;
}}
.metric-card strong {{
  font-size: 0.98rem;
}}
.hero-panel {{
  padding: 28px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.22), rgba(255, 255, 255, 0)),
    linear-gradient(135deg, color-mix(in srgb, var(--accent) 22%, transparent), transparent 54%),
    var(--surface-muted);
}}
.panel-stripes {{
  display: grid;
  gap: 10px;
  margin-top: 24px;
}}
.panel-stripes span {{
  height: 10px;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
}}
.container {{
  display: grid;
  gap: 18px;
  padding-bottom: 38px;
}}
.section-shell {{
  padding: 28px;
}}
.about-shell {{
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 24px;
}}
.project-grid {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 18px;
}}
.project-card {{
  position: relative;
  overflow: hidden;
  min-height: 260px;
  padding: 22px;
  border-radius: 24px;
  background: linear-gradient(180deg, rgba(255,255,255,0.82), rgba(255,255,255,0.58));
  border: 1px solid rgba(255,255,255,0.44);
}}
.project-card::after {{
  content: "";
  position: absolute;
  inset: auto -24px -34px auto;
  width: 160px;
  height: 160px;
  border-radius: 999px;
  background: radial-gradient(circle, color-mix(in srgb, var(--accent) 72%, white), transparent 68%);
  opacity: 0.45;
}}
.project-card.alt::after {{
  background: radial-gradient(circle, color-mix(in srgb, var(--accent-2) 74%, white), transparent 68%);
}}
.project-card.tone {{
  background: linear-gradient(180deg, rgba(255, 248, 239, 0.88), rgba(255, 238, 219, 0.72));
}}
.project-card h3 {{
  margin: 14px 0 10px;
  font-family: "Space Grotesk", "Segoe UI", sans-serif;
  font-size: 1.42rem;
}}
.project-card p {{
  color: var(--muted);
  line-height: 1.65;
}}
.project-meta {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 0;
  margin: auto 0 0;
  list-style: none;
}}
.project-meta li,
.skill-chip {{
  border-radius: 999px;
  padding: 8px 12px;
  background: var(--surface-strong);
  border: 1px solid var(--line);
  font-size: 0.9rem;
}}
.skills-shell .section-heading {{
  margin-bottom: 18px;
}}
.skill-cloud {{
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}}
.gallery-grid {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}}
.gallery-item {{
  margin: 0;
  overflow: hidden;
  border-radius: 24px;
  border: 1px solid var(--line);
  background: var(--surface-strong);
  box-shadow: var(--shadow);
}}
.gallery-item img {{
  display: block;
  width: 100%;
  height: 280px;
  object-fit: cover;
}}
.gallery-item figcaption {{
  padding: 12px 14px;
  color: var(--muted);
}}
.contact-shell {{
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 20px;
  align-items: start;
}}
.lead-form,
.contact-stack {{
  display: grid;
  gap: 12px;
}}
.contact-link {{
  font-family: "Space Grotesk", "Segoe UI", sans-serif;
  font-size: clamp(1.6rem, 4vw, 2.6rem);
}}
.contact-note {{
  color: var(--muted);
  margin: 0;
  line-height: 1.65;
}}
.btn {{
  appearance: none;
  border: 1px solid transparent;
  border-radius: 999px;
  padding: 0.9rem 1.2rem;
  font: inherit;
  cursor: pointer;
  transition: transform 180ms ease, box-shadow 180ms ease, background 180ms ease;
}}
.btn:hover {{
  transform: translateY(-2px);
}}
.btn.small {{
  padding: 0.75rem 1rem;
  font-size: 0.88rem;
}}
.btn.primary {{
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: #fff;
  box-shadow: 0 14px 34px rgba(249, 115, 22, 0.22);
}}
.btn.secondary {{
  background: var(--surface-strong);
  color: var(--text);
  border-color: var(--line);
}}
.btn.ghost {{
  background: transparent;
  color: var(--text);
  border-color: var(--line);
}}
input,
textarea {{
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 14px 16px;
  background: var(--surface-strong);
  color: var(--text);
  font: inherit;
}}
textarea {{
  min-height: 148px;
  resize: vertical;
}}
.site-footer {{
  padding-top: 0;
  padding-bottom: 26px;
  color: var(--muted);
}}
@media (max-width: 980px) {{
  .portfolio-hero,
  .about-shell,
  .contact-shell,
  .project-grid,
  .gallery-grid {{
    grid-template-columns: 1fr;
  }}
  .hero-copy h1 {{
    max-width: none;
  }}
}}
@media (max-width: 720px) {{
  .site-header,
  .container,
  .site-footer {{
    padding-left: 18px;
    padding-right: 18px;
  }}
  .topbar {{
    flex-direction: column;
    align-items: flex-start;
  }}
  .hero-copy,
  .hero-panel,
  .section-shell {{
    border-radius: 22px;
    padding: 22px;
  }}
  .hero-metrics {{
    grid-template-columns: 1fr;
  }}
}}
"""

    js_lines = [
        "document.addEventListener('DOMContentLoaded', () => {",
        "  const qs = (id) => document.getElementById(id);",
        "  for (const link of document.querySelectorAll('[data-scroll]')) {",
        "    link.addEventListener('click', (event) => {",
        "      const href = link.getAttribute('href') || '';",
        "      if (!href.startsWith('#')) return;",
        "      const target = document.querySelector(href);",
        "      if (!target) return;",
        "      event.preventDefault();",
        "      target.scrollIntoView({ behavior: 'smooth', block: 'start' });",
        "    });",
        "  }",
    ]
    if features.get("theme_toggle"):
        js_lines.extend(
            [
                "  const themeToggle = qs('themeToggle');",
                "  themeToggle?.addEventListener('click', () => {",
                "    const current = document.body.getAttribute('data-theme') || 'light';",
                "    document.body.setAttribute('data-theme', current === 'dark' ? 'light' : 'dark');",
                "  });",
            ]
        )
    if features.get("contact_form"):
        js_lines.extend(
            [
                "  const leadForm = qs('leadForm');",
                "  const leadStatus = qs('leadStatus');",
                "  leadForm?.addEventListener('submit', (event) => {",
                "    event.preventDefault();",
                "    if (leadStatus) leadStatus.textContent = 'Mesaj alindi. Geri donus yapilacak.';",
                "    leadForm.reset();",
                "  });",
            ]
        )
    if features.get("motion"):
        js_lines.extend(
            [
                "  if (window.gsap) {",
                "    if (window.ScrollTrigger) window.gsap.registerPlugin(window.ScrollTrigger);",
                "    window.gsap.from('.portfolio-hero', { opacity: 0, y: 20, duration: 0.9, ease: 'power2.out' });",
                "    document.querySelectorAll('.reveal').forEach((node, index) => {",
                "      window.gsap.from(node, {",
                "        opacity: 0,",
                "        y: 26,",
                "        duration: 0.72,",
                "        delay: Math.min(index * 0.05, 0.22),",
                "        scrollTrigger: window.ScrollTrigger ? { trigger: node, start: 'top 90%' } : undefined,",
                "      });",
                "    });",
                "  }",
            ]
        )
    js_lines.extend(["  console.log('Elyan dynamic scaffold ready');", "});"])
    return html, css, "\n".join(js_lines) + "\n"


def _build_vanilla_assets(project_name: str, brief: str, theme: str) -> tuple[str, str, str, dict[str, Any]]:
    profile = _derive_web_profile(project_name, brief, theme)
    if profile.get("layout") == "portfolio":
        html, css, js = _build_portfolio_assets(profile)
        return html, css, js, profile

    palette = profile["palette"]
    features = profile["features"]
    sections = profile["sections"]

    section_cards = []
    for idx, section in enumerate(sections, start=1):
        section_cards.append(
            (
                f"<article class='info-card'>"
                f"<h3>{_escape_html(section)}</h3>"
                f"<p>{_escape_html(profile['subtitle'])}</p>"
                f"<span class='index-badge'>0{idx}</span>"
                f"</article>"
            )
        )
    section_cards_html = "\n        ".join(section_cards)

    widgets: list[str] = []
    if features.get("counter"):
        widgets.append(
            """
        <section class="tool-card" id="counterWidget" aria-live="polite">
          <h3>Sayaç</h3>
          <p class="tool-subtitle">Etkileşimli sayaç modülü</p>
          <div id="counterValue" class="counter-value">0</div>
          <div class="counter-actions">
            <button id="decreaseBtn" type="button" class="btn secondary">- Azalt</button>
            <button id="increaseBtn" type="button" class="btn primary">+ Artır</button>
          </div>
          <button id="resetBtn" type="button" class="btn ghost">Sıfırla</button>
        </section>
"""
        )
    if features.get("todo"):
        widgets.append(
            """
        <section class="tool-card">
          <h3>Yapılacaklar</h3>
          <p class="tool-subtitle">Hızlı görev listesi</p>
          <div class="todo-row">
            <input id="todoInput" type="text" placeholder="Görev ekle..." />
            <button id="todoAddBtn" type="button" class="btn primary">Ekle</button>
          </div>
          <ul id="todoList" class="todo-list"></ul>
        </section>
"""
        )
    if features.get("search"):
        widgets.append(
            """
        <section class="tool-card">
          <h3>Arama</h3>
          <p class="tool-subtitle">Örnek içerik filtresi</p>
          <input id="searchInput" type="search" placeholder="Filtrele..." />
          <ul id="searchList" class="search-list">
            <li>Görev planlama</li>
            <li>Rapor üretimi</li>
            <li>Kanal yönetimi</li>
            <li>Tool yürütme</li>
          </ul>
        </section>
"""
        )
    if features.get("timer"):
        widgets.append(
            """
        <section class="tool-card">
          <h3>Zamanlayıcı</h3>
          <p class="tool-subtitle">Pomodoro benzeri kısa sayaç</p>
          <div id="timerValue" class="timer-value">25:00</div>
          <div class="counter-actions">
            <button id="timerStartBtn" type="button" class="btn primary">Başlat</button>
            <button id="timerResetBtn" type="button" class="btn secondary">Sıfırla</button>
          </div>
        </section>
"""
        )
    if features.get("contact_form"):
        widgets.append(
            """
        <section class="tool-card">
          <h3>İletişim</h3>
          <form id="leadForm" class="lead-form">
            <input name="name" type="text" placeholder="Ad Soyad" required />
            <input name="email" type="email" placeholder="E-posta" required />
            <textarea name="message" rows="3" placeholder="Mesaj"></textarea>
            <button type="submit" class="btn primary">Gönder</button>
            <p id="leadStatus" class="tool-subtitle"></p>
          </form>
        </section>
"""
        )
    if not widgets:
        widgets.append(
            """
        <section class="tool-card">
          <h3>Hızlı Not</h3>
          <p class="tool-subtitle">Bu alan brief'e göre özelleştirilebilir.</p>
          <textarea rows="4" placeholder="Notlar..."></textarea>
        </section>
"""
        )
    widgets_html = "\n".join(widgets)

    theme_toggle = ""
    if features.get("theme_toggle"):
        theme_toggle = '<button id="themeToggle" type="button" class="btn ghost small">Tema Değiştir</button>'

    tailwind_cdn = ""
    gsap_cdn = ""
    if features.get("tailwind"):
        tailwind_cdn = '  <script src="https://cdn.tailwindcss.com"></script>\n'
    if features.get("motion"):
        gsap_cdn = (
            '  <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"></script>\n'
            '  <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/ScrollTrigger.min.js"></script>\n'
        )

    gallery_block = ""
    if features.get("gallery_mode"):
        gallery_block = """
    <section class="gallery-grid" aria-label="Fotoğraf Galerisi">
      <figure class="gallery-item reveal"><img src="https://images.unsplash.com/photo-1517841905240-472988babdf9?auto=format&fit=crop&w=1200&q=80" alt="Galeri görseli 1" loading="lazy" /><figcaption>Öne Çıkan Görsel</figcaption></figure>
      <figure class="gallery-item reveal"><img src="https://images.unsplash.com/photo-1518717758536-85ae29035b6d?auto=format&fit=crop&w=1200&q=80" alt="Galeri görseli 2" loading="lazy" /><figcaption>Doğal Işık</figcaption></figure>
      <figure class="gallery-item reveal"><img src="https://images.unsplash.com/photo-1507146426996-ef05306b995a?auto=format&fit=crop&w=1200&q=80" alt="Galeri görseli 3" loading="lazy" /><figcaption>Yaratıcı Kare</figcaption></figure>
    </section>
"""

    html = f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_escape_html(profile['title'])}</title>
  <meta name="description" content="{_escape_html(profile['subtitle'])}">
{tailwind_cdn}{gsap_cdn}  <link rel="stylesheet" href="./styles/main.css">
</head>
<body data-style="{_escape_html(profile['style'])}">
  <header class="site-header">
    <div>
      <p class="eyebrow">Elyan Dynamic Scaffold</p>
      <h1>{_escape_html(profile['title'])}</h1>
      <p class="lead">{_escape_html(profile['subtitle'])}</p>
    </div>
    <div class="header-actions">
      {theme_toggle}
      <button type="button" class="btn primary">{_escape_html(profile['cta'])}</button>
    </div>
  </header>

  <main class="container">
    <section class="grid-sections">
      {section_cards_html}
    </section>
{gallery_block}
    <section class="tool-grid">
{widgets_html}
    </section>
  </main>

  <script src="./scripts/main.js"></script>
</body>
</html>
"""

    css = f""":root {{
  --bg-start: {palette['bg1']};
  --bg-end: {palette['bg2']};
  --surface: #ffffff;
  --text: #0f172a;
  --muted: #64748b;
  --border: #dbe3ee;
  --accent: {palette['accent']};
  --accent-2: {palette['accent2']};
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: "Avenir Next", "Segoe UI", sans-serif;
  color: var(--text);
  background: radial-gradient(circle at top, var(--bg-start), var(--bg-end));
}}
body[data-theme="dark"] {{
  --surface: #0f172a;
  --text: #e2e8f0;
  --muted: #94a3b8;
  --border: #1e293b;
  --bg-start: #0b1120;
  --bg-end: #020617;
}}
.site-header {{
  display: flex;
  gap: 16px;
  justify-content: space-between;
  align-items: flex-start;
  padding: 36px 28px 18px;
}}
.eyebrow {{ margin: 0; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }}
h1 {{ margin: 6px 0; font-size: clamp(28px, 4vw, 42px); }}
.lead {{ margin: 0; max-width: 760px; color: var(--muted); }}
.header-actions {{ display: flex; gap: 10px; align-items: center; }}
.container {{ padding: 0 28px 30px; max-width: 1200px; margin: 0 auto; }}
.grid-sections {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}}
.info-card {{
  position: relative;
  padding: 18px;
  border-radius: 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  min-height: 140px;
}}
.index-badge {{
  position: absolute;
  right: 12px;
  top: 10px;
  color: var(--muted);
  font-size: 12px;
}}
.tool-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}}
.gallery-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin: 0 0 16px;
}}
.gallery-item {{
  margin: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
}}
.gallery-item img {{
  width: 100%;
  height: 220px;
  object-fit: cover;
  display: block;
}}
.gallery-item figcaption {{
  padding: 10px 12px;
  color: var(--muted);
  font-size: 13px;
}}
.tool-card {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
}}
.tool-subtitle {{ color: var(--muted); margin-top: -6px; }}
.btn {{
  appearance: none;
  border: 1px solid transparent;
  border-radius: 11px;
  padding: 10px 12px;
  font-size: 14px;
  cursor: pointer;
}}
.btn.small {{ font-size: 12px; padding: 8px 10px; }}
.btn.primary {{ background: var(--accent); color: #fff; }}
.btn.secondary {{ background: #fff; border-color: var(--border); color: var(--text); }}
.btn.ghost {{ background: #f1f5f9; color: var(--text); }}
.counter-value {{
  margin: 12px 0 10px;
  font-size: 52px;
  font-weight: 700;
  line-height: 1;
}}
.counter-actions {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}}
.todo-row {{ display: grid; grid-template-columns: 1fr auto; gap: 8px; }}
input, textarea {{
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px;
  background: #fff;
  color: #0f172a;
}}
body[data-theme="dark"] input,
body[data-theme="dark"] textarea {{
  background: #111827;
  color: #e5e7eb;
  border-color: #374151;
}}
.todo-list, .search-list {{ margin: 10px 0 0; padding-left: 20px; }}
.timer-value {{ margin: 10px 0 12px; font-size: 36px; font-weight: 700; }}
@media (max-width: 720px) {{
  .site-header {{ flex-direction: column; }}
  .header-actions {{ width: 100%; justify-content: flex-start; }}
}}
"""

    js_lines = [
        "document.addEventListener('DOMContentLoaded', () => {",
        "  const qs = (id) => document.getElementById(id);",
    ]
    if features.get("theme_toggle"):
        js_lines.extend(
            [
                "  const themeToggle = qs('themeToggle');",
                "  themeToggle?.addEventListener('click', () => {",
                "    const current = document.body.getAttribute('data-theme') || 'light';",
                "    document.body.setAttribute('data-theme', current === 'dark' ? 'light' : 'dark');",
                "  });",
            ]
        )
    if features.get("counter"):
        js_lines.extend(
            [
                "  let count = 0;",
                "  const counterNode = qs('counterValue');",
                "  const renderCounter = () => { if (counterNode) counterNode.textContent = String(count); };",
                "  qs('increaseBtn')?.addEventListener('click', () => { count += 1; renderCounter(); });",
                "  qs('decreaseBtn')?.addEventListener('click', () => { count -= 1; renderCounter(); });",
                "  qs('resetBtn')?.addEventListener('click', () => { count = 0; renderCounter(); });",
                "  renderCounter();",
            ]
        )
    if features.get("todo"):
        js_lines.extend(
            [
                "  const todoInput = qs('todoInput');",
                "  const todoList = qs('todoList');",
                "  const pushTodo = () => {",
                "    const v = (todoInput?.value || '').trim();",
                "    if (!v || !todoList) return;",
                "    const li = document.createElement('li');",
                "    li.textContent = v;",
                "    li.addEventListener('click', () => li.remove());",
                "    todoList.appendChild(li);",
                "    todoInput.value = '';",
                "  };",
                "  qs('todoAddBtn')?.addEventListener('click', pushTodo);",
                "  todoInput?.addEventListener('keydown', (e) => { if (e.key === 'Enter') pushTodo(); });",
            ]
        )
    if features.get("search"):
        js_lines.extend(
            [
                "  const searchInput = qs('searchInput');",
                "  const searchList = qs('searchList');",
                "  searchInput?.addEventListener('input', () => {",
                "    const q = (searchInput.value || '').toLowerCase();",
                "    for (const li of searchList?.querySelectorAll('li') || []) {",
                "      li.style.display = li.textContent.toLowerCase().includes(q) ? '' : 'none';",
                "    }",
                "  });",
            ]
        )
    if features.get("timer"):
        js_lines.extend(
            [
                "  let timerSec = 25 * 60;",
                "  let timerRef = null;",
                "  const timerNode = qs('timerValue');",
                "  const renderTimer = () => {",
                "    if (!timerNode) return;",
                "    const m = String(Math.floor(timerSec / 60)).padStart(2, '0');",
                "    const s = String(timerSec % 60).padStart(2, '0');",
                "    timerNode.textContent = `${m}:${s}`;",
                "  };",
                "  qs('timerStartBtn')?.addEventListener('click', () => {",
                "    if (timerRef) return;",
                "    timerRef = setInterval(() => {",
                "      timerSec = Math.max(0, timerSec - 1);",
                "      renderTimer();",
                "      if (timerSec === 0) { clearInterval(timerRef); timerRef = null; }",
                "    }, 1000);",
                "  });",
                "  qs('timerResetBtn')?.addEventListener('click', () => {",
                "    timerSec = 25 * 60;",
                "    if (timerRef) { clearInterval(timerRef); timerRef = null; }",
                "    renderTimer();",
                "  });",
                "  renderTimer();",
            ]
        )
    if features.get("contact_form"):
        js_lines.extend(
            [
                "  const leadForm = qs('leadForm');",
                "  const leadStatus = qs('leadStatus');",
                "  leadForm?.addEventListener('submit', (e) => {",
                "    e.preventDefault();",
                "    if (leadStatus) leadStatus.textContent = 'Mesaj alındı. Teşekkürler.';",
                "    leadForm.reset();",
                "  });",
            ]
        )
    if features.get("motion"):
        js_lines.extend(
            [
                "  if (window.gsap) {",
                "    if (window.ScrollTrigger) window.gsap.registerPlugin(window.ScrollTrigger);",
                "    window.gsap.from('.site-header', { opacity: 0, y: -20, duration: 0.8, ease: 'power2.out' });",
                "    const reveals = document.querySelectorAll('.reveal, .info-card, .tool-card');",
                "    reveals.forEach((node, idx) => {",
                "      window.gsap.from(node, {",
                "        opacity: 0,",
                "        y: 18,",
                "        duration: 0.6,",
                "        delay: Math.min(idx * 0.04, 0.24),",
                "        scrollTrigger: window.ScrollTrigger ? { trigger: node, start: 'top 92%' } : undefined,",
                "      });",
                "    });",
                "  }",
            ]
        )

    js_lines.extend(["  console.log('Elyan dynamic scaffold ready');", "});"])
    js = "\n".join(js_lines) + "\n"
    return html, css, js, profile


def _default_run_commands(project_kind: str, stack: str) -> list[str]:
    kind = str(project_kind or "app").strip().lower()
    tech = str(stack or "python").strip().lower()

    if kind == "website":
        if tech == "nextjs":
            return ["npm install", "npm run dev", "npm run build"]
        if tech == "react":
            return ["npm install", "npm run dev", "npm run build"]
        return ["python3 -m http.server 8080"]

    if kind == "game":
        return ["python3 -m venv .venv", "source .venv/bin/activate", "pip install -r requirements.txt", "python src/main.py"]

    if tech in {"node", "express"}:
        return ["npm install", "npm run dev", "npm test"]
    return ["python3 -m venv .venv", "source .venv/bin/activate", "pip install -r requirements.txt", "pytest -q"]


def _complexity_profile(level: str) -> dict[str, Any]:
    normalized = str(level or "advanced").strip().lower()
    if normalized not in {"standard", "advanced", "expert"}:
        normalized = "advanced"

    profiles = {
        "standard": {
            "quality_gates": [
                "Lint + static checks green",
                "Core user flow manual test",
                "Basic README and run steps complete",
            ],
            "iterations": 2,
        },
        "advanced": {
            "quality_gates": [
                "Lint + static checks green",
                "Critical path unit/integration tests pass",
                "Performance smoke metrics collected",
                "Deployment checklist completed",
            ],
            "iterations": 3,
        },
        "expert": {
            "quality_gates": [
                "Lint + static checks green",
                "Core + edge-case tests with target coverage",
                "Security checklist + dependency scan clean",
                "Performance baseline and regression guard documented",
                "Rollback plan + production runbook ready",
            ],
            "iterations": 4,
        },
    }
    out = dict(profiles[normalized])
    out["complexity"] = normalized
    return out


def _first_existing(paths: list[Path]) -> Path | None:
    for candidate in paths:
        if candidate.exists():
            return candidate
    return None


def _check_item(check_id: str, title: str, ok: bool, details: str) -> dict[str, Any]:
    return {
        "id": check_id,
        "title": title,
        "ok": bool(ok),
        "details": str(details or "").strip(),
    }


def _detect_web_multi_skeleton(project_dir: Path) -> tuple[bool, str]:
    root_files = [project_dir / name for name in ("styles.css", "script.js", "main.js", "app.js")]
    nested_files = [project_dir / "styles" / "main.css", project_dir / "scripts" / "main.js"]
    root_present = [str(path.relative_to(project_dir)) for path in root_files if path.exists()]
    nested_present = [str(path.relative_to(project_dir)) for path in nested_files if path.exists()]
    mixed = bool(root_present and nested_present)
    if not mixed:
        return False, ""
    return True, f"root={', '.join(root_present)}; nested={', '.join(nested_present)}"


async def create_web_project_scaffold(
    project_name: str,
    stack: str = "vanilla",
    theme: str = "professional",
    output_dir: str = "~/Desktop",
    brief: str = "",
) -> dict[str, Any]:
    """
    Create a production-oriented web starter project.
    """
    try:
        valid, msg, base_dir = validate_path(output_dir)
        if not valid or base_dir is None:
            return {"success": False, "error": msg}

        slug = _safe_project_slug(project_name)
        project_dir = (base_dir / slug).resolve()
        if project_dir.exists():
            existing_entries = [item for item in project_dir.iterdir()]
            if existing_entries:
                existing_preview = ", ".join(sorted(item.name for item in existing_entries)[:8])
                return {
                    "success": False,
                    "error": f"Project directory already exists and is not empty: {project_dir}",
                    "error_code": "PROJECT_DIR_NOT_EMPTY",
                    "project_dir": str(project_dir),
                    "existing_entries": existing_preview,
                }
        project_dir.mkdir(parents=True, exist_ok=True)

        # Initial scope: robust static scaffold, can be extended per stack.
        actual_stack = stack.strip().lower() or "vanilla"
        if actual_stack not in {"vanilla", "react", "nextjs"}:
            actual_stack = "vanilla"

        index_html = f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{project_name}</title>
  <meta name="description" content="{project_name} web projesi">
  <link rel="stylesheet" href="./styles/main.css">
</head>
<body>
  <header class="site-header">
    <h1>{project_name}</h1>
    <p>Elyan Professional Scaffold ({actual_stack})</p>
  </header>

  <main class="container">
    <section class="card">
      <h2>Baslangic</h2>
      <p>Bu proje, profesyonel gelistirme akisina uygun baslangic dosyalari ile olusturuldu.</p>
    </section>
  </main>

  <script src="./scripts/main.js"></script>
</body>
</html>
"""

        style_css = f""":root {{
  --bg: #f8fafc;
  --text: #0f172a;
  --muted: #64748b;
  --card: #ffffff;
  --border: #e2e8f0;
}}

* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: "Avenir Next", "Segoe UI", sans-serif;
  color: var(--text);
  background: linear-gradient(180deg, #ffffff 0%, var(--bg) 100%);
}}
.site-header {{ padding: 40px 24px 20px; }}
.site-header p {{ color: var(--muted); }}
.container {{ padding: 0 24px 32px; max-width: 980px; }}
.card {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
}}
"""

        script_js = """document.addEventListener("DOMContentLoaded", () => {
  console.log("Elyan scaffold ready");
});
"""

        brief_text = _brief_excerpt(brief, fallback="No explicit brief provided.")

        readme_md = f"""# {project_name}

## Stack
- {actual_stack}

## Quick Start
1. `cd "{project_dir}"`
2. Kurulum komutlari stack'e gore degisir (asagida).

## Structure
- `index.html`
- `styles/main.css`
- `scripts/main.js`
- `README.md`
- `docs/IMPLEMENTATION_PLAN.md`
"""

        implementation_md = f"""# Implementation Plan

Generated: {datetime.now().isoformat()}

## Objective
{project_name} icin profesyonel bir web uygulama temeli.

## Design Direction
- Theme: {theme}
- Stack: {actual_stack}
- Priority: responsive layout, maintainable structure
- Brief: {brief_text}

## Next Steps
1. Bilgi mimarisi ve sayfa bolumlerini netlestir.
2. Bilesen yapisini ayristir.
3. Performans ve erisilebilirlik kontrollerini ekle.
4. Gerekirse framework tabanli migrasyon (React/Next.js) yap.
"""

        (project_dir / "styles").mkdir(exist_ok=True)
        (project_dir / "scripts").mkdir(exist_ok=True)
        (project_dir / "docs").mkdir(exist_ok=True)

        files_written = []
        if actual_stack == "react":
            react_pkg = f"""{{
  "name": "{slug.lower()}",
  "version": "0.1.0",
  "private": true,
  "scripts": {{
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  }},
  "dependencies": {{
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  }},
  "devDependencies": {{
    "vite": "^5.4.0",
    "@vitejs/plugin-react": "^4.3.1"
  }}
}}
"""
            vite_cfg = """import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
})
"""
            react_main = """import React from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import App from './App'

createRoot(document.getElementById('root')).render(<App />)
"""
            react_app = f"""export default function App() {{
  return (
    <main style={{{{padding: '32px', fontFamily: 'Avenir Next, Segoe UI, sans-serif'}}}}>
      <h1>{project_name}</h1>
      <p>Elyan React professional scaffold hazır.</p>
    </main>
  )
}}
"""
            react_css = """body { margin: 0; background: #f8fafc; color: #0f172a; }
* { box-sizing: border-box; }
"""
            react_html = """<!doctype html>
<html lang="tr">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Elyan React Scaffold</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
"""
            readme_md += """

## React Start
1. `npm install`
2. `npm run dev`
3. `http://localhost:5173`
"""
            (project_dir / "src").mkdir(exist_ok=True)
            file_map = {
                project_dir / "index.html": react_html,
                project_dir / "package.json": react_pkg,
                project_dir / "vite.config.js": vite_cfg,
                project_dir / "src" / "main.jsx": react_main,
                project_dir / "src" / "App.jsx": react_app,
                project_dir / "src" / "styles.css": react_css,
                project_dir / "README.md": readme_md,
                project_dir / "docs" / "IMPLEMENTATION_PLAN.md": implementation_md,
            }
        elif actual_stack == "nextjs":
            next_pkg = f"""{{
  "name": "{slug.lower()}",
  "version": "0.1.0",
  "private": true,
  "scripts": {{
    "dev": "next dev",
    "build": "next build",
    "start": "next start"
  }},
  "dependencies": {{
    "next": "^14.2.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  }}
}}
"""
            next_page = f"""export default function Page() {{
  return (
    <main style={{{{padding: '32px', fontFamily: 'Avenir Next, Segoe UI, sans-serif'}}}}>
      <h1>{project_name}</h1>
      <p>Elyan Next.js professional scaffold hazır.</p>
    </main>
  )
}}
"""
            next_layout = """export const metadata = {
  title: 'Elyan Next Scaffold',
  description: 'Professional starter generated by Elyan',
}

export default function RootLayout({ children }) {
  return (
    <html lang="tr">
      <body>{children}</body>
    </html>
  )
}
"""
            readme_md += """

## Next.js Start
1. `npm install`
2. `npm run dev`
3. `http://localhost:3000`
"""
            (project_dir / "app").mkdir(exist_ok=True)
            file_map = {
                project_dir / "package.json": next_pkg,
                project_dir / "app" / "layout.js": next_layout,
                project_dir / "app" / "page.js": next_page,
                project_dir / "README.md": readme_md,
                project_dir / "docs" / "IMPLEMENTATION_PLAN.md": implementation_md,
            }
        else:
            index_html, style_css, script_js, profile = _build_vanilla_assets(
                project_name=project_name,
                brief=brief,
                theme=theme,
            )
            enabled_features = [k for k, v in (profile.get("features", {}) or {}).items() if bool(v)]
            readme_md += "\n\n## Derived Profile\n"
            readme_md += f"- Layout: {profile.get('layout', 'landing')}\n"
            readme_md += f"- Style: {profile.get('style', 'professional')}\n"
            readme_md += f"- Features: {', '.join(enabled_features) if enabled_features else 'baseline'}\n"
            readme_md += f"- Brief: {brief_text}\n"
            implementation_md += (
                "\n\n## Derived Runtime Profile\n"
                f"- Layout: {profile.get('layout', 'landing')}\n"
                f"- Style: {profile.get('style', 'professional')}\n"
                f"- Sections: {', '.join(profile.get('sections', []))}\n"
                f"- Enabled features: {', '.join(enabled_features) if enabled_features else 'baseline'}\n"
            )
            readme_md += """

## Static Start
1. `python3 -m http.server 8080`
2. `http://localhost:8080`
"""
            file_map = {
                project_dir / "index.html": index_html,
                project_dir / "styles" / "main.css": style_css,
                project_dir / "scripts" / "main.js": script_js,
                project_dir / "README.md": readme_md,
                project_dir / "docs" / "IMPLEMENTATION_PLAN.md": implementation_md,
            }

        for path, content in file_map.items():
            if not str(content or "").strip():
                return {
                    "success": False,
                    "error": f"EMPTY_CONTENT_BLOCKED: {path.name} icin bos icerik uretildi.",
                    "error_code": "EMPTY_CONTENT_BLOCKED",
                }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            files_written.append(str(path))

        empty_files = [item for item in files_written if Path(item).exists() and Path(item).stat().st_size == 0]
        if empty_files:
            return {
                "success": False,
                "error": f"SCAFFOLD_VERIFY_FAILED: Bos dosyalar bulundu: {', '.join(empty_files)}",
                "error_code": "SCAFFOLD_VERIFY_FAILED",
                "files_created": files_written,
            }

        preview_source = ""
        if files_written:
            try:
                preview_source = Path(files_written[0]).read_text(encoding="utf-8", errors="ignore")[:200]
            except Exception:
                preview_source = ""
        total_bytes = sum(Path(item).stat().st_size for item in files_written if Path(item).exists())
        digest = hashlib.sha256("".join(sorted(files_written)).encode("utf-8")).hexdigest()

        return {
            "success": True,
            "ok": True,
            "project_name": project_name,
            "stack": actual_stack,
            "theme": theme,
            "brief": brief,
            "path": str(project_dir),
            "project_dir": str(project_dir),
            "files_created": files_written,
            "bytes_written": total_bytes,
            "sha256": digest,
            "preview_200_chars": preview_source,
            "message": f"Web scaffold olusturuldu: {project_dir}",
        }
    except Exception as exc:
        logger.error(f"create_web_project_scaffold error: {exc}")
        return {"success": False, "error": str(exc)}


async def create_coding_delivery_plan(
    project_path: str,
    project_name: str = "",
    project_kind: str = "app",
    stack: str = "python",
    complexity: str = "advanced",
    brief: str = "",
) -> dict[str, Any]:
    """
    Generate professional delivery planning docs for complex coding tasks.
    """
    try:
        target = Path(str(project_path or "")).expanduser()
        if not target.exists():
            return {"success": False, "error": f"Project path bulunamadı: {target}"}
        if not target.is_dir():
            return {"success": False, "error": f"Project path klasör olmalı: {target}"}

        kind = str(project_kind or "app").strip().lower()
        if kind not in {"website", "app", "game"}:
            kind = "app"
        tech = str(stack or "python").strip().lower() or "python"
        name = str(project_name or "").strip() or target.name
        profile = _complexity_profile(complexity)
        now = datetime.now().isoformat()

        docs_dir = target / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)

        phase_rows = [
            ("1", "Discovery", "Hedef, kapsam, kullanıcı akışları", "Problem ve başarı metrikleri net"),
            ("2", "Architecture", "Teknik kararlar, modül sınırları", "Mimari kararlar ve trade-off dokümante"),
            ("3", "Implementation", "Kodlama, refactor, tool entegrasyonu", "Özellikler branch düzeyinde tamam"),
            ("4", "Verification", "Test, performans, güvenlik", "Kalite kapıları geçildi"),
            ("5", "Delivery", "Deploy/runbook/handover", "Çalışır teslimat + rollback planı"),
        ]

        delivery_plan = docs_dir / "DELIVERY_PLAN.md"
        delivery_plan.write_text(
            "\n".join(
                [
                    f"# Delivery Plan - {name}",
                    "",
                    f"- Generated: {now}",
                    f"- Project Kind: {kind}",
                    f"- Stack: {tech}",
                    f"- Complexity: {profile['complexity']}",
                    f"- Iteration Target: {profile['iterations']}",
                    "",
                    "## Brief",
                    str(brief or "No explicit brief provided."),
                    "",
                    "## Phase Plan",
                    "| Phase | Name | Focus | Exit Criteria |",
                    "|---|---|---|---|",
                    *[f"| {pid} | {pname} | {focus} | {exitc} |" for pid, pname, focus, exitc in phase_rows],
                ]
            ),
            encoding="utf-8",
        )

        backlog = docs_dir / "TASK_BACKLOG.md"
        backlog.write_text(
            "\n".join(
                [
                    f"# Task Backlog - {name}",
                    "",
                    "| ID | Task | Owner | Priority | Status |",
                    "|---|---|---|---|---|",
                    "| T1 | Contract and scope freeze | Product/PM | High | Open |",
                    "| T2 | Architecture and component boundaries | Tech Lead | High | Open |",
                    "| T3 | Core feature implementation | Dev | High | Open |",
                    "| T4 | Integration + regression tests | QA | High | Open |",
                    "| T5 | Performance & security checks | DevOps | Medium | Open |",
                    "| T6 | Release checklist and runbook | DevOps | Medium | Open |",
                ]
            ),
            encoding="utf-8",
        )

        acceptance = docs_dir / "ACCEPTANCE_CRITERIA.md"
        criteria = [
            "Primary user flow works end-to-end without manual patching.",
            "Critical commands or UI actions have deterministic outcomes.",
            "All required configs and run commands are documented.",
            "Project starts locally with listed setup commands.",
        ]
        if kind == "website":
            criteria.extend(
                [
                    "index.html must have at least 3 distinct semantic sections (nav, main, footer).",
                    "styles.css must include at least one responsive media query breakpoint.",
                    "app.js must contain a DOMContentLoaded or equivalent event handler.",
                    "At least one interactive feature (form, toggle, filter) must be functional.",
                    "Client-side errors are zero in console on core pages.",
                ]
            )
        if profile["complexity"] == "expert":
            criteria.extend(
                [
                    "Coverage target and regression guard are documented.",
                    "Security scan/dependency audit result is recorded.",
                ]
            )
        acceptance.write_text(
            "\n".join(
                [
                    f"# Acceptance Criteria - {name}",
                    "",
                    *[f"- [ ] {c}" for c in criteria],
                ]
            ),
            encoding="utf-8",
        )

        test_strategy = docs_dir / "TEST_STRATEGY.md"
        test_strategy.write_text(
            "\n".join(
                [
                    f"# Test Strategy - {name}",
                    "",
                    "## Layers",
                    "- Unit tests for deterministic logic and parsing.",
                    "- Integration tests for workflow/tool boundaries.",
                    "- Smoke test for startup and core flow.",
                    "",
                    "## Quality Gates",
                    *[f"- [ ] {gate}" for gate in profile["quality_gates"]],
                ]
            ),
            encoding="utf-8",
        )

        runbook = docs_dir / "RUNBOOK.md"
        runbook.write_text(
            "\n".join(
                [
                    f"# Runbook - {name}",
                    "",
                    "## Local Run Commands",
                    *[f"1. `{cmd}`" if i == 0 else f"{i+1}. `{cmd}`" for i, cmd in enumerate(_default_run_commands(kind, tech))],
                    "",
                    "## Incident Notes",
                    "- If startup fails, capture logs and last command output.",
                    "- Keep rollback path: previous known-good commit/tag.",
                ]
            ),
            encoding="utf-8",
        )

        files_created = [
            str(delivery_plan),
            str(backlog),
            str(acceptance),
            str(test_strategy),
            str(runbook),
        ]
        return {
            "success": True,
            "project_path": str(target),
            "project_name": name,
            "project_kind": kind,
            "stack": tech,
            "complexity": profile["complexity"],
            "files_created": files_created,
            "message": f"Coding delivery plan oluşturuldu: {docs_dir}",
        }
    except Exception as exc:
        logger.error(f"create_coding_delivery_plan error: {exc}")
        return {"success": False, "error": str(exc)}


async def create_coding_verification_report(
    project_path: str,
    project_name: str = "",
    project_kind: str = "app",
    stack: str = "python",
    strict: bool = False,
) -> dict[str, Any]:
    """
    Generate a practical verification report for created coding projects.
    """
    try:
        target = Path(str(project_path or "")).expanduser()
        if not target.exists():
            return {"success": False, "error": f"Project path bulunamadı: {target}"}
        if not target.is_dir():
            return {"success": False, "error": f"Project path klasör olmalı: {target}"}

        kind = str(project_kind or "app").strip().lower()
        if kind not in {"website", "app", "game"}:
            kind = "app"
        tech = str(stack or "python").strip().lower() or "python"
        name = str(project_name or "").strip() or target.name

        checks: list[dict[str, Any]] = []
        docs_dir = target / "docs"

        checks.append(
            _check_item(
                "base_dir",
                "Project directory exists",
                target.exists() and target.is_dir(),
                str(target),
            )
        )

        readme = target / "README.md"
        checks.append(_check_item("readme", "README.md present", readme.exists(), str(readme)))

        docs_core = [
            ("delivery_plan", "DELIVERY_PLAN.md", docs_dir / "DELIVERY_PLAN.md"),
            ("task_backlog", "TASK_BACKLOG.md", docs_dir / "TASK_BACKLOG.md"),
            ("acceptance", "ACCEPTANCE_CRITERIA.md", docs_dir / "ACCEPTANCE_CRITERIA.md"),
            ("test_strategy", "TEST_STRATEGY.md", docs_dir / "TEST_STRATEGY.md"),
            ("runbook", "RUNBOOK.md", docs_dir / "RUNBOOK.md"),
        ]
        for cid, title, p in docs_core:
            checks.append(_check_item(cid, f"{title} present", p.exists(), str(p)))

        if kind == "website":
            if tech == "nextjs":
                pkg = target / "package.json"
                page = _first_existing([target / "app" / "page.js", target / "app" / "page.tsx"])
                checks.append(_check_item("next_pkg", "package.json present", pkg.exists(), str(pkg)))
                checks.append(
                    _check_item(
                        "next_page",
                        "Next page entry present",
                        page is not None,
                        str(page or (target / "app" / "page.js")),
                    )
                )
            elif tech == "react":
                pkg = target / "package.json"
                app_entry = _first_existing([target / "src" / "App.jsx", target / "src" / "App.tsx"])
                main_entry = _first_existing([target / "src" / "main.jsx", target / "src" / "main.tsx"])
                checks.append(_check_item("react_pkg", "package.json present", pkg.exists(), str(pkg)))
                checks.append(
                    _check_item(
                        "react_app",
                        "React App entry present",
                        app_entry is not None,
                        str(app_entry or (target / "src" / "App.jsx")),
                    )
                )
                checks.append(
                    _check_item(
                        "react_main",
                        "React main entry present",
                        main_entry is not None,
                        str(main_entry or (target / "src" / "main.jsx")),
                    )
                )
            else:
                html = target / "index.html"
                css = target / "styles" / "main.css"
                js = target / "scripts" / "main.js"
                checks.append(_check_item("web_html", "index.html present", html.exists(), str(html)))
                checks.append(_check_item("web_css", "styles/main.css present", css.exists(), str(css)))
                checks.append(_check_item("web_js", "scripts/main.js present", js.exists(), str(js)))
                mixed, mixed_details = _detect_web_multi_skeleton(target)
                checks.append(_check_item("web_layout", "Single scaffold layout", not mixed, mixed_details or "root/nested layout consistent"))
                smoke = await verify_web_project_smoke_test(str(target))
                smoke_ok = bool(smoke.get("all_passed", False)) if isinstance(smoke, dict) else False
                smoke_details = str(smoke.get("message") or "") if isinstance(smoke, dict) else ""
                checks.append(_check_item("web_smoke", "Web smoke test", smoke_ok, smoke_details or "smoke test çalıştırıldı"))
        else:
            if tech in {"node", "express"}:
                pkg = target / "package.json"
                checks.append(_check_item("node_pkg", "package.json present", pkg.exists(), str(pkg)))
            else:
                req = _first_existing([target / "requirements.txt", target / "pyproject.toml"])
                checks.append(
                    _check_item(
                        "python_deps",
                        "Python dependency manifest present",
                        req is not None,
                        str(req or (target / "requirements.txt")),
                    )
                )
                entry = _first_existing([target / "src" / "main.py", target / "main.py", target / "app.py"])
                checks.append(
                    _check_item(
                        "python_entry",
                        "Python entrypoint present",
                        entry is not None,
                        str(entry or (target / "src" / "main.py")),
                    )
                )

        tests_dir = target / "tests"
        checks.append(_check_item("tests_dir", "tests/ directory present", tests_dir.exists(), str(tests_dir)))

        total_checks = len(checks)
        passed_checks = sum(1 for c in checks if c.get("ok"))
        failed_checks = [c for c in checks if not c.get("ok")]
        score = int(round((passed_checks / max(total_checks, 1)) * 100))

        status = "ready"
        if score < 70:
            status = "blocked"
        elif score < 90:
            status = "needs_review"
        if strict and failed_checks:
            status = "blocked"

        report_lines = [
            f"# Verification Report - {name}",
            "",
            f"- Generated: {datetime.now().isoformat()}",
            f"- Project Path: {target}",
            f"- Project Kind: {kind}",
            f"- Stack: {tech}",
            f"- Score: {score}/100",
            f"- Status: {status}",
            "",
            "## Check Results",
            "| ID | Check | Result | Details |",
            "|---|---|---|---|",
        ]
        for check in checks:
            result_mark = "PASS" if check["ok"] else "FAIL"
            report_lines.append(
                f"| {check['id']} | {check['title']} | {result_mark} | {check['details']} |"
            )

        report_lines.extend(["", "## Next Actions"])
        if not failed_checks:
            report_lines.append("- Tüm temel doğrulamalar geçti. Geliştirme ve test döngüsüne devam edebilirsin.")
        else:
            for miss in failed_checks[:10]:
                report_lines.append(f"- Eksik: {miss['title']} ({miss['details']})")
        report_lines.append("")
        report_lines.append("## Delivery Recommendation")
        if status == "ready":
            report_lines.append("- Proje teslimata hazır görünüyor. Son adım olarak smoke test + release check çalıştır.")
        elif status == "needs_review":
            report_lines.append("- Proje kısmen hazır. Kritik eksikleri tamamladıktan sonra yeniden doğrula.")
        else:
            report_lines.append("- Proje şu an teslimat için bloklu. Eksik temel dosyaları tamamlayıp tekrar doğrulama çalıştır.")

        docs_dir.mkdir(parents=True, exist_ok=True)
        report_path = docs_dir / "VERIFICATION_REPORT.md"
        report_path.write_text("\n".join(report_lines), encoding="utf-8")

        return {
            "success": True,
            "project_path": str(target),
            "project_name": name,
            "project_kind": kind,
            "stack": tech,
            "score": score,
            "status": status,
            "passed_checks": passed_checks,
            "total_checks": total_checks,
            "failed_checks": failed_checks,
            "report_path": str(report_path),
            "message": f"Verification raporu oluşturuldu: {report_path} (score={score})",
        }
    except Exception as exc:
        logger.error(f"create_coding_verification_report error: {exc}")
        return {"success": False, "error": str(exc)}


async def verify_web_project_smoke_test(
    project_path: str,
) -> dict[str, Any]:
    """
    Perform a technical smoke test on a generated static web project.
    Checks for structural integrity, broken asset links, and required metadata.
    """
    try:
        target = Path(str(project_path or "")).expanduser()
        if not target.exists() or not target.is_dir():
            return {"success": False, "error": f"Proje dizini bulunamadı: {project_path}"}

        html_file = target / "index.html"
        if not html_file.exists():
            return {"success": False, "error": "index.html bulunamadı."}

        content = html_file.read_text(encoding="utf-8")
        
        results = []
        # 1. Structure check
        has_head = "<head" in content.lower()
        has_body = "<body" in content.lower()
        results.append(_check_item("structure", "HTML Basic Structure", has_head and has_body, "Head/Body tags present"))

        # 2. Asset links check
        import re
        css_links = re.findall(r'href=["\'](.*\.css)["\']', content)
        js_links = re.findall(r'src=["\'](.*\.js)["\']', content)
        
        broken_assets = []
        for css in css_links:
            if not css.startswith(("http", "//")):
                p = (target / css).resolve()
                if not p.exists(): broken_assets.append(css)
        
        for js in js_links:
            if not js.startswith(("http", "//")):
                p = (target / js).resolve()
                if not p.exists(): broken_assets.append(js)

        results.append(_check_item("assets", "Local Asset Links", len(broken_assets) == 0, 
                                   f"Broken: {', '.join(broken_assets)}" if broken_assets else "All local assets exist"))

        # 3. Interactive features check
        has_js_init = "DOMContentLoaded" in content or 'src="./scripts/main.js"' in content
        results.append(_check_item("interactivity", "JS Initialization", has_js_init, "Main JS entry point found"))

        all_ok = all(r["ok"] for r in results)
        
        return {
            "success": True,
            "project_path": str(target),
            "all_passed": all_ok,
            "checks": results,
            "message": "Smoke test tamamlandı. " + ("Tüm kontroller başarılı." if all_ok else "Bazı sorunlar tespit edildi.")
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def generate_document_pack(
    topic: str,
    brief: str = "",
    audience: str = "executive",
    language: str = "tr",
    output_dir: str = "~/Desktop",
    preferred_formats: Any = None,
) -> dict[str, Any]:
    """
    Generate a user-focused document in the requested format(s).
    """
    try:
        valid, msg, base_dir = validate_path(output_dir)
        if not valid or base_dir is None:
            return {"success": False, "error": msg}

        if _looks_like_non_document_request(topic, brief):
            return {
                "success": False,
                "error": "Belge paketi için yeterli içerik/brief yok veya istek belge dışı görünüyor.",
                "error_code": "INVALID_DOCUMENT_BRIEF",
            }

        safe_topic = _safe_project_slug(topic).replace("_", " ")
        pack_dir = (base_dir / f"{_safe_project_slug(topic)}_document_pack").resolve()
        pack_dir.mkdir(parents=True, exist_ok=True)

        now_str = datetime.now().strftime("%Y-%m-%d")
        requested_formats = _infer_requested_document_formats(topic, brief, preferred_formats=preferred_formats)
        paragraphs = _build_plain_document_paragraphs(safe_topic, brief or topic, audience=audience)
        body_text = "\n\n".join(paragraphs).strip()
        document_sections: list[dict[str, Any]] = []
        if paragraphs:
            document_sections.append(
                {
                    "title": "Kısa Özet",
                    "paragraphs": [{"text": paragraphs[0], "claim_ids": []}],
                }
            )
            if len(paragraphs) > 1:
                document_sections.append(
                    {
                        "title": "İçerik",
                        "paragraphs": [{"text": para, "claim_ids": []} for para in paragraphs[1:]],
                    }
                )
        if not document_sections:
            document_sections = [{"title": "İçerik", "paragraphs": [{"text": body_text or safe_topic, "claim_ids": []}]}]

        manifest = build_office_content_manifest(
            title=safe_topic,
            topic=topic,
            brief=brief or topic,
            audience=audience,
            language=language,
            content_kind="document_pack",
            document_profile="executive",
            citation_mode="none",
            source_policy="trusted",
            sections=document_sections,
            notes=[f"Generated: {now_str}"] if now_str else [],
            metadata={"requested_formats": requested_formats, "stack": "generic_document_pack"},
        )
        sectioned_document = sections_to_sectioned_document(
            title=safe_topic,
            sections=document_sections,
            metadata={"office_content_manifest": manifest.to_dict()},
        )
        renderer = DocumentRenderer()
        manifest_path = pack_dir / "office_content_manifest.json"
        manifest_payload = manifest.to_dict()
        manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        outputs: list[str] = []
        warnings: list[str] = []

        if "docx" in requested_formats:
            docx_path = pack_dir / "DOCUMENT.docx"
            word_result = await renderer.render_to_path(sectioned_document, "docx", str(docx_path))
            if isinstance(word_result, dict) and word_result.get("success") and word_result.get("path"):
                outputs.append(str(word_result["path"]))
            else:
                warnings.append(str((word_result or {}).get("error") or "docx generation failed"))

        if "xlsx" in requested_formats:
            excel_path = pack_dir / "DOCUMENT.xlsx"
            excel_result = await renderer.render_to_path(sectioned_document, "xlsx", str(excel_path))
            if isinstance(excel_result, dict) and excel_result.get("success") and excel_result.get("path"):
                outputs.append(str(excel_result["path"]))
            else:
                warnings.append(str((excel_result or {}).get("error") or "excel generation failed"))

        if "pptx" in requested_formats:
            pptx_path = pack_dir / "DOCUMENT.pptx"
            pptx_result = await renderer.render_to_path(sectioned_document, "pptx", str(pptx_path))
            if isinstance(pptx_result, dict) and pptx_result.get("success") and pptx_result.get("path"):
                outputs.append(str(pptx_result["path"]))
            else:
                warnings.append(str((pptx_result or {}).get("error") or "pptx generation failed"))

        if "pdf" in requested_formats:
            pdf_path = pack_dir / "DOCUMENT.pdf"
            pdf_result = _write_simple_pdf(str(pdf_path), safe_topic, body_text)
            if isinstance(pdf_result, dict) and pdf_result.get("success") and pdf_result.get("path"):
                outputs.append(str(pdf_result["path"]))
            else:
                warnings.append(str((pdf_result or {}).get("error") or "pdf generation failed"))

        if "tex" in requested_formats:
            tex_path = pack_dir / "DOCUMENT.tex"
            tex_path.write_text(
                _build_latex_document(safe_topic, paragraphs or _build_plain_document_paragraphs(safe_topic, brief or topic, audience=audience)),
                encoding="utf-8",
            )
            outputs.append(str(tex_path))

        if "md" in requested_formats:
            md_path = pack_dir / "DOCUMENT.md"
            md_result = await renderer.render_to_path(sectioned_document, "md", str(md_path))
            if isinstance(md_result, dict) and md_result.get("success") and md_result.get("path"):
                outputs.append(str(md_result["path"]))
            else:
                warnings.append(str((md_result or {}).get("error") or "markdown generation failed"))

        if "html" in requested_formats:
            html_path = pack_dir / "DOCUMENT.html"
            html_result = await renderer.render_to_path(sectioned_document, "html", str(html_path))
            if isinstance(html_result, dict) and html_result.get("success") and html_result.get("path"):
                outputs.append(str(html_result["path"]))
            else:
                warnings.append(str((html_result or {}).get("error") or "html generation failed"))

        if "txt" in requested_formats:
            txt_path = pack_dir / "DOCUMENT.txt"
            txt_path.write_text(body_text, encoding="utf-8")
            outputs.append(str(txt_path))

        if not outputs:
            return {
                "success": False,
                "error": "Belge oluşturulamadı.",
                "warnings": warnings,
            }

        primary_output = outputs[0]

        response = {
            "success": True,
            "topic": topic,
            "pack_dir": str(pack_dir),
            "path": primary_output,
            "outputs": outputs,
            "preview": str(manifest.summary.get("preview") or ""),
            "message": f"Belge hazır: {primary_output}",
        }
        manifest_payload["outputs"] = list(outputs)
        manifest_payload["supporting_artifacts"] = [str(manifest_path)]
        manifest_summary = dict(manifest.summary or manifest_payload.get("summary") or {})
        manifest_summary["outputs"] = list(outputs)
        manifest_summary["supporting_artifacts"] = [str(manifest_path)]
        manifest_payload["summary"] = manifest_summary
        manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        response["office_content_manifest_path"] = str(manifest_path)
        if warnings:
            response["warnings"] = warnings
        return response
    except Exception as exc:
        logger.error(f"generate_document_pack error: {exc}")
        return {"success": False, "error": str(exc)}


async def research_document_delivery(
    topic: str,
    brief: str = "",
    depth: str = "comprehensive",
    audience: str = "executive",
    language: str = "tr",
    output_dir: str = "~/Desktop",
    include_word: bool = True,
    include_excel: bool = False,
    include_pdf: bool = False,
    include_latex: bool = False,
    include_presentation: bool = False,
    include_report: bool = True,
    source_policy: str = "trusted",
    min_reliability: float = 0.62,
    citation_style: str = "none",
    include_bibliography: bool = True,
    document_profile: str = "executive",
    citation_mode: str = "inline",
    deliver_copy: bool = False,
    previous_claim_map_path: str = "",
    revision_request: str = "",
    target_sections: list[str] | None = None,
) -> dict[str, Any]:
    """
    Execute a high-quality research workflow, generate deliverable documents,
    and return concrete artifact paths suitable for channel delivery.
    """
    try:
        topic_raw = str(topic or "").strip()
        topic_clean = _sanitize_research_topic(topic_raw, user_input=brief or topic_raw, step_name=brief or topic_raw)
        if not topic_clean or topic_clean == "genel konu":
            topic_clean = _extract_topic(brief or topic_raw, topic_raw)
        topic_clean = str(topic_clean or "").strip()
        if not topic_clean:
            return {"success": False, "error": "Araştırma konusu gerekli."}

        valid, msg, base_dir = validate_path(output_dir)
        if not valid or base_dir is None:
            return {"success": False, "error": msg}

        depth_map = {
            "quick": "quick",
            "standard": "standard",
            "comprehensive": "comprehensive",
            "expert": "expert",
            "deep": "comprehensive",
            "detailed": "comprehensive",
        }
        normalized_depth = depth_map.get(str(depth or "comprehensive").strip().lower(), "comprehensive")

        policy = str(source_policy or "trusted").strip().lower()
        if policy not in {"balanced", "trusted", "academic", "official"}:
            policy = "trusted"
        citation_style = str(citation_style or "none").strip().lower()
        if citation_style not in {"none", "apa7", "mla", "ieee", "chicago"}:
            citation_style = "none"
        citation_mode = _normalize_citation_mode(
            citation_mode,
            citation_style=citation_style,
            include_bibliography=include_bibliography,
        )
        document_profile = _normalize_document_profile(document_profile, audience=audience)
        include_bibliography = bool(include_bibliography)
        if not _brief_requests_reference_detail(brief, document_profile) and citation_mode == "inline":
            citation_mode = "none"
            include_bibliography = False

        try:
            min_rel = float(min_reliability)
        except Exception:
            min_rel = 0.62
        if min_rel > 1.0:
            min_rel = min_rel / 100.0
        min_rel = max(0.0, min(1.0, min_rel))

        try:
            from tools.research_tools.advanced_research import advanced_research
        except Exception as exc:
            return {"success": False, "error": f"Gerekli araştırma/ofis modülleri yüklenemedi: {exc}"}

        research_result = await advanced_research(
            topic=topic_clean,
            depth=normalized_depth,
            language=language,
            include_evaluation=True,
            generate_report=False,
            persist_quick_report=bool(deliver_copy),
            source_policy=policy,
            min_reliability=min_rel,
            max_findings=8,
            citation_style=citation_style,
            include_bibliography=include_bibliography,
        )
        if not isinstance(research_result, dict) or not research_result.get("success"):
            err = str((research_result or {}).get("error") or "Araştırma başarısız.")
            return {"success": False, "error": err}

        slug = _safe_project_slug(topic_clean)
        delivery_dir = (base_dir / f"{slug}_research_delivery").resolve()
        delivery_dir.mkdir(parents=True, exist_ok=True)
        internal_dir = (delivery_dir / ".elyan").resolve()
        internal_dir.mkdir(parents=True, exist_ok=True)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        findings = [str(x).strip() for x in (research_result.get("findings") or []) if str(x).strip()]
        cleaned_document_findings = _select_research_document_findings(findings, topic=topic_clean, limit=6)
        summary = str(research_result.get("summary") or "").strip()
        sources = research_result.get("sources") if isinstance(research_result.get("sources"), list) else []
        research_contract = research_result.get("research_contract") if isinstance(research_result.get("research_contract"), dict) else {}
        if not research_contract:
            try:
                from tools.research_tools.advanced_research import ResearchSource, _build_research_contract_payload

                source_objs = [
                    ResearchSource(
                        url=str(src.get("url") or "").strip(),
                        title=str(src.get("title") or "").strip(),
                        snippet=str(src.get("snippet") or "").strip(),
                        reliability_score=float(src.get("reliability_score", 0.0) or 0.0),
                        fetched=bool(src.get("fetched", False)),
                        fetched_at=str(src.get("fetched_at") or ""),
                    )
                    for src in sources
                    if isinstance(src, dict)
                ]
                research_contract = _build_research_contract_payload(topic_clean, findings, source_objs)
            except Exception:
                research_contract = {}
        filtered_sources = _select_research_sources_for_document(
            sources,
            min_rel=min_rel,
            source_policy=policy,
            limit=6,
        )
        source_count = int(research_result.get("source_count") or len(filtered_sources or sources))
        reliability_scores = []
        for src in sources:
            if not isinstance(src, dict):
                continue
            try:
                reliability_scores.append(float(src.get("reliability_score", 0.0) or 0.0))
            except Exception:
                continue
        avg_reliability = (sum(reliability_scores) / len(reliability_scores)) if reliability_scores else 0.0
        quality_summary = research_result.get("quality_summary") if isinstance(research_result.get("quality_summary"), dict) else {}
        if not quality_summary:
            quality_summary = _quality_summary_from_research_payload(
                research_contract=research_contract,
                sources=sources,
                findings=findings,
                source_policy=policy,
                min_reliability=min_rel,
            )
        source_policy_stats = research_result.get("source_policy_stats") if isinstance(research_result.get("source_policy_stats"), dict) else {}
        previous_claim_map = _load_json_payload(previous_claim_map_path)
        outputs: list[str] = []
        warnings: list[str] = []
        supporting_artifacts: list[str] = []
        llm_body = await _synthesize_research_body_with_llm(
            topic=topic_clean,
            brief=brief,
            findings=cleaned_document_findings or findings,
            sources=filtered_sources or sources,
            language=language,
        )
        llm_body_allowed = _should_use_llm_research_body(
            topic=topic_clean,
            llm_body=llm_body,
            quality_summary=quality_summary,
            source_policy_stats=source_policy_stats,
            source_policy=policy,
            findings=cleaned_document_findings or findings,
            sources=filtered_sources or sources,
        )
        summary_seed = llm_body if llm_body_allowed else summary
        content_only_render = _brief_requests_compact_research_report(brief, document_profile)
        if content_only_render and any([include_excel, include_pdf, include_latex, include_presentation]):
            content_only_render = False

        sections = _build_research_document_sections(
            topic=topic_clean,
            brief=brief,
            profile=document_profile,
            citation_mode=citation_mode,
            summary=summary_seed,
            findings=cleaned_document_findings or findings,
            research_contract=research_contract,
            quality_summary=quality_summary,
            include_bibliography=include_bibliography,
        )
        sections = _merge_sections_with_previous_claim_map(
            previous_claim_map=previous_claim_map,
            current_sections=sections,
            target_sections=list(target_sections or []),
        )
        if content_only_render:
            render_sections = _content_only_research_sections(
                topic=topic_clean,
                summary=summary_seed or summary,
                findings=cleaned_document_findings or findings,
                llm_body=llm_body if llm_body_allowed else "",
            )
        else:
            render_sections = _renderable_research_document_sections(
                sections=sections,
                profile=document_profile,
                brief=brief,
                include_bibliography=include_bibliography,
            )
        document_title = _clean_research_sentence(str(topic_clean or "").strip()) or str(topic_clean or "").strip() or "Araştırma"
        research_body = _sections_to_document_text(document_title, render_sections)
        if len(research_body) < 280:
            heuristic_body = _build_research_word_content(
                topic=topic_clean,
                brief=brief,
                audience=audience,
                depth=normalized_depth,
                policy=policy,
                min_rel=min_rel,
                summary=summary,
                findings=cleaned_document_findings or findings,
                sources=filtered_sources or sources,
                source_count=source_count,
                avg_reliability=avg_reliability,
                include_bibliography=include_bibliography,
            )
            fallback_body = (llm_body if llm_body_allowed else "") or heuristic_body
            fallback_sections = _build_research_document_sections(
                topic=topic_clean,
                brief=brief,
                profile=document_profile,
                citation_mode=citation_mode,
                summary=fallback_body or summary,
                findings=cleaned_document_findings or findings,
                research_contract=research_contract,
                quality_summary=quality_summary,
                include_bibliography=include_bibliography,
            )
            if fallback_sections:
                if content_only_render:
                    fallback_render_sections = _content_only_research_sections(
                        topic=topic_clean,
                        summary=fallback_body or summary,
                        findings=cleaned_document_findings or findings,
                        llm_body=llm_body if llm_body_allowed else "",
                    )
                else:
                    fallback_render_sections = _renderable_research_document_sections(
                        sections=fallback_sections,
                        profile=document_profile,
                        brief=brief,
                        include_bibliography=include_bibliography,
                    )
                if fallback_render_sections:
                    render_sections = fallback_render_sections
                research_body = _sections_to_document_text(document_title, render_sections)
            else:
                research_body = fallback_body
        research_paragraphs = _extract_plain_paragraphs(research_body)
        if not render_sections and research_paragraphs:
            render_sections = [{"title": "", "paragraphs": [{"text": para, "claim_ids": []} for para in research_paragraphs]}]
        sectioned_document = sections_to_sectioned_document(
            title=document_title,
            sections=render_sections,
            metadata={
                "topic": topic_clean,
                "audience": audience,
                "depth": normalized_depth,
                "source_policy": policy,
                "claim_coverage": round(float(quality_summary.get("claim_coverage", 0.0) or 0.0), 2),
                "critical_claim_coverage": round(float(quality_summary.get("critical_claim_coverage", 0.0) or 0.0), 2),
                "uncertainty_count": int(quality_summary.get("uncertainty_count", 0) or 0),
            },
        )
        renderer = DocumentRenderer()

        claim_map_payload = _build_claim_map_artifact(
            topic=topic_clean,
            sections=sections,
            research_contract=research_contract,
            quality_summary=quality_summary,
            profile=document_profile,
            citation_mode=citation_mode,
        )
        claim_map_payload["delivery"] = {
            "source_policy": policy,
            "min_reliability": min_rel,
            "depth": normalized_depth,
            "audience": audience,
        }
        claim_map_path = internal_dir / "claim_map.json"
        claim_map_path.write_text(json.dumps(claim_map_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        supporting_artifacts.append(str(claim_map_path))
        claim_coverage = float(claim_map_payload.get("claim_coverage", quality_summary.get("claim_coverage", 0.0)) or 0.0)
        critical_claim_coverage = float(quality_summary.get("critical_claim_coverage", 0.0) or 0.0)
        uncertainty_count = int(quality_summary.get("uncertainty_count", 0) or 0)
        revision_summary = ""
        revision_summary_path: Path | None = None
        if previous_claim_map:
            revision_summary = _build_claim_map_revision_summary(
                previous_claim_map=previous_claim_map,
                current_claim_map=claim_map_payload,
                revision_request=revision_request,
            )
            revision_summary_path = internal_dir / "revision_summary.txt"
            revision_summary_path.write_text(revision_summary, encoding="utf-8")
            supporting_artifacts.append(str(revision_summary_path))

        office_manifest = build_office_content_manifest(
            title=document_title,
            topic=topic_clean,
            brief=brief,
            audience=audience,
            language=language,
            content_kind="research_delivery",
            document_profile=document_profile,
            citation_mode=citation_mode,
            source_policy=policy,
            sections=sections,
            sources=filtered_sources or sources,
            quality_summary=quality_summary,
            research_contract=research_contract,
            claim_map=claim_map_payload,
            outputs=[],
            supporting_artifacts=supporting_artifacts,
            notes=[
                f"Quality status: {str(quality_summary.get('status') or 'unknown')}",
                "Office manifest created for docx/xlsx/pptx/pdf delivery.",
            ] + ([revision_summary[:1200]] if revision_summary else []),
            metadata={
                "depth": normalized_depth,
                "include_bibliography": include_bibliography,
                "deliver_copy": deliver_copy,
                "include_presentation": include_presentation,
            },
        )
        sectioned_document.metadata["office_content_manifest"] = office_manifest.to_dict()
        office_manifest_path = internal_dir / "office_content_manifest.json"
        office_manifest_payload = office_manifest.to_dict()
        office_manifest_path.write_text(json.dumps(office_manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        supporting_artifacts.append(str(office_manifest_path))

        if include_pdf:
            pdf_path = delivery_dir / "RESEARCH_DELIVERY.pdf"
            pdf_result = await renderer.render_to_path(sectioned_document, "pdf", str(pdf_path))
            if isinstance(pdf_result, dict) and pdf_result.get("success") and pdf_result.get("path"):
                outputs.append(str(pdf_result["path"]))
            else:
                warnings.append(str((pdf_result or {}).get("error") or "pdf generation failed"))

        if include_word:
            word_path = delivery_dir / "RESEARCH_DELIVERY.docx"
            word_result = await renderer.render_to_path(sectioned_document, "docx", str(word_path))
            if isinstance(word_result, dict) and word_result.get("success") and word_result.get("path"):
                outputs.append(str(word_result["path"]))
            else:
                warnings.append(str((word_result or {}).get("error") or "word generation failed"))

        if include_latex:
            latex_path = delivery_dir / "RESEARCH_DELIVERY.tex"
            latex_path.write_text(
                _build_latex_document(f"Araştırma Raporu - {topic_clean}", research_paragraphs or [research_body]),
                encoding="utf-8",
            )
            outputs.append(str(latex_path))

        if include_excel:
            excel_path = delivery_dir / "RESEARCH_DELIVERY.xlsx"
            excel_result = await renderer.render_to_path(sectioned_document, "xlsx", str(excel_path))
            if isinstance(excel_result, dict) and excel_result.get("success") and excel_result.get("path"):
                outputs.append(str(excel_result["path"]))
            else:
                warnings.append(str((excel_result or {}).get("error") or "excel generation failed"))

        if include_presentation:
            pptx_path = delivery_dir / "RESEARCH_DELIVERY.pptx"
            pptx_result = await renderer.render_to_path(sectioned_document, "pptx", str(pptx_path))
            if isinstance(pptx_result, dict) and pptx_result.get("success") and pptx_result.get("path"):
                outputs.append(str(pptx_result["path"]))
            else:
                warnings.append(str((pptx_result or {}).get("error") or "pptx generation failed"))

        if not include_word and not include_excel and not include_pdf and not include_latex and not include_presentation:
            report_md = delivery_dir / "RESEARCH_DELIVERY.md"
            md_result = await renderer.render_to_path(sectioned_document, "md", str(report_md))
            if isinstance(md_result, dict) and md_result.get("success") and md_result.get("path"):
                outputs.append(str(md_result["path"]))
            else:
                warnings.append(str((md_result or {}).get("error") or "markdown generation failed"))

        if deliver_copy:
            for report_path in research_result.get("report_paths", []) if isinstance(research_result.get("report_paths"), list) else []:
                if not isinstance(report_path, str) or not report_path.strip():
                    continue
                src = Path(report_path).expanduser()
                if not src.exists() or not src.is_file():
                    continue
                try:
                    supporting_artifacts.append(str(src.resolve()))
                except Exception:
                    supporting_artifacts.append(str(src))

        dedup_outputs: list[str] = []
        seen_paths: set[str] = set()
        for item in outputs:
            if not isinstance(item, str) or not item.strip():
                continue
            key = str(Path(item).expanduser())
            if key in seen_paths:
                continue
            seen_paths.add(key)
            dedup_outputs.append(key)
        outputs = dedup_outputs

        dedup_supporting: list[str] = []
        seen_supporting: set[str] = set()
        for item in supporting_artifacts:
            if not isinstance(item, str) or not item.strip():
                continue
            key = str(Path(item).expanduser())
            if key in seen_supporting or key in seen_paths:
                continue
            seen_supporting.add(key)
            dedup_supporting.append(key)
        supporting_artifacts = dedup_supporting

        office_manifest_payload["outputs"] = list(outputs)
        office_manifest_payload["supporting_artifacts"] = list(supporting_artifacts)
        office_manifest_summary = dict(office_manifest.summary or office_manifest_payload.get("summary") or {})
        office_manifest_summary["outputs"] = list(outputs)
        office_manifest_summary["supporting_artifacts"] = list(supporting_artifacts)
        office_manifest_payload["summary"] = office_manifest_summary
        office_manifest_path.write_text(json.dumps(office_manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        if not outputs:
            return {
                "success": False,
                "error": "Belge oluşturulamadı.",
                "warnings": warnings,
                "delivery_dir": str(delivery_dir),
            }

        primary_output = outputs[0]

        quality_status = str((quality_summary or {}).get("status") or ("partial" if critical_claim_coverage < 1.0 or uncertainty_count > 0 else "pass"))
        message = f"Araştırma belgesi hazır: {primary_output}. İstersen bunu genişletip revize edebilirim."

        response = {
            "success": True,
            "ok": True,
            "topic": topic_clean,
            "depth": normalized_depth,
            "source_policy": policy,
            "min_reliability": min_rel,
            "citation_style": citation_style,
            "include_bibliography": include_bibliography,
            "include_presentation": include_presentation,
            "document_profile": document_profile,
            "citation_mode": citation_mode,
            "path": primary_output,
            "delivery_dir": str(delivery_dir),
            "outputs": outputs,
            "artifacts": outputs + supporting_artifacts,
            "supporting_artifacts": supporting_artifacts,
            "office_content_manifest_path": str(office_manifest_path),
            "preview": str(office_manifest.summary.get("preview") or ""),
            "source_count": source_count,
            "finding_count": len(findings),
            "claim_coverage": round(claim_coverage, 2),
            "critical_claim_coverage": round(critical_claim_coverage, 2),
            "uncertainty_count": uncertainty_count,
            "quality_summary": {
                **dict(quality_summary or {}),
                "avg_reliability": avg_reliability,
                "min_reliability_threshold": min_rel,
                "source_policy": policy,
                "claim_coverage": round(claim_coverage, 2),
                "critical_claim_coverage": round(critical_claim_coverage, 2),
                "uncertainty_count": uncertainty_count,
                "uncertainty_section_present": any(
                    str(section.get("title") or "").strip().lower() == "belirsizlikler"
                    for section in list(sections or [])
                    if isinstance(section, dict)
                ),
                "status": quality_status,
            },
            "claim_map_path": str(claim_map_path),
            "revision_summary": revision_summary,
            "revision_summary_path": str(revision_summary_path) if revision_summary_path else "",
            "research_contract": research_contract,
            "summary": summary,
            "message": message,
        }
        if warnings:
            response["warnings"] = warnings
        return response
    except Exception as exc:
        logger.error(f"research_document_delivery error: {exc}")
        return {"success": False, "error": str(exc)}


async def create_image_workflow_profile(
    project_name: str,
    visual_style: str = "editorial_clean",
    aspect_ratios: str = "1:1,16:9,9:16",
    output_dir: str = "~/Desktop"
) -> dict[str, Any]:
    """
    Generate a reusable image generation workflow package (prompt pack + style guide).
    """
    try:
        valid, msg, base_dir = validate_path(output_dir)
        if not valid or base_dir is None:
            return {"success": False, "error": msg}

        profile_dir = (base_dir / f"{_safe_project_slug(project_name)}_image_workflow").resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)

        ratios = [r.strip() for r in str(aspect_ratios).split(",") if r.strip()] or ["1:1"]
        prompt_pack = {
            "project": project_name,
            "style": visual_style,
            "ratios": ratios,
            "base_prompt": f"{project_name}, {visual_style}, high detail, cinematic lighting, clean composition",
            "negative_prompt": "blurry, low quality, distorted anatomy, text artifacts, watermark",
            "variations": [
                "hero shot, bold composition, premium product-ad look",
                "minimal editorial layout, neutral palette, soft shadows",
                "dynamic angle, high contrast, storytelling scene",
            ],
            "postprocess_checklist": [
                "composition balance",
                "subject clarity",
                "brand consistency",
                "export format validation",
            ],
            "generated_at": datetime.now().isoformat(),
        }

        prompts_md = profile_dir / "PROMPT_PACK.md"
        prompts_md.write_text(
            "\n".join(
                [
                    f"# Prompt Pack - {project_name}",
                    "",
                    f"Style: {visual_style}",
                    f"Ratios: {', '.join(ratios)}",
                    "",
                    "## Base Prompt",
                    prompt_pack["base_prompt"],
                    "",
                    "## Negative Prompt",
                    prompt_pack["negative_prompt"],
                    "",
                    "## Variations",
                    *[f"- {v}" for v in prompt_pack["variations"]],
                    "",
                    "## Postprocess Checklist",
                    *[f"- {x}" for x in prompt_pack["postprocess_checklist"]],
                ]
            ),
            encoding="utf-8",
        )

        style_json = profile_dir / "STYLE_PROFILE.json"
        import json
        style_json.write_text(json.dumps(prompt_pack, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "success": True,
            "project_name": project_name,
            "style": visual_style,
            "profile_dir": str(profile_dir),
            "files_created": [str(prompts_md), str(style_json)],
            "message": f"Image workflow profile olusturuldu: {profile_dir}",
        }
    except Exception as exc:
        logger.error(f"create_image_workflow_profile error: {exc}")
        return {"success": False, "error": str(exc)}


async def create_software_project_pack(
    project_name: str,
    project_type: str = "webapp",
    stack: str = "python",
    complexity: str = "advanced",
    output_dir: str = "~/Desktop",
    brief: str = "",
) -> dict[str, Any]:
    """
    Create a complex project pack for web/app/game style requests.
    Produces code scaffold + test skeleton + run/deploy docs + quality checklist.
    """
    try:
        valid, msg, base_dir = validate_path(output_dir)
        if not valid or base_dir is None:
            return {"success": False, "error": msg}

        safe_name = _safe_project_slug(project_name)
        ptype = str(project_type or "webapp").strip().lower()
        if ptype not in {"webapp", "app", "game"}:
            ptype = "webapp"
        chosen_stack = str(stack or "python").strip().lower()
        level = str(complexity or "advanced").strip().lower()
        if level not in {"standard", "advanced", "expert"}:
            level = "advanced"

        pack_dir = (base_dir / f"{safe_name}_project_pack").resolve()
        src_dir = pack_dir / "src"
        tests_dir = pack_dir / "tests"
        docs_dir = pack_dir / "docs"
        for d in (pack_dir, src_dir, tests_dir, docs_dir):
            d.mkdir(parents=True, exist_ok=True)

        brief_text = _brief_excerpt(brief, fallback="No explicit brief provided.")
        brief_low = str(brief or "").lower()

        if ptype == "game":
            entry = src_dir / "main.py"
            entry_content = """import pygame
import random

def main():
    pygame.init()
    screen = pygame.display.set_mode((900, 520))
    pygame.display.set_caption("Elyan Game Prototype")
    clock = pygame.time.Clock()
    running = True
    x = 100
    score = 0
    target_x = random.randint(120, 760)

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                if abs((x + 35) - target_x) < 40:
                    score += 1
                    target_x = random.randint(120, 760)

        keys = pygame.key.get_pressed()
        if keys[pygame.K_RIGHT]:
            x += 4
        if keys[pygame.K_LEFT]:
            x -= 4

        screen.fill((16, 24, 40))
        pygame.draw.rect(screen, (120, 180, 255), (x, 280, 70, 70))
        pygame.draw.circle(screen, (255, 184, 108), (target_x, 160), 20)
        font = pygame.font.SysFont("Arial", 24)
        score_text = font.render(f"Score: {score}", True, (226, 232, 240))
        hint_text = font.render("SPACE: hedefi yakala", True, (148, 163, 184))
        screen.blit(score_text, (20, 18))
        screen.blit(hint_text, (20, 48))
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()

if __name__ == "__main__":
    main()
"""
            deps = ["pygame>=2.6.0"]
        elif chosen_stack in {"node", "javascript", "typescript", "express"}:
            entry = src_dir / "main.js"
            todo_mode = any(k in brief_low for k in ("todo", "task", "görev", "gorev"))
            todo_block = ""
            if todo_mode:
                todo_block = """
const todos = [];
app.get('/todos', (_req, res) => res.json({ ok: true, items: todos }));
app.post('/todos', (req, res) => {
  const title = String(req.body?.title || '').trim();
  if (!title) return res.status(400).json({ ok: false, error: 'title required' });
  const item = { id: Date.now(), title, done: false };
  todos.push(item);
  return res.json({ ok: true, item });
});
"""
            entry_content = f"""const express = require('express');
const app = express();
app.use(express.json());

app.get('/health', (_req, res) => res.json({{ ok: true, service: '{project_name}' }}));
{todo_block}
const port = process.env.PORT || 8000;
app.listen(port, () => {{
  console.log(`{project_name} running on :${{port}}`);
}});
"""
            deps = ["express@^4.21.2"]
            (pack_dir / "package.json").write_text(
                "{\n"
                f'  "name": "{safe_name.lower()}",\n'
                '  "version": "0.1.0",\n'
                '  "private": true,\n'
                '  "type": "commonjs",\n'
                '  "scripts": { "start": "node src/main.js" },\n'
                '  "dependencies": { "express": "^4.21.2" }\n'
                "}\n",
                encoding="utf-8",
            )
        else:
            entry = src_dir / "main.py"
            todo_mode = any(k in brief_low for k in ("todo", "task", "görev", "gorev"))
            research_mode = any(k in brief_low for k in ("research", "araştır", "arastir", "rapor"))
            extra_routes = []
            if todo_mode:
                extra_routes.append(
                    """
@app.get("/todos")
def list_todos():
    return {"ok": True, "items": TODOS}

@app.post("/todos")
def add_todo(payload: dict):
    title = str(payload.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "title required"}
    item = {"id": len(TODOS) + 1, "title": title, "done": False}
    TODOS.append(item)
    return {"ok": True, "item": item}
"""
                )
            if research_mode:
                extra_routes.append(
                    """
@app.post("/research/summary")
def summarize(payload: dict):
    topic = str(payload.get("topic") or "").strip() or "genel"
    return {
        "ok": True,
        "topic": topic,
        "summary": f"{topic} için kısa özet üretildi (örnek endpoint)."
    }
"""
                )

            entry_content = (
                "from fastapi import FastAPI\n\n"
                "app = FastAPI(title='Elyan App Pack')\n"
                "TODOS = []\n\n"
                "@app.get('/health')\n"
                "def health():\n"
                f"    return {{'ok': True, 'service': '{project_name}'}}\n"
                + ("\n".join(extra_routes) if extra_routes else "")
                + "\n\nif __name__ == '__main__':\n"
                "    import uvicorn\n"
                "    uvicorn.run(app, host='0.0.0.0', port=8000)\n"
            )
            deps = ["fastapi>=0.111.0", "uvicorn>=0.30.0"]

        entry.write_text(entry_content, encoding="utf-8")

        test_file = tests_dir / "test_smoke.py"
        if entry.suffix == ".py":
            test_file.write_text(
                "\n".join(
                    [
                        "def test_smoke_import():",
                        "    import importlib.util",
                        "    spec = importlib.util.spec_from_file_location('main', 'src/main.py')",
                        "    assert spec is not None",
                    ]
                ),
                encoding="utf-8",
            )
        else:
            test_file.write_text(
                "\n".join(
                    [
                        "from pathlib import Path",
                        "",
                        "def test_smoke_node_entry_exists():",
                        "    assert Path('src/main.js').exists()",
                    ]
                ),
                encoding="utf-8",
            )

        req_path = pack_dir / "requirements.txt"
        if entry.suffix == ".py":
            req_path.write_text("\n".join(deps) + "\n", encoding="utf-8")
        else:
            req_path.write_text("# Node stack selected. Use npm install.\n", encoding="utf-8")

        run_setup = [
            "1. python3 -m venv .venv",
            "2. source .venv/bin/activate",
            "3. pip install -r requirements.txt",
        ]
        run_cmd = ["python src/main.py"]
        test_cmd = ["pytest -q"]
        if entry.suffix != ".py":
            run_setup = ["1. npm install"]
            run_cmd = ["npm start"]
            test_cmd = ["pytest -q  # smoke check for generated files"]

        (docs_dir / "RUN_GUIDE.md").write_text(
            "\n".join(
                [
                    f"# Run Guide - {project_name}",
                    "",
                    f"Project Type: {ptype}",
                    f"Stack: {chosen_stack}",
                    f"Complexity: {level}",
                    f"Brief: {brief_text}",
                    "",
                    "## Setup",
                    *run_setup,
                    "",
                    "## Run",
                    *run_cmd,
                    "",
                    "## Test",
                    *test_cmd,
                ]
            ),
            encoding="utf-8",
        )

        (docs_dir / "DEPLOY_GUIDE.md").write_text(
            "\n".join(
                [
                    f"# Deploy Guide - {project_name}",
                    "",
                    "## Steps",
                    "1. Build artifact / container image",
                    "2. Set runtime env vars",
                    "3. Configure health checks",
                    "4. Roll out gradually and monitor logs",
                ]
            ),
            encoding="utf-8",
        )

        (docs_dir / "QUALITY_REPORT.md").write_text(
            "\n".join(
                [
                    f"# Quality Report Seed - {project_name}",
                    "",
                    "Checklist:",
                    "- [ ] Correctness",
                    "- [ ] Test coverage",
                    "- [ ] Reproducible run",
                    "- [ ] Clear deployment path",
                    "- [ ] Security review for risky operations",
                ]
            ),
            encoding="utf-8",
        )

        (pack_dir / "README.md").write_text(
            "\n".join(
                [
                    f"# {project_name} - Project Pack",
                    "",
                    f"Type: {ptype}",
                    f"Stack: {chosen_stack}",
                    f"Complexity: {level}",
                    f"Brief: {brief_text}",
                    "",
                    "This pack is generated for complex multi-step delivery by Elyan.",
                ]
            ),
            encoding="utf-8",
        )

        files = [
            str(entry),
            str(test_file),
            str(req_path),
            str(docs_dir / "RUN_GUIDE.md"),
            str(docs_dir / "DEPLOY_GUIDE.md"),
            str(docs_dir / "QUALITY_REPORT.md"),
            str(pack_dir / "README.md"),
        ]
        return {
            "success": True,
            "project_name": project_name,
            "project_type": ptype,
            "stack": chosen_stack,
            "complexity": level,
            "pack_dir": str(pack_dir),
            "files_created": files,
            "message": f"Software project pack oluşturuldu: {pack_dir}",
        }
    except Exception as exc:
        logger.error(f"create_software_project_pack error: {exc}")
        return {"success": False, "error": str(exc)}
