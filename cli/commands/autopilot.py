from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from config.elyan_config import elyan_config


DEFAULT_PORT = int(os.environ.get("ELYAN_PORT", 18789))


def _gateway_running(port: int) -> bool:
    pid_file = Path.home() / ".elyan" / "gateway.pid"
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _admin_headers() -> dict[str, str]:
    token = str(
        os.environ.get("ELYAN_ADMIN_TOKEN", "")
        or elyan_config.get("gateway.admin.token", "")
        or ""
    ).strip()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Elyan-Admin-Token"] = token
    return headers


def _request_json(port: int, path: str, *, method: str = "GET", body: dict | None = None) -> dict:
    url = f"http://127.0.0.1:{port}{path}"
    try:
        payload = json.dumps(body or {}).encode("utf-8") if method != "GET" else None
        req = urllib.request.Request(url, data=payload, headers=_admin_headers(), method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
            return {"ok": True, "status": resp.status, "data": data}
    except urllib.error.HTTPError as exc:
        raw = ""
        try:
            raw = (exc.read() or b"").decode("utf-8")
        except Exception:
            raw = ""
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {"body": raw[:500]} if raw else {}
        err = str(data.get("error") or exc.reason or f"HTTP {exc.code}")
        if not isinstance(data, dict):
            data = {"body": raw[:500]}
        return {"ok": False, "status": int(exc.code or 0), "error": err, "data": data}
    except Exception as exc:
        return {"ok": False, "status": 0, "error": str(exc), "data": {}}


def _local_autopilot():
    from core.autopilot import get_autopilot

    return get_autopilot()


def run_autopilot(args=None):
    args = args or SimpleNamespace(action="status", port=DEFAULT_PORT, reason="")
    port = int(getattr(args, "port", None) or DEFAULT_PORT)
    action = str(getattr(args, "action", "status") or "status").strip().lower()
    running_gateway = _gateway_running(port)

    if running_gateway:
        if action == "status":
            data = _request_json(port, "/api/autopilot/status", method="GET")
            if data.get("ok"):
                print(json.dumps(data.get("data") or {}, ensure_ascii=False, indent=2))
                return 0
            if int(data.get("status") or 0) in {403, 404}:
                print(json.dumps(_local_autopilot().get_status(), ensure_ascii=False, indent=2))
                return 0
            print(f"Autopilot durumu alınamadı: {data.get('error')}")
            return 1
        if action == "start":
            data = _request_json(port, "/api/autopilot/start", method="POST")
        elif action == "stop":
            data = _request_json(port, "/api/autopilot/stop", method="POST")
        elif action == "tick":
            body = {"reason": getattr(args, "reason", "") or "manual_cli"}
            data = _request_json(port, "/api/autopilot/tick", method="POST", body=body)
        else:
            print(f"Bilinmeyen autopilot aksiyonu: {action}")
            return 1
        if data.get("ok"):
            print(json.dumps(data.get("data", {}).get("autopilot") or data.get("data") or {}, ensure_ascii=False, indent=2))
            return 0
        if int(data.get("status") or 0) in {403, 404}:
            autopilot = _local_autopilot()
            if action == "start":
                result = asyncio.run(autopilot.start())
            elif action == "stop":
                result = asyncio.run(autopilot.stop())
            else:
                result = asyncio.run(autopilot.run_tick(reason=getattr(args, "reason", "") or "manual_cli"))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        print(data.get("error") or "Autopilot komutu çalıştırılamadı")
        return 1

    autopilot = _local_autopilot()
    if action == "status":
        print(json.dumps(autopilot.get_status(), ensure_ascii=False, indent=2))
        return 0
    if action == "start":
        result = asyncio.run(autopilot.start())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if action == "stop":
        result = asyncio.run(autopilot.stop())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if action == "tick":
        result = asyncio.run(autopilot.run_tick(reason=getattr(args, "reason", "") or "manual_cli"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"Bilinmeyen autopilot aksiyonu: {action}")
    return 1
