from fastapi.testclient import TestClient
from app import crud, schemas


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

    # Stub YouTube call used by background sync
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

    session = app_ctx["SessionLocal"]()
    try:
        assert session.query(app_ctx["models"].Playlist).filter_by(pinned=True).count() == 1
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
    import re as _re
    count_match = _re.search(r"Sync started for (\d+) pinned", resp.text)
    assert count_match and count_match.group(1) == "1"

    # Execute the background worker directly to verify sync logic
    from app.main import _sync_playlist_videos

    _sync_playlist_videos(playlist_id)

    session = app_ctx["SessionLocal"]()
    try:
        video = session.query(app_ctx["models"].Video).filter_by(external_id="VID1").first()
        assert video is not None
        assert video.playlist.external_id == "PLSYNC"
        assert video.duration_seconds == 120
        assert video.playlist.last_synced_at is not None
    finally:
        session.close()


def test_update_status_and_tags(client: TestClient, app_ctx):
    session = app_ctx["SessionLocal"]()
    try:
        source = app_ctx["models"].Source(type="playlist", external_id="PLSTAT", name="StatusPlaylist")
        session.add(source)
        session.flush()
        playlist = app_ctx["models"].Playlist(
            source_id=source.id,
            external_id="PLSTAT",
            title="StatusPlaylist",
            pinned=True,
        )
        session.add(playlist)
        session.commit()
        video = crud.create_video(
            session,
            video=schemas.VideoCreate(
                external_id="VIDSTATUS",
                title="Status Video",
                description="Test",
                published_at=__import__("datetime").datetime.utcnow(),
                duration_seconds=60,
                channel_title="Chan",
            ),
            playlist_id=playlist.id,
        )
    finally:
        session.close()

    resp = client.post(
        f"/videos/{video.id}/status",
        data={"status": "watching", "notes": "note", "score": 4},
    )
    assert resp.status_code == 200
    assert "watching" in resp.text

    resp = client.post(f"/videos/{video.id}/tags", data={"tag": "c++"})
    assert resp.status_code == 200
    assert "c++" in resp.text


def test_export_endpoints(client: TestClient, app_ctx):
    session = app_ctx["SessionLocal"]()
    try:
        assert "test.db" in str(session.bind.url)
        from app.config import settings
        assert "test.db" in str(settings.database_url)
        session.execute(app_ctx["models"].video_tags.delete())
        session.query(app_ctx["models"].VideoState).delete()
        session.query(app_ctx["models"].Video).delete()
        session.query(app_ctx["models"].Playlist).delete()
        session.query(app_ctx["models"].Source).delete()
        session.query(app_ctx["models"].Tag).delete()
        session.commit()

        source = app_ctx["models"].Source(type="playlist", external_id="PLEXP", name="ExportPlaylist")
        session.add(source)
        session.flush()
        playlist = app_ctx["models"].Playlist(
            source_id=source.id,
            external_id="PLEXP",
            title="ExportPlaylist",
            pinned=True,
        )
        session.add(playlist)
        session.commit()
        crud.create_video(
            session,
            video=schemas.VideoCreate(
                external_id="VIDEXP",
                title="Export Video",
                description="Export",
                published_at=__import__("datetime").datetime.utcnow(),
                duration_seconds=90,
                channel_title="Chan",
            ),
            playlist_id=playlist.id,
        )
        videos_all = crud.get_videos(session)
        assert len(videos_all) == 1
        assert videos_all[0].state.status == "queued"
        assert len(crud.get_videos(session, status="queued")) == 1
    finally:
        session.close()

    from app import export as export_mod

    session = app_ctx["SessionLocal"]()
    try:
        content = export_mod.generate_markdown_export(crud.get_videos(session, status="queued"))
        assert "Export Video" in content
        content_csv = export_mod.generate_csv_export(crud.get_videos(session, status="queued"))
        assert "Export Video" in content_csv
    finally:
        session.close()

    resp = client.get("/export/markdown?status=queued")
    assert resp.status_code == 200

    resp = client.get("/export/csv?status=queued")
    assert resp.status_code == 200


