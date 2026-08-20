"""Request and response schemas for extended user details."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class UserDetailsFields(BaseModel):
    gender: str | None = Field(default=None, max_length=50)
    date_of_birth: date | None = None
    nationality: str | None = Field(default=None, max_length=100)
    address: str | None = None
    city: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    emergency_contact_name: str | None = Field(default=None, max_length=255)
    emergency_contact_phone: str | None = Field(default=None, max_length=50)
    photo_id: uuid.UUID | None = None
    reporting_to: uuid.UUID | None = None
    designation: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    organization: str | None = Field(default=None, max_length=255)
    years_of_experience: int | None = Field(default=None, ge=0)
    highest_degree: str | None = Field(default=None, max_length=255)
    university: str | None = Field(default=None, max_length=255)
    graduation_year: int | None = Field(default=None, ge=1)
    linkedin_url: str | None = Field(default=None, max_length=500)
    youtube_url: str | None = Field(default=None, max_length=500)
    facebook_url: str | None = Field(default=None, max_length=500)
    website_url: str | None = Field(default=None, max_length=500)
    notes: str | None = None


class UserDetailsCreate(UserDetailsFields):
    pass


class UserDetailsUpdate(UserDetailsFields):
    pass


class UserDetailsRead(UserDetailsFields):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
