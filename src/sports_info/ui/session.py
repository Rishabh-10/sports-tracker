"""Who is signed in to this browser session."""

import streamlit as st

from sports_info.store.models import User

USER_KEY = "user_id"


def current_user_id() -> int | None:
    return st.session_state.get(USER_KEY)


def require_user_id() -> int:
    """The signed-in user's id; stops the page if nobody is signed in."""
    user_id = current_user_id()
    if user_id is None:
        st.stop()
    return user_id


def sign_in(user: User) -> None:
    # Start from a clean session so nothing from a previous user (chat, wizard, briefings) carries over.
    st.session_state.clear()
    st.session_state[USER_KEY] = user.id


def sign_out() -> None:
    st.session_state.clear()
