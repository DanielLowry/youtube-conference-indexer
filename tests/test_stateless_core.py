"""Tests for stateless extraction core (Phase 2).

Purpose:
- Validate file-based run state persistence and output sinks.
- Validate bounded search/playlist/channel extraction behavior without database dependencies.
- Validate resume behavior from saved checkpoint state.
"""

import datetime
import json
import csv
from pathlib import Path

from app.services.contracts import ExtractionMode, OutputFormat, RunConfig, RunStatus, VideoRecord
from app.services.extractors import resume_extraction, run_extraction
from app.services.run_state import RunStateStore
from app.services.sinks import CSV_FIELDNAMES, create_sinks


def test_run_state_store_roundtrip(tmp_path: Path):
    """Run state should serialize/deserialize config, result, and dedupe IDs."""
    cfg = RunConfig(
        mode=ExtractionMode.SEARCH,
        query="cppcon allocator",
        output_root=str(tmp_path),
    )
    store = RunStateStore(output_root=str(tmp_path))
    result = store.initialize_run(cfg)
    result.status = RunStatus.RUNNING
    result.progress.pages_processed = 1
    store.write_state(config=cfg, result=result, seen_ids={"VID1", "VID2"})
    store.write_summary(result=result)

    loaded_cfg, loaded_result, seen_ids = store.load_state(result.run_id)
    assert loaded_cfg.query == "cppcon allocator"
    assert loaded_result.progress.pages_processed == 1
    assert seen_ids == {"VID1", "VID2"}
    assert (tmp_path / result.run_id / "run_state.json").exists()
    assert (tmp_path / result.run_id / "summary.json").exists()


def test_sinks_write_jsonl_and_csv(tmp_path: Path):
    """Sinks should write a record to JSONL and CSV with expected fields."""
    sink = create_sinks(
        output_dir=str(tmp_path),
        output_formats=[OutputFormat.JSONL, OutputFormat.CSV],
    )
    sink.write_record(
        VideoRecord(
            external_id="VID100",
            title="Test title",
            description="Desc",
            published_at=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
            duration_seconds=123,
            channel_id="UC123",
            channel_title="Test Channel",
            source_query="query",
            rank_in_run=1,
            page_number=1,
        )
    )
    sink.close()

    jsonl_path = tmp_path / "videos.jsonl"
    csv_path = tmp_path / "videos.csv"
    assert jsonl_path.exists()
    assert csv_path.exists()

    lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["external_id"] == "VID100"

    csv_lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(csv_lines) == 2
    assert "external_id" in csv_lines[0]
    assert "VID100" in csv_lines[1]


def test_sinks_jsonl_csv_schema_consistency(tmp_path: Path):
    """JSONL payload keys and CSV headers should stay aligned and stable."""
    sink = create_sinks(
        output_dir=str(tmp_path),
        output_formats=[OutputFormat.JSONL, OutputFormat.CSV],
    )
    sink.write_record(
        VideoRecord(
            external_id="VID200",
            title="Schema check",
            description="Desc",
            published_at=datetime.datetime(2025, 2, 1, tzinfo=datetime.UTC),
            duration_seconds=222,
            channel_id="UC200",
            channel_title="Schema Channel",
            source_playlist_id="PL200",
            source_channel_id="UC200",
            source_query="schema",
            rank_in_run=2,
            page_number=3,
        )
    )
    sink.close()

    jsonl_payload = json.loads((tmp_path / "videos.jsonl").read_text(encoding="utf-8").strip())
    with (tmp_path / "videos.csv").open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        csv_row = next(reader)
        csv_headers = reader.fieldnames

    assert csv_headers == CSV_FIELDNAMES
    assert list(csv_row.keys()) == CSV_FIELDNAMES
    assert set(CSV_FIELDNAMES).issubset(set(jsonl_payload.keys()))
    assert csv_row["external_id"] == jsonl_payload["external_id"] == "VID200"
    assert csv_row["channel_title"] == jsonl_payload["channel_title"] == "Schema Channel"


