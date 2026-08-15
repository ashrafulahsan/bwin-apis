"""Pure pagination arithmetic.

Deliberately free of Pydantic and ORM imports so it can be used from any
layer - repositories building queries, schemas building metadata, or tests.
"""

from math import ceil


def calculate_offset(page: int, page_size: int) -> int:
    """Rows to skip for a 1-based page number."""
    if page < 1:
        raise ValueError("page must be 1 or greater.")
    if page_size < 1:
        raise ValueError("page_size must be 1 or greater.")
    return (page - 1) * page_size


def calculate_total_pages(total_items: int, page_size: int) -> int:
    """Page count for a result set; an empty set has zero pages."""
    if page_size < 1:
        raise ValueError("page_size must be 1 or greater.")
    if total_items < 0:
        raise ValueError("total_items cannot be negative.")
    return ceil(total_items / page_size)


def has_next_page(page: int, total_pages: int) -> bool:
    return page < total_pages


def has_previous_page(page: int) -> bool:
    """True from page 2 onward, regardless of whether that page has rows."""
    return page > 1
