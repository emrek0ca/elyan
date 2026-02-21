"""
Araştırma Sentezleyici - Research Synthesizer
AI destekli sentez ve rapor oluşturma
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any
from config.settings import HOME_DIR
from utils.logger import get_logger

logger = get_logger("research_synthesizer")


async def synthesize_findings(
    research_id: str | None = None,
    findings: list[str] | None = None,
    sources: list[dict] | None = None,
    synthesis_type: str = "summary"
) -> dict[str, Any]:
    """
    Araştırma bulgularını sentezle

    Args:
        research_id: Araştırma ID'si (önceki araştırmadan)
        findings: Doğrudan bulgular listesi
        sources: Kaynak bilgileri
        synthesis_type: Sentez tipi ("summary", "analysis", "comparison", "recommendations")

    Returns:
        dict: Sentez sonucu
    """
    try:
        # Get findings from research if ID provided
        if research_id:
            from .advanced_research import get_research_result
            research = get_research_result(research_id)
            if not research.get("success"):
                return research
            findings = research.get("findings", [])
            sources = research.get("sources", [])

        if not findings:
            return {"success": False, "error": "Sentezlenecek bulgu yok"}

        synthesis = ""

        if synthesis_type == "summary":
            synthesis = _create_summary_synthesis(findings, sources)
        elif synthesis_type == "analysis":
            synthesis = _create_analysis_synthesis(findings, sources)
        elif synthesis_type == "comparison":
            synthesis = _create_comparison_synthesis(findings, sources)
        elif synthesis_type == "recommendations":
            synthesis = _create_recommendations_synthesis(findings, sources)
        else:
            synthesis = _create_summary_synthesis(findings, sources)

        return {
            "success": True,
            "synthesis_type": synthesis_type,
            "finding_count": len(findings),
            "source_count": len(sources) if sources else 0,
            "synthesis": synthesis,
            "generated_at": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Sentez hatası: {e}")
        return {"success": False, "error": f"Sentez yapılamadı: {str(e)}"}


async def create_research_report(
    topic: str,
    research_id: str | None = None,
    findings: list[str] | None = None,
    sources: list[dict] | None = None,
    output_format: str = "markdown",
    output_path: str | None = None,
    include_sources: bool = True,
    include_methodology: bool = True
) -> dict[str, Any]:
    """
    Araştırma raporu oluştur

    Args:
        topic: Araştırma konusu
        research_id: Araştırma ID'si
        findings: Bulgular
        sources: Kaynaklar
        output_format: Çıktı formatı ("markdown", "text", "docx")
        output_path: Çıktı dosya yolu
        include_sources: Kaynak listesi dahil et
        include_methodology: Metodoloji bölümü dahil et

    Returns:
        dict: Rapor oluşturma sonucu
    """
    try:
        # Get data from research if ID provided
        if research_id:
            from .advanced_research import get_research_result
            research = get_research_result(research_id)
            if not research.get("success"):
                return research
            findings = research.get("findings", [])
            sources = research.get("sources", [])
            if not topic:
                topic = research.get("topic", "Araştırma Raporu")

        if not topic:
            return {"success": False, "error": "Rapor konusu gerekli"}

        # Generate report content
        now = datetime.now()
        report_lines = []

        # Title
        report_lines.append(f"# {topic}")
        report_lines.append("")
        report_lines.append(f"*Rapor Tarihi: {now.strftime('%d.%m.%Y %H:%M')}*")
        report_lines.append("")

        # Table of contents
        report_lines.append("## İçindekiler")
        report_lines.append("")
        report_lines.append("1. [Özet](#özet)")
        if include_methodology:
            report_lines.append("2. [Metodoloji](#metodoloji)")
        report_lines.append("3. [Bulgular](#bulgular)")
        report_lines.append("4. [Analiz](#analiz)")
        if include_sources:
            report_lines.append("5. [Kaynaklar](#kaynaklar)")
        report_lines.append("")

        # Summary
        report_lines.append("## Özet")
        report_lines.append("")
        summary = _create_summary_synthesis(findings, sources) if findings else "Henüz bulgu eklenmedi."
        report_lines.append(summary)
        report_lines.append("")

        # Methodology
        if include_methodology:
            report_lines.append("## Metodoloji")
            report_lines.append("")
            source_count = len(sources) if sources else 0
            reliable_count = sum(1 for s in (sources or []) if s.get("reliability_score", 0) >= 0.6)
            report_lines.append(f"Bu araştırma için toplam **{source_count}** kaynak incelenmiştir.")
            if reliable_count > 0:
                report_lines.append(f"Bunlardan **{reliable_count}** tanesi yüksek güvenilirlik skoruna sahiptir.")
            report_lines.append("")
            report_lines.append("Kaynaklar güvenilirlik açısından değerlendirilmiş ve içerikleri analiz edilmiştir.")
            report_lines.append("")

        # Findings
        report_lines.append("## Bulgular")
        report_lines.append("")
        if findings:
            for i, finding in enumerate(findings, 1):
                # Clean up bullet points if already present
                finding_text = finding.strip()
                if finding_text.startswith("•"):
                    finding_text = finding_text[1:].strip()
                report_lines.append(f"{i}. {finding_text}")
                report_lines.append("")
        else:
            report_lines.append("Henüz bulgu eklenmedi.")
            report_lines.append("")

        # Analysis
        report_lines.append("## Analiz")
        report_lines.append("")
        analysis = _create_analysis_synthesis(findings, sources) if findings else "Analiz için yeterli veri yok."
        report_lines.append(analysis)
        report_lines.append("")

        # Sources
        if include_sources and sources:
            report_lines.append("## Kaynaklar")
            report_lines.append("")
            for i, source in enumerate(sources, 1):
                title = source.get("title", "Başlıksız")
                url = source.get("url", "")
                score = source.get("reliability_score", 0)
                reliability = "★★★" if score >= 0.8 else ("★★" if score >= 0.6 else "★")
                report_lines.append(f"{i}. [{title}]({url}) {reliability}")
            report_lines.append("")

        # Footer
        report_lines.append("---")
        report_lines.append("")
        report_lines.append("*Bu rapor CDACS Bot tarafından otomatik olarak oluşturulmuştur.*")

        report_content = "\n".join(report_lines)

        # Determine output path
        if not output_path:
            safe_topic = "".join(c if c.isalnum() or c in " -_" else "_" for c in topic)[:50]
            timestamp = now.strftime("%Y%m%d_%H%M%S")
            if output_format == "markdown":
                filename = f"rapor_{safe_topic}_{timestamp}.md"
            elif output_format == "docx":
                filename = f"rapor_{safe_topic}_{timestamp}.docx"
            else:
                filename = f"rapor_{safe_topic}_{timestamp}.txt"
            output_path = str(HOME_DIR / "Desktop" / filename)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write output based on format
        if output_format == "docx":
            try:
                from tools.office_tools import write_word
                result = await write_word(
                    str(output_path),
                    content=report_content,
                    title=topic
                )
                if not result.get("success"):
                    # Fallback to markdown
                    output_path = output_path.with_suffix(".md")
                    output_path.write_text(report_content, encoding="utf-8")
            except ImportError:
                # Fallback to markdown
                output_path = output_path.with_suffix(".md")
                output_path.write_text(report_content, encoding="utf-8")
        else:
            output_path.write_text(report_content, encoding="utf-8")

        logger.info(f"Araştırma raporu oluşturuldu: {output_path.name}")

        return {
            "success": True,
            "topic": topic,
            "output_path": str(output_path),
            "filename": output_path.name,
            "format": output_format,
            "finding_count": len(findings) if findings else 0,
            "source_count": len(sources) if sources else 0,
            "content_preview": report_content[:500],
            "message": f"Araştırma raporu oluşturuldu: {output_path.name}"
        }

    except Exception as e:
        logger.error(f"Rapor oluşturma hatası: {e}")
        return {"success": False, "error": f"Rapor oluşturulamadı: {str(e)}"}


def _create_summary_synthesis(
    findings: list[str] | None,
    sources: list[dict] | None
) -> str:
    """Özet sentezi oluştur"""
    if not findings:
        return "Sentezlenecek bulgu bulunamadı."

    lines = []
    lines.append(f"Toplam {len(findings)} bulgu incelendi.")

    if sources:
        reliable = sum(1 for s in sources if s.get("reliability_score", 0) >= 0.6)
        lines.append(f"Kaynakların {reliable}/{len(sources)} tanesi güvenilir olarak değerlendirildi.")

    lines.append("")
    lines.append("Öne çıkan bulgular:")

    # Take top findings
    for finding in findings[:5]:
        finding_text = finding.strip()
        if finding_text.startswith("•"):
            finding_text = finding_text[1:].strip()
        lines.append(f"- {finding_text}")

    return "\n".join(lines)


def _create_analysis_synthesis(
    findings: list[str] | None,
    sources: list[dict] | None
) -> str:
    """Analiz sentezi oluştur"""
    if not findings:
        return "Analiz için yeterli bulgu yok."

    lines = []

    # Theme analysis
    lines.append("### Tema Analizi")
    lines.append("")
    lines.append("Araştırma bulguları incelendiğinde aşağıdaki temalar öne çıkmaktadır:")
    lines.append("")

    # Extract common themes (simplified keyword extraction)
    all_text = " ".join(findings).lower()
    common_words = {}

    # Simple word frequency
    words = all_text.split()
    stop_words = {"ve", "ile", "bir", "bu", "için", "olan", "de", "da", "the", "and", "is", "of", "to", "in", "a"}

    for word in words:
        word = word.strip(".,;:!?\"'()[]")
        if len(word) > 3 and word not in stop_words:
            common_words[word] = common_words.get(word, 0) + 1

    # Get top themes
    sorted_words = sorted(common_words.items(), key=lambda x: -x[1])[:5]
    for word, count in sorted_words:
        lines.append(f"- **{word.capitalize()}** (tekrar: {count})")

    lines.append("")

    # Source reliability analysis
    if sources:
        lines.append("### Kaynak Güvenilirliği")
        lines.append("")
        high_rel = sum(1 for s in sources if s.get("reliability_score", 0) >= 0.8)
        med_rel = sum(1 for s in sources if 0.6 <= s.get("reliability_score", 0) < 0.8)
        low_rel = sum(1 for s in sources if s.get("reliability_score", 0) < 0.6)

        lines.append(f"- Yüksek güvenilirlik: {high_rel} kaynak")
        lines.append(f"- Orta güvenilirlik: {med_rel} kaynak")
        lines.append(f"- Düşük güvenilirlik: {low_rel} kaynak")

    return "\n".join(lines)


def _create_comparison_synthesis(
    findings: list[str] | None,
    sources: list[dict] | None
) -> str:
    """Karşılaştırma sentezi oluştur"""
    if not findings:
        return "Karşılaştırma için yeterli bulgu yok."

    lines = []
    lines.append("### Kaynak Karşılaştırması")
    lines.append("")

    if not sources:
        lines.append("Karşılaştırma için kaynak bilgisi mevcut değil.")
        return "\n".join(lines)

    # Group sources by reliability
    high_rel_sources = [s for s in sources if s.get("reliability_score", 0) >= 0.7]
    low_rel_sources = [s for s in sources if s.get("reliability_score", 0) < 0.7]

    if high_rel_sources:
        lines.append("**Güvenilir Kaynaklar:**")
        for source in high_rel_sources[:3]:
            lines.append(f"- {source.get('title', 'Başlıksız')}")
        lines.append("")

    if low_rel_sources:
        lines.append("**Dikkatli Değerlendirilmesi Gereken Kaynaklar:**")
        for source in low_rel_sources[:3]:
            lines.append(f"- {source.get('title', 'Başlıksız')}")

    return "\n".join(lines)


def _create_recommendations_synthesis(
    findings: list[str] | None,
    sources: list[dict] | None
) -> str:
    """Öneri sentezi oluştur"""
    lines = []
    lines.append("### Öneriler")
    lines.append("")

    if not findings:
        lines.append("Öneri oluşturmak için yeterli bulgu yok.")
        return "\n".join(lines)

    lines.append("Araştırma bulgularına dayanarak aşağıdaki öneriler sunulmaktadır:")
    lines.append("")

    lines.append("1. **Daha fazla araştırma:** Konunun derinlemesine anlaşılması için ek kaynaklar incelenmelidir.")
    lines.append("")
    lines.append("2. **Kaynak çeşitliliği:** Farklı perspektifler için akademik ve pratik kaynaklar birlikte değerlendirilmelidir.")
    lines.append("")

    if sources:
        reliable = [s for s in sources if s.get("reliability_score", 0) >= 0.7]
        if reliable:
            lines.append("3. **Öncelikli kaynaklar:** Aşağıdaki güvenilir kaynaklar detaylı incelenebilir:")
            for source in reliable[:3]:
                lines.append(f"   - {source.get('title', 'Başlıksız')}")

    return "\n".join(lines)