def test_run_extraction_search_writes_outputs(monkeypatch, tmp_path: Path):
    """Search extraction should write deduped outputs and final run state."""
    search_calls = []

    def fake_search_list(**kwargs):
        search_calls.append(kwargs.get("page_token"))
        if kwargs.get("page_token") is None:
            return {
                "items": [
                    {"id": {"videoId": "VID1"}},
                    {"id": {"videoId": "VID2"}},
                ],
                "nextPageToken": "page-2",
            }
        return {
            "items": [
                {"id": {"videoId": "VID2"}},
                {"id": {"videoId": "VID3"}},
            ],
            "nextPageToken": None,
        }

    def fake_videos_list(video_ids):
        return [
            {
                "id": video_id,
                "snippet": {
                    "title": f"Title {video_id}",
                    "description": "Desc",
                    "publishedAt": "2024-01-01T00:00:00Z",
                    "channelId": "UCX",
                    "channelTitle": "Chan",
                },
                "contentDetails": {"duration_seconds": 100},
            }
            for video_id in video_ids
        ]

    monkeypatch.setattr("app.services.extractors.youtube.search_list", fake_search_list)
    monkeypatch.setattr("app.services.extractors.youtube.videos_list", fake_videos_list)

    cfg = RunConfig(
        mode=ExtractionMode.SEARCH,
        query="allocators",
        output_root=str(tmp_path),
        max_pages=10,
        stop_after_empty_pages=2,
    )
    result = run_extraction(cfg)

    assert result.status == RunStatus.SUCCEEDED
    assert result.progress.pages_processed == 2
    assert result.progress.results_seen == 4
    assert result.progress.existing_video_ids == 1
    assert result.progress.new_video_ids == 3
    assert result.progress.videos_fetched == 3
    assert search_calls == [None, "page-2"]

    run_dir = tmp_path / result.run_id
    output_lines = (run_dir / "videos.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(output_lines) == 3
    assert (run_dir / "run_state.json").exists()
    assert (run_dir / "summary.json").exists()


def test_resume_extraction_from_checkpoint(monkeypatch, tmp_path: Path):
    """Resume should continue from next_page_token and preserve dedupe behavior."""
    cfg = RunConfig(
        mode=ExtractionMode.SEARCH,
        query="resume-case",
        output_root=str(tmp_path),
    )
    store = RunStateStore(output_root=str(tmp_path))
    seeded_result = store.initialize_run(cfg)
    seeded_result.status = RunStatus.RUNNING
    seeded_result.progress.pages_processed = 1
    seeded_result.progress.results_seen = 1
    seeded_result.progress.next_page_token = "resume-token"
    store.write_state(config=cfg, result=seeded_result, seen_ids={"VID1"})

    def fake_search_list(**kwargs):
        assert kwargs.get("page_token") == "resume-token"
        return {
            "items": [
                {"id": {"videoId": "VID1"}},
                {"id": {"videoId": "VID2"}},
            ],
            "nextPageToken": None,
        }

    def fake_videos_list(video_ids):
        assert video_ids == ["VID2"]
        return [
            {
                "id": "VID2",
                "snippet": {
                    "title": "Title VID2",
                    "description": "Desc",
                    "publishedAt": "2024-01-01T00:00:00Z",
                    "channelId": "UCY",
                    "channelTitle": "Chan",
                },
                "contentDetails": {"duration_seconds": 101},
            }
        ]

    monkeypatch.setattr("app.services.extractors.youtube.search_list", fake_search_list)
    monkeypatch.setattr("app.services.extractors.youtube.videos_list", fake_videos_list)

    resumed = resume_extraction(run_id=seeded_result.run_id, output_root=str(tmp_path))
    assert resumed.status == RunStatus.SUCCEEDED
    assert resumed.progress.pages_processed == 2
    assert resumed.progress.existing_video_ids == 1
    assert resumed.progress.new_video_ids == 1

    run_dir = tmp_path / seeded_result.run_id
    lines = (run_dir / "videos.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1


def test_run_extraction_failure_persists_error_summary(monkeypatch, tmp_path: Path):
    """Failures should mark run failed and persist error details to summary/state."""

    def _raise_search_error(**kwargs):
        raise RuntimeError("quota exhausted")

    monkeypatch.setattr("app.services.extractors.youtube.search_list", _raise_search_error)

    cfg = RunConfig(
        mode=ExtractionMode.SEARCH,
        query="failure-case",
        output_root=str(tmp_path),
    )
    result = run_extraction(cfg)

    assert result.status == RunStatus.FAILED
    assert result.error_message == "quota exhausted"
    assert result.finished_at is not None

    run_dir = tmp_path / result.run_id
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    state_payload = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["error_message"] == "quota exhausted"
    assert summary["finished_at"] is not None
    assert state_payload["result"]["status"] == "failed"
    assert state_payload["result"]["error_message"] == "quota exhausted"


def test_quota_summary_is_recorded_for_search(monkeypatch, tmp_path: Path):
    """Quota estimate should be reflected in both result and summary.json."""

    def fake_search_list(**kwargs):
        return {
            "items": [
                {"id": {"videoId": "VIDQ1"}},
                {"id": {"videoId": "VIDQ2"}},
            ],
            "nextPageToken": None,
        }

    def fake_videos_list(video_ids):
        return [
            {
                "id": video_id,
                "snippet": {
                    "title": f"Title {video_id}",
                    "description": "Desc",
                    "publishedAt": "2024-01-01T00:00:00Z",
                    "channelId": "UCQ",
                    "channelTitle": "Quota Channel",
                },
                "contentDetails": {"duration_seconds": 60},
            }
            for video_id in video_ids
        ]

    monkeypatch.setattr("app.services.extractors.youtube.search_list", fake_search_list)
    monkeypatch.setattr("app.services.extractors.youtube.videos_list", fake_videos_list)

    cfg = RunConfig(mode=ExtractionMode.SEARCH, query="quota-case", output_root=str(tmp_path))
    result = run_extraction(cfg)
    assert result.status == RunStatus.SUCCEEDED
    assert result.progress.quota_estimate == 101

    summary = json.loads((tmp_path / result.run_id / "summary.json").read_text(encoding="utf-8"))
    assert summary["progress"]["quota_estimate"] == 101


def test_resume_skips_work_for_succeeded_run(monkeypatch, tmp_path: Path):
    """Resuming a succeeded run should return immediately without API calls."""
    cfg = RunConfig(
        mode=ExtractionMode.SEARCH,
        query="already-done",
        output_root=str(tmp_path),
    )
    store = RunStateStore(output_root=str(tmp_path))
    result = store.initialize_run(cfg)
    result.status = RunStatus.SUCCEEDED
    result.progress.pages_processed = 3
    store.write_state(config=cfg, result=result, seen_ids={"VID1"})
    store.write_summary(result=result)

    def _unexpected_call(**kwargs):  # pragma: no cover - defensive check
        raise AssertionError("search_list should not be called for succeeded run")

    monkeypatch.setattr("app.services.extractors.youtube.search_list", _unexpected_call)
    resumed = resume_extraction(run_id=result.run_id, output_root=str(tmp_path))

    assert resumed.status == RunStatus.SUCCEEDED
    assert resumed.progress.pages_processed == 3


def test_resume_with_expired_page_token_marks_run_failed(monkeypatch, tmp_path: Path):
    """Expired/invalid resume tokens should fail cleanly with persisted error message."""
    cfg = RunConfig(
        mode=ExtractionMode.SEARCH,
        query="resume-expired-token",
        output_root=str(tmp_path),
    )
    store = RunStateStore(output_root=str(tmp_path))
    result = store.initialize_run(cfg)
    result.status = RunStatus.RUNNING
    result.progress.pages_processed = 1
    result.progress.next_page_token = "expired-token"
    store.write_state(config=cfg, result=result, seen_ids={"VID1"})
    store.write_summary(result=result)

    def _raise_token_error(**kwargs):
        raise RuntimeError("invalid page token")

    monkeypatch.setattr("app.services.extractors.youtube.search_list", _raise_token_error)
    resumed = resume_extraction(run_id=result.run_id, output_root=str(tmp_path))

    assert resumed.status == RunStatus.FAILED
    assert resumed.error_message == "invalid page token"

    summary = json.loads((tmp_path / result.run_id / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["error_message"] == "invalid page token"


def test_run_extraction_playlist_mode(monkeypatch, tmp_path: Path):
    """Playlist extraction should scan playlist pages and write deduped records."""

    def fake_playlist_items_list(playlist_id: str, page_token: str | None = None, max_results: int = 50):
        assert playlist_id == "PL123"
        assert max_results == 50
        if page_token is None:
            return {
                "items": [
                    {"contentDetails": {"videoId": "VID1"}},
                    {"contentDetails": {"videoId": "VID2"}},
                ],
                "nextPageToken": "page-2",
            }
        assert page_token == "page-2"
        return {
            "items": [
                {"contentDetails": {"videoId": "VID2"}},
                {"contentDetails": {"videoId": "VID3"}},
            ],
            "nextPageToken": None,
        }

    def fake_videos_list(video_ids):
        return [
            {
                "id": video_id,
                "snippet": {
                    "title": f"Title {video_id}",
                    "description": "Desc",
                    "publishedAt": "2024-01-01T00:00:00Z",
                    "channelId": "UCX",
                    "channelTitle": "Chan",
                },
                "contentDetails": {"duration_seconds": 100},
            }
            for video_id in video_ids
        ]

    monkeypatch.setattr("app.services.extractors.youtube.playlist_items_list", fake_playlist_items_list)
    monkeypatch.setattr("app.services.extractors.youtube.videos_list", fake_videos_list)

    cfg = RunConfig(
        mode=ExtractionMode.PLAYLIST,
        playlist_id="PL123",
        output_root=str(tmp_path),
        max_pages=10,
    )
    result = run_extraction(cfg)

    assert result.status == RunStatus.SUCCEEDED
    assert result.progress.pages_processed == 2
    assert result.progress.results_seen == 4
    assert result.progress.new_video_ids == 3
    assert result.progress.existing_video_ids == 1
    assert result.progress.videos_fetched == 3

    run_dir = tmp_path / result.run_id
    rows = [
        json.loads(line)
        for line in (run_dir / "videos.jsonl").read_text(encoding="utf-8").strip().splitlines()
    ]
    assert len(rows) == 3
    assert {row["source_playlist_id"] for row in rows} == {"PL123"}


def test_run_extraction_channel_mode(monkeypatch, tmp_path: Path):
    """Channel extraction should discover playlists and aggregate playlist scans."""

    def fake_get_channel_playlists(channel_id: str):
        assert channel_id == "UCCHAN"
        return [{"id": "PLA"}, {"id": "PLB"}]

    def fake_playlist_items_list(playlist_id: str, page_token: str | None = None, max_results: int = 50):
        assert max_results == 50
        assert page_token is None
        if playlist_id == "PLA":
            return {
                "items": [{"contentDetails": {"videoId": "A1"}}],
                "nextPageToken": None,
            }
        assert playlist_id == "PLB"
        return {
            "items": [
                {"contentDetails": {"videoId": "B1"}},
                {"contentDetails": {"videoId": "B2"}},
            ],
            "nextPageToken": None,
        }

    def fake_videos_list(video_ids):
        return [
            {
                "id": video_id,
                "snippet": {
                    "title": f"Title {video_id}",
                    "description": "Desc",
                    "publishedAt": "2024-01-01T00:00:00Z",
                    "channelId": "UCCHAN",
                    "channelTitle": "Chan",
                },
                "contentDetails": {"duration_seconds": 90},
            }
            for video_id in video_ids
        ]

    monkeypatch.setattr("app.services.extractors.youtube.get_channel_playlists", fake_get_channel_playlists)
    monkeypatch.setattr("app.services.extractors.youtube.playlist_items_list", fake_playlist_items_list)
    monkeypatch.setattr("app.services.extractors.youtube.videos_list", fake_videos_list)

    cfg = RunConfig(
        mode=ExtractionMode.CHANNEL,
        channel_id="UCCHAN",
        output_root=str(tmp_path),
        max_pages=10,
    )
    result = run_extraction(cfg)

    assert result.status == RunStatus.SUCCEEDED
    assert result.progress.total_playlists == 2
    assert result.progress.processed_playlists == 2
    assert result.progress.current_playlist_id is None
    assert result.progress.pages_processed == 2
    assert result.progress.videos_fetched == 3

    run_dir = tmp_path / result.run_id
    rows = [
        json.loads(line)
        for line in (run_dir / "videos.jsonl").read_text(encoding="utf-8").strip().splitlines()
    ]
    assert len(rows) == 3
    assert {row["source_channel_id"] for row in rows} == {"UCCHAN"}
    assert {row["source_playlist_id"] for row in rows} == {"PLA", "PLB"}
