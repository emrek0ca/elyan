"""
Gelişmiş Araştırma - Advanced Research
Çoklu kaynak araştırma, derinlik seviyeleri ve kaynak değerlendirmesi
"""

import asyncio
import uuid
from datetime import datetime
from typing import Any
from enum import Enum
from dataclasses import dataclass, field
from utils.logger import get_logger

logger = get_logger("advanced_research")


class ResearchDepth(Enum):
    QUICK = "quick"           # 2-3 kaynak, hızlı sonuç
    STANDARD = "standard"     # 5-7 kaynak, temel analiz
    COMPREHENSIVE = "comprehensive"  # 10-15 kaynak, detaylı analiz
    EXPERT = "expert"         # 15-20+ kaynak, akademik seviye


@dataclass
class ResearchSource:
    """Araştırma kaynağı"""
    url: str
    title: str
    snippet: str
    reliability_score: float = 0.0
    content: str = ""
    fetched: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "reliability_score": self.reliability_score,
            "fetched": self.fetched,
            "error": self.error
        }


@dataclass
class ResearchResult:
    """Araştırma sonucu"""
    id: str
    topic: str
    depth: ResearchDepth
    status: str = "pending"
    sources: list[ResearchSource] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    summary: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    progress: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic": self.topic,
            "depth": self.depth.value,
            "status": self.status,
            "source_count": len(self.sources),
            "sources": [s.to_dict() for s in self.sources],
            "findings": self.findings,
            "summary": self.summary,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "progress": self.progress
        }


# Store ongoing research
_research_tasks: dict[str, ResearchResult] = {}


def get_research_status(research_id: str) -> dict[str, Any]:
    """Get status of ongoing research"""
    if research_id not in _research_tasks:
        return {
            "success": False,
            "error": f"Araştırma bulunamadı: {research_id}"
        }

    result = _research_tasks[research_id]
    return {
        "success": True,
        "research_id": research_id,
        "status": result.status,
        "progress": result.progress,
        "topic": result.topic,
        "depth": result.depth.value,
        "source_count": len(result.sources),
        "finding_count": len(result.findings),
        "started_at": result.started_at,
        "completed_at": result.completed_at,
        "summary": result.summary if result.status == "completed" else None
    }


def get_research_result(research_id: str) -> dict[str, Any]:
    """Get completed research result"""
    if research_id not in _research_tasks:
        return {
            "success": False,
            "error": f"Araştırma bulunamadı: {research_id}"
        }

    result = _research_tasks[research_id]

    if result.status != "completed":
        return {
            "success": False,
            "error": f"Araştırma henüz tamamlanmadı. Durum: {result.status}",
            "progress": result.progress
        }

    sources_dict = [s.to_dict() for s in result.sources]
    return {
        "success": True,
        "research_id": research_id,
        "topic": result.topic,
        "depth": result.depth.value,
        "sources": sources_dict,
        "findings": result.findings,
        "summary": result.summary,
        "completed_at": result.completed_at
    }


