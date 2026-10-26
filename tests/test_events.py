from datetime import datetime, timezone

from sports_info.services.events import select_relevant
from sports_info.store.models import Event, Follow


def event(key, sport, competition, home=None, away=None):
    return Event(
        key=key, sport=sport, competition_id=competition, competition_name=competition, title=key,
        start_utc=datetime(2026, 10, 25, tzinfo=timezone.utc), status="scheduled", home_id=home, away_id=away,
    )


EVENTS = [
    event("ars-che", "football", "PL", "57", "61"),
    event("liv-mci", "football", "PL", "64", "65"),
    event("ars-psg", "football", "CL", "57", "524"),
    event("rma-bay", "football", "CL", "86", "5"),
    event("bar-sev", "football", "PD", "81", "559"),
    event("usgp", "f1", "f1"),
]


def follows(*items):
    return [Follow(sport=s, kind=k, external_id=i, name=i) for s, k, i in items]


def keys(events):
    return [e.key for e in events]


def test_followed_team_narrows_its_competitions():
    mine = follows(("football", "competition", "PL"), ("football", "competition", "CL"), ("football", "team", "57"))
    teams = {("football", "PL"): {"57", "61", "64", "65"}, ("football", "CL"): {"57", "524", "86", "5"}}
    assert keys(select_relevant(EVENTS, mine, teams)) == ["ars-che", "ars-psg"]


def test_competition_without_my_teams_shows_everything():
    mine = follows(("football", "competition", "PL"), ("football", "competition", "CL"), ("football", "team", "57"))
    teams = {("football", "PL"): {"57", "61", "64", "65"}, ("football", "CL"): {"86", "5"}}
    assert keys(select_relevant(EVENTS, mine, teams)) == ["ars-che", "ars-psg", "rma-bay"]


def test_unfollowed_competitions_and_sports_are_excluded():
    mine = follows(("football", "competition", "PD"))
    assert keys(select_relevant(EVENTS, mine, {})) == ["bar-sev"]


def test_f1_shows_every_race_regardless_of_drivers():
    mine = follows(("f1", "competition", "f1"), ("f1", "driver", "leclerc"))
    assert keys(select_relevant(EVENTS, mine, {})) == ["usgp"]


def test_unknown_team_lists_show_whole_competition():
    # No catalog yet (e.g. no API key): fall back to every match.
    mine = follows(("football", "competition", "PL"), ("football", "team", "57"))
    assert keys(select_relevant(EVENTS, mine, {})) == ["ars-che", "liv-mci"]
