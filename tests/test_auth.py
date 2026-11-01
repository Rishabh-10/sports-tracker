import pytest

from sports_info import auth
from sports_info.store import repo
from sports_info.store.db import get_session


def test_first_sign_in_creates_account_and_later_ones_reuse_it(temp_db):
    with get_session() as session:
        user = auth.sign_in(session, "google-123", "alice@example.com", "Alice")
        assert (user.google_sub, user.email, user.name) == ("google-123", "alice@example.com", "Alice")
        assert auth.sign_in(session, "google-123", "alice@example.com", "Alice").id == user.id
        assert repo.count_users(session) == 1


def test_email_and_name_follow_the_google_account(temp_db):
    with get_session() as session:
        user = auth.sign_in(session, "google-123", "alice@example.com", "Alice")
    with get_session() as session:
        again = auth.sign_in(session, "google-123", "alice@new.example", "Alice B")
    assert again.id == user.id
    with get_session() as session:
        stored = repo.get_user(session, user.id)
        assert (stored.email, stored.name) == ("alice@new.example", "Alice B")


def test_accounts_are_keyed_by_google_id_not_email(temp_db):
    with get_session() as session:
        first = auth.sign_in(session, "google-1", "shared@example.com", "One")
        second = auth.sign_in(session, "google-2", "shared@example.com", "Two")
        assert first.id != second.id


def test_google_id_is_required(temp_db):
    with get_session() as session, pytest.raises(ValueError):
        auth.sign_in(session, "", "alice@example.com", "Alice")


def test_simultaneous_first_sign_ins_share_one_account(temp_db, monkeypatch):
    """Two tabs signing in at once: the one that loses the race picks up the other's account."""
    with get_session() as other_tab:
        winner = repo.create_user(other_tab, "google-123", "alice@example.com", "Alice")
    real_lookup = repo.get_user_by_google_sub
    lookups = iter([None])  # the first lookup runs before the other tab's insert lands
    monkeypatch.setattr(repo, "get_user_by_google_sub",
                        lambda session, sub: next(lookups, None) or real_lookup(session, sub))
    with get_session() as session:
        assert auth.sign_in(session, "google-123", "alice@example.com", "Alice").id == winner.id
        assert repo.count_users(session) == 1