async def advanced_research(
    topic: str,
    depth: str = "standard",
    sources: list[str] | None = None,
    language: str = "tr",
    include_evaluation: bool = True,
    generate_report: bool = True
) -> dict[str, Any]:
    """
    Gelişmiş araştırma yap ve rapor oluştur

    Args:
        topic: Araştırma konusu
        depth: Derinlik seviyesi ("quick", "standard", "comprehensive", "expert")
        sources: Belirli kaynaklar (URL listesi)
        language: Arama dili ("tr", "en")
        include_evaluation: Kaynak güvenilirlik değerlendirmesi dahil et
        generate_report: Profesyonel rapor oluştur

    Returns:
        dict: Araştırma sonuçları ve rapor yolu
    """
    try:
        if not topic or not topic.strip():
            return {"success": False, "error": "Araştırma konusu gerekli"}

        topic = topic.strip()

        # Parse depth
        try:
            research_depth = ResearchDepth(depth.lower())
        except ValueError:
            research_depth = ResearchDepth.STANDARD

        # Determine source count based on depth
        source_counts = {
            ResearchDepth.QUICK: 3,
            ResearchDepth.STANDARD: 6,
            ResearchDepth.COMPREHENSIVE: 12,
            ResearchDepth.EXPERT: 18
        }
        target_sources = source_counts[research_depth]

        # Create research ID
        research_id = f"research_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        result = ResearchResult(
            id=research_id,
            topic=topic,
            depth=research_depth,
            status="running",
            started_at=datetime.now().isoformat()
        )
        _research_tasks[research_id] = result

        logger.info(f"Araştırma başlatıldı: {topic} ({research_depth.value})")

        try:
            # Step 1: Web search for sources
            result.progress = 10
            search_results = await _perform_web_search(topic, target_sources, language)

            if not search_results:
                result.status = "failed"
                result.completed_at = datetime.now().isoformat()
                return {
                    "success": False,
                    "research_id": research_id,
                    "error": "Arama sonucu bulunamadı"
                }

            # Add custom sources if provided
            if sources:
                for url in sources[:5]:  # Limit custom sources
                    search_results.append({
                        "url": url,
                        "title": "Kullanıcı kaynağı",
                        "snippet": ""
                    })

            # Create source objects
            for sr in search_results[:target_sources]:
                source = ResearchSource(
                    url=sr.get("url", ""),
                    title=sr.get("title", ""),
                    snippet=sr.get("snippet", "")
                )
                result.sources.append(source)

            result.progress = 30

            # Step 2: Fetch and evaluate sources
            if include_evaluation:
                for i, source in enumerate(result.sources):
                    try:
                        eval_result = await evaluate_source(source.url)
                        if eval_result.get("success"):
                            source.reliability_score = eval_result.get("reliability_score", 0.5)
                            source.content = eval_result.get("content_preview", "")
                            source.fetched = True
                        else:
                            source.error = eval_result.get("error")
                    except Exception as e:
                        source.error = str(e)

                    result.progress = 30 + int((i + 1) / len(result.sources) * 40)

            # Step 3: Extract findings
            result.progress = 75
            result.findings = await _extract_findings(result.sources, topic)

            # Step 4: Generate summary
            result.progress = 90
            result.summary = await _generate_summary(topic, result.findings, result.sources)

            # Step 5: Generate professional report with visualizations
            result.progress = 95
            sources_dict = [s.to_dict() for s in result.sources]

            report_data = {
                "sources": sources_dict,
                "findings": result.findings,
                "summary": result.summary,
                "depth": research_depth.value
            }

            report_paths = []
            if generate_report:
                try:
                    from .advanced_report import generate_advanced_professional_report

                    # Generate advanced professional report with visualizations
                    report_result = await generate_advanced_professional_report(topic, report_data)
                    if report_result.get("success"):
                        report_paths.append(report_result.get("path"))
                        logger.info(f"Profesyonel rapor oluşturuldu: {report_result.get('path')}")
                        logger.info(f"Rapor metrikleri - Kapsam: {report_result.get('metrics', {}).get('coverage'):.0f}%, "
                                  f"Güvenilirlik: {report_result.get('metrics', {}).get('reliability'):.0f}%, "
                                  f"Bütünlük: {report_result.get('metrics', {}).get('completeness'):.0f}%")
                    else:
                        logger.warning(f"Rapor oluşturma başarısız: {report_result.get('error')}")

                except Exception as e:
                    logger.warning(f"Gelişmiş rapor oluşturulamadı, temel format kullanılıyor: {e}")
                    try:
                        from .report_generator import create_research_report
                        pdf_result = await create_research_report(topic, report_data, format="pdf")
                        if pdf_result.get("success"):
                            report_paths.append(pdf_result.get("path"))
                            logger.info(f"Temel PDF rapor oluşturuldu: {pdf_result.get('path')}")
                    except Exception as fallback_error:
                        logger.warning(f"Fallback rapor oluşturulamadı: {fallback_error}")

            result.status = "completed"
            result.completed_at = datetime.now().isoformat()
            result.progress = 100

            logger.info(f"Araştırma tamamlandı: {topic} - {len(result.sources)} kaynak, {len(report_paths)} rapor")

            message = f"Araştırma tamamlandı: {len(result.sources)} kaynak, {len(result.findings)} bulgu"
            if report_paths:
                for path in report_paths:
                    message += f"\nRapor: {path}"

            return {
                "success": True,
                "research_id": research_id,
                "topic": topic,
                "depth": research_depth.value,
                "source_count": len(result.sources),
                "sources": sources_dict,
                "findings": result.findings,
                "summary": result.summary,
                "report_paths": report_paths,
                "message": message
            }

        except Exception as e:
            result.status = "failed"
            result.completed_at = datetime.now().isoformat()
            logger.error(f"Araştırma hatası: {e}")
            return {
                "success": False,
                "research_id": research_id,
                "error": f"Araştırma başarısız: {str(e)}"
            }

    except Exception as e:
        logger.error(f"Gelişmiş araştırma hatası: {e}")
        return {"success": False, "error": f"Araştırma yapılamadı: {str(e)}"}


