import pytest

from sports_info import auth
from sports_info.store import repo
from sports_info.store.db import get_session


def test_hash_and_verify():
    stored = auth.hash_password("correct horse")
    assert stored.startswith("scrypt$") and "correct horse" not in stored
    assert auth.verify_password("correct horse", stored)
    assert not auth.verify_password("wrong horse", stored)
    assert auth.hash_password("correct horse") != stored  # salted
    assert not auth.verify_password("x", "garbage")


def test_register_and_authenticate(temp_db):
    with get_session() as session:
        user = auth.register(session, "  Alice ", "password123")
        assert user.username == "alice"
        assert auth.authenticate(session, "ALICE", "password123").id == user.id
        assert auth.authenticate(session, "alice", "nope-nope") is None
        assert auth.authenticate(session, "nobody", "password123") is None


@pytest.mark.parametrize("username,password,message", [
    ("al", "password123", "3–32 characters"),
    ("has space", "password123", "3–32 characters"),
    ("bob", "short", "at least 8"),
])
def test_register_validation(temp_db, username, password, message):
    with get_session() as session, pytest.raises(auth.AuthError, match=message):
        auth.register(session, username, password)


def test_duplicate_username_rejected(temp_db):
    with get_session() as session:
        auth.register(session, "alice", "password123")
        with pytest.raises(auth.AuthError, match="taken"):
            auth.register(session, "Alice", "password456")


def test_change_password(temp_db):
    with get_session() as session:
        user = auth.register(session, "alice", "password123")
        with pytest.raises(auth.AuthError, match="incorrect"):
            auth.change_password(session, user.id, "wrong-one", "newpassword1")
        auth.change_password(session, user.id, "password123", "newpassword1")
        assert auth.authenticate(session, "alice", "newpassword1") is not None
        assert repo.get_user(session, user.id).password_hash.startswith("scrypt$")
