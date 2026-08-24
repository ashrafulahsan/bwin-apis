"""Schemas for writing into a ticket's conversation."""

from pydantic import BaseModel, Field


class MessageCreate(BaseModel):
    """A reply, from a student or from staff."""

    message: str = Field(min_length=1, description="The reply body.")


class InternalNoteCreate(BaseModel):
    """A note staff leave for each other on a ticket.

    A separate schema from `MessageCreate` rather than a boolean flag on it:
    a flag would mean one route where passing `is_internal_note=true` decides
    whether the student sees the text, and a client bug there is a
    confidentiality breach. Two routes means the private one carries its own
    permission.
    """

    message: str = Field(min_length=1, description="Visible to staff only.")
