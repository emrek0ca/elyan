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
    max_tokens: int = 150000
    max_usd: float = 0.5

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
    ),
    "code_delivery_job": JobTemplate(
        id="code_delivery_job",
        name="Advanced Coding Delivery",
        mandatory_artifacts=["README.md"],
        allowed_tools=[
            "create_software_project_pack", "write_file", "read_file",
            "execute_python_code", "run_safe_command", "create_coding_verification_report",
        ],
        verification_steps=["static", "runtime"]
    ),
    "api_integration_job": JobTemplate(
        id="api_integration_job",
        name="API Integration & Validation",
        mandatory_artifacts=["integration-report.md"],
        allowed_tools=["http_request", "graphql_query", "api_health_check", "write_file", "read_file"],
        verification_steps=["static", "runtime"]
    ),
    "automation_job": JobTemplate(
        id="automation_job",
        name="System Automation Delivery",
        mandatory_artifacts=["runbook.md"],
        allowed_tools=["run_safe_command", "write_file", "read_file", "list_files", "take_screenshot"],
        verification_steps=["static"]
    ),
    "generic": JobTemplate(
        id="generic",
        name="General Multi-Step Delivery",
        mandatory_artifacts=["summary.txt"],
        allowed_tools=["write_file", "read_file", "web_search", "run_safe_command"],
        verification_steps=["static"]
    ),
}

def get_template(job_type: str) -> JobTemplate:
    key = str(job_type or "").strip().lower()
    return TEMPLATES.get(key, TEMPLATES["generic"])


def detect_template_key(user_input: str) -> str:
    low = str(user_input or "").lower()
    if any(k in low for k in ("api", "endpoint", "graphql", "webhook", "http ")):
        return "api_integration_job"
    if any(k in low for k in ("web site", "website", "landing", "html", "css", "frontend", "react", "next")):
        return "web_site_job"
    if any(k in low for k in ("automation", "otomasyon", "workflow", "cron", "rutin", "background", "daemon")):
        return "automation_job"
    if any(k in low for k in ("kod", "code", "backend", "python", "script", "project", "uygulama")):
        return "code_delivery_job"
    if any(k in low for k in ("araştır", "research", "analiz", "rapor", "report", "incele")):
        return "research_report_job"
    return "generic"
