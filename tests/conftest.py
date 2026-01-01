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
    db_url = db_path.as_posix()
    full_url = f"sqlite:///{db_url}"
    monkeypatch.setenv("DATABASE_URL", full_url)
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")

    for module in _MODULES_TO_CLEAR:
        sys.modules.pop(module, None)

    from app import database  # noqa: WPS433
    database.init_engine(full_url)

    from app import main as main_module  # noqa: WPS433 (import inside fixture)
    from app import models  # noqa: WPS433
    from app.config import settings  # noqa: WPS433

    assert "test.db" in str(settings.database_url)
    assert str(database.engine.url) == full_url

    yield {
        "app": main_module.app,
        "SessionLocal": database.SessionLocal,
        "models": models,
        "database": database,
    }


@pytest.fixture
def client(app_ctx):
    return TestClient(app_ctx["app"])
