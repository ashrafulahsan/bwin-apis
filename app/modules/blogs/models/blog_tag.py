"""The blog-tag mapping table.

Tags are ordinary categories from the `blog_tag` taxonomy, so this joins
`blogs` to `categories` rather than to a table of its own. Many-to-many
because a post about migrating a database is legitimately tagged `postgres`,
`alembic` and `python` at once.

Carries a surrogate `id` primary key, matching every other table in the
schema; the `UNIQUE (blog_id, tag_id)` constraint is what stops the same tag
being attached twice.
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Table,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811

from app.core.database import Base

blog_tags = Table(
    "blog_tags",
    Base.metadata,
    Column(
        "id",
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    ),
    Column(
        "blog_id",
        PgUUID(as_uuid=True),
        # `CASCADE`: these rows describe the post and have no meaning without
        # it. Posts are soft deleted, so this only fires on a genuine purge.
        ForeignKey("blogs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "tag_id",
        PgUUID(as_uuid=True),
        # `RESTRICT`, matching the categories module: a tag that posts are
        # filed under cannot be dropped out from under them.
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
    UniqueConstraint("blog_id", "tag_id", name="uq_blog_tags_blog_tag"),
    # Covers "which posts carry this tag", the reverse of the unique index.
    Index("ix_blog_tags_tag_id", "tag_id"),
)
