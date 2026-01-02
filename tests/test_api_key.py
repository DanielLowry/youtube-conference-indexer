from fastapi.testclient import TestClient


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
