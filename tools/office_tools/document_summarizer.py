"""Document Summarizer - Use LLM to summarize documents"""

import asyncio
from pathlib import Path
from typing import Any
from utils.logger import get_logger
from security.validator import validate_path
from config.settings import OLLAMA_HOST, OLLAMA_MODEL

logger = get_logger("office.summarizer")

# Maximum content length for summarization
MAX_CONTENT_LENGTH = 8000


async def summarize_document(
    path: str = None,
    content: str = None,
    style: str = "brief"
) -> dict[str, Any]:
    """Summarize a document using LLM

    Args:
        path: Path to the document (Word, Excel, or PDF)
        content: Direct text content to summarize (alternative to path)
        style: Summary style - "brief" (short), "detailed" (longer), "bullets" (bullet points)
    """
    try:
        # Either path or content must be provided
        if not path and not content:
            return {"success": False, "error": "Dosya yolu veya içerik sağlanmalı"}

        document_content = content
        filename = "metin"

        # Read document if path provided
        if path:
            file_path = Path(path).expanduser().resolve()
            filename = file_path.name
            ext = file_path.suffix.lower()

            if ext in [".docx", ".doc"]:
                from .word_tools import read_word
                result = await read_word(path, max_chars=MAX_CONTENT_LENGTH)
            elif ext in [".xlsx", ".xls"]:
                from .excel_tools import read_excel
                result = await read_excel(path)
                if result.get("success"):
                    document_content = result.get("text_output", "")
            elif ext == ".pdf":
                from .pdf_tools import read_pdf
                result = await read_pdf(path, max_chars=MAX_CONTENT_LENGTH)
            elif ext == ".txt":
                # Simple text file
                is_valid, error, _ = validate_path(path)
                if not is_valid:
                    return {"success": False, "error": error}
                with open(file_path, "r", encoding="utf-8") as f:
                    document_content = f.read()[:MAX_CONTENT_LENGTH]
                result = {"success": True, "content": document_content}
            else:
                return {"success": False, "error": f"Desteklenmeyen dosya türü: {ext}"}

            if not result.get("success"):
                return result

            if not document_content:
                document_content = result.get("content", "")

        if not document_content or len(document_content.strip()) < 50:
            return {"success": False, "error": "Özetlenecek yeterli içerik yok"}

        # Truncate if too long
        if len(document_content) > MAX_CONTENT_LENGTH:
            document_content = document_content[:MAX_CONTENT_LENGTH]

        # Build prompt based on style
        style_prompts = {
            "brief": "Aşağıdaki belgeyi 2-3 cümleyle özetle. Türkçe yanıtla.",
            "detailed": "Aşağıdaki belgeyi detaylı bir paragraf halinde özetle. Ana noktaları ve önemli detayları dahil et. Türkçe yanıtla.",
            "bullets": "Aşağıdaki belgenin ana noktalarını madde işaretli liste halinde özetle (5-7 madde). Türkçe yanıtla."
        }

        prompt = style_prompts.get(style, style_prompts["brief"])
        full_prompt = f"{prompt}\n\nBelge:\n{document_content}"

        # Call Ollama for summarization
        try:
            import httpx
        except ImportError:
            return {"success": False, "error": "httpx kurulu değil"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{OLLAMA_HOST}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {
                        "num_predict": 500,
                        "temperature": 0.3
                    }
                }
            )

            if response.status_code != 200:
                return {"success": False, "error": f"LLM hatası: {response.status_code}"}

            result = response.json()
            summary = result.get("response", "").strip()

        if not summary:
            return {"success": False, "error": "Özet oluşturulamadı"}

        logger.info(f"Summarized document: {filename}, style: {style}")

        return {
            "success": True,
            "filename": filename,
            "style": style,
            "summary": summary,
            "original_length": len(document_content),
            "summary_length": len(summary)
        }

    except Exception as e:
        logger.error(f"Summarize error: {e}")
        return {"success": False, "error": str(e)}
