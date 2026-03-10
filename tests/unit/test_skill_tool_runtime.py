from __future__ import annotations

from typing import Type

import pytest

import tools
from core.skills.base import BaseSkill
from core.skills.builtin.browser_skill import BrowserSkill
from core.skills.builtin.email_skill import EmailSkill
from core.skills.builtin.files_skill import FilesSkill
from core.skills.builtin.office_skill import OfficeSkill
from core.skills.builtin.research_skill import ResearchSkill
from core.skills.builtin.system_skill import SystemSkill as BuiltinSystemSkill
from core.skills.system_skill import SystemSkill


def _instantiate_skill(cls: Type[BaseSkill]) -> BaseSkill:
    original = getattr(cls, "__abstractmethods__", frozenset())
    cls.__abstractmethods__ = frozenset()
    try:
        return cls({})
    finally:
        cls.__abstractmethods__ = original


@pytest.mark.asyncio
async def test_builtin_files_skill_routes_mkdir_through_task_executor(monkeypatch):
    skill = _instantiate_skill(FilesSkill)
    seen: dict[str, object] = {}

    async def create_folder(path: str = ""):
        return {"success": True, "message": f"created:{path}"}

    async def fake_execute(self, tool_func, params):
        seen["tool_name"] = getattr(tool_func, "__name__", "")
        seen["params"] = dict(params)
        return {"success": True, "status": "success", "message": "ok"}

    original = tools._loaded_tools.get("create_folder")
    tools._loaded_tools["create_folder"] = create_folder
    monkeypatch.setattr("core.task_executor.TaskExecutor.execute", fake_execute)

    try:
        result = await skill.execute("mkdir", {"params": {"path": "/tmp/demo"}})
    finally:
        if original is None:
            tools._loaded_tools.pop("create_folder", None)
        else:
            tools._loaded_tools["create_folder"] = original

    assert seen["tool_name"] == "create_folder"
    assert seen["params"] == {"path": "/tmp/demo"}
    assert result["success"] is True
    assert result["result"]["status"] == "success"


@pytest.mark.asyncio
async def test_builtin_files_skill_surfaces_malformed_output_as_normalized_failure():
    skill = _instantiate_skill(FilesSkill)

    async def bad_read_file(path: str = ""):
        return None

    original = tools._loaded_tools.get("read_file")
    tools._loaded_tools["read_file"] = bad_read_file

    try:
        result = await skill.execute("read", {"params": {"path": "/tmp/demo.txt"}})
    finally:
        if original is None:
            tools._loaded_tools.pop("read_file", None)
        else:
            tools._loaded_tools["read_file"] = original

    assert result["success"] is False
    assert result["error"]
    assert result["result"]["error_code"] == "TOOL_CONTRACT_VIOLATION"
    assert result["result"]["status"] == "failed"


@pytest.mark.asyncio
async def test_builtin_system_skill_routes_screenshot_through_task_executor(monkeypatch):
    skill = _instantiate_skill(BuiltinSystemSkill)
    seen: dict[str, object] = {}

    async def take_screenshot(filename: str | None = None):
        return {"success": True, "path": f"/tmp/{filename or 'shot.png'}"}

    async def fake_execute(self, tool_func, params):
        seen["tool_name"] = getattr(tool_func, "__name__", "")
        seen["params"] = dict(params)
        return {"success": True, "status": "success", "message": "shot-ok"}

    original = tools._loaded_tools.get("take_screenshot")
    tools._loaded_tools["take_screenshot"] = take_screenshot
    monkeypatch.setattr("core.task_executor.TaskExecutor.execute", fake_execute)

    try:
        result = await skill.execute("screenshot", {"params": {}})
    finally:
        if original is None:
            tools._loaded_tools.pop("take_screenshot", None)
        else:
            tools._loaded_tools["take_screenshot"] = original

    assert seen["tool_name"] == "take_screenshot"
    assert seen["params"] == {}
    assert result["success"] is True
    assert result["result"]["status"] == "success"


@pytest.mark.asyncio
async def test_system_skill_execute_tool_uses_normalized_unknown_and_malformed_paths():
    skill = SystemSkill({})

    async def bad_take_screenshot(filename: str | None = None):
        return None

    original = tools._loaded_tools.get("take_screenshot")
    tools._loaded_tools["take_screenshot"] = bad_take_screenshot

    try:
        malformed = await skill.execute_tool("take_screenshot", {})
        unknown = await skill.execute_tool("missing_tool_xyz", {})
    finally:
        if original is None:
            tools._loaded_tools.pop("take_screenshot", None)
        else:
            tools._loaded_tools["take_screenshot"] = original

    assert malformed["status"] == "failed"
    assert malformed["error_code"] == "TOOL_CONTRACT_VIOLATION"
    assert unknown["status"] == "failed"
    assert unknown["error_code"] == "UNKNOWN_TOOL"


