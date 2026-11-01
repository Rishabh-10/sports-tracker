"""Read/write helpers over the database tables."""

from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlmodel import Session, col, select

from sports_info.store.models import (
    CatalogItem,
    ChatMessage,
    Conversation,
    Event,
    FetchLog,
    Follow,
    User,
    UserProfile,
    utcnow,
)

# --- users -------------------------------------------------------------------


def get_user(session: Session, user_id: int) -> User | None:
    return session.get(User, user_id)


def get_user_by_google_sub(session: Session, google_sub: str) -> User | None:
    return session.exec(select(User).where(User.google_sub == google_sub)).first()


def create_user(session: Session, google_sub: str, email: str | None = None, name: str | None = None) -> User:
    user = User(google_sub=google_sub, email=email, name=name)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def count_users(session: Session) -> int:
    return len(session.exec(select(User.id)).all())


# --- profile (per user) --------------------------------------------------------


def get_profile(session: Session, user_id: int) -> UserProfile:
    profile = session.get(UserProfile, user_id)
    if profile is None:
        profile = UserProfile(user_id=user_id)
        session.add(profile)
        session.commit()
        session.refresh(profile)
    return profile


def save_profile(
    session: Session, user_id: int, *, timezone: str, days_ahead: int, onboarded: bool = True
) -> UserProfile:
    profile = get_profile(session, user_id)
    profile.timezone = timezone
    profile.days_ahead = days_ahead
    profile.onboarded = onboarded
    profile.updated_at = utcnow()
    session.add(profile)
    session.commit()
    return profile


def reset_user(session: Session, user_id: int) -> None:
    """Forget a user's profile and follows (their account, chats and shared data are kept)."""
    for follow in session.exec(select(Follow).where(Follow.user_id == user_id)).all():
        session.delete(follow)
    profile = session.get(UserProfile, user_id)
    if profile is not None:
        session.delete(profile)
    session.commit()


# --- follows (per user) --------------------------------------------------------


def get_follows(session: Session, user_id: int, sport: str | None = None) -> list[Follow]:
    query = select(Follow).where(Follow.user_id == user_id)
    if sport is not None:
        query = query.where(Follow.sport == sport)
    return list(session.exec(query.order_by(Follow.sport, Follow.kind, Follow.name)).all())


def replace_follows(session: Session, user_id: int, follows: Iterable[Follow]) -> None:
    for follow in session.exec(select(Follow).where(Follow.user_id == user_id)).all():
        session.delete(follow)
    session.flush()
    for follow in follows:
        follow.user_id = user_id
        session.add(follow)
    session.commit()


# --- conversations (per user) --------------------------------------------------


def create_conversation(session: Session, user_id: int, title: str) -> Conversation:
    conversation = Conversation(user_id=user_id, title=title[:80])
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def get_conversation(session: Session, user_id: int, conversation_id: int) -> Conversation | None:
    """The conversation, only if it belongs to `user_id`."""
    conversation = session.get(Conversation, conversation_id)
    return conversation if conversation is not None and conversation.user_id == user_id else None


def list_conversations(session: Session, user_id: int, limit: int = 20) -> list[Conversation]:
    query = select(Conversation).where(Conversation.user_id == user_id)
    return list(session.exec(query.order_by(col(Conversation.updated_at).desc()).limit(limit)).all())


def get_messages(session: Session, user_id: int, conversation_id: int) -> list[ChatMessage]:
    if get_conversation(session, user_id, conversation_id) is None:
        return []
    query = select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
    return list(session.exec(query.order_by(ChatMessage.id)).all())


def add_message(session: Session, user_id: int, conversation_id: int, message: ChatMessage) -> ChatMessage:
    conversation = get_conversation(session, user_id, conversation_id)
    if conversation is None:
        raise PermissionError("conversation does not belong to this user")
    message.conversation_id = conversation_id
    conversation.updated_at = utcnow()
    session.add(message)
    session.add(conversation)
    session.commit()
    session.refresh(message)
    return message


def delete_conversation(session: Session, user_id: int, conversation_id: int) -> None:
    conversation = get_conversation(session, user_id, conversation_id)
    if conversation is None:
        return
    for message in session.exec(select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)).all():
        session.delete(message)
    session.delete(conversation)
    session.commit()


# --- catalog -----------------------------------------------------------------


def replace_catalog(
    session: Session, sport: str, kind: str, parent_id: str | None, items: Iterable[CatalogItem]
) -> None:
    """Replace the cached options for one (sport, kind, parent) slice."""
    query = select(CatalogItem).where(CatalogItem.sport == sport, CatalogItem.kind == kind)
    query = query.where(CatalogItem.parent_id == parent_id if parent_id else col(CatalogItem.parent_id).is_(None))
    for item in session.exec(query).all():
        session.delete(item)
    session.flush()
    for item in items:
        session.merge(item)
    session.commit()


def get_catalog(
    session: Session, sport: str, kind: str, parent_ids: Iterable[str] | None = None
) -> list[CatalogItem]:
    query = select(CatalogItem).where(CatalogItem.sport == sport, CatalogItem.kind == kind)
    if parent_ids is not None:
        query = query.where(col(CatalogItem.parent_id).in_(list(parent_ids)))
    return list(session.exec(query.order_by(CatalogItem.name)).all())


# --- events ------------------------------------------------------------------


def upsert_events(session: Session, events: Iterable[Event]) -> None:
    for event in events:
        session.merge(event)
    session.commit()


def get_events(
    session: Session,
    *,
    sports: Iterable[str] | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Event]:
    query = select(Event)
    if sports is not None:
        query = query.where(col(Event.sport).in_(list(sports)))
    if start is not None:
        query = query.where(Event.start_utc >= start)
    if end is not None:
        query = query.where(Event.start_utc < end)
    return list(session.exec(query.order_by(Event.start_utc)).all())


# --- fetch log ---------------------------------------------------------------


def last_fetched(session: Session, key: str) -> datetime | None:
    entry = session.get(FetchLog, key)
    return entry.fetched_at if entry else None


def is_stale(session: Session, key: str, ttl: timedelta, now: datetime | None = None) -> bool:
    fetched = last_fetched(session, key)
    return fetched is None or (now or utcnow()) - fetched > ttl


def mark_fetched(session: Session, key: str) -> None:
    session.merge(FetchLog(key=key, fetched_at=utcnow()))
    session.commit()


def latest_fetch(session: Session, prefix: str) -> datetime | None:
    query = select(FetchLog).where(col(FetchLog.key).startswith(prefix))
    times = [entry.fetched_at for entry in session.exec(query).all()]
    return max(times) if times else None
