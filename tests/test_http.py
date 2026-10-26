import httpx
import pytest

from sports_info.providers.http import ProviderError, RateLimitedClient


def client_for(handler):
    return RateLimitedClient(
        "https://api.test", max_calls=10, period=60,
        client=httpx.Client(base_url="https://api.test", transport=httpx.MockTransport(handler)),
    )


def test_retries_once_after_429(monkeypatch):
    monkeypatch.setattr("sports_info.providers.http.time.sleep", lambda s: None)
    responses = iter([httpx.Response(429, headers={"X-RequestCounter-Reset": "3"}), httpx.Response(200, json={"ok": 1})])
    assert client_for(lambda request: next(responses)).get_json("/x") == {"ok": 1}


def test_http_error_includes_api_message():
    client = client_for(lambda request: httpx.Response(403, json={"message": "restricted"}))
    with pytest.raises(ProviderError, match="403: restricted"):
        client.get_json("/x")