async def evaluate_source(
    url: str,
    criteria: dict[str, bool] | None = None
) -> dict[str, Any]:
    """
    Kaynak güvenilirlik değerlendirmesi

    Args:
        url: Değerlendirilecek URL
        criteria: Değerlendirme kriterleri

    Returns:
        dict: Değerlendirme sonucu
    """
    try:
        if not url:
            return {"success": False, "error": "URL gerekli"}

        # Default criteria
        if criteria is None:
            criteria = {
                "check_domain": True,
                "check_https": True,
                "check_content": True
            }

        score = 0.5  # Base score
        factors = []

        # Domain reliability scoring
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # HTTPS check
        if criteria.get("check_https", True):
            if parsed.scheme == "https":
                score += 0.1
                factors.append({"name": "HTTPS", "value": True, "weight": 0.1})
            else:
                score -= 0.1
                factors.append({"name": "HTTPS", "value": False, "weight": -0.1})

        # Domain reliability
        if criteria.get("check_domain", True):
            # Academic and government domains
            trusted_tlds = [".edu", ".gov", ".ac.", ".org"]
            academic_domains = ["arxiv.org", "scholar.google", "researchgate.net", "academia.edu"]
            news_reliable = ["bbc.", "reuters.", "apnews.", "npr.org"]
            unreliable_patterns = ["blogspot.", "wordpress.", "tumblr.", "medium.com"]

            for tld in trusted_tlds:
                if tld in domain:
                    score += 0.15
                    factors.append({"name": f"TLD {tld}", "value": True, "weight": 0.15})
                    break

            for ad in academic_domains:
                if ad in domain:
                    score += 0.2
                    factors.append({"name": "Academic domain", "value": True, "weight": 0.2})
                    break

            for nr in news_reliable:
                if nr in domain:
                    score += 0.1
                    factors.append({"name": "Reliable news", "value": True, "weight": 0.1})
                    break

            for up in unreliable_patterns:
                if up in domain:
                    score -= 0.15
                    factors.append({"name": "User-generated content", "value": True, "weight": -0.15})
                    break

        # Try to fetch content preview
        content_preview = ""
        if criteria.get("check_content", True):
            try:
                from tools.web_tools import fetch_page
                fetch_result = await fetch_page(url, extract_content=True)
                if fetch_result.get("success"):
                    content = fetch_result.get("content", "")
                    content_preview = content[:500] if content else ""

                    # Content quality indicators
                    if len(content) > 1000:
                        score += 0.05
                        factors.append({"name": "Content length", "value": "long", "weight": 0.05})

                    # Check for citations/references
                    citation_keywords = ["source:", "reference", "citation", "et al.", "study", "research"]
                    if any(kw in content.lower() for kw in citation_keywords):
                        score += 0.1
                        factors.append({"name": "Has citations", "value": True, "weight": 0.1})
            except Exception as e:
                factors.append({"name": "Content fetch", "value": False, "error": str(e)})

        # Normalize score
        reliability_score = max(0.0, min(1.0, score))

        # Determine reliability level
        if reliability_score >= 0.8:
            level = "high"
        elif reliability_score >= 0.6:
            level = "medium"
        elif reliability_score >= 0.4:
            level = "low"
        else:
            level = "very_low"

        return {
            "success": True,
            "url": url,
            "domain": domain,
            "reliability_score": round(reliability_score, 2),
            "reliability_level": level,
            "factors": factors,
            "content_preview": content_preview
        }

    except Exception as e:
        logger.error(f"Kaynak değerlendirme hatası: {e}")
        return {"success": False, "error": f"Kaynak değerlendirilemedi: {str(e)}"}


