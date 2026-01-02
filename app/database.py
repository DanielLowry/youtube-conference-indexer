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
    ensure_fts()


def health_check():
    """Return True if DB is reachable and core tables exist."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        # check a core table exists
        with engine.connect() as conn:
            conn.execute(text("SELECT 1 FROM videos LIMIT 1"))
            conn.execute(text("SELECT 1 FROM videos_fts LIMIT 1"))
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def ensure_fts():
    """Ensure FTS virtual table and triggers exist."""
    sql_statements = [
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS videos_fts USING fts5(
            title,
            description,
            content='videos',
            content_rowid='id'
        );
        """,
        """
        CREATE TRIGGER IF NOT EXISTS videos_ai AFTER INSERT ON videos BEGIN
            INSERT INTO videos_fts(rowid, title, description)
            VALUES (new.id, new.title, new.description);
        END;
        """,
        """
        CREATE TRIGGER IF NOT EXISTS videos_ad AFTER DELETE ON videos BEGIN
            INSERT INTO videos_fts(videos_fts, rowid, title, description)
            VALUES ('delete', old.id, old.title, old.description);
        END;
        """,
        """
        CREATE TRIGGER IF NOT EXISTS videos_au AFTER UPDATE ON videos BEGIN
            INSERT INTO videos_fts(videos_fts, rowid, title, description)
            VALUES ('delete', old.id, old.title, old.description);
            INSERT INTO videos_fts(rowid, title, description)
            VALUES (new.id, new.title, new.description);
        END;
        """,
    ]
    with engine.begin() as conn:
        for stmt in sql_statements:
            conn.exec_driver_sql(stmt)
        # backfill existing rows if empty
        conn.exec_driver_sql(
            """
            INSERT INTO videos_fts (rowid, title, description)
            SELECT id, title, description FROM videos
            WHERE id NOT IN (SELECT rowid FROM videos_fts);
            """
        )


# Initialize on import
init_engine()
