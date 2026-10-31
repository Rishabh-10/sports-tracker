"""Database tables (SQLite or Postgres). All datetimes are timezone-aware UTC."""

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel, UniqueConstraint


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    # Google's permanent account ID (the OIDC "sub" claim); email and name can change, this can't.
    google_sub: str = Field(unique=True, index=True)
    email: str | None = None
    name: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


# --- per-user data: every row belongs to exactly one user --------------------


class UserProfile(SQLModel, table=True):
    """A user's preferences."""

    user_id: int = Field(primary_key=True, foreign_key="user.id")
    timezone: str = "UTC"
    days_ahead: int = 7
    onboarded: bool = False
    updated_at: datetime = Field(default_factory=utcnow)


class Follow(SQLModel, table=True):
    """Something a user follows: a competition, team, driver or constructor."""

    __table_args__ = (UniqueConstraint("user_id", "sport", "kind", "external_id"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="user.id")
    sport: str = Field(index=True)
    kind: str
    external_id: str
    name: str


class UserApiKeys(SQLModel, table=True):
    """A user's own API keys, encrypted (see keys.py). Empty means "use the app's shared key, if any"."""

    user_id: int = Field(primary_key=True, foreign_key="user.id")
    football_data: str = ""
    gemini: str = ""
    updated_at: datetime = Field(default_factory=utcnow)


class Conversation(SQLModel, table=True):
    """A chat on the Ask page."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="user.id")
    title: str
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ChatMessage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int = Field(index=True, foreign_key="conversation.id")
    role: str  # "user" or "assistant"
    text: str
    ok: bool = True  # False for failed or fallback answers, which aren't sent back to the LLM
    sources_json: str = "[]"
    fixtures: str = ""
    created_at: datetime = Field(default_factory=utcnow)


# --- shared data: public sports data, cached once for all users ---------------


class CatalogItem(SQLModel, table=True):
    """Options offered in the setup wizard, cached from the providers.

    The same team can appear under several competitions (e.g. league + Champions
    League), so the key includes the parent competition.
    """

    key: str = Field(primary_key=True)  # sport:kind:parent_id:external_id
    sport: str = Field(index=True)
    kind: str = Field(index=True)
    external_id: str
    name: str
    short_name: str | None = None
    parent_id: str | None = Field(default=None, index=True)
    logo_url: str | None = None
    info: str | None = None
    updated_at: datetime = Field(default_factory=utcnow)


class Event(SQLModel, table=True):
    """A match or race, upcoming or finished."""

    key: str = Field(primary_key=True)  # sport:external_id
    sport: str = Field(index=True)
    competition_id: str = Field(index=True)
    competition_name: str
    title: str
    start_utc: datetime = Field(index=True)
    status: str  # scheduled | live | finished | postponed | cancelled
    round: str | None = None
    venue: str | None = None
    home_id: str | None = Field(default=None, index=True)
    home_name: str | None = None
    home_logo: str | None = None
    away_id: str | None = Field(default=None, index=True)
    away_name: str | None = None
    away_logo: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    details_json: str = "{}"  # sport-specific extras (F1 sessions, results, ...)
    updated_at: datetime = Field(default_factory=utcnow)


class Article(SQLModel, table=True):
    """A news article from an RSS feed, with full text when the site allows it."""

    id: str = Field(primary_key=True)  # hash of the URL
    url: str
    title: str
    source: str
    sport: str = Field(index=True)
    published_utc: datetime = Field(index=True)
    summary: str = ""
    body: str = ""
    # Entity keys ("sport:kind:id") mentioned in the article, stored as "|key|key|" so
    # they can be matched with LIKE.
    entities: str = "|"
    fetched_at: datetime = Field(default_factory=utcnow)


class Chunk(SQLModel, table=True):
    """A passage of an article with its embedding; the unit retrieved for RAG."""

    id: str = Field(primary_key=True)  # article_id:n
    article_id: str = Field(index=True)
    sport: str = Field(index=True)
    published_utc: datetime = Field(index=True)
    entities: str = "|"
    text: str
    embedding: bytes  # float32 vector, L2-normalised


class FetchLog(SQLModel, table=True):
    """When each cached dataset was last fetched, for staleness checks."""

    key: str = Field(primary_key=True)
    fetched_at: datetime = Field(default_factory=utcnow)
