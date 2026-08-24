"""Dashboard and reporting schemas."""

import uuid

from pydantic import BaseModel, Field


class CountByKey(BaseModel):
    """A labelled tally, used for the by-category and by-priority breakdowns."""

    key: str = Field(description="Machine readable grouping value.")
    label: str = Field(description="Human readable name for the same group.")
    count: int


class CategoryCount(CountByKey):
    category_id: uuid.UUID | None = Field(
        default=None, description="Null for tickets filed under no category."
    )


class TicketStatistics(BaseModel):
    """The support dashboard, in one payload.

    Durations are reported in seconds and again in hours. Seconds are the
    honest unit and what a client should compute with; hours are what a
    dashboard displays, and rounding once here beats every consumer rounding
    differently.
    """

    total_tickets: int
    open_tickets: int = Field(description="Everything not resolved or closed.")
    in_progress_tickets: int
    resolved_tickets: int
    closed_tickets: int
    escalated_tickets: int
    unassigned_tickets: int = Field(
        description="Open tickets with no owner - the backlog to triage."
    )
    reopened_tickets: int

    average_response_seconds: float | None = Field(
        default=None, description="Null until at least one ticket has been answered."
    )
    average_response_hours: float | None = None
    average_resolution_seconds: float | None = None
    average_resolution_hours: float | None = None
    average_satisfaction: float | None = Field(
        default=None, description="Mean rating out of 5, over tickets that were rated."
    )

    by_status: dict[str, int] = Field(default_factory=dict)
    by_priority: list[CountByKey] = Field(default_factory=list)
    by_category: list[CategoryCount] = Field(default_factory=list)
