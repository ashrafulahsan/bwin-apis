"""Translation endpoints.

Read endpoints only for now. Create, update, delete and import are held back
until the roles module can enforce `TranslationPermission`, since an
unauthenticated write endpoint would let anyone rewrite the interface.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.constants import Language
from app.core.dependencies import DbSession, LanguageDep, PaginationDep, SearchDep
from app.modules.translations.schemas.translation import (
    MissingTranslations,
    TranslationBundle,
    TranslationRead,
)
from app.modules.translations.services.translation import TranslationService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    paginated_response,
    success_response,
)

router = APIRouter(prefix="/translations", tags=["Translations"])


@router.get(
    "",
    response_model=APIResponse[TranslationBundle],
    summary="Translation bundle",
    description=(
        "Every translation for the negotiated language, as a flat key/value "
        "map. Keys missing from the language fall back to English, so a "
        "partly translated interface still renders."
    ),
)
async def get_bundle(
    db: DbSession,
    language: LanguageDep,
    namespace: Annotated[
        str | None,
        Query(description="Limit to one key group, e.g. `dashboard`."),
    ] = None,
) -> APIResponse[TranslationBundle]:
    translations = await TranslationService(db).get_bundle(
        language, namespace=namespace
    )

    return success_response(
        data=TranslationBundle(
            language=language,
            namespace=namespace,
            count=len(translations),
            translations=translations,
        ),
        message="Translations fetched",
    )


@router.get(
    "/namespaces",
    response_model=APIResponse[list[str]],
    summary="List namespaces",
)
async def list_namespaces(
    db: DbSession,
    language: Annotated[
        Language | None, Query(description="Restrict to one language.")
    ] = None,
) -> APIResponse[list[str]]:
    namespaces = await TranslationService(db).list_namespaces(language)

    return success_response(data=namespaces, message="Namespaces fetched")


@router.get(
    "/missing",
    response_model=APIResponse[MissingTranslations],
    summary="Untranslated keys",
    description="Keys defined in English but absent from the given language.",
)
async def list_missing(
    db: DbSession,
    language: Annotated[Language, Query(description="Language to audit.")],
) -> APIResponse[MissingTranslations]:
    keys = await TranslationService(db).missing_keys(language)

    return success_response(
        data=MissingTranslations(language=language, count=len(keys), keys=keys),
        message="Missing translations fetched",
    )


@router.get(
    "/entries",
    response_model=APIResponse[Page[TranslationRead]],
    summary="Browse translations",
    description="Paginated rows for an admin interface, one per key/language.",
)
async def list_entries(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    language: Annotated[
        Language | None, Query(description="Filter by language.")
    ] = None,
    namespace: Annotated[str | None, Query(description="Filter by key group.")] = None,
) -> APIResponse[Page[TranslationRead]]:
    items, total = await TranslationService(db).list_translations(
        pagination, language=language, namespace=namespace, search=search.search
    )

    return paginated_response(
        [TranslationRead.model_validate(item) for item in items],
        total,
        pagination,
        message="Translations fetched",
    )
