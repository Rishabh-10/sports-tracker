import httpx
import pytest

from sports_info import config, keys
from sports_info.llm.gemini import get_llm
from sports_info.providers import get_provider
from sports_info.store.db import get_session
from sports_info.store.models import UserApiKeys


@pytest.fixture
def no_shared_keys(monkeypatch):
    monkeypatch.setattr(config, "FOOTBALL_DATA_API_KEY", "")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")


def test_users_keys_are_private(make_user, no_shared_keys):
    alice, bob = make_user("alice"), make_user("bob")
    with get_session() as session:
        keys.set_key(session, alice, "football_data", "  alice-football-key  ")
        alice_keys, bob_keys = keys.for_user(session, alice), keys.for_user(session, bob)
    assert (alice_keys.football_data, alice_keys.football_data_source) == ("alice-football-key", "yours")
    assert (bob_keys.football_data, bob_keys.football_data_source) == ("", "none")
    assert get_provider("football", alice_keys).is_configured()
    assert not get_provider("football", bob_keys).is_configured()


def test_own_key_beats_shared_and_removal_falls_back(make_user, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "shared-gemini")
    user = make_user("alice")
    with get_session() as session:
        assert keys.for_user(session, user).gemini_source == "shared"
        keys.set_key(session, user, "gemini", "my-gemini")
        assert (keys.for_user(session, user).gemini, keys.for_user(session, user).gemini_source) == ("my-gemini", "yours")
        keys.set_key(session, user, "gemini", "")
        assert keys.for_user(session, user).gemini == "shared-gemini"


def stored_value(user_id, service):
    with get_session() as session:
        return getattr(session.get(UserApiKeys, user_id), service)


def test_keys_are_encrypted_at_rest(make_user, no_shared_keys, monkeypatch):
    monkeypatch.setattr(config, "KEYS_ENCRYPTION_KEY", "test-secret")
    user = make_user("alice")
    with get_session() as session:
        keys.set_key(session, user, "gemini", "my-gemini-key-1234")
    stored = stored_value(user, "gemini")
    assert stored.startswith(keys.ENCRYPTED_PREFIX) and "my-gemini-key" not in stored
    with get_session() as session:
        assert keys.for_user(session, user).gemini == "my-gemini-key-1234"
        assert keys.own_key(session, user, "gemini") == "my-gemini-key-1234"
        keys.set_key(session, user, "gemini", "")
    assert stored_value(user, "gemini") == ""  # removing a key stores nothing, not an encrypted ""


def test_plain_text_keys_saved_before_encryption_still_work(make_user, no_shared_keys, monkeypatch):
    user = make_user("alice")
    with get_session() as session:
        keys.set_key(session, user, "football_data", "old-plain-key")  # no KEYS_ENCRYPTION_KEY yet
    assert stored_value(user, "football_data") == "old-plain-key"
    monkeypatch.setattr(config, "KEYS_ENCRYPTION_KEY", "test-secret")
    with get_session() as session:
        assert keys.for_user(session, user).football_data == "old-plain-key"
        keys.set_key(session, user, "football_data", "new-key")  # re-saving encrypts it
    assert stored_value(user, "football_data").startswith(keys.ENCRYPTED_PREFIX)


def test_undecryptable_key_reads_as_unset(make_user, monkeypatch):
    monkeypatch.setattr(config, "KEYS_ENCRYPTION_KEY", "first-secret")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "shared-gemini")
    user = make_user("alice")
    with get_session() as session:
        keys.set_key(session, user, "gemini", "my-gemini")
    for changed in ("second-secret", ""):
        monkeypatch.setattr(config, "KEYS_ENCRYPTION_KEY", changed)
        with get_session() as session:
            effective = keys.for_user(session, user)
        assert (effective.gemini, effective.gemini_source) == ("shared-gemini", "shared")


def test_get_llm_needs_a_key(no_shared_keys):
    assert get_llm(keys.ApiKeys()) is None
    assert get_llm(keys.ApiKeys(gemini="abc", gemini_source="yours")).model == config.GEMINI_MODEL


def test_unknown_service_rejected(make_user):
    with get_session() as session, pytest.raises(ValueError):
        keys.set_key(session, make_user("alice"), "password", "x")


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
