import datetime
import logging

from sqlalchemy.orm import Session

from app import database, models, youtube

logger = logging.getLogger(__name__)

MAX_PAGES_HARD_CAP = 50
DEFAULT_MAX_PAGES = 10
DEFAULT_STOP_AFTER_EMPTY_PAGES = 2
DEFAULT_SKIP_EXISTING = True
DEFAULT_REFRESH_EXISTING = False
PER_PAGE_MAX_RESULTS = 50


def create_search_run(db: Session, saved_search_id: int) -> models.SearchRun:
    run = models.SearchRun(saved_search_id=saved_search_id, status="queued")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def run_saved_search(saved_search_id: int) -> int:
    db = database.SessionLocal()
    try:
        saved_search = db.query(models.SavedSearch).filter(models.SavedSearch.id == saved_search_id).first()
        if not saved_search:
            raise ValueError("Saved search not found")
        run = create_search_run(db, saved_search_id=saved_search_id)
        run_id = run.id
    finally:
        db.close()

    execute_search_run(run_id)
    return run_id


def execute_search_run(run_id: int):
    db = database.SessionLocal()
    run = None
    try:
        run = db.query(models.SearchRun).filter(models.SearchRun.id == run_id).first()
        if not run:
            return
        saved_search = run.saved_search
        if not saved_search:
            run.status = "failed"
            run.error_message = "Saved search not found"
            run.finished_at = datetime.datetime.now(datetime.UTC)
            db.commit()
            return
        if run.status == "running":
            logger.info("Search run already running: run_id=%s", run_id)
            return

        if not run.started_at:
            run.started_at = datetime.datetime.now(datetime.UTC)
        run.status = "running"
        db.commit()

        _process_run(db, run, saved_search)

        run.status = "succeeded"
        run.finished_at = datetime.datetime.now(datetime.UTC)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Search run failed run_id=%s", run_id)
        if run:
            run.status = "failed"
            run.error_message = str(exc)
            run.finished_at = datetime.datetime.now(datetime.UTC)
            db.commit()
    finally:
        db.close()


def _process_run(db: Session, run: models.SearchRun, saved_search: models.SavedSearch):
    max_pages = saved_search.max_pages or DEFAULT_MAX_PAGES
    if max_pages < 1:
        max_pages = DEFAULT_MAX_PAGES
    max_pages = min(max_pages, MAX_PAGES_HARD_CAP)
    stop_after_empty_pages = saved_search.stop_after_empty_pages or DEFAULT_STOP_AFTER_EMPTY_PAGES
    if stop_after_empty_pages < 1:
        stop_after_empty_pages = DEFAULT_STOP_AFTER_EMPTY_PAGES

    skip_existing = getattr(saved_search, "skip_existing", DEFAULT_SKIP_EXISTING)
    refresh_existing = getattr(saved_search, "refresh_existing", DEFAULT_REFRESH_EXISTING)

    page_number = run.pages_processed or 0
    next_page_token = run.next_page_token
    empty_pages = 0
    search_requests = 0
    video_requests = 0
    base_quota = run.quota_estimate or 0

    while page_number < max_pages:
        response = youtube.search_list(
            query=saved_search.query,
            channel_id=saved_search.channel_id,
            published_after=saved_search.published_after,
            published_before=saved_search.published_before,
            video_duration=saved_search.video_duration,
            order_by=saved_search.order_by,
            region_code=saved_search.region_code,
            relevance_language=saved_search.relevance_language,
            safe_search=saved_search.safe_search,
            page_token=next_page_token,
            max_results=PER_PAGE_MAX_RESULTS,
        )
        search_requests += 1

        items = response.get("items", [])
        page_number += 1
        run.pages_processed = page_number

        video_ids, rank_map = _extract_video_ids(items, page_number)
        run.results_seen += len(video_ids)

        existing_by_external = _fetch_existing_videos(db, video_ids)
        new_ids = [vid for vid in video_ids if vid not in existing_by_external]

        run.new_video_ids += len(new_ids)
        run.existing_video_ids += len(video_ids) - len(new_ids)

        if not new_ids:
            empty_pages += 1
        else:
            empty_pages = 0

        fetch_ids = _select_fetch_ids(video_ids, new_ids, skip_existing, refresh_existing)
        fetched_items = []
        for batch in _chunks(fetch_ids, PER_PAGE_MAX_RESULTS):
            fetched_items.extend(youtube.videos_list(batch))
            video_requests += 1
        run.videos_fetched += len(fetched_items)

        fetched_at = datetime.datetime.now(datetime.UTC)
        for item in fetched_items:
            _upsert_video_from_item(db, item, existing_by_external, fetched_at=fetched_at)

        db.flush()
        _link_run_videos(db, run.id, video_ids, rank_map, page_number)

        next_page_token = response.get("nextPageToken")
        run.next_page_token = next_page_token
        run.quota_estimate = base_quota + (search_requests * 100) + video_requests
        db.commit()

        if not next_page_token:
            break
        if empty_pages >= stop_after_empty_pages:
            break


