"""Registry of sport adapters. Adding a sport = writing one SportProvider and listing it here."""

from functools import cache

from sports_info.keys import ApiKeys
from sports_info.providers.base import SportProvider
from sports_info.providers.football_data import FootballDataProvider
from sports_info.providers.jolpica_f1 import JolpicaF1Provider


@cache
def _football(api_key: str) -> FootballDataProvider:
    # One instance (and rate limiter) per key, since football-data.org limits per key.
    return FootballDataProvider(api_key)


@cache
def _f1() -> JolpicaF1Provider:
    return JolpicaF1Provider()


def get_providers(keys: ApiKeys | None = None) -> dict[str, SportProvider]:
    """Providers using the given user's keys. Without keys they're fine for labels and keyless calls."""
    keys = keys or ApiKeys()
    providers: list[SportProvider] = [_football(keys.football_data), _f1()]
    return {p.sport: p for p in providers}


def get_provider(sport: str, keys: ApiKeys | None = None) -> SportProvider:
    return get_providers(keys)[sport]
