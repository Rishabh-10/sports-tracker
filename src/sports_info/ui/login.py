import streamlit as st

from sports_info.ui.session import sign_in_configured


def render() -> None:
    _, middle, _ = st.columns([1, 2, 1])
    with middle:
        st.title("🏆 Sports Info")
        st.caption("Fixtures, news and answers for the teams and drivers you follow.")
        if not sign_in_configured():
            st.error(
                "Google sign-in isn't set up yet. Copy `.streamlit/secrets.toml.example` to "
                "`.streamlit/secrets.toml` and fill in the `[auth]` section (see the README)."
            )
            return
        st.button("Sign in with Google", type="primary", icon=":material/login:", width="stretch",
                  on_click=st.login)
        st.caption("Each account has its own teams, settings and chats. You stay signed in for 30 days.")
