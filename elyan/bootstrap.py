from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from core.version import APP_VERSION
from core.workspace_contract import ensure_workspace_contract

RUNTIME_DIRS = ("browser", "logs", "memory", "projects", "sandbox", "skills")


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
    }
    if isinstance(metadata, dict):
        payload.update(metadata)
    return payload


def _agents_md(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# AGENTS",
            "",
            f"- project: {payload.get('project', '')}",
            f"- role: {payload.get('role', '')}",
            f"- created_at: {payload.get('created_at', '')}",
            "- policy: isolated workspace",
            "- trace: required",
            "- verify: required",
        ]
    ).rstrip() + "\n"


def _memory_md(payload: dict[str, Any], contract_paths: dict[str, str]) -> str:
    memory_payload = {
        "workspace": payload.get("workspace", ""),
        "project": payload.get("project", ""),
        "role": payload.get("role", ""),
        "created_at": payload.get("created_at", ""),
        "version": payload.get("version", ""),
        "contracts": contract_paths,
    }
    return "# MEMORY\n\n```json\n" + json.dumps(memory_payload, ensure_ascii=False, indent=2) + "\n```\n"


def ensure_runtime_dirs(home: str | Path | None = None) -> dict[str, str]:
    base = Path(home or (Path.home() / ".elyan")).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)

    created: dict[str, str] = {}
    for name in RUNTIME_DIRS:
        path = base / name
        path.mkdir(parents=True, exist_ok=True)
        created[name] = str(path)
    return created


def bootstrap_workspace(
    workspace_dir: str | Path | None = None,
    *,
    role: str = "operator",
    metadata: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, str]:
    workspace = Path(workspace_dir or Path.cwd()).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    ensure_runtime_dirs()
    payload = _workspace_metadata(workspace, role, metadata)
    contract_paths = ensure_workspace_contract(
        workspace,
        role=role,
        allowed_tools=["filesystem", "terminal", "browser", "dashboard"],
        metadata=payload,
    )

    agents_path = workspace / "agents.md"
    memory_path = workspace / "memory.md"

    if force or not agents_path.exists():
        agents_path.write_text(_agents_md(payload), encoding="utf-8")
    if force or not memory_path.exists():
        memory_path.write_text(_memory_md(payload, contract_paths), encoding="utf-8")

    result = {
        "workspace": str(workspace),
        "agents_md": str(agents_path),
        "memory_md": str(memory_path),
    }
    result.update(contract_paths)
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="elyan.bootstrap", description="Elyan workspace bootstrap")
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help="Create workspace contract files")
    init.add_argument("--workspace", default=".")
    init.add_argument("--role", default="operator")
    init.add_argument("--force", action="store_true")
    init.add_argument("--json", action="store_true")

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

    result = bootstrap_workspace(
        getattr(args, "workspace", "."),
        role=getattr(args, "role", "operator"),
        force=bool(getattr(args, "force", False)),
    )
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Workspace bootstrapped: {result['workspace']}")
        print(f"agents.md: {result['agents_md']}")
        print(f"memory.md: {result['memory_md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

