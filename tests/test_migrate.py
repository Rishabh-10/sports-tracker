"""Older databases: from before accounts existed (the first account inherits the old setup),
and from the username/password version (the app asks for a fresh database)."""

import sqlite3

import pytest

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
            first = auth.sign_in(session, "google-owner", "owner@example.com", "Owner")
            second = auth.sign_in(session, "google-guest", "guest@example.com", "Guest")
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
            user = auth.sign_in(session, "google-owner", "owner@example.com", "Owner")
            assert len(repo.get_follows(session, user.id)) == 2
    finally:
        engine.dispose()
        db._engine = None


def test_password_accounts_database_asks_to_start_fresh(tmp_path):
    path = tmp_path / "passwords.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE user (id INTEGER PRIMARY KEY, username VARCHAR, password_hash VARCHAR, created_at DATETIME);
        INSERT INTO user VALUES (1, 'alice', 'scrypt$...', '2026-10-28 10:00:00');
    """)
    conn.commit()
    conn.close()
    with pytest.raises(db.LegacyDatabaseError, match="start fresh"):
        db.init_db(path)
    db._engine = None
    # Left untouched, so nothing is lost if it was opened by mistake.
    assert sqlite3.connect(path).execute("SELECT username FROM user").fetchall() == [("alice",)]
