"""YouTube Data API adapter helpers.

Purpose:
- Encapsulate all direct `googleapiclient` interactions for the application.
- Provide small, testable wrapper functions used by extraction services.
- Centralize retries/backoff, API-key selection, and quota usage accounting.

Implementation details:
- Requests are executed through the persisted API key registry.
- Successful calls record estimated quota units against the key that serviced
  the request for the current YouTube quota day.
- When one key hits a quota-exhausted error, the adapter marks it exhausted for
  the day and retries the same request with the next configured key.
"""

from __future__ import annotations

import datetime
import json
import time
from typing import Any, Callable

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import isodate

from .api_keys import ApiKeyRecord, ApiKeyStore
from .config import settings


SEARCH_LIST_QUOTA_COST = 100
PLAYLISTS_LIST_QUOTA_COST = 1
PLAYLIST_ITEMS_LIST_QUOTA_COST = 1
VIDEOS_LIST_QUOTA_COST = 1
QUOTA_EXHAUSTION_REASONS = {
    "dailyLimitExceeded",
    "dailyLimitExceeded402",
    "dailyLimitExceededUnreg",
    "quotaExceeded",
    "quotaExceeded402",
}

api_key_store = ApiKeyStore(settings.youtube_api_keys_path)
_last_validation_ok: bool | None = None
_last_validation_message: str | None = None


def bootstrap_api_keys() -> None:
    """Seed the persisted registry from the legacy env var if needed."""
    api_key_store.ensure_seed_key(settings.youtube_api_key)


def add_api_key(key: str, label: str | None = None, make_primary: bool = False) -> ApiKeyRecord:
    """Persist a new key or refresh an existing one."""
    bootstrap_api_keys()
    return api_key_store.upsert_key(api_key=key, label=label, make_primary=make_primary)


def set_api_key(key: str):
    """Backward-compatible single-key setter used by the existing route/tests."""
    record = add_api_key(key=key, label="Primary key", make_primary=True)
    return record.api_key


def delete_api_key(key_id: str) -> bool:
    """Delete one stored key."""
    bootstrap_api_keys()
    return api_key_store.delete_key(key_id)


def set_primary_api_key(key_id: str) -> ApiKeyRecord:
    """Promote one stored key to primary."""
    bootstrap_api_keys()
    return api_key_store.set_primary(key_id)


def list_api_keys_dashboard(history_days: int = 7) -> dict[str, Any]:
    """Return UI-ready dashboard data for the API keys page."""
    bootstrap_api_keys()
    return api_key_store.dashboard(history_days=history_days)


def get_primary_api_key_summary() -> dict[str, Any] | None:
    """Return a compact summary for the currently configured primary key."""
    dashboard = list_api_keys_dashboard(history_days=3)
    for item in dashboard["keys"]:
        if item["is_primary"]:
            return item
    return None


def get_api_key():
    """Return the configured primary key secret, if any."""
    bootstrap_api_keys()
    record = api_key_store.get_primary_key()
    if record:
        return record.api_key
    return ""


def has_valid_key():
    """Return whether the app currently has any usable key to execute with."""
    bootstrap_api_keys()
    return api_key_store.has_usable_key()


def _validate_api_key_value(key: str) -> str:
    if not key or "your_api_key_here" in key:
        raise RuntimeError("YouTube API key is missing or invalid. Set one on /api-key or in .env.")
    return key


def get_youtube_service():
    """Return a service bound to the best currently available key."""
    bootstrap_api_keys()
    candidates = api_key_store.get_candidate_keys()
    if not candidates:
        raise RuntimeError("No usable YouTube API key configured. Add one on /api-key.")
    return _build_youtube_service(candidates[0].api_key)


def validate_api_key(key_id: str | None = None):
    """Make a lightweight probe call to verify one stored API key."""
    global _last_validation_ok, _last_validation_message

    bootstrap_api_keys()
    record = api_key_store.get_key(key_id) if key_id else api_key_store.get_primary_key()
    if not record:
        _last_validation_ok = False
        _last_validation_message = "No YouTube API key configured."
        return False, _last_validation_message
    try:
        _execute_for_specific_key(
            record=record,
            request_builder=lambda yt: yt.playlists().list(
                part="id",
                channelId="UC_x5XG1OV2P6uZZ5FSM9Ttw",
                maxResults=1,
            ),
            quota_cost=PLAYLISTS_LIST_QUOTA_COST,
            operation_name="playlists.list.validate",
        )
        _last_validation_ok = True
        _last_validation_message = "API key validated successfully."
        api_key_store.record_validation(record.id, True, _last_validation_message)
        return True, _last_validation_message
    except HttpError as exc:
        _last_validation_ok = False
        error_message = _format_http_error(exc)
        _last_validation_message = f"API key validation failed: {error_message}"
        if _is_quota_exhausted_error(exc):
            api_key_store.mark_quota_exhausted(record.id, error_message)
        else:
            api_key_store.record_validation(record.id, False, _last_validation_message)
        return False, _last_validation_message
    except Exception as exc:  # noqa: BLE001
        _last_validation_ok = False
        _last_validation_message = f"API key validation failed: {exc}"
        api_key_store.record_validation(record.id, False, _last_validation_message)
        return False, _last_validation_message


