"""Shared FastAPI dependencies - the application's dependency container.

Routers compose behaviour from the aliases exported here instead of building
`Depends(...)` chains inline, which keeps signatures short and the wiring in
one place. Database sessions and the current-user dependency are added here as
those layers land.
"""

from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings, settings
from app.core.constants import (
    ACCEPT_LANGUAGE_HEADER,
    DEFAULT_PAGE,
    Language,
    SortOrder,
)
from app.core.database import get_db
from app.shared.utils.language import resolve_language, supported_languages


class PaginationParams:
    """Common `?page=&page_size=` query parameters."""

    def __init__(
        self,
        page: Annotated[
            int, Query(ge=1, description="1-based page number.")
        ] = DEFAULT_PAGE,
        page_size: Annotated[
            int,
            Query(
                ge=1,
                le=settings.max_page_size,
                description="Number of records per page.",
            ),
        ] = settings.default_page_size,
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        """Rows to skip - passed straight to the repository layer."""
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class SortParams:
    """Common `?sort_by=&sort_order=` query parameters."""

    def __init__(
        self,
        sort_by: Annotated[
            str | None, Query(description="Field name to sort by.")
        ] = None,
        sort_order: Annotated[
            SortOrder, Query(description="Sort direction.")
        ] = SortOrder.DESC,
    ) -> None:
        self.sort_by = sort_by
        self.sort_order = sort_order


class SearchParams:
    """Common `?search=` query parameter."""

    def __init__(
        self,
        search: Annotated[
            str | None, Query(min_length=1, max_length=255, description="Search term.")
        ] = None,
    ) -> None:
        self.search = search.strip() if search else None


async def get_language(
    request: Request,
    lang: Annotated[
        str | None,
        Query(
            description=(
                "Preferred language: "
                + " or ".join(language.value for language in supported_languages())
                + ". Overrides the Accept-Language header. An unrecognised "
                "value falls back to the default rather than failing."
            ),
        ),
    ] = None,
) -> Language:
    """Resolve the response language for this request.

    Declared as a dependency rather than read from the middleware's context
    so `?lang=` appears in the OpenAPI schema, and so the resolution still
    works for anyone mounting a router without the middleware.
    """
    return resolve_language(
        requested=lang,
        accept_language=request.headers.get(ACCEPT_LANGUAGE_HEADER),
    )


DbSession = Annotated[AsyncSession, Depends(get_db)]
LanguageDep = Annotated[Language, Depends(get_language)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
PaginationDep = Annotated[PaginationParams, Depends(PaginationParams)]
SortDep = Annotated[SortParams, Depends(SortParams)]
SearchDep = Annotated[SearchParams, Depends(SearchParams)]
