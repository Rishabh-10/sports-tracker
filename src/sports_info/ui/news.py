import streamlit as st

from sports_info import config
from sports_info.llm.gemini import get_llm
from sports_info.news.entities import entity_key
from sports_info.providers import get_providers
from sports_info.rag.answer import prepare
from sports_info.store import news_repo, repo
from sports_info.store.db import get_session
from sports_info.store.models import utcnow
from sports_info.ui import answer_view
from sports_info.ui.api_keys import keys_for
from sports_info.ui.components import data_status_sidebar, ensure_news_fresh, inject_css, render_news
from sports_info.ui.session import require_user_id

PAGE_SIZE = 30
MINE, EVERYTHING = "__mine__", "__all__"


def render() -> None:
    inject_css()
    st.title("📰 News")
    user_id = require_user_id()
    with get_session() as session:
        follows = repo.get_follows(session, user_id)
    ensure_news_fresh()
    data_status_sidebar()

    providers = get_providers()
    sports = sorted({f.sport for f in follows if f.sport in providers})
    picks = {entity_key(f.sport, f.kind, f.external_id): f.name for f in follows if f.kind != "competition"}

    left, right = st.columns([2, 3])
    chosen_sports = left.pills(
        "Sports", sports, default=sports, selection_mode="multi",
        format_func=lambda s: f"{providers[s].icon} {providers[s].label}",
    ) or []
    options = ([MINE] if picks else []) + list(picks) + [EVERYTHING]
    labels = {MINE: "Everything I follow", EVERYTHING: "All news in these sports", **picks}
    about = right.selectbox("About", options, format_func=labels.get)

    limit = st.session_state.get("news_limit", PAGE_SIZE)
    entity_filter = None if about == EVERYTHING else (list(picks) if about == MINE else [about])
    with get_session() as session:
        articles = news_repo.recent_articles(
            session, sports=chosen_sports, entity_keys=entity_filter,
            since=utcnow() - config.NEWS_RETENTION, limit=limit + 1,
        )

    llm = get_llm(keys_for(user_id))
    if llm is not None and articles:
        if about == MINE:
            target = "the teams and drivers I follow"
        elif about == EVERYTHING:
            target = " and ".join(providers[s].label for s in chosen_sports)
        else:
            target = picks[about]
        _briefing(user_id, target, llm)

    if not articles:
        st.info("No articles yet for this filter. Try 'All news in these sports', or refresh in a few minutes.")
        return
    render_news(news_repo.unique_stories(articles[:limit]), follows)
    if len(articles) > limit and st.button("Show more", icon=":material/expand_more:"):
        st.session_state["news_limit"] = limit + PAGE_SIZE
        st.rerun()


def _briefing(user_id: int, target: str, llm) -> None:
    """A 'catch me up' summary for the current filter, kept for the rest of the hour."""
    key = (target, utcnow().strftime("%Y-%m-%d %H"))
    briefings = st.session_state.setdefault("briefings", {})
    if key not in briefings:
        if not st.button(f"Catch me up on {target}", icon=":material/auto_awesome:", type="primary"):
            return
        question = f"Catch me up on the most important news from the last few days about {target}."
        with st.container(border=True):
            with st.spinner("Reading the latest articles..."):
                prepared = prepare(user_id, question)
            record = answer_view.answer(prepared, llm)
        if record["ok"]:
            briefings[key] = record
        return
    with st.container(border=True):
        st.markdown(briefings[key]["text"])
        answer_view.details(briefings[key])
