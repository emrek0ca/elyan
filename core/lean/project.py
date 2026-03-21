from __future__ import annotations

import json
import shlex
import uuid
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

STATE_ROOT = Path.home() / ".elyan" / "lean"
REGISTRY_FILE = STATE_ROOT / "projects.json"
SESSIONS_FILE = STATE_ROOT / "sessions.json"
GAUSS_MANIFEST = ".gauss/project.yaml"
LEAN_MARKERS = ("lean-toolchain", "lakefile.lean", "lakefile.toml", "lakefile")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ensure_state_root() -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else dict(default)
    except Exception:
        return dict(default)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_state_root()
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_registry() -> dict[str, Any]:
    return _read_json(REGISTRY_FILE, {"active_root": "", "projects": {}})


def _save_registry(payload: dict[str, Any]) -> None:
    _write_json(REGISTRY_FILE, payload)


def _load_sessions() -> dict[str, Any]:
    return _read_json(SESSIONS_FILE, {"sessions": []})


def _save_sessions(payload: dict[str, Any]) -> None:
    _write_json(SESSIONS_FILE, payload)


def _normalize_root(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    raw = str(path or "").strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve()
    except Exception:
        return None


def _safe_name(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "lean-project"
    return text.replace("_", " ").replace("-", " ").title()


def _read_simple_yaml(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or ":" not in raw:
                continue
            key, value = raw.split(":", 1)
            data[str(key).strip()] = str(value).strip().strip('"').strip("'")
    except Exception:
        return {}
    return data


def _write_simple_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key, value in data.items():
        if value is None:
            continue
        lines.append(f"{key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def detect_project_root(start: str | Path | None = None) -> Path | None:
    candidate = _normalize_root(start) or Path.cwd().resolve()
    search = [candidate]
    search.extend(candidate.parents)
    for root in search:
        if any((root / marker).exists() for marker in LEAN_MARKERS) or (root / GAUSS_MANIFEST).exists():
            return root
    return None


def resolve_project_root(path: str | Path | None = None) -> Path | None:
    root = _normalize_root(path)
    if root and root.exists():
        return detect_project_root(root) or root
    return detect_project_root(path)


def summarize_project(root: str | Path) -> dict[str, Any]:
    root_path = _normalize_root(root)
    if root_path is None:
        return {}
    manifest_path = root_path / GAUSS_MANIFEST
    manifest = _read_simple_yaml(manifest_path) if manifest_path.exists() else {}
    lean_toolchain = (root_path / "lean-toolchain").exists()
    lakefile = any((root_path / name).exists() for name in ("lakefile.lean", "lakefile.toml", "lakefile"))
    markers = {
        "lean_toolchain": lean_toolchain,
        "lakefile": lakefile,
        "gauss_manifest": manifest_path.exists(),
        "project_name": _safe_name(manifest.get("name") or root_path.name),
    }
    registry = _load_registry()
    projects = registry.get("projects", {}) if isinstance(registry.get("projects"), dict) else {}
    stored = dict(projects.get(str(root_path), {}) or {})
    active_root = str(registry.get("active_root") or "").strip()
    registered = bool(stored)
    return {
        "root": str(root_path),
        "name": str(stored.get("name") or manifest.get("name") or root_path.name),
        "kind": str(stored.get("kind") or manifest.get("kind") or "lean"),
        "active": active_root == str(root_path),
        "registered": registered,
        "status": "ready" if (lean_toolchain or lakefile or manifest_path.exists()) else "scaffolded",
        "manifest_path": str(manifest_path),
        "manifest": manifest,
        "markers": markers,
        "toolchain": (root_path / "lean-toolchain").read_text(encoding="utf-8").strip() if lean_toolchain else "",
        "lakefiles": [name for name in ("lakefile.lean", "lakefile.toml", "lakefile") if (root_path / name).exists()],
        "updated_at": str(stored.get("updated_at") or manifest.get("updated_at") or ""),
        "created_at": str(stored.get("created_at") or manifest.get("created_at") or ""),
        "source": str(stored.get("source") or manifest.get("source") or ""),
    }


def _project_payload(root: Path, *, name: str = "", kind: str = "lean", source: str = "auto") -> dict[str, Any]:
    summary = summarize_project(root)
    title = _safe_name(name or summary.get("name") or root.name)
    payload = {
        "name": title,
        "kind": kind,
        "root": str(root),
        "source": source,
        "status": summary.get("status") or "scaffolded",
        "markers": summary.get("markers") or {},
        "manifest_path": summary.get("manifest_path") or str(root / GAUSS_MANIFEST),
        "created_at": summary.get("created_at") or _now_iso(),
        "updated_at": _now_iso(),
    }
    return payload


def register_project(
    root: str | Path,
    *,
    name: str = "",
    kind: str = "lean",
    source: str = "auto",
    activate: bool = True,
    create_manifest: bool = True,
) -> dict[str, Any]:
    root_path = _normalize_root(root)
    if root_path is None:
        raise ValueError("project root is required")
    root_path.mkdir(parents=True, exist_ok=True)
    payload = _project_payload(root_path, name=name, kind=kind, source=source)
    if create_manifest:
        _write_simple_yaml(
            root_path / GAUSS_MANIFEST,
            {
                "name": payload["name"],
                "kind": payload["kind"],
                "root": payload["root"],
                "source": payload["source"],
                "created_at": payload["created_at"],
                "updated_at": payload["updated_at"],
            },
        )
    registry = _load_registry()
    projects = registry.get("projects", {}) if isinstance(registry.get("projects"), dict) else {}
    projects[str(root_path)] = payload
    registry["projects"] = projects
    if activate or not str(registry.get("active_root") or "").strip():
        registry["active_root"] = str(root_path)
    registry["updated_at"] = _now_iso()
    _save_registry(registry)
    return summarize_project(root_path)


def set_active_project(root: str | Path | None) -> dict[str, Any]:
    registry = _load_registry()
    root_path = _normalize_root(root)
    registry["active_root"] = str(root_path) if root_path else ""
    registry["updated_at"] = _now_iso()
    _save_registry(registry)
    return get_active_project()


def get_active_project() -> dict[str, Any]:
    registry = _load_registry()
    active = _normalize_root(registry.get("active_root"))
    if active and active.exists():
        return summarize_project(active)
    detected = detect_project_root()
    if detected:
        return summarize_project(detected)
    return {}


def list_projects() -> list[dict[str, Any]]:
    registry = _load_registry()
    projects = registry.get("projects", {}) if isinstance(registry.get("projects"), dict) else {}
    rows = [summarize_project(root) for root in projects.keys()]
    rows.sort(key=lambda item: (not bool(item.get("active")), str(item.get("name") or "").lower()))
    return rows


def list_workflow_sessions(root: str | Path | None = None) -> list[dict[str, Any]]:
    sessions = _load_sessions()
    rows = list(sessions.get("sessions", [])) if isinstance(sessions.get("sessions"), list) else []
    root_text = str(_normalize_root(root) or "").strip()
    if root_text:
        rows = [row for row in rows if str((row or {}).get("project_root") or "") == root_text]
    rows.sort(key=lambda item: str((item or {}).get("updated_at") or (item or {}).get("created_at") or ""), reverse=True)
    return [dict(row) for row in rows]


def record_workflow_session(
    action: str,
    *,
    project_root: str | Path,
    project_name: str = "",
    prompt: str = "",
    goal: str = "",
    target: str = "",
    backend: str = "auto",
    command: str = "",
    status: str = "planned",
    result: dict[str, Any] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    root_path = _normalize_root(project_root)
    if root_path is None:
        raise ValueError("project root is required")
    sessions = _load_sessions()
    rows = list(sessions.get("sessions", [])) if isinstance(sessions.get("sessions"), list) else []
    workflow_id = f"lean_{action}_{uuid.uuid4().hex[:10]}"
    now = _now_iso()
    session = {
        "workflow_id": workflow_id,
        "action": str(action or "workflow").strip().lower() or "workflow",
        "project_root": str(root_path),
        "project_name": str(project_name or root_path.name),
        "prompt": str(prompt or ""),
        "goal": str(goal or ""),
        "target": str(target or ""),
        "backend": str(backend or "auto"),
        "command": str(command or ""),
        "status": str(status or "planned"),
        "result": dict(result or {}),
        "notes": list(notes or []),
        "created_at": now,
        "updated_at": now,
    }
    rows = [row for row in rows if str((row or {}).get("workflow_id") or "") != workflow_id]
    rows.append(session)
    sessions["sessions"] = rows
    sessions["updated_at"] = now
    _save_sessions(sessions)
    return session


def update_workflow_session(workflow_id: str, **fields: Any) -> dict[str, Any]:
    target = str(workflow_id or "").strip()
    if not target:
        raise ValueError("workflow_id is required")
    sessions = _load_sessions()
    rows = list(sessions.get("sessions", [])) if isinstance(sessions.get("sessions"), list) else []
    updated: dict[str, Any] | None = None
    now = _now_iso()
    for row in rows:
        if str((row or {}).get("workflow_id") or "") == target:
            row.update({k: v for k, v in fields.items() if v is not None})
            row["updated_at"] = now
            updated = dict(row)
            break
    if updated is None:
        return {}
    sessions["sessions"] = rows
    sessions["updated_at"] = now
    _save_sessions(sessions)
    return updated


def build_lean_prompt(
    action: str,
    *,
    project: dict[str, Any],
    goal: str = "",
    target: str = "",
    backend: str = "auto",
) -> str:
    root = str(project.get("root") or "").strip()
    name = str(project.get("name") or Path(root).name or "Lean project").strip()
    action_text = str(action or "workflow").strip().lower() or "workflow"
    lines = [
        "You are Elyan's Lean 4 operator.",
        f"Project: {name}",
        f"Project root: {root}",
        f"Workflow: {action_text}",
        f"Backend: {backend}",
    ]
    if goal:
        lines.append(f"Goal: {goal}")
    if target:
        lines.append(f"Target: {target}")
    lines.extend(
        [
            "Use project-scoped Lean tooling and keep edits minimal.",
            "Prefer typechecked proofs, explicit theorem names, and compact lemmas.",
            "Return a concise proof plan, verification output, and next action.",
        ]
    )
    return "\n".join(lines)


def build_workflow_bundle(
    action: str,
    *,
    project: dict[str, Any],
    goal: str = "",
    target: str = "",
    backend: str = "auto",
) -> dict[str, Any]:
    root = str(project.get("root") or "").strip()
    bundle_id = f"lean_{str(action or 'workflow').strip().lower() or 'workflow'}"
    prompt = build_lean_prompt(action, project=project, goal=goal, target=target, backend=backend)
    command = build_lean_command(action, root=root, target=target)
    steps = [
        {
            "id": "inspect_project",
            "action": "lean_project",
            "params": {"action": "status", "path": root},
        },
        {
            "id": "verify_toolchain",
            "action": "lean_status",
            "params": {"path": root},
        },
        {
            "id": "run_workflow",
            "action": "lean_workflow",
            "params": {
                "action": action,
                "path": root,
                "goal": goal,
                "target": target,
                "backend": backend,
            },
        },
    ]
    return {
        "id": bundle_id,
        "name": f"Lean {str(action or 'workflow').strip().title()}",
        "category": "formal_methods",
        "required_skills": ["lean", "files", "research"],
        "required_tools": ["lean_status", "lean_project", "lean_workflow", "lean_swarm"],
        "steps": steps,
        "trigger_markers": ["lean", "mathlib", "theorem", "lemma", "prove", "formalize"],
        "objective": "project_scoped_lean_formalization",
        "prompt": prompt,
        "command": command,
        "project_root": root,
        "project_name": str(project.get("name") or ""),
        "output_artifacts": ["lean_project_manifest", "proof_trace", "build_log"],
        "quality_checklist": ["typecheck", "traceability", "project_scope", "reproducibility"],
        "auto_intent": str(action or "").strip().lower() in {"prove", "autoprove", "formalize", "autoformalize"},
    }


def build_lean_command(action: str, *, root: str, target: str = "") -> str:
    root_text = str(root or "").strip()
    if not root_text:
        return ""
    quoted_root = shlex.quote(root_text)
    target_text = str(target or "").strip()
    action_text = str(action or "").strip().lower()
    if action_text == "status":
        return f"cd {quoted_root} && (lean --version || lake --version)"
    if target_text:
        target_path = Path(target_text)
        if not target_path.is_absolute():
            target_path = Path(root_text) / target_path
        return f"cd {quoted_root} && lake env lean {shlex.quote(str(target_path))}"
    if action_text in {"prove", "autoprove", "formalize", "autoformalize"}:
        return f"cd {quoted_root} && lake build"
    return f"cd {quoted_root} && lake build"
