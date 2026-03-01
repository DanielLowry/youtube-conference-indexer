"""Stateless extraction service entry points.

Purpose:
- Provide Python-callable extraction APIs that do not depend on database models.
- Execute extraction runs and persist progress/output artifacts to filesystem.
- Keep one shared business layer for both CLI and FastAPI adapters.

Implementation details:
- All external callers use the service contract:
  - `run_extraction(config: RunConfig) -> RunResult`
  - `resume_extraction(run_id: str) -> RunResult`
- The extractor writes per-page checkpoints through `RunStateStore` so runs can
  be resumed using persisted `run_state.json`.
- Output persistence is delegated to sinks (`JsonlSink`, `CsvSink`) so extractor
  logic remains output-format agnostic.
- Dedupe is intentionally scoped to a run (`seen_ids` set) to avoid global state.
"""

import datetime
import logging

from app import youtube

from .contracts import ExtractionMode, RunConfig, RunResult, RunStatus, VideoRecord
from .run_state import RunStateStore
from .sinks import create_sinks


logger = logging.getLogger(__name__)

PER_PAGE_MAX_RESULTS = 50


def run_extraction(config: RunConfig) -> RunResult:
    """Start a new extraction run and return terminal run state."""
    state_store = RunStateStore(output_root=config.output_root)
    result = state_store.initialize_run(config)
    return _dispatch_mode(
        config=config,
        result=result,
        state_store=state_store,
        seen_ids=set(),
    )


def resume_extraction(run_id: str, output_root: str = "./runs") -> RunResult:
    """Resume a run from `run_state.json` checkpoint data."""
    state_store = RunStateStore(output_root=output_root)
    config, result, seen_ids = state_store.load_state(run_id)
    if result.status == RunStatus.SUCCEEDED:
        return result
    return _dispatch_mode(
        config=config,
        result=result,
        state_store=state_store,
        seen_ids=seen_ids,
    )


def _dispatch_mode(
    config: RunConfig,
    result: RunResult,
    state_store: RunStateStore,
    seen_ids: set[str],
) -> RunResult:
    """Dispatch run execution to the configured source mode handler."""
    if config.mode == ExtractionMode.SEARCH:
        return _execute_search(config=config, result=result, state_store=state_store, seen_ids=seen_ids)
    if config.mode == ExtractionMode.PLAYLIST:
        return _execute_playlist(config=config, result=result, state_store=state_store, seen_ids=seen_ids)
    if config.mode == ExtractionMode.CHANNEL:
        return _execute_channel(config=config, result=result, state_store=state_store, seen_ids=seen_ids)
    return _finalize_failure(
        config=config,
        result=result,
        state_store=state_store,
        seen_ids=seen_ids,
        error_message=f"Unsupported extraction mode: {config.mode}",
    )


def _execute_search(
    config: RunConfig,
    result: RunResult,
    state_store: RunStateStore,
    seen_ids: set[str],
) -> RunResult:
    """Run bounded `search.list` extraction and stream results to sinks."""
    _mark_running(config=config, result=result, state_store=state_store, seen_ids=seen_ids)
    sink = create_sinks(output_dir=result.output_dir, output_formats=config.output_formats)
    try:
        queries = config.resolved_queries
        if result.progress.total_queries == 0:
            result.progress.total_queries = len(queries)
        if not queries:
            return _finalize_success(config=config, result=result, state_store=state_store, seen_ids=seen_ids)

        start_index = min(result.progress.current_query_index, len(queries))
        resume_query = result.progress.current_query
        resume_page_token = result.progress.next_page_token
        for query_index in range(start_index, len(queries)):
            query = queries[query_index]
            result.progress.current_query_index = query_index
            result.progress.current_query = query
            _persist_checkpoint(config=config, result=result, state_store=state_store, seen_ids=seen_ids)

            page_token = None
            item_pages_processed = 0
            if (
                query_index == start_index
                and resume_page_token
                and (not resume_query or resume_query == query)
            ):
                page_token = resume_page_token
                item_pages_processed = max(0, result.progress.current_item_pages_processed)

            consecutive_empty_pages = 0
            while item_pages_processed < config.max_pages:
                response = youtube.search_list(
                    query=query,
                    channel_id=config.channel_id,
                    published_after=config.published_after,
                    published_before=config.published_before,
                    video_duration=config.video_duration,
                    order_by=config.order_by,
                    region_code=config.region_code,
                    relevance_language=config.relevance_language,
                    safe_search=config.safe_search,
                    page_token=page_token,
                    max_results=PER_PAGE_MAX_RESULTS,
                )
                result.progress.quota_estimate += 100

                result.progress.pages_processed += 1
                item_pages_processed += 1
                result.progress.current_item_pages_processed = item_pages_processed
                page_number = result.progress.pages_processed
                page_items = response.get("items", [])
                page_video_ids = _extract_search_video_ids(page_items)

                consecutive_empty_pages = _process_video_ids_for_page(
                    config=config,
                    result=result,
                    state_store=state_store,
                    seen_ids=seen_ids,
                    sink=sink,
                    page_video_ids=page_video_ids,
                    page_number=page_number,
                    source_playlist_id=None,
                    source_channel_id=config.channel_id,
                    source_query=query,
                    consecutive_empty_pages=consecutive_empty_pages,
                )

                page_token = response.get("nextPageToken")
                result.progress.next_page_token = page_token
                _persist_checkpoint(config=config, result=result, state_store=state_store, seen_ids=seen_ids)

                if not page_token:
                    break
                if consecutive_empty_pages >= config.stop_after_empty_pages:
                    break

            result.progress.processed_queries = query_index + 1
            result.progress.current_query_index = query_index + 1
            result.progress.current_query = None
            result.progress.next_page_token = None
            result.progress.current_item_pages_processed = 0
            _persist_checkpoint(config=config, result=result, state_store=state_store, seen_ids=seen_ids)

        return _finalize_success(config=config, result=result, state_store=state_store, seen_ids=seen_ids)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Search extraction failed for run_id=%s", result.run_id)
        return _finalize_failure(
            config=config,
            result=result,
            state_store=state_store,
            seen_ids=seen_ids,
            error_message=str(exc),
        )
    finally:
        sink.close()


