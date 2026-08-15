"""seed permissions and default grants

Seeds the built-in permissions and the starting grant matrix, so a fresh
environment comes up with working roles rather than seven empty shells.

The definitions are duplicated here rather than imported from
`app.modules.permissions.constants`, because a migration must keep applying the
same data even after the application code moves on.

Revision ID: 9a71b73cfa28
Revises: d9b531a063d1
Create Date: 2026-08-15 11:36:56.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a71b73cfa28"
down_revision: str | None = "d9b531a063d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SYSTEM_PERMISSIONS: dict[str, list[str]] = {
    "user": ["view", "create", "update", "delete"],
    "role": ["view", "create", "update", "delete", "assign"],
    "permission": ["view", "create", "update", "delete", "assign"],
    "course": ["view", "create", "update", "delete", "publish"],
    "lesson": ["view", "create", "update", "delete"],
    "enrollment": ["view", "create", "delete", "grade"],
    "page": ["view", "create", "update", "delete", "publish"],
    "media": ["view", "upload", "delete"],
    "category": ["view", "create", "update", "delete"],
    "translation": ["view", "create", "update", "delete", "import"],
    "setting": ["view", "update"],
    "report": ["view", "export"],
    "notification": ["view", "send"],
}

ACTION_LABELS = {
    "view": "View",
    "create": "Create",
    "update": "Update",
    "delete": "Delete",
    "publish": "Publish",
    "assign": "Assign",
    "upload": "Upload",
    "import": "Import",
    "export": "Export",
    "grade": "Grade",
    "send": "Send",
}

RESOURCE_LABELS = {
    "user": "users",
    "role": "roles",
    "permission": "permissions",
    "course": "courses",
    "lesson": "lessons",
    "enrollment": "enrolments",
    "page": "pages",
    "media": "media",
    "category": "categories",
    "translation": "translations",
    "setting": "settings",
    "report": "reports",
    "notification": "notifications",
}


def _codes(resource: str, *actions: str) -> list[str]:
    return [f"{resource}.{action}" for action in actions]


ALL_PERMISSIONS = "*"

DEFAULT_ROLE_PERMISSIONS: dict[str, list[str] | str] = {
    "super-admin": ALL_PERMISSIONS,
    "admin": [
        *_codes("user", "view", "create", "update", "delete"),
        *_codes("role", "view", "create", "update", "delete", "assign"),
        *_codes("permission", "view", "assign"),
        *_codes("course", "view", "create", "update", "delete", "publish"),
        *_codes("lesson", "view", "create", "update", "delete"),
        *_codes("enrollment", "view", "create", "delete", "grade"),
        *_codes("page", "view", "create", "update", "delete", "publish"),
        *_codes("media", "view", "upload", "delete"),
        *_codes("category", "view", "create", "update", "delete"),
        *_codes("translation", "view", "create", "update", "delete", "import"),
        *_codes("setting", "view", "update"),
        *_codes("report", "view", "export"),
        *_codes("notification", "view", "send"),
    ],
    "content-manager": [
        *_codes("page", "view", "create", "update", "delete", "publish"),
        *_codes("media", "view", "upload", "delete"),
        *_codes("category", "view", "create", "update", "delete"),
        *_codes("translation", "view", "update"),
        *_codes("course", "view"),
        *_codes("report", "view"),
    ],
    "editor": [
        *_codes("page", "view", "create", "update"),
        *_codes("media", "view", "upload"),
        *_codes("category", "view"),
        *_codes("translation", "view"),
        *_codes("course", "view"),
    ],
    "instructor": [
        *_codes("course", "view", "create", "update"),
        *_codes("lesson", "view", "create", "update", "delete"),
        *_codes("enrollment", "view", "grade"),
        *_codes("media", "view", "upload"),
        *_codes("report", "view"),
    ],
    "support": [
        *_codes("user", "view"),
        *_codes("course", "view"),
        *_codes("enrollment", "view"),
        *_codes("page", "view"),
        *_codes("notification", "view", "send"),
        *_codes("report", "view"),
    ],
    "student": [
        *_codes("course", "view"),
        *_codes("lesson", "view"),
        *_codes("enrollment", "view"),
        *_codes("page", "view"),
    ],
}


def upgrade() -> None:
    """Insert the built-in permissions, then apply the default grants."""
    connection = op.get_bind()

    for resource, actions in SYSTEM_PERMISSIONS.items():
        for action in actions:
            connection.execute(
                sa.text("""
                    INSERT INTO permissions
                        (code, resource, action, name, is_system)
                    VALUES (:code, :resource, :action, :name, true)
                    ON CONFLICT (code) DO NOTHING
                    """),
                {
                    "code": f"{resource}.{action}",
                    "resource": resource,
                    "action": action,
                    "name": (
                        f"{ACTION_LABELS[action]} "
                        f"{RESOURCE_LABELS.get(resource, resource)}"
                    ),
                },
            )

    for slug, codes in DEFAULT_ROLE_PERMISSIONS.items():
        if codes == ALL_PERMISSIONS:
            connection.execute(
                sa.text("""
                    INSERT INTO role_permissions (role_id, permission_id)
                    SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
                    WHERE r.slug = :slug
                    ON CONFLICT DO NOTHING
                    """),
                {"slug": slug},
            )
            continue

        connection.execute(
            sa.text("""
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT r.id, p.id FROM roles r JOIN permissions p ON true
                WHERE r.slug = :slug AND p.code = ANY(:codes)
                ON CONFLICT DO NOTHING
                """),
            {"slug": slug, "codes": list(codes)},
        )


def downgrade() -> None:
    """Remove the grants and the seeded permissions."""
    connection = op.get_bind()

    connection.execute(sa.text("""
            DELETE FROM role_permissions
            WHERE permission_id IN (SELECT id FROM permissions WHERE is_system = true)
            """))
    connection.execute(sa.text("DELETE FROM permissions WHERE is_system = true"))
