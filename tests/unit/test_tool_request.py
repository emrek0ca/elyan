"""
tests/unit/test_tool_request.py
ToolRequest / ToolResult log sistemi için birim testleri.
"""
import pytest
import time


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fresh_log():
    """Her test için izole ToolRequestLog örneği."""
    from core.tool_request import ToolRequestLog
    log = ToolRequestLog()
    log._jsonl_enabled = False   # Dosya yazmayı kapat (test ortamı)
    return log


# ── _sanitize_params ──────────────────────────────────────────────────────────

def test_sanitize_params_masks_token():
    from core.tool_request import _sanitize_params
    out = _sanitize_params({"token": "secret123", "path": "~/Desktop"})
    assert out["token"] == "***"
    assert out["path"] == "~/Desktop"


def test_sanitize_params_truncates_long_string():
    from core.tool_request import _sanitize_params
    long_val = "x" * 2000
    out = _sanitize_params({"content": long_val})
    assert len(out["content"]) < 300
    assert "chars more" in out["content"]


def test_sanitize_params_nested_dict():
    from core.tool_request import _sanitize_params
    out = _sanitize_params({"channel": {"token": "abc", "name": "telegram"}})
    assert out["channel"]["token"] == "***"
    assert out["channel"]["name"] == "telegram"


# ── _extract_artifacts ────────────────────────────────────────────────────────

def test_extract_artifacts_from_path_key():
    from core.tool_request import _extract_artifacts
    result = {"path": "/Users/user/Desktop/file.txt", "success": True}
    arts = _extract_artifacts(result)
    assert "/Users/user/Desktop/file.txt" in arts


def test_extract_artifacts_from_list():
    from core.tool_request import _extract_artifacts
    result = {"outputs": ["/tmp/a.docx", "/tmp/b.xlsx"]}
    arts = _extract_artifacts(result)
    assert len(arts) == 2


def test_extract_artifacts_ignores_urls():
    from core.tool_request import _extract_artifacts
    result = {"path": "https://example.com/file.pdf"}
    arts = _extract_artifacts(result)
    assert arts == []


def test_extract_artifacts_deduplicates():
    from core.tool_request import _extract_artifacts
    result = {"path": "/tmp/file.txt", "output_path": "/tmp/file.txt"}
    arts = _extract_artifacts(result)
    assert arts.count("/tmp/file.txt") == 1


# ── start_request / finish_request ───────────────────────────────────────────

def test_start_request_returns_request_with_id():
    log = _fresh_log()
    req = log.start_request("list_files", {"path": "~/Desktop"})
    assert len(req.request_id) == 8
    assert req.tool_name == "list_files"
    assert req.params == {"path": "~/Desktop"}
    assert req.started_at != ""


def test_finish_request_stores_in_ring():
    log = _fresh_log()
    req = log.start_request("write_file", {"path": "/tmp/out.txt"})
    result = {"success": True, "path": "/tmp/out.txt"}
    tr = log.finish_request(req, result, latency_ms=120, success=True)
    assert tr.success is True
    assert tr.latency_ms == 120
    assert "/tmp/out.txt" in tr.artifacts
    records = log.get_recent(limit=10)
    assert len(records) == 1
    assert records[0]["tool"] == "write_file"


def test_finish_request_extracts_error():
    log = _fresh_log()
    req = log.start_request("delete_file", {"path": "/nope/file.txt"})
    result = {"success": False, "error": "File not found"}
    tr = log.finish_request(req, result, latency_ms=5, success=False, error="File not found")
    assert tr.success is False
    assert "not found" in tr.error.lower()


def test_finish_request_captures_contract_verified():
    log = _fresh_log()
    req = log.start_request("write_word", {"content": "hello"})
    result = {"success": True, "path": "/tmp/doc.docx", "_contract_verified": True}
    tr = log.finish_request(req, result, latency_ms=200, success=True)
    assert tr.contract_verified is True


def test_finish_request_captures_contract_failed_and_repair():
    log = _fresh_log()
    req = log.start_request("write_word", {"content": ""})
    repair = [{"action": "retry", "reason": "content_too_short"}]
    result = {
        "success": True,
        "path": "/tmp/doc.docx",
        "_contract_verified": False,
        "_repair_actions": repair,
    }
    tr = log.finish_request(req, result, latency_ms=150, success=True)
    assert tr.contract_verified is False
    assert len(tr.repair_actions) == 1


