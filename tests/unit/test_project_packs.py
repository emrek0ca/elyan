from __future__ import annotations

import pytest

from core import project_packs


@pytest.mark.asyncio
async def test_build_pack_overview_merges_live_status(monkeypatch):
    async def fake_status(pack, path=""):
        _ = path
        return {
            "success": True,
            "status": "success",
            "project": {"name": pack, "root": f"/tmp/{pack}", "features": ["docker_compose", "schema_sql"]},
            "bundle": {"id": f"bundle-{pack}"},
            "message": f"{pack} ready",
        }

    monkeypatch.setattr(project_packs, "pack_status", fake_status)

    payload = await project_packs.build_pack_overview("quivr", path="/tmp/quivr")

    assert payload["success"] is True
    assert payload["count"] == 1
    item = payload["packs"][0]
    assert item["pack"] == "quivr"
    assert item["label"] == "Quivr"
    assert item["root"] == "/tmp/quivr"
    assert item["bundle_id"] == "bundle-quivr"
    assert item["feature_count"] == 2
    assert item["readiness"] == "ready"
    assert item["command"] == "elyan packs status quivr"
    assert item["commands"]["status"] == "elyan packs status quivr"


@pytest.mark.asyncio
async def test_pack_status_all_returns_three_items(monkeypatch):
    async def fake_status_all(path=""):
        _ = path
        return {
            "success": True,
            "status": "success",
            "packs": [
                {"pack": "quivr", "label": "Quivr", "status": "ready", "success": True, "project": {}, "bundle": {}, "feature_sample": []},
                {"pack": "cloudflare-agents", "label": "Cloudflare Agents", "status": "ready", "success": True, "project": {}, "bundle": {}, "feature_sample": []},
                {"pack": "opengauss", "label": "OpenGauss", "status": "ready", "success": True, "project": {}, "bundle": {}, "feature_sample": []},
            ],
            "count": 3,
        }

    monkeypatch.setattr(project_packs, "pack_status_all", fake_status_all)

    payload = await project_packs.build_pack_overview("all", path="/tmp")

    assert payload["success"] is True
    assert payload["count"] == 3
    assert [item["pack"] for item in payload["packs"]] == ["quivr", "cloudflare-agents", "opengauss"]
