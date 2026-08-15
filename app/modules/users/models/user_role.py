"""The user-role mapping table.

Many-to-many rather than a single `role_id`: an instructor who also manages
content needs both, and one-role-per-user is just the common case.

Carries a surrogate `id` primary key, matching every other table in the
schema, so an assignment can be addressed on its own and can later gain
attributes such as `assigned_by` or `expires_at` without a key change.

The `UNIQUE (user_id, role_id)` constraint is what actually prevents a role
being assigned twice; it replaces the composite primary key.
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Table,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811

from app.core.database import Base

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column(
        "id",
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    ),
    Column(
        "user_id",
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "role_id",
        PgUUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "assigned_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
    UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role"),
    # Covers "which users hold this role", the reverse of the unique index.
    Index("ix_user_roles_role_id", "role_id"),
)
