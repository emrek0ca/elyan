from __future__ import annotations

import asyncio
import json
from typing import Any

from core.project_packs import PACKS, build_pack_catalog, normalize_pack, pack_status, pack_status_all
from tools.cloudflare_agents_tools import (
    cloudflare_agents_scaffold,
    cloudflare_agents_workflow,
)
from tools.opengauss_tools import opengauss_query, opengauss_scaffold, opengauss_workflow
from tools.quivr_tools import quivr_brain_ask, quivr_project


def _run(coro):
    return asyncio.run(coro)


def _catalog(pack: str = "all") -> list[dict[str, Any]]:
    return build_pack_catalog(pack)


def _payload(success: bool, status: str, **extra: Any) -> dict[str, Any]:
    data = {"success": success, "status": status}
    data.update(extra)
    return data


def _print_payload(title: str, payload: dict[str, Any], *, as_json: bool = False) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if bool(payload.get("success", False)) else 1

    status = str(payload.get("status") or "ok")
    if payload.get("success", False):
        print(f"{title}: {status}")
    else:
        print(f"{title} hata: {payload.get('error') or status}")

    project = payload.get("project") or {}
    if project:
        print(f"Project: {project.get('name') or '-'} ({project.get('root') or '-'})")

    bundle = payload.get("bundle") or payload.get("workflow") or {}
    if bundle:
        print(f"Bundle: {bundle.get('id') or bundle.get('workflow_id') or '-'}")

    command = str(payload.get("command") or "").strip()
    if command:
        print(command)

    execution = payload.get("execution") or {}
    if execution:
        print(f"Execution: exit {execution.get('returncode', '-')}")
        stdout = str(execution.get("stdout") or "").strip()
        stderr = str(execution.get("stderr") or "").strip()
        if stdout:
            print(stdout)
        if stderr:
            print(stderr)

    message = str(payload.get("message") or "").strip()
    if message:
        print(message)

    return 0 if bool(payload.get("success", False)) else 1


def _print_catalog(pack: str, *, as_json: bool = False) -> int:
    items = _catalog(pack)
    if pack and pack != "all" and not items:
        payload = _payload(False, "missing", error=f"Pack bulunamadi: {pack}", packs=[], count=0)
        if as_json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 1
        print(f"Pack bulunamadi: {pack}")
        return 1

    payload = _payload(True, "success", packs=items, count=len(items))
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print("Pack kataloğu:")
    for item in items:
        print(f"- {item['label']}: {item['summary']}")
        commands = item.get("commands") or {}
        for key in ("status", "project", "scaffold", "workflow", "ask", "query"):
            command = str(commands.get(key) or "").strip()
            if command:
                print(f"  {key}: {command}")
    return 0


async def _status_payload(pack: str, path: str) -> dict[str, Any]:
    return await pack_status(pack, path=path)


def _print_status_all(payload: dict[str, Any], *, as_json: bool = False) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if bool(payload.get("success", False)) else 1

    rows = list(payload.get("packs") or [])
    print("Pack durumu:")
    for item in rows:
        label = str(item.get("label") or item.get("pack") or "pack")
        status = str(item.get("status") or "ok")
        line = f"- {label}: {status}"
        project = item.get("project") or {}
        root = str(project.get("root") or "").strip()
        name = str(project.get("name") or "").strip()
        if root or name:
            line += f" ({name or '-'}"
            if root:
                line += f" @ {root}"
            line += ")"
        print(line)
        bundle = item.get("bundle") or {}
        if bundle:
            print(f"  bundle: {bundle.get('id') or bundle.get('workflow_id') or '-'}")
        message = str(item.get("message") or "").strip()
        if message:
            print(f"  {message}")
    return 0 if bool(payload.get("success", False)) else 1


