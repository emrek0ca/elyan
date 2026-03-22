from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List

from core.text_artifacts import write_json_artifact, write_text_artifact


CODING_SUPERPOWERS_DOMAINS = frozenset({"code", "debug", "api_integration", "full_stack_delivery", "lean", "cloudflare_agents", "quivr", "opengauss"})
APPROVAL_MARKERS = (
    "onay",
    "go",
    "uygula",
    "implement",
    "devam et",
)
PREAPPROVAL_BLOCKED_TOOLS = frozenset(
    {
        "write_file",
        "create_folder",
        "create_directory",
        "delete_file",
        "move_file",
        "copy_file",
        "rename_file",
        "run_safe_command",
        "execute_shell_command",
        "execute_python_code",
        "create_web_project_scaffold",
        "create_software_project_pack",
        "create_coding_project",
        "write_word",
        "write_excel",
        "git_commit",
        "git_push",
        "git_pull",
    }
)
READ_ONLY_TASK_ACTIONS = frozenset(
    {
        "read_file",
        "list_files",
        "search_files",
        "web_search",
        "advanced_research",
        "analyze_document",
        "chat",
        "take_screenshot",
    }
)


@dataclass
class PhaseSpec:
    phase: str
    required_artifacts: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    exit_conditions: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)


@dataclass
class TaskPacket:
    packet_id: str
    title: str
    goal: str
    action: str = "chat"
    params: Dict[str, Any] = field(default_factory=dict)
    constraints: List[str] = field(default_factory=list)
    target_files: List[str] = field(default_factory=list)
    exact_change: str = ""
    tests_to_write: List[str] = field(default_factory=list)
    verification_steps: List[str] = field(default_factory=list)
    acceptance_checks: List[str] = field(default_factory=list)
    scope_guard: List[str] = field(default_factory=list)
    review_required: bool = True
    handoff_template: str = ""
    specialist_hint: str = "builder"
    execution_style: str = "tdd"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProcessProfile:
    id: str
    enabled_domains: List[str] = field(default_factory=list)
    approval_policy: str = "explicit"
    phase_specs: List[PhaseSpec] = field(default_factory=list)
    execution_mode: str = "subagent_driven"
    review_policy: str = "two_stage"
    workspace_policy: str = "auto"
    nexus_mode: str = "micro"

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["phase_specs"] = [asdict(x) for x in self.phase_specs]
        return data


def normalize_workflow_profile(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"superpowers", "superpowers-lite", "superpowers_lite"}:
        return "superpowers_lite"
    if raw in {"superpowers-strict", "superpowers_strict"}:
        return "superpowers_strict"
    if raw in {"lean", "lean_formalization", "lean-formalization"}:
        return "lean"
    if raw in {"cloudflare_agents", "cloudflare-agents", "cloudflare agents"}:
        return "cloudflare_agents"
    if raw in {"opengauss", "openGauss", "open-gauss", "database"}:
        return "opengauss"
    return "default"


def approval_granted(text: str) -> bool:
    low = str(text or "").strip().lower()
    if not low:
        return False
    for marker in APPROVAL_MARKERS:
        normalized = str(marker or "").strip().lower()
        if not normalized:
            continue
        if re.search(rf"(?<![a-z0-9_]){re.escape(normalized)}(?![a-z0-9_])", low):
            return True
    return False


def profile_applicable(profile: str, domain: str, allowed_domains: Iterable[str] | None = None) -> bool:
    normalized = normalize_workflow_profile(profile)
    if normalized == "default":
        return False
    allowed = {str(x or "").strip().lower() for x in (allowed_domains or CODING_SUPERPOWERS_DOMAINS)}
    return str(domain or "").strip().lower() in allowed


