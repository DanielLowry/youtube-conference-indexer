"""API key route tests for the stateless FastAPI adapter."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app import main as main_module
from app.api_keys import ApiKeyStore


@pytest.mark.anyio
async def test_home_shows_missing_api_key_warning(monkeypatch):
    monkeypatch.setattr(main_module.youtube, "bootstrap_api_keys", lambda: None)
    monkeypatch.setattr(
        main_module.youtube,
        "list_api_keys_dashboard",
        lambda history_days=7: {
            "quota_day": "2026-04-06",
            "quota_timezone_label": "America/Los_Angeles",
            "keys": [],
            "has_any_key": False,
            "has_usable_key": False,
        },
    )

    async with _async_client() as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "No valid YouTube API key configured" in response.text


@pytest.mark.anyio
async def test_api_key_validation_success(monkeypatch, tmp_path: Path):
    _configure_api_key_store(monkeypatch, tmp_path)
    monkeypatch.setattr(main_module.youtube, "validate_api_key", lambda key_id=None: (True, "Key OK"))

    async with _async_client() as client:
        response = await client.post(
            "/api-key",
            data={"key": "abc12345", "label": "Project A", "make_primary": "true"},
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert "Key OK" in response.text
    assert "Project A" in response.text
    assert "Dashboard" in response.text


@pytest.mark.anyio
async def test_api_key_validation_failure(monkeypatch, tmp_path: Path):
    _configure_api_key_store(monkeypatch, tmp_path)
    monkeypatch.setattr(main_module.youtube, "validate_api_key", lambda key_id=None: (False, "Bad key"))

    async with _async_client() as client:
        response = await client.post("/api-key", data={"key": "bad-key", "label": "Broken key"})

    assert response.status_code == 400
    assert "Bad key" in response.text
    assert "Broken key" in response.text


@pytest.mark.anyio
async def test_api_key_dashboard_can_switch_primary(monkeypatch, tmp_path: Path):
    store = _configure_api_key_store(monkeypatch, tmp_path)
    key_a = store.upsert_key("key-a-12345678", label="Key A", make_primary=True)
    key_b = store.upsert_key("key-b-12345678", label="Key B", make_primary=False)

    async with _async_client() as client:
        response = await client.post(f"/api-key/{key_b.id}/primary", follow_redirects=True)

    assert response.status_code == 200
    assert "Key B is now the primary API key." in response.text
    dashboard = main_module.youtube.list_api_keys_dashboard()
    primary = next(item for item in dashboard["keys"] if item["is_primary"])
    assert primary["label"] == "Key B"
    assert key_a.id != key_b.id


def _configure_api_key_store(monkeypatch, tmp_path: Path) -> ApiKeyStore:
    store = ApiKeyStore(str(tmp_path / "api_keys.json"))
    monkeypatch.setattr(main_module.youtube, "api_key_store", store)
    monkeypatch.setattr(main_module.youtube, "bootstrap_api_keys", lambda: None)
    return store


def _async_client() -> AsyncClient:
    """Build an AsyncClient backed by the FastAPI ASGI app."""
    transport = ASGITransport(app=main_module.app)
    return AsyncClient(transport=transport, base_url="http://testserver", follow_redirects=False)
