"""Entry point: `streamlit run app.py`. Sign-in first, then setup on a user's first visit, then the app."""

import streamlit as st

from sports_info.store import repo
from sports_info.store.db import LegacyDatabaseError, get_session, init_db
from sports_info.ui import api_keys, pages
from sports_info.ui.session import current_user_id, forget_user, sign_out

st.set_page_config(page_title="Sports Info", page_icon="🏆", layout="wide")
try:
    init_db()
except LegacyDatabaseError as exc:
    st.error(str(exc), icon=":material/database:")
    st.stop()

user_id = current_user_id()
with get_session() as session:
    user = repo.get_user(session, user_id) if user_id is not None else None
    onboarded = user is not None and repo.get_profile(session, user.id).onboarded

if user is None:
    if user_id is not None:
        forget_user()  # drop a stale id, e.g. the database was replaced; the account is recreated
        st.rerun()
    st.navigation([pages.login_page()], position="hidden").run()
else:
    with st.sidebar:
        st.caption(f"Signed in as **{user.name or user.email}**")
        if st.button("Sign out", icon=":material/logout:", width="stretch"):
            sign_out()
    api_keys.sidebar(user.id)
    if onboarded:
        st.navigation(pages.main_pages()).run()
    else:
        st.navigation([pages.welcome_page()], position="hidden").run()
