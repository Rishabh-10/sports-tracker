"""Interface every sport adapter implements."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from sports_info.store.models import CatalogItem, Event


class SportProvider(ABC):
    sport: str
    label: str
    icon: str
    blurb: str
    # Kinds of thing the user can follow, with the label used in the wizard.
    follow_kinds: dict[str, str]
    # True when the sport has exactly one competition (F1), so the wizard skips picking one.
    single_competition: bool = False
    setup_hint: str = ""

    def is_configured(self) -> bool:
        return True

    @abstractmethod
    def list_competitions(self) -> list[CatalogItem]: ...

    @abstractmethod
    def list_participants(self, competition_id: str) -> list[CatalogItem]:
        """Teams/drivers/constructors in a competition, each with parent_id=competition_id."""

    @abstractmethod
    def fetch_events(self, competition_id: str) -> list[Event]:
        """All matches/races of the competition's current season, upcoming and finished."""


def catalog_item(
    sport: str,
    kind: str,
    external_id: str,
    name: str,
    *,
    parent_id: str | None = None,
    short_name: str | None = None,
    logo_url: str | None = None,
    info: str | None = None,
) -> CatalogItem:
    return CatalogItem(
        key=f"{sport}:{kind}:{parent_id or ''}:{external_id}",
        sport=sport,
        kind=kind,
        external_id=external_id,
        name=name,
        parent_id=parent_id,
        short_name=short_name,
        logo_url=logo_url,
        info=info,
    )


def parse_utc(value: str) -> datetime:
    """Parse an ISO timestamp like '2026-10-25T14:00:00Z' into aware UTC (naive input is taken as UTC)."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