def _execute_playlist(
    config: RunConfig,
    result: RunResult,
    state_store: RunStateStore,
    seen_ids: set[str],
) -> RunResult:
    """Run playlist extraction via page-based `playlistItems.list` calls."""
    _mark_running(config=config, result=result, state_store=state_store, seen_ids=seen_ids)
    sink = create_sinks(output_dir=result.output_dir, output_formats=config.output_formats)
    try:
        playlist_ids = config.resolved_playlist_ids
        _run_playlist_sequence(
            config=config,
            result=result,
            state_store=state_store,
            seen_ids=seen_ids,
            sink=sink,
            playlist_ids=playlist_ids,
            source_channel_id=config.channel_id,
        )
        return _finalize_success(config=config, result=result, state_store=state_store, seen_ids=seen_ids)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Playlist extraction failed for run_id=%s", result.run_id)
        return _finalize_failure(
            config=config,
            result=result,
            state_store=state_store,
            seen_ids=seen_ids,
            error_message=str(exc),
        )
    finally:
        sink.close()


def _execute_channel(
    config: RunConfig,
    result: RunResult,
    state_store: RunStateStore,
    seen_ids: set[str],
) -> RunResult:
    """Run channel extraction by scanning each discovered playlist in sequence."""
    _mark_running(config=config, result=result, state_store=state_store, seen_ids=seen_ids)
    sink = create_sinks(output_dir=result.output_dir, output_formats=config.output_formats)
    try:
        channel_id = config.channel_id or ""
        playlists = youtube.get_channel_playlists(channel_id)
        playlist_ids = [item.get("id") for item in playlists if item.get("id")]
        _run_playlist_sequence(
            config=config,
            result=result,
            state_store=state_store,
            seen_ids=seen_ids,
            sink=sink,
            playlist_ids=playlist_ids,
            source_channel_id=channel_id,
        )

        return _finalize_success(config=config, result=result, state_store=state_store, seen_ids=seen_ids)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Channel extraction failed for run_id=%s", result.run_id)
        return _finalize_failure(
            config=config,
            result=result,
            state_store=state_store,
            seen_ids=seen_ids,
            error_message=str(exc),
        )
    finally:
        sink.close()


