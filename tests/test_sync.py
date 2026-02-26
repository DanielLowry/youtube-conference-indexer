import pytest

pytestmark = pytest.mark.skip(reason="Legacy DB-backed sync workflow was removed in stateless migration.")

from fastapi.testclient import TestClient

from app import crud, schemas
from app import state
from app.services import sync as sync_service
import datetime
from fastapi import BackgroundTasks


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


def test_auto_sync_queues_all_playlists_even_unpinned(app_ctx):
    session = app_ctx["SessionLocal"]()
    try:
        src = app_ctx["models"].Source(type="channel", external_id="SRC1", name="S")
        session.add(src)
        session.flush()
        p1 = app_ctx["models"].Playlist(source_id=src.id, external_id="P1", title="One", pinned=False)
        p2 = app_ctx["models"].Playlist(source_id=src.id, external_id="P2", title="Two", pinned=True)
        session.add_all([p1, p2])
        session.commit()
        pid1, pid2 = p1.id, p2.id
    finally:
        session.close()

    # reset state
    state.playlist_sync_status.clear()
    state.playlist_cancelled.clear()
    state.sync_in_progress = False
    state.last_auto_sync_at = None
    state.sync_steps_done = 0
    state.sync_steps_total = 0
    state.active_sync_jobs = 0
    state.total_sync_jobs = 0

    bg = BackgroundTasks()
    sync_service.queue_auto_sync(bg)

    assert state.sync_in_progress is True
    assert state.total_sync_jobs == 2
    assert state.active_sync_jobs == 2
    assert state.get_playlist_status(pid1)["state"] == "queued"
    assert state.get_playlist_status(pid2)["state"] == "queued"
    # ensure we queued both, pinned prioritized but included both
    queued_ids = {task.args[0] for task in bg.tasks}
    assert {pid1, pid2} == queued_ids

    # cleanup
    state.sync_in_progress = False
    state.active_sync_jobs = 0
    state.total_sync_jobs = 0


def test_auto_sync_throttles_when_recent_and_no_new_playlists(app_ctx):
    session = app_ctx["SessionLocal"]()
    try:
        src = app_ctx["models"].Source(type="channel", external_id="SRC2", name="S2")
        session.add(src)
        session.flush()
        now = datetime.datetime.now(datetime.UTC)
        playlist = app_ctx["models"].Playlist(
            source_id=src.id,
            external_id="P3",
            title="Three",
            pinned=False,
            last_synced_at=now,
        )
        session.add(playlist)
        session.commit()
    finally:
        session.close()

    state.playlist_sync_status.clear()
    state.sync_in_progress = False
    state.last_auto_sync_at = datetime.datetime.now(datetime.UTC)

    bg = BackgroundTasks()
    sync_service.queue_auto_sync(bg)

    # throttled: no tasks queued, state unchanged
    assert state.sync_in_progress is False
    assert not bg.tasks
    assert not state.playlist_sync_status
