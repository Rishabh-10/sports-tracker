"""Fixtures and results from the database, formatted as authoritative context for the LLM."""

import json
import re
from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlmodel import Session

from sports_info import config
from sports_info.news.entities import EntityIndex, normalize
from sports_info.services.events import recent_results, upcoming
from sports_info.store import repo
from sports_info.store.models import Event
from sports_info.timefmt import short_datetime

SPORT_WORDS = {
    "f1": r"f1|formula (1|one)|grand prix|gp|race|races|racing|qualifying|pole|podium|drivers?|constructors?|sprint|pit",
    "football": r"football|soccer|match(es)?|goals?|league|fixtures?|kick ?off|manager|transfers?|cup|derby|penalt(y|ies)|clean sheet",
}
UPCOMING_DAYS = 14
MAX_LINES = 12


def detect_sports(text: str, entity_sports: Iterable[str], followed: set[str]) -> set[str]:
    """Sports a question is about: from mentioned entities, else keywords, else everything followed."""
    sports = set(entity_sports) & followed
    if not sports:
        normalized = normalize(text)
        sports = {s for s, words in SPORT_WORDS.items() if s in followed and re.search(rf"\b({words})\b", normalized)}
    return sports or followed


def _f1_line(event: Event, tz: str, highlight: set[str]) -> str:
    details = json.loads(event.details_json or "{}")
    if event.status == "finished":
        results = details.get("results") or []
        top = ", ".join(f"{r['position_text']}. {r['driver']} ({r['constructor']})" for r in results[:10])
        mine = [f"{r['driver']} P{r['position_text']} ({r['status']})" for r in results[10:]
                if f"f1:driver:{r['driver_id']}" in highlight or f"f1:constructor:{r['constructor_id']}" in highlight]
        extra = f". Also: {', '.join(mine)}" if mine else ""
        return f"- {short_datetime(event.start_utc, tz)} · {event.title} ({event.round}) result: {top}{extra}"
    sessions = "; ".join(
        f"{s['name']} {short_datetime(datetime.fromisoformat(s['start']), tz)}"
        for s in details.get("sessions", []) if s["name"] in ("Sprint Qualifying", "Sprint", "Qualifying", "Race")
    )
    return f"- {event.title} ({event.round}, {event.venue}): {sessions}"


def _match_line(event: Event, tz: str) -> str:
    when = short_datetime(event.start_utc, tz)
    competition = " · ".join(p for p in (event.competition_name, event.round) if p)
    if event.status == "finished":
        return f"- {when} · {competition}: {event.home_name} {event.home_score}–{event.away_score} {event.away_name}"
    status = {"live": " (LIVE now)", "postponed": " (postponed)"}.get(event.status, "")
    return f"- {when} · {competition}: {event.home_name} vs {event.away_name}{status}"


def event_line(event: Event, tz: str, highlight: set[str] = frozenset()) -> str:
    return _f1_line(event, tz, highlight) if event.sport == "f1" else _match_line(event, tz)


def fixtures_context(
    session: Session,
    user_id: int,
    *,
    sports: set[str],
    focus: set[str],
    index: EntityIndex,
    tz: str,
    now: datetime,
) -> str:
    """Upcoming events and recent results for the question's sports, narrowed to focus teams if any."""
    coming = upcoming(user_id, UPCOMING_DAYS, sports=sports, now=now)
    past = recent_results(user_id, config.RESULTS_LOOKBACK, sports=sports, now=now)

    focus_teams = {index.get(k).external_id for k in focus if index.get(k) and index.get(k).kind == "team"}
    if focus_teams:
        # Include teams the user asked about even if they don't follow them.
        window = repo.get_events(session, sports=["football"], start=now - config.RESULTS_LOOKBACK,
                                 end=now + timedelta(days=UPCOMING_DAYS))
        extra = [e for e in window if {e.home_id, e.away_id} & focus_teams]
        known = {e.key for e in coming + past}
        coming += [e for e in extra if e.key not in known and e.status in ("scheduled", "live", "postponed")
                   and e.start_utc >= now - timedelta(hours=3)]
        past += [e for e in extra if e.key not in known and e.status == "finished"]

        def relevant(e: Event) -> bool:
            return e.sport != "football" or bool({e.home_id, e.away_id} & focus_teams)

        coming = [e for e in coming if relevant(e)]
        past = [e for e in past if relevant(e)]

    coming.sort(key=lambda e: e.start_utc)
    past.sort(key=lambda e: e.start_utc, reverse=True)
    lines = ["Upcoming:"] + ([event_line(e, tz, focus) for e in coming[:MAX_LINES]] or ["- nothing scheduled in the next two weeks"])
    lines += ["Recent results:"] + ([event_line(e, tz, focus) for e in past[:MAX_LINES]] or ["- none in the last three weeks"])
    return "\n".join(lines)
