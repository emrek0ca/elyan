import pytest

from tools import api_tools


@pytest.mark.asyncio
async def test_api_health_check_returns_deterministic_summary(monkeypatch):
    async def _fake_http_request(url, method="GET", timeout=10, **kwargs):
        _ = (method, timeout, kwargs)
        if "up" in url:
            return {"success": True, "status_code": 200, "duration_ms": 25}
        return {"success": False, "status_code": 503, "duration_ms": 50, "error": "service unavailable"}

    monkeypatch.setattr(api_tools, "http_request", _fake_http_request)

    res = await api_tools.api_health_check(["https://up.example", "https://down.example"])
    assert res["total"] == 2
    assert res["healthy"] == 1
    assert res["unhealthy"] == 1
    assert res["success"] is False
    assert isinstance(res.get("duration_ms"), int)
    assert res["results"]["https://down.example"]["error"] == "service unavailable"


@pytest.mark.asyncio
async def test_api_health_check_handles_empty_input():
    res = await api_tools.api_health_check([])
    assert res["total"] == 0
    assert res["healthy"] == 0
    assert res["unhealthy"] == 0
    assert res["success"] is False
