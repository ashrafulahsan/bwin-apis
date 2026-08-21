"""The activity log: one row per business action, for every module.

Append-only by design. Nothing updates a row here and nothing soft deletes
one, which is why the table carries `created_at` alone rather than the usual
timestamp pair - an audit record that can be edited is not an audit record.

The caller is denormalized onto the row: `user_name` and `role_name` are
copied at write time rather than joined at read time. That is deliberate
duplication. An audit trail has to keep saying "Rafiqul Islam, Admin, deleted
this" after the account is gone and after the role is renamed, and a foreign
key would either block the deletion or quietly rewrite history.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UUIDPrimaryKeyMixin

ACTION_MAX_LENGTH = 50
MODULE_MAX_LENGTH = 50
ENTITY_TYPE_MAX_LENGTH = 100
ENTITY_ID_MAX_LENGTH = 255
USER_NAME_MAX_LENGTH = 255
ROLE_NAME_MAX_LENGTH = 255
IP_ADDRESS_MAX_LENGTH = 45
USER_AGENT_MAX_LENGTH = 512
REQUEST_METHOD_MAX_LENGTH = 10
REQUEST_URL_MAX_LENGTH = 512


class ActivityAction(StrEnum):
    """What was done.

    One member per kind of business action rather than a free-text field, so
    "delete" cannot arrive spelled four ways and make a filter lie. Services
    may still pass a string for an action that has no member yet; adding the
    member here is what makes it findable.
    """

    # -- Lifecycle ------------------------------------------------------
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RESTORE = "restore"

    # -- Publication and review -----------------------------------------
    PUBLISH = "publish"
    UNPUBLISH = "unpublish"
    ARCHIVE = "archive"
    STATUS_CHANGE = "status_change"
    APPROVE = "approve"
    REJECT = "reject"

    # -- Authentication --------------------------------------------------
    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    TOKEN_REFRESH = "token_refresh"
    GOOGLE_LOGIN = "google_login"
    FACEBOOK_LOGIN = "facebook_login"
    SOCIAL_LOGIN = "social_login"
    ACCOUNT_LINK = "account_link"
    ACCOUNT_UNLINK = "account_unlink"

    # -- Credentials ------------------------------------------------------
    PASSWORD_RESET_REQUEST = "password_reset_request"
    PASSWORD_RESET = "password_reset"
    PASSWORD_CHANGE = "password_change"
    VERIFY = "verify"

    # -- Authorization ----------------------------------------------------
    ROLE_ASSIGN = "role_assign"
    ROLE_REVOKE = "role_revoke"
    PERMISSION_GRANT = "permission_grant"
    PERMISSION_REVOKE = "permission_revoke"

    # -- Configuration and content ----------------------------------------
    SETTINGS_CHANGE = "settings_change"
    UPLOAD = "upload"
    IMPORT = "import"
    EXPORT = "export"

    # -- Learning ----------------------------------------------------------
    ENROLL = "enroll"
    UNENROLL = "unenroll"


class ActivityModule(StrEnum):
    """Which part of the platform the action belongs to.

    Named after the module directory, so a reader can go from a log line to
    the code without a lookup table.
    """

    AUTH = "auth"
    USERS = "users"
    ROLES = "roles"
    PERMISSIONS = "permissions"
    SETTINGS = "settings"
    TRANSLATIONS = "translations"
    CATEGORIES = "categories"
    BLOGS = "blogs"
    PAGES = "pages"
    MENUS = "menus"
    MASTER_CRUDS = "master_cruds"
    COURSES = "courses"
    CONSULTANCIES = "consultancies"
    AUTOMATIONS = "automations"
    CMS = "cms"
    LMS = "lms"
    MEDIA = "media"
    NOTIFICATIONS = "notifications"
    REPORTS = "reports"
    SYSTEM = "system"


class ActivityStatus(StrEnum):
    """Whether the action succeeded.

    Failures are recorded too, and they are the entries most worth having: a
    run of `login_failed` against one account is the thing an audit log
    exists to make visible.
    """

    SUCCESS = "success"
    FAILURE = "failure"


#: Actions that must never be reachable without a log entry. Enforced by the
#: policy tests, which read this list rather than a copy of it.
MANDATORY_ACTIONS: frozenset[ActivityAction] = frozenset(
    {
        ActivityAction.CREATE,
        ActivityAction.UPDATE,
        ActivityAction.DELETE,
        ActivityAction.LOGIN,
        ActivityAction.LOGOUT,
        ActivityAction.STATUS_CHANGE,
        ActivityAction.APPROVE,
        ActivityAction.ENROLL,
        ActivityAction.PUBLISH,
        ActivityAction.SETTINGS_CHANGE,
        ActivityAction.PASSWORD_RESET,
        ActivityAction.GOOGLE_LOGIN,
        ActivityAction.FACEBOOK_LOGIN,
        ActivityAction.ROLE_ASSIGN,
        ActivityAction.PERMISSION_GRANT,
        ActivityAction.UPLOAD,
    }
)


class ActivityLog(Base, UUIDPrimaryKeyMixin):
    """One recorded action."""

    # -- Who ------------------------------------------------------------
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # `SET NULL`, never cascade: deleting an account must not delete the
        # record of what it did. `user_name` and `role_name` carry on saying
        # who it was.
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
        index=True,
        doc="Null for an anonymous caller, or once the account is removed.",
    )
    user_name: Mapped[str | None] = mapped_column(
        String(USER_NAME_MAX_LENGTH),
        default=None,
        doc="The caller's name as it was at the time.",
    )
    role_name: Mapped[str | None] = mapped_column(
        String(ROLE_NAME_MAX_LENGTH),
        default=None,
        doc="Every role held at the time, comma separated.",
    )

    # -- What -----------------------------------------------------------
    action: Mapped[str] = mapped_column(
        String(ACTION_MAX_LENGTH), nullable=False, index=True
    )
    module: Mapped[str] = mapped_column(
        String(MODULE_MAX_LENGTH), nullable=False, index=True
    )
    entity_type: Mapped[str | None] = mapped_column(
        String(ENTITY_TYPE_MAX_LENGTH),
        default=None,
        doc="The model acted on, e.g. `User`.",
    )
    entity_id: Mapped[str | None] = mapped_column(
        String(ENTITY_ID_MAX_LENGTH),
        default=None,
        doc=(
            "Which row, as text. Text rather than a UUID column because not "
            "everything worth auditing is keyed by one - a setting is "
            "identified by its key, a translation by key and locale."
        ),
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="One human-readable sentence, written for whoever reads the trail.",
    )

    # -- The change -----------------------------------------------------
    # JSONB rather than text: an auditor's question is nearly always "what
    # changed about this field", and JSONB can be queried and indexed for it.
    # Only the fields that actually changed are stored on an update, so the
    # pair reads as a diff rather than two copies of a row.
    old_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    new_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)

    # -- Where from -----------------------------------------------------
    ip_address: Mapped[str | None] = mapped_column(
        String(IP_ADDRESS_MAX_LENGTH), default=None, doc="Wide enough for IPv6."
    )
    user_agent: Mapped[str | None] = mapped_column(
        String(USER_AGENT_MAX_LENGTH), default=None
    )
    request_method: Mapped[str | None] = mapped_column(
        String(REQUEST_METHOD_MAX_LENGTH), default=None
    )
    request_url: Mapped[str | None] = mapped_column(
        String(REQUEST_URL_MAX_LENGTH), default=None
    )

    # -- Outcome --------------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(20),
        default=ActivityStatus.SUCCESS.value,
        server_default=ActivityStatus.SUCCESS.value,
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
        doc="There is no `updated_at`: nothing may edit an audit row.",
    )

    __table_args__ = (
        # "What happened to this thing?" - the question an audit trail is
        # opened to answer, and the one a bare `entity_id` index cannot serve
        # because ids are only unique within a type.
        Index("ix_activity_logs_entity", "entity_type", "entity_id"),
        # "What did this account do, most recent first."
        Index("ix_activity_logs_user_id_created_at", "user_id", "created_at"),
        # The default listing, and every module-scoped report.
        Index("ix_activity_logs_module_created_at", "module", "created_at"),
    )

    @property
    def succeeded(self) -> bool:
        return self.status == ActivityStatus.SUCCESS

    def __repr__(self) -> str:
        return f"<ActivityLog {self.module}.{self.action} {self.entity_id}>"
