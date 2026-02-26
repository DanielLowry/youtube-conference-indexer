"""Stateless extraction service entry points.

Purpose:
- Provide Python-callable extraction APIs that do not depend on SQLAlchemy/DB.
- Execute bounded extraction runs and persist outputs/checkpoints to files.
- Serve as the shared business layer for future CLI and FastAPI adapters.

Implementation details:
- Uses contracts from `app.services.contracts` as the only public API surface.
- Uses `RunStateStore` for checkpoint persistence (`run_state.json`, `summary.json`).
- Uses sink abstractions to stream normalized `VideoRecord` rows to files.
- Phase 2 scope intentionally implements `search` mode first; playlist/channel
  are explicit placeholders for Phase 3 parity work.
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
    """Start a new stateless extraction run and return its terminal state."""
    state_store = RunStateStore(output_root=config.output_root)
    result = state_store.initialize_run(config)
    if config.mode == ExtractionMode.SEARCH:
        return _execute_search(config=config, result=result, state_store=state_store, seen_ids=set())
    return _mark_unimplemented_mode(config=config, result=result, state_store=state_store)


def resume_extraction(run_id: str, output_root: str = "./runs") -> RunResult:
    """Resume an interrupted run from persisted `run_state.json` checkpoint."""
    state_store = RunStateStore(output_root=output_root)
    config, result, seen_ids = state_store.load_state(run_id)
    if result.status == RunStatus.SUCCEEDED:
        return result
    if config.mode == ExtractionMode.SEARCH:
        return _execute_search(config=config, result=result, state_store=state_store, seen_ids=seen_ids)
    return _mark_unimplemented_mode(config=config, result=result, state_store=state_store)


def _execute_search(
    config: RunConfig,
    result: RunResult,
    state_store: RunStateStore,
    seen_ids: set[str],
) -> RunResult:
    """Run bounded search extraction with per-page checkpoint persistence."""
    result.status = RunStatus.RUNNING
    if not result.started_at:
        result.started_at = datetime.datetime.now(datetime.UTC)
    state_store.write_state(config=config, result=result, seen_ids=seen_ids)

    sink = create_sinks(output_dir=result.output_dir, output_formats=config.output_formats)
    try:
        page_number = result.progress.pages_processed
        next_page_token = result.progress.next_page_token
        consecutive_empty_pages = 0

        while page_number < config.max_pages:
            response = youtube.search_list(
                query=config.query or "",
                channel_id=config.channel_id,
                published_after=config.published_after,
                published_before=config.published_before,
                video_duration=config.video_duration,
                order_by=config.order_by,
                region_code=config.region_code,
                relevance_language=config.relevance_language,
                safe_search=config.safe_search,
                page_token=next_page_token,
                max_results=PER_PAGE_MAX_RESULTS,
            )
            result.progress.quota_estimate += 100

            page_items = response.get("items", [])
            page_number += 1
            result.progress.pages_processed = page_number

            page_video_ids, rank_map = _extract_video_ids(page_items=page_items, page_number=page_number)
            result.progress.results_seen += len(page_video_ids)

            if config.dedupe_within_run:
                new_ids = [video_id for video_id in page_video_ids if video_id not in seen_ids]
                existing_count = len(page_video_ids) - len(new_ids)
            else:
                new_ids = list(page_video_ids)
                existing_count = 0

            result.progress.existing_video_ids += existing_count
            result.progress.new_video_ids += len(new_ids)

            if not new_ids:
                consecutive_empty_pages += 1
            else:
                consecutive_empty_pages = 0

            fetched_items = []
            for batch in _chunks(new_ids, PER_PAGE_MAX_RESULTS):
                if not batch:
                    continue
                fetched_items.extend(youtube.videos_list(batch))
                result.progress.quota_estimate += 1

            result.progress.videos_fetched += len(fetched_items)
            fetched_by_id = {item.get("id"): item for item in fetched_items if item.get("id")}

            for video_id in new_ids:
                if config.dedupe_within_run:
                    seen_ids.add(video_id)
                item = fetched_by_id.get(video_id)
                if not item:
                    continue
                sink.write_record(
                    _item_to_record(
                        item=item,
                        config=config,
                        page_number=page_number,
                        rank_in_run=rank_map.get(video_id),
                    )
                )

            next_page_token = response.get("nextPageToken")
            result.progress.next_page_token = next_page_token
            state_store.write_state(config=config, result=result, seen_ids=seen_ids)

            if not next_page_token:
                break
            if consecutive_empty_pages >= config.stop_after_empty_pages:
                break

        result.status = RunStatus.SUCCEEDED
        result.finished_at = datetime.datetime.now(datetime.UTC)
        state_store.write_state(config=config, result=result, seen_ids=seen_ids)
        state_store.write_summary(result=result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("Stateless extraction failed for run_id=%s", result.run_id)
        result.status = RunStatus.FAILED
        result.error_message = str(exc)
        result.finished_at = datetime.datetime.now(datetime.UTC)
        state_store.write_state(config=config, result=result, seen_ids=seen_ids)
        state_store.write_summary(result=result)
        return result
    finally:
        sink.close()


def _mark_unimplemented_mode(config: RunConfig, result: RunResult, state_store: RunStateStore) -> RunResult:
    """Mark non-search modes as failed until Phase 3 parity work lands."""
    result.status = RunStatus.FAILED
    result.error_message = f"Mode '{config.mode.value}' is not implemented yet"
    result.finished_at = datetime.datetime.now(datetime.UTC)
    state_store.write_state(config=config, result=result, seen_ids=set())
    state_store.write_summary(result=result)
    return result


def _extract_video_ids(page_items: list[dict], page_number: int) -> tuple[list[str], dict[str, int]]:
    """Extract unique video IDs from a search page and compute run-relative ranks."""
    ids: list[str] = []
    rank_map: dict[str, int] = {}
    for index, item in enumerate(page_items):
        item_id = item.get("id")
        if isinstance(item_id, dict):
            video_id = item_id.get("videoId")
        elif isinstance(item_id, str):
            video_id = item_id
        else:
            video_id = None
        if not video_id or video_id in rank_map:
            continue
        rank_map[video_id] = ((page_number - 1) * PER_PAGE_MAX_RESULTS) + index + 1
        ids.append(video_id)
    return ids, rank_map


def _item_to_record(item: dict, config: RunConfig, page_number: int, rank_in_run: int | None) -> VideoRecord:
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
        source_playlist_id=config.playlist_id,
        source_channel_id=config.channel_id,
        source_query=config.query,
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
    """Yield fixed-size chunks to satisfy API batch limits."""
    for index in range(0, len(items), size):
        yield items[index:index + size]
