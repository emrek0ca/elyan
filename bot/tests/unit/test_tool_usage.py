from core.tool_usage import record_tool_usage, get_tool_usage_snapshot, reset_tool_usage


def test_tool_usage_snapshot_tracks_counts_and_rates():
    reset_tool_usage()
    record_tool_usage("list_files", success=True, latency_ms=20, source="agent")
    record_tool_usage("list_files", success=False, latency_ms=40, source="agent", error="boom")

    snap = get_tool_usage_snapshot()
    stats = snap["stats"]["list_files"]
    assert stats["calls"] == 2
    assert stats["success"] == 1
    assert stats["failure"] == 1
    assert stats["success_rate"] == 50.0
    assert stats["last_error"] == "boom"
    assert snap["total_calls"] >= 2
