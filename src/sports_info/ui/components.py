"""Shared UI pieces: styling, event cards, data refresh."""

import html
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import groupby

import streamlit as st

from sports_info.news.entities import entity_key, parse_tags
from sports_info.news.ingest import NewsReport, refresh_news
from sports_info.providers import get_providers
from sports_info.services.events import RefreshReport, refresh_events
from sports_info.store import repo
from sports_info.store.db import get_session
from sports_info.store.models import Article, Event, Follow, utcnow
from sports_info.timefmt import day_label, relative, short_datetime, short_time, to_local
from sports_info.ui.session import require_user_id

CSS = """
<style>
.si-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin:4px 0 20px}
.si-card{border:1px solid rgba(128,128,128,.28);border-radius:12px;padding:12px 14px;background:rgba(128,128,128,.05)}
.si-card.si-live{border-color:#ff4b4b}
.si-meta{font-size:.78rem;opacity:.7;display:flex;justify-content:space-between;gap:8px}
.si-match{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:8px;margin:10px 0 4px}
.si-team{display:flex;align-items:center;gap:8px;min-width:0}
.si-team span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.si-away{justify-content:flex-end;text-align:right}
.si-team img{width:28px;height:28px;object-fit:contain;flex:none}
.si-center{text-align:center;font-weight:700;font-size:1.15rem;line-height:1.2}
.si-center small{display:block;font-weight:400;font-size:.72rem;opacity:.7}
.si-mine{font-weight:700;color:#ff4b4b}
.si-title{font-weight:700;font-size:1.05rem;margin-top:6px}
.si-sub,.si-foot{font-size:.8rem;opacity:.75}
.si-foot{margin-top:6px}
.si-sessions{margin-top:8px;font-size:.85rem;line-height:1.6}
.si-sessions b{font-weight:600}
.si-badge{font-size:.7rem;font-weight:700;padding:1px 6px;border-radius:6px;border:1px solid currentColor}
.si-badge.si-live{color:#ff4b4b}
a.si-headline{display:block;margin-top:6px;font-weight:600;color:inherit;text-decoration:none;line-height:1.35}
a.si-headline:hover{text-decoration:underline}
.si-chips{margin-top:8px;display:flex;flex-wrap:wrap;gap:4px}
.si-chip{font-size:.7rem;padding:1px 8px;border-radius:999px;background:rgba(255,75,75,.12);color:#ff4b4b}
</style>
"""

MEDALS = ["🥇", "🥈", "🥉"]

# F1 sessions stay listed for a couple of hours after they start (roughly their duration).
SESSION_GRACE = timedelta(hours=2)


@dataclass
class Highlights:
    """Ids of the things the user follows, used to emphasise them in cards."""

    teams: set[str] = field(default_factory=set)
    drivers: set[str] = field(default_factory=set)
    constructors: set[str] = field(default_factory=set)

    @classmethod
    def from_follows(cls, follows: Iterable[Follow]) -> "Highlights":
        highlights = cls()
        for follow in follows:
            target = {"team": highlights.teams, "driver": highlights.drivers, "constructor": highlights.constructors}
            if follow.kind in target:
                target[follow.kind].add(follow.external_id)
        return highlights


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def ensure_fresh() -> RefreshReport:
    """Refresh stale data (or everything, if the Refresh button was pressed) and show problems."""
    force = st.session_state.pop("force_refresh", False)
    with st.spinner("Fetching the latest fixtures..."):
        report = refresh_events(require_user_id(), force=force)
    for error in report.errors:
        st.warning(error, icon=":material/warning:")
    return report


def ensure_news_fresh() -> NewsReport:
    force = st.session_state.pop("force_news", False)
    with get_session() as session:
        first_time = repo.latest_fetch(session, "news:") is None
    message = "Fetching news for the first time (about a minute)..." if first_time else "Checking for new articles..."
    with st.spinner(message):
        report = refresh_news(require_user_id(), force=force)
    if report.errors and report.feeds_read == 0:
        st.warning("Couldn't reach the news feeds: " + "; ".join(report.errors[:3]), icon=":material/warning:")
    return report


def data_status_sidebar() -> None:
    with get_session() as session:
        last = repo.latest_fetch(session, "events:")
        last_news = repo.latest_fetch(session, "news:")
    with st.sidebar:
        st.caption(f"Fixtures updated {relative(last, utcnow())}" if last else "No fixtures fetched yet")
        if last_news:
            st.caption(f"News updated {relative(last_news, utcnow())}")
        if st.button("Refresh data", icon=":material/refresh:", width="stretch"):
            st.session_state["force_refresh"] = True
            st.session_state["force_news"] = True
            st.rerun()


def _esc(value: object) -> str:
    return html.escape(str(value)) if value is not None else ""


def _team_html(name: str | None, logo: str | None, mine: bool, away: bool) -> str:
    img = f'<img src="{_esc(logo)}" alt="">' if logo else ""
    label = f'<span class="{"si-mine" if mine else ""}">{_esc(name or "TBD")}</span>'
    return f'<div class="si-team{" si-away" if away else ""}">{label + img if away else img + label}</div>'


def _status_badge(event: Event) -> str:
    if event.status == "live":
        return '<span class="si-badge si-live">LIVE</span>'
    if event.status in ("postponed", "cancelled"):
        return f'<span class="si-badge">{event.status.title()}</span>'
    return ""


