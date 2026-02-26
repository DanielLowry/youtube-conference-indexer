import pytest

pytestmark = pytest.mark.skip(reason="Legacy DB-backed export routes were removed in stateless migration.")

from fastapi.testclient import TestClient

from app import crud, schemas

from datetime import datetime, UTC

def test_export_endpoints(client: TestClient, app_ctx):
    session = app_ctx["SessionLocal"]()
    try:
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
                published_at=datetime.now(UTC),
                duration_seconds=90,
                channel_title="Chan",
            ),
            playlist_id=playlist.id,
        )
    finally:
        session.close()

    from app import export as export_mod

    session = app_ctx["SessionLocal"]()
    try:
        content = export_mod.generate_markdown_export(crud.get_videos(session, status="queued"))
        assert "Export Video" in content
        assert "ExportPlaylist" in content
        assert "Export" in content  # description
        content_csv = export_mod.generate_csv_export(crud.get_videos(session, status="queued"))
        assert "Export Video" in content_csv
        assert "ExportPlaylist" in content_csv
        assert "Export" in content_csv
    finally:
        session.close()

    resp = client.get("/export/markdown?status=queued")
    assert resp.status_code == 200

    resp = client.get("/export/csv?status=queued")
    assert resp.status_code == 200
