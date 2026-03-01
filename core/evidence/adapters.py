"""
Evidence adapters: her tool için varsayılan kanıt üretimi.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _nested_get(payload: Dict[str, Any], key: str) -> Any:
    cur: Any = payload
    for part in str(key or "").split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _first_path(payload: Dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = _nested_get(payload, key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def fs_evidence(path: str) -> Dict[str, Any]:
    p = Path(str(path or "")).expanduser()
    exists = p.exists()
    is_file = bool(exists and p.is_file())
    is_dir = bool(exists and p.is_dir())
    data = {
        "path": str(p),
        "exists": exists,
        "is_file": is_file,
        "is_dir": is_dir,
        "size_bytes": int(p.stat().st_size) if is_file else 0,
        "mtime": float(p.stat().st_mtime) if exists else 0.0,
    }
    if is_file:
        try:
            data["sha256"] = _sha256_file(p)
        except Exception:
            pass
    return data


def http_evidence(resp: Dict[str, Any]) -> Dict[str, Any]:
    body = resp.get("body")
    body_bytes = None
    if isinstance(body, (dict, list)):
        body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8", errors="ignore")
    elif isinstance(body, str):
        body_bytes = body.encode("utf-8", errors="ignore")
    evidence = {
        "status_code": resp.get("status_code"),
        "duration_ms": resp.get("duration_ms"),
        "url": resp.get("url"),
        "ok": bool(resp.get("success", False)),
    }
    status_code = evidence.get("status_code")
    if isinstance(status_code, int):
        evidence["status_class"] = int(status_code // 100)
    if body_bytes:
        evidence["body_sha256"] = hashlib.sha256(body_bytes).hexdigest()
    return evidence


def ui_screenshot_evidence(path: str) -> Dict[str, Any]:
    p = Path(str(path or "")).expanduser()
    base = {"path": str(p), "exists": p.exists()}
    if p.exists() and p.is_file():
        base["size_bytes"] = int(p.stat().st_size)
        try:
            base["sha256"] = _sha256_file(p)
        except Exception:
            pass
    return base


def api_health_evidence(resp: Dict[str, Any]) -> Dict[str, Any]:
    results = resp.get("results")
    if not isinstance(results, dict):
        results = {}
    payload = json.dumps(results, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8", errors="ignore")
    return {
        "total": int(resp.get("total", len(results))),
        "healthy": int(resp.get("healthy", 0)),
        "unhealthy": int(resp.get("unhealthy", 0)),
        "duration_ms": resp.get("duration_ms"),
        "results_sha256": hashlib.sha256(payload).hexdigest() if results else "",
    }


EVIDENCE_ADAPTERS = {
    "write_file": lambda result: fs_evidence(_first_path(result, ("path", "file_path", "output_path"))),
    "read_file": lambda result: fs_evidence(_first_path(result, ("path", "file_path"))),
    "create_folder": lambda result: fs_evidence(_first_path(result, ("path",))),
    "set_wallpaper": lambda result: ui_screenshot_evidence(
        _first_path(result, ("_proof.screenshot", "screenshot", "path", "image_path"))
    ),
    "take_screenshot": lambda result: ui_screenshot_evidence(_first_path(result, ("path", "file_path"))),
    "analyze_screen": lambda result: ui_screenshot_evidence(_first_path(result, ("path", "file_path"))),
    "http_request": lambda result: http_evidence(result),
    "api_health_check": lambda result: api_health_evidence(result),
}


def adapt_evidence(tool: str, result: Dict[str, Any]) -> Dict[str, Any]:
    fn = EVIDENCE_ADAPTERS.get(tool)
    if not fn:
        return {}
    try:
        return fn(result or {})
    except Exception:
        return {}
