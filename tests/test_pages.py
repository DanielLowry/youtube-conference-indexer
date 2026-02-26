import pytest

pytestmark = pytest.mark.skip(reason="Legacy DB-centric pages were removed in stateless migration.")

from fastapi.testclient import TestClient


def test_root_route_renders(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "YouTube Conference Indexer" in response.text


def test_sources_page_renders(client: TestClient):
    response = client.get("/sources")
    assert response.status_code == 200
    assert "Add New Source" in response.text


def test_playlist_source_creates_playlist(client: TestClient):
    resp = client.post(
        "/sources",
        data={"name": "My Playlist", "type": "playlist", "external_id": "PL123"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "My Playlist" in resp.text
