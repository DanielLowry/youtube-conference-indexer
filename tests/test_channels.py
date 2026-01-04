import re

from fastapi.testclient import TestClient


def test_channel_discovery_creates_playlists(client: TestClient, monkeypatch):
    def fake_playlists(channel_id: str):
        return [
            {"id": "PLX", "snippet": {"title": "X", "description": "dx"}},
            {"id": "PLY", "snippet": {"title": "Y", "description": "dy"}},
        ]

    monkeypatch.setattr("app.main.youtube.get_channel_playlists", fake_playlists)

    client.post(
        "/sources",
        data={"name": "CppCon", "type": "channel", "external_id": "UCCHAN1"},
        follow_redirects=True,
    )
    page = client.get("/sources")
    assert "CppCon" in page.text

    match = re.search(r"/sources/(\d+)/discover", page.text)
    assert match, "Source id not found in rendered sources page"
    source_id = match.group(1)

    resp = client.post(f"/sources/{source_id}/discover")
    assert resp.status_code == 200
    assert "X" in resp.text
    assert "Y" in resp.text


def test_channel_autodiscover_on_create_renders_playlists(client: TestClient, monkeypatch):
    def fake_playlists(channel_id: str):
        return [
            {"id": "PL1", "snippet": {"title": "One", "description": "d1"}},
            {"id": "PL2", "snippet": {"title": "Two", "description": "d2"}},
        ]

    monkeypatch.setattr("app.main.youtube.get_channel_playlists", fake_playlists)
    monkeypatch.setattr("app.main.youtube.has_valid_key", lambda: True)

    resp = client.post(
        "/sources",
        data={"name": "CppCon", "type": "channel", "external_id": "UCCHAN1"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "One" in resp.text
    assert "Two" in resp.text


def test_channel_add_prompts_selection(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        "app.main.youtube.search_channels",
        lambda term: [{"id": "UCX", "title": "Match X"}, {"id": "UCY", "title": "Match Y"}],
    )
    resp = client.post(
        "/sources",
        data={"name": "Something", "type": "channel", "external_id": "CppCon"},
    )
    assert resp.status_code == 200
    assert "Match X" in resp.text
    assert "Use this channel" in resp.text


def test_channel_add_autopicks_clear_match(client: TestClient, app_ctx, monkeypatch):
    def _suggest(term):
        return [{"id": "UC123", "title": "CppCon"}]

    monkeypatch.setattr("app.main.youtube.search_channels", _suggest)
    resp = client.post(
        "/sources",
        data={"name": "CppCon", "type": "channel", "external_id": "CppCon"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    session = app_ctx["SessionLocal"]()
    try:
        found = session.query(app_ctx["models"].Source).filter_by(external_id="UC123").first()
        assert found is not None
        assert found.name == "CppCon"
    finally:
        session.close()


def test_channel_add_requires_api_key(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.main.youtube.has_valid_key", lambda: False)
    resp = client.post(
        "/sources",
        data={"name": "CppCon", "type": "channel", "external_id": "CppCon"},
    )
    assert resp.status_code == 400
    assert "valid YouTube API key" in resp.text


def test_discover_channel_error_is_shown(client: TestClient, monkeypatch):
    client.post(
        "/sources",
        data={"name": "BadChannel", "type": "channel", "external_id": "UCBAD"},
        follow_redirects=True,
    )

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
