"""Schema-level guarantees that the ORM layer alone cannot enforce."""

import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import engine
from app.modules.permissions.models.role_permission import role_permissions
from app.modules.users.models.user_role import user_roles

#: Association tables and the natural key each one must keep unique.
JUNCTIONS = {
    "role_permissions": ("role_id", "permission_id"),
    "user_roles": ("user_id", "role_id"),
}

APPLICATION_TABLES = [
    "users",
    "roles",
    "permissions",
    "translations",
    "user_identities",
    "user_roles",
    "role_permissions",
]


async def _table_names() -> set[str]:
    async with engine.connect() as connection:
        return set(
            await connection.run_sync(lambda sync: inspect(sync).get_table_names())
        )


async def test_every_application_table_exists(database: None) -> None:
    assert set(APPLICATION_TABLES) <= await _table_names()


@pytest.mark.parametrize("table", APPLICATION_TABLES)
async def test_every_table_has_a_single_column_id_primary_key(
    database: None, table: str
) -> None:
    """One addressable key per row, consistently across the schema."""
    async with engine.connect() as connection:
        primary_key = await connection.run_sync(
            lambda sync: inspect(sync).get_pk_constraint(table)
        )

    assert primary_key["constrained_columns"] == [
        "id"
    ], f"{table} primary key is {primary_key['constrained_columns']}"


@pytest.mark.parametrize(("table", "columns"), JUNCTIONS.items())
async def test_junction_tables_keep_their_natural_key_unique(
    database: None, table: str, columns: tuple[str, str]
) -> None:
    """The surrogate `id` replaced the composite primary key.

    Without this constraint, nothing would stop the same pair being inserted
    twice - which is exactly what the old composite key prevented.
    """
    async with engine.connect() as connection:
        constraints = await connection.run_sync(
            lambda sync: inspect(sync).get_unique_constraints(table)
        )

    pairs = [tuple(item["column_names"]) for item in constraints]
    assert columns in pairs, f"{table} is missing UNIQUE {columns}"


@pytest.mark.parametrize(("table", "columns"), JUNCTIONS.items())
async def test_junction_tables_index_the_reverse_lookup(
    database: None, table: str, columns: tuple[str, str]
) -> None:
    """The unique index only serves queries leading with the first column.

    Reading "which roles hold this permission" filters on the second, so it
    needs an index of its own or it scans the table.
    """
    async with engine.connect() as connection:
        indexes = await connection.run_sync(
            lambda sync: inspect(sync).get_indexes(table)
        )

    indexed = {tuple(item["column_names"]) for item in indexes}
    assert (columns[1],) in indexed, f"{table}.{columns[1]} is not indexed"


async def test_duplicate_role_permission_is_rejected(session: AsyncSession) -> None:
    """Proven against PostgreSQL, not just asserted from metadata."""
    role_id, permission_id = await _seed_pair(session)

    await session.execute(
        role_permissions.insert().values(role_id=role_id, permission_id=permission_id)
    )
    await session.flush()

    with pytest.raises(IntegrityError):
        await session.execute(
            role_permissions.insert().values(
                role_id=role_id, permission_id=permission_id
            )
        )
        await session.flush()

    await session.rollback()


async def test_duplicate_user_role_is_rejected(session: AsyncSession) -> None:
    user_id, role_id = await _seed_user_and_role(session)

    await session.execute(user_roles.insert().values(user_id=user_id, role_id=role_id))
    await session.flush()

    with pytest.raises(IntegrityError):
        await session.execute(
            user_roles.insert().values(user_id=user_id, role_id=role_id)
        )
        await session.flush()

    await session.rollback()


async def test_association_rows_get_a_generated_id(session: AsyncSession) -> None:
    """The surrogate key is filled in by the database, like every other table."""
    user_id, role_id = await _seed_user_and_role(session)

    result = await session.execute(
        user_roles.insert()
        .values(user_id=user_id, role_id=role_id)
        .returning(user_roles.c.id)
    )
    assigned_id = result.scalar_one()

    assert isinstance(assigned_id, uuid.UUID)

    await session.rollback()


# -- Fixtures for the integrity checks ----------------------------------


async def _seed_pair(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """A throwaway role and permission, rolled back by the caller."""
    role_id = (
        await session.execute(
            text(
                "INSERT INTO roles (name, slug, level, is_system) "
                "VALUES ('Schema Probe', 'schema-probe', 1, false) RETURNING id"
            )
        )
    ).scalar_one()

    permission_id = (
        await session.execute(
            text(
                "INSERT INTO permissions (code, resource, action, name, is_system) "
                "VALUES ('probe.act', 'probe', 'act', 'Act probe', false) RETURNING id"
            )
        )
    ).scalar_one()

    return role_id, permission_id


async def _seed_user_and_role(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user_id = (
        await session.execute(
            text(
                "INSERT INTO users (email, first_name, status, language) "
                "VALUES ('probe@example.com', 'Probe', 'active', 'en') RETURNING id"
            )
        )
    ).scalar_one()

    role_id = (
        await session.execute(
            text(
                "INSERT INTO roles (name, slug, level, is_system) "
                "VALUES ('Schema Probe', 'schema-probe', 1, false) RETURNING id"
            )
        )
    ).scalar_one()

    return user_id, role_id