def test_no_db_mode_toggle_banner(client: TestClient, app_ctx):
    # Switch to memory mode
    client.post("/db/use-memory")
    home = client.get("/")
    assert "NO-DB" in home.text
    assert "in-memory" in home.text.lower()

    # Switch back to primary DB (if available)
    client.post("/db/reconnect")
    home = client.get("/")
    if "NO-DB" in home.text:
        # Reconnect failed; banner should remain
        assert "in-memory" in home.text.lower()
    else:
        assert "NO-DB" not in home.text


def test_search_works_after_db_toggle(client: TestClient, app_ctx):
    # Ensure search works even after switching DB modes (tables must exist)
    client.post("/db/use-memory")
    resp = client.get("/search")
    assert resp.status_code == 200
    # Back to primary
    client.post("/db/reconnect")
    resp = client.get("/search")
    assert resp.status_code == 200


def test_search_handles_special_chars(client: TestClient, app_ctx):
    session = app_ctx["SessionLocal"]()
    try:
        source = app_ctx["models"].Source(type="playlist", external_id="PLFTS", name="FTS")
        session.add(source)
        session.flush()
        playlist = app_ctx["models"].Playlist(
            source_id=source.id,
            external_id="PLFTS",
            title="FTS",
            pinned=False,
        )
        session.add(playlist)
        session.commit()
        crud.create_video(
            session,
            video=schemas.VideoCreate(
                external_id="VIDFTS",
                title="C++ talk",
                description="About C++ templates",
                published_at=__import__("datetime").datetime.utcnow(),
                duration_seconds=100,
                channel_title="Chan",
            ),
            playlist_id=playlist.id,
        )
    finally:
        session.close()

    resp = client.get("/search?q=C%2B%2B")
    assert resp.status_code == 200
    assert "C++ talk" in resp.text


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


def test_discover_channel_error_is_shown(client: TestClient, monkeypatch):
    client.post(
        "/sources",
        data={"name": "BadChannel", "type": "channel", "external_id": "BAD"},
        follow_redirects=True,
    )
    # Force failure
    def _raise(_channel):
        raise RuntimeError("Channel not found")

    monkeypatch.setattr("app.main.youtube.get_channel_playlists", _raise)
    monkeypatch.setattr(
        "app.main.youtube.search_channels",
        lambda term: [{"id": "ALT1", "title": "MaybeThis"}, {"id": "ALT2", "title": "OrThat"}],
    )
    resp = client.post("/sources/1/discover")
    assert resp.status_code == 200
    assert "Channel not found" in resp.text
    assert "ALT1" in resp.text
    assert "MaybeThis" in resp.text


def test_update_status_error_returns_message(client: TestClient, app_ctx, monkeypatch):
    session = app_ctx["SessionLocal"]()
    try:
        source = app_ctx["models"].Source(type="playlist", external_id="PLERR", name="Err")
        session.add(source)
        session.flush()
        playlist = app_ctx["models"].Playlist(
            source_id=source.id,
            external_id="PLERR",
            title="Err",
            pinned=True,
        )
        session.add(playlist)
        session.commit()
        video = crud.create_video(
            session,
            video=schemas.VideoCreate(
                external_id="VIDERR",
                title="Err Video",
                description="Desc",
                published_at=__import__("datetime").datetime.utcnow(),
                duration_seconds=10,
                channel_title="Chan",
            ),
            playlist_id=playlist.id,
        )
    finally:
        session.close()

    def _raise_status(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.main.crud.update_video_state", _raise_status)
    resp = client.post(f"/videos/{video.id}/status", data={"status": "done"})
    assert resp.status_code == 200
    assert "Could not update status" in resp.text


def test_sync_failure_suggests_playlists(monkeypatch):
    from app import main as app_main
    app_main.sync_error_message = None

    def _fail_videos(_playlist_id: str):
        raise RuntimeError("playlist not found")

    monkeypatch.setattr("app.main.youtube.get_videos_for_playlist", _fail_videos)
    monkeypatch.setattr(
        "app.main.youtube.search_playlists",
        lambda term: [{"id": "P1", "title": "Maybe right one"}],
    )

    # Build minimal playlist record in test DB
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

    app_main._sync_playlist_videos(pid)
    assert app_main.sync_error_message is not None
    assert "Maybe right one" in app_main.sync_error_message
