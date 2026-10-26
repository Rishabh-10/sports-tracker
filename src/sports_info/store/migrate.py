"""Upgrading databases created before multi-user support.

The old single-user `userprofile` and `follow` tables are copied to `legacy_*` tables
(plain copies, without the old indexes) and dropped. The first account created claims
that data, so an existing setup carries over to its owner.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlmodel import Session

LEGACY_TABLES = {"userprofile": "legacy_userprofile", "follow": "legacy_follow"}


def migrate_single_user_schema(engine: Engine) -> None:
    """Run before create_all: set aside old-format tables so the new ones can be created."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "userprofile" not in tables:
        return
    if "user_id" in {c["name"] for c in inspector.get_columns("userprofile")}:
        return
    with engine.begin() as conn:
        for old, legacy in LEGACY_TABLES.items():
            if old in tables:
                conn.exec_driver_sql(f"DROP TABLE IF EXISTS {legacy}")
                conn.exec_driver_sql(f"CREATE TABLE {legacy} AS SELECT * FROM {old}")
                conn.exec_driver_sql(f"DROP TABLE {old}")


def _has_table(conn: Connection, name: str) -> bool:
    return inspect(conn).has_table(name)


def claim_legacy_data(session: Session, user_id: int) -> bool:
    """Give pre-multi-user preferences and follows to `user_id`. Returns True if there were any."""
    conn = session.connection()
    if not _has_table(conn, "legacy_userprofile"):
        return False
    profile = conn.execute(
        text("SELECT timezone, days_ahead, onboarded FROM legacy_userprofile LIMIT 1")
    ).first()
    if profile is not None:
        conn.execute(
            text("INSERT INTO userprofile (user_id, timezone, days_ahead, onboarded, updated_at) "
                 "VALUES (:user_id, :timezone, :days_ahead, :onboarded, CURRENT_TIMESTAMP)"),
            {"user_id": user_id, "timezone": profile[0], "days_ahead": profile[1], "onboarded": profile[2]},
        )
    if _has_table(conn, "legacy_follow"):
        conn.execute(
            text("INSERT INTO follow (user_id, sport, kind, external_id, name) "
                 "SELECT :user_id, sport, kind, external_id, name FROM legacy_follow"),
            {"user_id": user_id},
        )
    for legacy in LEGACY_TABLES.values():
        conn.exec_driver_sql(f"DROP TABLE IF EXISTS {legacy}")
    session.commit()
    return profile is not None
