from app import models


def test_root_route_renders(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "YouTube Conference Indexer" in response.text


def test_sources_page_renders(client):
    response = client.get("/sources")

    assert response.status_code == 200
    assert "Add New Source" in response.text


def test_playlist_source_creates_playlist(app_ctx, client):
    resp = client.post(
        "/sources",
        data={"name": "My Playlist", "type": "playlist", "external_id": "PL123"},
        allow_redirects=True,
    )
    assert resp.status_code == 200

    session = app_ctx["SessionLocal"]()
    try:
        playlists = session.query(models.Playlist).all()
        assert len(playlists) == 1
        assert playlists[0].external_id == "PL123"
        assert playlists[0].title == "My Playlist"
    finally:
        session.close()


def test_channel_discovery_creates_playlists(app_ctx, client, monkeypatch):
    def fake_playlists(channel_id: str):
        return [
            {"id": "PLX", "snippet": {"title": "X", "description": "dx"}},
            {"id": "PLY", "snippet": {"title": "Y", "description": "dy"}},
        ]

    import app.youtube as yt

    monkeypatch.setattr(yt, "get_channel_playlists", fake_playlists)

    client.post(
        "/sources",
        data={"name": "CppCon", "type": "channel", "external_id": "CHAN1"},
        allow_redirects=True,
    )

    session = app_ctx["SessionLocal"]()
    try:
        source = session.query(models.Source).filter(models.Source.external_id == "CHAN1").first()
        resp = client.post(f"/sources/{source.id}/discover")
        assert resp.status_code == 200
        playlists = session.query(models.Playlist).all()
        assert {p.external_id for p in playlists} == {"PLX", "PLY"}
    finally:
        session.close()