# ── get_recent ────────────────────────────────────────────────────────────────

def test_get_recent_filters_by_tool_name():
    log = _fresh_log()
    for tool in ["list_files", "write_file", "list_files"]:
        req = log.start_request(tool, {})
        log.finish_request(req, {}, latency_ms=10, success=True)
    records = log.get_recent(tool_name="list_files")
    assert all(r["tool"] == "list_files" for r in records)
    assert len(records) == 2


def test_get_recent_filters_success_only():
    log = _fresh_log()
    for ok in [True, False, True]:
        req = log.start_request("tool_x", {})
        log.finish_request(req, {}, latency_ms=10, success=ok)
    records = log.get_recent(success_only=True)
    assert all(r["success"] for r in records)
    assert len(records) == 2


def test_get_recent_newest_first():
    log = _fresh_log()
    for i in range(3):
        req = log.start_request(f"tool_{i}", {})
        log.finish_request(req, {}, latency_ms=i * 10, success=True)
    records = log.get_recent(limit=3)
    assert records[0]["tool"] == "tool_2"   # newest first


# ── get_stats ─────────────────────────────────────────────────────────────────

def test_get_stats_empty():
    log = _fresh_log()
    stats = log.get_stats()
    assert stats["total"] == 0
    assert stats["success"] == 0


def test_get_stats_counts():
    log = _fresh_log()
    for ok in [True, True, False]:
        req = log.start_request("some_tool", {})
        log.finish_request(req, {}, latency_ms=100, success=ok)
    stats = log.get_stats()
    assert stats["total"] == 3
    assert stats["success"] == 2
    assert stats["failure"] == 1
    assert stats["success_rate_pct"] == pytest.approx(66.7, abs=0.2)


def test_get_stats_avg_latency():
    log = _fresh_log()
    for ms in [100, 200, 300]:
        req = log.start_request("t", {})
        log.finish_request(req, {}, latency_ms=ms, success=True)
    stats = log.get_stats()
    assert stats["avg_latency_ms"] == pytest.approx(200.0, abs=0.1)


def test_get_stats_top_tools():
    log = _fresh_log()
    for tool, count in [("a", 3), ("b", 1), ("c", 2)]:
        for _ in range(count):
            req = log.start_request(tool, {})
            log.finish_request(req, {}, latency_ms=10, success=True)
    stats = log.get_stats()
    top_names = [t["tool"] for t in stats["top_tools"]]
    assert top_names[0] == "a"


def test_get_stats_last_artifact():
    log = _fresh_log()
    req1 = log.start_request("write_file", {"path": "/tmp/a.txt"})
    log.finish_request(req1, {"path": "/tmp/a.txt"}, latency_ms=10, success=True)
    req2 = log.start_request("write_word", {"path": "/tmp/b.docx"})
    log.finish_request(req2, {"path": "/tmp/b.docx"}, latency_ms=10, success=True)
    stats = log.get_stats()
    assert stats["last_artifact"] == "/tmp/b.docx"


def test_get_stats_contract_counts():
    log = _fresh_log()
    for cv in [True, True, False, None]:
        req = log.start_request("w", {})
        res = {"_contract_verified": cv}
        log.finish_request(req, res, latency_ms=10, success=True)
    stats = log.get_stats()
    assert stats["contract_verified"] == 2
    assert stats["contract_failed"] == 1


# ── Singleton ─────────────────────────────────────────────────────────────────

def test_get_tool_request_log_singleton():
    from core.tool_request import get_tool_request_log
    log1 = get_tool_request_log()
    log2 = get_tool_request_log()
    assert log1 is log2


# ── Ring buffer limit ─────────────────────────────────────────────────────────

def test_ring_buffer_does_not_exceed_max():
    from core.tool_request import ToolRequestLog
    log = ToolRequestLog()
    log._jsonl_enabled = False
    # Fill beyond default max (500)
    for i in range(520):
        req = log.start_request("t", {})
        log.finish_request(req, {}, latency_ms=1, success=True)
    # Ring buffer capped at _MAX_RING
    with log._lock:
        assert len(log._ring) <= 500
