"""add support ticket tables permissions and settings

Revision ID: 766818affd8d
Revises: 8b25cf7dfd34
Create Date: 2026-08-24 16:06:36.581410

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "766818affd8d"
down_revision: str | None = "8b25cf7dfd34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SUPPORT_PERMISSIONS = [
    ("ticket.view", "view", "View support tickets within your scope"),
    ("ticket.view_all", "view_all", "View every support ticket"),
    ("ticket.create", "create", "Raise support tickets"),
    ("ticket.reply", "reply", "Reply to support tickets"),
    ("ticket.assign", "assign", "Assign and reassign support tickets"),
    ("ticket.status", "status", "Change a support ticket status"),
    ("ticket.priority", "priority", "Change a support ticket priority"),
    ("ticket.category", "category", "Change a support ticket category"),
    ("ticket.escalate", "escalate", "Escalate support tickets"),
    ("ticket.internal_note", "internal_note", "Read and write internal notes"),
    ("ticket.merge", "merge", "Merge duplicate support tickets"),
    ("ticket.export", "export", "Export the support ticket queue"),
    ("ticket.report", "report", "View support desk reports"),
    ("ticket.delete", "delete", "Delete support tickets"),
]

ALL_TICKET_CODES = [code for code, *_ in SUPPORT_PERMISSIONS]

#: Who gets what.
#:
#: A student may raise and answer their own tickets and nothing else - the
#: scope limiting "their own" is enforced in the service, but the verbs they
#: hold are already the narrow set. A trainer works an assigned queue, so they
#: may move a ticket through the workflow but not hand it to someone else.
#: Support runs the desk. Internal notes go to support and above, deliberately
#: not to trainers: a note is where staff talk about a ticket rather than to
#: the student, and widening that audience defeats the point of it.
SUPPORT_GRANTS = {
    "super-admin": ALL_TICKET_CODES,
    "admin": ALL_TICKET_CODES,
    "support": [
        "ticket.view",
        "ticket.view_all",
        "ticket.create",
        "ticket.reply",
        "ticket.assign",
        "ticket.status",
        "ticket.priority",
        "ticket.category",
        "ticket.escalate",
        "ticket.internal_note",
        "ticket.merge",
        "ticket.export",
        "ticket.report",
    ],
    "instructor": [
        "ticket.view",
        "ticket.create",
        "ticket.reply",
        "ticket.status",
        "ticket.escalate",
    ],
    "student": ["ticket.view", "ticket.create", "ticket.reply"],
}

SUPPORT_SETTINGS = [
    (
        "support_ticket_reopen_days",
        "7",
        "integer",
        "Ticket reopen window (days)",
        "How long after closing a student may reopen a ticket. 0 forbids "
        "reopening; a negative value removes the limit.",
    ),
    (
        "support_ticket_max_upload_mb",
        "10",
        "integer",
        "Ticket attachment size limit (MB)",
        "Largest single file that may be attached to a support ticket.",
    ),
    (
        "support_ticket_max_attachments",
        "20",
        "integer",
        "Attachments per ticket",
        "How many files one support ticket may accumulate.",
    ),
    (
        "support_ticket_allowed_extensions",
        ".jpg,.jpeg,.png,.webp,.gif,.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.zip,.log",
        "string",
        "Accepted attachment types",
        "Comma separated file extensions a ticket attachment may use.",
    ),
]

#: The taxonomy tickets are filed under, with the topics the desk starts with.
#: Seeded here rather than left to an administrator because the module refuses
#: a category from any other taxonomy, so an empty one would mean no ticket
#: could be categorised at all.
SUPPORT_CATEGORY_TYPE = (
    "support_ticket",
    "Support Ticket",
    "Topics a support ticket can be filed under.",
)

SUPPORT_CATEGORIES = [
    ("technical-issue", "Technical Issue"),
    ("course-access", "Course Access"),
    ("payment-issue", "Payment Issue"),
    ("certificate-issue", "Certificate Issue"),
    ("assignment-issue", "Assignment Issue"),
    ("live-class-issue", "Live Class Issue"),
    ("account-issue", "Account Issue"),
    ("general-inquiry", "General Inquiry"),
]


def _seed(connection: sa.Connection) -> None:
    """Insert permissions, grants, settings and the support taxonomy.

    Every statement is idempotent, so running this against a database that
    already carries some of these rows is a no-op rather than an integrity
    error.
    """
    for code, action, name in SUPPORT_PERMISSIONS:
        connection.execute(
            sa.text("""
                INSERT INTO permissions (code, resource, action, name, is_system)
                VALUES (:code, 'ticket', :action, :name, true)
                ON CONFLICT (code) DO NOTHING
                """),
            {"code": code, "action": action, "name": name},
        )

    for slug, codes in SUPPORT_GRANTS.items():
        connection.execute(
            sa.text("""
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT r.id, p.id FROM roles r JOIN permissions p ON true
                WHERE r.slug = :slug AND p.code = ANY(:codes)
                ON CONFLICT DO NOTHING
                """),
            {"slug": slug, "codes": codes},
        )

    for key, value, value_type, label, description in SUPPORT_SETTINGS:
        connection.execute(
            sa.text("""
                INSERT INTO settings (
                    key, value, value_type, "group", label, description,
                    is_secret, is_system
                )
                VALUES (
                    :key, :value, :value_type, 'general', :label, :description,
                    false, true
                )
                ON CONFLICT (key) DO NOTHING
                """),
            {
                "key": key,
                "value": value,
                "value_type": value_type,
                "label": label,
                "description": description,
            },
        )

    slug, name, description = SUPPORT_CATEGORY_TYPE
    connection.execute(
        sa.text("""
            INSERT INTO category_types (name, slug, description, status)
            VALUES (:name, :slug, :description, 'active')
            ON CONFLICT (slug) DO NOTHING
            """),
        {"name": name, "slug": slug, "description": description},
    )

    type_id = connection.execute(
        sa.text("SELECT id FROM category_types WHERE slug = :slug"), {"slug": slug}
    ).scalar_one()

    for category_slug, category_name in SUPPORT_CATEGORIES:
        connection.execute(
            sa.text("""
                INSERT INTO categories (name, slug, category_type_id, status)
                VALUES (:name, :slug, :type_id, 'active')
                ON CONFLICT (slug) DO NOTHING
                """),
            {"name": category_name, "slug": category_slug, "type_id": type_id},
        )


def _unseed(connection: sa.Connection) -> None:
    """Remove what `_seed` added, innermost references first."""
    connection.execute(
        sa.text("""
            DELETE FROM categories
            WHERE category_type_id IN (
                SELECT id FROM category_types WHERE slug = :slug
            )
            """),
        {"slug": SUPPORT_CATEGORY_TYPE[0]},
    )
    connection.execute(
        sa.text("DELETE FROM category_types WHERE slug = :slug"),
        {"slug": SUPPORT_CATEGORY_TYPE[0]},
    )
    connection.execute(
        sa.text("DELETE FROM settings WHERE key = ANY(:keys)"),
        {"keys": [key for key, *_ in SUPPORT_SETTINGS]},
    )
    connection.execute(sa.text("""
            DELETE FROM role_permissions
            WHERE permission_id IN (
                SELECT id FROM permissions WHERE resource = 'ticket'
            )
            """))
    connection.execute(sa.text("DELETE FROM permissions WHERE resource = 'ticket'"))


def upgrade() -> None:
    """Apply this revision."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "support_tickets",
        sa.Column("ticket_no", sa.String(length=30), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=True),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("assigned_to", sa.UUID(), nullable=True),
        sa.Column(
            "priority", sa.String(length=20), server_default="medium", nullable=False
        ),
        sa.Column(
            "status", sa.String(length=30), server_default="open", nullable=False
        ),
        sa.Column("source", sa.String(length=20), server_default="web", nullable=False),
        sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reply_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_replies", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attachment_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_escalated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated_by", sa.UUID(), nullable=True),
        sa.Column("escalation_reason", sa.Text(), nullable=True),
        sa.Column("satisfaction_rating", sa.Integer(), nullable=True),
        sa.Column("satisfaction_comment", sa.Text(), nullable=True),
        sa.Column("merged_into_id", sa.UUID(), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "satisfaction_rating IS NULL OR "
            "(satisfaction_rating >= 1 AND satisfaction_rating <= 5)",
            name=op.f("ck_support_tickets_satisfaction_rating_range"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to"],
            ["users.id"],
            name=op.f("fk_support_tickets_assigned_to_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_support_tickets_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_support_tickets_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["escalated_by"],
            ["users.id"],
            name=op.f("fk_support_tickets_escalated_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["merged_into_id"],
            ["support_tickets.id"],
            name=op.f("fk_support_tickets_merged_into_id_support_tickets"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_support_tickets_student_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_support_tickets_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_tickets")),
    )
    op.create_index(
        op.f("ix_support_tickets_assigned_to"),
        "support_tickets",
        ["assigned_to"],
        unique=False,
    )
    op.create_index(
        "ix_support_tickets_assigned_to_status",
        "support_tickets",
        ["assigned_to", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_tickets_category_id"),
        "support_tickets",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        "ix_support_tickets_created_at", "support_tickets", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_support_tickets_deleted_at"),
        "support_tickets",
        ["deleted_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_tickets_is_escalated"),
        "support_tickets",
        ["is_escalated"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_tickets_last_reply_at"),
        "support_tickets",
        ["last_reply_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_tickets_merged_into_id"),
        "support_tickets",
        ["merged_into_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_tickets_priority"),
        "support_tickets",
        ["priority"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_tickets_status"), "support_tickets", ["status"], unique=False
    )
    op.create_index(
        "ix_support_tickets_status_priority",
        "support_tickets",
        ["status", "priority"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_tickets_student_id"),
        "support_tickets",
        ["student_id"],
        unique=False,
    )
    op.create_index(
        "ix_support_tickets_student_id_status",
        "support_tickets",
        ["student_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_tickets_ticket_no"),
        "support_tickets",
        ["ticket_no"],
        unique=True,
    )
    op.create_table(
        "support_ticket_activities",
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("activity_type", sa.String(length=50), nullable=False),
        sa.Column("activity_description", sa.String(length=500), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["support_tickets.id"],
            name=op.f("fk_support_ticket_activities_ticket_id_support_tickets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_support_ticket_activities_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_ticket_activities")),
    )
    op.create_index(
        op.f("ix_support_ticket_activities_activity_type"),
        "support_ticket_activities",
        ["activity_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_ticket_activities_ticket_id"),
        "support_ticket_activities",
        ["ticket_id"],
        unique=False,
    )
    op.create_index(
        "ix_support_ticket_activities_ticket_id_created_at",
        "support_ticket_activities",
        ["ticket_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_ticket_activities_user_id"),
        "support_ticket_activities",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "support_ticket_assignments",
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("assigned_from", sa.UUID(), nullable=True),
        sa.Column("assigned_to", sa.UUID(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["assigned_from"],
            ["users.id"],
            name=op.f("fk_support_ticket_assignments_assigned_from_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to"],
            ["users.id"],
            name=op.f("fk_support_ticket_assignments_assigned_to_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_support_ticket_assignments_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["support_tickets.id"],
            name=op.f("fk_support_ticket_assignments_ticket_id_support_tickets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_ticket_assignments")),
    )
    op.create_index(
        op.f("ix_support_ticket_assignments_assigned_to"),
        "support_ticket_assignments",
        ["assigned_to"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_ticket_assignments_ticket_id"),
        "support_ticket_assignments",
        ["ticket_id"],
        unique=False,
    )
    op.create_index(
        "ix_support_ticket_assignments_ticket_id_created_at",
        "support_ticket_assignments",
        ["ticket_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "support_ticket_feedback",
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("submitted_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.CheckConstraint(
            "rating >= 1 AND rating <= 5",
            name=op.f("ck_support_ticket_feedback_feedback_rating_range"),
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"],
            ["users.id"],
            name=op.f("fk_support_ticket_feedback_submitted_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["support_tickets.id"],
            name=op.f("fk_support_ticket_feedback_ticket_id_support_tickets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_ticket_feedback")),
    )
    op.create_index(
        op.f("ix_support_ticket_feedback_ticket_id"),
        "support_ticket_feedback",
        ["ticket_id"],
        unique=True,
    )
    op.create_table(
        "support_ticket_messages",
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "is_internal_note", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "is_system_message", sa.Boolean(), server_default="false", nullable=False
        ),
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
            name=op.f("fk_support_ticket_messages_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["support_tickets.id"],
            name=op.f("fk_support_ticket_messages_ticket_id_support_tickets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_support_ticket_messages_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_support_ticket_messages_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_ticket_messages")),
    )
    op.create_index(
        op.f("ix_support_ticket_messages_deleted_at"),
        "support_ticket_messages",
        ["deleted_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_ticket_messages_ticket_id"),
        "support_ticket_messages",
        ["ticket_id"],
        unique=False,
    )
    op.create_index(
        "ix_support_ticket_messages_ticket_id_created_at",
        "support_ticket_messages",
        ["ticket_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_ticket_messages_user_id"),
        "support_ticket_messages",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "support_ticket_status_history",
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("old_status", sa.String(length=30), nullable=True),
        sa.Column("new_status", sa.String(length=30), nullable=False),
        sa.Column("changed_by", sa.UUID(), nullable=True),
        sa.Column("remarks", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.id"],
            name=op.f("fk_support_ticket_status_history_changed_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["support_tickets.id"],
            name=op.f("fk_support_ticket_status_history_ticket_id_support_tickets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_ticket_status_history")),
    )
    op.create_index(
        op.f("ix_support_ticket_status_history_new_status"),
        "support_ticket_status_history",
        ["new_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_ticket_status_history_ticket_id"),
        "support_ticket_status_history",
        ["ticket_id"],
        unique=False,
    )
    op.create_index(
        "ix_support_ticket_status_history_ticket_id_created_at",
        "support_ticket_status_history",
        ["ticket_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "support_ticket_attachments",
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=150), nullable=True),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
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
            ["message_id"],
            ["support_ticket_messages.id"],
            name=op.f(
                "fk_support_ticket_attachments_message_id_support_ticket_messages"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["support_tickets.id"],
            name=op.f("fk_support_ticket_attachments_ticket_id_support_tickets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_support_ticket_attachments_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_ticket_attachments")),
    )
    op.create_index(
        op.f("ix_support_ticket_attachments_deleted_at"),
        "support_ticket_attachments",
        ["deleted_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_ticket_attachments_message_id"),
        "support_ticket_attachments",
        ["message_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_support_ticket_attachments_ticket_id"),
        "support_ticket_attachments",
        ["ticket_id"],
        unique=False,
    )
    op.create_index(
        "ix_support_ticket_attachments_ticket_id_created_at",
        "support_ticket_attachments",
        ["ticket_id", "created_at"],
        unique=False,
    )
    # ### end Alembic commands ###

    _seed(op.get_bind())


def downgrade() -> None:
    """Revert this revision."""
    _unseed(op.get_bind())

    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(
        "ix_support_ticket_attachments_ticket_id_created_at",
        table_name="support_ticket_attachments",
    )
    op.drop_index(
        op.f("ix_support_ticket_attachments_ticket_id"),
        table_name="support_ticket_attachments",
    )
    op.drop_index(
        op.f("ix_support_ticket_attachments_message_id"),
        table_name="support_ticket_attachments",
    )
    op.drop_index(
        op.f("ix_support_ticket_attachments_deleted_at"),
        table_name="support_ticket_attachments",
    )
    op.drop_table("support_ticket_attachments")
    op.drop_index(
        "ix_support_ticket_status_history_ticket_id_created_at",
        table_name="support_ticket_status_history",
    )
    op.drop_index(
        op.f("ix_support_ticket_status_history_ticket_id"),
        table_name="support_ticket_status_history",
    )
    op.drop_index(
        op.f("ix_support_ticket_status_history_new_status"),
        table_name="support_ticket_status_history",
    )
    op.drop_table("support_ticket_status_history")
    op.drop_index(
        op.f("ix_support_ticket_messages_user_id"), table_name="support_ticket_messages"
    )
    op.drop_index(
        "ix_support_ticket_messages_ticket_id_created_at",
        table_name="support_ticket_messages",
    )
    op.drop_index(
        op.f("ix_support_ticket_messages_ticket_id"),
        table_name="support_ticket_messages",
    )
    op.drop_index(
        op.f("ix_support_ticket_messages_deleted_at"),
        table_name="support_ticket_messages",
    )
    op.drop_table("support_ticket_messages")
    op.drop_index(
        op.f("ix_support_ticket_feedback_ticket_id"),
        table_name="support_ticket_feedback",
    )
    op.drop_table("support_ticket_feedback")
    op.drop_index(
        "ix_support_ticket_assignments_ticket_id_created_at",
        table_name="support_ticket_assignments",
    )
    op.drop_index(
        op.f("ix_support_ticket_assignments_ticket_id"),
        table_name="support_ticket_assignments",
    )
    op.drop_index(
        op.f("ix_support_ticket_assignments_assigned_to"),
        table_name="support_ticket_assignments",
    )
    op.drop_table("support_ticket_assignments")
    op.drop_index(
        op.f("ix_support_ticket_activities_user_id"),
        table_name="support_ticket_activities",
    )
    op.drop_index(
        "ix_support_ticket_activities_ticket_id_created_at",
        table_name="support_ticket_activities",
    )
    op.drop_index(
        op.f("ix_support_ticket_activities_ticket_id"),
        table_name="support_ticket_activities",
    )
    op.drop_index(
        op.f("ix_support_ticket_activities_activity_type"),
        table_name="support_ticket_activities",
    )
    op.drop_table("support_ticket_activities")
    op.drop_index(op.f("ix_support_tickets_ticket_no"), table_name="support_tickets")
    op.drop_index("ix_support_tickets_student_id_status", table_name="support_tickets")
    op.drop_index(op.f("ix_support_tickets_student_id"), table_name="support_tickets")
    op.drop_index("ix_support_tickets_status_priority", table_name="support_tickets")
    op.drop_index(op.f("ix_support_tickets_status"), table_name="support_tickets")
    op.drop_index(op.f("ix_support_tickets_priority"), table_name="support_tickets")
    op.drop_index(
        op.f("ix_support_tickets_merged_into_id"), table_name="support_tickets"
    )
    op.drop_index(
        op.f("ix_support_tickets_last_reply_at"), table_name="support_tickets"
    )
    op.drop_index(op.f("ix_support_tickets_is_escalated"), table_name="support_tickets")
    op.drop_index(op.f("ix_support_tickets_deleted_at"), table_name="support_tickets")
    op.drop_index("ix_support_tickets_created_at", table_name="support_tickets")
    op.drop_index(op.f("ix_support_tickets_category_id"), table_name="support_tickets")
    op.drop_index("ix_support_tickets_assigned_to_status", table_name="support_tickets")
    op.drop_index(op.f("ix_support_tickets_assigned_to"), table_name="support_tickets")
    op.drop_table("support_tickets")
    # ### end Alembic commands ###
