"""Database engine and sessions."""

from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from sports_info import config
from sports_info.store import models  # noqa: F401  (registers the tables)
from sports_info.store.migrate import migrate_single_user_schema

_engine: Engine | None = None


def init_db(db_path: Path | None = None) -> Engine:
    """Create the engine (once) and make sure all tables exist."""
    global _engine
    if _engine is None or db_path is not None:
        path = db_path or config.DB_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        migrate_single_user_schema(_engine)
        SQLModel.metadata.create_all(_engine)
        with _engine.begin() as conn:
            # Keyword index over chunks, used alongside embeddings for hybrid search.
            conn.exec_driver_sql(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5("
                "chunk_id UNINDEXED, text, tokenize='unicode61 remove_diacritics 2')"
            )
    return _engine


def get_session() -> Session:
    return Session(init_db(), expire_on_commit=False)
