import httpx
import pytest

from sports_info import config, keys
from sports_info.llm.gemini import get_llm
from sports_info.providers import get_provider


@pytest.fixture
def no_shared_keys(monkeypatch):
    monkeypatch.setattr(config, "FOOTBALL_DATA_API_KEY", "")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")


def test_own_key_is_used_and_unset_is_none(no_shared_keys):
    alice_keys, bob_keys = keys.resolve({"football_data": "alice-football-key"}), keys.resolve({})
    assert (alice_keys.football_data, alice_keys.football_data_source) == ("alice-football-key", "yours")
    assert (bob_keys.football_data, bob_keys.football_data_source) == ("", "none")
    assert get_provider("football", alice_keys).is_configured()
    assert not get_provider("football", bob_keys).is_configured()


def test_own_key_beats_shared_and_removal_falls_back(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "shared-gemini")
    assert keys.resolve({}).gemini_source == "shared"
    mine = keys.resolve({"gemini": "my-gemini"})
    assert (mine.gemini, mine.gemini_source) == ("my-gemini", "yours")
    assert keys.resolve({"gemini": ""}).gemini == "shared-gemini"


def test_get_llm_needs_a_key(no_shared_keys):
    assert get_llm(keys.ApiKeys()) is None
    assert get_llm(keys.ApiKeys(gemini="abc", gemini_source="yours")).model == config.GEMINI_MODEL


def test_mask_shows_only_last_four():
    assert keys.mask("abcdefgh12345678") == "••••5678"
    assert keys.mask("short") == "••••"


def client(status=None, error=False):
    def handler(request):
        if error:
            raise httpx.ConnectError("offline")
        return httpx.Response(status, json={"message": "Your API token is invalid."})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_football_validation():
    with pytest.raises(keys.InvalidKey):
        keys.validate_football_data("bad", client(400))
    keys.validate_football_data("good", client(200))
    keys.validate_football_data("unknown", client(error=True))  # offline: accepted
