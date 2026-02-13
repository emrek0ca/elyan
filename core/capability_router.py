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


class CapabilityRouter:
    """Detect major capability domain and provide execution hints."""

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
            "preferred_tools": ["create_software_project_pack", "execute_python_code", "debug_code", "write_file"],
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
        "general": {
            "objective": "solve_user_task_reliably",
            "preferred_tools": ["create_plan", "execute_plan"],
            "output_artifacts": ["result"],
            "quality_checklist": ["correctness", "clarity"],
            "learning_tags": ["general"],
        },
    }

    def route(self, text: str) -> CapabilityPlan:
        normalized = str(text or "").lower()
        scores: dict[str, int] = {}
        for domain, keywords in self._DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in normalized)
            if score > 0:
                scores[domain] = score

        if scores:
            best_domain = max(scores, key=scores.get)
            max_score = scores[best_domain]
            confidence = min(0.35 + (0.15 * max_score), 0.95)
        else:
            best_domain = "general"
            confidence = 0.3

        hints = self._DOMAIN_HINTS[best_domain]
        return CapabilityPlan(
            domain=best_domain,
            confidence=confidence,
            objective=str(hints["objective"]),
            preferred_tools=list(hints["preferred_tools"]),
            output_artifacts=list(hints["output_artifacts"]),
            quality_checklist=list(hints["quality_checklist"]),
            learning_tags=list(hints["learning_tags"]),
        )


_capability_router: CapabilityRouter | None = None


def get_capability_router() -> CapabilityRouter:
    global _capability_router
    if _capability_router is None:
        _capability_router = CapabilityRouter()
    return _capability_router
