"""Request and response schemas for consultancies."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from app.modules.consultancies.constants import (
    CONSULTANCY_CODE_MAX_LENGTH,
    CONSULTANCY_IMAGE_URL_MAX_LENGTH,
    CONSULTANCY_SLUG_MAX_LENGTH,
    CONSULTANCY_TITLE_MAX_LENGTH,
    ConsultancyStatus,
    ConsultancyType,
)
from app.shared.schemas.seo import SEOMetadata, SEOMetadataRead

if TYPE_CHECKING:
    from app.modules.consultancies.models.consultancy import Consultancy


class ConsultancyWriteBase(BaseModel):
    description: str | None = None
    consultancy_type: ConsultancyType = ConsultancyType.GENERAL
    category_id: uuid.UUID | None = None
    thumbnail: str | None = Field(
        default=None, max_length=CONSULTANCY_IMAGE_URL_MAX_LENGTH
    )
    promo_video_url: str | None = Field(
        default=None, max_length=CONSULTANCY_IMAGE_URL_MAX_LENGTH
    )
    sort_order: int = Field(default=0, ge=0)
    status: ConsultancyStatus = ConsultancyStatus.ACTIVE
    seo: SEOMetadata | None = None


class ConsultancyCreate(ConsultancyWriteBase):
    consultancy_code: str = Field(min_length=1, max_length=CONSULTANCY_CODE_MAX_LENGTH)
    title: str = Field(min_length=1, max_length=CONSULTANCY_TITLE_MAX_LENGTH)
    slug: str | None = Field(
        default=None, min_length=1, max_length=CONSULTANCY_SLUG_MAX_LENGTH
    )


class ConsultancyUpdate(BaseModel):
    consultancy_code: str | None = Field(
        default=None, min_length=1, max_length=CONSULTANCY_CODE_MAX_LENGTH
    )
    title: str | None = Field(
        default=None, min_length=1, max_length=CONSULTANCY_TITLE_MAX_LENGTH
    )
    slug: str | None = Field(
        default=None, min_length=1, max_length=CONSULTANCY_SLUG_MAX_LENGTH
    )
    description: str | None = None
    consultancy_type: ConsultancyType | None = None
    category_id: uuid.UUID | None = None
    thumbnail: str | None = Field(
        default=None, max_length=CONSULTANCY_IMAGE_URL_MAX_LENGTH
    )
    promo_video_url: str | None = Field(
        default=None, max_length=CONSULTANCY_IMAGE_URL_MAX_LENGTH
    )
    sort_order: int | None = Field(default=None, ge=0)
    status: ConsultancyStatus | None = None
    seo: SEOMetadata | None = None


class ConsultancySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    consultancy_code: str
    title: str
    slug: str
    consultancy_type: str
    category_id: uuid.UUID | None
    thumbnail: str | None
    sort_order: int
    status: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ConsultancyRead(ConsultancySummary):
    description: str
    promo_video_url: str | None
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None
    seo: SEOMetadataRead

    @classmethod
    def from_model(cls, consultancy: "Consultancy") -> "ConsultancyRead":
        summary = ConsultancySummary.model_validate(consultancy)
        return cls(
            **summary.model_dump(),
            description=consultancy.description,
            promo_video_url=consultancy.promo_video_url,
            created_by=consultancy.created_by,
            updated_by=consultancy.updated_by,
            seo=SEOMetadataRead.resolve(
                consultancy,
                title=consultancy.title,
                summary=consultancy.description,
                image_url=consultancy.thumbnail,
            ),
        )