def default_phase_specs() -> List[PhaseSpec]:
    return [
        PhaseSpec(
            phase="brainstorming",
            required_artifacts=["design.txt"],
            allowed_tools=["read_file", "list_files", "search_files", "web_search", "chat"],
            exit_conditions=["design_artifact_created", "explicit_approval_pending"],
            blockers=["approval_missing"],
        ),
        PhaseSpec(
            phase="approved",
            required_artifacts=["implementation_plan.txt", "implementation_plan.json", "workspace_report.json", "baseline_check.txt"],
            allowed_tools=["read_file", "list_files", "search_files", "chat"],
            exit_conditions=["task_packets_ready", "workspace_prepared"],
            blockers=[],
        ),
        PhaseSpec(
            phase="executing",
            required_artifacts=["review_report.txt"],
            allowed_tools=["run_safe_command", "write_file", "read_file", "list_files", "chat"],
            exit_conditions=["review_passed"],
            blockers=["review_failed", "red_test_missing"],
        ),
        PhaseSpec(
            phase="finished",
            required_artifacts=["finish_branch_report.txt"],
            allowed_tools=["chat", "read_file", "list_files"],
            exit_conditions=["finish_report_written"],
            blockers=[],
        ),
    ]


def get_process_profile(profile: str, *, nexus_mode: str = "micro", allowed_domains: Iterable[str] | None = None) -> ProcessProfile:
    normalized = normalize_workflow_profile(profile)
    if normalized == "default":
        return ProcessProfile(id="default", enabled_domains=list(allowed_domains or []))
    workspace_policy = "require_worktree" if normalized in {"superpowers_strict", "lean"} else "auto"
    if normalized == "cloudflare_agents":
        workspace_policy = "require_worktree"
    if normalized == "opengauss":
        workspace_policy = "require_worktree"
    return ProcessProfile(
        id=normalized,
        enabled_domains=list(allowed_domains or CODING_SUPERPOWERS_DOMAINS),
        approval_policy="explicit",
        phase_specs=default_phase_specs(),
        execution_mode="subagent_driven",
        review_policy="two_stage_plus_reality_check",
        workspace_policy=workspace_policy,
        nexus_mode=str(nexus_mode or "micro"),
    )


def infer_nexus_mode(*, complexity: float, goal_stage_count: int, plan_length: int) -> str:
    if complexity >= 0.92 or goal_stage_count >= 6 or plan_length >= 8:
        return "full"
    if complexity >= 0.72 or goal_stage_count >= 3 or plan_length >= 4:
        return "sprint"
    return "micro"


def _extract_target_files(step: Dict[str, Any]) -> List[str]:
    if not isinstance(step, dict):
        return []
    params = step.get("params") if isinstance(step.get("params"), dict) else {}
    candidates: List[str] = []
    for key in ("path", "file_path", "output_path", "source", "destination", "directory", "folder"):
        value = str(params.get(key) or "").strip()
        if value:
            candidates.append(value)
    desc = str(step.get("description") or step.get("title") or "").strip()
    for match in re.findall(r"([\w./-]+\.[A-Za-z0-9]{1,12})", desc):
        if match:
            candidates.append(match)
    deduped: List[str] = []
    seen: set[str] = set()
    for item in candidates:
        norm = str(item or "").strip()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        deduped.append(norm)
    return deduped


def _sanitize_target_files(target_files: Iterable[str]) -> List[str]:
    sanitized: List[str] = []
    seen: set[str] = set()
    for raw in list(target_files or []):
        text = str(raw or "").strip().replace("\\", "/")
        if not text or "://" in text:
            continue
        try:
            path = PurePosixPath(text)
        except Exception:
            continue
        if path.is_absolute():
            continue
        parts = [part for part in path.parts if part not in {"", "."}]
        if not parts or any(part == ".." for part in parts):
            continue
        normalized = "/".join(parts)
        if normalized in seen:
            continue
        seen.add(normalized)
        sanitized.append(normalized)
    return sanitized


def _task_kind(action: str) -> str:
    low = str(action or "").strip().lower()
    if low in READ_ONLY_TASK_ACTIONS:
        return "read-only"
    if low in {"write_file", "create_folder", "create_directory", "rename_file", "move_file", "copy_file"}:
        return "implementation"
    if low in {"run_safe_command", "execute_shell_command", "execute_python_code"}:
        return "verification"
    if low in {"create_web_project_scaffold", "create_software_project_pack", "create_coding_project"}:
        return "implementation"
    return "implementation"


