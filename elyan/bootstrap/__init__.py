from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from core.version import APP_VERSION
from core.workspace_contract import ensure_workspace_contract

from .dependencies import DependencyManager

RUNTIME_DIRS = ("browser", "logs", "memory", "mcp", "projects", "sandbox", "services", "skills")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _workspace_metadata(workspace: Path, role: str, metadata: dict[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project": workspace.name,
        "workspace": str(workspace),
        "role": role,
        "created_at": _now(),
        "version": APP_VERSION,
        "source": "elyan-bootstrap",
        "enabled_skills": ["browser", "desktop", "calendar"],
        "default_models": {
            "vision": "qwen2.5vl:7b",
            "reasoning": "llama3.2",
        },
    }
    if isinstance(metadata, dict):
        payload.update(metadata)
    return payload


def _agents_md(payload: dict[str, Any]) -> str:
    skills = ", ".join(payload.get("enabled_skills", []) or ["browser", "desktop", "calendar"])
    return (
        "# Elyan Agents\n\n"
        "## Operating Rules\n"
        "- Trace required before completion.\n"
        "- Verify every side effect.\n"
        "- Ask approval for destructive actions.\n"
        "- Keep work local-first unless an integration is required.\n\n"
        "## Seed Task\n"
        "- Hey Elyan, bugun ne yapayim?\n"
        "- Inspect the last 24 hours, summarize priorities, and report the result in Turkish.\n"
        "- If a browser, desktop, or calendar action is needed, use the enabled skills.\n\n"
        "## Enabled Skills\n"
        f"- {skills}\n"
    ).rstrip() + "\n"


def _memory_md(payload: dict[str, Any], contract_paths: dict[str, str]) -> str:
    memory_payload = {
        "workspace": payload.get("workspace", ""),
        "project": payload.get("project", ""),
        "role": payload.get("role", ""),
        "created_at": payload.get("created_at", ""),
        "version": payload.get("version", ""),
        "source": payload.get("source", ""),
        "enabled_skills": list(payload.get("enabled_skills", []) or []),
        "default_models": dict(payload.get("default_models", {}) or {}),
        "contracts": contract_paths,
        "preferences": {
            "language": "tr",
            "local_first": True,
            "trace_required": True,
        },
        "seed_task": "Hey Elyan, bugun ne yapayim?",
    }
    return (
        "# Elyan Memory\n\n"
        "## Preferences\n"
        "- Turkish responses by default.\n"
        "- Local-first execution.\n"
        "- Evidence before completion.\n\n"
        "## Seed State\n"
        "```json\n"
        + json.dumps(memory_payload, ensure_ascii=False, indent=2)
        + "\n```\n"
    )


def ensure_runtime_dirs(home: str | Path | None = None) -> dict[str, str]:
    base = Path(home or (Path.home() / ".elyan")).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)

    created: dict[str, str] = {}
    for name in RUNTIME_DIRS:
        path = base / name
        path.mkdir(parents=True, exist_ok=True)
        created[name] = str(path)
    return created


