"""add user details table

Revision ID: 9f0c2b7a1d4e
Revises: 194781c7a53f
Create Date: 2026-08-20 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9f0c2b7a1d4e"
down_revision: str | None = "194781c7a53f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_details",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("gender", sa.String(length=50), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("nationality", sa.String(length=100), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("emergency_contact_name", sa.String(length=255), nullable=True),
        sa.Column("emergency_contact_phone", sa.String(length=50), nullable=True),
        sa.Column("photo_id", sa.UUID(), nullable=True),
        sa.Column("reporting_to", sa.UUID(), nullable=True),
        sa.Column("designation", sa.String(length=255), nullable=True),
        sa.Column("department", sa.String(length=255), nullable=True),
        sa.Column("organization", sa.String(length=255), nullable=True),
        sa.Column("years_of_experience", sa.Integer(), nullable=True),
        sa.Column("highest_degree", sa.String(length=255), nullable=True),
        sa.Column("university", sa.String(length=255), nullable=True),
        sa.Column("graduation_year", sa.Integer(), nullable=True),
        sa.Column("linkedin_url", sa.String(length=500), nullable=True),
        sa.Column("youtube_url", sa.String(length=500), nullable=True),
        sa.Column("facebook_url", sa.String(length=500), nullable=True),
        sa.Column("website_url", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_details_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reporting_to"],
            ["users.id"],
            name=op.f("fk_user_details_reporting_to_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_details")),
        sa.UniqueConstraint("user_id", name=op.f("uq_user_details_user_id")),
    )
    op.create_index(
        op.f("ix_user_details_user_id"), "user_details", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_user_details_reporting_to"),
        "user_details",
        ["reporting_to"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_details_reporting_to"), table_name="user_details")
    op.drop_index(op.f("ix_user_details_user_id"), table_name="user_details")
    op.drop_table("user_details")