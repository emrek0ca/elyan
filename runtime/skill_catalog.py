from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any


_TOKEN_STOPWORDS = {
    "a",
    "acik",
    "and",
    "are",
    "bir",
    "bu",
    "da",
    "de",
    "for",
    "from",
    "gibi",
    "i",
    "ile",
    "in",
    "is",
    "it",
    "mi",
    "mı",
    "na",
    "of",
    "or",
    "olan",
    "olanlar",
    "olarak",
    "on",
    "the",
    "to",
    "ve",
    "ya",
    "yer",
    "yap",
    "yeni",
}

_CATEGORY_BASE_PRIORITY = {
    "math": 92,
    "browser": 86,
    "document": 84,
    "research": 82,
    "analysis": 78,
    "vision": 76,
    "image": 68,
    "operator": 60,
    "mcp": 58,
    "custom": 52,
}

_LATENCY_PRIORITIES = {
    "quick": 3,
    "medium": 2,
    "slow": 0,
}


def _fold_text(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return folded.lower()


def _tokenize(value: Any) -> list[str]:
    folded = _fold_text(value)
    if not folded:
        return []
    return [
        token
        for token in re.findall(r"[a-z0-9]+", folded)
        if token and token not in _TOKEN_STOPWORDS
    ]


def _unique_tokens(*values: Any) -> list[str]:
    tokens: set[str] = set()
    for value in values:
        tokens.update(_tokenize(value))
    return sorted(tokens)


def _inferred_latency_class(defn: dict[str, Any]) -> str:
    override = str(defn.get("latencyClass", "") or "").strip().lower()
    if override in {"quick", "medium", "slow"}:
        return override
    adapter = str(defn.get("adapter", "") or "").strip().lower()
    category = str(defn.get("category", "") or "custom").strip().lower()
    if adapter in {
        "document_write",
        "spreadsheet_write",
        "presentation_write",
        "canvas_write",
        "image_generate",
        "image_edit",
        "desktop_operator.run",
        "desktop_operator.execute_action",
    }:
        return "slow"
    if adapter in {
        "web_research",
        "ocr_read",
        "data_analyze",
        "chart_generate",
        "retrieve_context",
        "mcp_call_tool",
    }:
        return "medium"
    if category in {"browser", "math", "document"}:
        return "quick"
    if category in {"vision", "image", "analysis", "research"}:
        return "medium"
    return "quick"


def _inferred_selection_priority(defn: dict[str, Any]) -> int:
    override = defn.get("selectionPriority")
    if isinstance(override, (int, float)):
        return max(0, min(100, int(round(float(override)))))
    category = str(defn.get("category", "") or "custom").strip().lower()
    base = _CATEGORY_BASE_PRIORITY.get(category, 50)
    latency = _inferred_latency_class(defn)
    base += _LATENCY_PRIORITIES.get(latency, 1)
    if bool(defn.get("requiresConfirmation", False)):
        base -= 6
    adapter = str(defn.get("adapter", "") or "").strip().lower()
    if adapter in {"document_read", "retrieve_context", "browser_control", "math_solve"}:
        base += 4
    if adapter in {"web_research", "ocr_read", "data_analyze"}:
        base += 2
    return max(0, min(100, base))


def _inferred_expected_inputs(defn: dict[str, Any]) -> list[str]:
    expected = defn.get("expectedInputs")
    if isinstance(expected, list):
        values = [str(item).strip() for item in expected if str(item).strip()]
        if values:
            return list(dict.fromkeys(values))
    parameters = [str(item).strip() for item in (defn.get("parameters", []) or []) if str(item).strip()]
    required = [str(item).strip() for item in (defn.get("requiredParameters", []) or []) if str(item).strip()]
    return list(dict.fromkeys([*required, *parameters]))


def _inferred_intent_tags(defn: dict[str, Any]) -> list[str]:
    manual = defn.get("intentTags", [])
    tokens = _unique_tokens(
        defn.get("id", ""),
        defn.get("name", ""),
        defn.get("description", ""),
        defn.get("category", ""),
        defn.get("adapter", ""),
        *([item for item in manual] if isinstance(manual, list) else []),
        *([item for item in (defn.get("libraries", []) or []) if str(item).strip()]),
    )
    return tokens


def _skill(defn: dict[str, Any]) -> dict[str, Any]:
    steps = copy.deepcopy(defn.get("steps", []) or [])
    return {
        "id": str(defn.get("id", "") or ""),
        "name": str(defn.get("name", "") or ""),
        "description": str(defn.get("description", "") or ""),
        "enabled": True,
        "category": str(defn.get("category", "") or "custom"),
        "requiresConfirmation": bool(defn.get("requiresConfirmation", False)),
        "parameters": list(defn.get("parameters", []) or []),
        "requiredParameters": list(defn.get("requiredParameters", []) or []),
        "intentTags": _inferred_intent_tags(defn),
        "latencyClass": _inferred_latency_class(defn),
        "selectionPriority": _inferred_selection_priority(defn),
        "expectedInputs": _inferred_expected_inputs(defn),
        "adapter": str(defn.get("adapter", "") or ""),
        "libraries": [str(item) for item in (defn.get("libraries", []) or []) if str(item).strip()],
        "steps": steps,
        "stepCount": len(steps),
    }


BUILTIN_SKILL_DEFINITIONS: list[dict[str, Any]] = [
    {
        # İlk "görev tarifi" skill'i (Tek Spec, Üç Katman — Adım 2): sayfadan
        # link listesi topla → hedef klasörü hazırla → HER linki indir.
        # Kullanıcının "youtube-transkript" senaryosu bu tarifin bir örneğidir;
        # goal serbest metindir, tarayıcı ajanı keşfi kendi yapar.
        "id": "web.collect_download",
        "name": "Web Collect & Download",
        "description": "Bir web sayfasından link listesi toplar ve her birini belirtilen klasöre indirir.",
        "category": "browser",
        "adapter": "browser_agent.run",
        "libraries": ["playwright"],
        "requiresConfirmation": True,
        "parameters": ["goal", "outputDir"],
        "requiredParameters": ["goal", "outputDir"],
        "intentTags": ["indir", "topla", "linkler", "transcript", "transkript", "download", "collect"],
        "steps": [
            {
                "id": "klasor",
                "capability": "make_directory",
                "description": "Hedef klasörü hazırla",
                "args": {},
                "argsFromPayload": {"path": "outputDir"},
            },
            {
                "id": "topla",
                "capability": "browser_agent.run",
                "description": "Sayfayı gezip istenen linkleri topla",
                "args": {},
                "argsFromPayload": {"goal": "goal"},
            },
            {
                "id": "indir",
                "capability": "browser_session.download",
                "description": "{{index}}. bağlantı indiriliyor",
                "forEach": "{{steps.topla.result.collected}}",
                "args": {"url": "{{item.href}}"},
                "argsFromPayload": {"output_dir": "outputDir"},
            },
        ],
    },
    {
        "id": "document.summary",
        "name": "Document Summary",
        "description": "Belgeyi kısa özet olarak çıkarır.",
        "category": "document",
        "adapter": "document_read",
        "libraries": ["pymupdf", "pypdf", "markitdown", "mammoth"],
        "parameters": ["path"],
        "requiredParameters": ["path"],
        "steps": [
            {
                "capability": "document_read",
                "description": "Belge özeti",
                "args": {"mode": "summary"},
                "argsFromPayload": {"path": "path"},
            }
        ],
    },
    {
        "id": "document.summary_and_save",
        "name": "Document Summary and Save",
        "description": "Belgeyi veya paylaşılan metni özetler ve masaüstüne DOCX olarak kaydeder.",
        "category": "document",
        "adapter": "document_write",
        "libraries": ["pymupdf", "pypdf", "markitdown", "mammoth", "python-docx"],
        "requiresConfirmation": True,
        "parameters": ["path", "text", "selectedPaths", "outputPath", "title", "overwrite"],
        "requiredParameters": ["outputPath"],
        "selectionPriority": 96,
        "steps": [
            {
                "capability": "document_read",
                "description": "Kaynak içeriği özetle",
                "args": {"mode": "summary"},
                "argsFromPayload": {
                    "path": "path",
                    "text": "text",
                    "_selectedPaths": "selectedPaths",
                },
            },
            {
                "capability": "document_write",
                "description": "Özeti DOCX olarak kaydet",
                "args": {"overwrite": False},
                "argsFromPayload": {
                    "outputPath": "outputPath",
                    "title": "title",
                    "overwrite": "overwrite",
                },
                "argsFromPreviousResult": {"source_context": "summary"},
            },
        ],
    },
    {
        "id": "document.bullets",
        "name": "Document Bullets",
        "description": "Belgeyi maddeler halinde çıkarır.",
        "category": "document",
        "adapter": "document_read",
        "libraries": ["pymupdf", "pypdf", "markitdown", "mammoth"],
        "parameters": ["path"],
        "requiredParameters": ["path"],
        "steps": [
            {
                "capability": "document_read",
                "description": "Belge maddeleri",
                "args": {"mode": "bullets"},
                "argsFromPayload": {"path": "path"},
            }
        ],
    },
    {
        "id": "file.explain",
        "name": "File Explain",
        "description": "Belgeyi sade şekilde açıklar.",
        "category": "document",
        "adapter": "document_read",
        "libraries": ["pymupdf", "pypdf", "markitdown", "mammoth"],
        "parameters": ["path"],
        "requiredParameters": ["path"],
        "steps": [
            {
                "capability": "document_read",
                "description": "Belgeyi açıkla",
                "args": {"mode": "summary"},
                "argsFromPayload": {"path": "path"},
            }
        ],
    },
    {
        "id": "research.brief",
        "name": "Research Brief",
        "description": "Yerel bağlam ve çalışma alanından kısa, kaynaklı araştırma özeti üretir.",
        "category": "research",
        "adapter": "retrieve_context",
        "libraries": ["sentence-transformers"],
        "parameters": ["query", "sources", "limit", "conversationId"],
        "requiredParameters": ["query"],
        "steps": [
            {
                "capability": "retrieve_context",
                "description": "Yerel bağlamı topla",
                "argsFromPayload": {
                    "query": "query",
                    "sources": "sources",
                    "limit": "limit",
                    "conversationId": "conversationId",
                },
            }
        ],
    },
    {
        "id": "source.verify",
        "name": "Source Verify",
        "description": "Soru için kısa kaynak kontrolü yapar.",
        "category": "research",
        "adapter": "retrieve_context",
        "libraries": ["sentence-transformers"],
        "parameters": ["query", "sources", "limit", "conversationId"],
        "requiredParameters": ["query"],
        "steps": [
            {
                "capability": "retrieve_context",
                "description": "Kaynak kontrolü",
                "args": {"sources": "workspace,conversations", "limit": 5},
                "argsFromPayload": {
                    "query": "query",
                    "sources": "sources",
                    "limit": "limit",
                    "conversationId": "conversationId",
                },
            }
        ],
    },
    {
        "id": "workspace.answer",
        "name": "Workspace Answer",
        "description": "Çalışma alanından cevap hazırlamak için bağlam toplar.",
        "category": "research",
        "adapter": "retrieve_context",
        "libraries": ["sentence-transformers"],
        "parameters": ["query", "limit", "conversationId"],
        "requiredParameters": ["query"],
        "steps": [
            {
                "capability": "retrieve_context",
                "description": "Çalışma alanını tara",
                "args": {"sources": "workspace", "limit": 6},
                "argsFromPayload": {
                    "query": "query",
                    "limit": "limit",
                    "conversationId": "conversationId",
                },
            }
        ],
    },
    {
        "id": "web.research",
        "name": "Web Research",
        "description": "Public web üzerinde kaynak toplayıp kısa bir araştırma özeti üretir.",
        "category": "research",
        "adapter": "web_research",
        "libraries": ["httpx", "trafilatura", "playwright"],
        "parameters": ["query", "maxResults", "languageHint"],
        "requiredParameters": ["query"],
        "steps": [
            {
                "capability": "web_research",
                "description": "Web taraması",
                "argsFromPayload": {
                    "query": "query",
                    "max_results": "maxResults",
                    "language_hint": "languageHint",
                },
            }
        ],
    },
    {
        "id": "document.report_from_context",
        "name": "Context Report",
        "description": "Bağlamı toplayıp DOCX rapora dönüştürür.",
        "category": "document",
        "adapter": "document_write",
        "libraries": ["python-docx", "sentence-transformers"],
        "requiresConfirmation": True,
        "parameters": ["query", "outputPath", "title", "sources", "limit", "conversationId", "overwrite"],
        "requiredParameters": ["query", "outputPath"],
        "steps": [
            {
                "capability": "retrieve_context",
                "description": "Bağlamı topla",
                "argsFromPayload": {
                    "query": "query",
                    "sources": "sources",
                    "limit": "limit",
                    "conversationId": "conversationId",
                },
            },
            {
                "capability": "document_write",
                "description": "DOCX rapor üret",
                "argsFromPayload": {
                    "outputPath": "outputPath",
                    "title": "title",
                    "overwrite": "overwrite",
                },
                "argsFromPreviousOutput": ["sourceContext"],
            },
        ],
    },
    {
        "id": "document.docx_from_context",
        "name": "DOCX From Context",
        "description": "Bağlam veya kaynak belgeden DOCX üretir.",
        "category": "document",
        "adapter": "document_write",
        "libraries": ["python-docx"],
        "requiresConfirmation": True,
        "parameters": ["prompt", "outputPath", "title", "sourcePath", "sourceContext", "overwrite"],
        "steps": [
            {
                "capability": "document_write",
                "description": "DOCX üret",
                "argsFromPayload": {
                    "prompt": "prompt",
                    "outputPath": "outputPath",
                    "title": "title",
                    "sourcePath": "sourcePath",
                    "sourceContext": "sourceContext",
                    "overwrite": "overwrite",
                },
            }
        ],
    },
    {
        "id": "document.xlsx_from_rows",
        "name": "XLSX From Rows",
        "description": "Satırlardan XLSX üretir.",
        "category": "document",
        "adapter": "spreadsheet_write",
        "libraries": ["openpyxl"],
        "requiresConfirmation": True,
        "parameters": ["prompt", "outputPath", "title", "columns", "rows", "sourceContext", "overwrite"],
        "steps": [
            {
                "capability": "spreadsheet_write",
                "description": "XLSX üret",
                "argsFromPayload": {
                    "prompt": "prompt",
                    "outputPath": "outputPath",
                    "title": "title",
                    "columns": "columns",
                    "rows": "rows",
                    "sourceContext": "sourceContext",
                    "overwrite": "overwrite",
                },
            }
        ],
    },
    {
        "id": "document.presentation_from_context",
        "name": "Presentation From Context",
        "description": "Bağlamdan hızlı bir sunum üretir.",
        "category": "document",
        "adapter": "presentation_write",
        "libraries": ["python-pptx"],
        "requiresConfirmation": True,
        "parameters": ["prompt", "outputPath", "title", "slides", "sourceContext", "overwrite"],
        "steps": [
            {
                "capability": "presentation_write",
                "description": "PPTX üret",
                "argsFromPayload": {
                    "prompt": "prompt",
                    "outputPath": "outputPath",
                    "title": "title",
                    "slides": "slides",
                    "sourceContext": "sourceContext",
                    "overwrite": "overwrite",
                },
            }
        ],
    },
    {
        "id": "canvas.write",
        "name": "Canvas Write",
        "description": "Metin, tablo, grafik ve görselleri tek bir PDF veya PNG canvas çıktısında birleştirir.",
        "category": "document",
        "adapter": "canvas_write",
        "libraries": ["reportlab", "Pillow"],
        "requiresConfirmation": True,
        "parameters": [
            "prompt",
            "outputPath",
            "title",
            "blocks",
            "sections",
            "outputFormat",
            "width",
            "height",
            "sourceContext",
            "sourcePath",
            "overwrite",
        ],
        "steps": [
            {
                "capability": "canvas_write",
                "description": "Canvas üret",
                "argsFromPayload": {
                    "prompt": "prompt",
                    "outputPath": "outputPath",
                    "title": "title",
                    "blocks": "blocks",
                    "sections": "sections",
                    "outputFormat": "outputFormat",
                    "width": "width",
                    "height": "height",
                    "sourceContext": "sourceContext",
                    "sourcePath": "sourcePath",
                    "overwrite": "overwrite",
                },
            }
        ],
    },
    {
        "id": "data.analyze",
        "name": "Data Analyze",
        "description": "CSV veya JSON veriyi profil/özet olarak analiz eder.",
        "category": "analysis",
        "adapter": "data_analyze",
        "libraries": ["pandas"],
        "parameters": ["path", "mode", "columns"],
        "requiredParameters": ["path"],
        "steps": [
            {
                "capability": "data_analyze",
                "description": "Veri analizi",
                "argsFromPayload": {
                    "path": "path",
                    "mode": "mode",
                    "columns": "columns",
                },
            }
        ],
    },
    {
        "id": "chart.generate",
        "name": "Chart Generate",
        "description": "Veri kümesinden hızlı bir grafik oluşturur.",
        "category": "analysis",
        "adapter": "chart_generate",
        "libraries": ["pandas", "matplotlib"],
        "requiresConfirmation": True,
        "parameters": ["path", "chartType", "xColumn", "yColumn", "title"],
        "requiredParameters": ["path"],
        "steps": [
            {
                "capability": "chart_generate",
                "description": "Grafik üret",
                "argsFromPayload": {
                    "path": "path",
                    "chartType": "chartType",
                    "xColumn": "xColumn",
                    "yColumn": "yColumn",
                    "title": "title",
                },
            }
        ],
    },
    {
        "id": "math.solve",
        "name": "Math Solve",
        "description": "Denklem ve ifadeleri çözer, sadeleştirir.",
        "category": "math",
        "adapter": "math_solve",
        "libraries": ["sympy"],
        "parameters": ["expression", "mode"],
        "requiredParameters": ["expression"],
        "steps": [
            {
                "capability": "math_solve",
                "description": "Matematik çözümü",
                "argsFromPayload": {
                    "expression": "expression",
                    "mode": "mode",
                },
            }
        ],
    },
    {
        "id": "latex.parse",
        "name": "LaTeX Parse",
        "description": "LaTeX ifadesini sembolik forma dönüştürür.",
        "category": "math",
        "adapter": "latex_parse",
        "libraries": ["latex2sympy2_extended", "sympy"],
        "parameters": ["expression", "mode"],
        "requiredParameters": ["expression"],
        "steps": [
            {
                "capability": "latex_parse",
                "description": "LaTeX parse",
                "argsFromPayload": {
                    "expression": "expression",
                    "mode": "mode",
                },
            }
        ],
    },
    {
        "id": "ocr.read",
        "name": "OCR Read",
        "description": "Görsel veya PDF içinden metin okur.",
        "category": "vision",
        "adapter": "ocr_read",
        "libraries": ["easyocr", "tesseract", "pymupdf"],
        "parameters": ["path", "mode", "languageHint"],
        "requiredParameters": ["path"],
        "steps": [
            {
                "capability": "ocr_read",
                "description": "OCR",
                "argsFromPayload": {
                    "path": "path",
                    "mode": "mode",
                    "languageHint": "languageHint",
                },
            }
        ],
    },
    {
        "id": "image.generate",
        "name": "Image Generate",
        "description": "Gemini Interactions API ile yüksek kaliteli görsel üretir.",
        "category": "image",
        "adapter": "image_generate",
        "libraries": ["google-genai", "Pillow"],
        "requiresConfirmation": True,
        "parameters": ["prompt", "outputPath", "title", "aspectRatio", "imageSize"],
        "requiredParameters": ["prompt", "outputPath"],
        "steps": [
            {
                "capability": "image_generate",
                "description": "Görsel üret",
                "argsFromPayload": {
                    "prompt": "prompt",
                    "outputPath": "outputPath",
                    "title": "title",
                    "aspectRatio": "aspectRatio",
                    "imageSize": "imageSize",
                },
            }
        ],
    },
    {
        "id": "image.edit",
        "name": "Image Edit",
        "description": "Seçili görseli Gemini ile düzenler ve yeni dosya üretir.",
        "category": "image",
        "adapter": "image_edit",
        "libraries": ["google-genai", "Pillow"],
        "requiresConfirmation": True,
        "parameters": ["prompt", "sourcePath", "sourcePaths", "outputPath", "title", "aspectRatio", "imageSize"],
        "requiredParameters": ["prompt", "sourcePath", "outputPath"],
        "steps": [{
            "capability": "image_edit",
            "description": "Görsel düzenle",
            "argsFromPayload": {
                "prompt": "prompt", "sourcePath": "sourcePath", "sourcePaths": "sourcePaths",
                "outputPath": "outputPath", "title": "title", "aspectRatio": "aspectRatio", "imageSize": "imageSize",
            },
        }],
    },
    {
        "id": "browser.search",
        "name": "Browser Search",
        "description": "Tarayıcıda güvenli web araması açar.",
        "category": "browser",
        "adapter": "browser_control",
        "libraries": ["requests"],
        "requiresConfirmation": True,
        "parameters": ["query"],
        "requiredParameters": ["query"],
        "steps": [
            {
                "capability": "browser_control",
                "description": "Tarayıcı araması",
                "args": {"action": "search"},
                "argsFromPayload": {"query": "query"},
            }
        ],
    },
    {
        "id": "browser.open",
        "name": "Browser Open",
        "description": "Belirli bir URL'yi güvenli şekilde açar.",
        "category": "browser",
        "adapter": "browser_control",
        "libraries": ["requests"],
        "requiresConfirmation": True,
        "parameters": ["url"],
        "requiredParameters": ["url"],
        "steps": [
            {
                "capability": "browser_control",
                "description": "URL aç",
                "args": {"action": "open_url"},
                "argsFromPayload": {"url": "url"},
            }
        ],
    },
    {
        "id": "desktop.operator.run",
        "name": "Desktop Operator",
        "description": "Observe -> locate -> execute -> verify döngüsüyle görev tabanlı masaüstü akışı çalıştırır.",
        "category": "operator",
        "adapter": "desktop_operator.run",
        "libraries": ["pyautogui", "pynput", "mss", "psutil", "watchdog"],
        "requiresConfirmation": True,
        "parameters": ["goal", "action", "targetText", "elementType", "text", "appName", "steps"],
        "steps": [
            {
                "capability": "desktop_operator.run",
                "description": "Masaüstü operasyonu",
                "argsFromPayload": {
                    "goal": "goal",
                    "action": "action",
                    "targetText": "targetText",
                    "elementType": "elementType",
                    "text": "text",
                    "appName": "appName",
                    "steps": "steps",
                },
            }
        ],
    },
    {
        "id": "research.present",
        "name": "Research and Present",
        "description": "Konuyu web üzerinde araştırır ve bulguları bir sunuma (PPTX) dönüştürür.",
        "category": "research",
        "adapter": "presentation_write",
        "libraries": ["httpx", "trafilatura", "playwright", "python-pptx"],
        "requiresConfirmation": True,
        "parameters": ["query", "outputPath", "title", "maxResults", "languageHint", "overwrite"],
        "requiredParameters": ["query", "outputPath"],
        "selectionPriority": 94,
        "steps": [
            {
                "capability": "web_research",
                "description": "Konuyu araştır",
                "argsFromPayload": {
                    "query": "query",
                    "max_results": "maxResults",
                    "language_hint": "languageHint",
                },
            },
            {
                "capability": "presentation_write",
                "description": "Bulguları sunuma dönüştür",
                "args": {"overwrite": False},
                "argsFromPayload": {
                    "outputPath": "outputPath",
                    "title": "title",
                    "overwrite": "overwrite",
                },
                "argsFromPreviousOutput": ["sourceContext"],
            },
        ],
    },
    {
        "id": "research.report",
        "name": "Research and Report",
        "description": "Konuyu web üzerinde araştırır ve kaynaklı bir DOCX rapor olarak belgeler.",
        "category": "research",
        "adapter": "document_write",
        "libraries": ["httpx", "trafilatura", "playwright", "python-docx"],
        "requiresConfirmation": True,
        "parameters": ["query", "outputPath", "title", "maxResults", "languageHint", "overwrite"],
        "requiredParameters": ["query", "outputPath"],
        "selectionPriority": 94,
        "steps": [
            {
                "capability": "web_research",
                "description": "Konuyu araştır",
                "argsFromPayload": {
                    "query": "query",
                    "max_results": "maxResults",
                    "language_hint": "languageHint",
                },
            },
            {
                "capability": "document_write",
                "description": "Araştırmayı rapora dönüştür",
                "args": {"overwrite": False},
                "argsFromPayload": {
                    "outputPath": "outputPath",
                    "title": "title",
                    "overwrite": "overwrite",
                },
                "argsFromPreviousOutput": ["sourceContext"],
            },
        ],
    },
    {
        "id": "data.analyze_and_chart",
        "name": "Analyze and Chart",
        "description": "Veri dosyasını analiz eder ve ardından grafiğini çizer.",
        "category": "analysis",
        "adapter": "chart_generate",
        "libraries": ["pandas", "matplotlib"],
        "requiresConfirmation": True,
        "parameters": ["path", "mode", "columns", "chartType", "xColumn", "yColumn", "title"],
        "requiredParameters": ["path"],
        "selectionPriority": 90,
        "steps": [
            {
                "capability": "data_analyze",
                "description": "Veriyi analiz et",
                "argsFromPayload": {
                    "path": "path",
                    "mode": "mode",
                    "columns": "columns",
                },
            },
            {
                "capability": "chart_generate",
                "description": "Grafiğini çiz",
                "argsFromPayload": {
                    "path": "path",
                    "chartType": "chartType",
                    "xColumn": "xColumn",
                    "yColumn": "yColumn",
                    "title": "title",
                },
            },
        ],
    },
    {
        "id": "screen.explain",
        "name": "Screen Explain",
        "description": "Ekranda ne olduğunu gözlemler ve açıklar; öğe ve hedef önerileri çıkarır.",
        "category": "operator",
        "adapter": "desktop_operator.observe_screen",
        "libraries": ["mss", "pyobjc", "psutil"],
        "parameters": ["query", "target"],
        "steps": [
            {
                "capability": "desktop_operator.observe_screen",
                "description": "Ekranı gözlemle ve açıkla",
                "argsFromPayload": {
                    "query": "query",
                    "target": "target",
                },
            }
        ],
    },
    {
        "id": "image.describe",
        "name": "Image Describe",
        "description": "Bir görseli açıklar veya özetler.",
        "category": "vision",
        "adapter": "image_read",
        "libraries": ["Pillow"],
        "parameters": ["path", "mode"],
        "requiredParameters": ["path"],
        "steps": [
            {
                "capability": "image_read",
                "description": "Görseli açıkla",
                "args": {"mode": "summary"},
                "argsFromPayload": {
                    "path": "path",
                    "mode": "mode",
                },
            }
        ],
    },
    {
        "id": "mcp.readonly_tool_proxy",
        "name": "MCP Readonly Proxy",
        "description": "Read-only MCP aracini preset olarak cagirir.",
        "category": "mcp",
        "adapter": "mcp_call_tool",
        "libraries": ["mcp"],
        "parameters": ["serverId", "toolName", "arguments"],
        "requiredParameters": ["serverId", "toolName"],
        "steps": [
            {
                "capability": "mcp_call_tool",
                "description": "Read-only MCP araci",
                "argsFromPayload": {
                    "serverId": "serverId",
                    "toolName": "toolName",
                    "arguments": "arguments",
                },
                "requiresReadOnlyMcp": True,
            }
        ],
    },
]


def builtin_skill_manifests() -> list[dict[str, Any]]:
    return [_skill(defn) for defn in BUILTIN_SKILL_DEFINITIONS]
