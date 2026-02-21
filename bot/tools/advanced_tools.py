"""Advanced AI Tools - Enhanced research, summarization and file creation"""

import asyncio
import os
import json
from typing import Any, Dict, List
from pathlib import Path
from datetime import datetime
from utils.logger import get_logger

logger = get_logger("tools.advanced")


async def advanced_research(
    topic: str,
    depth: str = "comprehensive",
    sources: int = 10,
    include_images: bool = False,
    language: str = "tr"
) -> dict[str, Any]:
    """Advanced research with AI-powered summarization and analysis

    Args:
        topic: Research topic
        depth: "basic", "moderate", "comprehensive", "expert"
        sources: Number of sources to analyze
        include_images: Whether to include image analysis
        language: Output language ("tr", "en")

    Returns:
        Comprehensive research results with AI analysis
    """
    try:
        from .web_tools.background_research import start_research, get_research_status

        # Start research
        research_result = await start_research(topic, depth, None)
        if not research_result.get("success"):
            return research_result

        task_id = research_result["task_id"]

        # Wait for completion with progress updates
        max_wait = 300  # 5 minutes max
        wait_time = 0
        while wait_time < max_wait:
            status = await get_research_status(task_id)
            if status.get("status") in ["completed", "failed"]:
                break
            await asyncio.sleep(2)
            wait_time += 2

        if wait_time >= max_wait:
            return {"success": False, "error": "Research timed out"}

        final_status = await get_research_status(task_id)
        if final_status.get("status") != "completed":
            return {"success": False, "error": final_status.get("error", "Research failed")}

        # Get research results
        research_data = final_status.get("results", {})

        # Enhanced AI analysis
        enhanced_summary = await _ai_enhance_summary(topic, research_data, language)

        return {
            "success": True,
            "topic": topic,
            "summary": enhanced_summary,
            "sources": research_data.get("sources", []),
            "source_count": research_data.get("source_count", 0),
            "ai_analysis": True,
            "language": language,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Advanced research error: {e}")
        return {"success": False, "error": str(e)}


async def smart_summarize(
    content: str,
    content_type: str = "text",
    summary_type: str = "concise",
    language: str = "tr",
    max_length: int = 500
) -> dict[str, Any]:
    """AI-powered intelligent summarization

    Args:
        content: Content to summarize
        content_type: "text", "article", "document", "code", "conversation"
        summary_type: "concise", "detailed", "bullet_points", "key_insights"
        language: Output language
        max_length: Maximum summary length in characters

    Returns:
        Intelligent summary with key insights
    """
    try:
        # Get LLM client for advanced summarization
        from core.llm_client import LLMClient
        llm = LLMClient()

        # Create smart prompt based on content type and summary type
        prompt = _create_summary_prompt(content, content_type, summary_type, language, max_length)

        # Get AI summary
        response = await llm._ask_llm(prompt)
        ai_summary = response.get("message", "")

        # Extract key insights
        insights = await _extract_key_insights(content, content_type)

        # Calculate content metrics
        metrics = _calculate_content_metrics(content)

        return {
            "success": True,
            "summary": ai_summary,
            "key_insights": insights,
            "content_type": content_type,
            "summary_type": summary_type,
            "language": language,
            "metrics": metrics,
            "original_length": len(content),
            "summary_length": len(ai_summary)
        }

    except Exception as e:
        logger.error(f"Smart summarize error: {e}")
        return {"success": False, "error": str(e)}


async def create_smart_file(
    content: str,
    filename: str,
    file_type: str = "auto",
    template: str = "default",
    optimize: bool = True
) -> dict[str, Any]:
    """AI-powered intelligent file creation

    Args:
        content: Content to write to file
        filename: Target filename
        file_type: "auto", "python", "markdown", "json", "txt", "html", "csv"
        template: Template to use ("default", "report", "documentation", "config")
        optimize: Whether to optimize content for the file type

    Returns:
        File creation result with optimizations
    """
    try:
        # Determine file type if auto
        if file_type == "auto":
            file_type = _detect_file_type(filename, content)

        # Apply AI optimizations based on file type
        if optimize:
            content = await _optimize_content_for_filetype(content, file_type, template)

        # Create file
        file_path = Path(filename)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write with appropriate encoding
        encoding = "utf-8"
        if file_type in ["python", "json", "javascript"]:
            # Ensure proper formatting for code files
            content = _format_code_content(content, file_type)

        with open(file_path, "w", encoding=encoding) as f:
            f.write(content)

        # Get file stats
        stat = file_path.stat()

        return {
            "success": True,
            "file_path": str(file_path.absolute()),
            "file_type": file_type,
            "template": template,
            "optimized": optimize,
            "size": stat.st_size,
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "content_preview": content[:200] + "..." if len(content) > 200 else content
        }

    except Exception as e:
        logger.error(f"Smart file creation error: {e}")
        return {"success": False, "error": str(e)}


async def analyze_document(
    file_path: str,
    analysis_type: str = "comprehensive",
    extract_metadata: bool = True
) -> dict[str, Any]:
    """AI-powered document analysis

    Args:
        file_path: Path to document file
        analysis_type: "basic", "comprehensive", "sentiment", "topics"
        extract_metadata: Whether to extract file metadata

    Returns:
        Document analysis results
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        # Read file content
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Extract metadata
        metadata = {}
        if extract_metadata:
            stat = path.stat()
            metadata = {
                "size": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "extension": path.suffix,
                "name": path.name
            }

        # AI analysis based on type
        analysis = await _perform_document_analysis(content, analysis_type)

        return {
            "success": True,
            "file_path": file_path,
            "analysis_type": analysis_type,
            "metadata": metadata,
            "analysis": analysis,
            "content_length": len(content)
        }

    except Exception as e:
        logger.error(f"Document analysis error: {e}")
        return {"success": False, "error": str(e)}


async def generate_report(
    data: dict,
    report_type: str = "summary",
    format: str = "markdown",
    include_charts: bool = False
) -> dict[str, Any]:
    """Generate intelligent reports from data

    Args:
        data: Data to generate report from
        report_type: "summary", "analysis", "comparison", "trends"
        format: "markdown", "html", "json", "txt"
        include_charts: Whether to include ASCII charts

    Returns:
        Generated report
    """
    try:
        # AI-powered report generation
        from core.llm_client import LLMClient
        llm = LLMClient()

        prompt = f"""
        Generate a {report_type} report in {format} format from the following data:

        Data: {json.dumps(data, indent=2, ensure_ascii=False)}

        Make the report comprehensive, well-structured, and insightful.
        Include key findings, trends, and recommendations where applicable.
        """

        response = await llm._ask_llm(prompt)
        report_content = response.get("message", "")

        # Format the report
        if format == "markdown":
            report_content = _format_markdown_report(report_content, data)
        elif format == "html":
            report_content = _format_html_report(report_content, data)
        elif format == "json":
            report_content = json.dumps({
                "report": report_content,
                "data": data,
                "generated_at": datetime.now().isoformat()
            }, indent=2, ensure_ascii=False)

        return {
            "success": True,
            "report": report_content,
            "report_type": report_type,
            "format": format,
            "data_summary": f"Processed {len(str(data))} characters of data",
            "generated_at": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Report generation error: {e}")
        return {"success": False, "error": str(e)}


# Helper functions

async def _ai_enhance_summary(topic: str, research_data: dict, language: str) -> str:
    """Use AI to enhance research summary"""
    try:
        from core.llm_client import LLMClient
        llm = LLMClient()

        sources = research_data.get("sources", [])
        basic_summary = research_data.get("summary", "")

        prompt = f"""
        Enhance this research summary about "{topic}" with AI analysis:

        Basic Summary:
        {basic_summary}

        Sources ({len(sources)}):
        {json.dumps(sources[:5], indent=2, ensure_ascii=False)}

        Provide an enhanced summary in {language} that:
        1. Synthesizes information from multiple sources
        2. Identifies key trends and insights
        3. Provides balanced perspective
        4. Includes source credibility assessment
        5. Suggests areas for further research

        Make it comprehensive but concise.
        """

        response = await llm._ask_llm(prompt)
        return response.get("message", basic_summary)

    except Exception as e:
        logger.warning(f"AI enhancement failed: {e}")
        return research_data.get("summary", "")


def _create_summary_prompt(content: str, content_type: str, summary_type: str, language: str, max_length: int) -> str:
    """Create intelligent summary prompt"""
    type_instructions = {
        "text": "general text content",
        "article": "news article or blog post",
        "document": "formal document or report",
        "code": "programming code with comments",
        "conversation": "chat or dialogue transcript"
    }

    summary_instructions = {
        "concise": "brief and to the point",
        "detailed": "comprehensive with all important details",
        "bullet_points": "organized in clear bullet points",
        "key_insights": "focus on main insights and takeaways"
    }

    return f"""
    Summarize the following {type_instructions.get(content_type, 'content')}:

    {content[:4000]}{'...' if len(content) > 4000 else ''}

    Provide a {summary_instructions.get(summary_type, 'concise')} summary in {language}.
    Maximum length: {max_length} characters.
    Focus on the most important information and key takeaways.
    """


async def _extract_key_insights(content: str, content_type: str) -> list:
    """Extract key insights from content"""
    try:
        # Simple keyword-based extraction for now
        # Could be enhanced with AI in the future
        insights = []

        if content_type == "code":
            # Extract function/class names
            import re
            functions = re.findall(r'def (\w+)', content)
            classes = re.findall(r'class (\w+)', content)
            if functions:
                insights.append(f"Functions: {', '.join(functions[:5])}")
            if classes:
                insights.append(f"Classes: {', '.join(classes[:5])}")

        elif content_type in ["article", "document"]:
            # Extract potential key sentences
            sentences = content.split('.')
            long_sentences = [s.strip() for s in sentences if len(s.strip()) > 50][:3]
            insights.extend(long_sentences)

        return insights[:5]  # Max 5 insights

    except Exception as e:
        logger.warning(f"Insight extraction failed: {e}")
        return []


def _calculate_content_metrics(content: str) -> dict:
    """Calculate basic content metrics"""
    return {
        "characters": len(content),
        "words": len(content.split()),
        "sentences": len(content.split('.')),
        "lines": len(content.split('\n')),
        "avg_word_length": sum(len(word) for word in content.split()) / max(len(content.split()), 1)
    }


def _detect_file_type(filename: str, content: str) -> str:
    """Detect file type from filename and content"""
    ext = Path(filename).suffix.lower()

    ext_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.json': 'json',
        '.md': 'markdown',
        '.html': 'html',
        '.css': 'css',
        '.txt': 'txt',
        '.csv': 'csv',
        '.xml': 'xml'
    }

    if ext in ext_map:
        return ext_map[ext]

    # Content-based detection
    if content.strip().startswith(('{', '[')):
        try:
            json.loads(content)
            return 'json'
        except:
            pass

    if '<html' in content.lower() or '<!DOCTYPE html' in content.lower():
        return 'html'

    return 'txt'


async def _optimize_content_for_filetype(content: str, file_type: str, template: str) -> str:
    """Optimize content for specific file type"""
    try:
        from core.llm_client import LLMClient
        llm = LLMClient()

        prompt = f"""
        Optimize this content for a {file_type} file with {template} template:

        Content: {content[:2000]}

        Provide optimized version that follows {file_type} best practices and {template} conventions.
        """

        response = await llm._ask_llm(prompt)
        optimized = response.get("message", content)

        return optimized if optimized.strip() else content

    except Exception as e:
        logger.warning(f"Content optimization failed: {e}")
        return content


def _format_code_content(content: str, file_type: str) -> str:
    """Format code content appropriately"""
    if file_type == 'json':
        try:
            parsed = json.loads(content)
            return json.dumps(parsed, indent=2, ensure_ascii=False)
        except:
            pass
    elif file_type == 'python':
        # Basic Python formatting
        lines = content.split('\n')
        formatted_lines = []
        indent_level = 0

        for line in lines:
            stripped = line.strip()
            if not stripped:
                formatted_lines.append('')
                continue

            # Adjust indentation
            if stripped.startswith(('def ', 'class ', 'if ', 'for ', 'while ', 'try:', 'except:', 'finally:')):
                formatted_lines.append('    ' * indent_level + stripped)
                if not stripped.endswith(':'):
                    indent_level += 1
            elif stripped.startswith(('return', 'break', 'continue', 'pass')):
                formatted_lines.append('    ' * indent_level + stripped)
                indent_level = max(0, indent_level - 1)
            else:
                formatted_lines.append('    ' * indent_level + stripped)

        return '\n'.join(formatted_lines)

    return content


async def _perform_document_analysis(content: str, analysis_type: str) -> dict:
    """Perform document analysis"""
    metrics = _calculate_content_metrics(content)

    analysis = {
        "metrics": metrics,
        "readability_score": _calculate_readability(content),
        "language": _detect_language(content)
    }

    if analysis_type == "comprehensive":
        analysis["word_frequency"] = _get_word_frequency(content)
        analysis["sentiment"] = _analyze_sentiment(content)

    return analysis


def _calculate_readability(content: str) -> float:
    """Calculate basic readability score"""
    words = len(content.split())
    sentences = len(content.split('.'))
    if sentences == 0:
        return 0
    avg_words_per_sentence = words / sentences
    # Simple readability formula
    return max(0, min(100, 200 - avg_words_per_sentence))


def _detect_language(content: str) -> str:
    """Simple language detection"""
    turkish_chars = set('çğıöşüÇĞİÖŞÜ')
    if any(char in content for char in turkish_chars):
        return "tr"
    return "en"


def _get_word_frequency(content: str) -> dict:
    """Get word frequency analysis"""
    words = content.lower().split()
    # Remove common stop words
    stop_words = {'ve', 'veya', 'ile', 'da', 'de', 'bir', 'bu', 'şu', 'o', 'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
    filtered_words = [word for word in words if word not in stop_words and len(word) > 2]

    frequency = {}
    for word in filtered_words:
        frequency[word] = frequency.get(word, 0) + 1

    # Return top 10 words
    sorted_freq = sorted(frequency.items(), key=lambda x: x[1], reverse=True)
    return dict(sorted_freq[:10])


def _analyze_sentiment(content: str) -> str:
    """Simple sentiment analysis"""
    positive_words = {'iyi', 'güzel', 'harika', 'mükemmel', 'başarılı', 'good', 'great', 'excellent', 'success', 'happy'}
    negative_words = {'kötü', 'berbat', 'sorun', 'hata', 'başarısız', 'bad', 'terrible', 'error', 'fail', 'sad'}

    words = content.lower().split()
    positive_count = sum(1 for word in words if word in positive_words)
    negative_count = sum(1 for word in words if word in negative_words)

    if positive_count > negative_count:
        return "positive"
    elif negative_count > positive_count:
        return "negative"
    else:
        return "neutral"


def _format_markdown_report(content: str, data: dict) -> str:
    """Format report as markdown"""
    return f"""# AI Generated Report

Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Summary
{content}

## Data Overview
- Total items: {len(str(data))}
- Generated: {datetime.now().isoformat()}

## Raw Data
```json
{json.dumps(data, indent=2, ensure_ascii=False)}
```
"""


def _format_html_report(content: str, data: dict) -> str:
    """Format report as HTML"""
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>AI Generated Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        .header {{ background: #f0f0f0; padding: 20px; border-radius: 5px; }}
        .content {{ margin: 20px 0; }}
        .data {{ background: #f9f9f9; padding: 15px; border-left: 4px solid #007acc; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>AI Generated Report</h1>
        <p>Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>

    <div class="content">
        <h2>Summary</h2>
        <p>{content}</p>
    </div>

    <div class="data">
        <h2>Data Overview</h2>
        <ul>
            <li>Total items: {len(str(data))}</li>
            <li>Generated: {datetime.now().isoformat()}</li>
        </ul>

        <h3>Raw Data</h3>
        <pre>{json.dumps(data, indent=2, ensure_ascii=False)}</pre>
    </div>
</body>
</html>"""