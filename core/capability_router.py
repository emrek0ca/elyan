"""
Capability Router
High-level intent domain detection for professional assistant workflows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CapabilityPlan:
    domain: str
    confidence: float
    objective: str
    preferred_tools: list[str]
    output_artifacts: list[str]
    quality_checklist: list[str]
    learning_tags: list[str]
    complexity_tier: str = "low"
    suggested_job_type: str = "communication"
    multi_agent_recommended: bool = False
    orchestration_mode: str = "single_agent"


class CapabilityRouter:
    """Detect major capability domain and provide execution hints."""

    _DOMAIN_TO_JOB_TYPE: dict[str, str] = {
        "website": "web_project",
        "code": "code_project",
        "api_integration": "api_integration",
        "automation": "system_ops",
        "research": "research_report",
        "document": "research_report",
        "summarization": "research_report",
        "multimodal": "browser_task",
        "image": "browser_task",
        "full_stack_delivery": "code_project",
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
        "document": [
            "belge", "dokuman", "doküman", "docx", "pdf", "rapor", "report",
            "proposal", "sunum", "presentation", "teklif"
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
        "full_stack_delivery": [
            "full stack", "uçtan uca", "uctan uca", "production", "deployment",
            "mimari", "architecture", "pipeline", "microservice", "dashboard"
        ],
    }

    _DOMAIN_HINTS: dict[str, dict[str, Any]] = {
        "website": {
            "objective": "build_production_ready_web_artifact",
            "preferred_tools": ["create_software_project_pack", "create_web_project_scaffold", "create_smart_file", "write_file"],
            "output_artifacts": ["project_folder", "readme", "deployment_notes"],
            "quality_checklist": ["responsive", "accessible", "performant", "maintainable"],
            "learning_tags": ["web", "ui", "frontend"],
        },
        "code": {
            "objective": "deliver_working_testable_code",
            "preferred_tools": [
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
            "preferred_tools": ["create_image_workflow_profile", "analyze_image", "create_smart_file"],
            "output_artifacts": ["prompt_pack", "style_profile", "asset_plan"],
            "quality_checklist": ["style_consistency", "clarity", "brand_alignment"],
            "learning_tags": ["visual", "design", "creative"],
        },
        "multimodal": {
            "objective": "deliver_multimodal_input_output_pipeline",
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
            "preferred_tools": ["advanced_research", "evaluate_source", "synthesize_findings"],
            "output_artifacts": ["research_summary", "source_list", "recommendations"],
            "quality_checklist": ["source_quality", "coverage", "traceability", "actionability"],
            "learning_tags": ["research", "analysis", "evidence"],
        },
        "document": {
            "objective": "generate_professional_document_bundle",
            "preferred_tools": ["generate_document_pack", "generate_research_document", "generate_report"],
            "output_artifacts": ["docx", "pdf", "executive_summary"],
            "quality_checklist": ["structure", "language_quality", "professional_tone", "completeness"],
            "learning_tags": ["documentation", "writing", "delivery"],
        },
        "summarization": {
            "objective": "compress_information_without_losing_signal",
            "preferred_tools": ["smart_summarize", "summarize_document", "analyze_document"],
            "output_artifacts": ["summary", "key_points", "action_items"],
            "quality_checklist": ["conciseness", "fidelity", "clarity"],
            "learning_tags": ["summary", "compression", "knowledge"],
        },
        "api_integration": {
            "objective": "design_and_execute_api_integrations",
            "preferred_tools": ["http_request", "graphql_query", "api_health_check", "write_file", "read_file"],
            "output_artifacts": ["integration_spec", "request_examples", "response_contracts"],
            "quality_checklist": ["auth_safety", "retry_strategy", "idempotency", "observability"],
            "learning_tags": ["api", "integration", "automation"],
        },
        "automation": {
            "objective": "orchestrate_reliable_automation_workflows",
            "preferred_tools": ["create_plan", "execute_plan", "run_safe_command", "write_file", "list_files"],
            "output_artifacts": ["workflow_plan", "runbook", "automation_logs"],
            "quality_checklist": ["safety", "rollback", "monitoring", "repeatability"],
            "learning_tags": ["automation", "ops", "workflow"],
        },
        "full_stack_delivery": {
            "objective": "deliver_end_to_end_solution_with_validation",
            "preferred_tools": [
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

    def route(self, text: str) -> CapabilityPlan:
        normalized = str(text or "").lower()
        scores: dict[str, int] = {}
        for domain, keywords in self._DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in normalized)
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

        hints = self._DOMAIN_HINTS[best_domain]
        complexity_tier = self._complexity_tier(confidence=confidence, text=normalized, domain=best_domain)
        multi_agent_recommended = self._should_recommend_multi_agent(
            domain=best_domain,
            confidence=confidence,
            complexity_tier=complexity_tier,
        )
        suggested_job_type = self._DOMAIN_TO_JOB_TYPE.get(best_domain, "communication")

        return CapabilityPlan(
            domain=best_domain,
            confidence=confidence,
            objective=str(hints["objective"]),
            preferred_tools=list(hints["preferred_tools"]),
            output_artifacts=list(hints["output_artifacts"]),
            quality_checklist=list(hints["quality_checklist"]),
            learning_tags=list(hints["learning_tags"]),
            complexity_tier=complexity_tier,
            suggested_job_type=suggested_job_type,
            multi_agent_recommended=multi_agent_recommended,
            orchestration_mode="multi_agent" if multi_agent_recommended else "single_agent",
        )


_capability_router: CapabilityRouter | None = None


def get_capability_router() -> CapabilityRouter:
    global _capability_router
    if _capability_router is None:
        _capability_router = CapabilityRouter()
    return _capability_router