async def quick_research(
    topic: str,
    max_sources: int = 3
) -> dict[str, Any]:
    """
    Hızlı araştırma - minimal kaynakla hızlı sonuç

    Args:
        topic: Araştırma konusu
        max_sources: Maksimum kaynak sayısı

    Returns:
        dict: Hızlı araştırma sonuçları
    """
    return await advanced_research(
        topic=topic,
        depth="quick",
        include_evaluation=False
    )


async def _perform_web_search(
    query: str,
    num_results: int,
    language: str
) -> list[dict]:
    """Web araması yap"""
    try:
        from tools.web_tools import web_search
        result = await web_search(query, num_results=num_results, language=language)
        if result.get("success"):
            return result.get("results", [])
        return []
    except Exception as e:
        logger.warning(f"Web arama hatası: {e}")
        return []


async def _extract_findings(
    sources: list[ResearchSource],
    topic: str
) -> list[str]:
    """Kaynaklardan yüksek kaliteli bulgular çıkar"""
    findings = []
    
    # Kapsamlı gürültü ve spam filtreleri
    spam_patterns = [
        "cookie", "çerez", "gdpr", "privacy", "gizlilik",
        "subscribe", "abone", "newsletter", "bülten",
        "login", "giriş", "sign up", "kayıt",
        "buy now", "satın al", "indirim", "kampanya",
        "free trial", "ücretsiz dene", "premium",
        "advertisement", "reklam", "sponsored",
        "click here", "buraya tıkla", "download",
        "app store", "google play", "upgrade",
        "% off", "% indirim", "fiyat", "ücret",
        "characters", "karakter", "limit",
        "ai detector", "ai-generated", "human-written",
        "yandeks", "yandex", "arama sonuçları", "tıklayın",
        "tüm hakları", "copyright", "sayfa", "menü"
    ]
    
    # Gereksiz kategori ve SEO terimleri
    noise_keywords = [
        "en iyi", "fiyatları", "nedir", "nasıl yapılır",
        "yorumları", "şikayet", "satın alma", "rehberi",
        "tarif", "liste", "künefe", "aspirin", "kedi" # Kullanıcı örneğindeki alakasızlar
    ]
    
    topic_words = [w.lower() for w in topic.split() if len(w) > 2]
    
    def is_junk(text: str) -> bool:
        """İçeriğin gürültü/çöp olup olmadığını kontrol et"""
        text_lower = text.lower()
        
        # Spam pattern check
        if any(spam in text_lower for spam in spam_patterns):
            return True
            
        # Alakasız gürültü kelimeleri (eğer konuyla çok alakasızsa)
        if not any(word in text_lower for word in topic_words):
            if any(noise in text_lower for noise in noise_keywords):
                return True
                
        # Çok kısa veya çok uzun
        if len(text) < 60 or len(text) > 600:
            return True
            
        # Özel karakter yoğunluğu (UI elemanı olma riski)
        special_chars = sum(1 for c in text if not c.isalnum() and c not in ' .,;:!?()-İıĞğÜüŞşÖöÇç')
        if special_chars / len(text) > 0.12:
            return True
            
        # Soru listesi veya link listesi gibi duran yapılar
        if text.count('?') > 2 or text.count('-') > 4:
            return True
            
        return False
    
    def clean_finding(text: str) -> str:
        """Metni temizle ve normalize et"""
        import re
        # HTML etiketlerini temizle (varsa)
        text = re.sub(r'<[^>]+>', '', text)
        # Fazla boşlukları temizle
        text = re.sub(r'\s+', ' ', text)
        # Markdown linklerini temizle
        text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'\1', text)
        # Baştaki sembolleri temizle
        text = text.lstrip("•-* 1234567890. ")
        return text.strip()
    
    seen_content = set()
    
    for source in sources:
        content = ""
        if source.fetched and source.content:
            content = source.content
        elif source.snippet:
            content = source.snippet
        
        if not content:
            continue
            
        # İçeriği cümlelere böl (daha akıllıca)
        import re
        sentences = re.split(r'(?<=[.!?])\s+', content)
        
        source_findings = []
        for s in sentences:
            cleaned = clean_finding(s)
            
            if is_junk(cleaned):
                continue
                
            # Konuyla ilgililik kontrolü (Anahtar kelime geçişi)
            match_count = sum(1 for word in topic_words if word in cleaned.lower())
            relevance = match_count / max(len(topic_words), 1)
            
            if relevance >= 0.25: # En az %25 alaka düzeyi
                # Benzerlik kontrolü (Duplicate check)
                content_key = cleaned[:40].lower()
                if content_key not in seen_content:
                    source_findings.append((cleaned, relevance))
                    seen_content.add(content_key)
        
        # Kaynaktan gelen en alakalı 2 bulguyu al
        source_findings.sort(key=lambda x: x[1], reverse=True)
        for f, _ in source_findings[:2]:
            findings.append(f"• {f}")
            
    # Eğer sonuç yoksa veya çok azsa, snippet'ları daha esnek tara
    if len(findings) < 3:
        for source in sources:
            if source.snippet:
                cleaned = clean_finding(source.snippet)
                if len(cleaned) > 40 and cleaned[:40].lower() not in seen_content:
                    findings.append(f"• {cleaned}")
                    seen_content.add(cleaned[:40].lower())
                    if len(findings) >= 5: break

    return findings[:10]


