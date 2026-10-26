"""Step-by-step picker for sports, competitions, teams/drivers and preferences.

Used on first launch and again from Settings (prefilled) to edit choices.
Selections live in st.session_state[STATE]; Streamlit drops a widget's state once it
isn't drawn, so each widget is re-seeded from there whenever its step is shown.
"""

from typing import Any

import streamlit as st

from sports_info.providers import get_provider, get_providers
from sports_info.providers.http import ProviderError
from sports_info.services import catalog
from sports_info.store import repo
from sports_info.store.db import get_session
from sports_info.store.models import Follow
from sports_info.timefmt import all_timezones, default_timezone
from sports_info.ui.api_keys import keys_for

STATE = "_wizard"
PREFIX = "wiz_"
STEPS = ["Sports", "Competitions", "Teams & drivers", "Preferences"]


def start_wizard(user_id: int, *, prefill: bool) -> None:
    for key in [k for k in st.session_state if str(k).startswith(PREFIX)]:
        del st.session_state[key]
    state: dict[str, Any] = {
        "user_id": user_id,
        "step": 0,
        "sports": [],
        "competitions": {},  # sport -> [competition ids]
        "follows": {},  # "sport:kind" -> [external ids]
        "timezone": default_timezone(),
        "days_ahead": 7,
    }
    if prefill:
        with get_session() as session:
            profile = repo.get_profile(session, user_id)
            follows = repo.get_follows(session, user_id)
        state["timezone"] = profile.timezone
        state["days_ahead"] = profile.days_ahead
        for follow in follows:
            if follow.sport not in get_providers():
                continue
            if follow.sport not in state["sports"]:
                state["sports"].append(follow.sport)
            if follow.kind == "competition":
                state["competitions"].setdefault(follow.sport, []).append(follow.external_id)
            else:
                state["follows"].setdefault(f"{follow.sport}:{follow.kind}", []).append(follow.external_id)
    st.session_state[STATE] = state


def is_active() -> bool:
    return STATE in st.session_state


def close_wizard() -> None:
    st.session_state.pop(STATE, None)
    for key in [k for k in st.session_state if str(k).startswith(PREFIX)]:
        del st.session_state[key]


def _bind(key: str, saved: Any, options: list[Any] | None = None) -> str:
    """Seed a widget from wizard state, dropping values no longer among its options."""
    widget_key = PREFIX + key
    value = st.session_state.get(widget_key, saved)
    if options is not None:
        if isinstance(value, list):
            value = [v for v in value if v in options]
        elif value not in options:
            value = options[0]
    st.session_state[widget_key] = value
    return widget_key


def _names(sport: str, kind: str) -> dict[str, str]:
    with get_session() as session:
        return {item.external_id: item.name for item in repo.get_catalog(session, sport, kind)}


# --- steps (each returns whether the user may continue) -----------------------


def _step_sports(state: dict[str, Any]) -> bool:
    st.markdown("**Which sports do you follow?**")
    providers = list(get_providers(keys_for(state["user_id"])).values())
    selected = []
    for column, provider in zip(st.columns(len(providers)), providers):
        with column, st.container(border=True):
            st.markdown(f"### {provider.icon} {provider.label}")
            st.caption(provider.blurb)
            if not provider.is_configured():
                st.caption(f":orange[Needs setup: {provider.setup_hint}.]")
            key = _bind(f"sport_{provider.sport}", provider.sport in state["sports"])
            if st.checkbox(f"Follow {provider.label}", key=key):
                selected.append(provider.sport)
    st.caption("Cricket and more sports are coming in a later update.")
    state["sports"] = selected
    return bool(selected)


def _step_competitions(state: dict[str, Any]) -> bool:
    ok = True
    user_keys = keys_for(state["user_id"])
    for sport in state["sports"]:
        provider = get_provider(sport, user_keys)
        st.markdown(f"#### {provider.icon} {provider.label}")
        try:
            with st.spinner(f"Loading {provider.label} competitions..."):
                competitions = catalog.competitions(sport, keys=user_keys)
        except ProviderError as exc:
            st.error(f"Couldn't load competitions: {exc}")
            ok = False
            continue
        if provider.single_competition:
            state["competitions"][sport] = [competitions[0].external_id]
            st.caption(f"You'll get every race weekend of the {competitions[0].name}.")
            continue
        options = [c.external_id for c in competitions]
        labels = {c.external_id: f"{c.name} ({c.info})" if c.info else c.name for c in competitions}
        key = _bind(f"comps_{sport}", state["competitions"].get(sport, []), options)
        selected = st.multiselect(
            "Competitions", options, format_func=labels.get, key=key, placeholder="Choose one or more"
        )
        state["competitions"][sport] = selected
        ok = ok and bool(selected)
    return ok


