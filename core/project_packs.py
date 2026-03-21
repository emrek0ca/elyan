from __future__ import annotations

import asyncio
from typing import Any

from tools.cloudflare_agents_tools import cloudflare_agents_status
from tools.opengauss_tools import opengauss_status
from tools.quivr_tools import quivr_status

PACKS: dict[str, dict[str, Any]] = {
    "quivr": {
        "label": "Quivr",
        "summary": "Second-brain, grounded Q&A ve local-first knowledge pack.",
        "commands": {
            "status": "elyan packs status quivr",
            "project": "elyan packs project quivr --path ./quivr",
            "scaffold": "elyan packs scaffold quivr --path ./quivr",
            "workflow": "elyan packs workflow quivr",
            "ask": 'elyan packs ask quivr --question "Bu knowledge base ne biliyor?"',
        },
    },
    "cloudflare-agents": {
        "label": "Cloudflare Agents",
        "summary": "Edge agent runtime, worker scaffold ve MCP hizalamasi.",
        "commands": {
            "status": "elyan packs status cloudflare-agents",
            "project": "elyan packs project cloudflare-agents --path ./worker",
            "scaffold": "elyan packs scaffold cloudflare-agents --path ./worker",
            "workflow": "elyan packs workflow cloudflare-agents",
        },
    },
    "opengauss": {
        "label": "OpenGauss",
        "summary": "Docker tabanli database workspace, schema ve safe SQL akisi.",
        "commands": {
            "status": "elyan packs status opengauss",
            "project": "elyan packs project opengauss --path ./db",
            "scaffold": "elyan packs scaffold opengauss --path ./db",
            "workflow": "elyan packs workflow opengauss",
            "query": 'elyan packs query opengauss --sql "SELECT 1;" --execute',
        },
    },
}

_PACK_ALIASES = {
    "cloudflare_agents": "cloudflare-agents",
    "cloudflare agents": "cloudflare-agents",
    "cloudflareagents": "cloudflare-agents",
}


def normalize_pack(value: str) -> str:
    raw = str(value or "").strip().lower().replace(" ", "-").replace("_", "-")
    if not raw or raw == "all":
        return "all"
    return _PACK_ALIASES.get(raw, raw)


def build_pack_catalog(pack: str = "all") -> list[dict[str, Any]]:
    if pack and pack != "all":
        spec = PACKS.get(pack)
        if not spec:
            return []
        return [{"pack": pack, **spec}]
    return [{"pack": name, **spec} for name, spec in PACKS.items()]


async def pack_status(pack: str, path: str = "") -> dict[str, Any]:
    if pack == "quivr":
        return await quivr_status(path=path)
    if pack == "cloudflare-agents":
        return await cloudflare_agents_status(path=path)
    if pack == "opengauss":
        return await opengauss_status(path=path)
    return {"success": False, "status": "unsupported", "error": f"Unsupported pack: {pack}"}


async def pack_status_all(path: str = "") -> dict[str, Any]:
    pack_names = list(PACKS.keys())
    results = await asyncio.gather(
        *(pack_status(pack, path=path) for pack in pack_names),
        return_exceptions=True,
    )
    rows: list[dict[str, Any]] = []
    for pack, result in zip(pack_names, results, strict=False):
        if isinstance(result, Exception):
            payload = {
                "success": False,
                "status": "error",
                "error": str(result),
                "project": {},
                "bundle": {},
            }
        else:
            payload = result or {}
        project = payload.get("project") or {}
        bundle = payload.get("bundle") or payload.get("workflow") or {}
        features = list(project.get("features") or [])
        commands = dict(PACKS[pack].get("commands") or {})
        rows.append(
            {
                "pack": pack,
                "label": PACKS[pack]["label"],
                "summary": PACKS[pack]["summary"],
                "status": payload.get("status") or "ok",
                "success": bool(payload.get("success", False)),
                "project": project,
                "bundle": bundle,
                "message": payload.get("message"),
                "root": project.get("root"),
                "bundle_id": bundle.get("id") or bundle.get("workflow_id") or "",
                "feature_count": len(features),
                "feature_sample": features[:4],
                "commands": commands,
                "command_count": len(commands),
                "readiness": "ready" if bool(payload.get("success", False)) else "missing",
                "command": PACKS[pack]["commands"].get("status", ""),
                "next_step": _pack_next_step(pack, payload),
            }
        )
    success = all(item["success"] for item in rows)
    return {
        "success": success,
        "status": "success" if success else "partial",
        "packs": rows,
        "count": len(rows),
    }


def _merge_pack_meta(spec: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
    item = dict(spec or {})
    item.update(live or {})
    project = item.get("project") or {}
    bundle = item.get("bundle") or item.get("workflow") or {}
    features = list(project.get("features") or [])
    commands = dict(item.get("commands") or {})
    item["root"] = item.get("root") or project.get("root") or ""
    item["bundle_id"] = item.get("bundle_id") or bundle.get("id") or bundle.get("workflow_id") or ""
    item["feature_count"] = item.get("feature_count") if item.get("feature_count") is not None else len(features)
    item["feature_sample"] = item.get("feature_sample") or features[:4]
    item["readiness"] = item.get("readiness") or ("ready" if bool(item.get("success", False)) else "missing")
    item["command"] = item.get("command") or item.get("commands", {}).get("status", "")
    item["commands"] = commands
    item["command_count"] = item.get("command_count") if item.get("command_count") is not None else len(commands)
    return item


async def build_pack_overview(pack: str = "all", path: str = "") -> dict[str, Any]:
    normalized = normalize_pack(pack)
    catalog = build_pack_catalog(normalized)
    if normalized != "all":
        if not catalog:
            return {"success": False, "status": "missing", "packs": [], "count": 0}
        live = await pack_status(normalized, path=path)
        merged = _merge_pack_meta(catalog[0], live)
        return {
            "success": bool(live.get("success", False)),
            "status": live.get("status") or "ok",
            "packs": [merged],
            "count": 1,
        }

    live_all = await pack_status_all(path=path)
    live_lookup = {str(item.get("pack") or ""): item for item in list(live_all.get("packs") or [])}
    merged = [_merge_pack_meta(spec, live_lookup.get(spec["pack"], {})) for spec in catalog]
    success = bool(live_all.get("success", False))
    return {
        "success": success,
        "status": live_all.get("status") or ("success" if success else "partial"),
        "packs": merged,
        "count": len(merged),
    }


def _pack_next_step(pack: str, payload: dict[str, Any]) -> str:
    if not payload.get("success", False):
        return "Scaffold ile workspace kur."
    if pack == "quivr":
        return "Brain.from_files ve grounded Q&A ile veri kaynagini bagla."
    if pack == "cloudflare-agents":
        return "Worker scaffoldi deploy edip agent request akisini dogrula."
    if pack == "opengauss":
        return "Read-only query ile schema ve compose readiness'i dogrula."
    return "Bir sonraki eylemi calistir."
