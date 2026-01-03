import sys

from fastapi.testclient import TestClient

from tests.conftest import _MODULES_TO_CLEAR


def test_app_starts_without_api_key(monkeypatch, tmp_path):
    """App should render home without crashing when no API key is set."""
    for module in _MODULES_TO_CLEAR:
        sys.modules.pop(module, None)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

    from app import main as main_module  # noqa: WPS433

    client = TestClient(main_module.app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "No valid YouTube API key configured" in resp.text


def test_api_key_validation_success(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.main.youtube.validate_api_key", lambda: (True, "Key OK"))
    resp = client.post("/api-key", data={"key": "abc"}, follow_redirects=True)
    assert resp.status_code == 200
    assert "Key OK" in resp.text
    assert "API key status" in resp.text


def test_api_key_validation_failure(client: TestClient, monkeypatch):
    def _fail():
        return False, "Bad key"

    monkeypatch.setattr("app.main.youtube.validate_api_key", _fail)
    resp = client.post("/api-key", data={"key": "bad-key"})
    assert resp.status_code == 400
    assert "Bad key" in resp.text