def _step_follows(state: dict[str, Any]) -> bool:
    user_keys = keys_for(state["user_id"])
    for sport in state["sports"]:
        provider = get_provider(sport, user_keys)
        st.markdown(f"#### {provider.icon} {provider.label}")
        if not provider.is_configured():
            st.info(
                f"To pick specific teams, {provider.setup_hint}. "
                "Until then you'll see every match in the competitions you chose."
            )
            continue
        try:
            with st.spinner(f"Loading {provider.label} options..."):
                by_kind = catalog.participants(sport, state["competitions"].get(sport, []), keys=user_keys)
        except ProviderError as exc:
            st.warning(f"Couldn't load {provider.label} options: {exc}")
            continue
        for kind, label in provider.follow_kinds.items():
            items = by_kind.get(kind, [])
            options = [i.external_id for i in items]
            labels = {i.external_id: f"{i.name} · {i.info}" if i.info else i.name for i in items}
            key = _bind(f"follow_{sport}_{kind}", state["follows"].get(f"{sport}:{kind}", []), options)
            state["follows"][f"{sport}:{kind}"] = st.multiselect(
                label,
                options,
                format_func=lambda x, labels=labels: labels.get(x, x),
                key=key,
                placeholder=f"Search {label.lower()} (optional)",
            )
        if "team" in provider.follow_kinds:
            st.caption(
                "Optional. With teams picked, each competition only shows their matches "
                "(unless none of your teams play in it). Leave empty to see every match."
            )
    return True


def _step_preferences(state: dict[str, Any]) -> bool:
    zones = all_timezones()
    state["timezone"] = st.selectbox("Your timezone", zones, key=_bind("timezone", state["timezone"], zones))
    state["days_ahead"] = st.slider(
        "Show events this many days ahead", 3, 30, key=_bind("days_ahead", state["days_ahead"])
    )
    st.markdown("**Summary**")
    for sport in state["sports"]:
        provider = get_provider(sport)
        competitions = _names(sport, "competition")
        picks = [competitions.get(c, c) for c in state["competitions"].get(sport, [])]
        for kind in provider.follow_kinds:
            names = _names(sport, kind)
            picks += [names.get(i, i) for i in state["follows"].get(f"{sport}:{kind}", [])]
        st.markdown(f"- {provider.icon} **{provider.label}**: {', '.join(picks) or 'everything'}")
    return True


def _save(state: dict[str, Any]) -> None:
    follows = []
    for sport in state["sports"]:
        provider = get_provider(sport)
        competitions = _names(sport, "competition")
        for competition_id in state["competitions"].get(sport, []):
            follows.append(Follow(user_id=state["user_id"], sport=sport, kind="competition", external_id=competition_id,
                                  name=competitions.get(competition_id, competition_id)))
        for kind in provider.follow_kinds:
            names = _names(sport, kind)
            for external_id in state["follows"].get(f"{sport}:{kind}", []):
                follows.append(Follow(user_id=state["user_id"], sport=sport, kind=kind, external_id=external_id,
                                      name=names.get(external_id, external_id)))
    with get_session() as session:
        repo.replace_follows(session, state["user_id"], follows)
        repo.save_profile(session, state["user_id"], timezone=state["timezone"], days_ahead=state["days_ahead"])


def run_wizard(*, finish_label: str = "Finish") -> bool:
    """Draw the current step. Returns True once the user has saved."""
    state = st.session_state[STATE]
    step = state["step"]
    st.progress((step + 1) / len(STEPS), text=f"Step {step + 1} of {len(STEPS)}: {STEPS[step]}")
    can_continue = [_step_sports, _step_competitions, _step_follows, _step_preferences][step](state)

    st.divider()
    back, _, forward = st.columns([1, 3, 1])
    if step > 0 and back.button("Back", icon=":material/arrow_back:", width="stretch"):
        state["step"] -= 1
        st.rerun()
    if step < len(STEPS) - 1:
        if forward.button("Next", icon=":material/arrow_forward:", type="primary",
                          disabled=not can_continue, width="stretch"):
            state["step"] += 1
            st.rerun()
    elif forward.button(finish_label, icon=":material/check:", type="primary", width="stretch"):
        _save(state)
        close_wizard()
        return True
    return False
