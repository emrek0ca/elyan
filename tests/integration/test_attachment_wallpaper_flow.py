import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.agent import Agent


@pytest.mark.asyncio
async def test_attachment_wallpaper_flow_generates_manifest(monkeypatch, tmp_path):
    image = tmp_path / "dog.jpg"
    image.write_bytes(b"fake-image")

    agent = Agent()

    async def _fake_run(ctx, agent):
        _ = await agent._execute_tool(
            "set_wallpaper",
            {"image_path": str(image)},
            user_input=ctx.user_input,
            step_name="SetWallpaper",
        )
        ctx.action = "set_wallpaper"
        ctx.final_response = "Duvar kağıdı ayarlandı."
        return ctx

    async def _fake_exec(tool_name, params, **kwargs):
        _ = kwargs
        return {"success": True, "path": str(image), "tool": tool_name, "params": params}

    monkeypatch.setattr(agent.kernel, "tools", SimpleNamespace(execute=_fake_exec))

    from core import pipeline as _pipeline_mod
    monkeypatch.setattr(_pipeline_mod.pipeline_runner, "run", _fake_run)

    resp = await agent.process_envelope(
        "bunu duvar kağıdı yap",
        attachments=[{"path": str(image), "type": "image"}],
        channel="telegram",
    )

    assert resp.status in {"success", "partial"}
    assert Path(resp.evidence_manifest_path).exists()

    data = json.loads(Path(resp.evidence_manifest_path).read_text(encoding="utf-8"))
    assert data["steps"]
    assert any(s.get("tool") == "set_wallpaper" for s in data["steps"])
