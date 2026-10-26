"""Wizard options, served from the SQLite cache and refreshed from providers when stale."""

from collections.abc import Iterable

from sports_info import config
from sports_info.keys import ApiKeys
from sports_info.providers import get_provider
from sports_info.providers.http import ProviderError
from sports_info.store import repo
from sports_info.store.db import get_session
from sports_info.store.models import CatalogItem


def competitions(sport: str, *, keys: ApiKeys | None = None, force: bool = False) -> list[CatalogItem]:
    key = f"catalog:{sport}:competitions"
    with get_session() as session:
        if force or repo.is_stale(session, key, config.CATALOG_TTL):
            items = get_provider(sport, keys).list_competitions()
            repo.replace_catalog(session, sport, "competition", None, items)
            repo.mark_fetched(session, key)
        return repo.get_catalog(session, sport, "competition")


def participants(
    sport: str, competition_ids: Iterable[str], *, keys: ApiKeys | None = None, force: bool = False
) -> dict[str, list[CatalogItem]]:
    """Followable participants per kind, deduplicated across competitions.

    A failed fetch falls back to whatever is cached; it only raises if there's nothing cached.
    """
    provider = get_provider(sport, keys)
    competition_ids = list(competition_ids)
    with get_session() as session:
        for competition_id in competition_ids:
            key = f"catalog:{sport}:participants:{competition_id}"
            if not (force or repo.is_stale(session, key, config.CATALOG_TTL)):
                continue
            try:
                items = provider.list_participants(competition_id)
            except ProviderError:
                if repo.last_fetched(session, key) is None:
                    raise
                continue
            for kind in provider.follow_kinds:
                repo.replace_catalog(session, sport, kind, competition_id, [i for i in items if i.kind == kind])
            repo.mark_fetched(session, key)

        result: dict[str, list[CatalogItem]] = {}
        for kind in provider.follow_kinds:
            unique: dict[str, CatalogItem] = {}
            for item in repo.get_catalog(session, sport, kind, competition_ids):
                unique.setdefault(item.external_id, item)
            result[kind] = sorted(unique.values(), key=lambda i: i.name)
        return result


def teams_by_competition(sport: str) -> dict[str, set[str]]:
    """competition_id -> ids of teams in it, from the cached catalog."""
    with get_session() as session:
        mapping: dict[str, set[str]] = {}
        for item in repo.get_catalog(session, sport, "team"):
            mapping.setdefault(item.parent_id or "", set()).add(item.external_id)
        return mapping
