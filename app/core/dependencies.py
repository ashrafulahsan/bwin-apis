"""Shared FastAPI dependencies - the application's dependency container.

Routers compose behaviour from the aliases exported here instead of building
`Depends(...)` chains inline, which keeps signatures short and the wiring in
one place. Database sessions and the current-user dependency are added here as
those layers land.
"""

from typing import Annotated

from fastapi import Depends, Query

from app.core.config import Settings, get_settings, settings
from app.core.constants import DEFAULT_PAGE, SortOrder


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


SettingsDep = Annotated[Settings, Depends(get_settings)]
PaginationDep = Annotated[PaginationParams, Depends(PaginationParams)]
SortDep = Annotated[SortParams, Depends(SortParams)]
SearchDep = Annotated[SearchParams, Depends(SearchParams)]
