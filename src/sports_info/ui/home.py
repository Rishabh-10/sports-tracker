from datetime import timedelta

import streamlit as st

from sports_info.news.entities import entity_key
from sports_info.services.events import recent_results, upcoming
from sports_info.store import news_repo, repo
from sports_info.store.db import get_session
from sports_info.store.models import utcnow
from sports_info.ui.components import (
    Highlights,
    data_status_sidebar,
    ensure_fresh,
    ensure_news_fresh,
    follow_summary,
    inject_css,
    render_events_by_day,
    render_news,
)
from sports_info.ui.session import require_user_id


def render() -> None:
    inject_css()
    user_id = require_user_id()
    with get_session() as session:
        profile = repo.get_profile(session, user_id)
        follows = repo.get_follows(session, user_id)
    st.title("🏆 Your sports")
    st.caption(f"Following {follow_summary(follows)} · times in {profile.timezone}")
    ensure_fresh()
    ensure_news_fresh()
    data_status_sidebar()
    highlights = Highlights.from_follows(follows)

    st.subheader(f"Coming up in the next {profile.days_ahead} days")
    events = upcoming(user_id, profile.days_ahead)
    if events:
        render_events_by_day(events, profile.timezone, highlights)
    else:
        st.info("Nothing scheduled in this window. Try a longer window in Settings, or check Fixtures.")

    st.subheader("Recent results")
    results = recent_results(user_id)
    if results:
        render_events_by_day(results, profile.timezone, highlights)
    else:
        st.caption("No results in the last few days.")

    st.subheader("Latest news")
    picks = [entity_key(f.sport, f.kind, f.external_id) for f in follows if f.kind != "competition"]
    with get_session() as session:
        sports = {f.sport for f in follows}
        since = utcnow() - timedelta(days=3)
        articles = news_repo.recent_articles(session, sports=sports, entity_keys=picks, since=since, limit=6) if picks else []
        articles = articles or news_repo.recent_articles(session, sports=sports, since=since, limit=6)
        articles = news_repo.unique_stories(articles)
    if articles:
        render_news(articles, follows)
        from sports_info.ui.pages import news_page  # pages imports this module

        st.page_link(news_page(), label="More news", icon=":material/arrow_forward:")
    else:
        st.caption("No news yet.")
