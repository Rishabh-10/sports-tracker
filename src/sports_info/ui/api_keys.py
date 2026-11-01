"""Sidebar panel where each user adds, replaces or removes their own API keys.

Keys live only in st.session_state: never written to the database, and gone after a refresh,
sign-out or switch of account (session.py clears the session state on each).
"""

import streamlit as st

from sports_info import keys

SAVED_FLAG = "api_key_saved"
OWN_KEYS = "api_keys"


def _own_keys() -> dict[str, str]:
    return st.session_state.setdefault(OWN_KEYS, {})


def keys_for() -> keys.ApiKeys:
    """The keys in effect for this session: the user's own, else the app's shared ones."""
    return keys.resolve(_own_keys())


def _status(service: str, effective: keys.ApiKeys, own: str) -> str:
    source = effective.source(service)
    if source == "yours":
        return f":green[Using your key] `{keys.mask(own)}`"
    if source == "shared":
        return ":blue[Using the app's shared key]"
    return ":orange[Not set]"


def _service_row(service: str, effective: keys.ApiKeys) -> None:
    label = keys.SERVICES[service]
    own = _own_keys().get(service, "")
    st.markdown(f"**{label}** · {_status(service, effective, own)}")
    with st.form(f"api_key_{service}", clear_on_submit=True, border=False):
        value = st.text_input(
            f"{label} API key", type="password", label_visibility="collapsed", autocomplete="off",
            placeholder="Paste a new key to replace yours" if own else "Paste your key",
        )
        submitted = st.form_submit_button("Use this key", width="stretch")
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
                _own_keys()[service] = value
                st.session_state[SAVED_FLAG] = f"Using your {label} key for this session."
                st.session_state["force_refresh"] = True  # fetch anything the old key couldn't
                st.rerun()
    links = f"[Get a free key]({keys.SIGNUP_URLS[service]})"
    st.caption(links)
    if own and st.button("Remove my key", key=f"remove_{service}", type="tertiary", icon=":material/delete:"):
        _own_keys().pop(service, None)
        st.session_state[SAVED_FLAG] = f"{label} key removed."
        st.rerun()


def sidebar() -> None:
    if message := st.session_state.pop(SAVED_FLAG, None):
        st.toast(message, icon=":material/key:")
    effective = keys_for()
    missing = any(effective.source(service) == "none" for service in keys.SERVICES)
    with st.sidebar.expander("API keys", icon=":material/key:", expanded=missing):
        st.caption("Keys you add here are kept only for this browser session and are never saved. "
                   "Paste them again after a refresh or when you sign in again.")
        for service in keys.SERVICES:
            _service_row(service, effective)
