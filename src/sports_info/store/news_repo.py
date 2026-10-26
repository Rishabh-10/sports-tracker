"""Read/write helpers for articles, chunks and the keyword index."""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import delete, or_, text
from sqlmodel import Session, col, select

from sports_info.news.entities import normalize, parse_tags, tags
from sports_info.store.models import Article, Chunk


def existing_article_ids(session: Session, ids: Iterable[str]) -> set[str]:
    ids = list(ids)
    if not ids:
        return set()
    return set(session.exec(select(Article.id).where(col(Article.id).in_(ids))).all())


def add_article(session: Session, article: Article, chunks: list[Chunk]) -> None:
    session.add(article)
    session.add_all(chunks)
    if chunks:
        session.connection().execute(
            text("INSERT INTO chunk_fts (chunk_id, text) VALUES (:chunk_id, :text)"),
            [{"chunk_id": c.id, "text": c.text} for c in chunks],
        )


def add_entity_tag(session: Session, article_id: str, key: str) -> None:
    """Tag an already-stored article (and its chunks) with one more entity."""
    article = session.get(Article, article_id)
    if article is None or key in parse_tags(article.entities):
        return
    article.entities = tags(parse_tags(article.entities) | {key})
    session.add(article)
    for chunk in session.exec(select(Chunk).where(Chunk.article_id == article_id)).all():
        chunk.entities = article.entities
        session.add(chunk)


def prune(session: Session, before: datetime) -> int:
    """Delete articles published before `before`, with their chunks. Returns how many."""
    old_ids = list(session.exec(select(Article.id).where(Article.published_utc < before)).all())
    if not old_ids:
        return 0
    chunk_ids = list(session.exec(select(Chunk.id).where(col(Chunk.article_id).in_(old_ids))).all())
    for start in range(0, len(chunk_ids), 500):
        batch = chunk_ids[start : start + 500]
        params = {f"c{i}": cid for i, cid in enumerate(batch)}
        placeholders = ", ".join(f":c{i}" for i in range(len(batch)))
        session.connection().execute(text(f"DELETE FROM chunk_fts WHERE chunk_id IN ({placeholders})"), params)
    session.exec(delete(Chunk).where(col(Chunk.article_id).in_(old_ids)))
    session.exec(delete(Article).where(col(Article.id).in_(old_ids)))
    session.commit()
    return len(old_ids)


def recent_articles(
    session: Session,
    *,
    sports: Iterable[str],
    entity_keys: Iterable[str] | None = None,
    since: datetime | None = None,
    limit: int = 50,
) -> list[Article]:
    query = select(Article).where(col(Article.sport).in_(list(sports)))
    if since is not None:
        query = query.where(Article.published_utc >= since)
    if entity_keys is not None:
        keys = list(entity_keys)
        if not keys:
            return []
        query = query.where(or_(*(col(Article.entities).contains(f"|{k}|") for k in keys)))
    return list(session.exec(query.order_by(col(Article.published_utc).desc()).limit(limit)).all())


def _richness(article: Article) -> int:
    return 2 if article.body else 1 if article.summary else 0


def best_copies(articles: Iterable[Article]) -> dict[str, Article]:
    """Per headline, the copy with the most text (a site's own feed beats a Google News headline)."""
    best: dict[str, Article] = {}
    for article in articles:
        story = normalize(article.title)
        if story not in best or _richness(article) > _richness(best[story]):
            best[story] = article
    return best


def unique_stories(articles: list[Article]) -> list[Article]:
    """Drop repeat copies of the same story, keeping the richest copy in the first copy's position."""
    best = best_copies(articles)
    seen, result = set(), []
    for article in articles:
        story = normalize(article.title)
        if story not in seen:
            seen.add(story)
            result.append(best[story])
    return result


def candidate_chunks(session: Session, *, sports: Iterable[str], since: datetime) -> list[Chunk]:
    query = select(Chunk).where(col(Chunk.sport).in_(list(sports)), Chunk.published_utc >= since)
    return list(session.exec(query).all())


def keyword_search(session: Session, match_query: str, limit: int) -> list[str]:
    """Chunk ids ranked by BM25 for an FTS5 MATCH expression."""
    if not match_query:
        return []
    rows = session.connection().execute(
        text("SELECT chunk_id FROM chunk_fts WHERE chunk_fts MATCH :q ORDER BY rank LIMIT :limit"),
        {"q": match_query, "limit": limit},
    )
    return [row[0] for row in rows]


def articles_by_id(session: Session, ids: Iterable[str]) -> dict[str, Article]:
    ids = list(ids)
    if not ids:
        return {}
    return {a.id: a for a in session.exec(select(Article).where(col(Article.id).in_(ids))).all()}
