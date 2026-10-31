"""Per-user API keys, with the .env keys as a shared fallback.

Keys are encrypted with KEYS_ENCRYPTION_KEY before they're stored. Without it (fine for a
local install) they're stored as plain text, and plain-text keys saved before encryption
was turned on keep working until they're next saved.
"""

import base64
import hashlib
import logging
from dataclasses import dataclass

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlmodel import Session

from sports_info import config
from sports_info.store.models import UserApiKeys, utcnow

SERVICES = {
    "football_data": "football-data.org",
    "gemini": "Gemini",
}
SIGNUP_URLS = {
    "football_data": "https://www.football-data.org/client/register",
    "gemini": "https://aistudio.google.com/apikey",
}


@dataclass(frozen=True)
class ApiKeys:
    """The keys in effect for one user. `*_source` is "yours", "shared" (from .env) or "none"."""

    football_data: str = ""
    gemini: str = ""
    football_data_source: str = "none"
    gemini_source: str = "none"

    def source(self, service: str) -> str:
        return getattr(self, f"{service}_source")


class InvalidKey(Exception):
    """The service rejected the key; the message is safe to show the user."""


log = logging.getLogger(__name__)
ENCRYPTED_PREFIX = "fernet:"


def _fernet() -> Fernet | None:
    if not config.KEYS_ENCRYPTION_KEY:
        return None
    # Accept any secret string (like Streamlit's cookie_secret), not just a Fernet-format key.
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(config.KEYS_ENCRYPTION_KEY.encode()).digest()))


def encrypt(value: str) -> str:
    fernet = _fernet()
    if not value or fernet is None:
        return value
    return ENCRYPTED_PREFIX + fernet.encrypt(value.encode()).decode()


def decrypt(stored: str) -> str:
    """The plain key. A key that can't be decrypted (missing or changed KEYS_ENCRYPTION_KEY) reads as unset."""
    if not stored.startswith(ENCRYPTED_PREFIX):
        return stored  # saved before encryption was turned on
    fernet = _fernet()
    try:
        if fernet is None:
            raise InvalidToken
        return fernet.decrypt(stored.removeprefix(ENCRYPTED_PREFIX).encode()).decode()
    except InvalidToken:
        log.warning("A stored API key couldn't be decrypted; check KEYS_ENCRYPTION_KEY. Treating it as unset.")
        return ""


def _pick(own: str, shared: str) -> tuple[str, str]:
    if own:
        return own, "yours"
    if shared:
        return shared, "shared"
    return "", "none"


def for_user(session: Session, user_id: int) -> ApiKeys:
    own = session.get(UserApiKeys, user_id) or UserApiKeys(user_id=user_id)
    football, football_source = _pick(decrypt(own.football_data), config.FOOTBALL_DATA_API_KEY)
    gemini, gemini_source = _pick(decrypt(own.gemini), config.GEMINI_API_KEY)
    return ApiKeys(football, gemini, football_source, gemini_source)


def own_key(session: Session, user_id: int, service: str) -> str:
    own = session.get(UserApiKeys, user_id)
    return decrypt(getattr(own, service)) if own else ""


def set_key(session: Session, user_id: int, service: str, value: str) -> None:
    """Store (or with an empty value, remove) one of the user's keys."""
    if service not in SERVICES:
        raise ValueError(service)
    own = session.get(UserApiKeys, user_id) or UserApiKeys(user_id=user_id)
    setattr(own, service, encrypt(value.strip()))
    own.updated_at = utcnow()
    session.add(own)
    session.commit()


def mask(key: str) -> str:
    return f"••••{key[-4:]}" if len(key) > 8 else "••••"


# --- validation: one cheap request each, so typos are caught when saving ---------


def validate_football_data(key: str, client: httpx.Client | None = None) -> None:
    client = client or httpx.Client(timeout=15)
    try:
        response = client.get("https://api.football-data.org/v4/competitions/PL/teams",
                              headers={"X-Auth-Token": key})
    except httpx.HTTPError:
        return  # can't reach the service right now; accept the key and let real use surface problems
    if response.status_code in (400, 401, 403):
        raise InvalidKey("football-data.org didn't accept that key. Check it and try again.")


def validate_gemini(key: str) -> None:
    from google import genai
    from google.genai import errors

    client = genai.Client(api_key=key)
    try:
        next(iter(client.models.list(config={"page_size": 1})), None)
    except errors.APIError as exc:
        if exc.code in (400, 401, 403):
            raise InvalidKey("Gemini didn't accept that key. Check it in Google AI Studio and try again.") from exc
    except Exception:  # network trouble: accept the key
        return


VALIDATORS = {"football_data": validate_football_data, "gemini": validate_gemini}
