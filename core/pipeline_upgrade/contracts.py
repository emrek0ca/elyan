from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


_CONTRACT_DIR = Path(__file__).resolve().parents[2] / "contracts"


class OutputContract(BaseModel):
    model_config = ConfigDict(extra="allow")

    contract_id: str
    job_type: str
    objective: str


class ResearchClaim(BaseModel):
    claim_id: str
    text: str = Field(min_length=10)
    source_urls: list[str] = Field(default_factory=list)
    critical: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_count: int = Field(default=0, ge=0)
    needs_manual_review: bool = False
    missing_independent_source: bool = False


class ResearchPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    query_decomposition: dict[str, Any]
    claim_list: list[ResearchClaim] = Field(default_factory=list)
    citation_map: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    uncertainty_log: list[str] = Field(default_factory=list)
    critical_claim_ids: list[str] = Field(default_factory=list)


def _contract_name_for_job(job_type: str) -> str:
    job = str(job_type or "").strip().lower()
    mapping = {
        "research": "research_report.schema.json",
        "file_operations": "file_task.schema.json",
        "code_project": "code_task.schema.json",
    }
    return mapping.get(job, "")


def load_output_contract(job_type: str) -> dict[str, Any]:
    filename = _contract_name_for_job(job_type)
    if not filename:
        return {}
    path = _CONTRACT_DIR / filename
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def validate_output_contract(job_type: str, payload: dict[str, Any]) -> tuple[bool, list[str]]:
    contract = load_output_contract(job_type)
    if not contract:
        return True, []
    required = [str(item) for item in contract.get("required", []) if str(item).strip()]
    missing = [key for key in required if key not in payload]
    if missing:
        return False, [f"missing:{key}" for key in missing]
    try:
        OutputContract.model_validate(payload)
    except ValidationError as exc:
        return False, [f"contract:{err.get('loc')}" for err in exc.errors()[:5]]
    return True, []


def assign_model_roles(model_route: dict[str, Any] | None) -> dict[str, Any]:
    route = dict(model_route or {})
    tier = str(route.get("tier") or "mid")
    router_tier = "cheap" if tier in {"cheap", "mid"} else "mid"
    critic_tier = "mid" if tier in {"cheap", "mid"} else "strong"
    return {
        "router": {"tier": router_tier, "responsibility": "understand_and_plan"},
        "worker": {"tier": tier, "responsibility": "execute"},
        "critic": {"tier": critic_tier, "responsibility": "verify"},
    }


def build_success_criteria(job_type: str, *, required_artifacts: list[str] | None = None) -> list[str]:
    artifacts = [str(item) for item in (required_artifacts or []) if str(item).strip()]
    base = [
        "intent_is_correct",
        "plan_has_schema_bound_steps",
        "execution_produces_observable_output",
        "verify_gate_passes",
    ]
    if job_type == "research":
        base.extend(
            [
                "claims_have_sources",
                "critical_claims_have_two_sources",
                "conflicts_reported_as_uncertainty",
            ]
        )
    elif job_type == "file_operations":
        base.extend(["requested_path_written", "written_content_non_empty"])
    elif job_type == "code_project":
        base.extend(["entrypoint_exists", "quality_gates_reported"])
    if artifacts:
        base.append(f"required_artifacts:{','.join(artifacts)}")
    return base


