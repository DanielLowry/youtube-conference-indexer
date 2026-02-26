"""FastAPI adapter tests for stateless extraction routes.

Purpose:
- Verify UI endpoints can submit and inspect runs without database dependencies.
- Verify run artifacts are discoverable/downloadable through HTTP routes.
- Verify resume endpoints queue work against filesystem checkpoints.
"""

import re
from pathlib import Path

import pytest
from fastapi.responses import Response
from httpx import ASGITransport, AsyncClient

from app import main as main_module
from app.services.contracts import ExtractionMode, RunConfig
from app.services.run_state import RunStateStore


@pytest.mark.anyio
async def test_home_page_renders_stateless_dashboard(monkeypatch, tmp_path: Path):
    output_root = tmp_path / "runs"
    _configure_test_app(monkeypatch, output_root)

    async with _async_client() as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "Start Extraction Run" in response.text
    assert "No extraction runs yet" in response.text


@pytest.mark.anyio
async def test_submit_run_creates_checkpoint_and_redirects(monkeypatch, tmp_path: Path):
    output_root = tmp_path / "runs"
    _configure_test_app(monkeypatch, output_root)
    queued: list[tuple[str, str]] = []

    async def _fake_background(run_id: str, root: str):
        queued.append((run_id, root))

    monkeypatch.setattr(main_module, "_resume_job_background", _fake_background)

    async with _async_client() as client:
        response = await client.post(
            "/runs",
            data={
                "mode": "search",
                "query": "allocator",
                "max_pages": "2",
                "stop_after_empty_pages": "1",
                "output_formats": ["jsonl", "csv"],
            },
        )

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/?run_id=")

    run_id_match = re.search(r"run_id=([^&]+)", location)
    assert run_id_match is not None
    run_id = run_id_match.group(1)

    run_dir = output_root / run_id
    assert (run_dir / "run_state.json").exists()
    assert (run_dir / "summary.json").exists()
    assert queued == [(run_id, str(output_root))]


@pytest.mark.anyio
async def test_submit_run_rejects_invalid_config(monkeypatch, tmp_path: Path):
    output_root = tmp_path / "runs"
    _configure_test_app(monkeypatch, output_root)

    async with _async_client() as client:
        response = await client.post(
            "/runs",
            data={
                "mode": "search",
                "query": "",
            },
        )

    assert response.status_code == 400
    assert "Invalid run configuration" in response.text


@pytest.mark.anyio
async def test_runs_list_and_status_fragments(monkeypatch, tmp_path: Path):
    output_root = tmp_path / "runs"
    _configure_test_app(monkeypatch, output_root)
    run_id = _seed_run(output_root)

    async with _async_client() as client:
        list_response = await client.get("/runs/list")
        status_response = await client.get(f"/runs/{run_id}/status")
        missing_response = await client.get("/runs/does-not-exist/status")

    assert list_response.status_code == 200
    assert run_id in list_response.text
    assert status_response.status_code == 200
    assert run_id in status_response.text
    assert "queued" in status_response.text
    assert missing_response.status_code == 404


@pytest.mark.anyio
async def test_resume_route_queues_background_job(monkeypatch, tmp_path: Path):
    output_root = tmp_path / "runs"
    _configure_test_app(monkeypatch, output_root)
    run_id = _seed_run(output_root)

    queued: list[tuple[str, str]] = []

    async def _fake_background(run_id_value: str, root_value: str):
        queued.append((run_id_value, root_value))

    monkeypatch.setattr(main_module, "_resume_job_background", _fake_background)

    async with _async_client() as client:
        response = await client.post(f"/runs/{run_id}/resume")

    assert response.status_code == 303
    assert response.headers["location"].startswith("/?run_id=")
    assert queued == [(run_id, str(output_root))]


@pytest.mark.anyio
async def test_download_route_returns_artifact(monkeypatch, tmp_path: Path):
    output_root = tmp_path / "runs"
    _configure_test_app(monkeypatch, output_root)
    run_id = _seed_run(output_root)

    csv_path = output_root / run_id / "videos.csv"
    csv_path.write_text("external_id,title\nVID1,Test\n", encoding="utf-8")

    # Starlette's FileResponse uses a background close task that can deadlock
    # under ASGITransport in this sandboxed async test harness.
    def _fake_file_response(*, path, media_type: str, filename: str):
        payload = Path(path).read_bytes()
        return Response(
            content=payload,
            media_type=media_type,
            headers={"content-disposition": f'attachment; filename="{filename}"'},
        )

    monkeypatch.setattr(main_module, "FileResponse", _fake_file_response)

    async with _async_client() as client:
        response = await client.get(f"/runs/{run_id}/download/csv")
        missing = await client.get(f"/runs/{run_id}/download/jsonl")
        unsupported = await client.get(f"/runs/{run_id}/download/xml")

    assert response.status_code == 200
    assert "text/csv" in response.headers.get("content-type", "")
    assert response.text.startswith("external_id,title")
    assert missing.status_code == 404
    assert unsupported.status_code == 404


def _configure_test_app(monkeypatch, output_root: Path) -> None:
    """Patch app globals/services so route tests are deterministic and offline."""
    monkeypatch.setattr(main_module, "OUTPUT_ROOT", str(output_root))
    monkeypatch.setattr(main_module.youtube, "get_api_key", lambda: "test-key")
    monkeypatch.setattr(main_module.youtube, "has_valid_key", lambda: True)
    monkeypatch.setattr(main_module.youtube, "validate_api_key", lambda: (True, "Validation skipped in tests"))


def _seed_run(output_root: Path, mode: ExtractionMode = ExtractionMode.SEARCH) -> str:
    """Create one initialized run directory and return its run_id."""
    config = RunConfig(mode=mode, query="seed-query", output_root=str(output_root))
    store = RunStateStore(output_root=str(output_root))
    result = store.initialize_run(config)
    return result.run_id


def _async_client() -> AsyncClient:
    """Build an AsyncClient backed by the FastAPI ASGI app."""
    transport = ASGITransport(app=main_module.app)
    return AsyncClient(transport=transport, base_url="http://testserver", follow_redirects=False)
