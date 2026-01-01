import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_MODULES_TO_CLEAR = [
    "app.main",
    "app.database",
    "app.config",
    "app.models",
    "app.schemas",
    "app.crud",
    "app.youtube",
]


@pytest.fixture
def app_ctx(tmp_path: Path, monkeypatch):
    """Fresh app and DB per test; ensures settings pick up test env vars."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    for module in _MODULES_TO_CLEAR:
        sys.modules.pop(module, None)

    from app import main as main_module  # noqa: WPS433 (import inside fixture)
    from app.database import SessionLocal  # noqa: WPS433

    yield {"app": main_module.app, "SessionLocal": SessionLocal}


@pytest.fixture
def client(app_ctx):
    return TestClient(app_ctx["app"])