def init_workspace(
    workspace: str | Path | None = None,
    *,
    role: str = "operator",
    metadata: dict[str, Any] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    workspace_path = Path(workspace or Path.cwd()).expanduser().resolve()
    workspace_path.mkdir(parents=True, exist_ok=True)

    if not dry_run:
        ensure_runtime_dirs()

    os.environ.setdefault("ELYAN_PROJECT_DIR", str(workspace_path))
    payload = _workspace_metadata(workspace_path, role, metadata)
    contract_paths = ensure_workspace_contract(
        workspace_path,
        role=role,
        allowed_tools=["filesystem", "terminal", "browser", "dashboard", "screenpipe", "ollama", "desktop", "calendar"],
        metadata=payload,
    )

    agents_path = workspace_path / "agents.md"
    memory_path = workspace_path / "memory.md"

    if force or not agents_path.exists():
        agents_path.write_text(_agents_md(payload), encoding="utf-8")
    if force or not memory_path.exists():
        memory_path.write_text(_memory_md(payload, contract_paths), encoding="utf-8")

    result: dict[str, Any] = {
        "workspace": str(workspace_path),
        "agents_md": str(agents_path),
        "memory_md": str(memory_path),
    }
    result.update(contract_paths)
    return result


def init(
    workspace: str | Path | None = None,
    *,
    role: str = "operator",
    metadata: dict[str, Any] | None = None,
    force: bool = False,
    headless: bool = False,
    open_dashboard: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    workspace_result = init_workspace(
        workspace,
        role=role,
        metadata=metadata,
        force=force,
        dry_run=dry_run,
    )
    workspace_path = Path(workspace_result["workspace"])
    agents_path = Path(workspace_result["agents_md"])
    memory_path = Path(workspace_result["memory_md"])

    dependency_manager = DependencyManager(
        workspace=workspace_path,
        headless=headless,
        open_dashboard=open_dashboard,
        dry_run=dry_run,
    )
    dependency_summary = dependency_manager.bootstrap_all()

    result: dict[str, Any] = dict(workspace_result)
    result["dependencies"] = dependency_summary
    return result


def bootstrap_workspace(
    workspace_dir: str | Path | None = None,
    *,
    role: str = "operator",
    metadata: dict[str, Any] | None = None,
    force: bool = False,
    headless: bool = False,
    open_dashboard: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    return init(
        workspace_dir,
        role=role,
        metadata=metadata,
        force=force,
        headless=headless,
        open_dashboard=open_dashboard,
        dry_run=dry_run,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="elyan.bootstrap", description="Elyan workspace bootstrap")
    sub = parser.add_subparsers(dest="command")

    init_parser = sub.add_parser("init", help="Create workspace contract files and first-run dependencies")
    init_parser.add_argument("--workspace", default=".")
    init_parser.add_argument("--role", default="operator")
    init_parser.add_argument("--force", action="store_true")
    init_parser.add_argument("--headless", action="store_true")
    init_parser.add_argument("--open-dashboard", action="store_true")
    init_parser.add_argument("--dry-run", action="store_true")
    init_parser.add_argument("--json", action="store_true")

    onboard_parser = sub.add_parser("onboard", help="Run the unified onboarding flow")
    onboard_parser.add_argument("--workspace", default=".")
    onboard_parser.add_argument("--role", default="operator")
    onboard_parser.add_argument("--force", action="store_true")
    onboard_parser.add_argument("--headless", action="store_true")
    onboard_parser.add_argument("--open-dashboard", action="store_true")
    onboard_parser.add_argument("--no-dashboard", action="store_true")
    onboard_parser.add_argument("--skip-deps", action="store_true")
    onboard_parser.add_argument("--channel", default=None)
    onboard_parser.add_argument("--install-daemon", action="store_true")
    onboard_parser.add_argument("--dry-run", action="store_true")
    onboard_parser.add_argument("--json", action="store_true")
    onboard_parser.set_defaults(open_dashboard=True)

    dirs = sub.add_parser("dirs", help="Create ~/.elyan runtime directories")
    dirs.add_argument("--home", default=str(Path.home() / ".elyan"))
    dirs.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    command = str(getattr(args, "command", "") or "init").strip().lower()
    if command == "dirs":
        result = ensure_runtime_dirs(getattr(args, "home", None))
        if getattr(args, "json", False):
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Runtime dirs ready: {getattr(args, 'home', '')}")
        return 0

    if command == "onboard":
        from .onboard import onboard

        open_dashboard = bool(getattr(args, "open_dashboard", True)) and not bool(getattr(args, "no_dashboard", False))
        result = onboard(
            workspace=getattr(args, "workspace", "."),
            role=getattr(args, "role", "operator"),
            headless=bool(getattr(args, "headless", False)),
            channel=getattr(args, "channel", None),
            install_daemon=bool(getattr(args, "install_daemon", False)),
            force=bool(getattr(args, "force", False)),
            dry_run=bool(getattr(args, "dry_run", False)),
            open_dashboard=open_dashboard,
            skip_dependencies=bool(getattr(args, "skip_deps", False)),
        )
        if getattr(args, "json", False):
            print(json.dumps({"ok": bool(result)}, ensure_ascii=False, indent=2))
        return 0 if result else 1

    result = bootstrap_workspace(
        getattr(args, "workspace", "."),
        role=getattr(args, "role", "operator"),
        force=bool(getattr(args, "force", False)),
        headless=bool(getattr(args, "headless", False)),
        open_dashboard=bool(getattr(args, "open_dashboard", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Workspace bootstrapped: {result['workspace']}")
        print(f"agents.md: {result['agents_md']}")
        print(f"memory.md: {result['memory_md']}")
        deps = result.get("dependencies", {}) if isinstance(result.get("dependencies"), dict) else {}
        if deps:
            steps = ", ".join(f"{name}={'ok' if isinstance(step, dict) and step.get('ok') else 'skip'}" for name, step in deps.items())
            if steps:
                print(f"Dependencies: {steps}")
    return 0


__all__ = [
    "bootstrap_workspace",
    "ensure_runtime_dirs",
    "init_workspace",
    "init",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
