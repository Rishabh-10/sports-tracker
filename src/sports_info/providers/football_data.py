"""Football via football-data.org (v4). Free tier: 12 competitions, 10 requests/minute."""

import json
from typing import Any

from sports_info.providers.base import SportProvider, catalog_item, parse_utc
from sports_info.providers.http import ProviderError, ProviderNotConfigured, RateLimitedClient
from sports_info.store.models import CatalogItem, Event

BASE_URL = "https://api.football-data.org/v4"
FREE_PLAN = "TIER_ONE"
SPORT = "football"

# Used if the competitions endpoint can't be reached (code, name, area).
FALLBACK_COMPETITIONS = [
    ("PL", "Premier League", "England"),
    ("ELC", "Championship", "England"),
    ("PD", "Primera Division", "Spain"),
    ("SA", "Serie A", "Italy"),
    ("BL1", "Bundesliga", "Germany"),
    ("FL1", "Ligue 1", "France"),
    ("DED", "Eredivisie", "Netherlands"),
    ("PPL", "Primeira Liga", "Portugal"),
    ("BSA", "Campeonato Brasileiro Série A", "Brazil"),
    ("CL", "UEFA Champions League", "Europe"),
    ("EC", "European Championship", "Europe"),
    ("WC", "FIFA World Cup", "World"),
]

STATUS_MAP = {
    "SCHEDULED": "scheduled",
    "TIMED": "scheduled",
    "IN_PLAY": "live",
    "PAUSED": "live",
    "LIVE": "live",
    "FINISHED": "finished",
    "AWARDED": "finished",
    "POSTPONED": "postponed",
    "SUSPENDED": "postponed",
    "CANCELLED": "cancelled",
}


def parse_competition(data: dict[str, Any]) -> CatalogItem:
    return catalog_item(
        SPORT,
        "competition",
        data["code"],
        data["name"],
        logo_url=data.get("emblem"),
        info=(data.get("area") or {}).get("name"),
    )


def parse_team(data: dict[str, Any], competition_code: str) -> CatalogItem:
    return catalog_item(
        SPORT,
        "team",
        str(data["id"]),
        data["name"],
        parent_id=competition_code,
        short_name=data.get("shortName") or data.get("tla"),
        logo_url=data.get("crest"),
        info=(data.get("area") or {}).get("name"),
    )


def _round_label(stage: str | None, matchday: int | None) -> str | None:
    if stage in (None, "REGULAR_SEASON"):
        return f"Matchday {matchday}" if matchday else None
    label = stage.replace("_", " ").title()
    return f"{label} · Matchday {matchday}" if matchday and stage == "LEAGUE_STAGE" else label


def parse_match(data: dict[str, Any], competition: dict[str, Any]) -> Event:
    home = data.get("homeTeam") or {}
    away = data.get("awayTeam") or {}
    full_time = (data.get("score") or {}).get("fullTime") or {}
    competition = data.get("competition") or competition
    home_name = home.get("shortName") or home.get("name") or "TBD"
    away_name = away.get("shortName") or away.get("name") or "TBD"
    return Event(
        key=f"{SPORT}:{data['id']}",
        sport=SPORT,
        competition_id=competition["code"],
        competition_name=competition["name"],
        title=f"{home_name} vs {away_name}",
        start_utc=parse_utc(data["utcDate"]),
        status=STATUS_MAP.get(data.get("status", ""), "scheduled"),
        round=_round_label(data.get("stage"), data.get("matchday")),
        venue=data.get("venue"),
        home_id=str(home["id"]) if home.get("id") else None,
        home_name=home_name,
        home_logo=home.get("crest"),
        away_id=str(away["id"]) if away.get("id") else None,
        away_name=away_name,
        away_logo=away.get("crest"),
        home_score=full_time.get("home"),
        away_score=full_time.get("away"),
        details_json=json.dumps({"winner": (data.get("score") or {}).get("winner")}),
    )


class FootballDataProvider(SportProvider):
    sport = SPORT
    label = "Football"
    icon = "⚽"
    blurb = "Premier League, La Liga, Serie A, Bundesliga, Champions League and more"
    follow_kinds = {"team": "Teams"}
    setup_hint = "add your free football-data.org key under API keys in the sidebar"

    def __init__(self, api_key: str, client: RateLimitedClient | None = None):
        self.api_key = api_key
        headers = {"X-Auth-Token": api_key} if api_key else {}
        self.client = client or RateLimitedClient(BASE_URL, max_calls=10, period=60, headers=headers)

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _require_key(self) -> None:
        if not self.api_key:
            raise ProviderNotConfigured(f"Football needs an API key: {self.setup_hint}")

    def list_competitions(self) -> list[CatalogItem]:
        try:
            data = self.client.get_json("/competitions")
            items = [parse_competition(c) for c in data["competitions"] if c.get("plan") == FREE_PLAN]
        except (ProviderError, KeyError):
            items = []
        if not items:
            items = [catalog_item(SPORT, "competition", code, name, info=area) for code, name, area in FALLBACK_COMPETITIONS]
        return items

    def list_participants(self, competition_id: str) -> list[CatalogItem]:
        self._require_key()
        data = self.client.get_json(f"/competitions/{competition_id}/teams")
        return [parse_team(t, competition_id) for t in data.get("teams", [])]

    def fetch_events(self, competition_id: str) -> list[Event]:
        self._require_key()
        data = self.client.get_json(f"/competitions/{competition_id}/matches")
        competition = data.get("competition") or {"code": competition_id, "name": competition_id}
        return [parse_match(m, competition) for m in data.get("matches", [])]
