import pytest

flask = pytest.importorskip("flask")
Flask = flask.Flask

from api.privacy_api import create_privacy_blueprint
from core.learning.tiered_learning import TieredLearningHub
from core.privacy.data_governance import PrivacyEngine


def test_privacy_api_consent_and_stats_routes(tmp_path, monkeypatch):
    privacy_engine = PrivacyEngine(db_path=tmp_path / "consent.db", runtime_db_path=tmp_path / "runtime.sqlite3")
    monkeypatch.setattr("api.privacy_api.get_privacy_engine", lambda: privacy_engine)
    monkeypatch.setattr("api.privacy_api.get_tiered_hub", lambda: TieredLearningHub(db_path=tmp_path / "tiered.sqlite3", privacy_engine=privacy_engine))
    app = Flask(__name__)
    app.register_blueprint(create_privacy_blueprint())
    client = app.test_client()

    response = client.post("/api/v1/privacy/consent/user-1", json={"granted": True, "allow_personal_data_learning": True})
    assert response.status_code == 200
    body = response.get_json()
    assert body["consent"]["granted"] is True

    get_response = client.get("/api/v1/privacy/consent/user-1")
    assert get_response.status_code == 200
    stats = client.get("/api/v1/privacy/learning/stats")
    assert stats.status_code == 200
