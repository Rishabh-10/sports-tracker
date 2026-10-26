"""Which RSS feeds to read for the user's sports and follows."""

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlencode

from sports_info.news.entities import EntityIndex, entity_key
from sports_info.store.models import Follow


@dataclass(frozen=True)
class Feed:
    url: str
    source: str
    sport: str
    # Whether to download the linked page for its full text (allowed and useful for these sites).
    full_text: bool = True
    # Set for a news search about one followed team/driver; its articles get that tag.
    entity_key: str | None = None


SPORT_FEEDS = {
    "football": [
        Feed("https://feeds.bbci.co.uk/sport/football/rss.xml", "BBC Sport", "football"),
        Feed("https://www.theguardian.com/football/rss", "The Guardian", "football"),
        Feed("https://www.skysports.com/rss/11095", "Sky Sports", "football"),
        Feed("https://www.espn.com/espn/rss/soccer/news", "ESPN", "football"),
    ],
    "f1": [
        Feed("https://feeds.bbci.co.uk/sport/formula1/rss.xml", "BBC Sport", "f1"),
        Feed("https://www.theguardian.com/sport/formulaone/rss", "The Guardian", "f1"),
        Feed("https://www.skysports.com/rss/12433", "Sky Sports", "f1"),
        Feed("https://www.autosport.com/rss/f1/news/", "Autosport", "f1"),
        Feed("https://www.motorsport.com/rss/f1/news/", "Motorsport.com", "f1"),
    ],
}


def google_news_feed(sport: str, key: str, search_term: str) -> Feed:
    """Google News search for one entity. Links are redirects, so only headlines are kept."""
    query = urlencode({"q": f"{search_term} when:7d", "hl": "en-GB", "gl": "GB", "ceid": "GB:en"})
    return Feed(f"https://news.google.com/rss/search?{query}", "Google News", sport, full_text=False, entity_key=key)


def feeds_for(follows: Iterable[Follow], index: EntityIndex) -> list[Feed]:
    follows = list(follows)
    feeds = [feed for sport in sorted({f.sport for f in follows}) for feed in SPORT_FEEDS.get(sport, [])]
    for follow in follows:
        entity = index.get(entity_key(follow.sport, follow.kind, follow.external_id))
        if entity is not None:
            feeds.append(google_news_feed(entity.sport, entity.key, entity.search_term))
    return feeds