@pytest.mark.asyncio
async def test_builtin_browser_skill_routes_navigate_through_task_executor(monkeypatch):
    skill = _instantiate_skill(BrowserSkill)
    seen: dict[str, object] = {}

    async def open_url(url: str = "", browser: str | None = None):
        return {"success": True, "url": url, "browser": browser}

    async def fake_execute(self, tool_func, params):
        seen["tool_name"] = getattr(tool_func, "__name__", "")
        seen["params"] = dict(params)
        return {"success": True, "status": "success", "message": "navigated"}

    original = tools._loaded_tools.get("open_url")
    tools._loaded_tools["open_url"] = open_url
    monkeypatch.setattr("core.task_executor.TaskExecutor.execute", fake_execute)

    try:
        result = await skill.execute("navigate", {"params": {"url": "https://example.com"}})
    finally:
        if original is None:
            tools._loaded_tools.pop("open_url", None)
        else:
            tools._loaded_tools["open_url"] = original

    assert seen["tool_name"] == "open_url"
    assert seen["params"] == {"url": "https://example.com"}
    assert result["success"] is True
    assert result["result"]["status"] == "success"


@pytest.mark.asyncio
async def test_builtin_email_skill_routes_check_through_task_executor(monkeypatch):
    skill = _instantiate_skill(EmailSkill)
    seen: dict[str, object] = {}

    async def get_unread_emails():
        return {"success": True, "count": 3}

    async def fake_execute(self, tool_func, params):
        seen["tool_name"] = getattr(tool_func, "__name__", "")
        seen["params"] = dict(params)
        return {"success": True, "status": "success", "message": "checked"}

    original = tools._loaded_tools.get("get_unread_emails")
    tools._loaded_tools["get_unread_emails"] = get_unread_emails
    monkeypatch.setattr("core.task_executor.TaskExecutor.execute", fake_execute)

    try:
        result = await skill.execute("check", {"params": {}})
    finally:
        if original is None:
            tools._loaded_tools.pop("get_unread_emails", None)
        else:
            tools._loaded_tools["get_unread_emails"] = original

    assert seen["tool_name"] == "get_unread_emails"
    assert seen["params"] == {}
    assert result["success"] is True
    assert result["result"]["status"] == "success"


@pytest.mark.asyncio
async def test_builtin_office_skill_routes_excel_and_normalizes_pdf_failure(monkeypatch):
    skill = _instantiate_skill(OfficeSkill)
    seen: dict[str, object] = {}

    async def write_excel(path: str | None = None, data=None, **_kwargs):
        return {"success": True, "path": path, "rows": data}

    async def fake_execute(self, tool_func, params):
        seen["tool_name"] = getattr(tool_func, "__name__", "")
        seen["params"] = dict(params)
        return {"success": True, "status": "success", "message": "excel-ok"}

    original = tools._loaded_tools.get("write_excel")
    tools._loaded_tools["write_excel"] = write_excel
    monkeypatch.setattr("core.task_executor.TaskExecutor.execute", fake_execute)

    try:
        excel = await skill.execute("excel", {"params": {"path": "/tmp/out.xlsx", "data": [{"a": 1}]}})
        pdf = await skill.execute("pdf", {"params": {"path": "/tmp/out.pdf", "content": "demo"}})
    finally:
        if original is None:
            tools._loaded_tools.pop("write_excel", None)
        else:
            tools._loaded_tools["write_excel"] = original

    assert seen["tool_name"] == "write_excel"
    assert seen["params"] == {"path": "/tmp/out.xlsx", "data": [{"a": 1}]}
    assert excel["success"] is True
    assert excel["result"]["status"] == "success"
    assert pdf["success"] is False
    assert pdf["result"]["status"] == "failed"
    assert pdf["result"]["error_code"] == "UNKNOWN_TOOL"


@pytest.mark.asyncio
async def test_builtin_research_skill_routes_scrape_and_normalizes_malformed_output(monkeypatch):
    skill = _instantiate_skill(ResearchSkill)
    seen: dict[str, object] = {}

    async def scrape_page(url: str = "", selectors=None):
        _ = selectors
        return None

    async def fake_execute(self, tool_func, params):
        seen["tool_name"] = getattr(tool_func, "__name__", "")
        seen["params"] = dict(params)
        return {
            "success": False,
            "status": "failed",
            "error": "legacy tool returned None",
            "error_code": "TOOL_CONTRACT_VIOLATION",
        }

    original = tools._loaded_tools.get("scrape_page")
    tools._loaded_tools["scrape_page"] = scrape_page
    monkeypatch.setattr("core.task_executor.TaskExecutor.execute", fake_execute)

    try:
        result = await skill.execute("scrape", {"params": {"url": "https://example.com"}})
    finally:
        if original is None:
            tools._loaded_tools.pop("scrape_page", None)
        else:
            tools._loaded_tools["scrape_page"] = original

    assert seen["tool_name"] == "scrape_page"
    assert seen["params"] == {"url": "https://example.com"}
    assert result["success"] is False
    assert result["result"]["status"] == "failed"
    assert result["result"]["error_code"] == "TOOL_CONTRACT_VIOLATION"
