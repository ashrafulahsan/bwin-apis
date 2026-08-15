"""Tests for slug generation."""

from itertools import islice

import pytest

from app.shared.utils.slug import generate_unique_slug, slug_candidates, slugify


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Hello World", "hello-world"),
        ("  Leading and trailing  ", "leading-and-trailing"),
        ("Multiple   spaces", "multiple-spaces"),
        ("Punctuation!!! Here???", "punctuation-here"),
        ("UPPERCASE TITLE", "uppercase-title"),
        ("already-a-slug", "already-a-slug"),
        ("Under_scores_too", "under-scores-too"),
        ("Course 101: Intro", "course-101-intro"),
        ("--dashes--everywhere--", "dashes-everywhere"),
    ],
)
def test_slugify_basic_text(value: str, expected: str) -> None:
    assert slugify(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Café", "cafe"),
        ("São Paulo", "sao-paulo"),
        ("Über Alles", "uber-alles"),
        ("Grüße", "grusse"),
        ("Ærø", "aero"),
        ("Łódź", "lodz"),
        ("Ñandú", "nandu"),
    ],
)
def test_slugify_transliterates_accents(value: str, expected: str) -> None:
    assert slugify(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Bread & Butter", "bread-and-butter"),
        ("me@example", "me-at-example"),
    ],
)
def test_slugify_spells_out_symbols(value: str, expected: str) -> None:
    assert slugify(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("CEO's Guide", "ceos-guide"),
        ("Don’t Panic", "dont-panic"),
        ("Students' Union", "students-union"),
    ],
)
def test_slugify_drops_apostrophes_instead_of_splitting_words(
    value: str, expected: str
) -> None:
    assert slugify(value) == expected


def test_slugify_returns_empty_when_nothing_survives() -> None:
    assert slugify("日本語") == ""
    assert slugify("!!!") == ""


def test_slugify_respects_a_custom_separator() -> None:
    assert slugify("Hello World", separator="_") == "hello_world"


def test_slugify_truncates_at_a_word_boundary() -> None:
    slug = slugify("the quick brown fox jumps over the lazy dog", max_length=20)

    assert len(slug) <= 20
    assert slug == "the-quick-brown-fox"
    assert not slug.endswith("-")


def test_slugify_truncates_mid_word_rather_than_losing_most_of_the_slug() -> None:
    """A boundary that would discard over half the slug is not worth honouring."""
    slug = slugify("supercalifragilistic expialidocious", max_length=12)

    assert len(slug) <= 12
    assert slug == "supercalifra"


def test_slug_candidates_appends_increments() -> None:
    candidates = list(islice(slug_candidates("my-post"), 4))

    assert candidates == ["my-post", "my-post-2", "my-post-3", "my-post-4"]


def test_slug_candidates_keep_the_suffix_within_max_length() -> None:
    candidates = list(islice(slug_candidates("abcdefghij", max_length=10), 3))

    assert candidates == ["abcdefghij", "abcdefgh-2", "abcdefgh-3"]
    assert all(len(candidate) <= 10 for candidate in candidates)


async def test_generate_unique_slug_returns_the_base_when_free() -> None:
    async def never_exists(_: str) -> bool:
        return False

    assert await generate_unique_slug("My First Post", never_exists) == "my-first-post"


async def test_generate_unique_slug_skips_taken_slugs() -> None:
    taken = {"my-first-post", "my-first-post-2"}

    async def exists(slug: str) -> bool:
        return slug in taken

    assert await generate_unique_slug("My First Post", exists) == "my-first-post-3"


async def test_generate_unique_slug_falls_back_for_untranslatable_titles() -> None:
    async def never_exists(_: str) -> bool:
        return False

    slug = await generate_unique_slug("日本語", never_exists)

    assert slug
    assert slug.isalnum()


async def test_generate_unique_slug_gives_up_with_a_random_suffix() -> None:
    """Rather than looping forever against a table where everything collides."""

    async def always_exists(_: str) -> bool:
        return True

    slug = await generate_unique_slug("popular", always_exists, max_attempts=5)

    assert slug.startswith("popular-")
    assert slug != "popular-2"
