"""Tests for extended user details."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException, NotFoundException
from app.modules.users.models.user import User
from app.modules.users.models.user_details import UserDetails
from app.modules.users.schemas.user_details import (
    UserDetailsCreate,
    UserDetailsUpdate,
)
from app.modules.users.services.user_details import UserDetailsService


@pytest.fixture
async def details_service(session: AsyncSession) -> AsyncIterator[UserDetailsService]:
    await session.execute(delete(UserDetails))
    await session.execute(delete(User))
    await session.commit()

    user = User(email="details@example.com", first_name="Details")
    session.add(user)
    await session.flush()

    yield UserDetailsService(session)

    await session.execute(delete(UserDetails))
    await session.execute(delete(User))
    await session.commit()


async def test_user_details_crud(
    details_service: UserDetailsService,
) -> None:
    user_id = (await details_service.users.get_by_email("details@example.com")).id
    created = await details_service.create(
        user_id,
        UserDetailsCreate(
            designation="Instructor",
            department="Learning",
            years_of_experience=5,
        ),
    )

    assert created.user_id == user_id
    assert (await details_service.get(user_id)).designation == "Instructor"

    updated = await details_service.update(
        user_id, UserDetailsUpdate(designation="Senior Instructor")
    )
    assert updated.designation == "Senior Instructor"

    await details_service.delete(user_id)
    with pytest.raises(NotFoundException):
        await details_service.get(user_id)


async def test_user_details_are_one_to_one(
    details_service: UserDetailsService,
) -> None:
    user = await details_service.users.get_by_email("details@example.com")
    payload = UserDetailsCreate(city="Dhaka")

    await details_service.create(user.id, payload)

    with pytest.raises(ConflictException):
        await details_service.create(user.id, payload)


async def test_user_details_require_an_existing_user(
    details_service: UserDetailsService,
) -> None:
    import uuid

    with pytest.raises(NotFoundException):
        await details_service.create(uuid.uuid4(), UserDetailsCreate())
