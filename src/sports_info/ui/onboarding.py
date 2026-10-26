import streamlit as st

from sports_info.ui import wizard
from sports_info.ui.session import require_user_id


def render() -> None:
    st.title("👋 Welcome to Sports Info")
    st.write("Tell me what you follow and I'll keep track of the fixtures, races and results for you. "
             "You can change any of this later in Settings.")
    if not wizard.is_active():
        wizard.start_wizard(require_user_id(), prefill=False)
    if wizard.run_wizard(finish_label="Let's go"):
        st.rerun()
