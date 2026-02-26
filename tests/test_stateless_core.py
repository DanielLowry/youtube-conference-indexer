"""Tests for stateless extraction core (Phase 2).

Purpose:
- Validate file-based run state persistence and output sinks.
- Validate bounded search extraction behavior without database dependencies.
- Validate resume behavior from saved checkpoint state.
"""

import datetime
import json
from pathlib import Path

from app.services.contracts import ExtractionMode, OutputFormat, RunConfig, RunStatus, VideoRecord
from app.services.extractors import resume_extraction, run_extraction
from app.services.run_state import RunStateStore
from app.services.sinks import create_sinks


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