def build_task_packets(
    *,
    objective: str,
    plan: List[Dict[str, Any]],
    workflow_id: str,
    nexus_mode: str,
) -> List[TaskPacket]:
    packets: List[TaskPacket] = []
    for idx, step in enumerate(list(plan or []), start=1):
        if not isinstance(step, dict):
            continue
        title = str(step.get("title") or step.get("description") or f"Task {idx}").strip() or f"Task {idx}"
        action = str(step.get("action") or "chat").strip().lower()
        target_files = _sanitize_target_files(_extract_target_files(step))
        kind = _task_kind(action)
        read_only = kind == "read-only"
        tests_to_write = []
        execution_style = "read-only"
        if not read_only:
            execution_style = "tdd"
            tests_to_write = [f"Write a failing test covering: {title}"]
        verification_steps = []
        if action in {"run_safe_command", "execute_shell_command", "execute_python_code"}:
            verification_steps.append("Capture failing then passing output for the requested command.")
        elif read_only:
            verification_steps.append("Summarize findings without mutating repository files.")
        else:
            verification_steps.append("Run the smallest relevant test command and capture its result.")
        packet = TaskPacket(
            packet_id=str(step.get("id") or f"task_{idx}"),
            title=title,
            goal=str(objective or title),
            action=action or "chat",
            params=dict(step.get("params") or {}) if isinstance(step.get("params"), dict) else {},
            constraints=[
                "Respect the approved plan and do not expand scope.",
                "Do not modify files outside target_files unless explicitly required by the task.",
            ],
            target_files=target_files,
            exact_change=f"{title} | action={action or 'chat'}",
            tests_to_write=tests_to_write,
            verification_steps=verification_steps,
            acceptance_checks=[
                "Task output matches the approved design intent.",
                "Required verification evidence is attached.",
            ],
            scope_guard=target_files or ["No repository writes outside the assigned task."],
            review_required=True,
            handoff_template=(
                "Context: {objective}\n"
                "Task: {title}\n"
                "Target files: {target_files}\n"
                "Tests: {tests}\n"
                "Verification: {verification}\n"
                "Report spec compliance issues before code quality issues."
            ),
            specialist_hint=_specialist_hint_from_action(action, nexus_mode=nexus_mode, workflow_id=workflow_id),
            execution_style=execution_style,
        )
        packets.append(packet)
    return packets


def _specialist_hint_from_action(action: str, *, nexus_mode: str, workflow_id: str) -> str:
    low = str(action or "").strip().lower()
    if low in {"http_request", "graphql_query", "api_health_check"}:
        return "backend_architect"
    if low in {"create_web_project_scaffold"}:
        return "frontend_developer" if nexus_mode != "full" else "senior_developer"
    if low in {"run_safe_command", "execute_shell_command"}:
        return "devops_automator"
    if "api" in low or "backend" in str(workflow_id or "").lower():
        return "backend_architect"
    return "rapid_prototyper" if nexus_mode == "micro" else "senior_developer"


