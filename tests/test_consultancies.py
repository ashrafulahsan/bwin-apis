"""Tests for the consultancies module."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import PaginationParams
from app.core.exceptions import ConflictException
from app.modules.activity_logs.models.activity_log import ActivityLog, ActivityModule
from app.modules.consultancies.constants import ConsultancyStatus, ConsultancyType
from app.modules.consultancies.models.consultancy import Consultancy
from app.modules.consultancies.schemas.consultancy import (
    ConsultancyCreate,
    ConsultancyUpdate,
)
from app.modules.consultancies.services.consultancy import ConsultancyService
from app.modules.users.models.user import User


@pytest.fixture
async def consultancies(
    session: AsyncSession,
) -> AsyncIterator[ConsultancyService]:
    await session.execute(delete(Consultancy))
    await session.execute(delete(User))
    await session.commit()
    yield ConsultancyService(session)
    await session.execute(delete(Consultancy))
    await session.execute(delete(User))
    await session.commit()


def consultancy_payload(code: str = "CONS-101") -> ConsultancyCreate:
    return ConsultancyCreate(
        consultancy_code=code,
        title="Digital Transformation",
        description="Technology and process transformation advisory.",
        consultancy_type=ConsultancyType.CORPORATE,
        status=ConsultancyStatus.ACTIVE,
    )


async def test_consultancy_crud_and_activity(
    consultancies: ConsultancyService,
) -> None:
    created = await consultancies.create(consultancy_payload())
    assert created.slug == "digital-transformation"
    assert created.is_active is True

    activity = (
        (
            await consultancies.session.execute(
                select(ActivityLog).where(ActivityLog.entity_id == str(created.id))
            )
        )
        .scalars()
        .all()
    )
    assert activity[-1].module == ActivityModule.CONSULTANCIES
    assert activity[-1].entity_type == "Consultancy"

    updated = await consultancies.update(
        created.id,
        ConsultancyUpdate(title="Transformation Advisory"),
    )
    assert updated.title == "Transformation Advisory"

    await consultancies.delete(created.id)
    restored = await consultancies.restore(created.id)
    assert restored.deleted_at is None


async def test_consultancy_search_and_filters(
    consultancies: ConsultancyService,
) -> None:
    await consultancies.create(consultancy_payload())
    await consultancies.create(
        consultancy_payload("CONS-102").model_copy(
            update={
                "title": "Academic Research",
                "consultancy_type": ConsultancyType.ACADEMIC,
                "status": ConsultancyStatus.INACTIVE,
            }
        )
    )

    items, total = await consultancies.list_consultancies(
        PaginationParams(page=1, page_size=10),
        search="Academic",
        consultancy_type=ConsultancyType.ACADEMIC.value,
        status=ConsultancyStatus.INACTIVE,
    )
    assert total == 1
    assert items[0].title == "Academic Research"


async def test_consultancy_code_and_slug_are_unique(
    consultancies: ConsultancyService,
) -> None:
    await consultancies.create(consultancy_payload())

    with pytest.raises(ConflictException):
        await consultancies.create(
            consultancy_payload("CONS-102").model_copy(
                update={"slug": "digital-transformation"}
            )
        )

    with pytest.raises(ConflictException):
        await consultancies.create(consultancy_payload())
