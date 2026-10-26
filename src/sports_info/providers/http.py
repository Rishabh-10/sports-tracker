"""HTTP client shared by providers: JSON GETs with a sliding-window rate limit."""

import threading
import time
from collections import deque
from typing import Any

import httpx


class ProviderError(Exception):
    """A data source failed or returned something unusable."""


class ProviderNotConfigured(ProviderError):
    """A data source needs an API key that hasn't been set."""


class RateLimitedClient:
    def __init__(
        self,
        base_url: str,
        *,
        max_calls: int,
        period: float,
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ):
        self.max_calls = max_calls
        self.period = period
        self._client = client or httpx.Client(base_url=base_url, headers=headers or {}, timeout=timeout)
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def _wait_for_slot(self) -> None:
        with self._lock:
            while True:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= self.period:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                time.sleep(self.period - (now - self._calls[0]) + 0.05)

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        for attempt in range(2):
            self._wait_for_slot()
            try:
                response = self._client.get(path, params=params)
            except httpx.HTTPError as exc:
                raise ProviderError(f"network error calling {path}: {exc}") from exc

            if response.status_code == 429 and attempt == 0:
                wait = _retry_after_seconds(response)
                if wait is not None and wait <= 65:
                    time.sleep(wait + 1)
                    continue
            if response.status_code >= 400:
                raise ProviderError(f"{path} returned HTTP {response.status_code}: {_error_message(response)}")
            return response.json()
        raise ProviderError(f"{path} is rate limited, try again in a minute")


def _retry_after_seconds(response: httpx.Response) -> float | None:
    for header in ("Retry-After", "X-RequestCounter-Reset"):
        value = response.headers.get(header)
        if value:
            try:
                return float(value)
            except ValueError:
                pass
    return None


def _error_message(response: httpx.Response) -> str:
    try:
        return str(response.json().get("message", response.text))[:200]
    except ValueError:
        return response.text[:200]
