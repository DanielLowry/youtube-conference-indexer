"""Tests for multi-key YouTube API execution and quota accounting."""

from pathlib import Path

from googleapiclient.errors import HttpError

from app import youtube
from app.api_keys import ApiKeyStore


def test_search_falls_back_to_secondary_key_and_tracks_usage(monkeypatch, tmp_path: Path):
    store = ApiKeyStore(str(tmp_path / "api_keys.json"))
    monkeypatch.setattr(youtube, "api_key_store", store)
    monkeypatch.setattr(youtube, "bootstrap_api_keys", lambda: None)

    primary = store.upsert_key("primary-key-12345678", label="Primary key", make_primary=True)
    secondary = store.upsert_key("secondary-key-12345678", label="Secondary key", make_primary=False)

    def fake_build(service_name: str, version: str, developerKey: str):
        assert service_name == "youtube"
        assert version == "v3"
        return _FakeYoutubeService(developerKey)

    monkeypatch.setattr(youtube, "build", fake_build)

    response = youtube.search_list(query="allocators", max_results=5)

    assert response["items"][0]["id"]["videoId"] == "VID1"

    dashboard = youtube.list_api_keys_dashboard()
    by_label = {item["label"]: item for item in dashboard["keys"]}
    assert by_label["Primary key"]["quota_exhausted_today"] is True
    assert by_label["Primary key"]["today_quota_units"] == 0
    assert by_label["Secondary key"]["today_quota_units"] == youtube.SEARCH_LIST_QUOTA_COST
    assert by_label["Secondary key"]["today_request_count"] == 1
    assert primary.id != secondary.id


class _FakeYoutubeService:
    def __init__(self, key: str):
        self.key = key

    def search(self):
        return _FakeSearchResource(self.key)


class _FakeSearchResource:
    def __init__(self, key: str):
        self.key = key

    def list(self, **kwargs):
        return _FakeRequest(self.key, kwargs)


class _FakeRequest:
    def __init__(self, key: str, kwargs: dict):
        self.key = key
        self.kwargs = kwargs

    def execute(self):
        if self.key.startswith("primary-key"):
            raise _quota_exceeded_http_error()
        assert self.kwargs["q"] == "allocators"
        return {"items": [{"id": {"videoId": "VID1"}}], "nextPageToken": None}


def _quota_exceeded_http_error() -> HttpError:
    class _Resp:
        status = 403
        reason = "Forbidden"

    return HttpError(
        _Resp(),
        b'{"error":{"message":"Quota exceeded","errors":[{"reason":"quotaExceeded","message":"Quota exceeded"}]}}',
    )
