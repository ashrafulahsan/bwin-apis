"""add courses table

Revision ID: 7c1d8e4a6b20
Revises: 9f0c2b7a1d4e
Create Date: 2026-08-21 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c1d8e4a6b20"
down_revision: str | None = "9f0c2b7a1d4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("course_code", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("short_description", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("learning_outcomes", sa.JSON(), nullable=True),
        sa.Column("requirements", sa.JSON(), nullable=True),
        sa.Column("target_audience", sa.JSON(), nullable=True),
        sa.Column("category_id", sa.UUID(), nullable=True),
        sa.Column(
            "level", sa.String(length=20), server_default="beginner", nullable=False
        ),
        sa.Column(
            "language", sa.String(length=20), server_default="english", nullable=False
        ),
        sa.Column("course_type", sa.UUID(), nullable=True),
        sa.Column("delivery_mode", sa.UUID(), nullable=True),
        sa.Column("thumbnail", sa.String(length=500), nullable=True),
        sa.Column("cover_image", sa.String(length=500), nullable=True),
        sa.Column("promo_video_url", sa.String(length=500), nullable=True),
        sa.Column("intro_video_url", sa.String(length=500), nullable=True),
        sa.Column("duration_hours", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duration_minutes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_modules", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_lessons", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_quizzes", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "total_assignments", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("total_resources", sa.Integer(), server_default="0", nullable=False),
        sa.Column("passing_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "certificate_enabled", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("certificate_template_id", sa.UUID(), nullable=True),
        sa.Column("max_attempts", sa.Integer(), nullable=True),
        sa.Column("seat_limit", sa.Integer(), nullable=True),
        sa.Column(
            "price",
            sa.Numeric(precision=12, scale=2),
            server_default="0",
            nullable=False,
        ),
        sa.Column("discount_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "currency", sa.String(length=3), server_default="USD", nullable=False
        ),
        sa.Column("enrollment_start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enrollment_end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("course_start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("course_end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="draft", nullable=False
        ),
        sa.Column(
            "visibility", sa.String(length=20), server_default="public", nullable=False
        ),
        sa.Column("featured", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("allow_reviews", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "allow_discussion", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta_title", sa.String(length=255), nullable=True),
        sa.Column("meta_description", sa.String(length=500), nullable=True),
        sa.Column("meta_keywords", sa.String(length=255), nullable=True),
        sa.Column("canonical_url", sa.String(length=500), nullable=True),
        sa.Column("og_title", sa.String(length=255), nullable=True),
        sa.Column("og_description", sa.Text(), nullable=True),
        sa.Column("og_image_url", sa.String(length=500), nullable=True),
        sa.Column(
            "meta_robots",
            sa.String(length=100),
            server_default="index, follow",
            nullable=False,
        ),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_courses_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["course_type"],
            ["categories.id"],
            name=op.f("fk_courses_course_type_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_mode"],
            ["categories.id"],
            name=op.f("fk_courses_delivery_mode_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_courses_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_courses_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_courses")),
    )
    op.create_index(
        op.f("ix_courses_course_code"), "courses", ["course_code"], unique=True
    )
    op.create_index(op.f("ix_courses_slug"), "courses", ["slug"], unique=True)
    op.create_index(
        op.f("ix_courses_category_id"), "courses", ["category_id"], unique=False
    )
    op.create_index(
        op.f("ix_courses_course_type"), "courses", ["course_type"], unique=False
    )
    op.create_index(
        op.f("ix_courses_delivery_mode"), "courses", ["delivery_mode"], unique=False
    )
    op.create_index(op.f("ix_courses_status"), "courses", ["status"], unique=False)
    op.create_index(
        op.f("ix_courses_visibility"), "courses", ["visibility"], unique=False
    )
    op.create_index(
        op.f("ix_courses_published_at"), "courses", ["published_at"], unique=False
    )
    op.create_index(
        op.f("ix_courses_deleted_at"), "courses", ["deleted_at"], unique=False
    )
    op.create_index(
        "ix_courses_status_published_at",
        "courses",
        ["status", "published_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_courses_status_published_at", table_name="courses")
    for index in (
        "ix_courses_deleted_at",
        "ix_courses_published_at",
        "ix_courses_visibility",
        "ix_courses_status",
        "ix_courses_delivery_mode",
        "ix_courses_course_type",
        "ix_courses_category_id",
        "ix_courses_slug",
        "ix_courses_course_code",
    ):
        op.drop_index(op.f(index), table_name="courses")
    op.drop_table("courses")
