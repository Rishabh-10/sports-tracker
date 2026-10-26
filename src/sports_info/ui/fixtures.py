from datetime import timedelta

import streamlit as st

from sports_info.providers import get_providers
from sports_info.services.events import recent_results, upcoming
from sports_info.store import repo
from sports_info.store.db import get_session
from sports_info.ui.components import Highlights, data_status_sidebar, ensure_fresh, inject_css, render_events_by_day
from sports_info.ui.session import require_user_id


def render() -> None:
    inject_css()
    user_id = require_user_id()
    with get_session() as session:
        profile = repo.get_profile(session, user_id)
        follows = repo.get_follows(session, user_id)
    st.title("📅 Fixtures & results")
    ensure_fresh()
    data_status_sidebar()

    providers = get_providers()
    sports = sorted({f.sport for f in follows if f.sport in providers})
    controls = st.columns([2, 3, 3])
    view = controls[0].segmented_control("Show", ["Upcoming", "Results"], default="Upcoming") or "Upcoming"
    chosen = controls[1].pills(
        "Sports", sports, default=sports, selection_mode="multi",
        format_func=lambda s: f"{providers[s].icon} {providers[s].label}",
    ) or []
    days = controls[2].slider("Days", 1, 60, 14 if view == "Upcoming" else 30)

    teams = [f for f in follows if f.kind == "team" and f.sport in chosen]
    team_filter = None
    if teams:
        names = {f.external_id: f.name for f in teams}
        team_filter = st.selectbox("Team", [None, *names], format_func=lambda t: "All teams" if t is None else names[t])

    if view == "Upcoming":
        events = upcoming(user_id, days, sports=chosen)
    else:
        events = recent_results(user_id, timedelta(days=days), sports=chosen)
    if team_filter:
        events = [e for e in events if team_filter in (e.home_id, e.away_id)]

    if events:
        st.caption(f"{len(events)} {'events' if view == 'Upcoming' else 'results'}")
        render_events_by_day(events, profile.timezone, Highlights.from_follows(follows))
    else:
        st.info("Nothing to show for these filters.")
