from datetime import datetime, timezone

import httpx
import pytest

from sports_info.providers.football_data import FootballDataProvider, parse_match
from sports_info.providers.http import ProviderNotConfigured, RateLimitedClient

COMPETITION = {"code": "PL", "name": "Premier League"}


def match(**overrides):
    data = {
        "id": 501,
        "utcDate": "2026-10-25T16:30:00Z",
        "status": "TIMED",
        "matchday": 9,
        "stage": "REGULAR_SEASON",
        "homeTeam": {"id": 57, "name": "Arsenal FC", "shortName": "Arsenal", "crest": "https://x/57.png"},
        "awayTeam": {"id": 61, "name": "Chelsea FC", "shortName": "Chelsea", "crest": "https://x/61.png"},
        "score": {"winner": None, "fullTime": {"home": None, "away": None}},
    }
    data.update(overrides)
    return data


def test_parse_scheduled_match():
    event = parse_match(match(), COMPETITION)
    assert event.key == "football:501"
    assert event.title == "Arsenal vs Chelsea"
    assert event.start_utc == datetime(2026, 10, 25, 16, 30, tzinfo=timezone.utc)
    assert event.status == "scheduled"
    assert event.round == "Matchday 9"
    assert (event.home_id, event.away_id) == ("57", "61")
    assert event.home_score is None


def test_parse_finished_match_with_score():
    event = parse_match(
        match(status="FINISHED", score={"winner": "HOME_TEAM", "fullTime": {"home": 2, "away": 1}}), COMPETITION
    )
    assert event.status == "finished"
    assert (event.home_score, event.away_score) == (2, 1)


def test_parse_knockout_with_unknown_teams():
    event = parse_match(
        match(stage="LAST_16", matchday=None, homeTeam={"id": None, "name": None}, awayTeam={}), COMPETITION
    )
    assert event.title == "TBD vs TBD"
    assert event.home_id is None and event.away_id is None
    assert event.round == "Last 16"


def test_fetch_events_requires_key():
    with pytest.raises(ProviderNotConfigured):
        FootballDataProvider("").fetch_events("PL")


def test_fetch_events_sends_key_and_parses():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("X-Auth-Token")
        seen["path"] = request.url.path
        return httpx.Response(200, json={"competition": COMPETITION, "matches": [match()]})

    client = RateLimitedClient(
        "https://api.test",
        max_calls=10,
        period=60,
        client=httpx.Client(
            base_url="https://api.test", headers={"X-Auth-Token": "secret"}, transport=httpx.MockTransport(handler)
        ),
    )
    events = FootballDataProvider("secret", client=client).fetch_events("PL")
    assert seen == {"token": "secret", "path": "/competitions/PL/matches"}
    assert [e.title for e in events] == ["Arsenal vs Chelsea"]
