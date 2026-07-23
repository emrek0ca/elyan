// ÜRETİLEN DOSYA — ELLE DÜZENLEME.
// Kaynak: elyan-desktop runtime/skill_catalog.builtin_skill_manifests().
// Yeniden üretim: venv/bin/python scripts/export_capability_manifest.py <capability.ts> <bu dosya>
// Sunucu-materyalize planlayıcı skill kataloğunu yalnız planlama kelime
// dağarcığı olarak kullanır. Skill yürütme desktop'ta run_skill capability'si
// üzerinden, desktop güvenlik/onay sınırları korunarak yapılır.

export type DesktopSkillManifestEntry = {
  id: string;
  name: string;
  description: string;
  category: string;
  adapter: string;
  parameters: string[];
  requiredParameters: string[];
  expectedInputs: string[];
  intentTags: string[];
  stepCapabilities: string[];
  stepCount: number;
  latencyClass: string;
  selectionPriority: number;
  requiresConfirmation: boolean;
};

export const DESKTOP_SKILL_MANIFEST: DesktopSkillManifestEntry[] = [
  {
    "id": "math.solve",
    "name": "Math Solve",
    "description": "Denklem ve ifadeleri çözer, sadeleştirir.",
    "category": "math",
    "adapter": "math_solve",
    "parameters": [
      "expression",
      "mode"
    ],
    "requiredParameters": [
      "expression"
    ],
    "expectedInputs": [
      "expression",
      "mode"
    ],
    "intentTags": [
      "cozer",
      "denklem",
      "ifadeleri",
      "math",
      "sadelestirir",
      "solve",
      "sympy"
    ],
    "stepCapabilities": [
      "math_solve"
    ],
    "stepCount": 1,
    "latencyClass": "quick",
    "selectionPriority": 99,
    "requiresConfirmation": false
  },
  {
    "id": "document.summary_and_save",
    "name": "Document Summary and Save",
    "description": "Belgeyi veya paylaşılan metni özetler ve masaüstüne DOCX olarak kaydeder.",
    "category": "document",
    "adapter": "document_write",
    "parameters": [
      "path",
      "text",
      "selectedPaths",
      "outputPath",
      "title",
      "overwrite"
    ],
    "requiredParameters": [
      "outputPath"
    ],
    "expectedInputs": [
      "outputPath",
      "path",
      "text",
      "selectedPaths",
      "title",
      "overwrite"
    ],
    "intentTags": [
      "belgeyi",
      "document",
      "docx",
      "kaydeder",
      "mammoth",
      "markitdown",
      "masaustune",
      "metni",
      "ozetler",
      "paylaslan",
      "pymupdf",
      "pypdf",
      "python",
      "save",
      "summary",
      "veya",
      "write"
    ],
    "stepCapabilities": [
      "document_read",
      "document_write"
    ],
    "stepCount": 2,
    "latencyClass": "slow",
    "selectionPriority": 96,
    "requiresConfirmation": true
  },
  {
    "id": "latex.parse",
    "name": "LaTeX Parse",
    "description": "LaTeX ifadesini sembolik forma dönüştürür.",
    "category": "math",
    "adapter": "latex_parse",
    "parameters": [
      "expression",
      "mode"
    ],
    "requiredParameters": [
      "expression"
    ],
    "expectedInputs": [
      "expression",
      "mode"
    ],
    "intentTags": [
      "donusturur",
      "extended",
      "forma",
      "ifadesini",
      "latex",
      "latex2sympy2",
      "math",
      "parse",
      "sembolik",
      "sympy"
    ],
    "stepCapabilities": [
      "latex_parse"
    ],
    "stepCount": 1,
    "latencyClass": "quick",
    "selectionPriority": 95,
    "requiresConfirmation": false
  },
  {
    "id": "research.present",
    "name": "Research and Present",
    "description": "Konuyu web üzerinde araştırır ve bulguları bir sunuma (PPTX) dönüştürür.",
    "category": "research",
    "adapter": "presentation_write",
    "parameters": [
      "query",
      "outputPath",
      "title",
      "maxResults",
      "languageHint",
      "overwrite"
    ],
    "requiredParameters": [
      "query",
      "outputPath"
    ],
    "expectedInputs": [
      "query",
      "outputPath",
      "title",
      "maxResults",
      "languageHint",
      "overwrite"
    ],
    "intentTags": [
      "arastrr",
      "bulgular",
      "donusturur",
      "httpx",
      "konuyu",
      "playwright",
      "pptx",
      "present",
      "presentation",
      "python",
      "research",
      "sunuma",
      "trafilatura",
      "uzerinde",
      "web",
      "write"
    ],
    "stepCapabilities": [
      "web_research",
      "presentation_write"
    ],
    "stepCount": 2,
    "latencyClass": "slow",
    "selectionPriority": 94,
    "requiresConfirmation": true
  },
  {
    "id": "research.report",
    "name": "Research and Report",
    "description": "Konuyu web üzerinde araştırır ve kaynaklı bir DOCX rapor olarak belgeler.",
    "category": "research",
    "adapter": "document_write",
    "parameters": [
      "query",
      "outputPath",
      "title",
      "maxResults",
      "languageHint",
      "overwrite"
    ],
    "requiredParameters": [
      "query",
      "outputPath"
    ],
    "expectedInputs": [
      "query",
      "outputPath",
      "title",
      "maxResults",
      "languageHint",
      "overwrite"
    ],
    "intentTags": [
      "arastrr",
      "belgeler",
      "document",
      "docx",
      "httpx",
      "kaynakl",
      "konuyu",
      "playwright",
      "python",
      "rapor",
      "report",
      "research",
      "trafilatura",
      "uzerinde",
      "web",
      "write"
    ],
    "stepCapabilities": [
      "web_research",
      "document_write"
    ],
    "stepCount": 2,
    "latencyClass": "slow",
    "selectionPriority": 94,
    "requiresConfirmation": true
  },
  {
    "id": "document.bullets",
    "name": "Document Bullets",
    "description": "Belgeyi maddeler halinde çıkarır.",
    "category": "document",
    "adapter": "document_read",
    "parameters": [
      "path"
    ],
    "requiredParameters": [
      "path"
    ],
    "expectedInputs": [
      "path"
    ],
    "intentTags": [
      "belgeyi",
      "bullets",
      "ckarr",
      "document",
      "halinde",
      "maddeler",
      "mammoth",
      "markitdown",
      "pymupdf",
      "pypdf",
      "read"
    ],
    "stepCapabilities": [
      "document_read"
    ],
    "stepCount": 1,
    "latencyClass": "quick",
    "selectionPriority": 91,
    "requiresConfirmation": false
  },
  {
    "id": "document.summary",
    "name": "Document Summary",
    "description": "Belgeyi kısa özet olarak çıkarır.",
    "category": "document",
    "adapter": "document_read",
    "parameters": [
      "path"
    ],
    "requiredParameters": [
      "path"
    ],
    "expectedInputs": [
      "path"
    ],
    "intentTags": [
      "belgeyi",
      "ckarr",
      "document",
      "ksa",
      "mammoth",
      "markitdown",
      "ozet",
      "pymupdf",
      "pypdf",
      "read",
      "summary"
    ],
    "stepCapabilities": [
      "document_read"
    ],
    "stepCount": 1,
    "latencyClass": "quick",
    "selectionPriority": 91,
    "requiresConfirmation": false
  },
  {
    "id": "file.explain",
    "name": "File Explain",
    "description": "Belgeyi sade şekilde açıklar.",
    "category": "document",
    "adapter": "document_read",
    "parameters": [
      "path"
    ],
    "requiredParameters": [
      "path"
    ],
    "expectedInputs": [
      "path"
    ],
    "intentTags": [
      "acklar",
      "belgeyi",
      "document",
      "explain",
      "file",
      "mammoth",
      "markitdown",
      "pymupdf",
      "pypdf",
      "read",
      "sade",
      "sekilde"
    ],
    "stepCapabilities": [
      "document_read"
    ],
    "stepCount": 1,
    "latencyClass": "quick",
    "selectionPriority": 91,
    "requiresConfirmation": false
  },
  {
    "id": "data.analyze_and_chart",
    "name": "Analyze and Chart",
    "description": "Veri dosyasını analiz eder ve ardından grafiğini çizer.",
    "category": "analysis",
    "adapter": "chart_generate",
    "parameters": [
      "path",
      "mode",
      "columns",
      "chartType",
      "xColumn",
      "yColumn",
      "title"
    ],
    "requiredParameters": [
      "path"
    ],
    "expectedInputs": [
      "path",
      "mode",
      "columns",
      "chartType",
      "xColumn",
      "yColumn",
      "title"
    ],
    "intentTags": [
      "analiz",
      "analysis",
      "analyze",
      "ardndan",
      "chart",
      "cizer",
      "data",
      "dosyasn",
      "eder",
      "generate",
      "grafigini",
      "matplotlib",
      "pandas",
      "veri"
    ],
    "stepCapabilities": [
      "data_analyze",
      "chart_generate"
    ],
    "stepCount": 2,
    "latencyClass": "medium",
    "selectionPriority": 90,
    "requiresConfirmation": true
  },
  {
    "id": "research.brief",
    "name": "Research Brief",
    "description": "Yerel bağlam ve çalışma alanından kısa, kaynaklı araştırma özeti üretir.",
    "category": "research",
    "adapter": "retrieve_context",
    "parameters": [
      "query",
      "sources",
      "limit",
      "conversationId"
    ],
    "requiredParameters": [
      "query"
    ],
    "expectedInputs": [
      "query",
      "sources",
      "limit",
      "conversationId"
    ],
    "intentTags": [
      "alanndan",
      "arastrma",
      "baglam",
      "brief",
      "calsma",
      "context",
      "kaynakl",
      "ksa",
      "ozeti",
      "research",
      "retrieve",
      "sentence",
      "transformers",
      "uretir",
      "yerel"
    ],
    "stepCapabilities": [
      "retrieve_context"
    ],
    "stepCount": 1,
    "latencyClass": "medium",
    "selectionPriority": 88,
    "requiresConfirmation": false
  },
  {
    "id": "source.verify",
    "name": "Source Verify",
    "description": "Soru için kısa kaynak kontrolü yapar.",
    "category": "research",
    "adapter": "retrieve_context",
    "parameters": [
      "query",
      "sources",
      "limit",
      "conversationId"
    ],
    "requiredParameters": [
      "query"
    ],
    "expectedInputs": [
      "query",
      "sources",
      "limit",
      "conversationId"
    ],
    "intentTags": [
      "context",
      "icin",
      "kaynak",
      "kontrolu",
      "ksa",
      "research",
      "retrieve",
      "sentence",
      "soru",
      "source",
      "transformers",
      "verify",
      "yapar"
    ],
    "stepCapabilities": [
      "retrieve_context"
    ],
    "stepCount": 1,
    "latencyClass": "medium",
    "selectionPriority": 88,
    "requiresConfirmation": false
  },
  {
    "id": "workspace.answer",
    "name": "Workspace Answer",
    "description": "Çalışma alanından cevap hazırlamak için bağlam toplar.",
    "category": "research",
    "adapter": "retrieve_context",
    "parameters": [
      "query",
      "limit",
      "conversationId"
    ],
    "requiredParameters": [
      "query"
    ],
    "expectedInputs": [
      "query",
      "limit",
      "conversationId"
    ],
    "intentTags": [
      "alanndan",
      "answer",
      "baglam",
      "calsma",
      "cevap",
      "context",
      "hazrlamak",
      "icin",
      "research",
      "retrieve",
      "sentence",
      "toplar",
      "transformers",
      "workspace"
    ],
    "stepCapabilities": [
      "retrieve_context"
    ],
    "stepCount": 1,
    "latencyClass": "medium",
    "selectionPriority": 88,
    "requiresConfirmation": false
  },
  {
    "id": "browser.open",
    "name": "Browser Open",
    "description": "Belirli bir URL'yi güvenli şekilde açar.",
    "category": "browser",
    "adapter": "browser_control",
    "parameters": [
      "url"
    ],
    "requiredParameters": [
      "url"
    ],
    "expectedInputs": [
      "url"
    ],
    "intentTags": [
      "acar",
      "belirli",
      "browser",
      "control",
      "guvenli",
      "open",
      "requests",
      "sekilde",
      "url",
      "yi"
    ],
    "stepCapabilities": [
      "browser_control"
    ],
    "stepCount": 1,
    "latencyClass": "quick",
    "selectionPriority": 87,
    "requiresConfirmation": true
  },
  {
    "id": "browser.search",
    "name": "Browser Search",
    "description": "Tarayıcıda güvenli web araması açar.",
    "category": "browser",
    "adapter": "browser_control",
    "parameters": [
      "query"
    ],
    "requiredParameters": [
      "query"
    ],
    "expectedInputs": [
      "query"
    ],
    "intentTags": [
      "acar",
      "aramas",
      "browser",
      "control",
      "guvenli",
      "requests",
      "search",
      "taraycda",
      "web"
    ],
    "stepCapabilities": [
      "browser_control"
    ],
    "stepCount": 1,
    "latencyClass": "quick",
    "selectionPriority": 87,
    "requiresConfirmation": true
  },
  {
    "id": "web.research",
    "name": "Web Research",
    "description": "Public web üzerinde kaynak toplayıp kısa bir araştırma özeti üretir.",
    "category": "research",
    "adapter": "web_research",
    "parameters": [
      "query",
      "maxResults",
      "languageHint"
    ],
    "requiredParameters": [
      "query"
    ],
    "expectedInputs": [
      "query",
      "maxResults",
      "languageHint"
    ],
    "intentTags": [
      "arastrma",
      "httpx",
      "kaynak",
      "ksa",
      "ozeti",
      "playwright",
      "public",
      "research",
      "toplayp",
      "trafilatura",
      "uretir",
      "uzerinde",
      "web"
    ],
    "stepCapabilities": [
      "web_research"
    ],
    "stepCount": 1,
    "latencyClass": "medium",
    "selectionPriority": 86,
    "requiresConfirmation": false
  },
  {
    "id": "web.collect_download",
    "name": "Web Collect & Download",
    "description": "Bir web sayfasından link listesi toplar ve her birini belirtilen klasöre indirir.",
    "category": "browser",
    "adapter": "browser_agent.run",
    "parameters": [
      "goal",
      "outputDir"
    ],
    "requiredParameters": [
      "goal",
      "outputDir"
    ],
    "expectedInputs": [
      "goal",
      "outputDir"
    ],
    "intentTags": [
      "agent",
      "belirtilen",
      "birini",
      "browser",
      "collect",
      "download",
      "her",
      "indir",
      "indirir",
      "klasore",
      "link",
      "linkler",
      "listesi",
      "playwright",
      "run",
      "sayfasndan",
      "topla",
      "toplar"
    ],
    "stepCapabilities": [
      "make_directory",
      "browser_agent.run",
      "browser_session.download"
    ],
    "stepCount": 3,
    "latencyClass": "quick",
    "selectionPriority": 83,
    "requiresConfirmation": true
  },
  {
    "id": "data.analyze",
    "name": "Data Analyze",
    "description": "CSV veya JSON veriyi profil/özet olarak analiz eder.",
    "category": "analysis",
    "adapter": "data_analyze",
    "parameters": [
      "path",
      "mode",
      "columns"
    ],
    "requiredParameters": [
      "path"
    ],
    "expectedInputs": [
      "path",
      "mode",
      "columns"
    ],
    "intentTags": [
      "analiz",
      "analysis",
      "analyze",
      "csv",
      "data",
      "eder",
      "json",
      "ozet",
      "pandas",
      "profil",
      "veriyi",
      "veya"
    ],
    "stepCapabilities": [
      "data_analyze"
    ],
    "stepCount": 1,
    "latencyClass": "medium",
    "selectionPriority": 82,
    "requiresConfirmation": false
  },
  {
    "id": "ocr.read",
    "name": "OCR Read",
    "description": "Görsel veya PDF içinden metin okur.",
    "category": "vision",
    "adapter": "ocr_read",
    "parameters": [
      "path",
      "mode",
      "languageHint"
    ],
    "requiredParameters": [
      "path"
    ],
    "expectedInputs": [
      "path",
      "mode",
      "languageHint"
    ],
    "intentTags": [
      "easyocr",
      "gorsel",
      "icinden",
      "metin",
      "ocr",
      "okur",
      "pdf",
      "pymupdf",
      "read",
      "tesseract",
      "veya",
      "vision"
    ],
    "stepCapabilities": [
      "ocr_read"
    ],
    "stepCount": 1,
    "latencyClass": "medium",
    "selectionPriority": 80,
    "requiresConfirmation": false
  },
  {
    "id": "canvas.write",
    "name": "Canvas Write",
    "description": "Metin, tablo, grafik ve görselleri tek bir PDF veya PNG canvas çıktısında birleştirir.",
    "category": "document",
    "adapter": "canvas_write",
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
      "overwrite"
    ],
    "requiredParameters": [],
    "expectedInputs": [
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
      "overwrite"
    ],
    "intentTags": [
      "birlestirir",
      "canvas",
      "cktsnda",
      "document",
      "gorselleri",
      "grafik",
      "metin",
      "pdf",
      "pillow",
      "png",
      "reportlab",
      "tablo",
      "tek",
      "veya",
      "write"
    ],
    "stepCapabilities": [
      "canvas_write"
    ],
    "stepCount": 1,
    "latencyClass": "slow",
    "selectionPriority": 78,
    "requiresConfirmation": true
  },
  {
    "id": "document.docx_from_context",
    "name": "DOCX From Context",
    "description": "Bağlam veya kaynak belgeden DOCX üretir.",
    "category": "document",
    "adapter": "document_write",
    "parameters": [
      "prompt",
      "outputPath",
      "title",
      "sourcePath",
      "sourceContext",
      "overwrite"
    ],
    "requiredParameters": [],
    "expectedInputs": [
      "prompt",
      "outputPath",
      "title",
      "sourcePath",
      "sourceContext",
      "overwrite"
    ],
    "intentTags": [
      "baglam",
      "belgeden",
      "context",
      "document",
      "docx",
      "kaynak",
      "python",
      "uretir",
      "veya",
      "write"
    ],
    "stepCapabilities": [
      "document_write"
    ],
    "stepCount": 1,
    "latencyClass": "slow",
    "selectionPriority": 78,
    "requiresConfirmation": true
  },
  {
    "id": "document.presentation_from_context",
    "name": "Presentation From Context",
    "description": "Bağlamdan hızlı bir sunum üretir.",
    "category": "document",
    "adapter": "presentation_write",
    "parameters": [
      "prompt",
      "outputPath",
      "title",
      "slides",
      "sourceContext",
      "overwrite"
    ],
    "requiredParameters": [],
    "expectedInputs": [
      "prompt",
      "outputPath",
      "title",
      "slides",
      "sourceContext",
      "overwrite"
    ],
    "intentTags": [
      "baglamdan",
      "context",
      "document",
      "hzl",
      "pptx",
      "presentation",
      "python",
      "sunum",
      "uretir",
      "write"
    ],
    "stepCapabilities": [
      "presentation_write"
    ],
    "stepCount": 1,
    "latencyClass": "slow",
    "selectionPriority": 78,
    "requiresConfirmation": true
  },
  {
    "id": "document.report_from_context",
    "name": "Context Report",
    "description": "Bağlamı toplayıp DOCX rapora dönüştürür.",
    "category": "document",
    "adapter": "document_write",
    "parameters": [
      "query",
      "outputPath",
      "title",
      "sources",
      "limit",
      "conversationId",
      "overwrite"
    ],
    "requiredParameters": [
      "query",
      "outputPath"
    ],
    "expectedInputs": [
      "query",
      "outputPath",
      "title",
      "sources",
      "limit",
      "conversationId",
      "overwrite"
    ],
    "intentTags": [
      "baglam",
      "context",
      "document",
      "docx",
      "donusturur",
      "python",
      "rapora",
      "report",
      "sentence",
      "toplayp",
      "transformers",
      "write"
    ],
    "stepCapabilities": [
      "retrieve_context",
      "document_write"
    ],
    "stepCount": 2,
    "latencyClass": "slow",
    "selectionPriority": 78,
    "requiresConfirmation": true
  },
  {
    "id": "document.xlsx_from_rows",
    "name": "XLSX From Rows",
    "description": "Satırlardan XLSX üretir.",
    "category": "document",
    "adapter": "spreadsheet_write",
    "parameters": [
      "prompt",
      "outputPath",
      "title",
      "columns",
      "rows",
      "sourceContext",
      "overwrite"
    ],
    "requiredParameters": [],
    "expectedInputs": [
      "prompt",
      "outputPath",
      "title",
      "columns",
      "rows",
      "sourceContext",
      "overwrite"
    ],
    "intentTags": [
      "document",
      "openpyxl",
      "rows",
      "satrlardan",
      "spreadsheet",
      "uretir",
      "write",
      "xlsx"
    ],
    "stepCapabilities": [
      "spreadsheet_write"
    ],
    "stepCount": 1,
    "latencyClass": "slow",
    "selectionPriority": 78,
    "requiresConfirmation": true
  },
  {
    "id": "image.describe",
    "name": "Image Describe",
    "description": "Bir görseli açıklar veya özetler.",
    "category": "vision",
    "adapter": "image_read",
    "parameters": [
      "path",
      "mode"
    ],
    "requiredParameters": [
      "path"
    ],
    "expectedInputs": [
      "path",
      "mode"
    ],
    "intentTags": [
      "acklar",
      "describe",
      "gorseli",
      "image",
      "ozetler",
      "pillow",
      "read",
      "veya",
      "vision"
    ],
    "stepCapabilities": [
      "image_read"
    ],
    "stepCount": 1,
    "latencyClass": "medium",
    "selectionPriority": 78,
    "requiresConfirmation": false
  },
  {
    "id": "chart.generate",
    "name": "Chart Generate",
    "description": "Veri kümesinden hızlı bir grafik oluşturur.",
    "category": "analysis",
    "adapter": "chart_generate",
    "parameters": [
      "path",
      "chartType",
      "xColumn",
      "yColumn",
      "title"
    ],
    "requiredParameters": [
      "path"
    ],
    "expectedInputs": [
      "path",
      "chartType",
      "xColumn",
      "yColumn",
      "title"
    ],
    "intentTags": [
      "analysis",
      "chart",
      "generate",
      "grafik",
      "hzl",
      "kumesinden",
      "matplotlib",
      "olusturur",
      "pandas",
      "veri"
    ],
    "stepCapabilities": [
      "chart_generate"
    ],
    "stepCount": 1,
    "latencyClass": "medium",
    "selectionPriority": 74,
    "requiresConfirmation": true
  },
  {
    "id": "screen.explain",
    "name": "Screen Explain",
    "description": "Ekranda ne olduğunu gözlemler ve açıklar; öğe ve hedef önerileri çıkarır.",
    "category": "operator",
    "adapter": "desktop_operator.observe_screen",
    "parameters": [
      "query",
      "target"
    ],
    "requiredParameters": [],
    "expectedInputs": [
      "query",
      "target"
    ],
    "intentTags": [
      "acklar",
      "ckarr",
      "desktop",
      "ekranda",
      "explain",
      "gozlemler",
      "hedef",
      "mss",
      "ne",
      "observe",
      "oge",
      "oldugunu",
      "onerileri",
      "operator",
      "psutil",
      "pyobjc",
      "screen"
    ],
    "stepCapabilities": [
      "desktop_operator.observe_screen"
    ],
    "stepCount": 1,
    "latencyClass": "quick",
    "selectionPriority": 63,
    "requiresConfirmation": false
  },
  {
    "id": "image.edit",
    "name": "Image Edit",
    "description": "Seçili görseli Gemini ile düzenler ve yeni dosya üretir.",
    "category": "image",
    "adapter": "image_edit",
    "parameters": [
      "prompt",
      "sourcePath",
      "sourcePaths",
      "outputPath",
      "title",
      "aspectRatio",
      "imageSize"
    ],
    "requiredParameters": [
      "prompt",
      "sourcePath",
      "outputPath"
    ],
    "expectedInputs": [
      "prompt",
      "sourcePath",
      "outputPath",
      "sourcePaths",
      "title",
      "aspectRatio",
      "imageSize"
    ],
    "intentTags": [
      "dosya",
      "duzenler",
      "edit",
      "gemini",
      "genai",
      "google",
      "gorseli",
      "image",
      "pillow",
      "secili",
      "uretir"
    ],
    "stepCapabilities": [
      "image_edit"
    ],
    "stepCount": 1,
    "latencyClass": "slow",
    "selectionPriority": 62,
    "requiresConfirmation": true
  },
  {
    "id": "image.generate",
    "name": "Image Generate",
    "description": "Gemini Interactions API ile yüksek kaliteli görsel üretir.",
    "category": "image",
    "adapter": "image_generate",
    "parameters": [
      "prompt",
      "outputPath",
      "title",
      "aspectRatio",
      "imageSize"
    ],
    "requiredParameters": [
      "prompt",
      "outputPath"
    ],
    "expectedInputs": [
      "prompt",
      "outputPath",
      "title",
      "aspectRatio",
      "imageSize"
    ],
    "intentTags": [
      "api",
      "gemini",
      "genai",
      "generate",
      "google",
      "gorsel",
      "image",
      "interactions",
      "kaliteli",
      "pillow",
      "uretir",
      "yuksek"
    ],
    "stepCapabilities": [
      "image_generate"
    ],
    "stepCount": 1,
    "latencyClass": "slow",
    "selectionPriority": 62,
    "requiresConfirmation": true
  },
  {
    "id": "mcp.readonly_tool_proxy",
    "name": "MCP Readonly Proxy",
    "description": "Read-only MCP aracini preset olarak cagirir.",
    "category": "mcp",
    "adapter": "mcp_call_tool",
    "parameters": [
      "serverId",
      "toolName",
      "arguments"
    ],
    "requiredParameters": [
      "serverId",
      "toolName"
    ],
    "expectedInputs": [
      "serverId",
      "toolName",
      "arguments"
    ],
    "intentTags": [
      "aracini",
      "cagirir",
      "call",
      "mcp",
      "only",
      "preset",
      "proxy",
      "read",
      "readonly",
      "tool"
    ],
    "stepCapabilities": [
      "mcp_call_tool"
    ],
    "stepCount": 1,
    "latencyClass": "medium",
    "selectionPriority": 60,
    "requiresConfirmation": false
  },
  {
    "id": "desktop.operator.run",
    "name": "Desktop Operator",
    "description": "Observe -> locate -> execute -> verify döngüsüyle görev tabanlı masaüstü akışı çalıştırır.",
    "category": "operator",
    "adapter": "desktop_operator.run",
    "parameters": [
      "goal",
      "action",
      "targetText",
      "elementType",
      "text",
      "appName",
      "steps"
    ],
    "requiredParameters": [],
    "expectedInputs": [
      "goal",
      "action",
      "targetText",
      "elementType",
      "text",
      "appName",
      "steps"
    ],
    "intentTags": [
      "aks",
      "calstrr",
      "desktop",
      "dongusuyle",
      "execute",
      "gorev",
      "locate",
      "masaustu",
      "mss",
      "observe",
      "operator",
      "psutil",
      "pyautogui",
      "pynput",
      "run",
      "tabanl",
      "verify",
      "watchdog"
    ],
    "stepCapabilities": [
      "desktop_operator.run"
    ],
    "stepCount": 1,
    "latencyClass": "slow",
    "selectionPriority": 54,
    "requiresConfirmation": true
  }
];
