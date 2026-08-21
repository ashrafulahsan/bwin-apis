"""add consultancies table and permissions

Revision ID: 4b7e2c9d1f30
Revises: 7c1d8e4a6b20
Create Date: 2026-08-21 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4b7e2c9d1f30"
down_revision: str | None = "7c1d8e4a6b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSULTANCY_PERMISSIONS = [
    ("consultancy.view", "view", "View consultancies"),
    ("consultancy.create", "create", "Create consultancies"),
    ("consultancy.update", "update", "Update consultancies"),
    ("consultancy.delete", "delete", "Delete consultancies"),
]

CONSULTANCY_GRANTS = {
    "super-admin": [item[0] for item in CONSULTANCY_PERMISSIONS],
    "admin": [item[0] for item in CONSULTANCY_PERMISSIONS],
    "content-manager": [
        "consultancy.view",
        "consultancy.create",
        "consultancy.update",
        "consultancy.delete",
    ],
    "editor": ["consultancy.view", "consultancy.create", "consultancy.update"],
    "instructor": ["consultancy.view", "consultancy.create", "consultancy.update"],
    "support": ["consultancy.view"],
    "student": ["consultancy.view"],
}


def upgrade() -> None:
    op.create_table(
        "consultancies",
        sa.Column("consultancy_code", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "consultancy_type",
            sa.String(length=30),
            server_default="general",
            nullable=False,
        ),
        sa.Column("category_id", sa.UUID(), nullable=True),
        sa.Column("thumbnail", sa.String(length=500), nullable=True),
        sa.Column("promo_video_url", sa.String(length=500), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="active", nullable=False
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
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
            name=op.f("fk_consultancies_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_consultancies_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_consultancies_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consultancies")),
    )
    op.create_index(
        op.f("ix_consultancies_consultancy_code"),
        "consultancies",
        ["consultancy_code"],
        unique=True,
    )
    op.create_index(
        op.f("ix_consultancies_slug"), "consultancies", ["slug"], unique=True
    )
    op.create_index(
        op.f("ix_consultancies_consultancy_type"),
        "consultancies",
        ["consultancy_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_consultancies_category_id"),
        "consultancies",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_consultancies_status"), "consultancies", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_consultancies_deleted_at"),
        "consultancies",
        ["deleted_at"],
        unique=False,
    )
    op.create_index(
        "ix_consultancies_status_sort_order",
        "consultancies",
        ["status", "sort_order"],
        unique=False,
    )

    connection = op.get_bind()
    for code, action, name in CONSULTANCY_PERMISSIONS:
        connection.execute(
            sa.text(
                """
                INSERT INTO permissions (code, resource, action, name, is_system)
                VALUES (:code, 'consultancy', :action, :name, true)
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {"code": code, "action": action, "name": name},
        )

    for slug, codes in CONSULTANCY_GRANTS.items():
        connection.execute(
            sa.text(
                """
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT r.id, p.id FROM roles r JOIN permissions p ON true
                WHERE r.slug = :slug AND p.code = ANY(:codes)
                ON CONFLICT DO NOTHING
                """
            ),
            {"slug": slug, "codes": codes},
        )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            WHERE permission_id IN (
                SELECT id FROM permissions WHERE resource = 'consultancy'
            )
            """
        )
    )
    connection.execute(
        sa.text("DELETE FROM permissions WHERE resource = 'consultancy'")
    )
    op.drop_index("ix_consultancies_status_sort_order", table_name="consultancies")
    for index in (
        "ix_consultancies_deleted_at",
        "ix_consultancies_status",
        "ix_consultancies_category_id",
        "ix_consultancies_consultancy_type",
        "ix_consultancies_slug",
        "ix_consultancies_consultancy_code",
    ):
        op.drop_index(op.f(index), table_name="consultancies")
    op.drop_table("consultancies")