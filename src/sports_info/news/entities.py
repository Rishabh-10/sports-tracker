"""Recognising teams, drivers and constructors in articles and questions."""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from sqlmodel import Session

from sports_info.store import repo
from sports_info.store.models import CatalogItem, Follow

FOLLOWABLE_KINDS = ("team", "driver", "constructor")

# Words dropped from official club names to get the name people actually use.
CLUB_WORDS = {
    "fc", "afc", "cf", "sc", "ac", "as", "ssc", "fk", "sk", "bk", "sv", "vfb", "vfl", "tsg",
    "cd", "ud", "rcd", "sl", "ca", "club", "de", "1.", "calcio", "futbol",
}
# Aliases too generic to match on their own.
GENERIC = {"city", "united", "real", "club", "sporting", "athletic", "racing", "town", "rovers",
           "albion", "wanderers", "red", "team", "f1", "inter milano"}

# Nicknames the data providers don't use, keyed by a fragment of the normalised official name.
NICKNAMES = {
    "manchester united": ("Man Utd", "Man United"),
    "manchester city": ("Man City",),
    "tottenham hotspur": ("Spurs", "Tottenham"),
    "wolverhampton": ("Wolves",),
    "brighton": ("Brighton",),
    "west ham": ("West Ham",),
    "newcastle united": ("Newcastle",),
    "barcelona": ("Barca", "Barça"),
    "paris saint-germain": ("PSG", "Paris St-Germain"),
    "bayern munchen": ("Bayern Munich", "Bayern"),
    "atletico de madrid": ("Atletico Madrid",),
    "internazionale": ("Inter Milan", "Inter"),
    "red bull": ("Red Bull Racing",),
    "rb f1 team": ("Racing Bulls", "VCARB"),
}
SEARCH_HINTS = {"team": "football", "constructor": "F1", "driver": ""}


def normalize(text: str) -> str:
    """Lowercase and strip accents so 'Pérez' matches 'Perez'."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


@dataclass(frozen=True)
class Entity:
    key: str  # sport:kind:external_id
    sport: str
    kind: str
    external_id: str
    name: str
    aliases: tuple[str, ...]

    @property
    def search_term(self) -> str:
        """Query for news searches, e.g. '"Arsenal" football' or '"Charles Leclerc"'."""
        term = self.name if self.kind == "driver" else min(self.aliases, key=len)
        hint = SEARCH_HINTS.get(self.kind, "")
        return f'"{term}" {hint}'.strip()


def entity_key(sport: str, kind: str, external_id: str) -> str:
    return f"{sport}:{kind}:{external_id}"


def aliases_for(kind: str, name: str, short_name: str | None = None) -> tuple[str, ...]:
    candidates = {name}
    if short_name:
        candidates.add(short_name)
    if kind == "team":
        words = [w for w in name.split() if normalize(w) not in CLUB_WORDS]
        if words:
            candidates.add(" ".join(words))
    elif kind == "driver":
        candidates.add(name.split()[-1])
    elif kind == "constructor":
        candidates.add(re.sub(r"\s+F1 Team$", "", name))
    normalized_name = normalize(name)
    for fragment, nicknames in NICKNAMES.items():
        if fragment in normalized_name:
            candidates.update(nicknames)
    return tuple(sorted(a for a in candidates if len(a) >= 3 and normalize(a) not in GENERIC))


class EntityIndex:
    """Finds mentions of known entities in text using one combined regex."""

    def __init__(self, entities: Iterable[Entity]):
        self.entities = {e.key: e for e in entities}
        self._keys_by_alias: dict[str, set[str]] = defaultdict(set)
        for entity in self.entities.values():
            for alias in entity.aliases:
                self._keys_by_alias[normalize(alias)].add(entity.key)
        aliases = sorted(self._keys_by_alias, key=len, reverse=True)
        self._pattern = (
            re.compile(r"(?<!\w)(" + "|".join(re.escape(a) for a in aliases) + r")(?!\w)") if aliases else None
        )

    def find(self, text: str, sport: str | None = None) -> set[str]:
        if self._pattern is None:
            return set()
        keys = set()
        for match in self._pattern.finditer(normalize(text)):
            keys |= self._keys_by_alias[match.group(1)]
        if sport is not None:
            keys = {k for k in keys if self.entities[k].sport == sport}
        return keys

    def get(self, key: str) -> Entity | None:
        return self.entities.get(key)


def _from_catalog(item: CatalogItem) -> Entity:
    return Entity(
        key=entity_key(item.sport, item.kind, item.external_id),
        sport=item.sport,
        kind=item.kind,
        external_id=item.external_id,
        name=item.name,
        aliases=aliases_for(item.kind, item.name, item.short_name),
    )


def build_index(session: Session, sports: Iterable[str], follows: Iterable[Follow] = ()) -> EntityIndex:
    """All known teams/drivers/constructors in the given sports, plus anything followed."""
    entities: dict[str, Entity] = {}
    for sport in sports:
        for kind in FOLLOWABLE_KINDS:
            for item in repo.get_catalog(session, sport, kind):
                entities.setdefault(entity_key(sport, kind, item.external_id), _from_catalog(item))
    for follow in follows:
        key = entity_key(follow.sport, follow.kind, follow.external_id)
        if follow.kind in FOLLOWABLE_KINDS and key not in entities:
            entities[key] = Entity(key, follow.sport, follow.kind, follow.external_id, follow.name,
                                   aliases_for(follow.kind, follow.name))
    return EntityIndex(entities.values())


def tags(keys: Iterable[str]) -> str:
    """Entity keys in the '|a|b|' storage format."""
    keys = sorted(set(keys))
    return "|" + "".join(f"{k}|" for k in keys) if keys else "|"


def parse_tags(value: str) -> set[str]:
    return {k for k in (value or "").split("|") if k}
