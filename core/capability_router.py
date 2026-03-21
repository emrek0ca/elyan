"""
Capability Router
High-level intent domain detection for professional assistant workflows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re


@dataclass
class CapabilityPlan:
    domain: str
    confidence: float
    objective: str
    workflow_id: str
    primary_action: str
    preferred_tools: list[str]
    output_artifacts: list[str]
    quality_checklist: list[str]
    learning_tags: list[str]
    complexity_tier: str = "low"
    suggested_job_type: str = "communication"
    multi_agent_recommended: bool = False
    orchestration_mode: str = "single_agent"
    workflow_profile_applicable: bool = False
    requires_design_phase: bool = False
    requires_worktree: bool = False
    content_kind: str = "task"
    output_formats: list[str] = field(default_factory=list)
    style_profile: str = "executive"
    source_policy: str = "trusted"
    quality_contract: list[str] = field(default_factory=list)
    memory_scope: str = "task_routed"
    preview: str = ""
    request_contract: dict[str, Any] = field(default_factory=dict)


@dataclass
class RequestContract:
    domain: str
    objective: str
    route_mode: str
    content_kind: str
    confidence: float = 0.0
    output_formats: list[str] = field(default_factory=list)
    output_artifacts: list[str] = field(default_factory=list)
    style_profile: str = "executive"
    source_policy: str = "trusted"
    quality_contract: list[str] = field(default_factory=list)
    memory_scope: str = "task_routed"
    evidence_required: bool = True
    needs_clarification: bool = False
    clarifying_question: str = ""
    preview: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "objective": self.objective,
            "route_mode": self.route_mode,
            "content_kind": self.content_kind,
            "confidence": self.confidence,
            "output_formats": list(self.output_formats or []),
            "output_artifacts": list(self.output_artifacts or []),
            "style_profile": self.style_profile,
            "source_policy": self.source_policy,
            "quality_contract": list(self.quality_contract or []),
            "memory_scope": self.memory_scope,
            "evidence_required": self.evidence_required,
            "needs_clarification": self.needs_clarification,
            "clarifying_question": self.clarifying_question,
            "preview": self.preview,
            "metadata": dict(self.metadata or {}),
        }


class CapabilityRouter:
    """Detect major capability domain and provide execution hints."""

    @staticmethod
    def _keyword_in_text(text: str, keyword: str) -> bool:
        hay = str(text or "").lower()
        needle = str(keyword or "").lower().strip()
        if not hay or not needle:
            return False
        if re.fullmatch(r"[a-z0-9_.:+#-]+", needle):
            pattern = rf"(?<![a-z0-9_]){re.escape(needle)}(?![a-z0-9_])"
            return re.search(pattern, hay) is not None
        return needle in hay

    @staticmethod
    def _is_app_control_command(text: str) -> bool:
        low = str(text or "").lower().strip()
        if not low:
            return False
        # Avoid stealing true coding intents that include app-like words.
        if any(k in low for k in ("python", "react", "kod", "code", "script", "hata", "debug", "refactor", "api", "endpoint")):
            return False
        has_control = bool(
            re.search(
                r"\b(aç|ac|kapat|close|quit|başlat|baslat|çalıştır|calistir|sonlandır|sonlandir|durdur|open|launch)\b",
                low,
            )
        )
        if not has_control:
            return False
        app_markers = (
            "whatsapp", "telegram", "safari", "chrome", "krom", "finder", "terminal", "discord",
            "slack", "spotify", "mail", "notlar", "notes", "vscode", "visual studio code",
            "cursor", "preview", "word", "excel", "powerpoint", "teams", "zoom",
        )
        return any(marker in low for marker in app_markers)

    @staticmethod
    def _has_strong_screen_control_signal(text: str) -> bool:
        low = str(text or "").lower().strip()
        if not low:
            return False
        markers = (
            "tıkla", "tikla", "click", "yaz", "type", "gir", "seç", "sec", "kapat", "close",
            "aç", "ac", "open", "launch", "enter", "gönder", "gonder", "mouse",
            "bilgisayari kullan", "bilgisayarı kullan", "bilgisayari kontrol", "bilgisayarı kontrol",
            "uygulamayi ac", "uygulamayı aç", "app ac", "app aç",
        )
        return any(marker in low for marker in markers)

    @staticmethod
    def _has_multi_step_operator_signal(text: str) -> bool:
        low = str(text or "").lower().strip()
        if not low:
            return False
        markers = (
            "ayni anda", "aynı anda", "eszamanli", "eşzamanlı", "ve sonra", "ardindan", "ardından",
            "then", "1)", "2)", "3)", "birden fazla", "tumunu", "hepsini", "sırayla", "sirayla",
        )
        return any(marker in low for marker in markers)

    _DOMAIN_TO_JOB_TYPE: dict[str, str] = {
        "website": "web_project",
        "code": "code_project",
        "api_integration": "api_integration",
        "automation": "system_ops",
        "research": "research_report",
        "email": "communication",
        "calendar": "planning",
        "social": "communication",
        "scheduler": "automation",
        "google": "api_integration",
        "drive": "document",
        "document": "research_report",
        "summarization": "research_report",
        "screen_operator": "system_automation",
        "real_time_control": "system_automation",
        "file_ops": "file_operations",
        "multimodal": "browser_task",
        "image": "browser_task",
        "full_stack_delivery": "code_project",
        "lean": "formal_methods",
        "cloudflare_agents": "code_project",
        "general": "communication",
    }

    _DOMAIN_KEYWORDS: dict[str, list[str]] = {
        "website": [
            "website", "site", "landing page", "frontend", "ui", "ux", "html", "css",
            "react", "next.js", "tailwind", "web sayfas", "internet sitesi"
        ],
        "code": [
            "kod", "code", "bug", "debug", "refactor", "fonksiyon", "script",
            "api", "backend", "algorithm", "test yaz", "unit test",
            "oyun", "game", "prototip", "prototype", "uygulama", "app",
            "project pack", "proje paketi", "engine"
        ],
        "image": [
            "gorsel", "görsel", "image", "logo", "poster", "illustration",
            "tasarla", "design", "thumbnail", "afis", "kapak"
        ],
        "multimodal": [
            "ses", "audio", "voice", "konuş", "konus", "transcribe", "speech", "whisper",
            "mikrofon", "dinle", "duy", "görseli anlat", "gorseli anlat", "narrate", "tts",
            "stt", "video", "kamera", "görüntü analizi", "goruntu analizi"
        ],
        "research": [
            "araştır", "arastir", "research", "kaynak", "source", "literature",
            "incele", "analiz", "benchmark", "karşılaştır", "karsilastir"
        ],
        "email": [
            "mail", "email", "e-posta", "inbox", "outlook", "gmail", "smtp", "imap",
            "posta kutusu", "gelen kutu", "gelen kutusu",
        ],
        "calendar": [
            "calendar", "takvim", "event", "reminder", "hatırlat", "hatirlat",
            "meeting", "meet", "appointment", "randevu",
        ],
        "social": [
            "x.com", "twitter", "tweet", "instagram", "whatsapp", "dm", "story",
            "social media", "post at", "yayınla", "yayinla",
        ],
        "scheduler": [
            "schedule", "cron", "zamanla", "planla", "remind later", "heartbeat", "routine",
        ],
        "google": [
            "google", "gmail", "calendar", "drive", "docs", "sheets", "slides", "workspace",
        ],
        "drive": [
            "drive", "google drive", "dosya sürücü", "dosya surucu", "workspace files",
        ],
        "screen_operator": [
            "ekrana bak", "ekrani oku", "ekranı oku", "ekrandakini oku", "durum nedir",
            "ekranda ne var", "screen", "screenshot", "ss", "tıkla", "tikla", "mouse",
            "cursor", "imlec", "computer use", "bilgisayari kullan", "bilgisayarı kullan"
        ],
        "real_time_control": [
            "real time", "realtime", "canli ekran", "canlı ekran", "anlık ekran", "anlik ekran",
            "desktop control", "computer control", "ekran kontrol", "ekranı kontrol", "ekrani kontrol",
        ],
        "file_ops": [
            "dosya", "klasör", "klasor", "folder", "file", "kaydet", "yaz", "oku",
            "listele", "rename", "move", "copy", "masaüst", "masaust", "desktop"
        ],
        "document": [
            "belge", "dokuman", "doküman", "docx", "pdf", "rapor", "report",
            "proposal", "sunum", "presentation", "teklif",
            "layout", "ocr", "vision", "görsel", "gorsel", "table", "tablo",
            "chart", "grafik", "diagram", "figure", "extract", "çıkar", "cikar",
        ],
        "summarization": [
            "özet", "ozet", "summarize", "tl;dr", "kısalt", "kisalt",
            "özetle", "sentez", "synthesize"
        ],
        "api_integration": [
            "api", "endpoint", "rest", "graphql", "webhook", "json api",
            "http", "get istegi", "post istegi", "curl", "token yenileme", "integration"
        ],
        "automation": [
            "otomasyon", "automation", "workflow", "cron", "rutin", "schedule",
            "arka planda", "background", "daemon", "agent team", "multi agent"
        ],
        "lean": [
            "lean", "mathlib", "theorem", "lemma", "proof", "prove",
            "formalize", "formalisation", "formalization", "autoformalize", "autoprove",
            "lakefile", "lake", "lean-toolchain", "project-scoped formalization",
        ],
        "cloudflare_agents": [
            "cloudflare agents", "routeagentrequest", "useagent", "useagentchat",
            "durable objects", "cloudflare worker", "cloudflare workers", "wrangler",
            "new_sqlite_classes", "ai-chat", "ai chat agent", "edge runtime", "mcp",
        ],
        "full_stack_delivery": [
            "full stack", "uçtan uca", "uctan uca", "production", "deployment",
            "mimari", "architecture", "pipeline", "microservice", "dashboard"
        ],
    }

    _DOMAIN_HINTS: dict[str, dict[str, Any]] = {
        "website": {
            "objective": "build_production_ready_web_artifact",
            "workflow_id": "website_delivery_workflow",
            "primary_action": "create_web_project_scaffold",
            "preferred_tools": ["create_software_project_pack", "create_web_project_scaffold", "create_smart_file", "write_file"],
            "output_artifacts": ["project_folder", "readme", "deployment_notes"],
            "quality_checklist": ["responsive", "accessible", "performant", "maintainable"],
            "learning_tags": ["web", "ui", "frontend"],
        },
        "code": {
            "objective": "deliver_working_testable_code",
            "workflow_id": "coding_workflow",
            "primary_action": "create_coding_project",
            "preferred_tools": [
                "create_coding_project",
                "create_software_project_pack",
                "execute_python_code",
                "debug_code",
                "write_file",
                "run_safe_command",
            ],
            "output_artifacts": ["source_code", "tests", "implementation_notes"],
            "quality_checklist": ["correctness", "testability", "readability", "safety"],
            "learning_tags": ["code", "debug", "engineering"],
        },
        "image": {
            "objective": "produce_visual_asset_workflow",
            "workflow_id": "image_asset_workflow",
            "primary_action": "create_visual_asset_pack",
            "preferred_tools": ["create_image_workflow_profile", "analyze_image", "create_smart_file"],
            "output_artifacts": ["prompt_pack", "style_profile", "asset_plan"],
            "quality_checklist": ["style_consistency", "clarity", "brand_alignment"],
            "learning_tags": ["visual", "design", "creative"],
        },
        "multimodal": {
            "objective": "deliver_multimodal_input_output_pipeline",
            "workflow_id": "multimodal_workflow",
            "primary_action": "analyze_screen",
            "preferred_tools": [
                "transcribe_audio_file",
                "speak_text_local",
                "analyze_and_narrate_image",
                "create_visual_asset_pack",
                "get_multimodal_capability_report",
            ],
            "output_artifacts": ["transcript", "voice_output", "visual_pack", "analysis_notes"],
            "quality_checklist": ["clarity", "reproducibility", "correctness", "usability"],
            "learning_tags": ["voice", "vision", "multimodal"],
        },
        "research": {
            "objective": "produce_reliable_multi_source_research",
            "workflow_id": "research_workflow",
            "primary_action": "research_document_delivery",
            "preferred_tools": ["research_document_delivery", "advanced_research", "evaluate_source", "synthesize_findings"],
            "output_artifacts": ["research_document_bundle", "source_list", "recommendations"],
            "quality_checklist": ["source_quality", "coverage", "traceability", "actionability"],
            "learning_tags": ["research", "analysis", "evidence"],
        },
        "lean": {
            "objective": "orchestrate_project_scoped_lean_formalization",
            "workflow_id": "lean_formalization_workflow",
            "primary_action": "lean_workflow",
            "preferred_tools": ["lean_status", "lean_project", "lean_workflow", "lean_swarm", "run_safe_command"],
            "output_artifacts": ["lean_project_manifest", "proof_trace", "build_log"],
            "quality_checklist": ["typecheck", "traceability", "project_scope", "reproducibility"],
            "learning_tags": ["lean", "mathlib", "formal_methods"],
        },
        "cloudflare_agents": {
            "objective": "build_cloudflare_agents_worker_app",
            "workflow_id": "cloudflare_agents_workflow",
            "primary_action": "cloudflare_agents_scaffold",
            "preferred_tools": [
                "cloudflare_agents_status",
                "cloudflare_agents_project",
                "cloudflare_agents_scaffold",
                "cloudflare_agents_workflow",
                "create_software_project_pack",
                "create_web_project_scaffold",
            ],
            "output_artifacts": ["wrangler_jsonc", "server_ts", "client_tsx", "workflow_notes", "mcp_notes"],
            "quality_checklist": ["deploy_readiness", "durable_state", "realtime_sync", "callable_methods", "mcp_ready"],
            "learning_tags": ["cloudflare", "workers", "agents", "edge"],
        },
        "email": {
            "objective": "manage_email_workflow_with_traceability",
            "workflow_id": "email_workflow",
            "primary_action": "send_email",
            "preferred_tools": ["send_email", "get_emails", "search_emails", "read_file"],
            "output_artifacts": ["email_receipt", "inbox_summary"],
            "quality_checklist": ["recipient_accuracy", "delivery_confirmation", "thread_context"],
            "learning_tags": ["email", "communication", "delivery"],
        },
        "calendar": {
            "objective": "manage_schedule_and_reminders_reliably",
            "workflow_id": "calendar_workflow",
            "primary_action": "create_event",
            "preferred_tools": ["create_event", "create_reminder", "get_today_events"],
            "output_artifacts": ["calendar_entry", "reminder_receipt"],
            "quality_checklist": ["time_accuracy", "timezone_safety", "confirmation"],
            "learning_tags": ["calendar", "planning", "reminder"],
        },
        "social": {
            "objective": "manage_social_workflows_with_confirmation",
            "workflow_id": "social_workflow",
            "primary_action": "browser_social_control",
            "preferred_tools": ["open_url", "browser_open", "browser_click", "browser_type", "take_screenshot"],
            "output_artifacts": ["post_receipt", "conversation_summary"],
            "quality_checklist": ["account_accuracy", "post_verification", "policy_safety"],
            "learning_tags": ["social", "post", "communication"],
        },
        "scheduler": {
            "objective": "schedule_tasks_and_followups_reliably",
            "workflow_id": "scheduler_workflow",
            "primary_action": "create_reminder",
            "preferred_tools": ["create_reminder", "create_event", "schedule_job"],
            "output_artifacts": ["schedule_receipt", "job_spec"],
            "quality_checklist": ["time_accuracy", "persistence", "retryability"],
            "learning_tags": ["scheduler", "cron", "automation"],
        },
        "google": {
            "objective": "integrate_google_services",
            "workflow_id": "google_api_workflow",
            "primary_action": "http_request",
            "preferred_tools": ["http_request", "write_file", "read_file"],
            "output_artifacts": ["api_spec", "integration_trace"],
            "quality_checklist": ["scope_accuracy", "auth_safety", "traceability"],
            "learning_tags": ["google", "oauth", "api"],
        },
        "drive": {
            "objective": "manage_drive_documents_with_traceability",
            "workflow_id": "drive_workflow",
            "primary_action": "http_request",
            "preferred_tools": ["http_request", "read_file", "write_file"],
            "output_artifacts": ["drive_manifest", "file_receipt"],
            "quality_checklist": ["file_integrity", "source_traceability", "permissions"],
            "learning_tags": ["drive", "files", "workspace"],
        },
        "screen_operator": {
            "objective": "inspect_control_and_verify_screen_state",
            "workflow_id": "screen_operator_workflow",
            "primary_action": "screen_workflow",
            "preferred_tools": ["screen_workflow", "vision_operator_loop", "analyze_screen", "computer_use", "take_screenshot"],
            "output_artifacts": ["screenshots", "screen_summary", "control_result"],
            "quality_checklist": ["screen_readability", "control_verification", "artifact_traceability"],
            "learning_tags": ["screen", "operator", "vision"],
        },
        "real_time_control": {
            "objective": "inspect_control_and_verify_screen_state",
            "workflow_id": "real_time_control_workflow",
            "primary_action": "screen_workflow",
            "preferred_tools": ["screen_workflow", "vision_operator_loop", "analyze_screen", "computer_use", "take_screenshot"],
            "output_artifacts": ["screenshots", "screen_summary", "control_result"],
            "quality_checklist": ["screen_readability", "control_verification", "artifact_traceability"],
            "learning_tags": ["screen", "operator", "vision", "real_time"],
        },
        "file_ops": {
            "objective": "perform_filesystem_tasks_with_verification",
            "workflow_id": "file_operations_workflow",
            "primary_action": "filesystem_batch",
            "preferred_tools": ["write_file", "read_file", "create_folder", "list_files"],
            "output_artifacts": ["files", "folders", "verification_notes"],
            "quality_checklist": ["path_correctness", "non_empty_output", "verification"],
            "learning_tags": ["filesystem", "artifacts", "documents"],
        },
        "document": {
            "objective": "generate_professional_document_bundle",
            "workflow_id": "document_delivery_workflow",
            "primary_action": "analyze_document_vision",
            "preferred_tools": [
                "analyze_document_vision",
                "extract_tables_from_document",
                "extract_charts_from_document",
                "read_pdf",
                "summarize_document",
                "generate_document_pack",
                "generate_research_document",
                "generate_report",
            ],
            "output_artifacts": ["docx", "pdf", "executive_summary"],
            "quality_checklist": [
                "structure",
                "language_quality",
                "professional_tone",
                "completeness",
                "layout_accuracy",
                "table_integrity",
                "chart_fidelity",
            ],
            "learning_tags": ["documentation", "writing", "delivery", "vision", "tables", "charts"],
        },
        "summarization": {
            "objective": "compress_information_without_losing_signal",
            "workflow_id": "summarization_workflow",
            "primary_action": "summarize_text",
            "preferred_tools": ["smart_summarize", "summarize_document", "analyze_document"],
            "output_artifacts": ["summary", "key_points", "action_items"],
            "quality_checklist": ["conciseness", "fidelity", "clarity"],
            "learning_tags": ["summary", "compression", "knowledge"],
        },
        "api_integration": {
            "objective": "design_and_execute_api_integrations",
            "workflow_id": "api_integration_workflow",
            "primary_action": "http_request",
            "preferred_tools": ["http_request", "graphql_query", "api_health_check", "write_file", "read_file"],
            "output_artifacts": ["integration_spec", "request_examples", "response_contracts"],
            "quality_checklist": ["auth_safety", "retry_strategy", "idempotency", "observability"],
            "learning_tags": ["api", "integration", "automation"],
        },
        "automation": {
            "objective": "orchestrate_reliable_automation_workflows",
            "workflow_id": "automation_workflow",
            "primary_action": "computer_use",
            "preferred_tools": ["create_plan", "execute_plan", "run_safe_command", "write_file", "list_files"],
            "output_artifacts": ["workflow_plan", "runbook", "automation_logs"],
            "quality_checklist": ["safety", "rollback", "monitoring", "repeatability"],
            "learning_tags": ["automation", "ops", "workflow"],
        },
        "full_stack_delivery": {
            "objective": "deliver_end_to_end_solution_with_validation",
            "workflow_id": "full_stack_delivery_workflow",
            "primary_action": "create_coding_project",
            "preferred_tools": [
                "create_coding_project",
                "create_software_project_pack",
                "create_web_project_scaffold",
                "http_request",
                "run_safe_command",
                "write_file",
            ],
            "output_artifacts": ["project_pack", "deployment_plan", "verification_report"],
            "quality_checklist": ["architecture", "quality_gates", "security", "maintainability"],
            "learning_tags": ["delivery", "architecture", "multi-agent"],
        },
        "general": {
            "objective": "solve_user_task_reliably",
            "workflow_id": "general_assistance_workflow",
            "primary_action": "chat",
            "preferred_tools": ["create_plan", "execute_plan"],
            "output_artifacts": ["result"],
            "quality_checklist": ["correctness", "clarity"],
            "learning_tags": ["general"],
        },
    }

    @staticmethod
    def _complexity_tier(*, confidence: float, text: str, domain: str) -> str:
        low_text = str(text or "").lower()
        token_count = len(low_text.split())
        hard_markers = ("uçtan uca", "ucdan uca", "full stack", "mimari", "production", "microservice", "agent team")
        if domain in {"full_stack_delivery", "automation"} and confidence >= 0.55:
            return "extreme"
        if confidence >= 0.8 or token_count >= 30 or any(m in low_text for m in hard_markers):
            return "high"
        if confidence >= 0.55 or token_count >= 16:
            return "medium"
        return "low"

    @staticmethod
    def _should_recommend_multi_agent(*, domain: str, confidence: float, complexity_tier: str) -> bool:
        if complexity_tier in {"high", "extreme"} and confidence >= 0.55:
            return True
        return domain in {"full_stack_delivery", "automation"} and confidence >= 0.45

    @staticmethod
    def _content_kind_from_domain(domain: str, text: str) -> str:
        low = str(text or "").lower()
        if domain == "research":
            return "research_delivery"
        if domain == "email":
            return "communication"
        if domain == "calendar":
            return "planning"
        if domain == "social":
            return "communication"
        if domain == "scheduler":
            return "automation"
        if domain == "google":
            return "api_integration"
        if domain == "drive":
            return "document_pack"
        if domain == "document":
            if any(marker in low for marker in ("excel", "xlsx", "csv", "tablo", "sheet", "spreadsheet")):
                return "spreadsheet"
            if any(marker in low for marker in ("sunum", "presentation", "slide", "slides", "deck", "ppt", "pptx")):
                return "presentation"
            if any(marker in low for marker in ("layout", "ocr", "vision", "görsel", "gorsel", "chart", "grafik", "diagram", "figure")):
                return "document_pack"
            return "document_pack"
        if any(marker in low for marker in ("sunum", "presentation", "slide", "slides", "deck", "ppt", "pptx")):
            return "presentation"
        if any(marker in low for marker in ("excel", "xlsx", "csv", "tablo", "sheet", "spreadsheet")):
            return "spreadsheet"
        if domain == "website":
            return "web_project"
        if domain == "code":
            return "code_project"
        if domain == "document":
            return "document_pack"
        if domain == "summarization":
            return "summary_pack"
        if domain == "full_stack_delivery":
            return "delivery_bundle"
        if domain == "cloudflare_agents":
            return "code_project"
        return "task"

    @staticmethod
    def _infer_output_formats(text: str, content_kind: str, domain: str) -> list[str]:
        low = str(text or "").lower()
        formats: list[str] = []

        def add(fmt: str) -> None:
            if fmt and fmt not in formats:
                formats.append(fmt)

        if content_kind == "presentation":
            add("pptx")
            add("md")
        if content_kind == "spreadsheet":
            add("xlsx")
        if content_kind == "communication":
            add("txt")
            if any(marker in low for marker in ("email", "mail")):
                add("eml")
        if content_kind == "planning":
            add("ics")
            add("json")
        if content_kind == "automation":
            add("json")
        if content_kind in {"research_delivery", "document_pack", "summary_pack"}:
            add("docx")
            if any(marker in low for marker in ("layout", "ocr", "vision", "görsel", "gorsel", "tablo", "table", "grafik", "chart", "diagram", "figure")):
                add("json")
            if any(marker in low for marker in ("pdf", "portable document", "pdf olarak")):
                add("pdf")
            if any(marker in low for marker in ("html", "htm", "web")):
                add("html")
            if any(marker in low for marker in ("markdown", "md")):
                add("md")
            if any(marker in low for marker in ("tex", "latex")):
                add("tex")
            if any(marker in low for marker in ("ppt", "pptx", "sunum", "presentation", "slide", "slides", "deck")):
                add("pptx")
            if any(marker in low for marker in ("excel", "xlsx", "csv", "tablo", "sheet", "spreadsheet")):
                add("xlsx")
        elif content_kind == "web_project":
            add("html")
            add("md")
        elif content_kind == "code_project":
            add("md")
        if domain == "research" and not formats:
            add("docx")
        if domain == "code" and not formats:
            add("md")
        if domain == "cloudflare_agents" and not formats:
            add("md")
        return formats or ["docx"]

    @staticmethod
    def _infer_style_profile(text: str, content_kind: str, domain: str) -> str:
        low = str(text or "").lower()
        if content_kind == "presentation":
            return "presentation"
        if content_kind == "spreadsheet":
            return "structured"
        if content_kind == "communication":
            return "briefing"
        if content_kind == "planning":
            return "planning"
        if content_kind == "automation":
            return "operational"
        if domain == "code":
            return "implementation"
        if domain == "cloudflare_agents":
            return "implementation"
        if any(marker in low for marker in ("analitik", "analytical", "detaylı", "detayli", "scientific", "bilimsel")):
            return "analytical"
        if any(marker in low for marker in ("brief", "kısa", "kisa", "özet", "ozet", "summary")):
            return "briefing"
        return "executive"

    @staticmethod
    def _infer_source_policy(text: str, domain: str, content_kind: str) -> str:
        low = str(text or "").lower()
        if any(marker in low for marker in ("resmi", "official", "gov", "mevzuat", "kanun", "regulation", "yönetmelik", "yonetmelik")):
            return "official"
        if any(marker in low for marker in ("akademik", "academic", "makale", "journal", "literature", "literatür", "literatur")):
            return "academic"
        if domain == "research" or content_kind in {"research_delivery", "document_pack", "presentation"}:
            return "trusted"
        return "trusted"

    @staticmethod
    def _infer_quality_contract(domain: str, content_kind: str) -> list[str]:
        if content_kind == "research_delivery":
            return [
                "source_traceability",
                "claim_coverage",
                "critical_claim_coverage",
                "uncertainty_log",
                "artifact_manifest",
            ]
        if content_kind == "presentation":
            return [
                "slide_outline",
                "message_clarity",
                "source_traceability",
                "section_coverage",
            ]
        if content_kind == "spreadsheet":
            return [
                "sheet_integrity",
                "table_structure",
                "header_clarity",
                "source_traceability",
            ]
        if content_kind == "communication":
            return [
                "recipient_accuracy",
                "thread_context",
                "tone_alignment",
            ]
        if content_kind == "planning":
            return [
                "time_accuracy",
                "timezone_safety",
                "confirmation",
            ]
        if content_kind == "automation":
            return [
                "safety",
                "repeatability",
                "traceability",
            ]
        if domain == "cloudflare_agents":
            return [
                "deploy_readiness",
                "durable_state",
                "realtime_sync",
                "callable_methods",
                "mcp_ready",
            ]
        if content_kind == "web_project":
            return [
                "dom_contract",
                "responsive_preview",
                "artifact_evidence",
            ]
        if content_kind == "document_pack":
            return [
                "structure",
                "language_quality",
                "traceability",
                "layout_accuracy",
                "table_integrity",
                "chart_fidelity",
            ]
        if domain == "code":
            return [
                "repo_truth",
                "gates",
                "artifact_evidence",
            ]
        return [
            "structure",
            "language_quality",
            "traceability",
        ]

    @staticmethod
    def _infer_memory_scope(domain: str, content_kind: str) -> str:
        if domain == "general":
            return "profile_only"
        if content_kind in {"research_delivery", "document_pack", "presentation", "spreadsheet", "web_project", "code_project"}:
            return "task_routed"
        return "task_routed"

    @staticmethod
    def _build_preview(
        *,
        domain: str,
        content_kind: str,
        output_formats: list[str],
        style_profile: str,
        source_policy: str,
        quality_contract: list[str],
        confidence: float,
        needs_clarification: bool,
    ) -> str:
        preview_parts = []
        kind_labels = {
            "research_delivery": "kaynaklı araştırma belgesi",
            "presentation": "sunum",
            "spreadsheet": "excel tablo paketi",
            "document_pack": "doküman paketi",
            "web_project": "web projesi",
            "code_project": "kod teslimi",
            "delivery_bundle": "uçtan uca teslim paketi",
            "summary_pack": "özet paketi",
            "task": "görev",
        }
        preview_parts.append(kind_labels.get(content_kind, content_kind.replace("_", " ")))
        if output_formats:
            preview_parts.append(f"çıktılar: {', '.join(output_formats[:4])}")
        if style_profile:
            preview_parts.append(f"stil: {style_profile}")
        if source_policy and source_policy != "trusted":
            preview_parts.append(f"kaynak politikası: {source_policy}")
        if quality_contract:
            preview_parts.append(f"kalite: {', '.join(quality_contract[:3])}")
        if confidence < 0.5 or needs_clarification:
            preview_parts.append("netleştirme gerekebilir")
        if domain:
            preview_parts.append(f"alan: {domain}")
        return " | ".join(preview_parts)

    def build_request_contract(
        self,
        text: str,
        *,
        domain: str = "",
        confidence: float = 0.0,
        route_mode: str = "",
        output_artifacts: list[str] | None = None,
        quality_checklist: list[str] | None = None,
        quick_intent: Any = None,
        parsed_intent: dict[str, Any] | None = None,
        attachments: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RequestContract:
        low = str(text or "").lower()
        resolved_domain = str(domain or "").strip().lower() or self.route(text).domain
        content_kind = self._content_kind_from_domain(resolved_domain, low)
        if resolved_domain == "general" and any(marker in low for marker in ("rapor", "report", "docx", "pdf", "sunum", "presentation", "excel", "xlsx")):
            content_kind = self._content_kind_from_domain("document", low)
        output_formats = self._infer_output_formats(low, content_kind, resolved_domain)
        style_profile = self._infer_style_profile(low, content_kind, resolved_domain)
        source_policy = self._infer_source_policy(low, resolved_domain, content_kind)
        quality_contract = list(quality_checklist or []) or self._infer_quality_contract(resolved_domain, content_kind)
        memory_scope = self._infer_memory_scope(resolved_domain, content_kind)
        evidence_required = resolved_domain not in {"communication"}
        needs_clarification = bool(confidence < 0.5 and resolved_domain in {"general", "document"})
        if parsed_intent and isinstance(parsed_intent, dict):
            intent_action = str(parsed_intent.get("action") or "").strip().lower()
            if intent_action in {"chat", "answer", "respond"}:
                evidence_required = False
        clarifying_question = ""
        if needs_clarification:
            if content_kind in {"presentation", "spreadsheet"}:
                clarifying_question = "Bunu sunum, excel tablo ya da doküman olarak mı hazırlayayım?"
            elif content_kind in {"research_delivery", "document_pack"}:
                clarifying_question = "Bunu rapor, özet ya da kaynaklı belge olarak mı hazırlayayım?"
            else:
                clarifying_question = "Çıktı biçimini netleştirir misin?"
        preview = self._build_preview(
            domain=resolved_domain,
            content_kind=content_kind,
            output_formats=output_formats,
            style_profile=style_profile,
            source_policy=source_policy,
            quality_contract=quality_contract,
            confidence=float(confidence or 0.0),
            needs_clarification=needs_clarification,
        )
        metadata_payload = dict(metadata or {})
        if attachments:
            metadata_payload["attachment_count"] = len([item for item in attachments if str(item or "").strip()])
        if quick_intent is not None:
            metadata_payload["quick_intent_category"] = str(getattr(quick_intent, "category", "") or "")
            metadata_payload["quick_intent_confidence"] = float(getattr(quick_intent, "confidence", 0.0) or 0.0)
        if parsed_intent:
            metadata_payload["parsed_action"] = str(parsed_intent.get("action") or "")
        if route_mode:
            metadata_payload["route_mode"] = str(route_mode)
        return RequestContract(
            domain=resolved_domain,
            objective=" ".join(str(text or "").strip().split()),
            route_mode=str(route_mode or resolved_domain or "task"),
            content_kind=content_kind,
            confidence=float(confidence or 0.0),
            output_formats=output_formats,
            output_artifacts=list(output_artifacts or []),
            style_profile=style_profile,
            source_policy=source_policy,
            quality_contract=quality_contract,
            memory_scope=memory_scope,
            evidence_required=evidence_required,
            needs_clarification=needs_clarification,
            clarifying_question=clarifying_question,
            preview=preview,
            metadata=metadata_payload,
        )

    def route(self, text: str) -> CapabilityPlan:
        normalized = str(text or "").lower()
        scores: dict[str, int] = {}
        app_control_signal = self._is_app_control_command(normalized)
        for domain, keywords in self._DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if self._keyword_in_text(normalized, kw))
            if score > 0:
                scores[domain] = score

        if scores:
            ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
            best_domain = ranked[0][0]
            max_score = ranked[0][1]
            second_domain = ranked[1][0] if len(ranked) > 1 else ""
            second_score = ranked[1][1] if len(ranked) > 1 else 0

            # Strong mixed-signal requests are treated as full-stack delivery.
            combo = {best_domain, second_domain}
            if second_score >= 2 and combo.intersection({"website", "code", "api_integration"}) and len(combo) >= 2:
                best_domain = "full_stack_delivery"
                max_score += 1

            confidence = min(0.35 + (0.12 * max_score), 0.96)
        else:
            best_domain = "general"
            confidence = 0.3

        # App control commands are operator tasks; keep routing deterministic.
        if app_control_signal:
            best_domain = "screen_operator"
            confidence = max(float(confidence or 0.0), 0.82)

        hints = dict(self._DOMAIN_HINTS[best_domain])
        multi_step_operator = best_domain in {"screen_operator", "real_time_control"} and self._has_multi_step_operator_signal(normalized)
        if multi_step_operator:
            hints["primary_action"] = "operator_mission_control"
            hints["preferred_tools"] = ["operator_mission_control", "vision_operator_loop", "screen_workflow", "computer_use", "analyze_screen", "take_screenshot"]
        elif best_domain in {"screen_operator", "real_time_control"} and self._has_strong_screen_control_signal(normalized):
            hints["primary_action"] = "vision_operator_loop"
            hints["preferred_tools"] = ["vision_operator_loop", "screen_workflow", "computer_use", "analyze_screen", "take_screenshot"]
        complexity_tier = self._complexity_tier(confidence=confidence, text=normalized, domain=best_domain)
        multi_agent_recommended = self._should_recommend_multi_agent(
            domain=best_domain,
            confidence=confidence,
            complexity_tier=complexity_tier,
        )
        if multi_step_operator:
            multi_agent_recommended = True
        suggested_job_type = self._DOMAIN_TO_JOB_TYPE.get(best_domain, "communication")
        request_contract = self.build_request_contract(
            normalized,
            domain=best_domain,
            confidence=float(confidence),
            route_mode=suggested_job_type,
            output_artifacts=list(hints.get("output_artifacts") or []),
            quality_checklist=list(hints.get("quality_checklist") or []),
            metadata={"workflow_id": str(hints.get("workflow_id") or ""), "primary_action": str(hints.get("primary_action") or "")},
        )

        return CapabilityPlan(
            domain=best_domain,
            confidence=confidence,
            objective=str(hints["objective"]),
            workflow_id=str(hints["workflow_id"]),
            primary_action=str(hints["primary_action"]),
            preferred_tools=list(hints["preferred_tools"]),
            output_artifacts=list(hints["output_artifacts"]),
            quality_checklist=list(hints["quality_checklist"]),
            learning_tags=list(hints["learning_tags"]),
            complexity_tier=complexity_tier,
            suggested_job_type=suggested_job_type,
            multi_agent_recommended=multi_agent_recommended,
            orchestration_mode="multi_agent" if multi_agent_recommended else "single_agent",
            workflow_profile_applicable=best_domain in {"code", "api_integration", "full_stack_delivery", "lean", "cloudflare_agents"},
            requires_design_phase=best_domain in {"code", "api_integration", "full_stack_delivery", "lean", "cloudflare_agents"},
            requires_worktree=best_domain in {"full_stack_delivery", "cloudflare_agents"},
            content_kind=request_contract.content_kind,
            output_formats=list(request_contract.output_formats or []),
            style_profile=request_contract.style_profile,
            source_policy=request_contract.source_policy,
            quality_contract=list(request_contract.quality_contract or []),
            memory_scope=request_contract.memory_scope,
            preview=request_contract.preview,
            request_contract=request_contract.to_dict(),
        )


_capability_router: CapabilityRouter | None = None


def get_capability_router() -> CapabilityRouter:
    global _capability_router
    if _capability_router is None:
        _capability_router = CapabilityRouter()
    return _capability_router
