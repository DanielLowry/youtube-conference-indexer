"""CLI adapter tests for stateless extraction commands."""

import json

from app import cli
from app.services.contracts import ExtractionMode, RunResult, RunStatus


def test_cli_run_invokes_extraction_service(monkeypatch, capsys):
    captured = {}

    def _fake_run(config):
        captured["mode"] = config.mode
        captured["query"] = config.query
        return RunResult(
            run_id="run-1",
            mode=ExtractionMode.SEARCH,
            status=RunStatus.SUCCEEDED,
            output_dir="./runs/run-1",
        )

    monkeypatch.setattr(cli, "run_extraction", _fake_run)

    exit_code = cli.main(["run", "--mode", "search", "--query", "cppcon"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert captured == {"mode": ExtractionMode.SEARCH, "query": "cppcon"}
    payload = json.loads(output)
    assert payload["run_id"] == "run-1"


def test_cli_resume_invokes_resume_service(monkeypatch, capsys):
    captured = {}

    def _fake_resume(run_id: str, output_root: str):
        captured["run_id"] = run_id
        captured["output_root"] = output_root
        return RunResult(
            run_id=run_id,
            mode=ExtractionMode.SEARCH,
            status=RunStatus.SUCCEEDED,
            output_dir=f"{output_root}/{run_id}",
        )

    monkeypatch.setattr(cli, "resume_extraction", _fake_resume)

    exit_code = cli.main(["resume", "run-abc", "--output-root", "./tmp-runs"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert captured == {"run_id": "run-abc", "output_root": "./tmp-runs"}
    payload = json.loads(output)
    assert payload["run_id"] == "run-abc"
