"""agents.py - CLI-compatible multi-agent management."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from config.elyan_config import elyan_config
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
    if action == "info":
        return _status(agent_id)
    print(f"Bilinmeyen agents komutu: {action}")
    return 1
