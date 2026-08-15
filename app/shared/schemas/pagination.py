"""Paginated payload schemas.

A paginated endpoint keeps the standard envelope and puts the page inside
`data`:

    {"success": true, "message": "...", "data": {"items": [...], "meta": {...}}}
"""

from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel, Field

from app.shared.utils.pagination import (
    calculate_total_pages,
    has_next_page,
    has_previous_page,
)

T = TypeVar("T")


class SupportsPagination(Protocol):
    """Anything exposing `page` / `page_size`, such as `PaginationParams`."""

    page: int
    page_size: int


class PageMeta(BaseModel):
    """Everything a client needs to render pagination controls."""

    page: int = Field(description="Current 1-based page number.")
    page_size: int = Field(description="Records requested per page.")
    total_items: int = Field(description="Total records matching the query.")
    total_pages: int = Field(description="Total pages available.")
    has_next: bool = Field(description="Whether a following page exists.")
    has_previous: bool = Field(description="Whether a preceding page exists.")


class Page(BaseModel, Generic[T]):
    """A slice of results plus its metadata."""

    items: list[T] = Field(default_factory=list, description="Records on this page.")
    meta: PageMeta = Field(description="Pagination metadata.")

    @classmethod
    def create(
        cls, items: list[T], total_items: int, page: int, page_size: int
    ) -> "Page[T]":
        """Build a page from a result slice and the total row count."""
        total_pages = calculate_total_pages(total_items, page_size)
        return cls(
            items=items,
            meta=PageMeta(
                page=page,
                page_size=page_size,
                total_items=total_items,
                total_pages=total_pages,
                has_next=has_next_page(page, total_pages),
                has_previous=has_previous_page(page),
            ),
        )

    @classmethod
    def from_params(
        cls, items: list[T], total_items: int, pagination: SupportsPagination
    ) -> "Page[T]":
        """Build a page straight from the request's `PaginationDep`."""
        return cls.create(items, total_items, pagination.page, pagination.page_size)
