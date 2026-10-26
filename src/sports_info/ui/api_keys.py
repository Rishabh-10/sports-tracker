"""Sidebar panel where each user adds, replaces or removes their own API keys."""

import streamlit as st

from sports_info import keys
from sports_info.store.db import get_session

SAVED_FLAG = "api_key_saved"


def keys_for(user_id: int) -> keys.ApiKeys:
    with get_session() as session:
        return keys.for_user(session, user_id)


def _status(service: str, effective: keys.ApiKeys, own: str) -> str:
    source = effective.source(service)
    if source == "yours":
        return f":green[Using your key] `{keys.mask(own)}`"
    if source == "shared":
        return ":blue[Using the app's shared key]"
    return ":orange[Not set]"


def _service_row(user_id: int, service: str, effective: keys.ApiKeys) -> None:
    label = keys.SERVICES[service]
    with get_session() as session:
        own = keys.own_key(session, user_id, service)
    st.markdown(f"**{label}** · {_status(service, effective, own)}")
    with st.form(f"api_key_{service}", clear_on_submit=True, border=False):
        value = st.text_input(
            f"{label} API key", type="password", label_visibility="collapsed", autocomplete="off",
            placeholder="Paste a new key to replace yours" if own else "Paste your key",
        )
        submitted = st.form_submit_button("Save", width="stretch")
    if submitted:
        value = value.strip()
        if not value:
            st.warning("Paste a key first.")
        else:
            try:
                with st.spinner("Checking the key..."):
                    keys.VALIDATORS[service](value)
            except keys.InvalidKey as exc:
                st.error(str(exc))
            else:
                with get_session() as session:
                    keys.set_key(session, user_id, service, value)
                st.session_state[SAVED_FLAG] = f"{label} key saved."
                st.session_state["force_refresh"] = True  # fetch anything the old key couldn't
                st.rerun()
    links = f"[Get a free key]({keys.SIGNUP_URLS[service]})"
    st.caption(links)
    if own and st.button("Remove my key", key=f"remove_{service}", type="tertiary", icon=":material/delete:"):
        with get_session() as session:
            keys.set_key(session, user_id, service, "")
        st.session_state[SAVED_FLAG] = f"{label} key removed."
        st.rerun()


def sidebar(user_id: int) -> None:
    if message := st.session_state.pop(SAVED_FLAG, None):
        st.toast(message, icon=":material/key:")
    effective = keys_for(user_id)
    missing = any(effective.source(service) == "none" for service in keys.SERVICES)
    with st.sidebar.expander("API keys", icon=":material/key:", expanded=missing):
        st.caption("Your keys are private to your account and are only shown masked.")
        for service in keys.SERVICES:
            _service_row(user_id, service, effective)
