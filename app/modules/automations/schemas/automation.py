"""Request and response schemas for automations."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, Field

from app.modules.automations.constants import (
    AUTOMATION_IMAGE_URL_MAX_LENGTH,
    AUTOMATION_SLUG_MAX_LENGTH,
    AUTOMATION_TITLE_MAX_LENGTH,
)
from app.shared.schemas.seo import SEOMetadata, SEOMetadataRead

if TYPE_CHECKING:
    from app.modules.automations.models.automation import Automation


class AutomationWriteBase(BaseModel):
    description: str | None = None
    lists: list | None = None
    category_id: uuid.UUID | None = None
    image_url: str | None = Field(
        default=None, max_length=AUTOMATION_IMAGE_URL_MAX_LENGTH
    )
    video_url: str | None = Field(
        default=None, max_length=AUTOMATION_IMAGE_URL_MAX_LENGTH
    )
    seo: SEOMetadata | None = None


class AutomationCreate(AutomationWriteBase):
    title: str = Field(min_length=1, max_length=AUTOMATION_TITLE_MAX_LENGTH)
    slug: str | None = Field(
        default=None, min_length=1, max_length=AUTOMATION_SLUG_MAX_LENGTH
    )


class AutomationUpdate(AutomationWriteBase):
    title: str | None = Field(
        default=None, min_length=1, max_length=AUTOMATION_TITLE_MAX_LENGTH
    )
    slug: str | None = Field(
        default=None, min_length=1, max_length=AUTOMATION_SLUG_MAX_LENGTH
    )


class AutomationPublish(BaseModel):
    published_at: datetime | None = None


class AutomationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    slug: str
    category_id: uuid.UUID | None
    image_url: str | None
    status: str
    is_live: bool
    is_scheduled: bool
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AutomationRead(AutomationSummary):
    description: str | None
    lists: list | None
    video_url: str | None
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None
    seo: SEOMetadataRead

    @classmethod
    def from_model(cls, automation: "Automation") -> Self:
        listed = AutomationSummary.model_validate(automation)
        return cls(
            **listed.model_dump(),
            description=automation.description,
            lists=automation.lists,
            video_url=automation.video_url,
            created_by=automation.created_by,
            updated_by=automation.updated_by,
            seo=SEOMetadataRead.resolve(
                automation,
                title=automation.title,
                summary=automation.description,
                image_url=automation.image_url,
            ),
        )