def _extract_video_ids(items: list[dict], page_number: int):
    video_ids = []
    rank_map: dict[str, int] = {}
    for idx, item in enumerate(items):
        video_id = None
        item_id = item.get("id")
        if isinstance(item_id, dict):
            video_id = item_id.get("videoId")
        elif isinstance(item_id, str):
            video_id = item_id
        if not video_id or video_id in rank_map:
            continue
        rank_map[video_id] = ((page_number - 1) * PER_PAGE_MAX_RESULTS) + idx + 1
        video_ids.append(video_id)
    return video_ids, rank_map


def _fetch_existing_videos(db: Session, video_ids: list[str]) -> dict[str, models.Video]:
    if not video_ids:
        return {}
    rows = db.query(models.Video).filter(models.Video.external_id.in_(video_ids)).all()
    return {row.external_id: row for row in rows}


def _select_fetch_ids(
    video_ids: list[str],
    new_ids: list[str],
    skip_existing: bool,
    refresh_existing: bool,
):
    if not video_ids:
        return []
    if not skip_existing:
        return list(video_ids)
    if refresh_existing:
        return list(video_ids)
    return list(new_ids)


def _upsert_video_from_item(
    db: Session,
    item: dict,
    existing_by_external: dict[str, models.Video],
    fetched_at: datetime.datetime,
):
    video_id = item.get("id")
    if not video_id:
        return None
    snippet = item.get("snippet") or {}
    content_details = item.get("contentDetails") or {}
    published_at = _parse_published_at(snippet.get("publishedAt"))
    duration_seconds = content_details.get("duration_seconds") or 0

    existing = existing_by_external.get(video_id)
    if not existing:
        existing = db.query(models.Video).filter(models.Video.external_id == video_id).first()
        if existing:
            existing_by_external[video_id] = existing

    if existing:
        existing.title = snippet.get("title")
        existing.description = snippet.get("description")
        existing.published_at = published_at
        existing.duration_seconds = duration_seconds
        existing.channel_title = snippet.get("channelTitle")
        existing.channel_id = snippet.get("channelId")
        existing.fetched_at = fetched_at
        return existing

    video = models.Video(
        playlist_id=None,
        external_id=video_id,
        title=snippet.get("title"),
        description=snippet.get("description"),
        published_at=published_at,
        duration_seconds=duration_seconds,
        channel_title=snippet.get("channelTitle"),
        channel_id=snippet.get("channelId"),
        fetched_at=fetched_at,
    )
    db.add(video)
    db.add(models.VideoState(video=video))
    existing_by_external[video_id] = video
    return video


def _parse_published_at(value: str | None):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _link_run_videos(
    db: Session,
    run_id: int,
    video_ids: list[str],
    rank_map: dict[str, int],
    page_number: int,
):
    if not video_ids:
        return
    rows = db.query(models.Video).filter(models.Video.external_id.in_(video_ids)).all()
    id_map = {row.external_id: row.id for row in rows}
    if not id_map:
        return
    existing_links = db.query(models.SearchRunVideo.video_id).filter(
        models.SearchRunVideo.search_run_id == run_id,
        models.SearchRunVideo.video_id.in_(id_map.values()),
    ).all()
    linked_ids = {row[0] for row in existing_links}
    for video_id in video_ids:
        internal_id = id_map.get(video_id)
        if not internal_id or internal_id in linked_ids:
            continue
        db.add(
            models.SearchRunVideo(
                search_run_id=run_id,
                video_id=internal_id,
                rank_in_search=rank_map.get(video_id),
                page_number=page_number,
            )
        )


def _chunks(items: list[str], size: int):
    for idx in range(0, len(items), size):
        yield items[idx:idx + size]
