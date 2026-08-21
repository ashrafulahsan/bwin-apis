"""Request and response schemas for courses."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, Field

from app.modules.courses.constants import (
    COURSE_CODE_MAX_LENGTH,
    COURSE_IMAGE_URL_MAX_LENGTH,
    COURSE_SLUG_MAX_LENGTH,
    COURSE_TITLE_MAX_LENGTH,
    CourseLanguage,
    CourseLevel,
    CourseVisibility,
)
from app.shared.schemas.seo import SEOMetadata, SEOMetadataRead

if TYPE_CHECKING:
    from app.modules.courses.models.course import Course


class CourseWriteBase(BaseModel):
    short_description: str | None = None
    learning_outcomes: list | None = None
    requirements: list | None = None
    target_audience: list | None = None
    category_id: uuid.UUID | None = None
    level: CourseLevel = CourseLevel.BEGINNER
    language: CourseLanguage = CourseLanguage.ENGLISH
    course_type: uuid.UUID | None = None
    delivery_mode: uuid.UUID | None = None
    thumbnail: str | None = Field(default=None, max_length=COURSE_IMAGE_URL_MAX_LENGTH)
    cover_image: str | None = Field(
        default=None, max_length=COURSE_IMAGE_URL_MAX_LENGTH
    )
    promo_video_url: str | None = Field(
        default=None, max_length=COURSE_IMAGE_URL_MAX_LENGTH
    )
    intro_video_url: str | None = Field(
        default=None, max_length=COURSE_IMAGE_URL_MAX_LENGTH
    )
    duration_hours: int = Field(default=0, ge=0)
    duration_minutes: int = Field(default=0, ge=0, le=59)
    total_modules: int = Field(default=0, ge=0)
    total_lessons: int = Field(default=0, ge=0)
    total_quizzes: int = Field(default=0, ge=0)
    total_assignments: int = Field(default=0, ge=0)
    total_resources: int = Field(default=0, ge=0)
    passing_score: int = Field(default=0, ge=0, le=100)
    certificate_enabled: bool = False
    certificate_template_id: uuid.UUID | None = None
    max_attempts: int | None = Field(default=None, ge=1)
    seat_limit: int | None = Field(default=None, ge=1)
    price: Decimal = Field(default=Decimal("0.00"), ge=0)
    discount_price: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    enrollment_start_date: datetime | None = None
    enrollment_end_date: datetime | None = None
    course_start_date: datetime | None = None
    course_end_date: datetime | None = None
    visibility: CourseVisibility = CourseVisibility.PUBLIC
    featured: bool = False
    allow_reviews: bool = True
    allow_discussion: bool = True
    sort_order: int = 0
    seo: SEOMetadata | None = None


class CourseCreate(CourseWriteBase):
    course_code: str = Field(min_length=1, max_length=COURSE_CODE_MAX_LENGTH)
    title: str = Field(min_length=1, max_length=COURSE_TITLE_MAX_LENGTH)
    slug: str | None = Field(
        default=None, min_length=1, max_length=COURSE_SLUG_MAX_LENGTH
    )
    description: str = Field(min_length=1)


class CourseUpdate(CourseWriteBase):
    course_code: str | None = Field(
        default=None, min_length=1, max_length=COURSE_CODE_MAX_LENGTH
    )
    title: str | None = Field(
        default=None, min_length=1, max_length=COURSE_TITLE_MAX_LENGTH
    )
    slug: str | None = Field(
        default=None, min_length=1, max_length=COURSE_SLUG_MAX_LENGTH
    )
    description: str | None = Field(default=None, min_length=1)


class CoursePublish(BaseModel):
    published_at: datetime | None = None


class CourseSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_code: str
    title: str
    slug: str
    short_description: str | None
    thumbnail: str | None
    level: str
    language: str
    status: str
    visibility: str
    featured: bool
    is_live: bool
    is_scheduled: bool
    price: Decimal
    discount_price: Decimal | None
    currency: str
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CourseRead(CourseSummary):
    description: str
    learning_outcomes: list | None
    requirements: list | None
    target_audience: list | None
    category_id: uuid.UUID | None
    course_type: uuid.UUID | None
    delivery_mode: uuid.UUID | None
    cover_image: str | None
    promo_video_url: str | None
    intro_video_url: str | None
    duration_hours: int
    duration_minutes: int
    total_modules: int
    total_lessons: int
    total_quizzes: int
    total_assignments: int
    total_resources: int
    passing_score: int
    certificate_enabled: bool
    certificate_template_id: uuid.UUID | None
    max_attempts: int | None
    seat_limit: int | None
    enrollment_start_date: datetime | None
    enrollment_end_date: datetime | None
    course_start_date: datetime | None
    course_end_date: datetime | None
    allow_reviews: bool
    allow_discussion: bool
    sort_order: int
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None
    seo: SEOMetadataRead

    @classmethod
    def from_model(cls, course: "Course") -> Self:
        listed = CourseSummary.model_validate(course)
        return cls(
            **listed.model_dump(),
            description=course.description,
            learning_outcomes=course.learning_outcomes,
            requirements=course.requirements,
            target_audience=course.target_audience,
            category_id=course.category_id,
            course_type=course.course_type,
            delivery_mode=course.delivery_mode,
            cover_image=course.cover_image,
            promo_video_url=course.promo_video_url,
            intro_video_url=course.intro_video_url,
            duration_hours=course.duration_hours,
            duration_minutes=course.duration_minutes,
            total_modules=course.total_modules,
            total_lessons=course.total_lessons,
            total_quizzes=course.total_quizzes,
            total_assignments=course.total_assignments,
            total_resources=course.total_resources,
            passing_score=course.passing_score,
            certificate_enabled=course.certificate_enabled,
            certificate_template_id=course.certificate_template_id,
            max_attempts=course.max_attempts,
            seat_limit=course.seat_limit,
            enrollment_start_date=course.enrollment_start_date,
            enrollment_end_date=course.enrollment_end_date,
            course_start_date=course.course_start_date,
            course_end_date=course.course_end_date,
            allow_reviews=course.allow_reviews,
            allow_discussion=course.allow_discussion,
            sort_order=course.sort_order,
            created_by=course.created_by,
            updated_by=course.updated_by,
            seo=SEOMetadataRead.resolve(
                course,
                title=course.title,
                summary=course.short_description,
                image_url=course.cover_image,
            ),
        )
