import pytest

pytestmark = pytest.mark.skip(reason="Legacy DB-backed search workflow was removed in stateless migration.")

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app import crud, schemas


def test_search_works_after_db_toggle(client: TestClient, app_ctx):
    client.post("/db/use-memory")
    resp = client.get("/search")
    assert resp.status_code == 200
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
                published_at=datetime.now(UTC),
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
