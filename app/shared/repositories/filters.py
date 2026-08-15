"""Declarative filtering, searching and sorting for repository queries.

Filters are described as data rather than as SQLAlchemy expressions, so a
service can build them from query parameters without importing the ORM, and
the repository stays the only layer that knows how to turn them into SQL.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import ColumnElement, Select, or_
from sqlalchemy.orm import InstrumentedAttribute

from app.core.constants import SortOrder
from app.core.exceptions import BadRequestException

# Backslash escape for LIKE/ILIKE patterns, so a search term containing `%`
# or `_` is matched literally instead of acting as a wildcard.
_LIKE_ESCAPE = "\\"


class UnknownFieldError(BadRequestException):
    """Raised when a filter or sort names a column the model does not have.

    Deliberately a 400: these names usually arrive from query parameters, and
    a typo should not surface as a 500.
    """

    def __init__(self, model: type[Any], field: str) -> None:
        super().__init__(f"Unknown field '{field}' for {model.__name__}.")


class FilterOperator(StrEnum):
    """Comparison operators a `Filter` can express."""

    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"
    LIKE = "like"
    ILIKE = "ilike"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    IS_NULL = "is_null"
    BETWEEN = "between"


@dataclass(frozen=True, slots=True)
class Filter:
    """A single condition: `field operator value`."""

    field: str
    value: Any = None
    operator: FilterOperator = FilterOperator.EQ

    @classmethod
    def eq(cls, field: str, value: Any) -> "Filter":
        return cls(field, value, FilterOperator.EQ)

    @classmethod
    def ne(cls, field: str, value: Any) -> "Filter":
        return cls(field, value, FilterOperator.NE)

    @classmethod
    def gt(cls, field: str, value: Any) -> "Filter":
        return cls(field, value, FilterOperator.GT)

    @classmethod
    def gte(cls, field: str, value: Any) -> "Filter":
        return cls(field, value, FilterOperator.GTE)

    @classmethod
    def lt(cls, field: str, value: Any) -> "Filter":
        return cls(field, value, FilterOperator.LT)

    @classmethod
    def lte(cls, field: str, value: Any) -> "Filter":
        return cls(field, value, FilterOperator.LTE)

    @classmethod
    def in_(cls, field: str, values: Iterable[Any]) -> "Filter":
        return cls(field, list(values), FilterOperator.IN)

    @classmethod
    def not_in(cls, field: str, values: Iterable[Any]) -> "Filter":
        return cls(field, list(values), FilterOperator.NOT_IN)

    @classmethod
    def contains(cls, field: str, value: str) -> "Filter":
        return cls(field, value, FilterOperator.CONTAINS)

    @classmethod
    def starts_with(cls, field: str, value: str) -> "Filter":
        return cls(field, value, FilterOperator.STARTS_WITH)

    @classmethod
    def ends_with(cls, field: str, value: str) -> "Filter":
        return cls(field, value, FilterOperator.ENDS_WITH)

    @classmethod
    def is_null(cls, field: str, is_null: bool = True) -> "Filter":
        return cls(field, is_null, FilterOperator.IS_NULL)

    @classmethod
    def between(cls, field: str, low: Any, high: Any) -> "Filter":
        return cls(field, (low, high), FilterOperator.BETWEEN)


def escape_like(value: str) -> str:
    """Neutralize LIKE wildcards in user supplied search text."""
    return (
        value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )


_BUILDERS: dict[
    FilterOperator, Callable[[InstrumentedAttribute[Any], Any], ColumnElement[bool]]
] = {
    FilterOperator.EQ: lambda column, value: column == value,
    FilterOperator.NE: lambda column, value: column != value,
    FilterOperator.GT: lambda column, value: column > value,
    FilterOperator.GTE: lambda column, value: column >= value,
    FilterOperator.LT: lambda column, value: column < value,
    FilterOperator.LTE: lambda column, value: column <= value,
    FilterOperator.IN: lambda column, value: column.in_(value),
    FilterOperator.NOT_IN: lambda column, value: column.notin_(value),
    FilterOperator.LIKE: lambda column, value: column.like(value),
    FilterOperator.ILIKE: lambda column, value: column.ilike(value),
    FilterOperator.CONTAINS: lambda column, value: column.ilike(
        f"%{escape_like(value)}%", escape=_LIKE_ESCAPE
    ),
    FilterOperator.STARTS_WITH: lambda column, value: column.ilike(
        f"{escape_like(value)}%", escape=_LIKE_ESCAPE
    ),
    FilterOperator.ENDS_WITH: lambda column, value: column.ilike(
        f"%{escape_like(value)}", escape=_LIKE_ESCAPE
    ),
    FilterOperator.IS_NULL: lambda column, value: (
        column.is_(None) if value else column.is_not(None)
    ),
    FilterOperator.BETWEEN: lambda column, value: column.between(*value),
}


def resolve_column(model: type[Any], field: str) -> InstrumentedAttribute[Any]:
    """Look up a mapped column by name, rejecting anything else.

    The `InstrumentedAttribute` check is what stops a query parameter from
    reaching an arbitrary attribute or method on the model.
    """
    attribute = getattr(model, field, None)
    if not isinstance(attribute, InstrumentedAttribute):
        raise UnknownFieldError(model, field)
    return attribute


def build_condition(model: type[Any], filter_: Filter) -> ColumnElement[bool]:
    """Turn one `Filter` into a SQLAlchemy condition."""
    column = resolve_column(model, filter_.field)
    return _BUILDERS[filter_.operator](column, filter_.value)


def build_conditions(
    model: type[Any], filters: Iterable[Filter]
) -> list[ColumnElement[bool]]:
    """Turn many filters into conditions, combined by the caller with AND."""
    return [build_condition(model, filter_) for filter_ in filters]


def build_search_condition(
    model: type[Any], term: str, fields: Sequence[str]
) -> ColumnElement[bool]:
    """Case-insensitive `term` match across any of `fields`."""
    if not fields:
        raise ValueError("At least one search field is required.")

    return or_(
        *(build_condition(model, Filter.contains(field, term)) for field in fields)
    )


def apply_sorting(
    statement: Select[Any],
    model: type[Any],
    sort_by: str | None,
    sort_order: SortOrder = SortOrder.DESC,
    *,
    tiebreaker: str | None = "id",
) -> Select[Any]:
    """Order the statement, always appending a unique tiebreaker.

    Without a deterministic total order, two rows sharing a `created_at` can
    swap places between queries, so a paginated client sees one row twice and
    misses another entirely.
    """
    ordering = []

    if sort_by:
        column = resolve_column(model, sort_by)
        ordering.append(column.asc() if sort_order is SortOrder.ASC else column.desc())

    if tiebreaker and tiebreaker != sort_by:
        tie_column = getattr(model, tiebreaker, None)
        if isinstance(tie_column, InstrumentedAttribute):
            ordering.append(
                tie_column.asc() if sort_order is SortOrder.ASC else tie_column.desc()
            )

    return statement.order_by(*ordering) if ordering else statement
