import datetime
import time

# Core app state (shared across routes/services)
sync_error_message = None
api_key_status_message = None
api_key_validation_ok = None
db_health_ok = None
db_health_error = None

AUTO_SYNC_INTERVAL_MINUTES = 30
last_auto_sync_at = None
sync_in_progress = False
active_sync_jobs = 0
total_sync_jobs = 0
last_sync_started_at = None
last_sync_completed_at = None
sync_message = ""
sync_steps_done = 0
sync_steps_total = 0

# Playlist discovery + sync tracking
playlist_discover_cache: dict[int, dict] = {}
PLAYLIST_DISCOVER_CACHE_TTL_SECONDS = 3600
playlist_sync_status: dict[int, dict] = {}
playlist_cancelled: set[int] = set()


def set_playlist_status(playlist_id: int, state: str, total: int = 0, done: int = 0, message: str = ""):
    playlist_sync_status[playlist_id] = {
        "state": state,
        "total": total,
        "done": done,
        "message": message,
        "updated_at": datetime.datetime.now(datetime.UTC),
    }
    if state == "cancelled":
        playlist_cancelled.add(playlist_id)
    elif state not in ("queued", "fetching"):
        playlist_cancelled.discard(playlist_id)


def get_playlist_status(playlist_id: int):
    return playlist_sync_status.get(
        playlist_id,
        {
            "state": "idle",
            "total": 0,
            "done": 0,
            "message": "",
            "updated_at": None,
        },
    )


def discover_cache_expired(source_id: int) -> bool:
    cached = playlist_discover_cache.get(source_id)
    if not cached:
        return True
    ts = cached.get("ts", 0)
    return (time.time() - ts) > PLAYLIST_DISCOVER_CACHE_TTL_SECONDS


def mark_discover_cache(source_id: int):
    playlist_discover_cache[source_id] = {"ts": time.time()}
