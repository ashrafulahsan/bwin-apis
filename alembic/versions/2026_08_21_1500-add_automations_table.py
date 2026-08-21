"""add automations table and permissions

Revision ID: 6d3a9f2b8c41
Revises: 4b7e2c9d1f30
Create Date: 2026-08-21 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6d3a9f2b8c41"
down_revision: str | None = "4b7e2c9d1f30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTOMATION_PERMISSIONS = [
    ("automation.view", "view", "View automations"),
    ("automation.create", "create", "Create automations"),
    ("automation.update", "update", "Update automations"),
    ("automation.delete", "delete", "Delete automations"),
    ("automation.publish", "publish", "Publish automations"),
]

AUTOMATION_GRANTS = {
    "super-admin": [item[0] for item in AUTOMATION_PERMISSIONS],
    "admin": [item[0] for item in AUTOMATION_PERMISSIONS],
    "content-manager": [item[0] for item in AUTOMATION_PERMISSIONS],
    # Editors write but never publish - that is the point of the role.
    "editor": ["automation.view", "automation.create", "automation.update"],
    "instructor": ["automation.view"],
    "support": ["automation.view"],
    "student": ["automation.view"],
}


def upgrade() -> None:
    op.create_table(
        "automations",
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("lists", sa.JSON(), nullable=True),
        sa.Column("category_id", sa.UUID(), nullable=True),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("video_url", sa.String(length=500), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="draft", nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("fk_automations_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_automations_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_automations_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_automations")),
    )
    op.create_index(op.f("ix_automations_slug"), "automations", ["slug"], unique=True)
    op.create_index(
        op.f("ix_automations_category_id"), "automations", ["category_id"], unique=False
    )
    op.create_index(
        op.f("ix_automations_status"), "automations", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_automations_published_at"),
        "automations",
        ["published_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_automations_deleted_at"), "automations", ["deleted_at"], unique=False
    )
    op.create_index(
        "ix_automations_status_published_at",
        "automations",
        ["status", "published_at"],
        unique=False,
    )

    connection = op.get_bind()
    for code, action, name in AUTOMATION_PERMISSIONS:
        connection.execute(
            sa.text(
                """
                INSERT INTO permissions (code, resource, action, name, is_system)
                VALUES (:code, 'automation', :action, :name, true)
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {"code": code, "action": action, "name": name},
        )

    for slug, codes in AUTOMATION_GRANTS.items():
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
                SELECT id FROM permissions WHERE resource = 'automation'
            )
            """
        )
    )
    connection.execute(
        sa.text("DELETE FROM permissions WHERE resource = 'automation'")
    )
    op.drop_index("ix_automations_status_published_at", table_name="automations")
    for index in (
        "ix_automations_deleted_at",
        "ix_automations_published_at",
        "ix_automations_status",
        "ix_automations_category_id",
        "ix_automations_slug",
    ):
        op.drop_index(op.f(index), table_name="automations")
    op.drop_table("automations")
