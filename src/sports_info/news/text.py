"""Cleaning feed text and splitting articles into passages for retrieval."""

import html
import re

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"[ \t\r\f\v]+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# Passages of about this many characters (~200 tokens) fit the embedding model comfortably.
CHUNK_CHARS = 900
MAX_CHUNKS = 8
# Lines shorter than this are usually page furniture ("Published", "Image caption").
MIN_LINE_CHARS = 25


def clean_html(value: str) -> str:
    text = html.unescape(_TAG.sub(" ", value or ""))
    return "\n".join(_SPACE.sub(" ", line).strip() for line in text.splitlines() if line.strip())


def strip_source_suffix(title: str, source: str) -> str:
    """Google News titles end with ' - Source'; drop it."""
    suffix = f" - {source}"
    return title[: -len(suffix)] if source and title.endswith(suffix) else title


def _split_long(paragraph: str, limit: int) -> list[str]:
    pieces, current = [], ""
    for sentence in _SENTENCE_END.split(paragraph):
        if current and len(current) + len(sentence) + 1 > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def chunk_article(title: str, text: str, *, limit: int = CHUNK_CHARS, max_chunks: int = MAX_CHUNKS) -> list[str]:
    """Group paragraphs into passages of up to `limit` chars, each prefixed with the title.

    The title gives every passage enough context to make sense when retrieved on its own.
    """
    paragraphs = []
    for line in (text or "").splitlines():
        line = line.strip()
        if len(line) >= MIN_LINE_CHARS and line != title:
            paragraphs.extend(_split_long(line, limit) if len(line) > limit else [line])

    chunks, current = [], ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 1 > limit:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n{paragraph}".strip()
    if current:
        chunks.append(current)
    if not chunks:
        return [title]
    return [f"{title}\n{chunk}" for chunk in chunks[:max_chunks]]