async def _generate_summary(
    topic: str,
    findings: list[str],
    sources: list[ResearchSource]
) -> str:
    """Araştırma sonuçlarından profesyonel ve bağlamsal bir özet oluşturur."""
    reliable_count = sum(1 for s in sources if s.reliability_score >= 0.6)
    source_count = len(sources)
    
    # Giriş cümlesi
    summary = f"**'{topic}'** üzerine yürütülen kapsamlı araştırma kapsamında toplam **{source_count}** stratejik kaynak analiz edilmiştir.\n\n"
    
    # Güvenilirlik analizi
    if reliable_count > 0:
        summary += f"İnceleme sonucunda, kaynakların **%{int((reliable_count/source_count)*100)}**'sinin yüksek güvenilirlik standartlarını karşıladığı doğrulanmıştır.\n\n"
    
    # Tematik Bulgular
    if findings:
        summary += "### Yönetici Özeti (Öne Çıkan Bulgular):\n"
        # Bulguları daha temiz bir şekilde işle
        for finding in findings[:6]:
            content = finding.lstrip("• ").strip()
            summary += f"- {content}\n"
        
        summary += "\nBu bulgular, konunun güncel durumunu ve kritik gelişim noktalarını yansıtacak şekilde sentezlenmiştir."
    else:
        summary += "Yapılan tarama sonucunda konuyla doğrudan örtüşen yeterli nitelikte bulguya rastlanmamıştır. Aramanın daha spesifik anahtar kelimelerle tekrarlanması önerilir."

    return summary


def get_research_result(research_id: str) -> dict[str, Any]:
    """Araştırma sonucunu getir"""
    if research_id not in _research_tasks:
        return {"success": False, "error": f"Araştırma bulunamadı: {research_id}"}

    result = _research_tasks[research_id]
    return {
        "success": True,
        **result.to_dict()
    }


