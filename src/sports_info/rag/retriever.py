"""Hybrid news search: embedding similarity + BM25 keywords, merged with reciprocal rank fusion."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from sqlmodel import Session

from sports_info.news.embeddings import Embedder, from_blobs
from sports_info.news.entities import normalize, parse_tags
from sports_info.store import news_repo
from sports_info.store.models import Article

CANDIDATES = 40  # how many hits each method contributes before fusion
RRF_K = 60
ENTITY_BOOST = 0.012  # roughly "moves up ~20 places" against RRF scores near 1/60
MAX_CHUNKS_PER_ARTICLE = 2

STOPWORDS = set(
    "a an and are as at be but by did do does for from had has have how i in is it its me my of on or "
    "so than that the their them then there these they this to up was we were what when where which "
    "who why will with would you your about any after again all also been before can could just more "
    "most new news latest tell think going happen happened".split()
)


@dataclass
class Hit:
    chunk_id: str
    text: str
    score: float
    article: Article


def keyword_terms(text: str) -> list[str]:
    """The question's meaningful words (lowercase, accents removed, no repeats), for keyword search."""
    words = [w for w in re.findall(r"\w+", normalize(text)) if len(w) > 1 and w not in STOPWORDS]
    return list(dict.fromkeys(words))


def search(
    session: Session,
    query: str,
    *,
    embedder: Embedder,
    sports: Iterable[str],
    since: datetime,
    boost_entities: Iterable[str] = (),
    k: int = 8,
) -> list[Hit]:
    chunks = news_repo.candidate_chunks(session, sports=sports, since=since)
    if not chunks:
        return []
    by_id = {c.id: c for c in chunks}

    similarities = from_blobs([c.embedding for c in chunks]) @ embedder.embed_query(query)
    vector_ranked = [chunks[i].id for i in np.argsort(-similarities)[:CANDIDATES]]
    keyword_ranked = [cid for cid in news_repo.keyword_search(session, keyword_terms(query), CANDIDATES * 3)
                      if cid in by_id][:CANDIDATES]

    scores: dict[str, float] = {}
    for ranked in (vector_ranked, keyword_ranked):
        for rank, chunk_id in enumerate(ranked):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    boost = set(boost_entities)
    if boost:
        for chunk_id in scores:
            if parse_tags(by_id[chunk_id].entities) & boost:
                scores[chunk_id] += ENTITY_BOOST

    ordered = sorted(scores, key=scores.get, reverse=True)
    articles = news_repo.articles_by_id(session, {by_id[c].article_id for c in ordered})
    # The same story often arrives twice (the site's own feed and Google News): use the richest copy.
    best = news_repo.best_copies(articles.values())
    hits, per_story = [], {}
    for chunk_id in ordered:
        chunk = by_id[chunk_id]
        article = articles[chunk.article_id]
        story = normalize(article.title)
        if best[story].id != article.id or per_story.get(story, 0) >= MAX_CHUNKS_PER_ARTICLE:
            continue
        per_story[story] = per_story.get(story, 0) + 1
        hits.append(Hit(chunk_id, chunk.text, scores[chunk_id], article))
        if len(hits) == k:
            break
    return hits
