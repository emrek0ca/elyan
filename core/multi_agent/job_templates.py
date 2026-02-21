"""
core/multi_agent/job_templates.py
─────────────────────────────────────────────────────────────────────────────
Plugin-based Job Templates.
Defines mandatory artifacts, tool permissions and checks for specific tasks.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class JobTemplate:
    id: str
    name: str
    mandatory_artifacts: List[str]
    min_file_size: int = 500
    allowed_tools: List[str] = field(default_factory=list)
    verification_steps: List[str] = field(default_factory=list)

TEMPLATES = {
    "web_site_job": JobTemplate(
        id="web_site_job",
        name="Static Landing Page Generator",
        mandatory_artifacts=["index.html"],
        allowed_tools=["write_file", "apply_patch", "web_search", "verify_visual_quality"],
        verification_steps=["static", "visual"]
    ),
    "research_report_job": JobTemplate(
        id="research_report_job",
        name="Internet Research Specialist",
        mandatory_artifacts=["report.md"],
        allowed_tools=["advanced_research", "summarize_document", "write_file"],
        verification_steps=["static"]
    )
}

def get_template(job_type: str) -> JobTemplate:
    return TEMPLATES.get(job_type, TEMPLATES["web_site_job"])
