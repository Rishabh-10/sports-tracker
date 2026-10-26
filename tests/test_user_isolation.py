"""Each user sees only their own follows, events, news context and conversations."""

import json
from datetime import timedelta

import pytest

from sports_info.news.feeds import Feed
from sports_info.news.ingest import FeedItem, ingest_items
from sports_info.news.entities import EntityIndex
from sports_info.rag.answer import prepare
from sports_info.services.events import recent_results, upcoming
from sports_info.store import repo
from sports_info.store.db import get_session
from sports_info.store.models import ChatMessage, Event, Follow, utcnow


def follow(sport, kind, external_id, name):
    return Follow(sport=sport, kind=kind, external_id=external_id, name=name)


@pytest.fixture
def two_users(make_user):
    """alice follows F1 (Leclerc); bob follows the Premier League."""
    alice, bob = make_user("alice"), make_user("bob")
    soon = utcnow() + timedelta(days=2)
    with get_session() as session:
        repo.replace_follows(session, alice, [follow("f1", "competition", "f1", "Formula 1"),
                                              follow("f1", "driver", "leclerc", "Charles Leclerc")])
        repo.replace_follows(session, bob, [follow("football", "competition", "PL", "Premier League")])
        repo.save_profile(session, alice, timezone="Europe/Rome", days_ahead=7)
        repo.save_profile(session, bob, timezone="Asia/Kolkata", days_ahead=14)
        repo.upsert_events(session, [
            Event(key="f1:1", sport="f1", competition_id="f1", competition_name="Formula 1", title="Mexico GP",
                  start_utc=soon, status="scheduled", details_json='{"sessions": []}'),
            Event(key="football:1", sport="football", competition_id="PL", competition_name="Premier League",
                  title="Arsenal vs Chelsea", start_utc=soon, status="scheduled", home_name="Arsenal", away_name="Chelsea"),
            Event(key="football:0", sport="football", competition_id="PL", competition_name="Premier League",
                  title="Spurs vs Wolves", start_utc=utcnow() - timedelta(days=1), status="finished",
                  home_name="Spurs", away_name="Wolves", home_score=1, away_score=0),
        ])
    return alice, bob


def test_follows_and_profiles_are_separate(two_users):
    alice, bob = two_users
    with get_session() as session:
        assert [f.name for f in repo.get_follows(session, alice)] == ["Formula 1", "Charles Leclerc"]
        assert [f.name for f in repo.get_follows(session, bob)] == ["Premier League"]
        assert repo.get_profile(session, alice).timezone == "Europe/Rome"
        assert repo.get_profile(session, bob).timezone == "Asia/Kolkata"
        # Saving one user's follows leaves the other's alone.
        repo.replace_follows(session, alice, [])
        assert [f.name for f in repo.get_follows(session, bob)] == ["Premier League"]


def test_events_are_filtered_per_user(two_users):
    alice, bob = two_users
    assert [e.title for e in upcoming(alice, 7)] == ["Mexico GP"]
    assert [e.title for e in upcoming(bob, 7)] == ["Arsenal vs Chelsea"]
    assert recent_results(alice) == []
    assert [e.title for e in recent_results(bob)] == ["Spurs vs Wolves"]


def test_rag_context_uses_only_the_askers_follows(two_users, fake_embedder):
    alice, bob = two_users
    with get_session() as session:
        for feed, title in [(Feed("https://f1.test", "BBC", "f1"), "Leclerc on pole in Mexico"),
                            (Feed("https://pl.test", "BBC", "football"), "Arsenal injury update")]:
            ingest_items(session, feed, [FeedItem(f"{feed.url}/1", title, "BBC", utcnow(), title)],
                         index=EntityIndex([]), embedder=fake_embedder)
    alice_prompt = prepare(alice, "What's the latest?", embedder=fake_embedder).messages[-1].text
    bob_prompt = prepare(bob, "What's the latest?", embedder=fake_embedder).messages[-1].text
    assert "Mexico GP" in alice_prompt and "Leclerc on pole" in alice_prompt
    assert "Arsenal" not in alice_prompt
    assert "Arsenal vs Chelsea" in bob_prompt and "Arsenal injury update" in bob_prompt
    assert "Leclerc" not in bob_prompt and "Mexico" not in bob_prompt


def test_conversations_are_private(two_users):
    alice, bob = two_users
    with get_session() as session:
        convo = repo.create_conversation(session, alice, "Leclerc chat")
        repo.add_message(session, alice, convo.id, ChatMessage(role="user", text="How is Leclerc?"))
        repo.add_message(session, alice, convo.id, ChatMessage(
            role="assistant", text="P2 [1]", sources_json=json.dumps([{"number": 1}])))

        assert [c.title for c in repo.list_conversations(session, alice)] == ["Leclerc chat"]
        assert repo.list_conversations(session, bob) == []
        # Knowing the id isn't enough: bob can't read, write to or delete alice's conversation.
        assert repo.get_conversation(session, bob, convo.id) is None
        assert repo.get_messages(session, bob, convo.id) == []
        with pytest.raises(PermissionError):
            repo.add_message(session, bob, convo.id, ChatMessage(role="user", text="hi"))
        repo.delete_conversation(session, bob, convo.id)
        assert len(repo.get_messages(session, alice, convo.id)) == 2

        repo.delete_conversation(session, alice, convo.id)
        assert repo.list_conversations(session, alice) == []
