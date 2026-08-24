"""Request and response schemas for contact inquiries.

Validation lives here rather than in the service because these are shape
rules - is this a well-formed email, is this one of the four options - and
FastAPI turns a failure into a 422 naming the offending field. The service
keeps the rules that need the database.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    computed_field,
    field_validator,
)

from app.modules.inquiries.constants import (
    INQUIRY_EMAIL_MAX_LENGTH,
    INQUIRY_NAME_MAX_LENGTH,
    INQUIRY_PHONE_MAX_LENGTH,
    InquiryStatus,
    InterestedIn,
)
from app.modules.users.constants import normalize_email, normalize_phone

if TYPE_CHECKING:
    from app.modules.inquiries.models.contact_inquiry import ContactInquiry


class InquiryCreate(BaseModel):
    """What the public contact form posts.

    `status`, `notes`, `ip_address` and `is_read` are all absent on purpose:
    they are ours to set. Accepting them here would let anyone with the
    endpoint file an inquiry already marked converted, or write an internal
    note.

    Trimming comes from `str_strip_whitespace` in `model_config`, which is
    what actually does it in Pydantic v2 - `Field(strip_whitespace=True)`
    looks like it would and is silently ignored. Length constraints are
    still checked before the trim, so a field of nothing but spaces passes
    `min_length` and needs the explicit validator below.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "full_name": "John Doe",
                "email": "john@example.com",
                "phone": "+8801712345678",
                "interested_in": "consultancy",
                "message": "Need consultancy support.",
            }
        },
    )

    full_name: str = Field(
        min_length=1,
        max_length=INQUIRY_NAME_MAX_LENGTH,
        description="The visitor's name, as they typed it.",
    )
    email: EmailStr = Field(
        max_length=INQUIRY_EMAIL_MAX_LENGTH,
        description="Validated for format, then lowercased.",
    )
    phone: str = Field(
        min_length=1,
        max_length=INQUIRY_PHONE_MAX_LENGTH,
        description=(
            "Normalized to E.164. A local Bangladeshi number such as "
            "`01712-345678` is stored as `+8801712345678`."
        ),
    )
    interested_in: InterestedIn = Field(
        description="One of the four options on the form."
    )
    message: str | None = Field(
        default=None, description="Optional. Blank is stored as null, not as ''."
    )

    @field_validator("full_name")
    @classmethod
    def _reject_blank_name(cls, value: str) -> str:
        # `min_length` runs before stripping, so a field of spaces would pass
        # it and arrive here empty.
        if not value.strip():
            raise ValueError("Full name cannot be blank.")
        return value.strip()

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("phone")
    @classmethod
    def _normalize_phone(cls, value: str) -> str:
        """Normalize, turning an unusable number into a field-level 422.

        `normalize_phone` raises `ValueError`, which Pydantic renders against
        the `phone` field - so the caller is told which input was wrong
        rather than being handed a generic bad request.
        """
        try:
            return normalize_phone(value)
        except ValueError as error:
            raise ValueError(str(error)) from error

    @field_validator("message")
    @classmethod
    def _blank_message_is_absent(cls, value: str | None) -> str | None:
        """An empty box is "they did not write a message", not an empty one."""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class InquiryStatusUpdate(BaseModel):
    """An administrator moving an inquiry along."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "status": "contacted",
                "notes": "Client contacted via phone.",
            }
        },
    )

    status: InquiryStatus = Field(description="The new handling state.")
    notes: str | None = Field(
        default=None,
        description=(
            "Internal note, replacing whatever is there. Omit the field to "
            "leave the existing note alone; send null to clear it."
        ),
    )


class InquiryUpdate(BaseModel):
    """Editing an inquiry's own details, for a correction after a phone call."""

    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str | None = Field(
        default=None, min_length=1, max_length=INQUIRY_NAME_MAX_LENGTH
    )
    email: EmailStr | None = Field(default=None, max_length=INQUIRY_EMAIL_MAX_LENGTH)
    phone: str | None = Field(
        default=None, min_length=1, max_length=INQUIRY_PHONE_MAX_LENGTH
    )
    interested_in: InterestedIn | None = None
    message: str | None = None
    notes: str | None = None

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str | None) -> str | None:
        return normalize_email(value) if value else None

    @field_validator("phone")
    @classmethod
    def _normalize_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return normalize_phone(value)
        except ValueError as error:
            raise ValueError(str(error)) from error


class InquirySummary(BaseModel):
    """One row in the admin listing.

    `notes` is not here. A listing is the screen most likely to be shown on a
    shared display, and an internal note about a named person does not belong
    on one.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str
    phone: str
    interested_in: str
    status: str
    is_read: bool
    read_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def interest_label(self) -> str:
        """The form wording, so a client does not re-derive it."""
        from app.modules.inquiries.constants import INTEREST_LABELS

        try:
            return INTEREST_LABELS[InterestedIn(self.interested_in)]
        except ValueError:
            return self.interested_in.replace("_", " ").title()


class InquiryRead(InquirySummary):
    """One inquiry opened on its own page."""

    message: str | None
    notes: str | None
    ip_address: str | None
    user_agent: str | None
    read_by: uuid.UUID | None
    updated_by: uuid.UUID | None
    deleted_at: datetime | None

    @classmethod
    def from_model(cls, inquiry: "ContactInquiry") -> "InquiryRead":
        return cls.model_validate(inquiry)


class InquiryStatistics(BaseModel):
    """Counts for the inquiries dashboard."""

    total: int
    unread: int
    open: int = Field(description="Not converted, closed or marked spam.")
    by_status: dict[str, int] = Field(default_factory=dict)
    by_interest: dict[str, int] = Field(default_factory=dict)
