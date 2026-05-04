from ui.home_data import MockHomeDataService


def test_mock_home_snapshot_includes_operator_status():
    snapshot = MockHomeDataService().fetch_snapshot()
    assert snapshot.operator_status["status"] == "healthy"
    assert "mobile_dispatch" in snapshot.operator_status["summary"]
    assert snapshot.operator_status["summary"]["speed_runtime"]["current_lane"] == "turbo_lane"
    assert "model_runtime" in snapshot.operator_status["summary"]
