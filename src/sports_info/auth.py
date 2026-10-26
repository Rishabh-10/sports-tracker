"""Local accounts: username + password, hashed with scrypt (Python standard library)."""

import base64
import hashlib
import hmac
import os
import re

from sqlmodel import Session

from sports_info.store import repo
from sports_info.store.migrate import claim_legacy_data
from sports_info.store.models import User

USERNAME_PATTERN = re.compile(r"^[a-z0-9_.-]{3,32}$")
MIN_PASSWORD_LENGTH = 8
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


class AuthError(Exception):
    """Registration or sign-in failed; the message is safe to show the user."""


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    expected = base64.b64decode(digest)
    actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                            dklen=len(expected))
    return hmac.compare_digest(actual, expected)


# Checked when the username doesn't exist, so a wrong username takes as long as a wrong password.
_DUMMY_HASH = hash_password("not-a-real-password")


def register(session: Session, username: str, password: str) -> User:
    username = username.strip().lower()
    if not USERNAME_PATTERN.match(username):
        raise AuthError("Usernames are 3–32 characters: letters, numbers, dots, dashes or underscores.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Passwords need at least {MIN_PASSWORD_LENGTH} characters.")
    if repo.get_user_by_username(session, username) is not None:
        raise AuthError("That username is taken.")
    user = repo.create_user(session, username, hash_password(password))
    if repo.count_users(session) == 1:
        # The first account inherits any setup from before accounts existed.
        claim_legacy_data(session, user.id)
    return user


def authenticate(session: Session, username: str, password: str) -> User | None:
    user = repo.get_user_by_username(session, username)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    return user if verify_password(password, user.password_hash) else None


def change_password(session: Session, user_id: int, current: str, new: str) -> None:
    user = repo.get_user(session, user_id)
    if user is None or not verify_password(current, user.password_hash):
        raise AuthError("Your current password is incorrect.")
    if len(new) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Passwords need at least {MIN_PASSWORD_LENGTH} characters.")
    user.password_hash = hash_password(new)
    session.add(user)
    session.commit()
