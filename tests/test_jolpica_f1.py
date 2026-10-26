import json
from datetime import datetime, timezone

from sports_info.providers.jolpica_f1 import parse_driver_standing, parse_race

RACE = {
    "season": "2026",
    "round": "18",
    "raceName": "United States Grand Prix",
    "Circuit": {
        "circuitId": "americas",
        "circuitName": "Circuit of the Americas",
        "Location": {"locality": "Austin", "country": "USA"},
    },
    "date": "2026-10-25",
    "time": "20:00:00Z",
    "Qualifying": {"date": "2026-10-24", "time": "21:00:00Z"},
    "FirstPractice": {"date": "2026-10-23", "time": "17:30:00Z"},
}


def result(position, driver_id, code, constructor_id):
    return {
        "position": str(position),
        "positionText": str(position),
        "points": "25",
        "grid": "1",
        "status": "Finished",
        "Driver": {"driverId": driver_id, "code": code, "givenName": "Given", "familyName": code.title()},
        "Constructor": {"constructorId": constructor_id, "name": constructor_id.title()},
    }


def test_parse_upcoming_race_orders_sessions_and_ends_with_race():
    event = parse_race(RACE)
    details = json.loads(event.details_json)
    assert event.key == "f1:2026-18"
    assert event.status == "scheduled"
    assert event.start_utc == datetime(2026, 10, 25, 20, 0, tzinfo=timezone.utc)
    assert event.venue == "Circuit of the Americas, Austin"
    assert [s["name"] for s in details["sessions"]] == ["Practice 1", "Qualifying", "Race"]


def test_parse_finished_race_sorts_results():
    event = parse_race(RACE, [result(2, "leclerc", "LEC", "ferrari"), result(1, "max_verstappen", "VER", "red_bull")])
    details = json.loads(event.details_json)
    assert event.status == "finished"
    assert [r["code"] for r in details["results"]] == ["VER", "LEC"]


def test_parse_driver_standing_mentions_team():
    item = parse_driver_standing(
        {
            "position": "3",
            "Driver": {"driverId": "hamilton", "code": "HAM", "givenName": "Lewis", "familyName": "Hamilton"},
            "Constructors": [{"constructorId": "ferrari", "name": "Ferrari"}],
        }
    )
    assert (item.kind, item.external_id, item.name) == ("driver", "hamilton", "Lewis Hamilton")
    assert item.info == "Ferrari · P3 in standings"
