"""
Runtime Security Guard

Centralized enforcement for:
- RBAC role checks
- operator autonomy policy
- command/path safety checks
- runtime risk classification
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple

from config.elyan_config import elyan_config
from core.command_hardening import blocked_command_reason
from core.operator_policy import get_operator_policy_engine
from core.security.contracts import decision_for
from core.security.rbac import Role, rbac


RUNTIME_ACTIONS = {
    "run_command",
    "run_safe_command",
    "execute_command",
    "execute_shell_command",
    "execute_python_code",
    "open_app",
    "close_app",
    "type_text",
    "press_key",
    "key_combo",
    "mouse_move",
    "mouse_click",
    "computer_use",
    "kill_process",
    "shutdown_system",
    "restart_system",
}

SYSTEM_ACTIONS = {
    "run_command",
    "run_safe_command",
    "execute_command",
    "execute_shell_command",
    "kill_process",
    "shutdown_system",
    "restart_system",
    "open_app",
    "close_app",
    "type_text",
    "press_key",
    "key_combo",
    "mouse_move",
    "mouse_click",
    "computer_use",
}

DESTRUCTIVE_ACTIONS = {
    "delete_file",
    "format_disk",
    "shutdown_system",
    "restart_system",
    "kill_process",
}

WRITE_ACTIONS = {
    "write_file",
    "replace_in_file",
    "edit_text_file",
    "append_file",
    "delete_file",
    "move_file",
    "copy_file",
    "rename_file",
    "create_folder",
    "write_word",
    "write_excel",
    "create_web_project_scaffold",
    "create_software_project_pack",
    "create_coding_project",
    "create_coding_delivery_plan",
    "create_coding_verification_report",
}

PATH_KEYS = {
    "path",
    "file_path",
    "output_path",
    "source",
    "destination",
    "directory",
    "dir",
    "cwd",
    "workspace",
    "workspace_dir",
    "image_path",
}

DEFAULT_DANGEROUS_PATTERNS = [
    "rm -rf",
    "mkfs",
    "dd if=",
    "shutdown -h",
    "reboot",
    "kill -9 1",
    ":(){:|:&};:",
]

DEFAULT_MUTATION_COMMAND_PATTERNS = [
    ">",
    ">>",
    " tee ",
    "touch ",
    "mkdir ",
    "cp ",
    "mv ",
    "rm ",
    "sed -i",
]


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


@lru_cache(maxsize=256)
def _pattern_to_regex(token: str) -> re.Pattern[str]:
    # Convert command marker into whitespace-tolerant case-insensitive regex.
    escaped = re.escape(token or "")
    escaped = escaped.replace(r"\ ", r"\s+")
    return re.compile(escaped, flags=re.IGNORECASE)


def _to_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _merge_list(primary: Any, fallback: Any) -> List[str]:
    merged: List[str] = []
    for item in _to_list(primary) + _to_list(fallback):
        if item not in merged:
            merged.append(item)
    return merged


@dataclass
class GuardProfile:
    operator_mode: str
    enforce_rbac: bool
    default_user_role: str
    path_guard_enabled: bool
    allowed_roots: List[str]
    denied_roots: List[str]
    dangerous_command_patterns: List[str]
    dangerous_tools_enabled: bool
    require_evidence_for_dangerous: bool
    require_confirmation_for_risky: bool


class RuntimeSecurityGuard:
    @staticmethod
    def _map_legacy_risk(legacy_risk: str) -> str:
        token = str(legacy_risk or "").strip().lower()
        if token == "dangerous":
            return "destructive"
        if token == "guarded":
            return "write_safe"
        return "read_only"

    def _decision_payload(
        self,
        *,
        allowed: bool,
        requires_approval: bool,
        legacy_risk: str,
        reason: str,
        profile: GuardProfile,
        data: Any = None,
    ) -> Dict[str, Any]:
        payload = decision_for(
            allowed=allowed,
            requires_approval=requires_approval,
            risk_level=self._map_legacy_risk(legacy_risk),
            legacy_risk=legacy_risk,
            data=data,
            reason=reason,
            source="runtime_guard",
        ).to_dict()
        payload["profile"] = profile
        return payload

    def _resolve_profile(self, runtime_policy: Dict[str, Any] | None = None) -> GuardProfile:
        policy = runtime_policy if isinstance(runtime_policy, dict) else {}
        security = policy.get("security", {}) if isinstance(policy.get("security"), dict) else {}

        cfg_operator_mode = str(elyan_config.get("security.operatorMode", "Confirmed") or "Confirmed")
        cfg_role = str(elyan_config.get("security.defaultUserRole", "operator") or "operator").strip().lower()
        cfg_enforce_rbac = bool(elyan_config.get("security.enforceRBAC", True))
        cfg_path_guard = bool(elyan_config.get("security.pathGuard.enabled", True))
        cfg_allowed = _to_list(
            elyan_config.get(
                "security.pathGuard.allowedRoots",
                [str(Path.home()), "/tmp", "/private", "/var/tmp", "/var/folders", str(Path.home() / ".elyan")],
            )
        )
        cfg_denied = _to_list(elyan_config.get("security.pathGuard.deniedRoots", ["/System", "/usr", "/bin", "/sbin", "/etc", "/var/root"]))
        cfg_patterns = _to_list(elyan_config.get("security.dangerousCommandPatterns", DEFAULT_DANGEROUS_PATTERNS))
        cfg_dangerous_tools_enabled = bool(elyan_config.get("security.enableDangerousTools", True))
        cfg_require_evidence = bool(elyan_config.get("security.requireEvidenceForDangerous", True))
        cfg_require_confirm = bool(elyan_config.get("security.requireConfirmationForRisky", True))

        operator_mode = str(security.get("operator_mode", cfg_operator_mode) or cfg_operator_mode)
        default_role = str(security.get("default_user_role", cfg_role) or cfg_role).strip().lower()
        if default_role not in {Role.ADMIN, Role.OPERATOR, Role.VIEWER}:
            default_role = cfg_role if cfg_role in {Role.ADMIN, Role.OPERATOR, Role.VIEWER} else Role.OPERATOR

        enforce_rbac = bool(security.get("enforce_rbac", cfg_enforce_rbac))
        path_guard_enabled = bool(security.get("path_guard_enabled", cfg_path_guard))
        allowed_roots = _merge_list(security.get("allowed_roots"), cfg_allowed)
        denied_roots = _merge_list(security.get("denied_roots"), cfg_denied)
        dangerous_patterns = _merge_list(security.get("dangerous_command_patterns"), cfg_patterns)
        dangerous_tools_enabled = bool(security.get("dangerous_tools_enabled", cfg_dangerous_tools_enabled))
        require_evidence = bool(security.get("require_evidence_for_dangerous", cfg_require_evidence))
        require_confirm = bool(security.get("require_confirmation_for_risky", cfg_require_confirm))

        return GuardProfile(
            operator_mode=operator_mode,
            enforce_rbac=enforce_rbac,
            default_user_role=default_role,
            path_guard_enabled=path_guard_enabled,
            allowed_roots=allowed_roots,
            denied_roots=denied_roots,
            dangerous_command_patterns=dangerous_patterns or list(DEFAULT_DANGEROUS_PATTERNS),
            dangerous_tools_enabled=dangerous_tools_enabled,
            require_evidence_for_dangerous=require_evidence,
            require_confirmation_for_risky=require_confirm,
        )

    @staticmethod
    def classify_risk(tool_name: str) -> str:
        tool = str(tool_name or "").strip().lower()
        if tool in DESTRUCTIVE_ACTIONS:
            return "dangerous"
        if tool in SYSTEM_ACTIONS:
            return "guarded"
        if tool in RUNTIME_ACTIONS:
            return "guarded"
        return "safe"

    @staticmethod
    def _normalize_path(raw_path: str) -> Path | None:
        value = str(raw_path or "").strip()
        if not value:
            return None
        if any(ord(ch) < 32 for ch in value):
            return None
        if "://" in value:
            return None
        try:
            p = Path(value).expanduser()
            if not p.is_absolute():
                p = (Path.home() / p).resolve()
            else:
                p = p.resolve()
            return p
        except Exception:
            return None

    @staticmethod
    def _path_under(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except Exception:
            return False

    def _collect_paths(self, params: Dict[str, Any]) -> Tuple[List[Path], List[str]]:
        out: List[Path] = []
        invalid: List[str] = []
        for key, value in (params or {}).items():
            k = str(key or "").strip().lower()
            if k in PATH_KEYS or "path" in k or k.endswith("_dir") or k == "cwd":
                if isinstance(value, str):
                    p = self._normalize_path(value)
                    if p is not None:
                        out.append(p)
                    elif value.strip():
                        invalid.append(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            p = self._normalize_path(item)
                            if p is not None:
                                out.append(p)
                            elif item.strip():
                                invalid.append(item)
        dedup: List[Path] = []
        seen = set()
        for p in out:
            s = str(p)
            if s in seen:
                continue
            seen.add(s)
            dedup.append(p)
        invalid_dedup: List[str] = []
        seen_invalid = set()
        for raw in invalid:
            if raw in seen_invalid:
                continue
            seen_invalid.add(raw)
            invalid_dedup.append(raw)
        return dedup, invalid_dedup

    @staticmethod
    def _extract_command(params: Dict[str, Any]) -> str:
        for key in ("command", "cmd", "shell_command", "code"):
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _looks_like_write_mutation(tool_name: str, params: Dict[str, Any]) -> bool:
        tool = str(tool_name or "").strip().lower()
        if tool in WRITE_ACTIONS:
            return True
        if tool not in RUNTIME_ACTIONS:
            return False
        compact = f" {_collapse_whitespace(RuntimeSecurityGuard._extract_command(params or {})).lower()} "
        if not compact.strip():
            return False
        return any(marker in compact for marker in DEFAULT_MUTATION_COMMAND_PATTERNS)

    def evaluate(
        self,
        *,
        tool_name: str,
        params: Dict[str, Any],
        user_id: str,
        runtime_policy: Dict[str, Any] | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        profile = self._resolve_profile(runtime_policy)
        tool = str(tool_name or "").strip()
        uid = str(user_id or "unknown").strip() or "unknown"
        meta = metadata if isinstance(metadata, dict) else {}
        risk = self.classify_risk(tool)

        unsupported_reason = blocked_command_reason(str(meta.get("user_input") or ""), tool_name=tool)
        if unsupported_reason and tool in RUNTIME_ACTIONS.union(SYSTEM_ACTIONS):
            return self._decision_payload(
                allowed=False,
                requires_approval=False,
                legacy_risk="dangerous",
                reason=unsupported_reason,
                profile=profile,
                data=params,
            )

        # RBAC
        role = str(meta.get("user_role", profile.default_user_role) or profile.default_user_role).strip().lower()
        if role not in {Role.ADMIN, Role.OPERATOR, Role.VIEWER}:
            role = profile.default_user_role
        try:
            rbac.set_role(uid, role)
        except Exception:
            pass
        if profile.enforce_rbac:
            has_perm = bool(rbac.check_permission(uid, tool))
            # Viewer: strict allow-list.
            if role == Role.VIEWER and not has_perm:
                return self._decision_payload(
                    allowed=False,
                    requires_approval=False,
                    legacy_risk=risk,
                    reason=f"RBAC blocked for role '{role}': {tool}",
                    profile=profile,
                    data=params,
                )

        # Operator mode
        op_policy = get_operator_policy_engine().resolve(profile.operator_mode)
        if tool in SYSTEM_ACTIONS and not op_policy.allow_system_actions:
            return self._decision_payload(
                allowed=False,
                requires_approval=False,
                legacy_risk=risk,
                reason=f"Operator policy '{op_policy.level}' blocks system actions",
                profile=profile,
                data=params,
            )
        if tool in DESTRUCTIVE_ACTIONS and not op_policy.allow_destructive_actions:
            return self._decision_payload(
                allowed=False,
                requires_approval=False,
                legacy_risk=risk,
                reason=f"Operator policy '{op_policy.level}' blocks destructive actions",
                profile=profile,
                data=params,
            )
        if risk == "dangerous" and not profile.dangerous_tools_enabled:
            return self._decision_payload(
                allowed=False,
                requires_approval=False,
                legacy_risk=risk,
                reason="Dangerous tools are disabled by runtime security policy",
                profile=profile,
                data=params,
            )

        # Command guard
        cmd = self._extract_command(params or {})
        if cmd and tool in RUNTIME_ACTIONS:
            compact = _collapse_whitespace(cmd)
            for marker in profile.dangerous_command_patterns:
                token = str(marker or "").strip()
                if not token:
                    continue
                if _pattern_to_regex(token).search(compact):
                    return self._decision_payload(
                        allowed=False,
                        requires_approval=False,
                        legacy_risk="dangerous",
                        reason=f"Dangerous command pattern blocked: {token.lower()}",
                        profile=profile,
                        data=params,
                    )

        paths, invalid_paths = self._collect_paths(params or {})

        # Path guard
        if profile.path_guard_enabled:
            if invalid_paths:
                sample = invalid_paths[0]
                return self._decision_payload(
                    allowed=False,
                    requires_approval=False,
                    legacy_risk=risk,
                    reason=f"Invalid path-like parameter blocked: {sample}",
                    profile=profile,
                    data=params,
                )
            allowed_roots = [self._normalize_path(v) for v in profile.allowed_roots]
            denied_roots = [self._normalize_path(v) for v in profile.denied_roots]
            allowed_roots = [p for p in allowed_roots if p is not None]
            denied_roots = [p for p in denied_roots if p is not None]

            for p in paths:
                if any(self._path_under(p, root) for root in denied_roots):
                    return self._decision_payload(
                        allowed=False,
                        requires_approval=False,
                        legacy_risk=risk,
                        reason=f"Path guard denied: {p}",
                        profile=profile,
                        data={"path": str(p)},
                    )
                if allowed_roots and not any(self._path_under(p, root) for root in allowed_roots):
                    return self._decision_payload(
                        allowed=False,
                        requires_approval=False,
                        legacy_risk=risk,
                        reason=f"Path is outside allowed roots: {p}",
                        profile=profile,
                        data={"path": str(p)},
                    )

        # Contract-first coding write scope guard
        if self._looks_like_write_mutation(tool, params or {}):
            write_allowed = [self._normalize_path(v) for v in _to_list(meta.get("allowed_write_paths"))]
            write_forbidden = [self._normalize_path(v) for v in _to_list(meta.get("forbidden_write_paths"))]
            write_allowed = [p for p in write_allowed if p is not None]
            write_forbidden = [p for p in write_forbidden if p is not None]
            if meta.get("contract_first_coding") and not write_allowed:
                return self._decision_payload(
                    allowed=False,
                    requires_approval=False,
                    legacy_risk="dangerous",
                    reason="Coding runtime write scope missing.",
                    profile=profile,
                    data=params,
                )
            if tool in RUNTIME_ACTIONS and self._looks_like_write_mutation(tool, params or {}) and not paths:
                cwd_value = self._normalize_path(str((params or {}).get("cwd") or ""))
                if cwd_value is not None:
                    paths = [cwd_value]
                elif meta.get("contract_first_coding"):
                    return self._decision_payload(
                        allowed=False,
                        requires_approval=False,
                        legacy_risk="dangerous",
                        reason="Mutating command requires an explicit scoped path or cwd.",
                        profile=profile,
                        data=params,
                    )
            for p in paths:
                if any(self._path_under(p, root) for root in write_forbidden):
                    return self._decision_payload(
                        allowed=False,
                        requires_approval=False,
                        legacy_risk="dangerous",
                        reason=f"Write scope denied: {p}",
                        profile=profile,
                        data={"path": str(p)},
                    )
                if write_allowed and not any(self._path_under(p, root) for root in write_allowed):
                    return self._decision_payload(
                        allowed=False,
                        requires_approval=False,
                        legacy_risk="dangerous",
                        reason=f"Path is outside coding write scope: {p}",
                        profile=profile,
                        data={"path": str(p)},
                    )

        has_runtime_policy = isinstance(runtime_policy, dict) and bool(runtime_policy)
        approval_scope = "dangerous_only"
        try:
            security_cfg = runtime_policy.get("security", {}) if isinstance(runtime_policy, dict) and isinstance(runtime_policy.get("security"), dict) else {}
            approval_scope = str(security_cfg.get("approval_scope") or "dangerous_only").strip().lower()
        except Exception:
            approval_scope = "dangerous_only"
        risky_match = risk == "dangerous" if approval_scope != "all_risky" else risk in {"guarded", "dangerous"}
        needs_confirmation = bool(
            has_runtime_policy
            and profile.require_confirmation_for_risky
            and risky_match
            and role != Role.ADMIN
        )
        needs_policy_confirmation = bool(
            has_runtime_policy
            and op_policy.require_confirmation_for_risky
            and risky_match
        )
        requires_approval = bool(needs_confirmation or needs_policy_confirmation)

        return self._decision_payload(
            allowed=True,
            requires_approval=requires_approval,
            legacy_risk=risk,
            reason="ok",
            profile=profile,
            data=params,
        )


runtime_security_guard = RuntimeSecurityGuard()
