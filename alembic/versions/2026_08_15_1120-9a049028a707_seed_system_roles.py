"""seed system roles

Seeds the built-in roles so every environment starts with the same set. Kept
separate from the schema revision so the table and its contents can be rolled
back independently.

The definitions are copied here rather than imported from
`app.modules.roles.constants`, because a migration must keep applying the same
data even after the application code moves on.

Revision ID: 9a049028a707
Revises: ed305d09a035
Create Date: 2026-08-15 11:20:22.664066

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a049028a707"
down_revision: str | None = "ed305d09a035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SYSTEM_ROLES = [
    {
        "slug": "super-admin",
        "name": "Super Admin",
        "description": "Unrestricted access to every part of the platform.",
        "level": 100,
    },
    {
        "slug": "admin",
        "name": "Admin",
        "description": "Manages users, roles and platform settings.",
        "level": 90,
    },
    {
        "slug": "content-manager",
        "name": "Content Manager",
        "description": "Owns the content library and publishes CMS pages.",
        "level": 70,
    },
    {
        "slug": "editor",
        "name": "Editor",
        "description": "Writes and edits content, but cannot publish it.",
        "level": 60,
    },
    {
        "slug": "instructor",
        "name": "Instructor",
        "description": "Creates and teaches courses, and grades learners.",
        "level": 50,
    },
    {
        "slug": "support",
        "name": "Support",
        "description": "Assists learners and handles support requests.",
        "level": 40,
    },
    {
        "slug": "student",
        "name": "Student",
        "description": "Enrols in courses and tracks personal progress.",
        "level": 10,
    },
]


def upgrade() -> None:
    """Insert the built-in roles, skipping any that already exist."""
    connection = op.get_bind()

    for role in SYSTEM_ROLES:
        connection.execute(
            sa.text("""
                INSERT INTO roles (slug, name, description, level, is_system)
                VALUES (:slug, :name, :description, :level, true)
                ON CONFLICT (slug) DO NOTHING
                """),
            role,
        )


def downgrade() -> None:
    """Remove the seeded roles, leaving any custom ones untouched."""
    connection = op.get_bind()

    connection.execute(
        sa.text("DELETE FROM roles WHERE is_system = true AND slug = ANY(:slugs)"),
        {"slugs": [role["slug"] for role in SYSTEM_ROLES]},
    )
