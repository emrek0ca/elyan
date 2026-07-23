"""P0 — Tek plan otoritesi: CompiledExecutionPlan (elyan.compiled_plan.v1).

Planlayıcıdan çıkan, onaylanan ve yürütülen plan TEK kanonik şekle derlenir ve
tek bir hash'e bağlanır. Kurallar:

- `plan_signature(steps)` kanonik hash'in TEK kaynağıdır. execution_journal,
  execution_trust ve pending-plan bağları hep bu fonksiyonu kullanır.
- Bir plan derlendikten sonra step/args/dependsOn değişirse hash tutmaz ve
  yürütme fail-closed reddedilir (PLAN_BINDING_MISMATCH).
- Clarification/replan yeni `revision` + yeni `planHash` üretir; eski
  revision'a bağlı WorkOrder/grant yeniden kullanılamaz.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

PLAN_CONTRACT = "elyan.compiled_plan.v1"
_HASH_PREFIX = "sha256:"
_STEP_REF_RE = re.compile(r"\{\{\s*steps\.([A-Za-z0-9_\-]+)")

_RISK_LEVELS = ("low", "medium", "high", "critical")


class PlanBindingError(RuntimeError):
    """Derlenmiş plan bağı doğrulanamadı — fail-closed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code or "PLAN_BINDING_MISMATCH").upper()
        self.message = message


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _public_args(args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    return {str(key): value for key, value in args.items() if not str(key).startswith("_")}


class StepRetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    maxAttempts: int = Field(default=2, ge=1, le=6)
    backoffBaseSeconds: float = Field(default=1.0, ge=0.0, le=60.0)
    retryableErrorClasses: tuple[str, ...] = Field(
        default=("timeout", "rate_limited", "upstream_unavailable", "network")
    )


class StepVerificationContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = "tool_result"
    # Semantik beklentiler (GoalContract'tan türetilir): adet/format/kaynak.
    expectedFormat: str = ""
    expectedMinCount: int = Field(default=0, ge=0)
    expectedKind: str = ""


class CompiledPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stepId: str = Field(min_length=1, max_length=80)
    capability: str = Field(min_length=1, max_length=120)
    args: dict[str, Any] = Field(default_factory=dict)
    dependsOn: tuple[str, ...] = ()
    # Adımın args'ındaki {{steps.<id>...}} veri-akışı atıfları (çıkarılmış).
    outputBindings: tuple[str, ...] = ()
    resourceScope: tuple[str, ...] = ()
    forEach: str | None = None
    risk: str = "low"
    timeoutSeconds: int = Field(default=60, ge=1, le=3600)
    retry: StepRetryPolicy = Field(default_factory=StepRetryPolicy)
    verification: StepVerificationContract = Field(default_factory=StepVerificationContract)

    @field_validator("risk")
    @classmethod
    def _risk_enum(cls, value: str) -> str:
        normalized = str(value or "low").strip().lower()
        return normalized if normalized in _RISK_LEVELS else "low"

    @field_validator("args")
    @classmethod
    def _drop_private_args(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _public_args(value)


class CompiledExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: str = PLAN_CONTRACT
    taskId: str = ""
    revision: int = Field(default=1, ge=1)
    planHash: str = ""
    objective: str = ""
    compiledAt: str = ""
    steps: tuple[CompiledPlanStep, ...] = ()

    @field_validator("contract")
    @classmethod
    def _contract_const(cls, value: str) -> str:
        if value != PLAN_CONTRACT:
            raise ValueError(f"unsupported plan contract: {value!r}")
        return value


def _canonical_step_shape(step: dict[str, Any]) -> dict[str, Any]:
    """Hash'e giren kanonik adım şekli — journal'ın eski şekliyle birebir aynı
    (mevcut resume state'leri geçersiz kılmamak için alan kümesi korunur)."""
    return {
        "id": str(step.get("id", "") or ""),
        "capability": str(step.get("capability", "") or ""),
        "args": _public_args(step.get("args", {})),
        "dependsOn": list(step.get("dependsOn", []) or []),
        "forEach": step.get("forEach"),
        "resourceScope": list(step.get("resourceScope", []) or []),
    }


def plan_signature(steps: list[dict[str, Any]] | tuple[Any, ...]) -> str:
    """Kanonik plan hash'i — imza, onay ve yürütme aynı değeri kullanır."""
    shape = [
        _canonical_step_shape(step)
        for step in steps
        if isinstance(step, dict)
    ]
    return _HASH_PREFIX + hashlib.sha256(_canonical_json(shape).encode("utf-8")).hexdigest()


def _step_output_bindings(step: dict[str, Any]) -> tuple[str, ...]:
    blob = _canonical_json({"args": _public_args(step.get("args", {})), "forEach": step.get("forEach")})
    return tuple(sorted(set(_STEP_REF_RE.findall(blob))))


def compile_plan(
    steps: list[dict[str, Any]],
    *,
    task_id: str = "",
    revision: int = 1,
    objective: str = "",
    goal_contract: dict[str, Any] | None = None,
    metadata_provider: Any = None,
) -> CompiledExecutionPlan:
    """Doğrulanmış planner adımlarını tek otorite CompiledExecutionPlan'a derler."""
    goal = goal_contract if isinstance(goal_contract, dict) else {}
    goal_risk = str(goal.get("risk", "") or "low").strip().lower()
    if goal_risk not in _RISK_LEVELS:
        goal_risk = "low"
    compiled_steps: list[CompiledPlanStep] = []
    seen_ids: set[str] = set()
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        capability = str(step.get("capability", "") or "").strip()
        if not capability:
            continue
        step_id = str(step.get("id", "") or f"step_{index}").strip()[:80]
        if step_id in seen_ids:
            raise PlanBindingError("PLAN_STEP_ID_DUPLICATE", f"Plan adım kimliği tekrarlı: {step_id!r}")
        seen_ids.add(step_id)
        metadata: dict[str, Any] = {}
        if callable(metadata_provider):
            try:
                metadata = metadata_provider(capability) or {}
            except Exception:
                metadata = {}
        side_effect = bool(metadata.get("sideEffect", False))
        timeout_seconds = int(metadata.get("timeoutSeconds", 60) or 60)
        depends_on = tuple(
            dict.fromkeys(
                str(item or "").strip()[:80]
                for item in (step.get("dependsOn", []) or [])
                if str(item or "").strip()
            )
        )
        resource_scope = tuple(
            " ".join(str(item or "").split())[:240]
            for item in (step.get("resourceScope", []) or [])
            if str(item or "").strip()
        )
        for_each = step.get("forEach")
        compiled_steps.append(
            CompiledPlanStep(
                stepId=step_id,
                capability=capability,
                args=_public_args(step.get("args", {})),
                dependsOn=depends_on,
                outputBindings=_step_output_bindings(step),
                resourceScope=resource_scope,
                forEach=str(for_each) if isinstance(for_each, str) and for_each.strip() else None,
                risk=goal_risk if side_effect else "low",
                timeoutSeconds=max(1, min(3600, timeout_seconds)),
                retry=StepRetryPolicy(maxAttempts=3 if bool(metadata.get("retryable", False)) else 1),
                verification=StepVerificationContract(
                    mode=str(metadata.get("verificationMode", "tool_result") or "tool_result"),
                ),
            )
        )

    executable_steps = [
        {
            "id": item.stepId,
            "capability": item.capability,
            "args": dict(item.args),
            "dependsOn": list(item.dependsOn),
            "forEach": item.forEach,
            "resourceScope": list(item.resourceScope),
        }
        for item in compiled_steps
    ]
    return CompiledExecutionPlan(
        taskId=str(task_id or "").strip(),
        revision=max(1, int(revision or 1)),
        planHash=plan_signature(executable_steps),
        objective=" ".join(str(objective or goal.get("objective", "") or "").split())[:1000],
        compiledAt=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        steps=tuple(compiled_steps),
    )


def verify_steps_against_hash(steps: list[dict[str, Any]], expected_hash: str) -> None:
    """Yürütülecek adımlar derleme anındaki hash'le birebir aynı olmalı."""
    expected = str(expected_hash or "").strip()
    if not expected:
        raise PlanBindingError("PLAN_BINDING_MISSING", "Plan hash bağı bulunamadı.")
    actual = plan_signature(steps)
    if actual != expected:
        raise PlanBindingError(
            "PLAN_BINDING_MISMATCH",
            "Plan, imzalanan/onaylanan halinden farklı; yürütme fail-closed durduruldu.",
        )


# ── Pending-plan bağları (state_store choke-point'i için yardımcılar) ────────


def binding_for_steps(
    steps: list[dict[str, Any]],
    *,
    revision: int = 1,
) -> dict[str, Any]:
    return {
        "contract": PLAN_CONTRACT,
        "revision": max(1, int(revision or 1)),
        "planHash": plan_signature(steps),
        "boundAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def next_binding(previous: dict[str, Any] | None, steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Replan/clarification/revizyon: revision +1 ve YENİ planHash."""
    prior_revision = 0
    if isinstance(previous, dict):
        try:
            prior_revision = int(previous.get("revision", 0) or 0)
        except (TypeError, ValueError):
            prior_revision = 0
    return binding_for_steps(steps, revision=prior_revision + 1)


def plan_steps_for_binding(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Pending plan kaydından bağa giren adım listesini çıkarır."""
    steps = plan.get("steps")
    if isinstance(steps, list) and steps:
        return [step for step in steps if isinstance(step, dict)]
    preview = plan.get("planPreview")
    if isinstance(preview, dict) and isinstance(preview.get("steps"), list):
        return [step for step in preview["steps"] if isinstance(step, dict)]
    return []


def verify_pending_plan_binding(plan: dict[str, Any]) -> bool:
    """Pending planın kayıtlı bağı adımlarla tutuyor mu? (tamper → False)."""
    binding = plan.get("planBinding")
    if not isinstance(binding, dict):
        return False
    steps = plan_steps_for_binding(plan)
    try:
        verify_steps_against_hash(steps, str(binding.get("planHash", "") or ""))
    except PlanBindingError:
        return False
    return True
