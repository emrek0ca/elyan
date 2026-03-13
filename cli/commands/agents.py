"""agents.py - CLI-compatible multi-agent management."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from config.elyan_config import elyan_config
from core.agents.registry import list_agent_modules, run_agent_module
from core.automation_registry import automation_registry
from core.multi_agent.pool import agent_pool


def _load_agents() -> list[dict[str, Any]]:
    agents = elyan_config.get("agents", [])
    if not isinstance(agents, list):
        return []
    return [dict(item) for item in agents if isinstance(item, dict)]


def _save_agents(agents: list[dict[str, Any]]) -> None:
    elyan_config.set("agents", agents)
    elyan_config.save()


def _find_agent(agent_id: str) -> dict[str, Any] | None:
    target = str(agent_id or "").strip()
    for row in _load_agents():
        if str(row.get("id") or "").strip() == target:
            return row
    return None


def _running_ids() -> set[str]:
    return set(getattr(agent_pool, "agents", {}).keys())


def _build_status_row(agent_row: dict[str, Any]) -> dict[str, Any]:
    aid = str(agent_row.get("id") or "")
    return {
        "id": aid,
        "workspace": str(agent_row.get("workspace") or ""),
        "model": str(agent_row.get("model") or ""),
        "routes": list(agent_row.get("routes") or []),
        "user_routes": list(agent_row.get("user_routes") or []),
        "running": aid in _running_ids(),
    }


def _print_agent_list(as_json: bool = False) -> None:
    rows = [_build_status_row(item) for item in _load_agents()]
    if as_json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    if not rows:
        print("Kayitli agent yok.")
        return
    print(f"{'ID':<18} {'DURUM':<10} {'KANALLAR':<24} {'MODEL'}")
    print("-" * 80)
    for row in rows:
        status = "active" if row["running"] else "idle"
        routes = ", ".join(row["routes"]) or "-"
        print(f"{row['id']:<18} {status:<10} {routes:<24} {row['model'] or '-'}")


def _status(agent_id: str | None = None) -> int:
    if agent_id:
        found = _find_agent(agent_id)
        if not found:
            print(f"Agent bulunamadi: {agent_id}")
            return 1
        print(json.dumps(_build_status_row(found), indent=2, ensure_ascii=False))
        return 0
    _print_agent_list(False)
    return 0


def _add(agent_id: str, channel: str | None = None) -> int:
    target = str(agent_id or "").strip()
    if not target:
        print("Agent ID gerekli.")
        return 1
    rows = _load_agents()
    if any(str(row.get("id") or "").strip() == target for row in rows):
        print(f"Agent zaten var: {target}")
        return 1
    routes = [str(channel).strip()] if channel else []
    rows.append(
        {
            "id": target,
            "workspace": "",
            "model": str(elyan_config.get("models.default.model", "") or ""),
            "routes": routes,
            "user_routes": [],
        }
    )
    _save_agents(rows)
    print(f"Agent eklendi: {target}")
    return 0


def _remove(agent_id: str) -> int:
    target = str(agent_id or "").strip()
    rows = _load_agents()
    filtered = [row for row in rows if str(row.get("id") or "").strip() != target]
    if len(filtered) == len(rows):
        print(f"Agent bulunamadi: {target}")
        return 1
    _save_agents(filtered)
    print(f"Agent silindi: {target}")
    return 0


def _start(agent_id: str) -> int:
    target = str(agent_id or "").strip()
    if not _find_agent(target):
        print(f"Agent bulunamadi: {target}")
        return 1
    asyncio.run(agent_pool.get_agent(target))
    print(f"Agent baslatildi: {target}")
    return 0


def _stop(agent_id: str) -> int:
    target = str(agent_id or "").strip()
    running = getattr(agent_pool, "agents", {})
    agent = running.get(target)
    if agent is None:
        print(f"Agent calismiyor: {target}")
        return 0
    asyncio.run(agent.shutdown())
    running.pop(target, None)
    print(f"Agent durduruldu: {target}")
    return 0


def _logs(agent_id: str) -> int:
    print(f"Agent loglari icin ortak log akisina bak: ~/.elyan/logs (agent={agent_id})")
    return 0


def _modules() -> int:
    modules = list_agent_modules()
    if not modules:
        print("Kayitli module yok.")
        return 0
    print(f"{'MODULE_ID':<32} {'INTERVAL(s)':<12} {'CATEGORY':<16} {'NAME'}")
    print("-" * 96)
    for row in modules:
        print(
            f"{str(row.get('module_id') or ''):<32} "
            f"{int(row.get('default_interval_seconds') or 0):<12} "
            f"{str(row.get('category') or ''):<16} "
            f"{str(row.get('name') or '')}"
        )
    return 0


def _parse_params(raw: str | None) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    print("Geçersiz --params JSON, boş payload kullanılacak.")
    return {}


def _module_run(module_id: str, *, workspace: str | None = None, params: str | None = None) -> int:
    mid = str(module_id or "").strip().lower()
    if not mid:
        print("Module ID gerekli.")
        return 1
    payload = _parse_params(params)
    if workspace:
        payload.setdefault("workspace", str(workspace))
    result = asyncio.run(run_agent_module(mid, payload))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if bool(result.get("success", False)) else 1


def _module_enable(
    module_id: str,
    *,
    interval: int | None = None,
    timeout: int | None = None,
    retries: int | None = None,
    backoff: int | None = None,
    circuit_threshold: int | None = None,
    circuit_cooldown: int | None = None,
    workspace: str | None = None,
    params: str | None = None,
    channel: str | None = None,
) -> int:
    mid = str(module_id or "").strip().lower()
    if not mid:
        print("Module ID gerekli.")
        return 1

    payload = _parse_params(params)
    if workspace:
        payload.setdefault("workspace", str(workspace))
    try:
        task_id = automation_registry.register_module(
            mid,
            interval_seconds=interval,
            timeout_seconds=timeout,
            max_retries=retries,
            retry_backoff_seconds=backoff,
            circuit_breaker_threshold=circuit_threshold,
            circuit_breaker_cooldown_seconds=circuit_cooldown,
            channel=str(channel or "automation"),
            params=payload,
        )
    except Exception as exc:
        print(f"Module automation kaydı başarısız: {exc}")
        return 1

    print(f"Module automation kaydedildi: {task_id} ({mid})")
    return 0


def _fmt_epoch(value: Any) -> str:
    try:
        ts = float(value or 0.0)
    except Exception:
        ts = 0.0
    if ts <= 0:
        return "-"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except Exception:
        return "-"


def _module_tasks(*, include_inactive: bool = False, as_json: bool = False) -> int:
    rows = automation_registry.list_module_tasks(include_inactive=bool(include_inactive), limit=200)
    if as_json:
        print(json.dumps({"tasks": rows, "count": len(rows)}, indent=2, ensure_ascii=False))
        return 0
    if not rows:
        print("Module task bulunamadi.")
        return 0
    print(f"{'TASK_ID':<10} {'MODULE_ID':<30} {'STATUS':<9} {'HEALTH':<12} {'INT':<6} {'TO':<5} {'RT':<4}")
    print("-" * 98)
    for row in rows:
        print(
            f"{str(row.get('task_id') or ''):<10} "
            f"{str(row.get('module_id') or ''):<30} "
            f"{str(row.get('status') or ''):<9} "
            f"{str(row.get('health') or ''):<12} "
            f"{int(row.get('interval_seconds') or 0):<6} "
            f"{int(row.get('timeout_seconds') or 0):<5} "
            f"{int(row.get('max_retries') or 0):<4}"
        )
    return 0


def _module_health(*, as_json: bool = False) -> int:
    snapshot = automation_registry.get_module_health(limit=50)
    summary = snapshot.get("summary") if isinstance(snapshot, dict) else {}
    rows = snapshot.get("modules") if isinstance(snapshot, dict) else []
    if as_json:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
        return 0
    print(
        "Module Health | "
        f"active={int((summary or {}).get('active_modules') or 0)} "
        f"healthy={int((summary or {}).get('healthy') or 0)} "
        f"failing={int((summary or {}).get('failing') or 0)} "
        f"circuit_open={int((summary or {}).get('circuit_open') or 0)}"
    )
    if not rows:
        print("Health satiri yok.")
        return 0
    print(f"{'TASK_ID':<10} {'MODULE_ID':<30} {'HEALTH':<12} {'LAST_STATUS':<12} {'LAST_RUN'}")
    print("-" * 92)
    for row in rows:
        print(
            f"{str(row.get('task_id') or ''):<10} "
            f"{str(row.get('module_id') or ''):<30} "
            f"{str(row.get('health') or ''):<12} "
            f"{str(row.get('last_status') or ''):<12} "
            f"{_fmt_epoch(row.get('last_run'))}"
        )
    return 0


def _module_run_now(task_id: str) -> int:
    rid = str(task_id or "").strip()
    if not rid:
        print("Task ID gerekli.")
        return 1
    result = asyncio.run(automation_registry.run_task_now(rid))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if bool(result.get("success", False)) else 1


def _module_set_status(task_id: str, *, status: str) -> int:
    rid = str(task_id or "").strip()
    if not rid:
        print("Task ID gerekli.")
        return 1
    ok = bool(automation_registry.set_status(rid, status))
    if not ok:
        print(f"Task bulunamadi veya guncellenemedi: {rid}")
        return 1
    print(f"Task guncellendi: {rid} -> {status}")
    return 0


def _module_remove(task_id: str) -> int:
    rid = str(task_id or "").strip()
    if not rid:
        print("Task ID gerekli.")
        return 1
    ok = bool(automation_registry.unregister(rid))
    if not ok:
        print(f"Task bulunamadi: {rid}")
        return 1
    print(f"Task silindi: {rid}")
    return 0


def _module_update(
    task_id: str,
    *,
    interval: int | None = None,
    timeout: int | None = None,
    retries: int | None = None,
    backoff: int | None = None,
    circuit_threshold: int | None = None,
    circuit_cooldown: int | None = None,
    workspace: str | None = None,
    params: str | None = None,
    channel: str | None = None,
    status: str | None = None,
) -> int:
    rid = str(task_id or "").strip()
    if not rid:
        print("Task ID gerekli.")
        return 1

    params_obj: dict[str, Any] | None = None
    if params is not None:
        params_obj = _parse_params(params)
    if workspace:
        if params_obj is None:
            params_obj = {}
        params_obj.setdefault("workspace", str(workspace))

    updated = automation_registry.update_module_task(
        rid,
        interval_seconds=interval,
        timeout_seconds=timeout,
        max_retries=retries,
        retry_backoff_seconds=backoff,
        circuit_breaker_threshold=circuit_threshold,
        circuit_breaker_cooldown_seconds=circuit_cooldown,
        params=params_obj,
        channel=channel,
        status=status,
    )
    if not updated:
        print(f"Task bulunamadi: {rid}")
        return 1
    print(json.dumps({"ok": True, "task": updated}, indent=2, ensure_ascii=False))
    return 0


def _module_reconcile() -> int:
    result = automation_registry.reconcile_module_tasks()
    print(json.dumps({"ok": True, **result}, indent=2, ensure_ascii=False))
    return 0


def handle_agents(args) -> int:
    action = str(getattr(args, "action", "") or "list").strip().lower() or "list"
    agent_id = getattr(args, "id", None)
    channel = getattr(args, "channel", None)

    if action == "list":
        _print_agent_list(False)
        return 0
    if action == "status":
        return _status(agent_id)
    if action in {"add", "create"}:
        return _add(str(agent_id or ""), channel)
    if action == "remove":
        return _remove(str(agent_id or ""))
    if action == "start":
        return _start(str(agent_id or ""))
    if action == "stop":
        return _stop(str(agent_id or ""))
    if action == "logs":
        return _logs(str(agent_id or ""))
    if action == "modules":
        return _modules()
    if action == "module-run":
        return _module_run(
            str(agent_id or ""),
            workspace=getattr(args, "workspace", None),
            params=getattr(args, "params", None),
        )
    if action == "module-enable":
        return _module_enable(
            str(agent_id or ""),
            interval=getattr(args, "interval", None),
            timeout=getattr(args, "timeout", None),
            retries=getattr(args, "retries", None),
            backoff=getattr(args, "backoff", None),
            circuit_threshold=getattr(args, "circuit_threshold", None),
            circuit_cooldown=getattr(args, "circuit_cooldown", None),
            workspace=getattr(args, "workspace", None),
            params=getattr(args, "params", None),
            channel=getattr(args, "channel", None),
        )
    if action == "module-tasks":
        return _module_tasks(
            include_inactive=bool(getattr(args, "include_inactive", False)),
            as_json=bool(getattr(args, "json", False)),
        )
    if action == "module-health":
        return _module_health(as_json=bool(getattr(args, "json", False)))
    if action == "module-run-now":
        return _module_run_now(str(agent_id or ""))
    if action == "module-pause":
        return _module_set_status(str(agent_id or ""), status="paused")
    if action == "module-resume":
        return _module_set_status(str(agent_id or ""), status="active")
    if action == "module-remove":
        return _module_remove(str(agent_id or ""))
    if action == "module-update":
        return _module_update(
            str(agent_id or ""),
            interval=getattr(args, "interval", None),
            timeout=getattr(args, "timeout", None),
            retries=getattr(args, "retries", None),
            backoff=getattr(args, "backoff", None),
            circuit_threshold=getattr(args, "circuit_threshold", None),
            circuit_cooldown=getattr(args, "circuit_cooldown", None),
            workspace=getattr(args, "workspace", None),
            params=getattr(args, "params", None),
            channel=getattr(args, "channel", None),
            status=getattr(args, "status", None),
        )
    if action == "module-reconcile":
        return _module_reconcile()
    if action == "info":
        return _status(agent_id)
    print(f"Bilinmeyen agents komutu: {action}")
    return 1
