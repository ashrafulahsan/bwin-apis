"""seed master crud permissions

Two resources rather than one, because the module holds two jobs that belong
to different people. `master_crud_field.*` designs the form - it changes what
every record in a category means, and a careless edit invalidates data already
stored. `master_crud.*` fills the form in, which is ordinary content work.

So the grants are not parallel: content managers get every record permission
but only `master_crud_field.view`, and editors write records without deleting
them, exactly as they write pages and posts without publishing. Designing a
form stays with administrators.

No categories are seeded. Which categories carry master CRUD records, and what
they ask, is entirely an editorial decision - the module works against any
category the platform already has.

The definitions are duplicated here rather than imported from
`app.modules.permissions.constants`, matching the other seeding revisions: a
migration must keep applying the same data even after the application moves
on.

Revision ID: 15e2aac57903
Revises: 945488541a49
Create Date: 2026-08-18 16:01:32.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "15e2aac57903"
down_revision: str | None = "945488541a49"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ACTIONS = ["view", "create", "update", "delete"]

ACTION_LABELS = {
    "view": "View",
    "create": "Create",
    "update": "Update",
    "delete": "Delete",
}

#: `resource -> (label used in permission names, roles and their actions)`.
RESOURCES = {
    "master_crud": (
        "master CRUD records",
        {
            "super-admin": ACTIONS,
            "admin": ACTIONS,
            "content-manager": ACTIONS,
            # Writes and revises records but does not remove them, exactly as
            # the role writes pages and posts without publishing them.
            "editor": ["view", "create", "update"],
            "support": ["view"],
            "student": ["view"],
        },
    ),
    "master_crud_field": (
        "master CRUD fields",
        {
            "super-admin": ACTIONS,
            "admin": ACTIONS,
            # Reads the form definition in order to fill it in; changing it
            # would change what every stored answer means.
            "content-manager": ["view"],
            "editor": ["view"],
        },
    ),
}


def upgrade() -> None:
    """Insert the permissions, then their grants."""
    connection = op.get_bind()

    for resource, (label, grants) in RESOURCES.items():
        for action in ACTIONS:
            connection.execute(
                sa.text("""
                    INSERT INTO permissions (code, resource, action, name, is_system)
                    VALUES (:code, :resource, :action, :name, true)
                    ON CONFLICT (code) DO NOTHING
                    """),
                {
                    "code": f"{resource}.{action}",
                    "resource": resource,
                    "action": action,
                    "name": f"{ACTION_LABELS[action]} {label}",
                },
            )

        for slug, actions in grants.items():
            connection.execute(
                sa.text("""
                    INSERT INTO role_permissions (role_id, permission_id)
                    SELECT r.id, p.id FROM roles r JOIN permissions p ON true
                    WHERE r.slug = :slug AND p.code = ANY(:codes)
                    ON CONFLICT DO NOTHING
                    """),
                {"slug": slug, "codes": [f"{resource}.{action}" for action in actions]},
            )


def downgrade() -> None:
    """Remove the grants and the permissions."""
    connection = op.get_bind()

    resources = list(RESOURCES)

    connection.execute(
        sa.text("""
            DELETE FROM role_permissions
            WHERE permission_id IN (
                SELECT id FROM permissions WHERE resource = ANY(:resources)
            )
            """),
        {"resources": resources},
    )
    connection.execute(
        sa.text("DELETE FROM permissions WHERE resource = ANY(:resources)"),
        {"resources": resources},
    )
