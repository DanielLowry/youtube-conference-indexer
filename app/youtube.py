import datetime
import time

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import isodate
from .config import settings

_current_api_key = settings.youtube_api_key
_last_validation_ok: bool | None = None
_last_validation_message: str | None = None


def set_api_key(key: str):
    global _current_api_key, _last_validation_ok, _last_validation_message
    _current_api_key = key
    _last_validation_ok = None
    _last_validation_message = None
    return _current_api_key


def get_api_key():
    return _current_api_key


def has_valid_key():
    if _last_validation_ok is False:
        return False
    try:
        _validate_api_key()
        if _last_validation_ok is True:
            return True
        return True
    except RuntimeError:
        return False


def _validate_api_key():
    key = _current_api_key
    if not key or "your_api_key_here" in key:
        raise RuntimeError("YouTube API key is missing or invalid. Set YOUTUBE_API_KEY in .env.")
    return key


def get_youtube_service():
    key = _validate_api_key()
    try:
        return build('youtube', 'v3', developerKey=key)
    except HttpError as exc:
        raise RuntimeError(f"YouTube API error: {exc}") from exc


def validate_api_key():
    """
    Make a lightweight call to verify the key.
    Uses Google Developers channel playlists as a cheap probe.
    """
    global _last_validation_ok, _last_validation_message
    try:
        yt = get_youtube_service()
        req = yt.playlists().list(part="id", channelId="UC_x5XG1OV2P6uZZ5FSM9Ttw", maxResults=1)
        req.execute()
        _last_validation_ok = True
        _last_validation_message = "API key validated successfully."
        return True, _last_validation_message
    except Exception as exc:  # noqa: BLE001
        _last_validation_ok = False
        _last_validation_message = f"API key validation failed: {exc}"
        return False, _last_validation_message


def get_last_validation():
    return _last_validation_ok, _last_validation_message


def search_channels(term: str):
    """Find channel suggestions for a loose term (used when a channel id is wrong)."""
    yt = get_youtube_service()
    request = yt.search().list(
        part="snippet",
        q=term,
        type="channel",
        maxResults=5,
    )
    response = request.execute()
    suggestions = []
    for item in response.get("items", []):
        channel_id = item["id"].get("channelId")
        title = item["snippet"].get("title")
        if channel_id:
            suggestions.append({"id": channel_id, "title": title})
    return suggestions


def search_playlists(term: str):
    """Find playlist suggestions for a loose term (used when a playlist id/name is wrong)."""
    yt = get_youtube_service()
    request = yt.search().list(
        part="snippet",
        q=term,
        type="playlist",
        maxResults=5,
    )
    response = request.execute()
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
        # handle; use as search term
        handle = val.split("@", 1)[1]
        return None, handle
    # fallback: treat input as search term
    return None, val


def _execute_with_retries(request, max_attempts: int = 3, base_sleep: float = 1.0):
    for attempt in range(max_attempts):
        try:
            return request.execute()
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            retryable = status in (429, 500, 503)
            if not retryable or attempt == max_attempts - 1:
                raise
            time.sleep(base_sleep * (2 ** attempt))


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
    yt = get_youtube_service()
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
    request = yt.search().list(**params)
    return _execute_with_retries(request)


def videos_list(video_ids: list[str]):
    if not video_ids:
        return []
    yt = get_youtube_service()
    request = yt.videos().list(
        part="snippet,contentDetails",
        id=",".join(video_ids),
        maxResults=min(50, len(video_ids)),
    )
    response = _execute_with_retries(request)
    items = response.get("items", [])
    for item in items:
        duration_iso = item.get("contentDetails", {}).get("duration")
        if duration_iso:
            item.setdefault("contentDetails", {})["duration_seconds"] = _parse_duration_seconds(duration_iso)
        else:
            item.setdefault("contentDetails", {})["duration_seconds"] = 0
    return items

def get_channel_playlists(channel_id: str):
    youtube = get_youtube_service()
    playlists = []
    next_page_token = None
    while True:
        request = youtube.playlists().list(
            part="snippet,contentDetails",
            channelId=channel_id,
            maxResults=50,
            pageToken=next_page_token
        )
        response = request.execute()
        playlists.extend(response.get('items', []))
        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break
    return playlists

def _video_ids_from_playlist_items(items):
    return [item['contentDetails']['videoId'] for item in items]

def get_videos_for_playlist(playlist_id: str):
    youtube = get_youtube_service()
    
    # Get all video IDs from the playlist
    video_ids = []
    next_page_token = None
    while True:
        request = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=next_page_token
        )
        response = request.execute()
        video_ids.extend(_video_ids_from_playlist_items(response.get('items', [])))
        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break

    # Fetch video details in batches of 50
    videos = []
    for i in range(0, len(video_ids), 50):
        batch_ids = video_ids[i:i+50]
        request = youtube.videos().list(
            part="snippet,contentDetails",
            id=",".join(batch_ids)
        )
        response = _execute_with_retries(request)
        for item in response.get('items', []):
            duration_iso = item.get('contentDetails', {}).get('duration')
            item.setdefault('contentDetails', {})['duration_seconds'] = _parse_duration_seconds(duration_iso) if duration_iso else 0
            videos.append(item)

    return videos
