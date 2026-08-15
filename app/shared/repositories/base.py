"""Generic asynchronous CRUD repository.

Every module's repository subclasses `BaseRepository`, so the routine queries
are written once. Repositories never commit - the service layer owns the
transaction boundary - they only `flush()` when they need the database to
assign defaults.
"""

import uuid
from collections.abc import Iterable, Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.core.database import Base
from app.core.exceptions import NotFoundException
from app.shared.repositories.filters import (
    Filter,
    build_conditions,
    build_search_condition,
    resolve_column,
)
from app.shared.schemas.pagination import SupportsPagination
from app.shared.utils.dates import utc_now
from app.shared.utils.pagination import calculate_offset

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Reusable data access for a single model.

        class UserRepository(BaseRepository[User]):
            model = User

    Subclasses add only the queries that are specific to their model.
    """

    #: Set by every subclass.
    model: type[ModelT]

    #: Column used to order results when the caller does not choose one.
    default_sort_by: str | None = "created_at"

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Catch the missing attribute at import time rather than on the first
        # query in production.
        if not getattr(cls, "__abstract_repository__", False) and not hasattr(
            cls, "model"
        ):
            raise TypeError(f"{cls.__name__} must set a `model` attribute.")

    # -- Query construction --------------------------------------------

    @property
    def supports_soft_delete(self) -> bool:
        return hasattr(self.model, "deleted_at")

    def _conditions(
        self,
        *,
        filters: Iterable[Filter] | None = None,
        search: str | None = None,
        search_fields: Sequence[str] | None = None,
        include_deleted: bool = False,
    ) -> list[ColumnElement[bool]]:
        """Assemble the WHERE clauses shared by reads and counts."""
        conditions: list[ColumnElement[bool]] = []

        if self.supports_soft_delete and not include_deleted:
            conditions.append(self.model.deleted_at.is_(None))

        if filters:
            conditions.extend(build_conditions(self.model, filters))

        if search and search_fields:
            conditions.append(build_search_condition(self.model, search, search_fields))

        return conditions

    def _apply_ordering(
        self,
        statement: Select[Any],
        sort_by: str | None,
        sort_order: SortOrder,
    ) -> Select[Any]:
        """Order by the caller's column, falling back to the model default.

        A primary key tiebreaker is always appended so pagination is stable:
        rows sharing a `created_at` would otherwise be free to swap places
        between two queries, showing a client one row twice and hiding
        another.
        """
        ordering = []
        column_name = sort_by or self.default_sort_by

        if column_name and hasattr(self.model, column_name):
            column = resolve_column(self.model, column_name)
            ordering.append(
                column.asc() if sort_order is SortOrder.ASC else column.desc()
            )
        elif sort_by:
            # Named explicitly but absent - surface it rather than ignore it.
            resolve_column(self.model, sort_by)

        if column_name != "id" and hasattr(self.model, "id"):
            id_column = resolve_column(self.model, "id")
            ordering.append(
                id_column.asc() if sort_order is SortOrder.ASC else id_column.desc()
            )

        return statement.order_by(*ordering) if ordering else statement

    # -- Reads ----------------------------------------------------------

    async def get(
        self, entity_id: uuid.UUID, *, include_deleted: bool = False
    ) -> ModelT | None:
        """Fetch by primary key, or `None` when it does not exist."""
        conditions = self._conditions(include_deleted=include_deleted)
        statement = select(self.model).where(self.model.id == entity_id, *conditions)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_or_raise(
        self, entity_id: uuid.UUID, *, include_deleted: bool = False
    ) -> ModelT:
        """Fetch by primary key, raising `NotFoundException` when missing."""
        instance = await self.get(entity_id, include_deleted=include_deleted)
        if instance is None:
            raise NotFoundException(self.model.__name__)
        return instance

    async def get_by(
        self, *filters: Filter, include_deleted: bool = False
    ) -> ModelT | None:
        """Fetch the first row matching `filters`."""
        conditions = self._conditions(filters=filters, include_deleted=include_deleted)
        statement = select(self.model).where(*conditions).limit(1)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_field(
        self, field: str, value: Any, *, include_deleted: bool = False
    ) -> ModelT | None:
        """Convenience wrapper for the common single-column lookup."""
        return await self.get_by(
            Filter.eq(field, value), include_deleted=include_deleted
        )

    async def list(
        self,
        *,
        filters: Iterable[Filter] | None = None,
        search: str | None = None,
        search_fields: Sequence[str] | None = None,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.DESC,
        offset: int | None = None,
        limit: int | None = None,
        include_deleted: bool = False,
    ) -> list[ModelT]:
        """Fetch rows matching the given filters, search, ordering and slice."""
        conditions = self._conditions(
            filters=filters,
            search=search,
            search_fields=search_fields,
            include_deleted=include_deleted,
        )

        statement = self._apply_ordering(
            select(self.model).where(*conditions), sort_by, sort_order
        )

        if offset is not None:
            statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)

        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def count(
        self,
        *,
        filters: Iterable[Filter] | None = None,
        search: str | None = None,
        search_fields: Sequence[str] | None = None,
        include_deleted: bool = False,
    ) -> int:
        """Count rows matching the same criteria `list()` would apply."""
        conditions = self._conditions(
            filters=filters,
            search=search,
            search_fields=search_fields,
            include_deleted=include_deleted,
        )
        statement = select(func.count()).select_from(self.model).where(*conditions)
        result = await self.session.execute(statement)
        return int(result.scalar_one())

    async def paginate(
        self,
        pagination: SupportsPagination,
        *,
        filters: Iterable[Filter] | None = None,
        search: str | None = None,
        search_fields: Sequence[str] | None = None,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.DESC,
        include_deleted: bool = False,
    ) -> tuple[list[ModelT], int]:
        """Return one page of rows plus the total count matching the query.

        The total is what `paginated_response` needs to build page metadata;
        it counts every match, not just the rows on this page.
        """
        # Materialize once: a generator of filters would be exhausted by the
        # count and leave the page unfiltered.
        criteria = list(filters) if filters is not None else None

        total = await self.count(
            filters=criteria,
            search=search,
            search_fields=search_fields,
            include_deleted=include_deleted,
        )
        items = await self.list(
            filters=criteria,
            search=search,
            search_fields=search_fields,
            sort_by=sort_by,
            sort_order=sort_order,
            offset=calculate_offset(pagination.page, pagination.page_size),
            limit=pagination.page_size,
            include_deleted=include_deleted,
        )
        return items, total

    async def exists(self, *filters: Filter, include_deleted: bool = False) -> bool:
        """Whether any row matches, without fetching it."""
        conditions = self._conditions(filters=filters, include_deleted=include_deleted)
        statement = select(select(self.model).where(*conditions).exists())
        result = await self.session.execute(statement)
        return bool(result.scalar_one())

    # -- Writes ---------------------------------------------------------

    async def create(self, **values: Any) -> ModelT:
        """Add a row and flush, so database defaults are populated.

        No `refresh()` is needed: on PostgreSQL the INSERT uses RETURNING, so
        `id`, `created_at` and friends are already loaded once the flush
        completes.
        """
        instance = self.model(**values)
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def create_many(self, values: Iterable[dict[str, Any]]) -> list[ModelT]:
        """Add several rows in one flush."""
        instances = [self.model(**row) for row in values]
        self.session.add_all(instances)
        await self.session.flush()
        return instances

    async def update(self, instance: ModelT, **values: Any) -> ModelT:
        """Apply `values` to a loaded instance and flush.

        The `refresh()` is required, not defensive: an UPDATE expires columns
        carrying a server-side `onupdate` such as `updated_at`, and reading an
        expired attribute afterwards triggers lazy IO, which raises
        `MissingGreenlet` under asyncio.
        """
        for field, value in values.items():
            resolve_column(type(instance), field)
            setattr(instance, field, value)

        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def delete(self, instance: ModelT) -> None:
        """Remove the row permanently."""
        await self.session.delete(instance)
        await self.session.flush()

    async def soft_delete(self, instance: ModelT) -> ModelT:
        """Mark the row deleted, keeping it for audit and restore.

        Refreshed for the same reason `update()` is: this writes an UPDATE,
        which expires `updated_at` and anything else with a server-side
        `onupdate`, and reading an expired attribute afterwards triggers lazy
        IO - `MissingGreenlet` under asyncio, at response-rendering time.
        """
        if not self.supports_soft_delete:
            raise TypeError(f"{self.model.__name__} has no `deleted_at` column.")

        instance.deleted_at = utc_now()
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def restore(self, instance: ModelT) -> ModelT:
        """Undo a soft delete, refreshing as `soft_delete()` does."""
        if not self.supports_soft_delete:
            raise TypeError(f"{self.model.__name__} has no `deleted_at` column.")

        instance.deleted_at = None
        await self.session.flush()
        await self.session.refresh(instance)
        return instance
