"""Tests for the automations module."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import PaginationParams
from app.core.exceptions import ConflictException
from app.modules.activity_logs.models.activity_log import ActivityLog, ActivityModule
from app.modules.automations.constants import AutomationStatus
from app.modules.automations.models.automation import Automation
from app.modules.automations.schemas.automation import (
    AutomationCreate,
    AutomationRead,
    AutomationUpdate,
)
from app.modules.automations.services.automation import AutomationService
from app.modules.users.models.user import User


@pytest.fixture
async def automations(session: AsyncSession) -> AsyncIterator[AutomationService]:
    await session.execute(delete(Automation))
    await session.execute(delete(User))
    await session.commit()

    yield AutomationService(session)

    await session.execute(delete(Automation))
    await session.execute(delete(User))
    await session.commit()


def automation_payload(title: str = "Invoice Reminders") -> AutomationCreate:
    return AutomationCreate(
        title=title,
        description="Chase unpaid invoices without anyone remembering to.",
        lists=["Detect overdue invoices", "Send a reminder", "Log the outcome"],
        image_url="/media/automations/invoice-reminders.png",
        video_url="https://videos.example.com/invoice-reminders.mp4",
    )


async def test_automation_lifecycle(automations: AutomationService) -> None:
    created = await automations.create(automation_payload())

    assert created.status == AutomationStatus.DRAFT
    assert created.slug == "invoice-reminders"
    assert created.published_at is None
    assert created.lists == [
        "Detect overdue invoices",
        "Send a reminder",
        "Log the outcome",
    ]

    activity = (
        (
            await automations.session.execute(
                select(ActivityLog).where(ActivityLog.entity_id == str(created.id))
            )
        )
        .scalars()
        .all()
    )
    assert activity[-1].module == ActivityModule.AUTOMATIONS
    assert activity[-1].entity_type == "Automation"

    updated = await automations.update(
        created.id, AutomationUpdate(title="Invoice Chasing")
    )
    assert updated.title == "Invoice Chasing"

    published = await automations.publish(created.id, published_at=datetime.now(UTC))
    assert published.status == AutomationStatus.PUBLISHED
    assert published.is_live is True

    draft = await automations.unpublish(created.id)
    assert draft.status == AutomationStatus.DRAFT
    # The date survives, so republishing does not present an old entry as new.
    assert draft.published_at is not None

    archived = await automations.archive(created.id)
    assert archived.status == AutomationStatus.ARCHIVED

    await automations.delete(created.id)
    restored = await automations.restore(created.id)
    assert restored.deleted_at is None


async def test_a_scheduled_automation_is_published_but_not_live(
    automations: AutomationService,
) -> None:
    created = await automations.create(automation_payload())

    scheduled = await automations.publish(
        created.id, published_at=datetime.now(UTC) + timedelta(days=1)
    )

    assert scheduled.is_published is True
    assert scheduled.is_live is False
    assert scheduled.is_scheduled is True


async def test_search_and_filters(automations: AutomationService) -> None:
    await automations.create(automation_payload())
    second = await automations.create(automation_payload("Lead Routing"))
    await automations.publish(second.id, published_at=datetime.now(UTC))

    items, total = await automations.list_automations(
        PaginationParams(page=1, page_size=10), search="Lead"
    )
    assert total == 1
    assert items[0].title == "Lead Routing"

    _, drafts = await automations.list_automations(
        PaginationParams(page=1, page_size=10), status=AutomationStatus.DRAFT
    )
    assert drafts == 1

    live, live_total = await automations.list_automations(
        PaginationParams(page=1, page_size=10), live_only=True
    )
    assert live_total == 1
    assert live[0].id == second.id


async def test_slugs_are_unique(automations: AutomationService) -> None:
    await automations.create(automation_payload())

    with pytest.raises(ConflictException):
        await automations.create(
            automation_payload("Something Else").model_copy(
                update={"slug": "invoice-reminders"}
            )
        )

    # A derived slug collides quietly, with a suffix.
    duplicate = await automations.create(automation_payload())
    assert duplicate.slug == "invoice-reminders-2"


async def test_a_published_automation_cannot_change_its_address(
    automations: AutomationService,
) -> None:
    created = await automations.create(automation_payload())
    await automations.publish(created.id)

    with pytest.raises(ConflictException):
        await automations.update(created.id, AutomationUpdate(slug="new-address"))


async def test_publishing_twice_is_refused(automations: AutomationService) -> None:
    created = await automations.create(automation_payload())
    await automations.publish(created.id)

    with pytest.raises(ConflictException):
        await automations.publish(created.id)


async def test_seo_metadata_falls_back_to_the_automation(
    automations: AutomationService,
) -> None:
    created = await automations.create(automation_payload())

    resolved = AutomationRead.from_model(created).seo

    assert resolved.meta_title == created.title
    assert resolved.og_title == created.title
    assert resolved.og_image_url == created.image_url
    assert resolved.is_indexable is True