def render_design_markdown(
    *,
    objective: str,
    domain: str,
    workflow_profile: str,
    workflow_id: str,
    nexus_mode: str,
    capability_plan: Dict[str, Any] | None = None,
) -> str:
    quality = list((capability_plan or {}).get("quality_checklist") or [])
    tools = list((capability_plan or {}).get("preferred_tools") or [])
    lines = [
        "# Design",
        "",
        f"- Objective: {str(objective or '').strip()}",
        f"- Domain: {str(domain or 'general').strip()}",
        f"- Workflow Profile: {str(workflow_profile or 'default').strip()}",
        f"- Workflow ID: {str(workflow_id or '').strip() or '-'}",
        f"- NEXUS Mode: {str(nexus_mode or 'micro').strip()}",
        "",
        "## Intent",
        "",
        str(objective or "").strip() or "-",
        "",
        "## Success Criteria",
        "",
        "- Deliver code or implementation guidance only after explicit approval.",
        "- Keep scope aligned with the coding request.",
        "- Produce verifiable outputs and review evidence.",
        "",
        "## Constraints",
        "",
        "- No repository mutations before approval.",
        "- Tests-first unless the task is explicitly read-only or docs-only.",
        "- Use isolated workspace guidance before broad changes.",
    ]
    if quality:
        lines.extend(["", "## Quality Gates", ""])
        lines.extend(f"- {str(item)}" for item in quality[:8])
    if tools:
        lines.extend(["", "## Preferred Tools", ""])
        lines.extend(f"- {str(item)}" for item in tools[:10])
    lines.extend(
        [
            "",
            "## Approval",
            "",
            "Reply with `onay`, `go`, `uygula`, `implement`, or `devam et` to continue to the implementation plan.",
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def render_plan_markdown(*, objective: str, packets: List[TaskPacket], nexus_mode: str) -> str:
    lines = [
        "# Implementation Plan",
        "",
        f"- Objective: {str(objective or '').strip()}",
        f"- NEXUS Mode: {str(nexus_mode or 'micro').strip()}",
        f"- Task Count: {len(list(packets or []))}",
        "",
    ]
    for idx, packet in enumerate(list(packets or []), start=1):
        lines.extend(
            [
                f"## Task {idx}: {packet.title}",
                "",
                f"- Packet ID: {packet.packet_id}",
                f"- Specialist Hint: {packet.specialist_hint}",
                f"- Execution Style: {packet.execution_style}",
                f"- Exact Change: {packet.exact_change}",
                f"- Target Files: {', '.join(packet.target_files) if packet.target_files else '-'}",
                f"- Tests To Write: {', '.join(packet.tests_to_write) if packet.tests_to_write else 'N/A'}",
                f"- Verification: {', '.join(packet.verification_steps) if packet.verification_steps else '-'}",
                f"- Acceptance Checks: {', '.join(packet.acceptance_checks) if packet.acceptance_checks else '-'}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def render_review_report(
    *,
    outputs: List[Dict[str, Any]],
    notes: List[str] | None = None,
    review_status: str = "",
) -> str:
    lines = [
        "# Review Report",
        "",
        f"- Review Status: {str(review_status or 'pending').strip()}",
        "",
        "## Task Reviews",
        "",
    ]
    for row in list(outputs or []):
        if not isinstance(row, dict):
            continue
        task = str(row.get("task") or row.get("task_id") or "task").strip()
        status = str(row.get("status") or "").strip()
        validation = row.get("validation") if isinstance(row.get("validation"), dict) else {}
        failed_gates = [str(x).strip() for x in list(validation.get("failed_gates") or []) if str(x).strip()]
        lines.append(f"- {task}: {status or '-'}")
        if failed_gates:
            lines.append(f"  failed_gates={', '.join(failed_gates)}")
    if notes:
        lines.extend(["", "## Notes", ""])
        lines.extend(f"- {str(note)}" for note in list(notes or []) if str(note).strip())
    return "\n".join(lines).strip() + "\n"


def render_finish_branch_report(
    *,
    workflow_profile: str,
    workspace_mode: str,
    verified: bool,
    errors: List[str] | None = None,
) -> str:
    errors = [str(x).strip() for x in list(errors or []) if str(x).strip()]
    recommendation = "merge_or_pr" if verified and not errors else "keep_for_revision"
    if workspace_mode == "strict_worktree_required":
        recommendation = "prepare_worktree_first"
    lines = [
        "# Finish Branch Report",
        "",
        f"- Workflow Profile: {str(workflow_profile or 'default').strip()}",
        f"- Workspace Mode: {str(workspace_mode or '-').strip() or '-'}",
        f"- Verified: {'yes' if verified else 'no'}",
        f"- Recommendation: {recommendation}",
        "",
        "## Risks",
        "",
    ]
    if errors:
        lines.extend(f"- {err}" for err in errors[:20])
    else:
        lines.append("- No blocking risks recorded.")
    lines.extend(
        [
            "",
            "## Suggested Next Step",
            "",
            "- Merge/PR if all review gates passed.",
            "- Keep branch/workspace for revision if any review gate failed.",
            "- Discard only after artifact review and explicit operator decision.",
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def detect_baseline_commands(workspace_root: str) -> Dict[str, str]:
    root = Path(str(workspace_root or ".")).expanduser()
    commands: Dict[str, str] = {}
    if (root / "pyproject.toml").exists() or (root / "pytest.ini").exists():
        commands["test"] = "python -m pytest -q"
        commands["lint"] = "ruff check ."
    if (root / "package.json").exists():
        try:
            payload = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        scripts = payload.get("scripts") if isinstance(payload, dict) else {}
        if isinstance(scripts, dict):
            if "test" in scripts:
                commands["test"] = "npm test -- --runInBand"
            if "lint" in scripts:
                commands["lint"] = "npm run lint"
            if "typecheck" in scripts:
                commands["typecheck"] = "npm run typecheck"
    if not commands:
        commands["test"] = "baseline test command not detected"
    return commands


def inspect_workspace(*, current_dir: str, profile: str, run_dir: str) -> Dict[str, Any]:
    cwd = Path(str(current_dir or ".")).expanduser().resolve()
    run_root = Path(str(run_dir or cwd)).expanduser().resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    workspace_dir = run_root / "artifacts" / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    repo_root = ""
    git_dirty = False
    branch_name = ""
    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0:
            repo_root = str(Path(proc.stdout.strip()).expanduser().resolve())
            dirty = subprocess.run(
                ["git", "-C", repo_root, "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            git_dirty = bool(str(dirty.stdout or "").strip())
            branch = subprocess.run(
                ["git", "-C", repo_root, "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            branch_name = str(branch.stdout or "").strip()
    except Exception:
        repo_root = ""

    normalized = normalize_workflow_profile(profile)
    mode = "current_workspace"
    if normalized == "superpowers_strict" and repo_root:
        mode = "strict_worktree_required"
    elif repo_root and git_dirty:
        mode = "isolated_workspace"
    elif repo_root:
        mode = "git_worktree_recommended"
    else:
        mode = "isolated_workspace"

    baseline_commands = detect_baseline_commands(repo_root or str(cwd))
    baseline_text = [
        "# Baseline Check",
        "",
        f"- Timestamp: {int(time.time())}",
        f"- Repo Root: {repo_root or '-'}",
        f"- Git Dirty: {'yes' if git_dirty else 'no'}",
        f"- Branch: {branch_name or '-'}",
        "",
        "## Suggested Commands",
        "",
    ]
    baseline_text.extend(f"- {key}: {value}" for key, value in baseline_commands.items())
    baseline_path = Path(write_text_artifact(workspace_dir, "baseline_check.md", "\n".join(baseline_text).strip() + "\n"))

    report = {
        "workspace_mode": mode,
        "repo_root": repo_root,
        "git_dirty": git_dirty,
        "branch": branch_name,
        "isolated_workspace": str(workspace_dir),
        "baseline_commands": baseline_commands,
        "requires_worktree": mode == "strict_worktree_required",
        "recommended_branch": "codex/superpowers-task" if repo_root else "",
    }
    report_path = workspace_dir / "workspace_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        **report,
        "workspace_report_path": str(report_path),
        "baseline_check_path": str(baseline_path),
    }

def artifact_entry(path: str, *, artifact_type: str = "document", tool: str = "workflow_profile") -> Dict[str, Any]:
    target = Path(str(path or "")).expanduser()
    size_bytes = 0
    if target.exists():
        try:
            size_bytes = int(target.stat().st_size)
        except Exception:
            size_bytes = 0
    return {
        "path": str(target),
        "name": target.name,
        "type": artifact_type,
        "mime": "",
        "size_bytes": size_bytes,
        "sha256": "",
        "tool": tool,
        "source": "workflow_profile",
    }


__all__ = [
    "APPROVAL_MARKERS",
    "CODING_SUPERPOWERS_DOMAINS",
    "PREAPPROVAL_BLOCKED_TOOLS",
    "PhaseSpec",
    "ProcessProfile",
    "TaskPacket",
    "approval_granted",
    "artifact_entry",
    "build_task_packets",
    "detect_baseline_commands",
    "get_process_profile",
    "infer_nexus_mode",
    "inspect_workspace",
    "normalize_workflow_profile",
    "profile_applicable",
    "render_design_markdown",
    "render_finish_branch_report",
    "render_plan_markdown",
    "render_review_report",
    "write_json_artifact",
    "write_text_artifact",
]
