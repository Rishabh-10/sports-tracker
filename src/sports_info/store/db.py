"""Database engine and sessions: Postgres when DATABASE_URL is set, else a local SQLite file."""

from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from sports_info import config
from sports_info.store import models  # noqa: F401  (registers the tables)
from sports_info.store.migrate import migrate_single_user_schema

_engine: Engine | None = None


class LegacyDatabaseError(RuntimeError):
    """The database still has the old username/password accounts; the message is safe to show the user."""


def database_url(url: str = "", db_path: Path | None = None) -> str:
    url = url or config.DATABASE_URL
    if not url:
        path = db_path or config.DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path}"
    # Neon and most hosts hand out postgres:// or postgresql:// URLs; use the psycopg 3 driver for both.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


def _check_not_password_accounts(engine: Engine) -> None:
    inspector = inspect(engine)
    if inspector.has_table("user") and "google_sub" not in {c["name"] for c in inspector.get_columns("user")}:
        where = "data/sports_info.db" if engine.dialect.name == "sqlite" else "the database at DATABASE_URL"
        raise LegacyDatabaseError(
            f"{where} was created by the old username/password version of Sports Info. "
            "Delete it (or point DATABASE_URL at a new database) to start fresh with Google sign-in. "
            "Fixtures and news are fetched again automatically."
        )


def _create_keyword_index(engine: Engine) -> None:
    """Keyword index over chunks, used alongside embeddings for hybrid search."""
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            # Filled with accent-free text (see news_repo), so "Perez" matches "Pérez".
            conn.exec_driver_sql("ALTER TABLE chunk ADD COLUMN IF NOT EXISTS search tsvector")
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_chunk_search ON chunk USING gin (search)")
        else:
            conn.exec_driver_sql(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5("
                "chunk_id UNINDEXED, text, tokenize='unicode61 remove_diacritics 2')"
            )


def init_db(db_path: Path | None = None, *, url: str = "") -> Engine:
    """Create the engine (once) and make sure all tables exist.

    Passing `db_path` or `url` replaces the engine (used by tests); otherwise DATABASE_URL
    or the default SQLite file is used.
    """
    global _engine
    if _engine is None or db_path is not None or url:
        engine_url = database_url(url, db_path)
        if engine_url.startswith("sqlite"):
            engine = create_engine(engine_url, connect_args={"check_same_thread": False})
        else:
            engine = create_engine(engine_url, pool_pre_ping=True)  # pre-ping: Neon drops idle connections
        try:
            _check_not_password_accounts(engine)
        except LegacyDatabaseError:
            engine.dispose()
            raise
        migrate_single_user_schema(engine)
        SQLModel.metadata.create_all(engine)
        _create_keyword_index(engine)
        _engine = engine
    return _engine


def get_session() -> Session:
    return Session(init_db(), expire_on_commit=False)