def _match_card(event: Event, tz: str, now: datetime, hl: Highlights) -> str:
    icon = get_providers()[event.sport].icon
    meta = " · ".join(_esc(p) for p in (event.competition_name, event.round) if p)
    if event.home_score is not None and event.status in ("live", "finished"):
        center = f"{event.home_score} – {event.away_score}"
        sub = "FT" if event.status == "finished" else "live"
    else:
        center = short_time(event.start_utc, tz)
        sub = relative(event.start_utc, now)
    foot = f'<div class="si-foot">📍 {_esc(event.venue)}</div>' if event.venue else ""
    return (
        f'<div class="si-card{" si-live" if event.status == "live" else ""}">'
        f'<div class="si-meta"><span>{icon} {meta}</span>{_status_badge(event)}</div>'
        '<div class="si-match">'
        f"{_team_html(event.home_name, event.home_logo, event.home_id in hl.teams, away=False)}"
        f'<div class="si-center">{_esc(center)}<small>{_esc(sub)}</small></div>'
        f"{_team_html(event.away_name, event.away_logo, event.away_id in hl.teams, away=True)}"
        f"</div>{foot}</div>"
    )


def _race_card(event: Event, tz: str, now: datetime, hl: Highlights) -> str:
    icon = get_providers()[event.sport].icon
    details = json.loads(event.details_json or "{}")
    sub = " · ".join(_esc(p) for p in (event.venue, details.get("country")) if p)
    results = details.get("results") or []
    if results:
        podium = " &nbsp; ".join(f"{MEDALS[i]} {_esc(r['code'])}" for i, r in enumerate(results[:3]))
        mine = [
            f"{_esc(r['driver'])} <b>P{_esc(r['position_text'])}</b>"
            for r in results
            if r["driver_id"] in hl.drivers or r["constructor_id"] in hl.constructors
        ]
        body = f'<div class="si-sessions">{podium}</div>'
        if mine:
            body += f'<div class="si-foot"><span class="si-mine">Yours:</span> {" · ".join(mine)}</div>'
    else:
        sessions = [
            s for s in details.get("sessions", [])
            if datetime.fromisoformat(s["start"]) >= now - SESSION_GRACE
        ]
        lines = []
        for s in sessions[-3:]:
            start = datetime.fromisoformat(s["start"])
            lines.append(
                f"<b>{_esc(s['name'])}</b> · {_esc(short_datetime(start, tz))} "
                f"<small>({_esc(relative(start, now))})</small>"
            )
        body = f'<div class="si-sessions">{"<br>".join(lines)}</div>'
    return (
        f'<div class="si-card{" si-live" if event.status == "live" else ""}">'
        f'<div class="si-meta"><span>{icon} {_esc(event.competition_name)} · {_esc(event.round)}</span>'
        f"{_status_badge(event)}</div>"
        f'<div class="si-title">{_esc(event.title)}</div><div class="si-sub">{sub}</div>{body}</div>'
    )


def event_card(event: Event, tz: str, now: datetime, hl: Highlights) -> str:
    return _race_card(event, tz, now, hl) if event.sport == "f1" else _match_card(event, tz, now, hl)


def render_events_by_day(events: list[Event], tz: str, hl: Highlights, *, now: datetime | None = None) -> None:
    """Cards grouped under a heading per local calendar day, in the order given."""
    now = now or utcnow()
    today = to_local(now, tz).date()
    for day, day_events in groupby(events, key=lambda e: to_local(e.start_utc, tz).date()):
        st.markdown(f"##### {day_label(day, today)}")
        cards = "".join(event_card(e, tz, now, hl) for e in day_events)
        st.markdown(f'<div class="si-grid">{cards}</div>', unsafe_allow_html=True)


def _news_card(article: Article, now: datetime, names: dict[str, str]) -> str:
    icon = get_providers()[article.sport].icon if article.sport in get_providers() else ""
    summary = article.summary or (article.body[:240] if article.body else "")
    if len(summary) > 240:
        summary = summary[:240].rsplit(" ", 1)[0] + "…"
    chips = "".join(f'<span class="si-chip">{_esc(names[k])}</span>' for k in sorted(parse_tags(article.entities)) if k in names)
    return (
        '<div class="si-card">'
        f'<div class="si-meta"><span>{icon} {_esc(article.source)} · {_esc(relative(article.published_utc, now))}</span></div>'
        f'<a class="si-headline" href="{_esc(article.url)}" target="_blank" rel="noopener">{_esc(article.title)}</a>'
        + (f'<div class="si-sub" style="margin-top:4px">{_esc(summary)}</div>' if summary else "")
        + (f'<div class="si-chips">{chips}</div>' if chips else "")
        + "</div>"
    )


def render_news(articles: list[Article], follows: Iterable[Follow], *, now: datetime | None = None) -> None:
    """News cards, with chips for the followed teams/drivers each article mentions."""
    now = now or utcnow()
    names = {entity_key(f.sport, f.kind, f.external_id): f.name for f in follows if f.kind != "competition"}
    cards = "".join(_news_card(a, now, names) for a in articles)
    st.markdown(f'<div class="si-grid">{cards}</div>', unsafe_allow_html=True)


def follow_summary(follows: Iterable[Follow]) -> str:
    follows = list(follows)
    picks = [f.name for f in follows if f.kind != "competition"] or [f.name for f in follows]
    if len(picks) > 6:
        return ", ".join(picks[:6]) + f" and {len(picks) - 6} more"
    return ", ".join(picks)
