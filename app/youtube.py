from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import isodate
from .config import settings

_current_api_key = settings.youtube_api_key


def set_api_key(key: str):
    global _current_api_key
    _current_api_key = key
    return _current_api_key


def get_api_key():
    return _current_api_key


def has_valid_key():
    try:
        _validate_api_key()
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
        response = request.execute()
        for item in response.get('items', []):
            duration_iso = item['contentDetails']['duration']
            duration_seconds = isodate.parse_duration(duration_iso).total_seconds()
            item['contentDetails']['duration_seconds'] = int(duration_seconds)
            videos.append(item)

    return videos
