"""Fetching RSS feeds, extracting article text, tagging, chunking and embedding."""

import calendar
import hashlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

import feedparser
import httpx
import trafilatura
from sqlmodel import Session

from sports_info import config
from sports_info.news.embeddings import Embedder, get_embedder, to_blob
from sports_info.news.entities import EntityIndex, build_index, tags
from sports_info.news.feeds import Feed, feeds_for
from sports_info.news.text import chunk_article, clean_html, strip_source_suffix
from sports_info.store import news_repo, repo
from sports_info.store.db import get_session
from sports_info.store.models import Article, Chunk, utcnow

USER_AGENT = "Mozilla/5.0 (compatible; sports-info personal news reader)"
# Full-text downloads per refresh, so a first run doesn't hit sites with hundreds of requests.
MAX_FULL_TEXT_PER_RUN = 60
MAX_BODY_CHARS = 8000
MAX_ITEMS_PER_FEED = 40


@dataclass
class FeedItem:
    url: str
    title: str
    source: str
    published_utc: datetime
    summary: str


@dataclass
class NewsReport:
    new_articles: int = 0
    feeds_read: int = 0
    errors: list[str] = field(default_factory=list)


def article_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:20]


def parse_feed(feed: Feed, content: bytes) -> list[FeedItem]:
    parsed = feedparser.parse(content)
    items = []
    for entry in parsed.entries[:MAX_ITEMS_PER_FEED]:
        url = entry.get("link")
        title = clean_html(entry.get("title", ""))
        if not url or not title:
            continue
        source = (entry.get("source") or {}).get("title") or feed.source
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        published = datetime.fromtimestamp(calendar.timegm(stamp), timezone.utc) if stamp else utcnow()
        # Google News summaries are just a link back to the headline; skip them.
        summary = "" if feed.entity_key else clean_html(entry.get("summary", ""))
        items.append(FeedItem(url, strip_source_suffix(title, source), source, published, summary))
    return items


class FullTextFetcher:
    """Downloads article pages and extracts their main text, within a per-run budget."""

    def __init__(self, client: httpx.Client, budget: int = MAX_FULL_TEXT_PER_RUN):
        self.client = client
        self.remaining = budget

    def _extract(self, url: str) -> str:
        try:
            response = self.client.get(url)
            response.raise_for_status()
        except httpx.HTTPError:
            return ""
        body = trafilatura.extract(response.text, include_comments=False, include_tables=False, favor_precision=True)
        return (body or "")[:MAX_BODY_CHARS]

    def fetch_many(self, urls: list[str]) -> dict[str, str]:
        urls = urls[: max(self.remaining, 0)]
        self.remaining -= len(urls)
        with ThreadPoolExecutor(max_workers=4) as pool:
            return dict(zip(urls, pool.map(self._extract, urls)))


def ingest_items(
    session: Session,
    feed: Feed,
    items: list[FeedItem],
    *,
    index: EntityIndex,
    embedder: Embedder,
    fetch_bodies: Callable[[list[str]], dict[str, str]] | None = None,
) -> int:
    """Store new articles from one feed. Returns how many were new."""
    oldest = utcnow() - config.NEWS_RETENTION
    by_id = {article_id(i.url): i for i in items if i.published_utc >= oldest}
    existing = news_repo.existing_article_ids(session, by_id)
    if feed.entity_key:
        for aid in existing:
            news_repo.add_entity_tag(session, aid, feed.entity_key)
    new = {aid: item for aid, item in by_id.items() if aid not in existing}
    if not new:
        session.commit()
        return 0

    bodies = fetch_bodies([i.url for i in new.values()]) if feed.full_text and fetch_bodies else {}
    articles, chunk_texts = [], []
    for aid, item in new.items():
        body = bodies.get(item.url, "")
        mentioned = index.find(f"{item.title}\n{body or item.summary}", sport=feed.sport)
        if feed.entity_key:
            mentioned.add(feed.entity_key)
        article = Article(
            id=aid, url=item.url, title=item.title, source=item.source, sport=feed.sport,
            published_utc=item.published_utc, summary=item.summary[:600], body=body, entities=tags(mentioned),
        )
        articles.append(article)
        chunk_texts.append(chunk_article(item.title, body or item.summary))

    vectors = embedder.embed_passages([t for texts in chunk_texts for t in texts])
    position = 0
    for article, texts in zip(articles, chunk_texts):
        chunks = []
        for n, chunk_text in enumerate(texts):
            chunks.append(Chunk(
                id=f"{article.id}:{n}", article_id=article.id, sport=article.sport,
                published_utc=article.published_utc, entities=article.entities,
                text=chunk_text, embedding=to_blob(vectors[position]),
            ))
            position += 1
        news_repo.add_article(session, article, chunks)
    session.commit()
    return len(articles)


def _download(client: httpx.Client, feed: Feed) -> bytes:
    response = client.get(feed.url)
    response.raise_for_status()
    return response.content


def refresh_news(user_id: int, *, force: bool = False, embedder: Embedder | None = None) -> NewsReport:
    """Read every stale feed for this user's sports and follows, then drop expired articles.

    Articles are shared public data: feeds another user also reads are fetched once.
    """
    report = NewsReport()
    with get_session() as session:
        follows = repo.get_follows(session, user_id)
        index = build_index(session, {f.sport for f in follows}, follows)
        feeds = [
            f for f in feeds_for(follows, index)
            if force or repo.is_stale(session, f"news:{f.url}", config.NEWS_TTL)
        ]
        if feeds:
            embedder = embedder or get_embedder()
            with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=15, follow_redirects=True) as client:
                with ThreadPoolExecutor(max_workers=6) as pool:
                    downloads = list(pool.map(lambda f: _safe_download(client, f), feeds))
                fetcher = FullTextFetcher(client)
                for feed, (content, error) in zip(feeds, downloads):
                    if error:
                        report.errors.append(f"{feed.source}: {error}")
                        continue
                    report.new_articles += ingest_items(
                        session, feed, parse_feed(feed, content),
                        index=index, embedder=embedder, fetch_bodies=fetcher.fetch_many,
                    )
                    report.feeds_read += 1
                    repo.mark_fetched(session, f"news:{feed.url}")
        news_repo.prune(session, utcnow() - config.NEWS_RETENTION)
    return report


def _safe_download(client: httpx.Client, feed: Feed) -> tuple[bytes, str | None]:
    try:
        return _download(client, feed), None
    except httpx.HTTPError as exc:
        return b"", f"couldn't read feed ({exc.__class__.__name__})"
