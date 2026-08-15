"""Tests for language negotiation helpers."""

import pytest

from app.core.constants import DEFAULT_LANGUAGE, Language
from app.shared.utils.language import (
    is_supported,
    language_display_name,
    localized_field_name,
    negotiate_language,
    normalize_language,
    parse_accept_language,
    pick_translation,
    resolve_language,
    supported_languages,
)


def test_english_is_the_default() -> None:
    assert DEFAULT_LANGUAGE is Language.EN


def test_supported_languages_lists_the_default_first() -> None:
    assert supported_languages() == [Language.EN, Language.BN]


# -- Normalization ------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("en", Language.EN),
        ("bn", Language.BN),
        ("EN", Language.EN),
        ("  bn  ", Language.BN),
        ("bn-BD", Language.BN),
        ("bn_BD", Language.BN),
        ("en-US", Language.EN),
        ("EN-GB", Language.EN),
    ],
)
def test_normalize_language(value: str, expected: Language) -> None:
    assert normalize_language(value) is expected


@pytest.mark.parametrize("value", ["fr", "de-DE", "", "   ", None, "xx", "123"])
def test_normalize_language_rejects_unsupported(value: str | None) -> None:
    assert normalize_language(value) is None


def test_is_supported() -> None:
    assert is_supported("bn-BD") is True
    assert is_supported("fr") is False


# -- Accept-Language parsing --------------------------------------------


def test_parse_accept_language_orders_by_quality() -> None:
    parsed = parse_accept_language("en;q=0.5,bn;q=0.9,fr;q=0.1")

    assert parsed == [("bn", 0.9), ("en", 0.5), ("fr", 0.1)]


def test_parse_accept_language_defaults_missing_quality_to_one() -> None:
    assert parse_accept_language("bn-BD,bn;q=0.9,en;q=0.8") == [
        ("bn-bd", 1.0),
        ("bn", 0.9),
        ("en", 0.8),
    ]


def test_parse_accept_language_preserves_order_within_equal_quality() -> None:
    assert parse_accept_language("bn,en") == [("bn", 1.0), ("en", 1.0)]


def test_parse_accept_language_drops_explicitly_refused_languages() -> None:
    """`q=0` is the client saying it does not accept that language."""
    assert parse_accept_language("en;q=0,bn;q=1") == [("bn", 1.0)]


@pytest.mark.parametrize("header", [None, "", "   ", ",,,"])
def test_parse_accept_language_handles_empty_headers(header: str | None) -> None:
    assert parse_accept_language(header) == []


def test_parse_accept_language_survives_a_malformed_header() -> None:
    """A broken header from a proxy must not fail the request."""
    assert parse_accept_language("bn;q=abc,;q=0.5,en") == [("bn", 1.0), ("en", 1.0)]


def test_parse_accept_language_clamps_out_of_range_quality() -> None:
    assert parse_accept_language("bn;q=5.0") == [("bn", 1.0)]


# -- Negotiation --------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("bn", Language.BN),
        ("bn-BD,bn;q=0.9,en;q=0.8", Language.BN),
        ("en-US,en;q=0.9", Language.EN),
        ("fr-FR,fr;q=0.9,bn;q=0.8", Language.BN),
        ("fr,de", Language.EN),
        ("*", Language.EN),
        ("fr;q=0.9,*;q=0.5", Language.EN),
        (None, Language.EN),
        ("", Language.EN),
    ],
)
def test_negotiate_language(header: str | None, expected: Language) -> None:
    assert negotiate_language(header) is expected


def test_negotiate_language_skips_unsupported_higher_priority_tags() -> None:
    assert negotiate_language("de;q=1.0,bn;q=0.2") is Language.BN


# -- Resolution ---------------------------------------------------------


def test_query_parameter_beats_the_header() -> None:
    """A reader clicking a language switcher overrides their browser."""
    assert resolve_language(requested="bn", accept_language="en-US,en") is Language.BN


def test_header_is_used_without_a_query_parameter() -> None:
    assert resolve_language(accept_language="bn-BD,bn;q=0.9") is Language.BN


def test_unsupported_query_parameter_falls_back_to_the_header() -> None:
    assert resolve_language(requested="fr", accept_language="bn") is Language.BN


def test_everything_unsupported_falls_back_to_the_default() -> None:
    assert resolve_language(requested="fr", accept_language="de") is Language.EN


def test_resolution_never_raises_on_junk_input() -> None:
    assert resolve_language(requested="???", accept_language="!!!;q=") is Language.EN


# -- Helpers ------------------------------------------------------------


def test_language_display_names_are_endonyms() -> None:
    assert language_display_name(Language.EN) == "English"
    assert language_display_name(Language.BN) == "বাংলা"


def test_localized_field_name() -> None:
    assert localized_field_name("title", Language.BN) == "title_bn"
    assert localized_field_name("summary", Language.EN) == "summary_en"


def test_pick_translation_prefers_the_requested_language() -> None:
    translations = {"en": "Hello", "bn": "হ্যালো"}

    assert pick_translation(translations, Language.BN) == "হ্যালো"
    assert pick_translation(translations, Language.EN) == "Hello"


def test_pick_translation_falls_back_to_the_default_language() -> None:
    """A partly translated record still renders rather than showing a blank."""
    assert pick_translation({"en": "Hello"}, Language.BN) == "Hello"


def test_pick_translation_falls_back_to_any_available_value() -> None:
    assert pick_translation({"bn": "হ্যালো"}, Language.BN, fallback=None) == "হ্যালো"


def test_pick_translation_handles_missing_data() -> None:
    assert pick_translation(None, Language.EN) is None
    assert pick_translation({}, Language.EN) is None
