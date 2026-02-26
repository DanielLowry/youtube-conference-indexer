import pytest

from app.services.contracts import (
    ExtractionMode,
    OutputFormat,
    RunConfig,
    RunResult,
    RunStatus,
)


def test_run_config_defaults_for_search():
    cfg = RunConfig(mode=ExtractionMode.SEARCH, query="cppcon allocators")
    assert cfg.max_pages == 10
    assert cfg.stop_after_empty_pages == 2
    assert cfg.dedupe_within_run is True
    assert cfg.output_root == "./runs"
    assert cfg.output_formats == [OutputFormat.JSONL, OutputFormat.CSV]
    assert cfg.max_results == 500


def test_run_config_requires_mode_specific_fields():
    with pytest.raises(ValueError):
        RunConfig(mode=ExtractionMode.SEARCH)
    with pytest.raises(ValueError):
        RunConfig(mode=ExtractionMode.PLAYLIST)
    with pytest.raises(ValueError):
        RunConfig(mode=ExtractionMode.CHANNEL)


def test_run_config_rejects_invalid_date_window():
    with pytest.raises(ValueError):
        RunConfig(
            mode=ExtractionMode.SEARCH,
            query="foo",
            published_after="2025-01-02T00:00:00+00:00",
            published_before="2025-01-01T00:00:00+00:00",
        )


def test_run_result_defaults():
    result = RunResult(
        run_id="run-123",
        mode=ExtractionMode.SEARCH,
        status=RunStatus.QUEUED,
        output_dir="./runs/run-123",
    )
    assert result.progress.pages_processed == 0
    assert result.output_files == []
