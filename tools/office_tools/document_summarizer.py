"""Document Summarizer - Use LLM to summarize documents"""

from pathlib import Path
from typing import Any
from utils.logger import get_logger
from security.validator import validate_path

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
                    rows = result.get("data")
                    if isinstance(rows, list):
                        preview_lines = []
                        for row in rows[:200]:
                            if isinstance(row, dict):
                                line = " | ".join(f"{k}: {v}" for k, v in row.items())
                            elif isinstance(row, (list, tuple)):
                                line = " | ".join(str(v) for v in row)
                            else:
                                line = str(row)
                            if line.strip():
                                preview_lines.append(line.strip())
                        document_content = "\n".join(preview_lines)
                    elif isinstance(rows, dict):
                        sections = []
                        for sheet, sheet_rows in rows.items():
                            sections.append(f"[Sheet: {sheet}]")
                            if isinstance(sheet_rows, list):
                                for row in sheet_rows[:100]:
                                    if isinstance(row, dict):
                                        sections.append(" | ".join(f"{k}: {v}" for k, v in row.items()))
                                    elif isinstance(row, (list, tuple)):
                                        sections.append(" | ".join(str(v) for v in row))
                                    else:
                                        sections.append(str(row))
                        document_content = "\n".join(sections)
                    else:
                        document_content = str(result.get("summary", "") or "")
            elif ext == ".pdf":
                from .pdf_tools import read_pdf
                result = await read_pdf(path, extract_tables=False, use_ocr=False)
                if result.get("success"):
                    document_content = str(result.get("content", "") or "")[:MAX_CONTENT_LENGTH]
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

        # Use the configured global LLM stack (OpenAI/Groq/Gemini/Ollama...)
        try:
            from core.llm_client import LLMClient
            llm = LLMClient()
            summary = (await llm.generate(
                full_prompt,
                system_prompt=(
                    "Sen profesyonel bir döküman özetleyicisin. "
                    "Yanıtını sadece istenen özeti üretmek için kullan. "
                    "Gereksiz giriş/çıkış cümleleri ekleme."
                ),
                role="analysis",
            )).strip()
        except Exception as llm_exc:
            logger.error(f"LLM summarize error: {llm_exc}")
            return {"success": False, "error": f"LLM özetleme hatası: {llm_exc}"}

        if summary.lower().startswith("hata:"):
            return {"success": False, "error": summary}

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
