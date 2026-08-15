"""Tests for the translation loader, repository and service."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Language
from app.core.dependencies import PaginationParams
from app.core.exceptions import ConflictException
from app.modules.translations import loader
from app.modules.translations.constants import namespace_of
from app.modules.translations.models.translation import Translation
from app.modules.translations.schemas.translation import (
    TranslationCreate,
    TranslationImport,
    TranslationUpdate,
)
from app.modules.translations.services.translation import TranslationService


@pytest.fixture
async def translations(session: AsyncSession) -> AsyncIterator[TranslationService]:
    """A service over an empty translations table, cleaned up afterwards."""
    await session.execute(delete(Translation))
    await session.commit()

    yield TranslationService(session)

    await session.execute(delete(Translation))
    await session.commit()


@pytest.fixture
async def seeded(translations: TranslationService) -> TranslationService:
    """The real locale files, imported."""
    await translations.sync_all_locales()
    return translations


# -- Loader -------------------------------------------------------------


def test_flatten_nested_translations() -> None:
    flattened = loader.flatten_translations(
        {"dashboard": {"title": "Dashboard", "widgets": {"chart": "Chart"}}}
    )

    assert flattened == {
        "dashboard.title": "Dashboard",
        "dashboard.widgets.chart": "Chart",
    }


def test_flatten_accepts_already_flat_keys() -> None:
    assert loader.flatten_translations({"login.button": "Log in"}) == {
        "login.button": "Log in"
    }


def test_flatten_coerces_non_string_leaves() -> None:
    """A locale file written with a number should load, not explode."""
    assert loader.flatten_translations({"cart": {"count": 5}}) == {"cart.count": "5"}


def test_flatten_skips_nulls() -> None:
    assert loader.flatten_translations({"a": {"b": None, "c": "x"}}) == {"a.c": "x"}


def test_load_language_reads_the_real_locale_file() -> None:
    english = loader.load_language(Language.EN)

    assert english["dashboard.title"] == "Dashboard"
    assert english["login.button"] == "Log in"
    assert english["course.enroll"] == "Enrol"


def test_bengali_locale_file_is_translated() -> None:
    bengali = loader.load_language(Language.BN)

    assert bengali["dashboard.title"] == "ড্যাশবোর্ড"
    assert bengali["course.enroll"] == "ভর্তি হন"


def test_every_locale_file_loads() -> None:
    bundles = loader.load_all_locales()

    assert set(bundles) == {Language.EN, Language.BN}


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        loader.load_language(Language.EN, directory=tmp_path)


def test_load_rejects_a_json_array(tmp_path: Path) -> None:
    path = tmp_path / "en.json"
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    with pytest.raises(ValueError, match="must contain a JSON object"):
        loader.load_locale_file(path)


def test_load_all_locales_skips_absent_languages(tmp_path: Path) -> None:
    (tmp_path / "en.json").write_text(json.dumps({"a.b": "c"}), encoding="utf-8")

    assert set(loader.load_all_locales(directory=tmp_path)) == {Language.EN}


# -- Key handling -------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("dashboard.title", "dashboard"),
        ("course.enroll", "course"),
        ("a.b.c.d", "a"),
    ],
)
def test_namespace_of(key: str, expected: str) -> None:
    assert namespace_of(key) == expected


@pytest.mark.parametrize(
    "key", ["dashboard.title", "login.button", "course.enroll", "a.b.c"]
)
def test_schema_accepts_valid_keys(key: str) -> None:
    payload = TranslationCreate(key=key, language=Language.EN, value="x")

    assert payload.key == key


@pytest.mark.parametrize(
    "key",
    [
        "nodots",  # no namespace
        "trailing.",
        ".leading",
        "has space.x",
        "dash-ed.key",
        "9leading.digit",
        "",
    ],
)
def test_schema_rejects_malformed_keys(key: str) -> None:
    with pytest.raises(ValueError, match="dot-namespaced|at most"):
        TranslationCreate(key=key, language=Language.EN, value="x")


def test_schema_normalizes_key_casing() -> None:
    assert TranslationCreate(
        key="  DASHBOARD.TITLE  ", language=Language.EN, value="x"
    ).key == ("dashboard.title")


def test_import_schema_validates_every_key() -> None:
    with pytest.raises(ValueError, match="dot-namespaced"):
        TranslationImport(language=Language.BN, translations={"bad key": "x"})


# -- Import and upsert --------------------------------------------------


async def test_import_inserts_translations(translations: TranslationService) -> None:
    imported = await translations.import_translations(
        Language.EN, {"dashboard.title": "Dashboard", "login.button": "Log in"}
    )

    assert imported == 2
    assert await translations.get_bundle(Language.EN) == {
        "dashboard.title": "Dashboard",
        "login.button": "Log in",
    }


async def test_reimport_updates_instead_of_failing(
    translations: TranslationService,
) -> None:
    """Re-running a locale import must not trip the unique constraint."""
    await translations.import_translations(Language.EN, {"login.button": "Log in"})
    await translations.import_translations(Language.EN, {"login.button": "Sign in"})

    bundle = await translations.get_bundle(Language.EN)

    assert bundle == {"login.button": "Sign in"}


async def test_import_derives_the_namespace(
    translations: TranslationService,
) -> None:
    await translations.import_translations(Language.EN, {"course.enroll": "Enrol"})

    assert await translations.list_namespaces() == ["course"]


async def test_import_of_nothing_is_a_no_op(
    translations: TranslationService,
) -> None:
    assert await translations.import_translations(Language.EN, {}) == 0


async def test_sync_all_locales_imports_both_languages(
    translations: TranslationService,
) -> None:
    results = await translations.sync_all_locales()

    assert results[Language.EN] > 0
    assert results[Language.BN] > 0


# -- Bundles ------------------------------------------------------------


async def test_bundle_returns_the_requested_language(
    seeded: TranslationService,
) -> None:
    bundle = await seeded.get_bundle(Language.BN)

    assert bundle["dashboard.title"] == "ড্যাশবোর্ড"
    assert bundle["course.enroll"] == "ভর্তি হন"


async def test_bundle_fills_gaps_from_english(seeded: TranslationService) -> None:
    """`course.certificate` is untranslated, so Bengali falls back to English."""
    bundle = await seeded.get_bundle(Language.BN)

    assert bundle["course.certificate"] == "Certificate"


async def test_bundle_without_fallback_omits_untranslated_keys(
    seeded: TranslationService,
) -> None:
    bundle = await seeded.get_bundle(Language.BN, fallback=False)

    assert "course.certificate" not in bundle
    assert bundle["dashboard.title"] == "ড্যাশবোর্ড"


async def test_bundle_can_be_narrowed_to_a_namespace(
    seeded: TranslationService,
) -> None:
    bundle = await seeded.get_bundle(Language.EN, namespace="login")

    assert bundle["login.button"] == "Log in"
    assert all(key.startswith("login.") for key in bundle)


# -- Single key resolution ----------------------------------------------


async def test_translate_returns_the_value(seeded: TranslationService) -> None:
    assert await seeded.translate("course.enroll", Language.BN) == "ভর্তি হন"


async def test_translate_falls_back_to_english(seeded: TranslationService) -> None:
    assert await seeded.translate("course.certificate", Language.BN) == "Certificate"


async def test_translate_returns_the_key_when_undefined(
    seeded: TranslationService,
) -> None:
    """A missing string shows as `nope.missing`, which is obvious in review."""
    assert await seeded.translate("nope.missing", Language.EN) == "nope.missing"


async def test_translate_accepts_an_explicit_default(
    seeded: TranslationService,
) -> None:
    result = await seeded.translate("nope.missing", Language.EN, default="Fallback")

    assert result == "Fallback"


async def test_translate_interpolates_parameters(
    seeded: TranslationService,
) -> None:
    result = await seeded.translate("dashboard.welcome", Language.EN, name="Ashraful")

    assert result == "Welcome back, Ashraful"


async def test_translate_interpolates_bengali(seeded: TranslationService) -> None:
    result = await seeded.translate("dashboard.welcome", Language.BN, name="আশরাফুল")

    assert result == "স্বাগতম, আশরাফুল"


async def test_translate_survives_a_missing_parameter(
    seeded: TranslationService,
) -> None:
    """A translator dropping a placeholder must not raise in production."""
    result = await seeded.translate("dashboard.welcome", Language.EN, wrong="x")

    assert result == "Welcome back, {name}"


# -- Missing key audit --------------------------------------------------


async def test_missing_keys_lists_untranslated_strings(
    seeded: TranslationService,
) -> None:
    missing = await seeded.missing_keys(Language.BN)

    assert "course.certificate" in missing


async def test_default_language_is_never_missing_keys(
    seeded: TranslationService,
) -> None:
    assert await seeded.missing_keys(Language.EN) == []


# -- CRUD ---------------------------------------------------------------


async def test_create_translation(translations: TranslationService) -> None:
    created = await translations.create(
        TranslationCreate(key="course.enroll", language=Language.EN, value="Enrol")
    )

    assert created.namespace == "course"
    assert created.language == "en"


async def test_create_rejects_a_duplicate_key_and_language(
    translations: TranslationService,
) -> None:
    payload = TranslationCreate(
        key="course.enroll", language=Language.EN, value="Enrol"
    )
    await translations.create(payload)

    with pytest.raises(ConflictException, match="already has an? en translation"):
        await translations.create(payload)


async def test_the_same_key_can_exist_in_another_language(
    translations: TranslationService,
) -> None:
    await translations.create(
        TranslationCreate(key="course.enroll", language=Language.EN, value="Enrol")
    )
    created = await translations.create(
        TranslationCreate(key="course.enroll", language=Language.BN, value="ভর্তি হন")
    )

    assert created.language == "bn"


async def test_update_changes_the_value(translations: TranslationService) -> None:
    created = await translations.create(
        TranslationCreate(key="login.button", language=Language.EN, value="Log in")
    )

    updated = await translations.update(created.id, TranslationUpdate(value="Sign in"))

    assert updated.value == "Sign in"


async def test_delete_removes_the_translation(
    translations: TranslationService,
) -> None:
    created = await translations.create(
        TranslationCreate(key="login.button", language=Language.EN, value="Log in")
    )

    await translations.delete(created.id)

    assert await translations.get_bundle(Language.EN) == {}


# -- Listing ------------------------------------------------------------


async def test_list_translations_paginates(seeded: TranslationService) -> None:
    items, total = await seeded.list_translations(PaginationParams(page=1, page_size=5))

    assert len(items) == 5
    assert total > 5


async def test_list_translations_filters_by_language(
    seeded: TranslationService,
) -> None:
    _, total = await seeded.list_translations(PaginationParams(), language=Language.BN)

    assert total == len(loader.load_language(Language.BN))


async def test_list_translations_searches_keys_and_values(
    seeded: TranslationService,
) -> None:
    items, _ = await seeded.list_translations(
        PaginationParams(), language=Language.EN, search="enrol"
    )

    assert {item.key for item in items} == {"course.enroll", "course.enrolled"}


async def test_list_namespaces(seeded: TranslationService) -> None:
    namespaces = await seeded.list_namespaces(Language.EN)

    assert namespaces == ["common", "course", "dashboard", "login", "validation"]