async def _dispatch(pack: str, action: str, *, path: str, name: str, goal: str, backend: str, include_samples: bool,
                    include_chat: bool, include_workflows: bool, include_mcp: bool, force: bool, dry_run: bool,
                    question: str, retrieval_config: str, file_paths: list[str], use_llm: bool,
                    image: str, database: str, user: str, password: str, port: int, sql: str,
                    execute: bool, allow_mutation: bool, timeout: int) -> dict[str, Any]:
    if pack == "quivr":
        if action == "status":
            return await quivr_status(path=path)
        if action in {"scaffold", "project"}:
            return await quivr_project(
                action="scaffold",
                path=path,
                name=name or goal,
                include_samples=include_samples,
                force=force,
                dry_run=dry_run,
            )
        if action in {"workflow", "bundle"}:
            return await quivr_project(
                action="workflow",
                path=path,
                name=name or goal,
                backend=backend,
                include_samples=include_samples,
                force=force,
                dry_run=dry_run,
            )
        if action == "ask":
            return await quivr_brain_ask(
                question=question or goal,
                path=path,
                file_paths=file_paths or None,
                retrieval_config_path=retrieval_config,
                backend=backend,
                use_llm=use_llm,
            )

    if pack == "cloudflare-agents":
        if action == "status":
            return await cloudflare_agents_status(path=path)
        if action in {"scaffold", "project"}:
            return await cloudflare_agents_scaffold(
                path=path,
                name=name or goal,
                include_chat=include_chat,
                include_workflows=include_workflows,
                include_mcp=include_mcp,
                force=force,
                dry_run=dry_run,
            )
        if action in {"workflow", "bundle"}:
            return await cloudflare_agents_workflow(
                action="starter",
                path=path,
                goal=name or goal,
                backend=backend,
            )

    if pack == "opengauss":
        if action == "status":
            return await opengauss_status(path=path)
        if action in {"scaffold", "project"}:
            return await opengauss_scaffold(
                path=path,
                name=name or goal,
                image=image,
                port=port,
                database=database,
                user=user,
                password=password,
                include_samples=include_samples,
                force=force,
                dry_run=dry_run,
            )
        if action in {"workflow", "bundle"}:
            return await opengauss_workflow(
                action="starter",
                path=path,
                goal=name or goal,
                target=database,
                backend=backend,
            )
        if action == "query":
            return await opengauss_query(
                sql=sql or goal or "SELECT 1;",
                path=path,
                database=database,
                user=user,
                port=port,
                backend=backend,
                dry_run=dry_run,
                execute=execute,
                allow_mutation=allow_mutation,
                timeout=timeout,
            )

    return {"success": False, "status": "unsupported", "error": f"Unsupported pack/action: {pack} / {action}"}


def run(args) -> int:
    action = str(getattr(args, "action", "") or "list").strip().lower() or "list"
    pack = normalize_pack(getattr(args, "pack", "") or "all")
    path = str(getattr(args, "path", "") or "").strip()
    name = str(getattr(args, "name", "") or "").strip()
    text = " ".join(str(item) for item in list(getattr(args, "text", []) or []) if str(item).strip()).strip()
    backend = str(getattr(args, "backend", "auto") or "auto").strip() or "auto"
    include_samples = bool(getattr(args, "include_samples", True))
    include_chat = bool(getattr(args, "include_chat", True))
    include_workflows = bool(getattr(args, "include_workflows", True))
    include_mcp = bool(getattr(args, "include_mcp", True))
    force = bool(getattr(args, "force", False))
    dry_run = bool(getattr(args, "dry_run", False))
    question = str(getattr(args, "question", "") or "").strip() or text
    retrieval_config = str(getattr(args, "retrieval_config", "") or "").strip()
    file_paths = [str(item).strip() for item in list(getattr(args, "file_paths", []) or []) if str(item).strip()]
    use_llm = bool(getattr(args, "use_llm", False))
    image = str(getattr(args, "image", "opengauss/opengauss-server:latest") or "opengauss/opengauss-server:latest").strip() or "opengauss/opengauss-server:latest"
    database = str(getattr(args, "database", "appdb") or "appdb").strip() or "appdb"
    user = str(getattr(args, "user", "root") or "root").strip() or "root"
    password = str(getattr(args, "password", "OpenGauss@123") or "OpenGauss@123").strip() or "OpenGauss@123"
    port = int(getattr(args, "port", 5432) or 5432)
    sql = str(getattr(args, "sql", "") or "").strip() or text
    execute = bool(getattr(args, "execute", False))
    allow_mutation = bool(getattr(args, "allow_mutation", False))
    timeout = int(getattr(args, "timeout", 30) or 30)
    json_mode = bool(getattr(args, "json", False))

    if action == "list":
        return _print_catalog(pack, as_json=json_mode)

    if action == "status":
        if pack == "all":
            payload = _run(pack_status_all(path))
            return _print_status_all(payload, as_json=json_mode)
        if pack not in PACKS:
            return _print_payload("Pack", {"success": False, "status": "missing", "error": f"Pack bulunamadi: {pack}"}, as_json=json_mode)
        payload = _run(_status_payload(pack, path))
        return _print_payload(PACKS[pack]["label"], payload, as_json=json_mode)

    if pack == "all" or pack not in PACKS:
        return _print_payload("Pack", {"success": False, "status": "missing", "error": f"Pack seçin: {pack}"}, as_json=json_mode)

    normalized_action = "workflow" if action == "bundle" else action
    payload = _run(
        _dispatch(
            pack,
            normalized_action,
            path=path,
            name=name,
            goal=name or text,
            backend=backend,
            include_samples=include_samples,
            include_chat=include_chat,
            include_workflows=include_workflows,
            include_mcp=include_mcp,
            force=force,
            dry_run=dry_run,
            question=question,
            retrieval_config=retrieval_config,
            file_paths=file_paths,
            use_llm=use_llm,
            image=image,
            database=database,
            user=user,
            password=password,
            port=port,
            sql=sql,
            execute=execute,
            allow_mutation=allow_mutation,
            timeout=timeout,
        )
    )
    return _print_payload(PACKS[pack]["label"], payload, as_json=json_mode)
