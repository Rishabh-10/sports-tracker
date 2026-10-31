from datetime import datetime, timedelta, timezone

from sqlmodel import func, select

from sports_info.news.entities import Entity, EntityIndex, aliases_for
from sports_info.news.feeds import Feed
from sports_info.news.ingest import FeedItem, article_id, ingest_items, parse_feed
from sports_info.store import news_repo
from sports_info.store.db import get_session
from sports_info.store.models import Article, Chunk, utcnow

BBC = Feed("https://bbc.test/f1.xml", "BBC Sport", "f1")
GOOGLE = Feed("https://news.google.test/q", "Google News", "f1", full_text=False, entity_key="f1:driver:leclerc")
INDEX = EntityIndex([
    Entity("f1:driver:leclerc", "f1", "driver", "leclerc", "Charles Leclerc", aliases_for("driver", "Charles Leclerc")),
    Entity("f1:constructor:ferrari", "f1", "constructor", "ferrari", "Ferrari", aliases_for("constructor", "Ferrari")),
])

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Leclerc takes pole - Sky Sports</title><link>https://sky.test/a</link>
<pubDate>Sat, 24 Oct 2026 21:30:00 GMT</pubDate><description>&lt;a href="x"&gt;link&lt;/a&gt;</description>
<source url="https://sky.test">Sky Sports</source></item>
<item><title>No link item</title></item>
</channel></rss>"""


def item(url, title, summary="", age=timedelta(hours=1)):
    return FeedItem(url, title, "BBC Sport", utcnow() - age, summary)


def count(session, model):
    return session.exec(select(func.count()).select_from(model)).one()


def test_parse_google_news_feed():
    items = parse_feed(GOOGLE, RSS)
    assert len(items) == 1
    assert items[0].title == "Leclerc takes pole"
    assert items[0].source == "Sky Sports"
    assert items[0].summary == ""  # Google News descriptions are just links
    assert items[0].published_utc == datetime(2026, 10, 24, 21, 30, tzinfo=timezone.utc)


def test_ingest_tags_chunks_and_dedupes(temp_db, fake_embedder):
    bodies = {"https://bbc.test/1": "Charles Leclerc said Ferrari had paid the price for its strategy in Austin."}
    items = [item("https://bbc.test/1", "Austin reaction"), item("https://bbc.test/2", "Alpine news", "Gasly is happy.")]
    with get_session() as session:
        assert ingest_items(session, BBC, items, index=INDEX, embedder=fake_embedder, fetch_bodies=lambda u: bodies) == 2
        assert ingest_items(session, BBC, items, index=INDEX, embedder=fake_embedder, fetch_bodies=lambda u: bodies) == 0
        stored = session.get(Article, article_id("https://bbc.test/1"))
        assert stored.entities == "|f1:constructor:ferrari|f1:driver:leclerc|"
        assert stored.body.startswith("Charles Leclerc")
        assert count(session, Chunk) == 2
        assert news_repo.keyword_search(session, ["strategy"], 5) == [f"{stored.id}:0"]


def test_entity_feed_tags_existing_article(temp_db, fake_embedder):
    plain = item("https://bbc.test/3", "Ferrari upgrade explained")
    with get_session() as session:
        ingest_items(session, BBC, [plain], index=INDEX, embedder=fake_embedder)
        ingest_items(session, GOOGLE, [plain], index=INDEX, embedder=fake_embedder)
        stored = session.get(Article, article_id(plain.url))
        assert "f1:driver:leclerc" in stored.entities
        chunk = session.exec(select(Chunk).where(Chunk.article_id == stored.id)).one()
        assert chunk.entities == stored.entities


def test_old_items_skipped_and_pruned(temp_db, fake_embedder):
    with get_session() as session:
        assert ingest_items(session, BBC, [item("https://bbc.test/old", "Old", age=timedelta(days=40))],
                            index=INDEX, embedder=fake_embedder) == 0
        ingest_items(session, BBC, [item("https://bbc.test/4", "Fresh story", age=timedelta(days=5))],
                     index=INDEX, embedder=fake_embedder)
        assert news_repo.prune(session, utcnow() - timedelta(days=1)) == 1
        assert count(session, Article) == 0 and count(session, Chunk) == 0
        assert news_repo.keyword_search(session, ["fresh"], 5) == []
