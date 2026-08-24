"""Request and response schemas for notifications."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.notifications.constants import (
    NOTIFICATION_ICON_MAX_LENGTH,
    NOTIFICATION_IMAGE_URL_MAX_LENGTH,
    NOTIFICATION_TITLE_MAX_LENGTH,
    TARGETED_DELIVERY_TYPES,
    DeliveryType,
    NotificationPriority,
)

if TYPE_CHECKING:
    from app.modules.notifications.models.notification import Notification
    from app.modules.notifications.models.notification_recipient import (
        NotificationRecipient,
    )


class NotificationCreate(BaseModel):
    """An administrator announcing something.

    `notification_type` is not accepted. Everything created through the admin
    API is an `admin` notification by definition; a `system` one records that
    the platform did something, and letting a person file one by hand would
    make the distinction meaningless.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "title": "New PMP Batch",
                "short_message": "Registration is now open",
                "details_content": "<p>Details here...</p>",
                "delivery_type": "course",
                "target_ids": [
                    "8f1d6c2a-4b3e-4f5a-9c7d-1e2f3a4b5c6d",
                    "9a2e7d3b-5c4f-4a6b-8d9e-2f3a4b5c6d7e",
                ],
                "priority": "high",
                "publish_at": None,
                "expires_at": None,
            }
        },
    )

    title: str = Field(min_length=1, max_length=NOTIFICATION_TITLE_MAX_LENGTH)
    short_message: str = Field(
        min_length=1, description="The line shown in the notification list."
    )
    details_content: str = Field(
        min_length=1, description="The body of the details page. May be HTML."
    )

    delivery_type: DeliveryType = Field(description="How the audience is chosen.")
    target_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description=(
            "Role, course or user identifiers, according to "
            "`delivery_type`. Must be empty for `global`."
        ),
    )

    priority: NotificationPriority = NotificationPriority.NORMAL
    icon: str | None = Field(default=None, max_length=NOTIFICATION_ICON_MAX_LENGTH)
    image_url: str | None = Field(
        default=None, max_length=NOTIFICATION_IMAGE_URL_MAX_LENGTH
    )
    has_details_page: bool = True
    is_active: bool = True

    publish_at: datetime | None = Field(
        default=None, description="Leave null to publish immediately."
    )
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _check_targets(self) -> "NotificationCreate":
        """Targets must match the delivery type, and dates must be in order.

        A targeted delivery with no targets would reach nobody while
        reporting success, which is the worst thing a notification system can
        do. Targets on a global one are a sign the caller meant something
        else, so they are refused rather than ignored.
        """
        if self.delivery_type in TARGETED_DELIVERY_TYPES and not self.target_ids:
            raise ValueError(
                f"'{self.delivery_type.value}' delivery needs at least one "
                "entry in target_ids."
            )
        if self.delivery_type is DeliveryType.GLOBAL and self.target_ids:
            raise ValueError("'global' delivery reaches everyone and takes no targets.")

        if (
            self.publish_at is not None
            and self.expires_at is not None
            and self.expires_at <= self.publish_at
        ):
            raise ValueError("expires_at must be after publish_at.")

        return self


class NotificationUpdate(BaseModel):
    """Editing an announcement before it goes out.

    Refused once the notification is published - see the service. Changing
    the wording of something people have already read would leave them
    remembering a different notice from the one on file.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(
        default=None, min_length=1, max_length=NOTIFICATION_TITLE_MAX_LENGTH
    )
    short_message: str | None = Field(default=None, min_length=1)
    details_content: str | None = Field(default=None, min_length=1)
    delivery_type: DeliveryType | None = None
    target_ids: list[uuid.UUID] | None = Field(
        default=None,
        description="Replaces the audience. The recipient list is rebuilt.",
    )
    priority: NotificationPriority | None = None
    icon: str | None = Field(default=None, max_length=NOTIFICATION_ICON_MAX_LENGTH)
    image_url: str | None = Field(
        default=None, max_length=NOTIFICATION_IMAGE_URL_MAX_LENGTH
    )
    has_details_page: bool | None = None
    is_active: bool | None = None
    publish_at: datetime | None = None
    expires_at: datetime | None = None


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str


class NotificationSummary(BaseModel):
    """One row in the administrative listing."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    short_message: str
    notification_type: str
    delivery_type: str
    priority: str
    icon: str | None
    image_url: str | None
    has_details_page: bool
    is_active: bool
    publish_at: datetime | None
    expires_at: datetime | None
    total_recipients: int
    total_reads: int
    total_detail_views: int
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class NotificationRead(NotificationSummary):
    """One notification, with its body and its engagement figures."""

    details_content: str
    target_ids: list[uuid.UUID] | None
    updated_by: uuid.UUID | None
    read_percentage: float = Field(
        description="Share of recipients who have read it, 0 when none exist."
    )
    is_published: bool
    is_scheduled: bool
    is_expired: bool
    author: UserBrief | None = None

    @classmethod
    def from_model(cls, notification: "Notification") -> "NotificationRead":
        summary = NotificationSummary.model_validate(notification)
        return cls(
            **summary.model_dump(),
            details_content=notification.details_content,
            target_ids=notification.target_ids,
            updated_by=notification.updated_by,
            read_percentage=notification.read_percentage,
            is_published=notification.is_published,
            is_scheduled=notification.is_scheduled,
            is_expired=notification.is_expired,
            author=(
                UserBrief.model_validate(notification.author)
                if notification.author is not None
                else None
            ),
        )