def get_last_validation():
    return _last_validation_ok, _last_validation_message


def search_channels(term: str):
    """Find channel suggestions for a loose term (used when a channel id is wrong)."""
    response = _execute_with_available_keys(
        request_builder=lambda yt: yt.search().list(
            part="snippet",
            q=term,
            type="channel",
            maxResults=5,
        ),
        quota_cost=SEARCH_LIST_QUOTA_COST,
        operation_name="search.list.channel",
    )
    suggestions = []
    for item in response.get("items", []):
        channel_id = item["id"].get("channelId")
        title = item["snippet"].get("title")
        if channel_id:
            suggestions.append({"id": channel_id, "title": title})
    return suggestions


def search_playlists(term: str):
    """Find playlist suggestions for a loose term (used when a playlist id/name is wrong)."""
    response = _execute_with_available_keys(
        request_builder=lambda yt: yt.search().list(
            part="snippet",
            q=term,
            type="playlist",
            maxResults=5,
        ),
        quota_cost=SEARCH_LIST_QUOTA_COST,
        operation_name="search.list.playlist",
    )
    suggestions = []
    for item in response.get("items", []):
        playlist_id = item["id"].get("playlistId")
        title = item["snippet"].get("title")
        if playlist_id:
            suggestions.append({"id": playlist_id, "title": title})
    return suggestions


def extract_channel_identifier(value: str):
    """
    Try to extract a UC... channel id from a URL/handle.
    Returns (channel_id, search_term).
    """
    val = value.strip()
    if val.startswith("UC"):
        return val, None
    lowered = val.lower()
    if "youtube.com/channel/" in lowered:
        parts = val.split("/channel/")
        if len(parts) > 1:
            cid = parts[1].split("/")[0]
            if cid.startswith("UC"):
                return cid, None
    if "youtube.com/@".lower() in lowered:
        handle = val.split("@", 1)[1]
        return None, handle
    return None, val


def _execute_for_specific_key(
    record: ApiKeyRecord,
    request_builder: Callable[[Any], Any],
    quota_cost: int,
    operation_name: str,
    max_attempts: int = 3,
    base_sleep: float = 1.0,
):
    """Execute one request against a specific key with transient retries."""
    for attempt in range(max_attempts):
        try:
            service = _build_youtube_service(record.api_key)
            response = request_builder(service).execute()
            api_key_store.record_usage(record.id, quota_cost, operation_name)
            return response
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            retryable = status in (429, 500, 503)
            if not retryable or attempt == max_attempts - 1:
                raise
            time.sleep(base_sleep * (2 ** attempt))


def _execute_with_available_keys(
    request_builder: Callable[[Any], Any],
    quota_cost: int,
    operation_name: str,
    max_attempts: int = 3,
    base_sleep: float = 1.0,
):
    """Execute a request using the primary key first, then fallback keys."""
    bootstrap_api_keys()
    candidates = api_key_store.get_candidate_keys()
    if not candidates:
        raise RuntimeError("No usable YouTube API key configured. Add one on /api-key.")

    last_exception: Exception | None = None
    quota_errors: list[str] = []
    for record in candidates:
        try:
            return _execute_for_specific_key(
                record=record,
                request_builder=request_builder,
                quota_cost=quota_cost,
                operation_name=operation_name,
                max_attempts=max_attempts,
                base_sleep=base_sleep,
            )
        except HttpError as exc:
            last_exception = exc
            if _is_quota_exhausted_error(exc):
                message = _format_http_error(exc)
                api_key_store.mark_quota_exhausted(record.id, message)
                quota_errors.append(f"{record.label}: {message}")
                continue
            raise
        except Exception as exc:  # noqa: BLE001
            last_exception = exc
            raise

    if quota_errors:
        joined = "; ".join(quota_errors)
        raise RuntimeError(f"All configured API keys are quota-exhausted for today. {joined}")
    if last_exception is not None:
        raise last_exception
    raise RuntimeError("No usable YouTube API key configured. Add one on /api-key.")


def _build_youtube_service(key: str):
    normalized_key = _validate_api_key_value(key)
    try:
        return build("youtube", "v3", developerKey=normalized_key)
    except HttpError as exc:
        raise RuntimeError(f"YouTube API error: {exc}") from exc


def _is_quota_exhausted_error(exc: HttpError) -> bool:
    payload = _http_error_payload(exc)
    errors = payload.get("error", {}).get("errors", [])
    for error in errors:
        reason = error.get("reason")
        if reason in QUOTA_EXHAUSTION_REASONS:
            return True
    message = str(payload.get("error", {}).get("message", "")).lower()
    return "quota" in message and "exceed" in message


def _http_error_payload(exc: HttpError) -> dict[str, Any]:
    content = getattr(exc, "content", None)
    if not content:
        return {}
    try:
        if isinstance(content, bytes):
            return json.loads(content.decode("utf-8"))
        if isinstance(content, str):
            return json.loads(content)
    except Exception:  # noqa: BLE001
        return {}
    return {}


