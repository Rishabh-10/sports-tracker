"""Who is signed in: Streamlit's st.user (Google, kept for 30 days by a login cookie)."""

import streamlit as st

from sports_info import auth
from sports_info.store.db import get_session

USER_KEY = "user_id"
SUB_KEY = "user_sub"


def sign_in_configured() -> bool:
    """Whether .streamlit/secrets.toml (or the Cloud secrets) has an [auth] section for st.login."""
    try:
        return "auth" in st.secrets
    except FileNotFoundError:  # no secrets file at all
        return False


def current_user_id() -> int | None:
    """The signed-in user's account id, creating the account on first sign-in."""
    # st.user has no is_logged_in until [auth] is configured.
    if not sign_in_configured() or not st.user.is_logged_in:
        return None
    google_sub = st.user.sub
    if st.session_state.get(SUB_KEY) != google_sub:
        # Start from a clean session so nothing from a previous user (chat, wizard, briefings) carries over.
        st.session_state.clear()
        with get_session() as session:
            user = auth.sign_in(session, google_sub, st.user.get("email"), st.user.get("name"))
        st.session_state[USER_KEY] = user.id
        st.session_state[SUB_KEY] = google_sub
    return st.session_state[USER_KEY]


def require_user_id() -> int:
    """The signed-in user's id; stops the page if nobody is signed in."""
    user_id = st.session_state.get(USER_KEY)
    if user_id is None:
        st.stop()
    return user_id


def forget_user() -> None:
    """Drop the cached account id, so the next run looks the account up again."""
    st.session_state.clear()


def sign_out() -> None:
    st.session_state.clear()
    st.logout()