class NotificationStatistics(BaseModel):
    """The engagement panel on the notification details page."""

    total_recipients: int
    total_reads: int
    total_unread: int
    total_detail_views: int
    unique_detail_viewers: int
    total_archived: int
    read_percentage: float
    detail_view_percentage: float = Field(
        description="Share of recipients who opened the details page."
    )


class NotificationDetail(BaseModel):
    """What the administrative details page renders."""

    notification: NotificationRead
    statistics: NotificationStatistics


# -- The recipient's own view ---------------------------------------------


class MyNotification(BaseModel):
    """One notification as its recipient sees it.

    Flattened deliberately: a client rendering a notification list wants one
    object per row, not a notification nested inside a delivery record. The
    identifier is the notification's, because that is what every user-facing
    route takes.
    """

    id: uuid.UUID = Field(description="The notification's identifier.")
    title: str
    short_message: str
    notification_type: str
    priority: str
    icon: str | None
    image_url: str | None
    has_details_page: bool
    publish_at: datetime | None
    expires_at: datetime | None

    is_read: bool
    read_at: datetime | None
    read_count: int
    details_viewed: bool
    details_view_count: int
    details_viewed_at: datetime | None
    last_viewed_at: datetime | None
    is_archived: bool
    archived_at: datetime | None
    delivered_at: datetime
    received_at: datetime = Field(
        description="When this reached the recipient - the row's creation."
    )

    @classmethod
    def from_recipient(cls, recipient: "NotificationRecipient") -> "MyNotification":
        notification = recipient.notification
        return cls(
            id=notification.id,
            title=notification.title,
            short_message=notification.short_message,
            notification_type=notification.notification_type,
            priority=notification.priority,
            icon=notification.icon,
            image_url=notification.image_url,
            has_details_page=notification.has_details_page,
            publish_at=notification.publish_at,
            expires_at=notification.expires_at,
            is_read=recipient.is_read,
            read_at=recipient.read_at,
            read_count=recipient.read_count,
            details_viewed=recipient.details_viewed,
            details_view_count=recipient.details_view_count,
            details_viewed_at=recipient.details_viewed_at,
            last_viewed_at=recipient.last_viewed_at,
            is_archived=recipient.is_archived,
            archived_at=recipient.archived_at,
            delivered_at=recipient.delivered_at,
            received_at=recipient.created_at,
        )


class MyNotificationDetail(MyNotification):
    """A notification opened on its own page, with the body included."""

    details_content: str

    @classmethod
    def from_recipient(
        cls, recipient: "NotificationRecipient"
    ) -> "MyNotificationDetail":
        base = MyNotification.from_recipient(recipient)
        return cls(
            **base.model_dump(),
            details_content=recipient.notification.details_content,
        )


class UnreadCount(BaseModel):
    """The badge."""

    model_config = ConfigDict(json_schema_extra={"example": {"count": 12}})

    count: int


class MarkAllReadResult(BaseModel):
    """How many notifications one call marked."""

    marked: int


class RecipientSummary(BaseModel):
    """One person's engagement, for the administrative recipient list."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    is_read: bool
    read_at: datetime | None
    read_count: int
    details_viewed: bool
    details_view_count: int
    details_viewed_at: datetime | None
    last_viewed_at: datetime | None
    is_archived: bool
    delivered_at: datetime
    user: UserBrief | None = None
