"""The role-permission mapping table.

A plain association table rather than a mapped class: the grant carries no
behaviour of its own, only the fact that it happened and when.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Table, func

from app.core.database import Base

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column(
        "role_id",
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_id",
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "granted_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
)
