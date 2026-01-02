from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import StaticPool

from .config import settings

Base = declarative_base()

primary_db_url = settings.database_url
current_db_url = primary_db_url
db_mode = "primary"  # "primary" | "memory"
engine = None
SessionLocal = None


def _make_engine(url: str):
    kwargs = {}
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    if ":memory:" in url:
        kwargs["poolclass"] = StaticPool
        if url == "sqlite:///:memory:":
            url = "sqlite+pysqlite:///:memory:"
    return create_engine(url, connect_args=connect_args, **kwargs)


def _bind_engine(url: str, mode: str):
    global engine, SessionLocal, current_db_url, db_mode
    engine = _make_engine(url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    current_db_url = url
    db_mode = mode


def init_engine(url: str | None = None):
    """Initialize engine; fallback to in-memory if primary is unreachable."""
    target_url = url or primary_db_url
    try:
        _bind_engine(target_url, mode="primary")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        _bind_engine("sqlite+pysqlite:///:memory:", mode="memory")


def switch_to_memory():
    _bind_engine("sqlite+pysqlite:///:memory:", mode="memory")
    create_tables()


def switch_to_primary():
    try:
        _bind_engine(primary_db_url, mode="primary")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        create_tables()
        return True
    except OperationalError:
        switch_to_memory()
        return False


def get_db_state():
    return {"mode": db_mode, "url": current_db_url}


def create_tables():
    """Create tables for all registered models."""
    from . import models  # noqa: WPS433

    models.Base.metadata.create_all(bind=engine)


# Initialize on import
init_engine()
