"""add subscriptions table, permissions and newsletter settings

Revision ID: 9a1f5c7e3b82
Revises: 6d3a9f2b8c41
Create Date: 2026-08-21 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9a1f5c7e3b82"
down_revision: str | None = "6d3a9f2b8c41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUBSCRIPTION_PERMISSIONS = [
    ("subscription.view", "view", "View newsletter subscribers"),
    ("subscription.create", "create", "Create newsletter subscribers"),
    ("subscription.update", "update", "Update newsletter subscribers"),
    ("subscription.delete", "delete", "Delete newsletter subscribers"),
]

#: A subscriber list is personal data, so the grants are narrower than a
#: content module's: the roles that run the newsletter get it, support can
#: look an address up when somebody asks, and nobody else needs a copy.
SUBSCRIPTION_GRANTS = {
    "super-admin": [item[0] for item in SUBSCRIPTION_PERMISSIONS],
    "admin": [item[0] for item in SUBSCRIPTION_PERMISSIONS],
    "content-manager": [item[0] for item in SUBSCRIPTION_PERMISSIONS],
    "support": ["subscription.view"],
}

NEWSLETTER_SETTINGS = [
    (
        "newsletter_confirm_path",
        "/newsletter/confirm",
        "Newsletter confirmation page",
        "Frontend page a newsletter confirmation link points at. The token "
        "is appended as `?token=`.",
    ),
    (
        "newsletter_unsubscribe_path",
        "/newsletter/unsubscribe",
        "Newsletter unsubscribe page",
        "Frontend page the unsubscribe link in every message footer points "
        "at. The token is appended as `?token=`.",
    ),
]


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="pending", nullable=False
        ),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("confirmation_token_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "confirmation_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("confirmation_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unsubscribe_reason", sa.String(length=255), nullable=True),
        sa.Column("signup_ip", sa.String(length=45), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
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
            ["created_by"],
            ["users.id"],
            name=op.f("fk_subscriptions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_subscriptions_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
        sa.UniqueConstraint(
            "confirmation_token_hash",
            name=op.f("uq_subscriptions_confirmation_token_hash"),
        ),
    )
    op.create_index(
        op.f("ix_subscriptions_email"), "subscriptions", ["email"], unique=True
    )
    op.create_index(
        op.f("ix_subscriptions_status"), "subscriptions", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_subscriptions_source"), "subscriptions", ["source"], unique=False
    )
    op.create_index(
        op.f("ix_subscriptions_deleted_at"),
        "subscriptions",
        ["deleted_at"],
        unique=False,
    )
    op.create_index(
        "ix_subscriptions_status_created_at",
        "subscriptions",
        ["status", "created_at"],
        unique=False,
    )

    connection = op.get_bind()
    for code, action, name in SUBSCRIPTION_PERMISSIONS:
        connection.execute(
            sa.text(
                """
                INSERT INTO permissions (code, resource, action, name, is_system)
                VALUES (:code, 'subscription', :action, :name, true)
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {"code": code, "action": action, "name": name},
        )

    for slug, codes in SUBSCRIPTION_GRANTS.items():
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

    for key, value, label, description in NEWSLETTER_SETTINGS:
        connection.execute(
            sa.text(
                """
                INSERT INTO settings (
                    key, value, value_type, "group", label, description,
                    is_secret, is_system
                )
                VALUES (
                    :key, :value, 'string', 'general', :label, :description,
                    false, true
                )
                ON CONFLICT (key) DO NOTHING
                """
            ),
            {
                "key": key,
                "value": value,
                "label": label,
                "description": description,
            },
        )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("DELETE FROM settings WHERE key = ANY(:keys)"),
        {"keys": [key for key, *_ in NEWSLETTER_SETTINGS]},
    )
    connection.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            WHERE permission_id IN (
                SELECT id FROM permissions WHERE resource = 'subscription'
            )
            """
        )
    )
    connection.execute(
        sa.text("DELETE FROM permissions WHERE resource = 'subscription'")
    )
    op.drop_index("ix_subscriptions_status_created_at", table_name="subscriptions")
    for index in (
        "ix_subscriptions_deleted_at",
        "ix_subscriptions_source",
        "ix_subscriptions_status",
        "ix_subscriptions_email",
    ):
        op.drop_index(op.f(index), table_name="subscriptions")
    op.drop_table("subscriptions")
