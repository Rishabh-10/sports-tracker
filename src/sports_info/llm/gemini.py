"""Gemini via the google-genai SDK, behind a small interface so other LLMs can be swapped in."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from sports_info import config
from sports_info.keys import ApiKeys


@dataclass
class Message:
    role: str  # "user" or "model"
    text: str


class LLMError(Exception):
    """The LLM call failed; the message is safe to show the user."""


class LLMClient(Protocol):
    model: str

    def stream(self, system: str, messages: list[Message], *, temperature: float = 0.3) -> Iterator[str]: ...


class GeminiClient:
    def __init__(self, api_key: str, model: str):
        from google import genai

        self.model = model
        self._client = genai.Client(api_key=api_key)

    def stream(self, system: str, messages: list[Message], *, temperature: float = 0.3) -> Iterator[str]:
        from google.genai import errors, types

        contents = [types.Content(role=m.role, parts=[types.Part(text=m.text)]) for m in messages]
        settings = types.GenerateContentConfig(system_instruction=system, temperature=temperature)
        try:
            for chunk in self._client.models.generate_content_stream(
                model=self.model, contents=contents, config=settings
            ):
                if chunk.text:
                    yield chunk.text
        except errors.APIError as exc:
            raise LLMError(_friendly_error(exc, self.model)) from exc


def _friendly_error(exc: Exception, model: str) -> str:
    code = getattr(exc, "code", None)
    detail = getattr(exc, "message", None) or str(exc)
    if code == 429:
        return ("Gemini's free-tier limit was reached. Wait a minute (or until tomorrow if it's the daily cap), "
                "or set GEMINI_MODEL=gemini-flash-lite-latest in .env for a higher limit.")
    if code in (400, 401, 403) and "key" in detail.lower():
        return "Gemini rejected the API key. Update it under API keys in the sidebar."
    if code == 404:
        return f"The model '{model}' isn't available to your key. Set GEMINI_MODEL in .env to one listed in AI Studio."
    return f"Gemini request failed ({code}): {detail[:200]}"


def get_llm(keys: ApiKeys) -> LLMClient | None:
    """Gemini with the user's key (or the shared one), or None if there's no key."""
    if not keys.gemini:
        return None
    return GeminiClient(keys.gemini, config.GEMINI_MODEL)
