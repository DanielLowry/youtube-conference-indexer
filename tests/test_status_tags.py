from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app import crud, schemas


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
                published_at=datetime.now(UTC),
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
                published_at=datetime.now(UTC),
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
