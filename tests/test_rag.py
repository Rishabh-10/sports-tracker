from datetime import timedelta

import pytest

from sports_info.llm.gemini import Message, _friendly_error
from sports_info.news.entities import EntityIndex
from sports_info.news.feeds import Feed
from sports_info.news.ingest import FeedItem, ingest_items
from sports_info.providers.base import catalog_item
from sports_info.rag.answer import SYSTEM_PROMPT, prepare, stream_answer
from sports_info.rag.retriever import keyword_terms, search
from sports_info.store import news_repo, repo
from sports_info.store.db import get_session
from sports_info.store.models import Chunk, Event, Follow, utcnow

F1_FEED = Feed("https://bbc.test/f1.xml", "BBC Sport", "f1")
FOOTBALL_FEED = Feed("https://bbc.test/football.xml", "BBC Sport", "football")


def add_news(session, embedder, feed, *stories, index=EntityIndex([])):
    items = [FeedItem(f"https://news.test/{feed.sport}/{n}", title, "BBC Sport", utcnow() - timedelta(hours=n + 1), body)
             for n, (title, body) in enumerate(stories)]
    ingest_items(session, feed, items, index=index, embedder=embedder)


def test_keyword_terms_drop_stopwords_and_accents():
    assert keyword_terms("What is the latest on Leclerc's injury?") == ["leclerc", "injury"]
    assert keyword_terms("Is Pérez out? Pérez said so") == ["perez", "out", "said"]


def test_keyword_search_ignores_accents_and_ranks(temp_db, fake_embedder):
    with get_session() as session:
        add_news(session, fake_embedder, F1_FEED,
                 ("Pérez extends contract", "Sergio Pérez signs for two more years. Pérez is delighted."),
                 ("Midfield battle heats up", "Ocon praised Perez after a long race in which Haas, Alpine, "
                  "Williams and Sauber all scored points and the midfield fight went down to the final lap."),
                 ("Unrelated", "Gasly tests the new car."))
        session.commit()
        ids = news_repo.keyword_search(session, ["perez"], 10)
        titles = [session.get(Chunk, cid).text for cid in ids]
        assert len(ids) == 2 and titles[0].startswith("Pérez extends")  # more mentions rank first
        assert news_repo.keyword_search(session, ["pérez"], 10) == ids
        assert news_repo.keyword_search(session, ["nobody"], 10) == []
        assert news_repo.keyword_search(session, [], 10) == []


def test_hybrid_search_ranks_relevant_and_filters_sport(temp_db, fake_embedder):
    with get_session() as session:
        add_news(session, fake_embedder, F1_FEED,
                 ("Verstappen wins in Singapore", "Max Verstappen won the Singapore Grand Prix ahead of Leclerc."),
                 ("Tyre rules for 2027", "Pirelli explains new compounds for next season."))
        add_news(session, fake_embedder, FOOTBALL_FEED, ("Singapore friendly", "A football friendly in Singapore."))
        hits = search(session, "Who won in Singapore?", embedder=fake_embedder, sports=["f1"],
                      since=utcnow() - timedelta(days=7))
        assert hits[0].article.title == "Verstappen wins in Singapore"
        assert all(h.article.sport == "f1" for h in hits)


def test_duplicate_headlines_collapse_to_richest_copy(temp_db, fake_embedder):
    with get_session() as session:
        add_news(session, fake_embedder, F1_FEED,
                 ("Leclerc demands answers", ""),  # Google News style: headline only
                 ("Leclerc demands answers", "Leclerc wants Ferrari to investigate."))
        hits = search(session, "Leclerc demands answers", embedder=fake_embedder, sports=["f1"],
                      since=utcnow() - timedelta(days=7))
        assert len({h.article.id for h in hits}) == 1
        assert hits[0].article.summary == "Leclerc wants Ferrari to investigate."
        recent = news_repo.recent_articles(session, sports=["f1"])
        assert [a.summary for a in news_repo.unique_stories(recent)] == ["Leclerc wants Ferrari to investigate."]


def setup_user(session, user_id):
    repo.replace_catalog(session, "f1", "driver", "f1", [catalog_item("f1", "driver", "leclerc", "Charles Leclerc", parent_id="f1")])
    repo.replace_follows(session, user_id, [
        Follow(sport="f1", kind="competition", external_id="f1", name="Formula 1 World Championship"),
        Follow(sport="f1", kind="driver", external_id="leclerc", name="Charles Leclerc"),
    ])
    repo.save_profile(session, user_id, timezone="Europe/London", days_ahead=7)
    repo.upsert_events(session, [Event(
        key="f1:2026-19", sport="f1", competition_id="f1", competition_name="Formula 1", title="Mexico City Grand Prix",
        start_utc=utcnow() + timedelta(days=6), status="scheduled", round="Round 19", venue="Autódromo, Mexico City",
        details_json='{"sessions": [{"name": "Race", "start": "%s"}]}' % (utcnow() + timedelta(days=6)).isoformat(),
    )])


def test_prepare_builds_grounded_prompt(make_user, fake_embedder):
    user_id = make_user("alice")
    with get_session() as session:
        setup_user(session, user_id)
        add_news(session, fake_embedder, F1_FEED, ("Leclerc fumes at Ferrari", "Leclerc said the team paid the price."))
    prepared = prepare(user_id, "Why is Leclerc unhappy?", embedder=fake_embedder)
    prompt = prepared.messages[-1].text
    assert prepared.entities == ["Charles Leclerc"]
    assert "Mexico City Grand Prix" in prompt
    assert "[1] Leclerc fumes at Ferrari (BBC Sport" in prompt
    assert "The user follows: Formula 1: Charles Leclerc." in prompt
    assert prompt.endswith("## QUESTION\nWhy is Leclerc unhappy?")
    assert prepared.sources[0].number == 1


def test_follow_up_reuses_entities_and_strips_old_citations(make_user, fake_embedder):
    user_id = make_user("alice")
    with get_session() as session:
        setup_user(session, user_id)
    history = [Message("user", "How is Leclerc doing?"), Message("model", "He was second [1][2] in Singapore [3].")]
    prepared = prepare(user_id, "and when does he race next?", history, embedder=fake_embedder)
    assert prepared.entities == ["Charles Leclerc"]
    assert prepared.messages[1].text == "He was second in Singapore."


def test_stream_answer_uses_system_prompt(make_user, fake_embedder):
    user_id = make_user("alice")
    with get_session() as session:
        setup_user(session, user_id)
    calls = []

    class FakeLLM:
        model = "fake"

        def stream(self, system, messages, temperature=0.3):
            calls.append((system, messages))
            yield "Next race: Mexico."

    prepared = prepare(user_id, "When is the next race?", embedder=fake_embedder)
    assert "".join(stream_answer(prepared, FakeLLM())) == "Next race: Mexico."
    assert calls[0][0] == SYSTEM_PROMPT


@pytest.mark.parametrize("code,message,expected", [
    (429, "Resource exhausted", "free-tier limit"),
    (400, "API key not valid", "rejected the API key"),
    (404, "models/x is not found", "isn't available"),
])
def test_friendly_errors(code, message, expected):
    exc = Exception(message)
    exc.code, exc.message = code, message
    assert expected in _friendly_error(exc, "gemini-flash-latest")