def _format_http_error(exc: HttpError) -> str:
    payload = _http_error_payload(exc)
    message = payload.get("error", {}).get("message")
    if message:
        return str(message)
    return str(exc)


def _to_rfc3339(dt_value: datetime.datetime) -> str:
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=datetime.UTC)
    dt_value = dt_value.astimezone(datetime.UTC)
    return dt_value.isoformat().replace("+00:00", "Z")


def _parse_duration_seconds(duration_iso: str) -> int:
    try:
        return int(isodate.parse_duration(duration_iso).total_seconds())
    except Exception:
        return 0


def search_list(
    query: str,
    channel_id: str | None = None,
    published_after: datetime.datetime | None = None,
    published_before: datetime.datetime | None = None,
    video_duration: str | None = None,
    order_by: str | None = None,
    region_code: str | None = None,
    relevance_language: str | None = None,
    safe_search: str | None = None,
    page_token: str | None = None,
    max_results: int = 50,
):
    params = {
        "part": "snippet",
        "type": "video",
        "q": query,
        "maxResults": max_results,
        "order": order_by or "relevance",
    }
    if channel_id:
        params["channelId"] = channel_id
    if published_after:
        params["publishedAfter"] = _to_rfc3339(published_after)
    if published_before:
        params["publishedBefore"] = _to_rfc3339(published_before)
    if video_duration and video_duration != "any":
        params["videoDuration"] = video_duration
    if region_code:
        params["regionCode"] = region_code
    if relevance_language:
        params["relevanceLanguage"] = relevance_language
    if safe_search:
        safe_value = safe_search.lower()
        if safe_value in ("none", "moderate", "strict"):
            params["safeSearch"] = safe_value
    if page_token:
        params["pageToken"] = page_token
    return _execute_with_available_keys(
        request_builder=lambda yt: yt.search().list(**params),
        quota_cost=SEARCH_LIST_QUOTA_COST,
        operation_name="search.list",
    )


def videos_list(video_ids: list[str]):
    if not video_ids:
        return []
    response = _execute_with_available_keys(
        request_builder=lambda yt: yt.videos().list(
            part="snippet,contentDetails",
            id=",".join(video_ids),
            maxResults=min(50, len(video_ids)),
        ),
        quota_cost=VIDEOS_LIST_QUOTA_COST,
        operation_name="videos.list",
    )
    items = response.get("items", [])
    for item in items:
        duration_iso = item.get("contentDetails", {}).get("duration")
        if duration_iso:
            item.setdefault("contentDetails", {})["duration_seconds"] = _parse_duration_seconds(duration_iso)
        else:
            item.setdefault("contentDetails", {})["duration_seconds"] = 0
    return items


def playlist_items_list(
    playlist_id: str,
    page_token: str | None = None,
    max_results: int = 50,
):
    """Fetch one playlistItems page (contentDetails only) with retries."""
    return _execute_with_available_keys(
        request_builder=lambda yt: yt.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=max_results,
            pageToken=page_token,
        ),
        quota_cost=PLAYLIST_ITEMS_LIST_QUOTA_COST,
        operation_name="playlistItems.list",
    )


def get_channel_playlists(channel_id: str):
    """Return all playlists for a channel (eagerly loaded)."""
    playlists = []
    next_page_token = None
    while True:
        response = _execute_with_available_keys(
            request_builder=lambda yt: yt.playlists().list(
                part="snippet,contentDetails",
                channelId=channel_id,
                maxResults=50,
                pageToken=next_page_token,
            ),
            quota_cost=PLAYLISTS_LIST_QUOTA_COST,
            operation_name="playlists.list",
        )
        playlists.extend(response.get("items", []))
        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break
    return playlists


def _video_ids_from_playlist_items(items):
    """Extract `videoId` values from playlistItems payloads."""
    return [item["contentDetails"]["videoId"] for item in items]


def get_videos_for_playlist(playlist_id: str):
    """Fetch full video metadata for all IDs in a playlist."""
    video_ids = []
    next_page_token = None
    while True:
        response = playlist_items_list(
            playlist_id=playlist_id,
            page_token=next_page_token,
            max_results=50,
        )
        video_ids.extend(_video_ids_from_playlist_items(response.get("items", [])))
        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    videos = []
    for i in range(0, len(video_ids), 50):
        batch_ids = video_ids[i:i + 50]
        response = _execute_with_available_keys(
            request_builder=lambda yt: yt.videos().list(
                part="snippet,contentDetails",
                id=",".join(batch_ids),
            ),
            quota_cost=VIDEOS_LIST_QUOTA_COST,
            operation_name="videos.list.playlist",
        )
        for item in response.get("items", []):
            duration_iso = item.get("contentDetails", {}).get("duration")
            item.setdefault("contentDetails", {})["duration_seconds"] = _parse_duration_seconds(duration_iso) if duration_iso else 0
            videos.append(item)

    return videos
