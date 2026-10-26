import streamlit as st

from sports_info import auth
from sports_info.store.db import get_session
from sports_info.ui.session import sign_in


def render() -> None:
    _, middle, _ = st.columns([1, 2, 1])
    with middle:
        st.title("🏆 Sports Info")
        st.caption("Fixtures, news and answers for the teams and drivers you follow.")
        sign_in_tab, register_tab = st.tabs(["Sign in", "Create account"])

        with sign_in_tab, st.form("sign_in"):
            username = st.text_input("Username", autocomplete="username")
            password = st.text_input("Password", type="password", autocomplete="current-password")
            if st.form_submit_button("Sign in", type="primary", width="stretch"):
                with get_session() as session:
                    user = auth.authenticate(session, username, password)
                if user is None:
                    st.error("Wrong username or password.")
                else:
                    sign_in(user)
                    st.rerun()

        with register_tab, st.form("register"):
            new_username = st.text_input("Choose a username", autocomplete="username")
            new_password = st.text_input("Choose a password", type="password", autocomplete="new-password",
                                         help=f"At least {auth.MIN_PASSWORD_LENGTH} characters.")
            confirm = st.text_input("Repeat the password", type="password", autocomplete="new-password")
            if st.form_submit_button("Create account", type="primary", width="stretch"):
                if new_password != confirm:
                    st.error("The passwords don't match.")
                else:
                    try:
                        with get_session() as session:
                            user = auth.register(session, new_username, new_password)
                    except auth.AuthError as exc:
                        st.error(str(exc))
                    else:
                        sign_in(user)
                        st.rerun()
        st.caption("Each account has its own teams, settings and chats. Accounts are stored only in this app's database.")
