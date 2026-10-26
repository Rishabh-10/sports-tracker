from itertools import groupby

import streamlit as st

from sports_info import auth
from sports_info.providers import get_providers
from sports_info.services.events import refresh_events
from sports_info.store import repo
from sports_info.store.db import get_session
from sports_info.store.models import utcnow
from sports_info.timefmt import relative
from sports_info.ui import wizard
from sports_info.ui.api_keys import keys_for
from sports_info.ui.session import require_user_id

KIND_LABELS = {"competition": "Competitions", "team": "Teams", "driver": "Drivers", "constructor": "Constructors"}


def render() -> None:
    st.title("⚙️ Settings")
    user_id = require_user_id()

    if st.session_state.get("editing_follows"):
        if wizard.run_wizard(finish_label="Save"):
            st.session_state["editing_follows"] = False
            st.toast("Saved. Your feed now uses the new choices.", icon=":material/check:")
            st.rerun()
        if st.button("Cancel editing"):
            wizard.close_wizard()
            st.session_state["editing_follows"] = False
            st.rerun()
        return

    with get_session() as session:
        profile = repo.get_profile(session, user_id)
        follows = repo.get_follows(session, user_id)
    providers = get_providers()

    st.subheader("What you follow")
    for sport, sport_follows in groupby(follows, key=lambda f: f.sport):
        provider = providers.get(sport)
        if provider is None:
            continue
        st.markdown(f"**{provider.icon} {provider.label}**")
        for kind, items in groupby(sport_follows, key=lambda f: f.kind):
            st.markdown(f"- {KIND_LABELS.get(kind, kind)}: {', '.join(f.name for f in items)}")
    st.caption(f"Timezone {profile.timezone} · showing {profile.days_ahead} days ahead")
    if st.button("Edit sports, teams & preferences", icon=":material/edit:", type="primary"):
        wizard.start_wizard(user_id, prefill=True)
        st.session_state["editing_follows"] = True
        st.rerun()

    st.subheader("Data sources")
    user_providers = get_providers(keys_for(user_id))
    with get_session() as session:
        for sport, provider in user_providers.items():
            last = repo.latest_fetch(session, f"events:{sport}:")
            status = "ready" if provider.is_configured() else f"needs setup: {provider.setup_hint}"
            updated = f"updated {relative(last, utcnow())}" if last else "not fetched yet"
            st.markdown(f"- {provider.icon} **{provider.label}**: {status} · {updated}")
    if st.button("Refresh all data now", icon=":material/refresh:"):
        with st.spinner("Fetching everything again..."):
            report = refresh_events(user_id, force=True)
        for error in report.errors:
            st.warning(error, icon=":material/warning:")
        st.success(f"Refreshed {len(report.refreshed)} dataset(s).")

    st.subheader("Account")
    with st.expander("Change password", icon=":material/key:"):
        with st.form("change_password", clear_on_submit=True):
            current = st.text_input("Current password", type="password", autocomplete="current-password")
            new = st.text_input("New password", type="password", autocomplete="new-password")
            if st.form_submit_button("Change password"):
                try:
                    with get_session() as session:
                        auth.change_password(session, user_id, current, new)
                except auth.AuthError as exc:
                    st.error(str(exc))
                else:
                    st.success("Password changed.")

    st.subheader("Start over")
    confirm = st.checkbox("I want to clear my sports and teams and run setup again")
    if st.button("Reset", icon=":material/restart_alt:", disabled=not confirm):
        with get_session() as session:
            repo.reset_user(session, user_id)
        st.rerun()
