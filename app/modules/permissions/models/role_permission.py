"""The role-permission mapping table.

Carries a surrogate `id` primary key, matching every other table in the
schema, so a single grant can be addressed on its own and the row can later
gain attributes such as `granted_by` without a key change.

The `UNIQUE (role_id, permission_id)` constraint is what actually prevents
duplicate grants. It is doing the job the composite primary key used to do,
and removing it would let the same permission be granted twice.
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

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column(
        "id",
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    ),
    Column(
        "role_id",
        PgUUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "permission_id",
        PgUUID(as_uuid=True),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "granted_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
    UniqueConstraint(
        "role_id", "permission_id", name="uq_role_permissions_role_permission"
    ),
    # The unique index above already serves lookups leading with `role_id`.
    # This one covers the reverse direction - "which roles hold this
    # permission" - which would otherwise scan the whole table.
    Index("ix_role_permissions_permission_id", "permission_id"),
)
