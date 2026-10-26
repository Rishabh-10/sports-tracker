"""Showing a RAG answer: streamed text, numbered sources and the context that was used."""

from dataclasses import asdict
from typing import Any

import streamlit as st

from sports_info.llm.gemini import LLMClient, LLMError
from sports_info.providers.base import parse_utc
from sports_info.rag.answer import PreparedQuestion, stream_answer
from sports_info.store.models import utcnow
from sports_info.timefmt import relative


def answer(prepared: PreparedQuestion, llm: LLMClient | None) -> dict[str, Any]:
    """Draw the answer (streaming it if an LLM is configured) and return a record for chat history."""
    text, ok = None, False
    if llm is None:
        text = _without_llm(prepared)
        st.markdown(text)
    else:
        try:
            text = st.write_stream(stream_answer(prepared, llm))
            ok = True
        except LLMError as exc:
            text = f":warning: {exc}"
            st.markdown(text)
    record = {
        "role": "assistant",
        "text": text if isinstance(text, str) else "",
        "ok": ok,
        "sources": [asdict(s) for s in prepared.sources],
        "fixtures": prepared.fixtures,
    }
    details(record)
    return record


def _without_llm(prepared: PreparedQuestion) -> str:
    if not prepared.sources:
        return "Gemini isn't set up yet, and I couldn't find news matching that question."
    lines = ["Gemini isn't set up yet (add your key under **API keys** in the sidebar), "
             "so here are the most relevant articles:"]
    lines += [f"{s.number}. [{s.title}]({s.url}) · {s.source}" for s in prepared.sources]
    return "\n".join(lines)


def details(record: dict[str, Any]) -> None:
    """Expanders listing the sources and the fixtures context behind an answer."""
    sources = record.get("sources") or []
    now = utcnow()
    if sources and record.get("ok"):
        with st.expander(f"Sources ({len(sources)})", icon=":material/link:"):
            for s in sources:
                published = s["published_utc"]
                if isinstance(published, str):  # sources loaded back from the database
                    published = parse_utc(published)
                st.markdown(f"**[{s['number']}]** [{s['title']}]({s['url']}) · {s['source']}, "
                            f"{relative(published, now)}")
    if record.get("fixtures"):
        with st.expander("Fixtures & results I looked at", icon=":material/calendar_month:"):
            st.text(record["fixtures"])
