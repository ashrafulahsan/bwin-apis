"""seed blog taxonomies and permissions

Two pieces of reference data the blogs module cannot work without.

**The taxonomies.** A post draws its category from `blog_category` and its
tags from `blog_tag`, and the code looks both up by slug. Seeding them here
means a fresh database comes up working, rather than needing an administrator
to guess two exact names. The slugs use underscores because that is how they
were specified; everything else in the module derives them from these
constants, so nothing depends on the spelling by hand.

The rows are inserted with `created_by` left null: nobody created them, the
platform ships with them.

**The permissions.** `blog.*` mirrors `page.*`, including publishing as a code
of its own - an Editor writes and revises but does not decide what goes live,
which only means something if the transition is guarded separately. Grants go
to the same roles that hold the equivalent page permission, so the two content
types behave alike.

The definitions are duplicated here rather than imported from
`app.modules.blogs.constants`, matching the other seeding revisions: a
migration must keep applying the same data even after the application moves
on.

Revision ID: 34b19ea310f8
Revises: 1ec7fb0c4bb7
Create Date: 2026-08-15 18:53:03.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "34b19ea310f8"
down_revision: str | None = "1ec7fb0c4bb7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: `(slug, name, description)` for each taxonomy a blog post draws on.
BLOG_TAXONOMIES = [
    (
        "blog_category",
        "Blog Category",
        "What a blog post is about. One per post.",
    ),
    (
        "blog_tag",
        "Blog Tag",
        "Finer grained labels for a blog post. Any number per post.",
    ),
]

BLOG_ACTIONS = ["view", "create", "update", "delete", "publish"]

ACTION_LABELS = {
    "view": "View",
    "create": "Create",
    "update": "Update",
    "delete": "Delete",
    "publish": "Publish",
}

#: Which roles get which blog permissions, mirroring the `page` grants.
BLOG_GRANTS = {
    "super-admin": BLOG_ACTIONS,
    "admin": BLOG_ACTIONS,
    "content-manager": BLOG_ACTIONS,
    # Writes and revises, but does not publish.
    "editor": ["view", "create", "update"],
    "support": ["view"],
    "student": ["view"],
}


def upgrade() -> None:
    """Insert the two taxonomies, then the permissions and their grants."""
    connection = op.get_bind()

    for slug, name, description in BLOG_TAXONOMIES:
        connection.execute(
            sa.text("""
                INSERT INTO category_types (name, slug, description, status)
                VALUES (:name, :slug, :description, 'active')
                ON CONFLICT (slug) DO NOTHING
                """),
            {"slug": slug, "name": name, "description": description},
        )

    for action in BLOG_ACTIONS:
        connection.execute(
            sa.text("""
                INSERT INTO permissions (code, resource, action, name, is_system)
                VALUES (:code, 'blog', :action, :name, true)
                ON CONFLICT (code) DO NOTHING
                """),
            {
                "code": f"blog.{action}",
                "action": action,
                "name": f"{ACTION_LABELS[action]} blog posts",
            },
        )

    for slug, actions in BLOG_GRANTS.items():
        connection.execute(
            sa.text("""
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT r.id, p.id FROM roles r JOIN permissions p ON true
                WHERE r.slug = :slug AND p.code = ANY(:codes)
                ON CONFLICT DO NOTHING
                """),
            {"slug": slug, "codes": [f"blog.{action}" for action in actions]},
        )


def downgrade() -> None:
    """Remove the grants, the permissions, and the taxonomies.

    The taxonomies are only removed when nothing is filed under them. Dropping
    a category type that still holds categories would fail on the foreign key
    anyway, and cascading it would take an administrator's own vocabulary with
    it - this revision seeded the two rows, not everything since put in them.
    """
    connection = op.get_bind()

    connection.execute(
        sa.text("""
            DELETE FROM role_permissions
            WHERE permission_id IN (SELECT id FROM permissions WHERE resource = 'blog')
            """)
    )
    connection.execute(sa.text("DELETE FROM permissions WHERE resource = 'blog'"))

    connection.execute(
        sa.text("""
            DELETE FROM category_types ct
            WHERE ct.slug = ANY(:slugs)
              AND NOT EXISTS (
                  SELECT 1 FROM categories c WHERE c.category_type_id = ct.id
              )
            """),
        {"slugs": [slug for slug, _, _ in BLOG_TAXONOMIES]},
    )
