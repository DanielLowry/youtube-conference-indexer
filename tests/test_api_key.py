"""API key route tests for the stateless FastAPI adapter."""

import pytest
from httpx import ASGITransport, AsyncClient

from app import main as main_module


@pytest.mark.anyio
async def test_home_shows_missing_api_key_warning(monkeypatch):
    monkeypatch.setattr(main_module.youtube, "get_api_key", lambda: "")
    monkeypatch.setattr(main_module.youtube, "has_valid_key", lambda: False)

    async with _async_client() as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "No valid YouTube API key configured" in response.text


@pytest.mark.anyio
async def test_api_key_validation_success(monkeypatch):
    monkeypatch.setattr(main_module.youtube, "validate_api_key", lambda: (True, "Key OK"))

    async with _async_client() as client:
        response = await client.post("/api-key", data={"key": "abc"}, follow_redirects=True)

    assert response.status_code == 200
    assert "Key OK" in response.text
    assert "API key status" in response.text


@pytest.mark.anyio
async def test_api_key_validation_failure(monkeypatch):
    monkeypatch.setattr(main_module.youtube, "validate_api_key", lambda: (False, "Bad key"))

    async with _async_client() as client:
        response = await client.post("/api-key", data={"key": "bad-key"})

    assert response.status_code == 400
    assert "Bad key" in response.text


def _async_client() -> AsyncClient:
    """Build an AsyncClient backed by the FastAPI ASGI app."""
    transport = ASGITransport(app=main_module.app)
    return AsyncClient(transport=transport, base_url="http://testserver", follow_redirects=False)
