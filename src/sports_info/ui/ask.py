import json

import streamlit as st

from sports_info.llm.gemini import Message, get_llm
from sports_info.rag.answer import prepare
from sports_info.store import repo
from sports_info.store.db import get_session
from sports_info.store.models import ChatMessage, Follow
from sports_info.ui import answer_view
from sports_info.ui.api_keys import keys_for
from sports_info.ui.components import data_status_sidebar, ensure_fresh, ensure_news_fresh, inject_css
from sports_info.ui.session import require_user_id

CURRENT = "conversation_id"


def _suggestions(follows: list[Follow]) -> list[str]:
    picks = [f for f in follows if f.kind != "competition"]
    teams = [f.name for f in picks if f.kind == "team"]
    drivers = [f.name for f in picks if f.kind == "driver"]
    suggestions = []
    if picks:
        suggestions.append(f"What's the latest news on {picks[0].name}?")
    if any(f.sport == "f1" for f in follows):
        suggestions.append(f"When is the next race, and how has {drivers[0]} been doing?" if drivers
                           else "When is the next race, and who's in form?")
    if teams:
        suggestions.append(f"When do {teams[0]} play next, and is there any injury news?")
    elif any(f.sport == "football" for f in follows):
        suggestions.append("What were the big football stories this week?")
    return suggestions[:3]


def _record(message: ChatMessage) -> dict:
    return {"role": message.role, "text": message.text, "ok": message.ok,
            "sources": json.loads(message.sources_json or "[]"), "fixtures": message.fixtures}


def _conversation_sidebar(user_id: int, current: int | None) -> None:
    with get_session() as session:
        conversations = repo.list_conversations(session, user_id)
    with st.sidebar:
        if st.button("New conversation", icon=":material/add_comment:", width="stretch"):
            st.session_state.pop(CURRENT, None)
            st.rerun()
        if conversations:
            st.caption("Your conversations")
        for conversation in conversations:
            label = conversation.title if len(conversation.title) <= 38 else conversation.title[:37] + "…"
            selected = conversation.id == current
            if st.button(label, key=f"conv_{conversation.id}", width="stretch",
                         type="primary" if selected else "tertiary"):
                st.session_state[CURRENT] = conversation.id
                st.rerun()
        if current is not None and st.button("Delete this conversation", icon=":material/delete:", width="stretch"):
            with get_session() as session:
                repo.delete_conversation(session, user_id, current)
            st.session_state.pop(CURRENT, None)
            st.rerun()


def render() -> None:
    inject_css()
    st.title("💬 Ask")
    user_id = require_user_id()
    with get_session() as session:
        follows = repo.get_follows(session, user_id)
        current = st.session_state.get(CURRENT)
        if current is not None and repo.get_conversation(session, user_id, current) is None:
            current = None  # deleted, or not this user's
        messages = repo.get_messages(session, user_id, current) if current is not None else []
    ensure_fresh()
    ensure_news_fresh()
    data_status_sidebar()
    llm = get_llm(keys_for(user_id))
    _conversation_sidebar(user_id, current)
    if llm is not None:
        st.sidebar.caption(f"Answers by {llm.model}")

    if llm is None:
        st.info("Add your free Gemini key under **API keys** in the sidebar to get written answers. "
                "Until then I'll show the articles that best match your question.",
                icon=":material/key:")

    if not messages:
        st.caption("Ask about your teams, drivers, fixtures or the latest news. Answers cite their sources, "
                   "and your conversations are saved to your account.")
        for column, suggestion in zip(st.columns(3), _suggestions(follows)):
            if column.button(suggestion, width="stretch"):
                st.session_state["pending_question"] = suggestion
                st.rerun()

    for message in messages:
        with st.chat_message(message.role):
            st.markdown(message.text)
            if message.role == "assistant":
                answer_view.details(_record(message))

    question = st.chat_input("Ask anything about the sports you follow") or st.session_state.pop("pending_question", None)
    if not question:
        return
    history = [Message("user" if m.role == "user" else "model", m.text)
               for m in messages if m.role == "user" or m.ok]
    with st.chat_message("user"):
        st.markdown(question)
    with get_session() as session:
        if current is None:
            current = repo.create_conversation(session, user_id, question).id
            st.session_state[CURRENT] = current
        repo.add_message(session, user_id, current, ChatMessage(role="user", text=question))

    with st.chat_message("assistant"):
        with st.spinner("Searching news and fixtures..."):
            prepared = prepare(user_id, question, history)
        record = answer_view.answer(prepared, llm)
    with get_session() as session:
        repo.add_message(session, user_id, current, ChatMessage(
            role="assistant", text=record["text"], ok=record["ok"],
            sources_json=json.dumps(record["sources"], default=str), fixtures=record["fixtures"],
        ))
    st.rerun()  # redraw so the sidebar shows the new or updated conversation