def _run_playlist_sequence(
    config: RunConfig,
    result: RunResult,
    state_store: RunStateStore,
    seen_ids: set[str],
    sink,
    playlist_ids: list[str],
    source_channel_id: str | None,
) -> None:
    """Scan a playlist list in order with checkpoint-aware resume support."""
    if result.progress.total_playlists == 0:
        result.progress.total_playlists = len(playlist_ids)
    if not playlist_ids:
        return

    start_index = min(result.progress.current_playlist_index, len(playlist_ids))
    resume_playlist_id = result.progress.current_playlist_id
    resume_page_token = result.progress.next_page_token
    for playlist_index in range(start_index, len(playlist_ids)):
        playlist_id = playlist_ids[playlist_index]
        result.progress.current_playlist_index = playlist_index
        result.progress.current_playlist_id = playlist_id
        _persist_checkpoint(config=config, result=result, state_store=state_store, seen_ids=seen_ids)

        resume_token = None
        resume_item_pages = 0
        if (
            playlist_index == start_index
            and resume_playlist_id == playlist_id
            and resume_page_token
        ):
            resume_token = resume_page_token
            resume_item_pages = max(0, result.progress.current_item_pages_processed)

        _scan_playlist_pages(
            config=config,
            result=result,
            state_store=state_store,
            seen_ids=seen_ids,
            sink=sink,
            playlist_id=playlist_id,
            source_channel_id=source_channel_id,
            initial_page_token=resume_token,
            initial_item_pages_processed=resume_item_pages,
        )

        result.progress.processed_playlists = playlist_index + 1
        result.progress.current_playlist_index = playlist_index + 1
        result.progress.current_playlist_id = None
        result.progress.next_page_token = None
        result.progress.current_item_pages_processed = 0
        _persist_checkpoint(config=config, result=result, state_store=state_store, seen_ids=seen_ids)


def _scan_playlist_pages(
    config: RunConfig,
    result: RunResult,
    state_store: RunStateStore,
    seen_ids: set[str],
    sink,
    playlist_id: str,
    source_channel_id: str | None,
    initial_page_token: str | None,
    initial_item_pages_processed: int = 0,
) -> None:
    """Scan playlist pages and stream fetched videos to sinks.

    This helper is reused by playlist mode and channel mode.
    """
    page_token = initial_page_token
    consecutive_empty_pages = 0
    item_pages_processed = max(0, initial_item_pages_processed)

    while item_pages_processed < config.max_pages:
        response = youtube.playlist_items_list(
            playlist_id=playlist_id,
            page_token=page_token,
            max_results=PER_PAGE_MAX_RESULTS,
        )
        result.progress.quota_estimate += 1

        result.progress.pages_processed += 1
        item_pages_processed += 1
        result.progress.current_item_pages_processed = item_pages_processed
        page_number = result.progress.pages_processed
        page_items = response.get("items", [])
        page_video_ids = _extract_playlist_video_ids(page_items)

        consecutive_empty_pages = _process_video_ids_for_page(
            config=config,
            result=result,
            state_store=state_store,
            seen_ids=seen_ids,
            sink=sink,
            page_video_ids=page_video_ids,
            page_number=page_number,
            source_playlist_id=playlist_id,
            source_channel_id=source_channel_id,
            source_query=None,
            consecutive_empty_pages=consecutive_empty_pages,
        )

        page_token = response.get("nextPageToken")
        result.progress.next_page_token = page_token
        _persist_checkpoint(config=config, result=result, state_store=state_store, seen_ids=seen_ids)

        if not page_token:
            break
        if consecutive_empty_pages >= config.stop_after_empty_pages:
            break


def _process_video_ids_for_page(
    config: RunConfig,
    result: RunResult,
    state_store: RunStateStore,
    seen_ids: set[str],
    sink,
    page_video_ids: list[str],
    page_number: int,
    source_playlist_id: str | None,
    source_channel_id: str | None,
    source_query: str | None,
    consecutive_empty_pages: int,
) -> int:
    """Process a page of video IDs: dedupe, fetch metadata, write sink rows."""
    base_rank = result.progress.results_seen
    rank_map = _build_rank_map(page_video_ids, base_rank)
    result.progress.results_seen += len(page_video_ids)

    new_ids, existing_count = _split_new_and_existing_ids(
        page_video_ids=page_video_ids,
        seen_ids=seen_ids,
        dedupe_within_run=config.dedupe_within_run,
    )
    result.progress.existing_video_ids += existing_count
    result.progress.new_video_ids += len(new_ids)

    if not new_ids:
        consecutive_empty_pages += 1
    else:
        consecutive_empty_pages = 0

    fetched_by_id = _fetch_video_details_by_id(new_ids, result)
    for video_id in new_ids:
        if config.dedupe_within_run:
            seen_ids.add(video_id)
        item = fetched_by_id.get(video_id)
        if not item:
            continue
        sink.write_record(
            _item_to_record(
                item=item,
                page_number=page_number,
                rank_in_run=rank_map.get(video_id),
                source_playlist_id=source_playlist_id,
                source_channel_id=source_channel_id,
                source_query=source_query,
            )
        )

    _persist_checkpoint(config=config, result=result, state_store=state_store, seen_ids=seen_ids)
    return consecutive_empty_pages


def _split_new_and_existing_ids(
    page_video_ids: list[str],
    seen_ids: set[str],
    dedupe_within_run: bool,
) -> tuple[list[str], int]:
    """Split current page IDs into new IDs and already-seen count."""
    if not dedupe_within_run:
        return list(page_video_ids), 0
    new_ids = [video_id for video_id in page_video_ids if video_id not in seen_ids]
    existing_count = len(page_video_ids) - len(new_ids)
    return new_ids, existing_count


