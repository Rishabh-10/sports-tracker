from sports_info.news.entities import Entity, EntityIndex, aliases_for, parse_tags, tags


def entity(sport, kind, eid, name, short=None):
    return Entity(f"{sport}:{kind}:{eid}", sport, kind, eid, name, aliases_for(kind, name, short))


INDEX = EntityIndex([
    entity("football", "team", "57", "Arsenal FC", "Arsenal"),
    entity("football", "team", "66", "Manchester United FC", "Man United"),
    entity("football", "team", "78", "Club Atlético de Madrid", "Atleti"),
    entity("f1", "driver", "perez", "Sergio Pérez", "PER"),
    entity("f1", "driver", "leclerc", "Charles Leclerc", "LEC"),
    entity("f1", "constructor", "cadillac", "Cadillac F1 Team"),
])


def test_team_aliases_drop_club_words_and_add_nicknames():
    assert "Atlético Madrid" in aliases_for("team", "Club Atlético de Madrid")
    assert {"Man Utd", "Man United"} <= set(aliases_for("team", "Manchester United FC"))


def test_driver_and_constructor_aliases():
    assert "Leclerc" in aliases_for("driver", "Charles Leclerc")
    assert "Cadillac" in aliases_for("constructor", "Cadillac F1 Team")


def test_find_is_accent_insensitive_and_word_bounded():
    assert INDEX.find("Perez and Leclerc collide") == {"f1:driver:perez", "f1:driver:leclerc"}
    assert INDEX.find("Arsenalista fans") == set()
    assert INDEX.find("Man Utd beat Arsenal") == {"football:team:66", "football:team:57"}


def test_find_filters_by_sport():
    assert INDEX.find("Arsenal and Cadillac", sport="f1") == {"f1:constructor:cadillac"}


def test_search_terms():
    assert INDEX.get("football:team:57").search_term == '"Arsenal" football'
    assert INDEX.get("f1:driver:leclerc").search_term == '"Charles Leclerc"'


def test_tag_round_trip():
    assert tags(["b", "a", "a"]) == "|a|b|"
    assert parse_tags("|a|b|") == {"a", "b"}
    assert tags([]) == "|"
