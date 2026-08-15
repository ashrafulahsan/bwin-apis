"""Tests for the generic repository, run against a real PostgreSQL table."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.core.database import AsyncSessionFactory
from app.core.dependencies import PaginationParams
from app.core.exceptions import NotFoundException
from app.shared.repositories.base import BaseRepository
from app.shared.repositories.filters import Filter, UnknownFieldError, escape_like
from tests.conftest import Widget, WidgetRepository

SAMPLE = [
    {"name": "Alpha", "category": "tools", "price": 100},
    {"name": "Beta", "category": "tools", "price": 200},
    {"name": "Gamma", "category": "toys", "price": 300},
    {"name": "Delta", "category": "toys", "price": 400, "is_active": False},
    {"name": "Epsilon", "category": "books", "price": 500},
]


@pytest.fixture
async def seeded(widgets: WidgetRepository) -> list[Widget]:
    return [await widgets.create(**row) for row in SAMPLE]


# -- Create -------------------------------------------------------------


async def test_create_populates_database_defaults(widgets: WidgetRepository) -> None:
    widget = await widgets.create(name="Alpha", category="tools", price=100)

    assert isinstance(widget.id, uuid.UUID)
    assert widget.created_at is not None
    assert widget.updated_at is not None
    assert widget.deleted_at is None
    assert widget.is_active is True


async def test_create_many(widgets: WidgetRepository) -> None:
    created = await widgets.create_many(SAMPLE[:3])

    assert len(created) == 3
    assert await widgets.count() == 3


# -- Read ---------------------------------------------------------------


async def test_get_returns_the_row(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    found = await widgets.get(seeded[0].id)

    assert found is not None
    assert found.name == "Alpha"


async def test_get_returns_none_for_an_unknown_id(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    assert await widgets.get(uuid.uuid4()) is None


async def test_get_or_raise_raises_not_found(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    with pytest.raises(NotFoundException, match="Widget not found"):
        await widgets.get_or_raise(uuid.uuid4())


async def test_get_by_field(widgets: WidgetRepository, seeded: list[Widget]) -> None:
    found = await widgets.get_by_field("name", "Gamma")

    assert found is not None
    assert found.category == "toys"


async def test_get_by_combines_filters(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    found = await widgets.get_by(
        Filter.eq("category", "toys"), Filter.gte("price", 400)
    )

    assert found is not None
    assert found.name == "Delta"


async def test_exists(widgets: WidgetRepository, seeded: list[Widget]) -> None:
    assert await widgets.exists(Filter.eq("name", "Beta")) is True
    assert await widgets.exists(Filter.eq("name", "Missing")) is False


# -- Filtering ----------------------------------------------------------


@pytest.mark.parametrize(
    ("filter_", "expected"),
    [
        (Filter.eq("category", "tools"), {"Alpha", "Beta"}),
        (Filter.ne("category", "tools"), {"Gamma", "Delta", "Epsilon"}),
        (Filter.gt("price", 300), {"Delta", "Epsilon"}),
        (Filter.gte("price", 300), {"Gamma", "Delta", "Epsilon"}),
        (Filter.lt("price", 200), {"Alpha"}),
        (Filter.lte("price", 200), {"Alpha", "Beta"}),
        (Filter.in_("category", ["toys", "books"]), {"Gamma", "Delta", "Epsilon"}),
        (Filter.not_in("category", ["toys", "books"]), {"Alpha", "Beta"}),
        (Filter.contains("name", "et"), {"Beta"}),
        (Filter.starts_with("name", "G"), {"Gamma"}),
        (Filter.ends_with("name", "a"), {"Alpha", "Beta", "Gamma", "Delta"}),
        (Filter.between("price", 200, 400), {"Beta", "Gamma", "Delta"}),
        (Filter.eq("is_active", False), {"Delta"}),
        (Filter.is_null("deleted_at"), {"Alpha", "Beta", "Gamma", "Delta", "Epsilon"}),
    ],
)
async def test_filter_operators(
    widgets: WidgetRepository,
    seeded: list[Widget],
    filter_: Filter,
    expected: set[str],
) -> None:
    results = await widgets.list(filters=[filter_])

    assert {widget.name for widget in results} == expected


async def test_filters_are_combined_with_and(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    results = await widgets.list(
        filters=[Filter.eq("category", "toys"), Filter.lt("price", 400)]
    )

    assert [widget.name for widget in results] == ["Gamma"]


async def test_unknown_filter_field_is_rejected(widgets: WidgetRepository) -> None:
    with pytest.raises(UnknownFieldError, match="Unknown field 'nope'"):
        await widgets.list(filters=[Filter.eq("nope", 1)])


async def test_unknown_field_is_a_bad_request(widgets: WidgetRepository) -> None:
    """It arrives from query parameters, so a typo must not become a 500."""
    with pytest.raises(UnknownFieldError) as exc_info:
        await widgets.list(filters=[Filter.eq("__class__", 1)])

    assert exc_info.value.status_code == 400


# -- Search -------------------------------------------------------------


async def test_search_matches_any_field(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    results = await widgets.list(search="to", search_fields=["name", "category"])

    assert {widget.name for widget in results} == {"Alpha", "Beta", "Gamma", "Delta"}


async def test_search_is_case_insensitive(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    results = await widgets.list(search="ALPHA", search_fields=["name"])

    assert [widget.name for widget in results] == ["Alpha"]


async def test_search_treats_wildcards_literally(widgets: WidgetRepository) -> None:
    """A `%` in user input must match a literal percent, not everything."""
    await widgets.create(name="100% Cotton", category="cloth", price=10)
    await widgets.create(name="Plain Cotton", category="cloth", price=10)

    results = await widgets.list(search="100%", search_fields=["name"])

    assert [widget.name for widget in results] == ["100% Cotton"]


async def test_search_treats_underscore_literally(widgets: WidgetRepository) -> None:
    await widgets.create(name="snake_case", category="code", price=1)
    await widgets.create(name="snakeXcase", category="code", price=1)

    results = await widgets.list(search="snake_case", search_fields=["name"])

    assert [widget.name for widget in results] == ["snake_case"]


def test_escape_like_neutralizes_wildcards() -> None:
    assert escape_like("100%") == "100\\%"
    assert escape_like("a_b") == "a\\_b"
    assert escape_like("back\\slash") == "back\\\\slash"


# -- Sorting ------------------------------------------------------------


async def test_sort_ascending(widgets: WidgetRepository, seeded: list[Widget]) -> None:
    results = await widgets.list(sort_by="price", sort_order=SortOrder.ASC)

    assert [widget.price for widget in results] == [100, 200, 300, 400, 500]


async def test_sort_descending(widgets: WidgetRepository, seeded: list[Widget]) -> None:
    results = await widgets.list(sort_by="price", sort_order=SortOrder.DESC)

    assert [widget.price for widget in results] == [500, 400, 300, 200, 100]


async def test_unknown_sort_field_is_rejected(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    with pytest.raises(UnknownFieldError, match="Unknown field 'bogus'"):
        await widgets.list(sort_by="bogus")


async def test_ordering_is_stable_when_the_sort_column_ties(
    widgets: WidgetRepository,
) -> None:
    """Every row shares a price, so only the id tiebreaker gives a total order."""
    for name in ["one", "two", "three", "four", "five"]:
        await widgets.create(name=name, category="same", price=42)

    first = await widgets.list(sort_by="price", sort_order=SortOrder.ASC)
    second = await widgets.list(sort_by="price", sort_order=SortOrder.ASC)

    assert [widget.id for widget in first] == [widget.id for widget in second]


# -- Pagination ---------------------------------------------------------


async def test_paginate_returns_a_page_and_the_total(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    items, total = await widgets.paginate(
        PaginationParams(page=1, page_size=2), sort_by="price", sort_order=SortOrder.ASC
    )

    assert total == 5
    assert [widget.price for widget in items] == [100, 200]


async def test_paginate_second_page(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    items, total = await widgets.paginate(
        PaginationParams(page=2, page_size=2), sort_by="price", sort_order=SortOrder.ASC
    )

    assert total == 5
    assert [widget.price for widget in items] == [300, 400]


async def test_paginate_past_the_end(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    items, total = await widgets.paginate(PaginationParams(page=99, page_size=20))

    assert items == []
    assert total == 5


async def test_paginate_total_reflects_the_filters(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    """The count must apply the same criteria as the page, not count everything."""
    items, total = await widgets.paginate(
        PaginationParams(page=1, page_size=10),
        filters=[Filter.eq("category", "tools")],
    )

    assert total == 2
    assert len(items) == 2


async def test_paginate_accepts_a_filter_generator(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    """A generator would be exhausted by the count, leaving the page unfiltered."""
    criteria = (Filter.eq("category", category) for category in ["tools"])

    items, total = await widgets.paginate(
        PaginationParams(page=1, page_size=10), filters=criteria
    )

    assert total == 2
    assert len(items) == 2


# -- Counting -----------------------------------------------------------


async def test_count_all(widgets: WidgetRepository, seeded: list[Widget]) -> None:
    assert await widgets.count() == 5


async def test_count_with_filters(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    assert await widgets.count(filters=[Filter.eq("category", "toys")]) == 2


# -- Update -------------------------------------------------------------


async def test_update_changes_fields(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    updated = await widgets.update(seeded[0], name="Renamed", price=999)

    assert updated.name == "Renamed"
    assert updated.price == 999


async def test_update_leaves_updated_at_alone_within_one_transaction(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    """`now()` is the transaction timestamp, so it does not move mid-transaction."""
    before = seeded[0].updated_at

    updated = await widgets.update(seeded[0], price=111)

    assert updated.updated_at == before


async def test_update_advances_updated_at_across_transactions(
    widget_table: None,
) -> None:
    """The case that matters in production: two requests, two transactions."""
    async with AsyncSessionFactory() as session:
        widget = await WidgetRepository(session).create(
            name="Timestamped", category="time", price=1
        )
        await session.commit()
        widget_id, created_at = widget.id, widget.updated_at

    try:
        async with AsyncSessionFactory() as session:
            repository = WidgetRepository(session)
            target = await repository.get_or_raise(widget_id)
            await repository.update(target, price=2)
            await session.commit()

            assert target.updated_at > created_at
    finally:
        async with AsyncSessionFactory() as session:
            repository = WidgetRepository(session)
            leftover = await repository.get(widget_id, include_deleted=True)
            if leftover is not None:
                await repository.delete(leftover)
            await session.commit()


async def test_update_rejects_unknown_fields(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    with pytest.raises(UnknownFieldError, match="Unknown field 'nonexistent'"):
        await widgets.update(seeded[0], nonexistent="value")


# -- Delete -------------------------------------------------------------


async def test_delete_removes_the_row(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    target = seeded[0]

    await widgets.delete(target)

    assert await widgets.get(target.id) is None
    assert await widgets.count() == 4


async def test_soft_delete_hides_the_row(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    target = seeded[0]

    await widgets.soft_delete(target)

    assert target.deleted_at is not None
    assert await widgets.get(target.id) is None
    assert await widgets.count() == 4


async def test_soft_deleted_rows_are_reachable_on_request(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    target = seeded[0]
    await widgets.soft_delete(target)

    assert await widgets.get(target.id, include_deleted=True) is not None
    assert await widgets.count(include_deleted=True) == 5


async def test_restore_brings_the_row_back(
    widgets: WidgetRepository, seeded: list[Widget]
) -> None:
    target = seeded[0]
    await widgets.soft_delete(target)

    await widgets.restore(target)

    assert target.deleted_at is None
    assert await widgets.get(target.id) is not None


# -- Subclass contract --------------------------------------------------


def test_subclass_must_declare_a_model() -> None:
    with pytest.raises(TypeError, match="must set a `model` attribute"):

        class BrokenRepository(BaseRepository[Widget]):
            pass


def test_soft_delete_helpers_require_the_column(session: AsyncSession) -> None:
    assert WidgetRepository(session).supports_soft_delete is True
