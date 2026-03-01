import pytest
from pathlib import Path

from core.sub_agent.team import AgentTeam


class _DummyAgent:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    async def _execute_tool(self, tool_name, params, **kwargs):
        _ = kwargs
        params = dict(params or {})
        if tool_name in {"write_file", "take_screenshot", "write_word", "write_excel"}:
            raw_path = str(params.get("path") or params.get("filename") or f"{tool_name}.txt")
            p = Path(raw_path).expanduser()
            if not p.is_absolute():
                p = self.base_dir / p.name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("team-output", encoding="utf-8")
            return {"success": True, "tool": tool_name, "path": str(p)}
        return {"success": True, "tool": tool_name, "message": params.get("message", "ok")}


@pytest.mark.asyncio
async def test_agent_team_execute_project_returns_outputs(tmp_path):
    team = AgentTeam(_DummyAgent(tmp_path))
    result = await team.execute_project("Kediler için landing page hazırla")

    assert result.status in {"success", "partial"}
    assert isinstance(result.outputs, list)
    assert len(result.outputs) >= 1