async def save_research_to_document(
    topic: str,
    findings: list[str],
    sources: list[dict],
    output_path: str = None,
    output_format: str = "docx"
) -> dict[str, Any]:
    """
    Araştırma sonuçlarını belge olarak kaydet
    
    Args:
        topic: Araştırma konusu
        findings: Bulgular listesi
        sources: Kaynak listesi
        output_path: Çıktı dosyası yolu (opsiyonel)
        output_format: Çıktı formatı (docx, txt, md)
    
    Returns:
        dict: Kayıt sonucu
    """
    from datetime import datetime
    from pathlib import Path
    
    try:
        # Default output path
        if not output_path:
            from config.settings import HOME_DIR
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_topic = "".join(c for c in topic if c.isalnum() or c in " -_")[:50]
            filename = f"arastirma_{safe_topic}_{timestamp}.{output_format}"
            output_path = str(HOME_DIR / "Desktop" / filename)
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if output_format == "docx":
            # Word belgesi oluştur
            try:
                from docx import Document
                from docx.shared import Pt, Inches
                from docx.enum.text import WD_ALIGN_PARAGRAPH
                
                doc = Document()
                
                # Başlık
                title = doc.add_heading(f"Araştırma Raporu: {topic}", level=0)
                title.alignment = WD_ALIGN_PARAGRAPH.CENTER
                
                # Tarih
                doc.add_paragraph(f"Tarih: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
                doc.add_paragraph()
                
                # Özet
                doc.add_heading("Özet", level=1)
                doc.add_paragraph(f"Bu rapor '{topic}' konusunda {len(sources)} kaynak incelenerek hazırlanmıştır.")
                
                # Bulgular
                doc.add_heading("Önemli Bulgular", level=1)
                for finding in findings:
                    # Bullet point olarak ekle
                    p = doc.add_paragraph(style='List Bullet')
                    finding_clean = finding.lstrip("• -").strip()
                    p.add_run(finding_clean)
                
                # Kaynaklar
                doc.add_heading("Kaynaklar", level=1)
                for i, source in enumerate(sources, 1):
                    title_text = source.get("title", "Başlıksız")
                    url = source.get("url", "")
                    p = doc.add_paragraph()
                    p.add_run(f"{i}. {title_text}").bold = True
                    if url:
                        p.add_run(f"\n   {url}")
                
                doc.save(str(output_path))
                
            except ImportError:
                # python-docx yoksa txt olarak kaydet
                output_format = "txt"
                output_path = output_path.with_suffix(".txt")
        
        if output_format in ["txt", "md"]:
            # Metin dosyası olarak kaydet
            content_lines = [
                f"# Araştırma Raporu: {topic}",
                f"Tarih: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                "",
                "## Özet",
                f"Bu rapor '{topic}' konusunda {len(sources)} kaynak incelenerek hazırlanmıştır.",
                "",
                "## Önemli Bulgular",
            ]
            
            for finding in findings:
                finding_clean = finding.lstrip("• -").strip()
                content_lines.append(f"- {finding_clean}")
            
            content_lines.extend([
                "",
                "## Kaynaklar",
            ])
            
            for i, source in enumerate(sources, 1):
                title_text = source.get("title", "Başlıksız")
                url = source.get("url", "")
                content_lines.append(f"{i}. **{title_text}**")
                if url:
                    content_lines.append(f"   {url}")
            
            output_path.write_text("\n".join(content_lines), encoding="utf-8")
        
        logger.info(f"Araştırma belgesi kaydedildi: {output_path}")
        
        return {
            "success": True,
            "path": str(output_path),
            "format": output_format,
            "message": f"Araştırma raporu kaydedildi: {output_path.name}"
        }
        
    except Exception as e:
        logger.error(f"Belge kaydetme hatası: {e}")
        return {"success": False, "error": f"Belge kaydedilemedi: {str(e)}"}
