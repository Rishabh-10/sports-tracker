"""Keeping fixtures fresh and picking the ones relevant to the user."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sports_info import config, keys
from sports_info.providers import get_provider
from sports_info.providers.http import ProviderError
from sports_info.services.catalog import teams_by_competition
from sports_info.store import repo
from sports_info.store.db import get_session
from sports_info.store.models import Event, Follow, utcnow


@dataclass
class RefreshReport:
    refreshed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def followed_competitions(follows: Iterable[Follow]) -> dict[str, set[str]]:
    competitions: dict[str, set[str]] = defaultdict(set)
    for follow in follows:
        if follow.kind == "competition":
            competitions[follow.sport].add(follow.external_id)
    return competitions


def refresh_events(user_id: int, *, force: bool = False) -> RefreshReport:
    """Fetch the season's fixtures for each competition the user follows whose cache is stale.

    The fixtures cache itself is shared: another user following the same competition reuses it.
    """
    report = RefreshReport()
    with get_session() as session:
        follows = repo.get_follows(session, user_id)
        user_keys = keys.for_user(session, user_id)
        for sport, competition_ids in followed_competitions(follows).items():
            provider = get_provider(sport, user_keys)
            if not provider.is_configured():
                report.errors.append(f"{provider.label}: {provider.setup_hint}.")
                continue
            for competition_id in sorted(competition_ids):
                key = f"events:{sport}:{competition_id}"
                if not force and not repo.is_stale(session, key, config.EVENTS_TTL):
                    continue
                try:
                    repo.upsert_events(session, provider.fetch_events(competition_id))
                except ProviderError as exc:
                    report.errors.append(f"{provider.label} ({competition_id}): {exc}")
                    continue
                repo.mark_fetched(session, key)
                report.refreshed.append(key)
    return report


def select_relevant(
    events: Iterable[Event], follows: Iterable[Follow], teams_by_comp: dict[tuple[str, str], set[str]]
) -> list[Event]:
    """Events in followed competitions, narrowed to followed teams where the user picked any.

    If none of the user's teams play in a competition, every event in it is shown; that's
    how "follow the whole Champions League" works. Sports without teams (F1) show every event.
    """
    follows = list(follows)
    competitions = {(f.sport, f.external_id) for f in follows if f.kind == "competition"}
    teams = {(f.sport, f.external_id) for f in follows if f.kind == "team"}
    selected = []
    for event in events:
        if (event.sport, event.competition_id) not in competitions:
            continue
        in_competition = teams_by_comp.get((event.sport, event.competition_id), set())
        mine = {team_id for sport, team_id in teams if sport == event.sport} & in_competition
        if not mine or event.home_id in mine or event.away_id in mine:
            selected.append(event)
    return selected


def _relevant_between(
    user_id: int, start: datetime, end: datetime, sports: Iterable[str] | None = None
) -> list[Event]:
    with get_session() as session:
        follows = repo.get_follows(session, user_id)
        followed_sports = {f.sport for f in follows}
        if sports is not None:
            followed_sports &= set(sports)
        events = repo.get_events(session, sports=followed_sports, start=start, end=end)
    teams_by_comp = {
        (sport, competition_id): team_ids
        for sport in followed_sports
        for competition_id, team_ids in teams_by_competition(sport).items()
    }
    return select_relevant(events, follows, teams_by_comp)


def upcoming(
    user_id: int, days: int, *, sports: Iterable[str] | None = None, now: datetime | None = None
) -> list[Event]:
    """Live and scheduled events from now until `days` ahead (live matches started up to 4h ago)."""
    now = now or utcnow()
    events = _relevant_between(user_id, now - timedelta(hours=4), now + timedelta(days=days), sports)
    return [
        e for e in events
        if e.status in ("live", "postponed") or (e.status == "scheduled" and e.start_utc >= now - timedelta(hours=3))
    ]


def recent_results(
    user_id: int,
    lookback: timedelta = config.RESULTS_LOOKBACK,
    *,
    sports: Iterable[str] | None = None,
    now: datetime | None = None,
) -> list[Event]:
    """Finished events, most recent first."""
    now = now or utcnow()
    events = _relevant_between(user_id, now - lookback, now, sports)
    return sorted((e for e in events if e.status == "finished"), key=lambda e: e.start_utc, reverse=True)
