"""Gateway-backed messaging and operator summary CLI surface."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from config import get_gateway_api_root_url, get_gateway_root_url


def handle_message(args) -> int:
    action = getattr(args, "action", None) or "status"
    if action == "send":
        text = str(getattr(args, "text", "") or "").strip()
        if not text:
            print("Error: Text required.")
            return 1
        return asyncio.run(send_message(text, channel=getattr(args, "channel", None)))
    if action == "poll":
        return asyncio.run(poll_recent_runs())
    if action == "broadcast":
        print("Broadcast CLI yuzeyi henuz tek kanalli gateway akisi ile sinirli. once 'message send' kullanin.")
        return 0
    if action == "status":
        return asyncio.run(show_status(as_json=bool(getattr(args, "json", False))))
    if action == "platforms":
        return asyncio.run(show_platforms(as_json=bool(getattr(args, "json", False))))
    if action == "stack":
        return asyncio.run(show_stack(as_json=bool(getattr(args, "json", False))))
    print("Usage: elyan message [status|platforms|stack|send|poll|broadcast] [--json]")
    return 1


async def _fetch_json(path: str, *, timeout: float = 10.0) -> tuple[bool, dict[str, Any] | list[Any], str]:
    url = f"{get_gateway_root_url().rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return False, {}, f"HTTP {resp.status_code}"
            return True, resp.json(), ""
    except Exception as exc:
        return False, {}, str(exc)


async def send_message(text: str, channel: str | None = None) -> int:
    url = f"{get_gateway_api_root_url().rstrip('/')}/message"
    channel_name = str(channel or "cli").strip() or "cli"
    print(f"Sending [{channel_name}]: {text}")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json={"text": text, "channel": channel_name})
            if resp.status_code != 200:
                print(f"Error: {resp.status_code}")
                return 1
            data = resp.json()
            print(f"Response: {data.get('status', 'OK')}")
            return 0
    except Exception as exc:
        print(f"Gateway not reachable: {exc}")
        return 1


async def poll_recent_runs() -> int:
    ok, payload, error = await _fetch_json("/api/runs/recent?limit=5")
    if not ok:
        print(f"Poll failed: {error}")
        return 1
    runs = payload.get("runs", []) if isinstance(payload, dict) else []
    if not runs:
        print("Yeni run bulunamadi.")
        return 0
    print("Son calismalar:")
    for row in runs[:5]:
        run_id = str(row.get("run_id") or row.get("id") or "-")
        status = str(row.get("status") or "-")
        text = str(row.get("response_text") or row.get("summary") or "").strip().replace("\n", " ")
        print(f"- {run_id} [{status}] {text[:120]}")
    return 0


async def show_status(*, as_json: bool = False) -> int:
    ok, payload, error = await _fetch_json("/api/v1/system/overview")
    if not ok or not isinstance(payload, dict):
        print(f"Status unavailable: {error}")
        return 1
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    readiness = payload.get("readiness", {}) if isinstance(payload.get("readiness"), dict) else {}
    platforms = ((payload.get("platforms") if isinstance(payload.get("platforms"), dict) else {}) or {}).get("summary", {})
    skills = payload.get("skills", {}) if isinstance(payload.get("skills"), dict) else {}
    providers = ((payload.get("providers") if isinstance(payload.get("providers"), dict) else {}) or {}).get("summary", {})

    print("Operator message status")
    print(f"  Ready:       {'yes' if readiness.get('elyan_ready') else 'no'}")
    print(f"  Model:       {readiness.get('connected_provider', 'local')} / {readiness.get('connected_model', '-')}")
    print(f"  Channels:    {int(platforms.get('connected_channels', 0) or 0)} live / {int(platforms.get('configured_channels', 0) or 0)} configured")
    print(f"  Skills:      {int(skills.get('enabled', 0) or 0)} enabled · {int(skills.get('issues', 0) or 0)} issues")
    print(f"  Providers:   {int(providers.get('available', 0) or 0)} ready · {int(providers.get('auth_required', 0) or 0)} auth needed")
    return 0


async def show_platforms(*, as_json: bool = False) -> int:
    ok, payload, error = await _fetch_json("/api/v1/system/platforms")
    if not ok or not isinstance(payload, dict):
        print(f"Platforms unavailable: {error}")
        return 1
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    gateway = payload.get("gateway", {}) if isinstance(payload.get("gateway"), dict) else {}
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    surfaces = payload.get("surfaces", []) if isinstance(payload.get("surfaces"), list) else []
    print("Operator platforms")
    print(f"  Gateway:     {'active' if gateway.get('running') else 'inactive'}")
    print(f"  Surfaces:    {int(summary.get('active', 0) or 0)} active")
    for item in surfaces:
        if not isinstance(item, dict):
            continue
        print(f"  - {item.get('label', item.get('name', '?'))}: {item.get('status', '-')}")
    return 0


async def show_stack(*, as_json: bool = False) -> int:
    ok_skills, skills_payload, skills_error = await _fetch_json("/api/skills")
    ok_workflows, workflows_payload, workflows_error = await _fetch_json("/api/skills/workflows")
    ok_routines, routines_payload, routines_error = await _fetch_json("/api/routines")
    if not (ok_skills and ok_workflows and ok_routines):
        errors = [err for err in (skills_error, workflows_error, routines_error) if err]
        print(f"Stack unavailable: {'; '.join(errors) or 'unknown error'}")
        return 1

    payload = {
        "skills": skills_payload,
        "workflows": workflows_payload,
        "routines": routines_payload,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    skill_summary = skills_payload.get("summary", {}) if isinstance(skills_payload, dict) else {}
    workflow_summary = workflows_payload.get("summary", {}) if isinstance(workflows_payload, dict) else {}
    routine_summary = routines_payload.get("summary", {}) if isinstance(routines_payload, dict) else {}
    print("Operator stack")
    print(f"  Skills:      {int(skill_summary.get('enabled', 0) or 0)}/{int(skill_summary.get('installed', 0) or 0)} enabled")
    print(f"  Workflows:   {int(workflow_summary.get('enabled', 0) or 0)}/{int(workflow_summary.get('total', 0) or 0)} enabled")
    print(f"  Routines:    {int(routine_summary.get('enabled', 0) or 0)}/{int(routine_summary.get('total', 0) or 0)} active")
    return 0
