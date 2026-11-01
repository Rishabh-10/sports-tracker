"""API keys: the user's own (kept only in their browser session, never stored), with the
.env keys as a shared fallback."""

from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from sports_info import config

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


def _pick(own: str, shared: str) -> tuple[str, str]:
    if own:
        return own, "yours"
    if shared:
        return shared, "shared"
    return "", "none"


def resolve(own: Mapping[str, str]) -> ApiKeys:
    """The keys in effect, given the user's own keys for this session ({service: key})."""
    football, football_source = _pick(own.get("football_data", ""), config.FOOTBALL_DATA_API_KEY)
    gemini, gemini_source = _pick(own.get("gemini", ""), config.GEMINI_API_KEY)
    return ApiKeys(football, gemini, football_source, gemini_source)


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
