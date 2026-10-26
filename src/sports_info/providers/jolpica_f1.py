"""Formula 1 via the Jolpica API (Ergast successor). No key needed; ~4 requests/second."""

import json
from collections import defaultdict
from datetime import datetime
from typing import Any

from sports_info.providers.base import SportProvider, catalog_item, parse_utc
from sports_info.providers.http import RateLimitedClient
from sports_info.store.models import CatalogItem, Event

BASE_URL = "https://api.jolpi.ca/ergast/f1"
SPORT = "f1"
COMPETITION_ID = "f1"
COMPETITION_NAME = "Formula 1"
PAGE_SIZE = 100

# Race-weekend sessions in the order they usually happen.
SESSIONS = [
    ("FirstPractice", "Practice 1"),
    ("SecondPractice", "Practice 2"),
    ("ThirdPractice", "Practice 3"),
    ("SprintQualifying", "Sprint Qualifying"),
    ("Sprint", "Sprint"),
    ("Qualifying", "Qualifying"),
]


def _session_start(data: dict[str, Any]) -> datetime:
    return parse_utc(f"{data['date']}T{data.get('time') or '00:00:00Z'}")


def driver_name(driver: dict[str, Any]) -> str:
    return f"{driver['givenName']} {driver['familyName']}"


def parse_result(row: dict[str, Any]) -> dict[str, Any]:
    driver = row["Driver"]
    constructor = row["Constructor"]
    return {
        "position": int(row["position"]),
        "position_text": row.get("positionText", row["position"]),
        "driver_id": driver["driverId"],
        "driver": driver_name(driver),
        "code": driver.get("code") or driver["familyName"][:3].upper(),
        "constructor_id": constructor["constructorId"],
        "constructor": constructor["name"],
        "points": float(row.get("points", 0)),
        "grid": int(row["grid"]) if row.get("grid", "").isdigit() else None,
        "status": row.get("status"),
    }


def parse_race(race: dict[str, Any], results: list[dict[str, Any]] | None = None) -> Event:
    circuit = race["Circuit"]
    location = circuit.get("Location", {})
    start = _session_start(race)
    sessions = [
        {"name": label, "start": _session_start(race[field]).isoformat()}
        for field, label in SESSIONS
        if field in race
    ]
    sessions.sort(key=lambda s: s["start"])
    sessions.append({"name": "Race", "start": start.isoformat()})
    parsed_results = sorted((parse_result(r) for r in results or []), key=lambda r: r["position"])
    return Event(
        key=f"{SPORT}:{race['season']}-{race['round']}",
        sport=SPORT,
        competition_id=COMPETITION_ID,
        competition_name=COMPETITION_NAME,
        title=race["raceName"],
        start_utc=start,
        status="finished" if parsed_results else "scheduled",
        round=f"Round {race['round']}",
        venue=", ".join(p for p in (circuit.get("circuitName"), location.get("locality")) if p),
        details_json=json.dumps(
            {
                "country": location.get("country"),
                "circuit_id": circuit.get("circuitId"),
                "sessions": sessions,
                "results": parsed_results,
            }
        ),
    )


def parse_driver_standing(row: dict[str, Any]) -> CatalogItem:
    driver = row["Driver"]
    constructors = row.get("Constructors") or []
    team = constructors[-1]["name"] if constructors else None
    return catalog_item(
        SPORT,
        "driver",
        driver["driverId"],
        driver_name(driver),
        parent_id=COMPETITION_ID,
        short_name=driver.get("code"),
        info=f"{team} · P{row['position']} in standings" if team and row.get("position") else team,
    )


def parse_constructor(data: dict[str, Any]) -> CatalogItem:
    return catalog_item(
        SPORT,
        "constructor",
        data["constructorId"],
        data["name"],
        parent_id=COMPETITION_ID,
        info=data.get("nationality"),
    )


class JolpicaF1Provider(SportProvider):
    sport = SPORT
    label = "Formula 1"
    icon = "🏎️"
    blurb = "Every Grand Prix weekend, with your drivers and constructors highlighted"
    follow_kinds = {"driver": "Drivers", "constructor": "Constructors"}
    single_competition = True

    def __init__(self, client: RateLimitedClient | None = None):
        self.client = client or RateLimitedClient(BASE_URL, max_calls=4, period=1.0)

    def list_competitions(self) -> list[CatalogItem]:
        return [catalog_item(SPORT, "competition", COMPETITION_ID, "Formula 1 World Championship", info="FIA")]

    def list_participants(self, competition_id: str) -> list[CatalogItem]:
        standings = self.client.get_json("/current/driverStandings.json")["MRData"]["StandingsTable"]
        lists = standings.get("StandingsLists") or []
        if lists:
            drivers = [parse_driver_standing(row) for row in lists[0]["DriverStandings"]]
        else:  # before the first race of a season there are no standings yet
            raw = self.client.get_json("/current/drivers.json", {"limit": PAGE_SIZE})["MRData"]["DriverTable"]
            drivers = [
                catalog_item(SPORT, "driver", d["driverId"], driver_name(d), parent_id=COMPETITION_ID, short_name=d.get("code"))
                for d in raw["Drivers"]
            ]
        teams = self.client.get_json("/current/constructors.json", {"limit": PAGE_SIZE})["MRData"]["ConstructorTable"]
        return drivers + [parse_constructor(c) for c in teams["Constructors"]]

    def fetch_events(self, competition_id: str) -> list[Event]:
        races = self.client.get_json("/current.json", {"limit": PAGE_SIZE})["MRData"]["RaceTable"]["Races"]
        results = self._all_results()
        return [parse_race(race, results.get(race["round"])) for race in races]

    def _all_results(self) -> dict[str, list[dict[str, Any]]]:
        """Race results for the season, keyed by round. The endpoint pages by result row."""
        by_round: dict[str, list[dict[str, Any]]] = defaultdict(list)
        offset = 0
        while True:
            data = self.client.get_json("/current/results.json", {"limit": PAGE_SIZE, "offset": offset})["MRData"]
            for race in data["RaceTable"]["Races"]:
                by_round[race["round"]].extend(race.get("Results", []))
            offset += PAGE_SIZE
            if offset >= int(data["total"]):
                return by_round
