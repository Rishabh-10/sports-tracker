"""Page definitions, shared by the navigation in app.py and by links between pages.

Streamlit identifies a page by its url_path, so a freshly built Page links to the registered one.
"""

import streamlit as st

from sports_info.ui import ask, fixtures, home, login, news, onboarding, settings


def main_pages() -> list[st.Page]:
    return [
        st.Page(home.render, title="Home", icon=":material/home:", url_path="home", default=True),
        st.Page(fixtures.render, title="Fixtures & results", icon=":material/calendar_month:", url_path="fixtures"),
        news_page(),
        st.Page(ask.render, title="Ask", icon=":material/forum:", url_path="ask"),
        st.Page(settings.render, title="Settings", icon=":material/settings:", url_path="settings"),
    ]


def news_page() -> st.Page:
    return st.Page(news.render, title="News", icon=":material/newspaper:", url_path="news")


def login_page() -> st.Page:
    return st.Page(login.render, title="Sign in", icon=":material/login:", url_path="signin", default=True)


def welcome_page() -> st.Page:
    return st.Page(onboarding.render, title="Welcome", icon=":material/waving_hand:", url_path="welcome", default=True)
