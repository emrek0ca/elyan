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
        "required_features": [
            "quivr_core",
            "brain_from_files",
            "retrieval_config",
            "query_loop",
            "workflow_yaml",
        ],
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
        "required_features": [
            "persistent_state",
            "agent_routing",
            "realtime_sync",
            "callable_methods",
            "workflow_hooks",
            "mcp_ready",
            "deploy_readiness",
        ],
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
        "required_features": [
            "docker_compose",
            "schema_sql",
            "env_example",
            "query_script",
            "backup_script",
            "restore_script",
        ],
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


def _unique_features(features: Any) -> list[str]:
    values = []
    seen = set()
    for raw in list(features or []):
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        values.append(item)
    return values


def _required_features(pack: str) -> list[str]:
    return _unique_features(PACKS.get(pack, {}).get("required_features") or [])


def _recommended_command(pack: str, *, ready: bool, missing_features: list[str], commands: dict[str, Any]) -> str:
    if not ready:
        return str(commands.get("scaffold") or commands.get("project") or commands.get("status") or "").strip()
    if missing_features:
        return str(commands.get("scaffold") or commands.get("project") or commands.get("workflow") or commands.get("status") or "").strip()
    if pack == "quivr":
        return str(commands.get("workflow") or commands.get("ask") or commands.get("status") or "").strip()
    if pack == "cloudflare-agents":
        return str(commands.get("workflow") or commands.get("status") or "").strip()
    if pack == "opengauss":
        return str(commands.get("query") or commands.get("workflow") or commands.get("status") or "").strip()
    return str(commands.get("status") or "").strip()


def _pack_readiness(pack: str, payload: dict[str, Any], *, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = dict(spec or PACKS.get(pack, {}))
    project = payload.get("project") or {}
    bundle = payload.get("bundle") or payload.get("workflow") or {}
    features = _unique_features(project.get("features") or [])
    required_features = _required_features(pack)
    missing_features = [feature for feature in required_features if feature not in features]
    ready_features = max(len(required_features) - len(missing_features), 0)
    readiness_percent = 100 if not required_features else int(round((ready_features / len(required_features)) * 100))
    raw_success = bool(payload.get("success", False))
    if not raw_success:
        readiness = "missing"
    elif missing_features:
        readiness = "partial"
    else:
        readiness = "ready"
    commands = dict(spec.get("commands") or {})
    item = dict(spec or {})
    item.update(payload or {})
    item["project"] = project
    item["bundle"] = bundle
    item["root"] = item.get("root") or project.get("root") or ""
    item["bundle_id"] = item.get("bundle_id") or bundle.get("id") or bundle.get("workflow_id") or ""
    item["feature_count"] = len(features)
    item["feature_sample"] = features[:4]
    item["required_features"] = required_features
    item["ready_features"] = ready_features
    item["missing_features"] = missing_features
    item["missing_count"] = len(missing_features)
    item["readiness_percent"] = readiness_percent
    item["readiness"] = readiness
    item["command"] = item.get("command") or commands.get("status", "")
    item["commands"] = commands
    item["command_count"] = len(commands)
    item["recommended_command"] = item.get("recommended_command") or _recommended_command(
        pack,
        ready=raw_success,
        missing_features=missing_features,
        commands=commands,
    )
    item["next_step"] = item.get("next_step") or _pack_next_step(pack, payload, missing_features=missing_features)
    return item


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
        rows.append(
            _pack_readiness(
                pack,
                {
                    "pack": pack,
                    "label": PACKS[pack]["label"],
                    "summary": PACKS[pack]["summary"],
                    "status": payload.get("status") or "ok",
                    "success": bool(payload.get("success", False)),
                    "project": payload.get("project") or {},
                    "bundle": payload.get("bundle") or payload.get("workflow") or {},
                    "message": payload.get("message"),
                },
                spec=PACKS[pack],
            )
        )
    success = all(item["success"] for item in rows)
    return {
        "success": success,
        "status": "success" if success else "partial",
        "packs": rows,
        "count": len(rows),
    }


def _merge_pack_meta(spec: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
    base = dict(spec or {})
    base.update(live or {})
    return _pack_readiness(str(base.get("pack") or spec.get("pack") or ""), base, spec=spec)


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


def _pack_next_step(pack: str, payload: dict[str, Any], *, missing_features: list[str] | None = None) -> str:
    missing_features = list(missing_features or [])
    if not payload.get("success", False):
        return "Scaffold ile workspace kur."
    if missing_features:
        missing_text = ", ".join(missing_features[:4])
        return f"Eksik: {missing_text}. Scaffold veya repair ile tamamla."
    if pack == "quivr":
        return "Brain.from_files ve grounded Q&A ile veri kaynagini bagla."
    if pack == "cloudflare-agents":
        return "Worker scaffoldi deploy edip agent request akisini dogrula."
    if pack == "opengauss":
        return "Read-only query ile schema ve compose readiness'i dogrula."
    return "Bir sonraki eylemi calistir."