def _fetch_video_details_by_id(video_ids: list[str], result: RunResult) -> dict[str, dict]:
    """Fetch video metadata in API-sized batches and return an ID->payload map."""
    if not video_ids:
        return {}
    fetched_items = []
    for batch in _chunks(video_ids, PER_PAGE_MAX_RESULTS):
        if not batch:
            continue
        fetched_items.extend(youtube.videos_list(batch))
        result.progress.quota_estimate += 1
    result.progress.videos_fetched += len(fetched_items)
    return {item.get("id"): item for item in fetched_items if item.get("id")}


def _mark_running(
    config: RunConfig,
    result: RunResult,
    state_store: RunStateStore,
    seen_ids: set[str],
) -> None:
    """Mark run status as running and persist checkpoint immediately."""
    result.status = RunStatus.RUNNING
    result.error_message = None
    result.finished_at = None
    _persist_checkpoint(config=config, result=result, state_store=state_store, seen_ids=seen_ids)


def _finalize_success(
    config: RunConfig,
    result: RunResult,
    state_store: RunStateStore,
    seen_ids: set[str],
) -> RunResult:
    """Finalize run as succeeded and persist terminal checkpoint."""
    result.status = RunStatus.SUCCEEDED
    result.finished_at = datetime.datetime.now(datetime.UTC)
    _persist_checkpoint(config=config, result=result, state_store=state_store, seen_ids=seen_ids)
    return result


def _finalize_failure(
    config: RunConfig,
    result: RunResult,
    state_store: RunStateStore,
    seen_ids: set[str],
    error_message: str,
) -> RunResult:
    """Finalize run as failed and persist terminal checkpoint."""
    result.status = RunStatus.FAILED
    result.error_message = error_message
    result.finished_at = datetime.datetime.now(datetime.UTC)
    _persist_checkpoint(config=config, result=result, state_store=state_store, seen_ids=seen_ids)
    return result


def _persist_checkpoint(
    config: RunConfig,
    result: RunResult,
    state_store: RunStateStore,
    seen_ids: set[str],
) -> None:
    """Persist checkpoint and summary in one call for UI/CLI visibility."""
    state_store.write_state(config=config, result=result, seen_ids=seen_ids)
    state_store.write_summary(result=result)


def _extract_search_video_ids(page_items: list[dict]) -> list[str]:
    """Extract unique `videoId` values from `search.list` page items."""
    ids: list[str] = []
    seen: set[str] = set()
    for item in page_items:
        item_id = item.get("id")
        if isinstance(item_id, dict):
            video_id = item_id.get("videoId")
        elif isinstance(item_id, str):
            video_id = item_id
        else:
            video_id = None
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        ids.append(video_id)
    return ids


def _extract_playlist_video_ids(page_items: list[dict]) -> list[str]:
    """Extract unique `videoId` values from `playlistItems.list` payloads."""
    ids: list[str] = []
    seen: set[str] = set()
    for item in page_items:
        video_id = item.get("contentDetails", {}).get("videoId")
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        ids.append(video_id)
    return ids


def _build_rank_map(video_ids: list[str], base_rank: int) -> dict[str, int]:
    """Build a run-relative rank map based on previously seen result count."""
    return {
        video_id: base_rank + index + 1
        for index, video_id in enumerate(video_ids)
    }


def _item_to_record(
    item: dict,
    page_number: int,
    rank_in_run: int | None,
    source_playlist_id: str | None,
    source_channel_id: str | None,
    source_query: str | None,
) -> VideoRecord:
    """Normalize raw `videos.list` payload into a `VideoRecord`."""
    snippet = item.get("snippet", {})
    details = item.get("contentDetails", {})
    return VideoRecord(
        external_id=item.get("id", ""),
        title=snippet.get("title"),
        description=snippet.get("description"),
        published_at=_parse_published_at(snippet.get("publishedAt")),
        duration_seconds=details.get("duration_seconds") or 0,
        channel_id=snippet.get("channelId"),
        channel_title=snippet.get("channelTitle"),
        source_playlist_id=source_playlist_id,
        source_channel_id=source_channel_id,
        source_query=source_query,
        rank_in_run=rank_in_run,
        page_number=page_number,
    )


def _parse_published_at(value: str | None):
    """Parse YouTube timestamp strings into timezone-aware datetimes."""
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _chunks(items: list[str], size: int):
    """Yield fixed-size chunks to satisfy YouTube API batch limits."""
    for index in range(0, len(items), size):
        yield items[index:index + size]
