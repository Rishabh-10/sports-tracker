from datetime import datetime, timedelta, timezone

from sports_info.providers.base import catalog_item
from sports_info.store import repo
from sports_info.store.db import get_session
from sports_info.store.models import Event, Follow, utcnow


def test_profile_defaults_then_saves(make_user):
    user_id = make_user("alice")
    with get_session() as session:
        assert repo.get_profile(session, user_id).onboarded is False
        repo.save_profile(session, user_id, timezone="Europe/London", days_ahead=10)
    with get_session() as session:
        profile = repo.get_profile(session, user_id)
        assert (profile.timezone, profile.days_ahead, profile.onboarded) == ("Europe/London", 10, True)


def test_replace_follows_and_reset(make_user):
    user_id = make_user("alice")
    with get_session() as session:
        repo.replace_follows(session, user_id, [Follow(sport="f1", kind="driver", external_id="leclerc", name="Leclerc")])
        repo.replace_follows(session, user_id, [Follow(sport="f1", kind="driver", external_id="norris", name="Norris")])
        assert [f.external_id for f in repo.get_follows(session, user_id)] == ["norris"]
        repo.save_profile(session, user_id, timezone="UTC", days_ahead=7)
        repo.reset_user(session, user_id)
        assert repo.get_follows(session, user_id) == []
        assert repo.get_profile(session, user_id).onboarded is False


def test_replace_catalog_only_touches_its_slice(temp_db):
    with get_session() as session:
        repo.replace_catalog(session, "football", "team", "PL", [catalog_item("football", "team", "57", "Arsenal", parent_id="PL")])
        repo.replace_catalog(session, "football", "team", "CL", [catalog_item("football", "team", "57", "Arsenal", parent_id="CL")])
        repo.replace_catalog(session, "football", "team", "PL", [catalog_item("football", "team", "61", "Chelsea", parent_id="PL")])
        assert [i.name for i in repo.get_catalog(session, "football", "team", ["PL"])] == ["Chelsea"]
        assert [i.name for i in repo.get_catalog(session, "football", "team", ["CL"])] == ["Arsenal"]


def test_events_upsert_and_window(temp_db):
    base = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    events = [
        Event(key=f"f1:{i}", sport="f1", competition_id="f1", competition_name="F1", title=str(i),
              start_utc=base + timedelta(days=i), status="scheduled")
        for i in range(3)
    ]
    with get_session() as session:
        repo.upsert_events(session, events)
        repo.upsert_events(session, [Event(**{**events[0].model_dump(), "status": "finished"})])
        window = repo.get_events(session, sports=["f1"], start=base, end=base + timedelta(days=2))
        assert [(e.key, e.status) for e in window] == [("f1:0", "finished"), ("f1:1", "scheduled")]


def test_staleness(temp_db):
    with get_session() as session:
        assert repo.is_stale(session, "events:f1:f1", timedelta(hours=6))
        repo.mark_fetched(session, "events:f1:f1")
        assert not repo.is_stale(session, "events:f1:f1", timedelta(hours=6))
        assert repo.is_stale(session, "events:f1:f1", timedelta(hours=6), now=utcnow() + timedelta(hours=7))
