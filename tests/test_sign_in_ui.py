"""The app's sign-in flow, driven through Streamlit's AppTest with a faked st.user."""

from pathlib import Path
from unittest import mock

import pytest
import streamlit.user_info
from streamlit.testing.v1 import AppTest

from sports_info.store import repo
from sports_info.store.db import get_session

APP = str(Path(__file__).resolve().parents[1] / "app.py")
AUTH = {
    "redirect_uri": "http://localhost:8501/oauth2callback",
    "cookie_secret": "test-cookie-secret",
    "client_id": "test.apps.googleusercontent.com",
    "client_secret": "test-secret",
    "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
}
ALICE = {"is_logged_in": True, "sub": "google-alice", "email": "alice@example.com", "name": "Alice"}


@pytest.fixture
def run_app(temp_db):
    """Run app.py as the given Google user (None: signed out), optionally without [auth] configured."""

    def run(user=None, *, configured=True, app=None):
        app = app or AppTest.from_file(APP, default_timeout=30)
        # Always pass secrets: with none, AppTest falls back to the developer's real .streamlit/secrets.toml.
        app.secrets["TEST"] = "isolated"
        if configured:
            app.secrets["auth"] = AUTH
        # st.user reads the identity Streamlit decoded from the login cookie; stand in for it here.
        info = user or ({"is_logged_in": False} if configured else {})
        with mock.patch.object(streamlit.user_info, "_get_user_info", return_value=info):
            app.run()
        assert not app.exception, app.exception
        return app

    return run


def test_without_auth_settings_explains_setup(run_app):
    app = run_app(configured=False)
    assert "Google sign-in isn't set up" in app.error[0].value
    assert not app.button


def test_signed_out_shows_only_the_google_button(run_app):
    app = run_app()
    assert [b.label for b in app.button] == ["Sign in with Google"]
    assert not app.sidebar.caption


def test_first_sign_in_creates_account_and_starts_setup(run_app):
    app = run_app(ALICE)
    assert "Signed in as **Alice**" in app.sidebar.caption[0].value
    assert app.title[0].value == "👋 Welcome to Sports Info"
    with get_session() as session:
        user = repo.get_user_by_google_sub(session, "google-alice")
        assert (user.email, user.name) == ("alice@example.com", "Alice")
        assert app.session_state["user_id"] == user.id


def test_returning_user_gets_their_own_account(run_app):
    run_app(ALICE)
    run_app({**ALICE, "name": "Alice B"})  # a new browser session, e.g. after a refresh
    run_app({"is_logged_in": True, "sub": "google-bob", "email": "bob@example.com", "name": "Bob"})
    with get_session() as session:
        assert repo.count_users(session) == 2
        assert repo.get_user_by_google_sub(session, "google-alice").name == "Alice B"


def test_switching_google_accounts_clears_the_previous_session(run_app):
    app = run_app(ALICE)
    app.session_state["chat_draft"] = "alice's unsent question"
    app.session_state["api_keys"] = {"gemini": "alice-gemini-key"}
    app = run_app({"is_logged_in": True, "sub": "google-bob", "email": "bob@example.com", "name": "Bob"}, app=app)
    assert "Signed in as **Bob**" in app.sidebar.caption[0].value
    assert "chat_draft" not in app.session_state
    assert app.session_state["api_keys"] == {}  # Bob never gets Alice's keys


def test_own_api_keys_stay_in_the_session_not_the_database(run_app, monkeypatch):
    from sqlalchemy import inspect

    from sports_info import config, keys
    from sports_info.store.db import init_db

    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(keys, "VALIDATORS", {**keys.VALIDATORS, "gemini": lambda key: None})  # no network
    app = run_app(ALICE)
    next(t for t in app.sidebar.text_input if t.label == "Gemini API key").input("my-gemini-key-1234")
    use_buttons = [b for b in app.sidebar.button if b.label == "Use this key"]  # football-data, then Gemini
    with mock.patch.object(streamlit.user_info, "_get_user_info", return_value=ALICE):
        use_buttons[1].click().run()
    assert not app.exception, app.exception
    assert app.session_state["api_keys"] == {"gemini": "my-gemini-key-1234"}
    assert any("Using your key" in m.value for m in app.sidebar.markdown)
    assert "userapikeys" not in inspect(init_db()).get_table_names()
