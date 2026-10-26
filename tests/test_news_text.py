from sports_info.news.text import chunk_article, clean_html, strip_source_suffix


def test_clean_html_strips_tags_and_entities():
    assert clean_html("<p>Leclerc &amp; Hamilton</p>\n<p>  on   pole </p>") == "Leclerc & Hamilton\non pole"


def test_strip_source_suffix():
    assert strip_source_suffix("Leclerc fumes - Sky Sports", "Sky Sports") == "Leclerc fumes"
    assert strip_source_suffix("Leclerc fumes", "Sky Sports") == "Leclerc fumes"


def test_chunks_carry_title_and_respect_limit():
    paragraphs = "\n".join(f"Paragraph number {i} has some words about the race weekend." for i in range(30))
    chunks = chunk_article("Title", paragraphs, limit=200)
    assert all(c.startswith("Title\n") for c in chunks)
    assert all(len(c) <= 200 + len("Title\n") for c in chunks)
    assert len(chunks) == 8  # capped


def test_short_furniture_lines_are_dropped():
    chunks = chunk_article("Title", "Published\nImage caption\nThe actual story about the Grand Prix is here.")
    assert chunks == ["Title\nThe actual story about the Grand Prix is here."]


def test_headline_only_article_is_one_chunk():
    assert chunk_article("Just a headline", "") == ["Just a headline"]
