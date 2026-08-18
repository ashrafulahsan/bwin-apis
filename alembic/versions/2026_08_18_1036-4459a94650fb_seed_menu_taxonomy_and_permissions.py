"""seed menu taxonomy and permissions

Two pieces of reference data the menus module cannot work without.

**The taxonomy.** A menu item's `menu_category_id` points at a row in
`categories` from the Menu Category type, which is what says whether an item
belongs to the main bar, the footer or a sidebar. The row is inserted with an
explicit id rather than a generated one: the identifier was specified, code
refers to it as `MENU_CATEGORY_TYPE_ID`, and every environment has to resolve
the same taxonomy. `created_by` is left null - nobody created it, the platform
ships with it.

The categories filed under it are not seeded. Which navigations a site has is
an editorial decision, and an administrator creates them through
`POST /categories` with this type.

**The permissions.** `menu.*` mirrors `category.*` in shape but not in who
holds it. Arranging a navigation is content work, so content managers get the
full set and editors get `menu.view`; the *vocabulary* of menu categories
stays with the administrators who own the categories module.

The definitions are duplicated here rather than imported from
`app.modules.menus.constants`, matching the other seeding revisions: a
migration must keep applying the same data even after the application moves
on.

Revision ID: 4459a94650fb
Revises: 5250e9d445c9
Create Date: 2026-08-18 10:36:47.736270

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4459a94650fb"
down_revision: str | None = "5250e9d445c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The category type every menu item draws its category from, pinned to the
#: identifier the module refers to.
MENU_CATEGORY_TYPE_ID = "ae340508-652a-414a-b5b9-2daf24a728d8"
MENU_CATEGORY_TYPE_SLUG = "menu_category"
MENU_CATEGORY_TYPE_NAME = "Menu Category"
MENU_CATEGORY_TYPE_DESCRIPTION = (
    "Which navigation a menu item belongs to - the main bar, the footer, a "
    "sidebar. One category per navigation."
)

MENU_ACTIONS = ["view", "create", "update", "delete"]

ACTION_LABELS = {
    "view": "View",
    "create": "Create",
    "update": "Update",
    "delete": "Delete",
}

#: Which roles get which menu permissions. Content managers arrange the
#: navigation; editors see it but do not rearrange it.
MENU_GRANTS = {
    "super-admin": MENU_ACTIONS,
    "admin": MENU_ACTIONS,
    "content-manager": MENU_ACTIONS,
    "editor": ["view"],
    "support": ["view"],
    "student": ["view"],
}


def upgrade() -> None:
    """Insert the taxonomy, then the permissions and their grants."""
    connection = op.get_bind()

    # `DO NOTHING` on any conflict rather than on the slug alone: a database
    # that already carries this taxonomy - under this id with a name of its
    # own, or under this slug with an id of its own - keeps what it has. The
    # module resolves the type by id and falls back to the slug, so either
    # shape works, and overwriting an administrator's naming would not.
    connection.execute(
        sa.text("""
            INSERT INTO category_types (id, name, slug, description, status)
            VALUES (:id, :name, :slug, :description, 'active')
            ON CONFLICT DO NOTHING
            """),
        {
            "id": MENU_CATEGORY_TYPE_ID,
            "name": MENU_CATEGORY_TYPE_NAME,
            "slug": MENU_CATEGORY_TYPE_SLUG,
            "description": MENU_CATEGORY_TYPE_DESCRIPTION,
        },
    )

    for action in MENU_ACTIONS:
        connection.execute(
            sa.text("""
                INSERT INTO permissions (code, resource, action, name, is_system)
                VALUES (:code, 'menu', :action, :name, true)
                ON CONFLICT (code) DO NOTHING
                """),
            {
                "code": f"menu.{action}",
                "action": action,
                "name": f"{ACTION_LABELS[action]} menu items",
            },
        )

    for slug, actions in MENU_GRANTS.items():
        connection.execute(
            sa.text("""
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT r.id, p.id FROM roles r JOIN permissions p ON true
                WHERE r.slug = :slug AND p.code = ANY(:codes)
                ON CONFLICT DO NOTHING
                """),
            {"slug": slug, "codes": [f"menu.{action}" for action in actions]},
        )


def downgrade() -> None:
    """Remove the grants, the permissions, and the taxonomy.

    The taxonomy is only removed when nothing is filed under it. Dropping a
    category type that still holds categories would fail on the foreign key
    anyway, and cascading it would take an administrator's own navigations
    with it - this revision seeded one row, not everything since put in it.
    """
    connection = op.get_bind()

    connection.execute(sa.text("""
            DELETE FROM role_permissions
            WHERE permission_id IN (SELECT id FROM permissions WHERE resource = 'menu')
            """))
    connection.execute(sa.text("DELETE FROM permissions WHERE resource = 'menu'"))

    connection.execute(
        sa.text("""
            DELETE FROM category_types ct
            WHERE ct.slug = :slug
              AND NOT EXISTS (
                  SELECT 1 FROM categories c WHERE c.category_type_id = ct.id
              )
            """),
        {"slug": MENU_CATEGORY_TYPE_SLUG},
    )
