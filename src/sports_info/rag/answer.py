"""The RAG pipeline: understand the question, gather context, ask the LLM once."""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime

from sports_info import config
from sports_info.llm.gemini import LLMClient, Message
from sports_info.news.embeddings import Embedder, get_embedder
from sports_info.news.entities import build_index, entity_key
from sports_info.providers import get_providers
from sports_info.rag.context import detect_sports, fixtures_context
from sports_info.rag.retriever import Hit, search
from sports_info.store import repo
from sports_info.store.db import get_session
from sports_info.store.models import Follow, utcnow
from sports_info.timefmt import to_local

SYSTEM_PROMPT = """You are Sports Info, a personal sports assistant for one fan. You answer questions about the \
sports they follow using ONLY the context supplied with each question.

Rules:
- FIXTURES & RESULTS come from official data feeds: trust them for dates, times and scores.
- NEWS items are numbered. Cite every fact you take from them like [2] or [1][3].
- If the context doesn't answer the question, say so plainly and offer what you can tell them instead. \
Never guess scores, dates, injuries, transfers, line-ups or quotes.
- News may be outdated or contradictory: prefer the most recent item and point out conflicts.
- Times in the context are already in the user's timezone. Use the stated current date for words like \
"tomorrow" or "last weekend".
- Be concise: lead with the answer, then a few bullets if useful. No preamble, no sign-off."""

HISTORY_TURNS = 6
NEWS_HITS = 8
_CITATION = re.compile(r"\s?\[\d+\](\[\d+\])*")


@dataclass
class Source:
    number: int
    title: str
    source: str
    url: str
    published_utc: datetime


@dataclass
class PreparedQuestion:
    question: str
    messages: list[Message]
    sources: list[Source] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    fixtures: str = ""
    entities: list[str] = field(default_factory=list)


def _number_sources(hits: list[Hit]) -> tuple[list[Source], dict[str, int]]:
    sources, numbers = [], {}
    for hit in hits:
        article = hit.article
        if article.id not in numbers:
            numbers[article.id] = len(numbers) + 1
            sources.append(Source(numbers[article.id], article.title, article.source, article.url, article.published_utc))
    return sources, numbers


def _following_summary(follows: list[Follow]) -> str:
    """e.g. 'Formula 1: Charles Leclerc, Ferrari; Football: Premier League'."""
    providers = get_providers()
    parts = []
    for sport in sorted({f.sport for f in follows} & set(providers)):
        names = [f.name for f in follows if f.sport == sport and f.kind != "competition"]
        names = names or [f.name for f in follows if f.sport == sport]
        parts.append(f"{providers[sport].label}: {', '.join(names)}")
    return "; ".join(parts)


def build_prompt(
    question: str, *, now: datetime, tz: str, following: str, fixtures: str, hits: list[Hit], numbers: dict[str, int]
) -> str:
    local_now = to_local(now, tz)
    news_blocks = []
    for hit in hits:
        article = hit.article
        body = hit.text.split("\n", 1)[1] if "\n" in hit.text else ""
        header = f"[{numbers[article.id]}] {article.title} ({article.source}, {to_local(article.published_utc, tz):%d %b %H:%M})"
        news_blocks.append(f"{header}\n{body}".strip())
    return "\n\n".join([
        f"Current date and time: {local_now:%A %d %B %Y, %H:%M} ({tz}).",
        f"The user follows: {following}.",
        f"## FIXTURES & RESULTS\n{fixtures}",
        "## NEWS\n" + ("\n\n".join(news_blocks) if news_blocks else "No relevant news articles found."),
        f"## QUESTION\n{question}",
    ])


def prepare(
    user_id: int,
    question: str,
    history: list[Message] | None = None,
    *,
    embedder: Embedder | None = None,
    now: datetime | None = None,
) -> PreparedQuestion:
    """Gather everything the LLM needs. Makes no LLM calls (the free tier is precious)."""
    history = history or []
    now = now or utcnow()
    with get_session() as session:
        profile = repo.get_profile(session, user_id)
        follows = repo.get_follows(session, user_id)
        followed_sports = {f.sport for f in follows}
        index = build_index(session, followed_sports, follows)

        # Follow-ups like "and their next match?" borrow entities and search terms from the last question.
        previous = [m.text for m in history if m.role == "user"][-1:]
        mentioned = index.find(question) or (index.find(previous[0]) if previous else set())
        entity_sports = {index.get(k).sport for k in mentioned}
        sports = detect_sports(" ".join(previous + [question]), entity_sports, followed_sports)
        followed_keys = {entity_key(f.sport, f.kind, f.external_id) for f in follows if f.kind != "competition"}
        search_query = f"{previous[0]} {question}" if previous and not index.find(question) else question

        hits = search(
            session, search_query, embedder=embedder or get_embedder(), sports=sports,
            since=now - config.NEWS_SEARCH_WINDOW, boost_entities=mentioned or followed_keys, k=NEWS_HITS,
        )
        fixtures = fixtures_context(session, user_id, sports=sports, focus=mentioned, index=index, tz=profile.timezone, now=now)

    sources, numbers = _number_sources(hits)
    prompt = build_prompt(question, now=now, tz=profile.timezone, following=_following_summary(follows),
                          fixtures=fixtures, hits=hits, numbers=numbers)
    past = [Message(m.role, _CITATION.sub("", m.text)) for m in history[-HISTORY_TURNS:]]
    return PreparedQuestion(
        question=question,
        messages=past + [Message("user", prompt)],
        sources=sources,
        hits=hits,
        fixtures=fixtures,
        entities=sorted(index.get(k).name for k in mentioned),
    )


def stream_answer(prepared: PreparedQuestion, llm: LLMClient) -> Iterator[str]:
    yield from llm.stream(SYSTEM_PROMPT, prepared.messages)
