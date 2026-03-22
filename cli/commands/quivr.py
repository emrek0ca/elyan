from __future__ import annotations

import asyncio
import json
from typing import Any

from tools.quivr_tools import quivr_brain_ask, quivr_project, quivr_scaffold, quivr_status


def _print(payload: dict[str, Any], *, as_json: bool = False) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if bool(payload.get("success", False)) else 1
    status = str(payload.get("status") or "ok")
    if payload.get("success", False):
        print(f"Quivr: {status}")
    else:
        print(f"Quivr hata: {payload.get('error') or status}")
    project = payload.get("project") or {}
    if project:
        print(f"Project: {project.get('name') or '-'} ({project.get('root') or '-'})")
    bundle = payload.get("bundle") or payload.get("workflow") or {}
    if bundle:
        print(f"Bundle: {bundle.get('id') or bundle.get('workflow_id') or '-'}")
    message = str(payload.get("message") or "").strip()
    if message:
        print(message)
    return 0 if bool(payload.get("success", False)) else 1


def _run(coro):
    return asyncio.run(coro)


def run(args) -> int:
    action = str(getattr(args, "action", "") or "status").strip().lower() or "status"
    path = str(getattr(args, "path", "") or "").strip()
    text = " ".join(str(item) for item in list(getattr(args, "text", []) or []) if str(item).strip()).strip()
    json_mode = bool(getattr(args, "json", False))
    backend = str(getattr(args, "backend", "auto") or "auto").strip() or "auto"
    name = str(getattr(args, "name", "") or "").strip()
    question = str(getattr(args, "question", "") or "").strip() or text
    retrieval_config = str(getattr(args, "retrieval_config", "") or "").strip()
    file_paths = [str(item).strip() for item in list(getattr(args, "file_paths", []) or []) if str(item).strip()]
    include_samples = bool(getattr(args, "include_samples", True))
    force = bool(getattr(args, "force", False))
    dry_run = bool(getattr(args, "dry_run", False))
    use_llm = bool(getattr(args, "use_llm", False))

    if action == "status":
        return _print(_run(quivr_status(path=path)), as_json=json_mode)

    if action == "project":
        root = path
        project = _run(quivr_status(path=root))
        if project.get("success"):
            return _print(project, as_json=json_mode)
        return _print(
            _run(
                quivr_project(
                    action="scaffold",
                    path=path,
                    name=name or text,
                    include_samples=include_samples,
                    force=force,
                    dry_run=dry_run,
                )
            ),
            as_json=json_mode,
        )

    if action in {"scaffold", "bundle", "workflow"}:
        project_action = "scaffold" if action == "scaffold" else "workflow"
        return _print(
            _run(
                quivr_project(
                    action=project_action,
                    path=path,
                    name=name or text,
                    backend=backend,
                    include_samples=include_samples,
                    force=force,
                    dry_run=dry_run,
                )
            ),
            as_json=json_mode,
        )

    if action == "ask":
        return _print(
            _run(
                quivr_brain_ask(
                    question=question,
                    path=path,
                    file_paths=file_paths or None,
                    retrieval_config_path=retrieval_config,
                    backend=backend,
                    use_llm=use_llm,
                )
            ),
            as_json=json_mode,
        )

    return _print({"success": False, "status": "unsupported", "error": f"Unsupported Quivr action: {action}"}, as_json=json_mode)
