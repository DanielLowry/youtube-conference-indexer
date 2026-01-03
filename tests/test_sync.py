from fastapi.testclient import TestClient

from app import crud, schemas


def test_sync_background_creates_videos(client: TestClient, app_ctx, monkeypatch):
    def fake_videos(playlist_id: str):
        return [
            {
                "id": "VID1",
                "snippet": {
                    "title": "Test Video",
                    "description": "Desc",
                    "publishedAt": "2024-01-01T00:00:00Z",
                    "channelTitle": "Chan",
                },
                "contentDetails": {"duration_seconds": 120},
            }
        ]

    monkeypatch.setattr("app.main.youtube.get_videos_for_playlist", fake_videos)

    session = app_ctx["SessionLocal"]()
    try:
        source = app_ctx["models"].Source(type="playlist", external_id="PLSYNC", name="SyncPlaylist")
        session.add(source)
        session.flush()
        playlist = app_ctx["models"].Playlist(
            source_id=source.id,
            external_id="PLSYNC",
            title="SyncPlaylist",
            pinned=True,
        )
        session.add(playlist)
        session.commit()
        playlist_id = playlist.id
    finally:
        session.close()

    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.main.crud.get_pinned_playlists",
        lambda db: [SimpleNamespace(id=playlist_id)],
    )

    resp = client.post("/sync/run")
    assert resp.status_code == 200
    assert "Sync started" in resp.text

    from app.services.sync import sync_playlist_videos

    sync_playlist_videos(playlist_id)

    session = app_ctx["SessionLocal"]()
    try:
        video = session.query(app_ctx["models"].Video).filter_by(external_id="VID1").first()
        assert video is not None
        assert video.playlist.external_id == "PLSYNC"
        assert video.duration_seconds == 120
        assert video.playlist.last_synced_at is not None
    finally:
        session.close()


def test_sync_failure_suggests_playlists(monkeypatch):
    from app import main as app_main
    from app import state
    state.sync_error_message = None

    def _fail_videos(_playlist_id: str):
        raise RuntimeError("playlist not found")

    monkeypatch.setattr("app.main.youtube.get_videos_for_playlist", _fail_videos)
    monkeypatch.setattr(
        "app.main.youtube.search_playlists",
        lambda term: [{"id": "P1", "title": "Maybe right one"}],
    )

    session = app_main.database.SessionLocal()
    try:
        src = app_main.models.Source(type="playlist", external_id="BADP", name="Bad")
        session.add(src)
        session.flush()
        playlist = app_main.models.Playlist(
            source_id=src.id,
            external_id="BADP",
            title="Bad",
            pinned=True,
        )
        session.add(playlist)
        session.commit()
        pid = playlist.id
    finally:
        session.close()

    from app.services.sync import sync_playlist_videos
    from app import state

    sync_playlist_videos(pid)
    assert state.sync_error_message is not None
    assert "Maybe right one" in state.sync_error_message