def validate_research_payload(payload: dict[str, Any] | None) -> tuple[bool, list[str]]:
    if not isinstance(payload, dict):
        return False, ["missing:research_payload"]
    try:
        parsed = ResearchPayload.model_validate(payload)
    except ValidationError as exc:
        return False, [f"research_payload:{err.get('loc')}" for err in exc.errors()[:6]]

    errors: list[str] = []
    if not parsed.query_decomposition:
        errors.append("query_decomposition")
    if not parsed.claim_list:
        errors.append("claim_list")
    if not parsed.citation_map:
        errors.append("citation_map")
    for claim in parsed.claim_list:
        if claim.claim_id not in parsed.citation_map:
            errors.append(f"citation_map:{claim.claim_id}")
        if not claim.source_urls:
            errors.append(f"claim_sources:{claim.claim_id}")
        if claim.source_count and claim.source_count != len(set(claim.source_urls)):
            errors.append(f"source_count:{claim.claim_id}")
    critical_ids = set(parsed.critical_claim_ids or [c.claim_id for c in parsed.claim_list if c.critical])
    for claim in parsed.claim_list:
        if claim.claim_id in critical_ids and len(set(claim.source_urls)) < 2:
            errors.append(f"critical_sources:{claim.claim_id}")
        if claim.missing_independent_source and len(set(claim.source_urls)) >= 2:
            errors.append(f"independent_source_flag:{claim.claim_id}")
    quality_summary = payload.get("quality_summary") if isinstance(payload, dict) else {}
    if isinstance(quality_summary, dict) and quality_summary:
        try:
            claim_coverage = float(quality_summary.get("claim_coverage", 0.0) or 0.0)
            critical_claim_coverage = float(quality_summary.get("critical_claim_coverage", 0.0) or 0.0)
        except Exception:
            claim_coverage = 0.0
            critical_claim_coverage = 0.0
        if parsed.claim_list and claim_coverage <= 0.0:
            errors.append("quality_summary:claim_coverage")
        if critical_ids and critical_claim_coverage <= 0.0:
            errors.append("quality_summary:critical_claim_coverage")
    return not errors, errors


def verify_taskspec_contract(
    task_spec: dict[str, Any] | None = None,
    job_type: str = "",
    final_response: str = "",
    tool_results: list[dict[str, Any]] | None = None,
    produced_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Verify task specification contract against produced outputs."""
    result: dict[str, Any] = {"ok": True, "failed_gates": [], "warnings": []}
    tool_results = tool_results or []
    produced_paths = produced_paths or []

    if not task_spec:
        return result

    # Check required artifacts
    required = task_spec.get("required_artifacts", [])
    for artifact in required:
        artifact_type = str(artifact.get("type", "") if isinstance(artifact, dict) else artifact)
        if artifact_type == "file" and not produced_paths:
            result["failed_gates"].append(f"missing_artifact:{artifact_type}")
            result["ok"] = False

    # Check success criteria
    success_criteria = task_spec.get("success_criteria", [])
    for criterion in success_criteria:
        crit_str = str(criterion)
        if "file" in crit_str.lower() and not produced_paths:
            result["failed_gates"].append(f"unmet_criterion:{crit_str[:50]}")
            result["ok"] = False

    return result


def build_reflexion_hint(
    verification_payload: dict[str, Any] | None = None,
    job_type: str = "",
) -> str:
    """Build a reflexion hint from verification failures to guide retry."""
    if not verification_payload:
        return ""

    failed = verification_payload.get("failed_gates", [])
    if not failed:
        return ""

    hints = []
    for gate in failed[:3]:
        gate_str = str(gate)
        if "missing_artifact" in gate_str:
            hints.append("Beklenen dosya/çıktı üretilemedi — dosya oluşturma adımını kontrol et.")
        elif "unmet_criterion" in gate_str:
            hints.append(f"Başarı kriteri karşılanmadı: {gate_str}")
        else:
            hints.append(f"Doğrulama hatası: {gate_str}")

    return " | ".join(hints) if hints else ""


def build_critic_review_prompt(
    job_type: str = "",
    final_response: str = "",
    qa_results: dict[str, Any] | list | None = None,
    errors: list[str] | None = None,
) -> str:
    """Build a critic review prompt for LLM quality assessment."""
    errors = errors or []
    if not final_response or not final_response.strip():
        return ""

    # Only trigger critic for complex jobs with potential issues
    if not errors and not qa_results:
        return ""

    error_section = ""
    if errors:
        error_section = f"\nHatalar:\n" + "\n".join(f"- {e}" for e in errors[:5])

    return (
        f"Aşağıdaki yanıtı kalite açısından değerlendir.\n"
        f"Görev tipi: {job_type}\n"
        f"Yanıt:\n{final_response[:2000]}\n"
        f"{error_section}\n\n"
        f"Kısa bir değerlendirme yap: yanıt yeterli mi, eksik bir şey var mı?"
    )
