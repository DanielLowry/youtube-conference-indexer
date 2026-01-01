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


def test_channel_discovery_creates_playlists(client: TestClient, monkeypatch):
    def fake_playlists(channel_id: str):
        return [
            {"id": "PLX", "snippet": {"title": "X", "description": "dx"}},
            {"id": "PLY", "snippet": {"title": "Y", "description": "dy"}},
        ]

    monkeypatch.setattr("app.main.youtube.get_channel_playlists", fake_playlists)

    client.post(
        "/sources",
        data={"name": "CppCon", "type": "channel", "external_id": "CHAN1"},
        follow_redirects=True,
    )
    page = client.get("/sources")
    assert "CppCon" in page.text

    import re

    match = re.search(r"/sources/(\d+)/discover", page.text)
    assert match, "Source id not found in rendered sources page"
    source_id = match.group(1)

    resp = client.post(f"/sources/{source_id}/discover")
    assert resp.status_code == 200
    assert "X" in resp.text
    assert "Y" in resp.text
