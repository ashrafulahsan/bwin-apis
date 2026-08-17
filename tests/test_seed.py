"""Tests for the seeding script."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.blogs.constants import (
    BLOG_CATEGORY_TYPE_NAME,
    BLOG_CATEGORY_TYPE_SLUG,
    BLOG_TAG_TYPE_NAME,
    BLOG_TAG_TYPE_SLUG,
    BlogStatus,
)
from app.modules.blogs.models.blog import Blog
from app.modules.blogs.models.blog_tag import blog_tags
from app.modules.blogs.repositories.blog import BlogRepository
from app.modules.blogs.schemas.blog import BlogRead
from app.modules.categories.constants import CategoryStatus
from app.modules.categories.models.category import Category
from app.modules.categories.models.category_type import CategoryType
from app.modules.categories.repositories.category import CategoryRepository
from app.modules.categories.repositories.category_type import CategoryTypeRepository
from app.modules.permissions.models.permission import Permission
from app.modules.permissions.models.role_permission import role_permissions
from app.modules.roles.models.role import Role
from app.modules.roles.services.role import RoleService
from app.modules.users.constants import UserStatus
from app.modules.users.models.user import User
from app.modules.users.models.user_identity import UserIdentity
from app.modules.users.models.user_role import user_roles
from app.modules.users.repositories.user import UserRepository
from scripts.seed import (
    DEMO_BLOG_CATEGORIES,
    DEMO_BLOG_TAGS,
    DEMO_BLOGS,
    DEMO_USERS,
    seed_blog_content,
    seed_demo_users,
    seed_reference_data,
)

PASSWORD = "SeedTest#2026"


@pytest.fixture
async def seeded(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """A database seeded exactly as the script leaves it."""

    async def wipe() -> None:
        await session.execute(delete(user_roles))
        await session.execute(delete(UserIdentity))
        await session.execute(delete(User))
        await session.execute(delete(role_permissions))
        await session.execute(delete(Permission))
        await session.execute(delete(Role))
        await session.commit()

    await wipe()
    await seed_reference_data(session)
    await seed_demo_users(session, PASSWORD)

    yield session

    await wipe()


async def test_every_role_has_at_least_one_user(seeded: AsyncSession) -> None:
    """The point of the demo data: no role is left without an account."""
    roles = await RoleService(seeded).list_all()
    assert len(roles) == 7

    for role in roles:
        holders = await seeded.execute(
            select(user_roles.c.user_id).where(user_roles.c.role_id == role.id)
        )
        assert holders.first() is not None, f"no user holds '{role.slug}'"


async def test_all_demo_users_are_created(seeded: AsyncSession) -> None:
    total = await seeded.execute(select(User))

    assert len(list(total.scalars().all())) == len(DEMO_USERS)


async def test_seeding_users_twice_creates_nothing(seeded: AsyncSession) -> None:
    """The script is safe to re-run against an existing database."""
    created = await seed_demo_users(seeded, PASSWORD)

    assert created == []


async def test_reference_data_seeding_is_idempotent(seeded: AsyncSession) -> None:
    counts = await seed_reference_data(seeded)

    assert counts["roles"] == 0
    assert counts["permissions"] == 0


async def test_demo_accounts_can_sign_in_with_either_identifier(
    seeded: AsyncSession,
) -> None:
    repository = UserRepository(seeded)

    by_email = await repository.get_by_identifier("student@bwin.example.com")
    by_phone = await repository.get_by_identifier("+8801700000007")

    assert by_email is not None
    assert by_phone is not None
    assert by_email.id == by_phone.id


async def test_demo_accounts_can_sign_in_with_a_local_phone_number(
    seeded: AsyncSession,
) -> None:
    """The format a Bangladeshi user actually types."""
    found = await UserRepository(seeded).get_by_identifier("01700000007")

    assert found is not None
    assert found.email == "student@bwin.example.com"


async def test_super_admin_holds_every_permission(seeded: AsyncSession) -> None:
    user = await UserRepository(seeded).get_by_email("superadmin@bwin.example.com")
    permissions = await seeded.execute(select(Permission))

    assert user is not None
    assert len(user.permission_codes) == len(list(permissions.scalars().all()))


async def test_editor_cannot_publish(seeded: AsyncSession) -> None:
    user = await UserRepository(seeded).get_by_email("editor@bwin.example.com")

    assert user is not None
    assert user.has_permission("page.update") is True
    assert user.has_permission("page.publish") is False


async def test_the_multi_role_account_combines_permissions(
    seeded: AsyncSession,
) -> None:
    """A single `role_id` column could not express this."""
    user = await UserRepository(seeded).get_by_email("lead.instructor@bwin.example.com")

    assert user is not None
    assert user.role_slugs == {"instructor", "content-manager"}
    assert user.has_permission("course.create") is True
    assert user.has_permission("page.publish") is True


async def test_the_social_account_has_no_password(seeded: AsyncSession) -> None:
    user = await UserRepository(seeded).get_by_email("google.user@bwin.example.com")

    assert user is not None
    assert user.has_password is False
    assert user.linked_providers() == {"google"}
    assert user.email_verified is True


async def test_lifecycle_states_are_represented(seeded: AsyncSession) -> None:
    """Pending and suspended accounts exist, so status filters have data."""
    repository = UserRepository(seeded)

    pending = await repository.get_by_email("pending@bwin.example.com")
    suspended = await repository.get_by_email("suspended@bwin.example.com")

    assert pending is not None
    assert pending.status == UserStatus.PENDING
    assert pending.email_verified is False

    assert suspended is not None
    assert suspended.status == UserStatus.SUSPENDED
    assert suspended.can_sign_in is False


def test_demo_emails_use_a_reserved_domain() -> None:
    """`example.com` is reserved by RFC 2606, so it can never be delivered to."""
    for spec in DEMO_USERS:
        assert spec["email"].endswith("@bwin.example.com")


def test_every_system_role_appears_in_the_demo_data() -> None:
    """A new role added without a demo account would fail here."""
    covered = {slug for spec in DEMO_USERS for slug in spec["roles"]}

    assert covered == {
        "super-admin",
        "admin",
        "content-manager",
        "editor",
        "instructor",
        "support",
        "student",
    }


# -- Blog content -------------------------------------------------------


@pytest.fixture
async def content(seeded: AsyncSession) -> AsyncIterator[AsyncSession]:
    """A database seeded with the demo blog content, users included.

    Built on `seeded` because the posts carry the bylines of the demo
    accounts, so those have to exist first.
    """

    async def wipe() -> None:
        await seeded.execute(delete(blog_tags))
        await seeded.execute(delete(Blog))
        # Children first: the parent pointer is `RESTRICT`, so a single
        # delete of the whole table can trip over its own rows.
        await seeded.execute(
            delete(Category).where(Category.parent_category_id.is_not(None))
        )
        await seeded.execute(delete(Category))
        await seeded.commit()

    async def restore_taxonomies() -> None:
        """Put back what the migration seeds and another module removes.

        The test database is shared, and `tests/test_blogs.py` wipes
        `category_types` wholesale to build its own. The script is right to
        depend on the migration's rows; this only makes sure they are there
        when it looks.
        """
        types = CategoryTypeRepository(seeded)

        for slug, name in (
            (BLOG_CATEGORY_TYPE_SLUG, BLOG_CATEGORY_TYPE_NAME),
            (BLOG_TAG_TYPE_SLUG, BLOG_TAG_TYPE_NAME),
        ):
            if await types.get_by_slug(slug) is None:
                await types.create(
                    name=name, slug=slug, status=CategoryStatus.ACTIVE.value
                )

        await seeded.commit()

    await wipe()
    await restore_taxonomies()
    await seed_blog_content(seeded)

    yield seeded

    await wipe()


async def test_all_demo_posts_are_created(content: AsyncSession) -> None:
    posts = await content.execute(select(Blog))

    assert len(list(posts.scalars().all())) == len(DEMO_BLOGS)


async def test_all_demo_categories_and_tags_are_created(
    content: AsyncSession,
) -> None:
    categories = await content.execute(select(Category))
    expected = len(DEMO_BLOG_CATEGORIES) + len(DEMO_BLOG_TAGS)

    assert len(list(categories.scalars().all())) == expected


async def test_seeding_content_twice_creates_nothing(content: AsyncSession) -> None:
    """The script is safe to re-run against an existing database."""
    counts = await seed_blog_content(content)

    assert counts == {"categories": 0, "tags": 0, "posts": 0}


async def test_every_post_state_a_listing_filters_on_has_data(
    content: AsyncSession,
) -> None:
    """The point of the demo posts: no filter comes back empty."""
    posts = (await content.execute(select(Blog))).scalars().all()

    assert any(post.status == BlogStatus.DRAFT for post in posts)
    assert any(post.status == BlogStatus.ARCHIVED for post in posts)
    assert any(post.is_live for post in posts)
    assert any(post.is_scheduled for post in posts)
    assert any(post.is_featured for post in posts)


async def test_a_posts_category_and_tags_come_from_the_right_taxonomies(
    content: AsyncSession,
) -> None:
    """The rule a foreign key cannot express, checked against the seeded rows."""
    types = await content.execute(select(CategoryType))
    by_id = {row.id: row.slug for row in types.scalars().all()}

    posts = (await content.execute(select(Blog))).scalars().all()

    for post in posts:
        assert by_id[post.category.category_type_id] == BLOG_CATEGORY_TYPE_SLUG
        for tag in post.tags:
            assert by_id[tag.category_type_id] == BLOG_TAG_TYPE_SLUG


async def test_the_category_tree_is_nested(content: AsyncSession) -> None:
    """A flat list would not exercise the tree endpoints at all."""
    categories = (await content.execute(select(Category))).scalars().all()
    tree = {row.name: row for row in categories}

    assert (
        tree["Course Design"].parent_category_id == tree["Teaching and Instruction"].id
    )
    assert tree["Teaching and Instruction"].is_root is True
    # Tags are deliberately flat.
    assert all(tree[spec["name"]].is_root for spec in DEMO_BLOG_TAGS)


async def test_the_retired_category_is_inactive(content: AsyncSession) -> None:
    """Inactive, so the "cannot file a post here" path has something to hit."""
    found = await CategoryRepository(content).get_by_slug("exam-prep")

    assert found is not None
    assert found.status == CategoryStatus.INACTIVE


async def test_the_editors_post_is_still_a_draft(content: AsyncSession) -> None:
    """An Editor holds `blog.update` but not `blog.publish`."""
    post = await BlogRepository(content).get_by_slug(
        "connecting-live-classes-to-the-course-timeline"
    )
    author = await UserRepository(content).get_by_email("editor@bwin.example.com")

    assert post is not None
    assert author is not None
    assert post.author_id == author.id
    assert post.status == BlogStatus.DRAFT
    assert post.published_at is None


async def test_the_scheduled_post_is_published_but_not_live(
    content: AsyncSession,
) -> None:
    post = await BlogRepository(content).get_by_slug(
        "issuing-certificates-students-want-to-share"
    )

    assert post is not None
    assert post.is_published is True
    assert post.is_live is False
    assert post.is_scheduled is True


async def test_the_archived_post_kept_its_publication_date(
    content: AsyncSession,
) -> None:
    """Archived is retired, not unpublished: its URL still has to resolve."""
    post = await BlogRepository(content).get_by_slug(
        "retiring-the-legacy-gradebook-import"
    )

    assert post is not None
    assert post.status == BlogStatus.ARCHIVED
    assert post.published_at is not None
    # Kept out of search, since the current release note replaces it.
    assert post.meta_robots == "noindex, follow"


async def test_seo_metadata_falls_back_to_the_post(content: AsyncSession) -> None:
    """Only keywords are seeded, so the derivation is what fills the rest."""
    post = await BlogRepository(content).get_by_slug(
        "designing-a-course-outline-students-actually-finish"
    )

    assert post is not None
    assert post.meta_title is None

    resolved = BlogRead.from_model(post).seo

    assert resolved.meta_title == post.title
    assert resolved.og_image_url == post.featured_image_url
    assert resolved.meta_keywords is not None
    assert resolved.is_indexable is True


async def test_every_post_carries_a_byline(content: AsyncSession) -> None:
    posts = (await content.execute(select(Blog))).scalars().all()

    assert all(post.author_id is not None for post in posts)


async def test_reading_time_is_estimated_from_the_content(
    content: AsyncSession,
) -> None:
    posts = (await content.execute(select(Blog))).scalars().all()

    assert all(post.reading_minutes >= 1 for post in posts)


def test_demo_categories_list_parents_before_children() -> None:
    """The seeding loop resolves `parent` by name as it goes, in order."""
    seen: set[str] = set()

    for spec in DEMO_BLOG_CATEGORIES:
        parent = spec.get("parent")
        assert parent is None or parent in seen, f"'{spec['name']}' precedes its parent"
        seen.add(spec["name"])


def test_no_tag_reuses_a_category_name() -> None:
    """Allowed, but the second one would quietly take a `-2` slug.

    Names are unique per taxonomy; slugs are unique across the whole
    `categories` table.
    """
    categories = {spec["name"] for spec in DEMO_BLOG_CATEGORIES}
    tags = {spec["name"] for spec in DEMO_BLOG_TAGS}

    assert categories & tags == set()


def test_demo_posts_use_unique_slugs() -> None:
    slugs = [spec["slug"] for spec in DEMO_BLOGS]

    assert len(set(slugs)) == len(slugs)


def test_demo_posts_only_reference_seeded_vocabulary() -> None:
    """A typo in a category or tag name would fail the seed run itself."""
    categories = {spec["name"] for spec in DEMO_BLOG_CATEGORIES}
    tags = {spec["name"] for spec in DEMO_BLOG_TAGS}

    for spec in DEMO_BLOGS:
        assert spec["category"] in categories
        assert set(spec.get("tags", [])) <= tags


def test_demo_posts_are_written_by_demo_accounts() -> None:
    accounts = {user["email"] for user in DEMO_USERS}

    for spec in DEMO_BLOGS:
        assert spec["author"] in accounts


def test_the_inactive_category_holds_no_posts() -> None:
    """The blogs module refuses to file a post under an inactive category."""
    retired = {
        spec["name"]
        for spec in DEMO_BLOG_CATEGORIES
        if spec.get("status") == CategoryStatus.INACTIVE
    }

    assert retired
    assert all(spec["category"] not in retired for spec in DEMO_BLOGS)
