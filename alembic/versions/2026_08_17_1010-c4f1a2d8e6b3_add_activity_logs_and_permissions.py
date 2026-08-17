"""add activity logs and permissions

The platform-wide audit trail: one row per business action, written by
`ActivityLogService` from inside the service that made the change.

**Append-only, and shaped like it.** There is no `updated_at` and no
`deleted_at`. An audit row that can be edited or quietly removed is not
evidence of anything, so the schema does not offer the columns that would let
it happen. The permissions seeded here say the same thing in the other
direction: `activity_log.view` and `activity_log.export` exist, and no
create, update or delete code does.

**The caller is denormalized on purpose.** `user_name` and `role_name` are
copied onto the row rather than joined from `users` and `roles`. A trail has
to keep saying who did something after the account is closed and after the
role is renamed, and `user_id` is `SET NULL` for the same reason - deleting an
account must never delete the record of what it did.

**`entity_id` is text.** Not every auditable row is keyed by a UUID: a
setting is identified by its key and a translation by key and locale. Text
holds all of them, and the `(entity_type, entity_id)` index is what makes
"what happened to this record" a fast question.

**JSONB for the values.** `old_values` and `new_values` hold only the fields
that actually changed, so the pair reads as a diff. JSONB rather than text
because the follow-up question is always about one field inside it.

Revision ID: c4f1a2d8e6b3
Revises: 34b19ea310f8
Create Date: 2026-08-17 10:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4f1a2d8e6b3"
down_revision: str | None = "34b19ea310f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Read the trail, and take it out of the system in bulk. Deliberately no
#: write codes - see the module docstring.
ACTIVITY_LOG_PERMISSIONS = [
    ("activity_log.view", "view", "View activity log"),
    ("activity_log.export", "export", "Export activity log"),
]

#: Who may read it. Auditing is an administrative function: the roles that
#: manage the platform can see what was done to it, and nobody else can -
#: an editor being able to read every other editor's actions is surveillance,
#: not accountability. Export is narrower still.
ACTIVITY_LOG_GRANTS = {
    "super-admin": ["activity_log.view", "activity_log.export"],
    "admin": ["activity_log.view", "activity_log.export"],
    "content-manager": ["activity_log.view"],
}


def upgrade() -> None:
    """Create the table, its indexes, and the two permissions."""
    op.create_table(
        "activity_logs",
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("user_name", sa.String(length=255), nullable=True),
        sa.Column("role_name", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("module", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=True),
        sa.Column("entity_id", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("old_values", postgresql.JSONB(), nullable=True),
        sa.Column("new_values", postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("request_method", sa.String(length=10), nullable=True),
        sa.Column("request_url", sa.String(length=512), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="success", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_activity_logs_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity_logs")),
    )

    op.create_index(
        op.f("ix_activity_logs_action"), "activity_logs", ["action"], unique=False
    )
    op.create_index(
        op.f("ix_activity_logs_created_at"),
        "activity_logs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_activity_logs_module"), "activity_logs", ["module"], unique=False
    )
    op.create_index(
        op.f("ix_activity_logs_status"), "activity_logs", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_activity_logs_user_id"), "activity_logs", ["user_id"], unique=False
    )
    # "What happened to this record?" - ids are only unique within a type, so
    # the pair is the index that answers it.
    op.create_index(
        "ix_activity_logs_entity",
        "activity_logs",
        ["entity_type", "entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_activity_logs_user_id_created_at",
        "activity_logs",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_activity_logs_module_created_at",
        "activity_logs",
        ["module", "created_at"],
        unique=False,
    )

    connection = op.get_bind()

    for code, action, name in ACTIVITY_LOG_PERMISSIONS:
        connection.execute(
            sa.text("""
                INSERT INTO permissions (code, resource, action, name, is_system)
                VALUES (:code, 'activity_log', :action, :name, true)
                ON CONFLICT (code) DO NOTHING
                """),
            {"code": code, "action": action, "name": name},
        )

    for slug, codes in ACTIVITY_LOG_GRANTS.items():
        connection.execute(
            sa.text("""
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT r.id, p.id FROM roles r JOIN permissions p ON true
                WHERE r.slug = :slug AND p.code = ANY(:codes)
                ON CONFLICT DO NOTHING
                """),
            {"slug": slug, "codes": codes},
        )


def downgrade() -> None:
    """Drop the table and its permissions.

    This does discard the audit trail, which is the one thing an audit trail
    must not lose - take a copy of `activity_logs` before running it.
    """
    connection = op.get_bind()

    connection.execute(sa.text("""
            DELETE FROM role_permissions
            WHERE permission_id IN (
                SELECT id FROM permissions WHERE resource = 'activity_log'
            )
            """))
    connection.execute(
        sa.text("DELETE FROM permissions WHERE resource = 'activity_log'")
    )

    op.drop_index("ix_activity_logs_module_created_at", table_name="activity_logs")
    op.drop_index("ix_activity_logs_user_id_created_at", table_name="activity_logs")
    op.drop_index("ix_activity_logs_entity", table_name="activity_logs")
    op.drop_index(op.f("ix_activity_logs_user_id"), table_name="activity_logs")
    op.drop_index(op.f("ix_activity_logs_status"), table_name="activity_logs")
    op.drop_index(op.f("ix_activity_logs_module"), table_name="activity_logs")
    op.drop_index(op.f("ix_activity_logs_created_at"), table_name="activity_logs")
    op.drop_index(op.f("ix_activity_logs_action"), table_name="activity_logs")

    op.drop_table("activity_logs")
