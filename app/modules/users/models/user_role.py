"""The user-role mapping table.

Many-to-many rather than a single `role_id`: an instructor who also manages
content needs both, and one-role-per-user is just the common case of this.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Table, func

from app.core.database import Base

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "assigned_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
)
