import sys
from pathlib import Path

from fastapi.testclient import TestClient


def _fresh_app(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    # Reload app modules so settings pick up test env vars.
    for module in [
        "app.main",
        "app.database",
        "app.config",
        "app.models",
        "app.schemas",
        "app.crud",
        "app.youtube",
    ]:
        sys.modules.pop(module, None)

    from app import main as main_module

    return main_module.app


def test_root_route_renders(tmp_path, monkeypatch):
    app = _fresh_app(tmp_path, monkeypatch)
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "YouTube Conference Indexer" in response.text


def test_sources_page_renders(tmp_path, monkeypatch):
    app = _fresh_app(tmp_path, monkeypatch)
    client = TestClient(app)

    response = client.get("/sources")

    assert response.status_code == 200
    assert "Add New Source" in response.text
