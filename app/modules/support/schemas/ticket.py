"""Request and response schemas for support tickets."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.support.constants import (
    FEEDBACK_MAX_RATING,
    FEEDBACK_MIN_RATING,
    TICKET_REASON_MAX_LENGTH,
    TICKET_REMARKS_MAX_LENGTH,
    TICKET_SUBJECT_MAX_LENGTH,
    TicketPriority,
    TicketSource,
    TicketStatus,
)

if TYPE_CHECKING:
    from app.modules.support.models.support_ticket import SupportTicket


class UserBrief(BaseModel):
    """Just enough of a person to render a row without a second request."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str


class CategoryBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str


# -- Writes ---------------------------------------------------------------


class TicketCreate(BaseModel):
    """What a student sends to raise a ticket.

    Neither `status` nor `priority` is accepted here. A ticket always starts
    open and medium; letting the caller pick would make "urgent" a
    self-service label and the queue meaningless.
    """

    subject: str = Field(min_length=1, max_length=TICKET_SUBJECT_MAX_LENGTH)
    description: str = Field(min_length=1)
    category_id: uuid.UUID | None = Field(
        default=None, description="A category from the `support_ticket` taxonomy."
    )
    source: TicketSource = Field(
        default=TicketSource.WEB, description="Where the ticket was raised from."
    )


class AdminTicketCreate(TicketCreate):
    """An agent filing a ticket on a student's behalf.

    Adds the two fields the student-facing form withholds, because an agent
    triaging a phone call legitimately knows the priority.
    """

    student_id: uuid.UUID = Field(description="Who the ticket is being raised for.")
    priority: TicketPriority = TicketPriority.MEDIUM
    assigned_to: uuid.UUID | None = None


class TicketUpdate(BaseModel):
    """Editing the ticket's own text. Workflow moves have their own routes."""

    subject: str | None = Field(
        default=None, min_length=1, max_length=TICKET_SUBJECT_MAX_LENGTH
    )
    description: str | None = Field(default=None, min_length=1)
    category_id: uuid.UUID | None = None


class TicketAssign(BaseModel):
    assigned_to: uuid.UUID | None = Field(
        description="The new owner, or null to return the ticket to the pool."
    )
    reason: str | None = Field(default=None, max_length=TICKET_REASON_MAX_LENGTH)


class TicketStatusChange(BaseModel):
    status: TicketStatus
    remarks: str | None = Field(default=None, max_length=TICKET_REMARKS_MAX_LENGTH)


class TicketPriorityChange(BaseModel):
    priority: TicketPriority
    reason: str | None = Field(default=None, max_length=TICKET_REASON_MAX_LENGTH)


class TicketCategoryChange(BaseModel):
    category_id: uuid.UUID | None
    reason: str | None = Field(default=None, max_length=TICKET_REASON_MAX_LENGTH)


class TicketEscalate(BaseModel):
    reason: str = Field(
        min_length=1,
        description="Why this needs attention above the assigned agent.",
    )
    assigned_to: uuid.UUID | None = Field(
        default=None, description="Optionally hand it to someone at the same time."
    )


class TicketClose(BaseModel):
    remarks: str | None = Field(default=None, max_length=TICKET_REMARKS_MAX_LENGTH)


class TicketReopen(BaseModel):
    reason: str | None = Field(default=None, max_length=TICKET_REASON_MAX_LENGTH)


class TicketMerge(BaseModel):
    """Fold this ticket into another. The target survives."""

    target_ticket_id: uuid.UUID = Field(
        description="The ticket that absorbs this one's conversation."
    )
    reason: str | None = Field(default=None, max_length=TICKET_REASON_MAX_LENGTH)


class FeedbackCreate(BaseModel):
    rating: int = Field(ge=FEEDBACK_MIN_RATING, le=FEEDBACK_MAX_RATING)
    feedback: str | None = None


# -- Reads ----------------------------------------------------------------


class TicketSummary(BaseModel):
    """One row in a queue listing."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_no: str
    subject: str
    category_id: uuid.UUID | None
    student_id: uuid.UUID
    assigned_to: uuid.UUID | None
    priority: str
    status: str
    source: str
    is_escalated: bool
    total_replies: int
    attachment_count: int
    satisfaction_rating: int | None
    last_reply_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TicketRead(TicketSummary):
    """A ticket opened on its own page."""

    description: str
    first_response_at: datetime | None
    escalated_at: datetime | None
    escalated_by: uuid.UUID | None
    escalation_reason: str | None
    satisfaction_comment: str | None
    merged_into_id: uuid.UUID | None
    merged_at: datetime | None
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None

    category: CategoryBrief | None = None
    student: UserBrief | None = None
    assignee: UserBrief | None = None

    @classmethod
    def from_model(cls, ticket: "SupportTicket") -> "TicketRead":
        summary = TicketSummary.model_validate(ticket)
        return cls(
            **summary.model_dump(),
            description=ticket.description,
            first_response_at=ticket.first_response_at,
            escalated_at=ticket.escalated_at,
            escalated_by=ticket.escalated_by,
            escalation_reason=ticket.escalation_reason,
            satisfaction_comment=ticket.satisfaction_comment,
            merged_into_id=ticket.merged_into_id,
            merged_at=ticket.merged_at,
            created_by=ticket.created_by,
            updated_by=ticket.updated_by,
            category=(
                CategoryBrief.model_validate(ticket.category)
                if ticket.category is not None
                else None
            ),
            student=(
                UserBrief.model_validate(ticket.student)
                if ticket.student is not None
                else None
            ),
            assignee=(
                UserBrief.model_validate(ticket.assignee)
                if ticket.assignee is not None
                else None
            ),
        )


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    user_id: uuid.UUID | None
    message: str
    is_internal_note: bool
    is_system_message: bool
    created_at: datetime
    updated_at: datetime
    author: UserBrief | None = None


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    message_id: uuid.UUID | None
    original_name: str
    file_size: int
    mime_type: str | None
    uploaded_by: uuid.UUID | None
    created_at: datetime

    # `file_path` and `file_name` are deliberately absent: they describe
    # where the file sits on the server, and a client has no use for that
    # beyond constructing a path we would then have to defend.


class AssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    assigned_from: uuid.UUID | None
    assigned_to: uuid.UUID | None
    reason: str | None
    created_by: uuid.UUID | None
    created_at: datetime


class StatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    old_status: str | None
    new_status: str
    changed_by: uuid.UUID | None
    remarks: str | None
    created_at: datetime


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    user_id: uuid.UUID | None
    activity_type: str
    activity_description: str
    metadata: dict[str, Any] | None = Field(
        default=None,
        validation_alias="activity_metadata",
        serialization_alias="metadata",
    )
    created_at: datetime


class FeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    rating: int
    feedback: str | None
    submitted_by: uuid.UUID | None
    created_at: datetime


class TicketDetail(BaseModel):
    """Everything one ticket page needs, in a single response.

    Assembled server side because the alternative is five round trips to
    render one screen, and because the internal-note filter has to be applied
    identically to the thread and the timeline.
    """

    ticket: TicketRead
    messages: list[MessageRead] = Field(default_factory=list)
    attachments: list[AttachmentRead] = Field(default_factory=list)
    activities: list[ActivityRead] = Field(default_factory=list)
    status_history: list[StatusHistoryRead] = Field(default_factory=list)
    assignments: list[AssignmentRead] = Field(default_factory=list)
    feedback: FeedbackRead | None = None
