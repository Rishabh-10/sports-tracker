"""Databases from before accounts existed: the first account inherits the old setup."""

import sqlite3

from sports_info import auth
from sports_info.store import db, repo
from sports_info.store.db import get_session


def make_single_user_db(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE userprofile (id INTEGER PRIMARY KEY, timezone VARCHAR, days_ahead INTEGER,
                                  onboarded BOOLEAN, updated_at DATETIME);
        CREATE TABLE follow (id INTEGER PRIMARY KEY, sport VARCHAR, kind VARCHAR, external_id VARCHAR,
                             name VARCHAR, UNIQUE (sport, kind, external_id));
        CREATE INDEX ix_follow_sport ON follow (sport);
        INSERT INTO userprofile VALUES (1, 'Asia/Calcutta', 9, 1, '2026-10-25 18:20:33');
        INSERT INTO follow (sport, kind, external_id, name) VALUES
            ('f1', 'competition', 'f1', 'Formula 1'), ('f1', 'driver', 'leclerc', 'Charles Leclerc');
    """)
    conn.commit()
    conn.close()


def test_first_account_claims_old_setup(tmp_path):
    path = tmp_path / "old.db"
    make_single_user_db(path)
    engine = db.init_db(path)
    try:
        with get_session() as session:
            first = auth.register(session, "owner", "password123")
            second = auth.register(session, "guest", "password123")
            profile = repo.get_profile(session, first.id)
            assert (profile.timezone, profile.days_ahead, profile.onboarded) == ("Asia/Calcutta", 9, True)
            assert [f.name for f in repo.get_follows(session, first.id)] == ["Formula 1", "Charles Leclerc"]
            assert repo.get_follows(session, second.id) == []
            assert repo.get_profile(session, second.id).onboarded is False
        tables = {r[0] for r in sqlite3.connect(path).execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {"legacy_userprofile", "legacy_follow"} & tables
    finally:
        engine.dispose()
        db._engine = None


def test_reopening_migrated_db_is_a_no_op(tmp_path):
    path = tmp_path / "old.db"
    make_single_user_db(path)
    db.init_db(path).dispose()
    engine = db.init_db(path)  # second start: nothing left to migrate
    try:
        with get_session() as session:
            user = auth.register(session, "owner", "password123")
            assert len(repo.get_follows(session, user.id)) == 2
    finally:
        engine.dispose()
        db._engine = None
