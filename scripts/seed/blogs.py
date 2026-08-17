"""The demo blog content: the two taxonomies, and the posts filed under them.

A worked example of the blogs module rather than reference data. Every post
is created as a draft and then moved into its state through `publish` and
`archive`, the same route the API offers, so nothing here is in a shape the
application itself could not produce.

The specs are in `scripts/seed/data/blogs.py`.
"""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.blogs.constants import (
    BLOG_CATEGORY_TYPE_SLUG,
    BLOG_TAG_TYPE_SLUG,
    BlogStatus,
)
from app.modules.blogs.schemas.blog import BlogCreate
from app.modules.blogs.services.blog import BlogService
from app.modules.categories.constants import CategoryStatus
from app.modules.categories.models.category import Category
from app.modules.categories.models.category_type import CategoryType
from app.modules.categories.repositories.category_type import CategoryTypeRepository
from app.modules.categories.schemas.category import CategoryCreate
from app.modules.categories.services.category import CategoryService
from app.modules.users.repositories.user import UserRepository
from app.shared.schemas.seo import SEOMetadata
from app.shared.utils.dates import utc_now
from scripts.seed.base import AllPages, Seeder, SeedOptions, heading
from scripts.seed.data.blogs import (
    DEMO_BLOG_CATEGORIES,
    DEMO_BLOG_TAGS,
    DEMO_BLOGS,
    DemoCategory,
)


async def _taxonomy(session: AsyncSession, slug: str) -> CategoryType:
    """One of the two category types a blog post draws its vocabulary from."""
    found = await CategoryTypeRepository(session).get_by_slug(slug)

    if found is None:
        raise SystemExit(
            f"Category type '{slug}' is missing. Run `alembic upgrade head` first."
        )

    return found


def _named(known: dict[str, Category], name: str, label: str) -> Category:
    """Look a seeded category up by name, saying which spec is wrong if not."""
    found = known.get(name)

    if found is None:
        raise SystemExit(f"No seeded blog {label} named '{name}'.")

    return found


async def seed_blog_vocabulary(
    session: AsyncSession, type_slug: str, specs: list[DemoCategory]
) -> tuple[dict[str, Category], list[str]]:
    """Create any category in `specs` its taxonomy does not have yet.

    Returns every category in the taxonomy keyed by name, along with the
    names created. Keyed by name rather than slug because a name is what a
    spec refers to its parent by, and what the table's unique constraint is
    written against - a slug may have picked up a `-2` on the way in.
    """
    taxonomy = await _taxonomy(session, type_slug)
    service = CategoryService(session)

    known = {
        row.name: row for row in await service.repository.list_for_type(taxonomy.id)
    }
    created: list[str] = []

    for spec in specs:
        name = spec["name"]

        if name in known:
            continue

        parent_name = spec.get("parent")
        parent = _named(known, parent_name, "category") if parent_name else None

        known[name] = await service.create(
            CategoryCreate(
                name=name,
                description=spec.get("description"),
                category_type_id=taxonomy.id,
                parent_category_id=parent.id if parent else None,
                status=spec.get("status", CategoryStatus.ACTIVE),
            )
        )
        created.append(name)

    return known, created


async def seed_demo_blogs(
    session: AsyncSession,
    categories: dict[str, Category],
    tags: dict[str, Category],
) -> list[str]:
    """Create any demo post that is missing. Returns the slugs created.

    Every post is created as a draft and then moved into the state its spec
    asks for, which is the only route the application itself offers: it means
    a scheduled or archived post here has a publication date set by the
    transition, exactly as an editor's would.
    """
    blogs = BlogService(session)
    users = UserRepository(session)
    created: list[str] = []

    for spec in DEMO_BLOGS:
        slug = spec["slug"]

        if await blogs.repository.get_by_slug(slug) is not None:
            continue

        author = await users.get_by_email(spec["author"])
        # Missing only when the users seeder was left out. The post is still
        # worth having, it just carries no byline.
        author_id = author.id if author else None

        image_url, image_alt = spec.get("image", (None, None))

        blog = await blogs.create(
            BlogCreate(
                title=spec["title"],
                slug=slug,
                excerpt=spec["excerpt"],
                content=spec["content"],
                blog_category_id=_named(categories, spec["category"], "category").id,
                tag_ids=[_named(tags, name, "tag").id for name in spec.get("tags", [])],
                featured_image_url=image_url,
                featured_image_alt=image_alt,
                is_featured=spec.get("featured", False),
                author_id=author_id,
                # Only the keywords are given. Everything else a client needs
                # in `<head>` is derived from the post - meta title from the
                # title, description from the excerpt, Open Graph image from
                # the cover - and demo data that filled all eight columns in
                # would hide that.
                seo=SEOMetadata(
                    meta_keywords=spec.get("keywords"),
                    meta_robots=spec.get("robots"),
                ),
            ),
            actor_id=author_id,
        )

        status = spec.get("status", BlogStatus.DRAFT)
        if status is not BlogStatus.DRAFT:
            # Archived posts are published first: one that was never live
            # would have no publication date, and nothing in the application
            # can produce that state.
            await blogs.publish(
                blog.id,
                published_at=utc_now() + timedelta(days=spec.get("days", 0)),
                actor_id=author_id,
            )

            if status is BlogStatus.ARCHIVED:
                await blogs.archive(blog.id, actor_id=author_id)

        created.append(slug)

    return created


async def seed_blog_content(session: AsyncSession) -> dict[str, int]:
    """The blog taxonomies and the demo posts filed under them."""
    categories, new_categories = await seed_blog_vocabulary(
        session, BLOG_CATEGORY_TYPE_SLUG, DEMO_BLOG_CATEGORIES
    )
    tags, new_tags = await seed_blog_vocabulary(
        session, BLOG_TAG_TYPE_SLUG, DEMO_BLOG_TAGS
    )

    posts = await seed_demo_blogs(session, categories, tags)

    return {
        "categories": len(new_categories),
        "tags": len(new_tags),
        "posts": len(posts),
    }


class BlogSeeder(Seeder):
    name = "blogs"
    description = "Blog categories, tags and posts, in every publication state."
    # A post carries the byline of the account that would have written it.
    requires = ("users",)

    async def run(self, session: AsyncSession, options: SeedOptions) -> dict[str, int]:
        return await seed_blog_content(session)

    async def report(self, session: AsyncSession, options: SeedOptions) -> None:
        """How many posts are in each state a listing can filter on."""
        blogs = BlogService(session)

        states: tuple[tuple[str, dict[str, object]], ...] = (
            ("draft", {"status": BlogStatus.DRAFT}),
            ("published", {"status": BlogStatus.PUBLISHED}),
            ("archived", {"status": BlogStatus.ARCHIVED}),
            # Published and dated in the past, which is the subset a reader
            # sees; the rest of `published` is scheduled.
            ("live now", {"live_only": True}),
            ("featured", {"featured_only": True}),
        )

        heading("BLOG POSTS        COUNT")

        for label, filters in states:
            _, total = await blogs.list_blogs(AllPages(), **filters)
            print(f"  {label:<18}{total:>4}")
