"""Tests for pagination arithmetic and page schemas."""

import pytest

from app.core.dependencies import PaginationParams
from app.shared.schemas.pagination import Page
from app.shared.utils.pagination import (
    calculate_offset,
    calculate_total_pages,
    has_next_page,
    has_previous_page,
)


@pytest.mark.parametrize(
    ("page", "page_size", "expected"),
    [(1, 20, 0), (2, 20, 20), (3, 25, 50), (10, 1, 9)],
)
def test_calculate_offset(page: int, page_size: int, expected: int) -> None:
    assert calculate_offset(page, page_size) == expected


@pytest.mark.parametrize(("page", "page_size"), [(0, 20), (-1, 20), (1, 0)])
def test_calculate_offset_rejects_invalid_input(page: int, page_size: int) -> None:
    with pytest.raises(ValueError, match="1 or greater"):
        calculate_offset(page, page_size)


@pytest.mark.parametrize(
    ("total_items", "page_size", "expected"),
    [(0, 20, 0), (1, 20, 1), (20, 20, 1), (21, 20, 2), (100, 20, 5), (101, 20, 6)],
)
def test_calculate_total_pages(total_items: int, page_size: int, expected: int) -> None:
    assert calculate_total_pages(total_items, page_size) == expected


def test_calculate_total_pages_rejects_negative_totals() -> None:
    with pytest.raises(ValueError, match="negative"):
        calculate_total_pages(-1, 20)


def test_page_boundaries() -> None:
    assert has_previous_page(1) is False
    assert has_previous_page(2) is True
    assert has_next_page(1, 3) is True
    assert has_next_page(3, 3) is False


def test_page_create_builds_metadata() -> None:
    page = Page.create(items=["a", "b"], total_items=45, page=2, page_size=20)

    assert page.items == ["a", "b"]
    assert page.meta.page == 2
    assert page.meta.page_size == 20
    assert page.meta.total_items == 45
    assert page.meta.total_pages == 3
    assert page.meta.has_next is True
    assert page.meta.has_previous is True


def test_page_create_on_the_last_page() -> None:
    page = Page.create(items=["z"], total_items=41, page=3, page_size=20)

    assert page.meta.total_pages == 3
    assert page.meta.has_next is False
    assert page.meta.has_previous is True


def test_page_create_with_no_results() -> None:
    page = Page.create(items=[], total_items=0, page=1, page_size=20)

    assert page.items == []
    assert page.meta.total_pages == 0
    assert page.meta.has_next is False
    assert page.meta.has_previous is False


def test_page_from_params_reads_the_dependency() -> None:
    page = Page.from_params(
        items=[1, 2, 3],
        total_items=100,
        pagination=PaginationParams(page=2, page_size=3),
    )

    assert page.meta.page == 2
    assert page.meta.page_size == 3
    assert page.meta.total_pages == 34
