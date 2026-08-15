"""add settings table and social login columns

Adds the `settings` table that holds runtime configuration, and the
denormalized social columns on `users`.

Two details autogenerate does not get right on its own:

- `is_social_login` is NOT NULL, and the table already has rows. It is added
  with a server default so the existing rows get a value, and the default is
  dropped afterwards so the schema matches the model.
- The new columns are backfilled from `user_identities`, which is the source
  of truth. Without that, an account that already signed in with Google would
  come out of this migration looking like a password-only account.

Revision ID: e772640a005f
Revises: acc052757d68
Create Date: 2026-08-15 16:04:41.523165

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e772640a005f"
down_revision: str | None = "acc052757d68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply this revision."""
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("value_type", sa.String(length=20), nullable=False),
        sa.Column("group", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_secret", sa.Boolean(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_settings")),
    )
    op.create_index(op.f("ix_settings_group"), "settings", ["group"], unique=False)
    op.create_index(op.f("ix_settings_key"), "settings", ["key"], unique=True)

    op.add_column("users", sa.Column("google_id", sa.String(length=255), nullable=True))
    op.add_column(
        "users", sa.Column("facebook_id", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "users", sa.Column("social_provider", sa.String(length=30), nullable=True)
    )
    # The server default is what lets this be added to a table that already
    # has rows, and it is kept afterwards: the column is NOT NULL, so anything
    # inserting a user without going through the ORM would otherwise fail.
    op.add_column(
        "users",
        sa.Column(
            "is_social_login",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    _backfill_social_columns()

    # Unique: one Google account must never point at two platform accounts.
    op.create_index(op.f("ix_users_facebook_id"), "users", ["facebook_id"], unique=True)
    op.create_index(op.f("ix_users_google_id"), "users", ["google_id"], unique=True)
    op.create_index(
        op.f("ix_users_is_social_login"), "users", ["is_social_login"], unique=False
    )

    _seed_settings()


def _backfill_social_columns() -> None:
    """Fill the new columns from the identities already linked."""
    connection = op.get_bind()

    for provider, column in (("google", "google_id"), ("facebook", "facebook_id")):
        connection.execute(
            sa.text(f"""
                UPDATE users AS u
                SET {column} = i.provider_user_id
                FROM user_identities AS i
                WHERE i.user_id = u.id AND i.provider = :provider
                """),
            {"provider": provider},
        )

    # The oldest link is the provider the account arrived through.
    connection.execute(
        sa.text("""
            UPDATE users AS u
            SET social_provider = first_link.provider,
                is_social_login = true
            FROM (
                SELECT DISTINCT ON (user_id) user_id, provider
                FROM user_identities
                ORDER BY user_id, created_at
            ) AS first_link
            WHERE first_link.user_id = u.id
            """)
    )


#: Copied here rather than imported from `app.modules.settings.constants`,
#: because a migration must keep applying the same data even after the
#: application code moves on. Credentials are deliberately blank: real ones
#: belong to whoever runs the platform, never to the repository.
SYSTEM_SETTINGS = [
    {
        "key": "app_base_url",
        "value": "http://127.0.0.1:8000",
        "value_type": "string",
        "group": "general",
        "label": "API base URL",
        "description": "Public origin of this API, used to build OAuth callbacks.",
        "is_secret": False,
    },
    {
        "key": "frontend_url",
        "value": "http://localhost:3000",
        "value_type": "string",
        "group": "general",
        "label": "Frontend URL",
        "description": "Where a browser is sent once a social sign-in completes.",
        "is_secret": False,
    },
    {
        "key": "social_login_redirect_path",
        "value": "/auth/callback",
        "value_type": "string",
        "group": "general",
        "label": "Social sign-in redirect path",
        "description": "Appended to the frontend URL after a social sign-in.",
        "is_secret": False,
    },
    {
        "key": "google_auth_enabled",
        "value": "false",
        "value_type": "boolean",
        "group": "google_auth",
        "label": "Enable Google sign-in",
        "description": "Off until a client ID and secret have been filled in.",
        "is_secret": False,
    },
    {
        "key": "google_client_id",
        "value": None,
        "value_type": "string",
        "group": "google_auth",
        "label": "Google client ID",
        "description": "From the Google Cloud console, OAuth 2.0 Client IDs.",
        "is_secret": False,
    },
    {
        "key": "google_client_secret",
        "value": None,
        "value_type": "string",
        "group": "google_auth",
        "label": "Google client secret",
        "description": "Issued alongside the client ID. Never leaves the server.",
        "is_secret": True,
    },
    {
        "key": "google_callback_url",
        "value": None,
        "value_type": "string",
        "group": "google_auth",
        "label": "Google callback URL",
        "description": (
            "Must match an authorized redirect URI exactly. Left blank, it is "
            "derived from the API base URL."
        ),
        "is_secret": False,
    },
    {
        "key": "facebook_auth_enabled",
        "value": "false",
        "value_type": "boolean",
        "group": "facebook_auth",
        "label": "Enable Facebook sign-in",
        "description": "Off until an app ID and secret have been filled in.",
        "is_secret": False,
    },
    {
        "key": "facebook_app_id",
        "value": None,
        "value_type": "string",
        "group": "facebook_auth",
        "label": "Facebook app ID",
        "description": "From the Meta for Developers dashboard.",
        "is_secret": False,
    },
    {
        "key": "facebook_app_secret",
        "value": None,
        "value_type": "string",
        "group": "facebook_auth",
        "label": "Facebook app secret",
        "description": "Issued alongside the app ID. Never leaves the server.",
        "is_secret": True,
    },
    {
        "key": "facebook_callback_url",
        "value": None,
        "value_type": "string",
        "group": "facebook_auth",
        "label": "Facebook callback URL",
        "description": (
            "Must match a valid OAuth redirect URI exactly. Left blank, it is "
            "derived from the API base URL."
        ),
        "is_secret": False,
    },
]


def _seed_settings() -> None:
    """Insert the built-in settings, leaving any that already exist alone."""
    connection = op.get_bind()

    for setting in SYSTEM_SETTINGS:
        connection.execute(
            sa.text("""
                INSERT INTO settings (
                    key, value, value_type, "group", label, description,
                    is_secret, is_system
                )
                VALUES (
                    :key, :value, :value_type, :group, :label, :description,
                    :is_secret, true
                )
                ON CONFLICT (key) DO NOTHING
                """),
            setting,
        )


def downgrade() -> None:
    """Revert this revision."""
    op.drop_index(op.f("ix_users_is_social_login"), table_name="users")
    op.drop_index(op.f("ix_users_google_id"), table_name="users")
    op.drop_index(op.f("ix_users_facebook_id"), table_name="users")
    op.drop_column("users", "is_social_login")
    op.drop_column("users", "social_provider")
    op.drop_column("users", "facebook_id")
    op.drop_column("users", "google_id")
    op.drop_index(op.f("ix_settings_key"), table_name="settings")
    op.drop_index(op.f("ix_settings_group"), table_name="settings")
    op.drop_table("settings")
