"""Tests for blog posts.

Two themes run through these. The first is that a post's category and tags are
ordinary categories, and nothing in the schema stops the wrong ones being
attached - a foreign key names a table, not a subset of it - so the checks
that keep `blog_category` and `blog_tag` apart are tested directly.

The second is publication: it is a transition with its own permission, not a
field, and the tests pin the behaviour that follows from that.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import PaginationParams
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.modules.auth.models.password_reset_token import PasswordResetToken
from app.modules.auth.models.refresh_token import RefreshToken
from app.modules.blogs.constants import (
    BLOG_CATEGORY_TYPE_NAME,
    BLOG_CATEGORY_TYPE_SLUG,
    BLOG_TAG_TYPE_NAME,
    BLOG_TAG_TYPE_SLUG,
    BlogStatus,
)
from app.modules.blogs.models.blog import Blog
from app.modules.blogs.models.blog_tag import blog_tags
from app.modules.blogs.schemas.blog import (
    BlogCreate,
    BlogRead,
    BlogUpdate,
)
from app.modules.blogs.services.blog import BlogService, estimate_reading_minutes
from app.modules.categories.constants import CategoryStatus
from app.modules.categories.models.category import Category
from app.modules.categories.models.category_type import CategoryType
from app.modules.categories.repositories.category_type import CategoryTypeRepository
from app.modules.categories.schemas.category import CategoryCreate, CategoryUpdate
from app.modules.categories.services.category import CategoryService
from app.modules.permissions.models.permission import Permission
from app.modules.permissions.models.role_permission import role_permissions
from app.modules.permissions.services.permission import PermissionService
from app.modules.roles.models.role import Role
from app.modules.roles.repositories.role import RoleRepository
from app.modules.roles.services.role import RoleService
from app.modules.users.constants import UserStatus
from app.modules.users.models.user import User
from app.modules.users.models.user_identity import UserIdentity
from app.modules.users.models.user_role import user_roles
from app.modules.users.schemas.user import UserCreate
from app.modules.users.services.user import UserService
from app.shared.schemas.seo import SEOMetadata, SEOMetadataRead, shorten
from app.shared.utils.dates import utc_now

PASSWORD = "BlogTest#2026"

BODY = "word " * 400  # 400 words, two minutes at 200 wpm


class Taxonomies:
    """The two seeded category types, plus a category and tag inside them."""

    def __init__(
        self,
        category_type: CategoryType,
        tag_type: CategoryType,
        category: Category,
        tag: Category,
    ) -> None:
        self.category_type = category_type
        self.tag_type = tag_type
        self.category = category
        self.tag = tag


@pytest.fixture
async def blogs(session: AsyncSession) -> AsyncIterator[BlogService]:
    async def wipe() -> None:
        await session.execute(delete(blog_tags))
        await session.execute(delete(Blog))
        await session.execute(delete(Category))
        await session.execute(delete(CategoryType))
        await session.execute(delete(PasswordResetToken))
        await session.execute(delete(RefreshToken))
        await session.execute(delete(user_roles))
        await session.execute(delete(UserIdentity))
        await session.execute(delete(User))
        await session.execute(delete(role_permissions))
        await session.execute(delete(Permission))
        await session.execute(delete(Role))
        await session.commit()

    await wipe()
    await RoleService(session).seed_system_roles()
    await PermissionService(session).seed_system_permissions()
    await PermissionService(session).seed_default_role_permissions()

    yield BlogService(session)

    await wipe()


@pytest.fixture
async def taxonomy(blogs: BlogService, session: AsyncSession) -> Taxonomies:
    """The vocabularies a post draws on, as the migration seeds them.

    Created through the repository rather than the service, because the two
    slugs are fixed identifiers - `blog_category`, not `blog-category` - and
    the service derives slugs from names.
    """
    types = CategoryTypeRepository(session)

    category_type = await types.create(
        name=BLOG_CATEGORY_TYPE_NAME,
        slug=BLOG_CATEGORY_TYPE_SLUG,
        status=CategoryStatus.ACTIVE.value,
    )
    tag_type = await types.create(
        name=BLOG_TAG_TYPE_NAME,
        slug=BLOG_TAG_TYPE_SLUG,
        status=CategoryStatus.ACTIVE.value,
    )
    await session.commit()

    categories = CategoryService(session)
    category = await categories.create(
        CategoryCreate(name="Engineering", category_type_id=category_type.id)
    )
    tag = await categories.create(
        CategoryCreate(name="postgres", category_type_id=tag_type.id)
    )

    return Taxonomies(category_type, tag_type, category, tag)


async def make_user(session: AsyncSession, email: str, role: str) -> User:
    role_row = await RoleRepository(session).get_by_slug(role)
    assert role_row is not None

    return await UserService(session).create(
        UserCreate(
            email=email,
            password=PASSWORD,
            first_name=role.title(),
            status=UserStatus.ACTIVE,
            role_ids=[role_row.id],
        )
    )


def draft(
    taxonomy: Taxonomies, title: str = "Migrating a database", **kwargs
) -> BlogCreate:
    payload = {
        "title": title,
        "content": BODY,
        "blog_category_id": taxonomy.category.id,
        **kwargs,
    }
    return BlogCreate(**payload)


def page() -> PaginationParams:
    return PaginationParams(page=1, page_size=100)


# -- Creating -----------------------------------------------------------


async def test_a_post_is_born_a_draft(blogs: BlogService, taxonomy: Taxonomies) -> None:
    """Publishing has its own permission, so creating cannot bypass it."""
    created = await blogs.create(draft(taxonomy))

    assert created.status == BlogStatus.DRAFT
    assert created.published_at is None
    assert created.is_live is False


async def test_the_slug_comes_from_the_title(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    created = await blogs.create(draft(taxonomy, title="Migrating a Database!"))

    assert created.slug == "migrating-a-database"


async def test_reading_time_is_estimated_from_the_body(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    created = await blogs.create(draft(taxonomy))

    assert created.reading_minutes == 2


def test_reading_time_ignores_markup_and_never_reads_zero() -> None:
    assert estimate_reading_minutes("<p><span>one</span> two</p>") == 1
    assert estimate_reading_minutes("") == 1
    assert estimate_reading_minutes("word " * 201) == 2


async def test_the_response_renders_straight_after_creation(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    """Regression: `selectin` loads on query, not on flush.

    A freshly inserted post has its `category`, `tags` and `author` unloaded,
    so rendering the response reached for them and raised MissingGreenlet.
    """
    created = await blogs.create(draft(taxonomy, tag_ids=[taxonomy.tag.id]))

    rendered = BlogRead.from_model(created)

    assert rendered.category.slug == taxonomy.category.slug
    assert [tag.name for tag in rendered.tags] == ["postgres"]


async def test_the_author_defaults_to_whoever_created_it(
    blogs: BlogService, taxonomy: Taxonomies, session: AsyncSession
) -> None:
    writer = await make_user(session, "writer@blogs.example.com", "editor")

    created = await blogs.create(draft(taxonomy), actor_id=writer.id)

    assert created.author_id == writer.id
    assert created.created_by == writer.id


async def test_the_byline_can_be_someone_else(
    blogs: BlogService, taxonomy: Taxonomies, session: AsyncSession
) -> None:
    """A guest column typed in by staff still carries the guest's name."""
    staff = await make_user(session, "staff@blogs.example.com", "content-manager")
    guest = await make_user(session, "guest@blogs.example.com", "editor")

    created = await blogs.create(draft(taxonomy, author_id=guest.id), actor_id=staff.id)

    assert created.author_id == guest.id
    assert created.created_by == staff.id


async def test_an_unknown_author_is_refused(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    with pytest.raises(BadRequestException):
        await blogs.create(draft(taxonomy, author_id=uuid.uuid4()))


# -- The two vocabularies -----------------------------------------------


async def test_the_category_must_come_from_the_blog_category_taxonomy(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    """The module's central rule, and the one a foreign key cannot express."""
    payload = draft(taxonomy)
    payload.blog_category_id = taxonomy.tag.id  # a tag, not a category

    with pytest.raises(BadRequestException) as failure:
        await blogs.create(payload)

    assert BLOG_CATEGORY_TYPE_NAME in str(failure.value)


async def test_a_tag_must_come_from_the_blog_tag_taxonomy(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    with pytest.raises(BadRequestException) as failure:
        await blogs.create(draft(taxonomy, tag_ids=[taxonomy.category.id]))

    assert BLOG_TAG_TYPE_NAME in str(failure.value)


async def test_an_unknown_category_is_refused(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    payload = draft(taxonomy)
    payload.blog_category_id = uuid.uuid4()

    with pytest.raises(BadRequestException):
        await blogs.create(payload)


async def test_an_inactive_category_takes_no_new_posts(
    blogs: BlogService, taxonomy: Taxonomies, session: AsyncSession
) -> None:
    """Inactive means "not offered for new content" - which is this case."""
    await CategoryService(session).update(
        taxonomy.category.id, CategoryUpdate(status=CategoryStatus.INACTIVE)
    )

    with pytest.raises(BadRequestException):
        await blogs.create(draft(taxonomy))


async def test_a_missing_taxonomy_says_which_one(
    blogs: BlogService, taxonomy: Taxonomies, session: AsyncSession
) -> None:
    """Seeded by migration, so its absence means someone removed it."""
    await session.execute(delete(Category))
    await session.execute(
        delete(CategoryType).where(CategoryType.slug == BLOG_CATEGORY_TYPE_SLUG)
    )
    await session.commit()

    with pytest.raises(ConflictException) as failure:
        await blogs.create(draft(taxonomy))

    assert BLOG_CATEGORY_TYPE_SLUG in str(failure.value)


async def test_tags_are_deduplicated_rather_than_rejected(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    created = await blogs.create(
        draft(taxonomy, tag_ids=[taxonomy.tag.id, taxonomy.tag.id])
    )

    assert len(created.tags) == 1


async def test_only_active_vocabulary_is_offered(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    categories = await blogs.available_categories()
    tags = await blogs.available_tags()

    assert [item.name for item in categories] == ["Engineering"]
    assert [item.name for item in tags] == ["postgres"]


# -- Slugs --------------------------------------------------------------


async def test_a_derived_slug_is_suffixed_on_collision(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    await blogs.create(draft(taxonomy, title="Indexes"))
    second = await blogs.create(draft(taxonomy, title="Indexes"))

    assert second.slug == "indexes-2"


async def test_a_requested_slug_is_not_quietly_changed(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    """An editor who asked for a URL is told it is taken, not handed `-2`."""
    await blogs.create(draft(taxonomy, slug="postgres-tips"))

    with pytest.raises(ConflictException):
        await blogs.create(draft(taxonomy, title="Other", slug="postgres-tips"))


async def test_a_draft_may_change_its_address(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    created = await blogs.create(draft(taxonomy))

    updated = await blogs.update(created.id, BlogUpdate(slug="a-better-url"))

    assert updated.slug == "a-better-url"


async def test_a_published_post_may_not(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    """The address is already in links, feeds and search results."""
    created = await blogs.create(draft(taxonomy))
    await blogs.publish(created.id)

    with pytest.raises(ConflictException):
        await blogs.update(created.id, BlogUpdate(slug="too-late"))


async def test_renaming_a_post_leaves_its_address_alone(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    created = await blogs.create(draft(taxonomy, title="Original"))

    updated = await blogs.update(created.id, BlogUpdate(title="Rewritten"))

    assert updated.title == "Rewritten"
    assert updated.slug == "original"


# -- Updating -----------------------------------------------------------


async def test_tags_are_replaced_wholesale(
    blogs: BlogService, taxonomy: Taxonomies, session: AsyncSession
) -> None:
    other = await CategoryService(session).create(
        CategoryCreate(name="alembic", category_type_id=taxonomy.tag_type.id)
    )
    created = await blogs.create(draft(taxonomy, tag_ids=[taxonomy.tag.id]))

    updated = await blogs.update(created.id, BlogUpdate(tag_ids=[other.id]))

    assert [tag.name for tag in updated.tags] == ["alembic"]


async def test_omitting_tags_leaves_them_alone(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    created = await blogs.create(draft(taxonomy, tag_ids=[taxonomy.tag.id]))

    updated = await blogs.update(created.id, BlogUpdate(title="Renamed"))

    assert [tag.name for tag in updated.tags] == ["postgres"]


async def test_editing_the_body_recomputes_the_reading_time(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    created = await blogs.create(draft(taxonomy))
    # Read before updating: the identity map hands back the same instance,
    # so `created` would otherwise already show the new estimate.
    before = created.reading_minutes

    updated = await blogs.update(created.id, BlogUpdate(content="word " * 1000))

    assert before == 2
    assert updated.reading_minutes == 5


async def test_an_explicit_null_on_a_required_field_is_ignored(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    """A form clearing a field it never edited should not be a 500."""
    created = await blogs.create(draft(taxonomy))

    updated = await blogs.update(created.id, BlogUpdate(title=None, content=None))

    assert updated.title == created.title
    assert updated.content == created.content


# -- Publishing ---------------------------------------------------------


async def test_publishing_dates_the_post(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    created = await blogs.create(draft(taxonomy))

    published = await blogs.publish(created.id)

    assert published.status == BlogStatus.PUBLISHED
    assert published.published_at is not None
    assert published.is_live is True


async def test_publishing_twice_is_refused(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    created = await blogs.create(draft(taxonomy))
    await blogs.publish(created.id)

    with pytest.raises(ConflictException):
        await blogs.publish(created.id)


async def test_a_future_date_schedules_without_a_job(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    """Every read compares the date against the clock, so nothing has to run."""
    created = await blogs.create(draft(taxonomy))

    scheduled = await blogs.publish(
        created.id, published_at=utc_now() + timedelta(days=1)
    )

    assert scheduled.is_published is True
    assert scheduled.is_scheduled is True
    assert scheduled.is_live is False


async def test_a_scheduled_post_is_not_served_as_live(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    live = await blogs.create(draft(taxonomy, title="Out now"))
    await blogs.publish(live.id)

    later = await blogs.create(draft(taxonomy, title="Out later"))
    await blogs.publish(later.id, published_at=utc_now() + timedelta(days=1))

    items, total = await blogs.list_blogs(page(), live_only=True)

    assert total == 1
    assert [item.title for item in items] == ["Out now"]


async def test_returning_to_draft_keeps_the_original_date(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    """Republishing should not present an old post as new."""
    created = await blogs.create(draft(taxonomy))
    published = await blogs.publish(created.id)
    first_date = published.published_at

    await blogs.unpublish(created.id)
    republished = await blogs.publish(created.id)

    assert republished.published_at == first_date


async def test_archiving_keeps_the_post_resolvable(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    created = await blogs.create(draft(taxonomy))
    await blogs.publish(created.id)

    archived = await blogs.archive(created.id)

    assert archived.status == BlogStatus.ARCHIVED
    assert archived.is_live is False
    assert await blogs.get_by_slug(archived.slug) is not None


async def test_archiving_twice_is_refused(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    created = await blogs.create(draft(taxonomy))
    await blogs.archive(created.id)

    with pytest.raises(ConflictException):
        await blogs.archive(created.id)


# -- Deleting -----------------------------------------------------------


async def test_deleting_is_soft_and_reversible(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    created = await blogs.create(draft(taxonomy))

    await blogs.delete(created.id)
    with pytest.raises(NotFoundException):
        await blogs.get(created.id)

    restored = await blogs.restore(created.id)
    assert restored.deleted_at is None
    assert await blogs.get(created.id) is not None


# -- Listing ------------------------------------------------------------


async def test_filters_narrow_the_listing(
    blogs: BlogService, taxonomy: Taxonomies, session: AsyncSession
) -> None:
    other_tag = await CategoryService(session).create(
        CategoryCreate(name="alembic", category_type_id=taxonomy.tag_type.id)
    )

    await blogs.create(draft(taxonomy, title="Tagged", tag_ids=[taxonomy.tag.id]))
    await blogs.create(draft(taxonomy, title="Other", tag_ids=[other_tag.id]))
    await blogs.create(draft(taxonomy, title="Featured", is_featured=True))

    tagged, tagged_total = await blogs.list_blogs(page(), tag_id=taxonomy.tag.id)
    featured, _ = await blogs.list_blogs(page(), featured_only=True)
    found, _ = await blogs.list_blogs(page(), search="Other")

    assert tagged_total == 1
    assert [item.title for item in tagged] == ["Tagged"]
    assert [item.title for item in featured] == ["Featured"]
    assert [item.title for item in found] == ["Other"]


async def test_the_tag_filter_counts_a_post_once(
    blogs: BlogService, taxonomy: Taxonomies, session: AsyncSession
) -> None:
    """A join through the association table would multiply the rows."""
    second = await CategoryService(session).create(
        CategoryCreate(name="alembic", category_type_id=taxonomy.tag_type.id)
    )
    await blogs.create(draft(taxonomy, tag_ids=[taxonomy.tag.id, second.id]))

    items, total = await blogs.list_blogs(page(), tag_id=taxonomy.tag.id)

    assert total == 1
    assert len(items) == 1


# -- Search metadata ----------------------------------------------------


async def test_metadata_is_served_even_when_none_was_written(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    created = await blogs.create(
        draft(taxonomy, title="Indexes explained", excerpt="A short primer.")
    )

    seo = BlogRead.from_model(created).seo

    assert seo.meta_title == "Indexes explained"
    assert seo.meta_description == "A short primer."
    assert seo.og_title == "Indexes explained"
    assert seo.meta_robots == "index, follow"
    assert seo.is_indexable is True


async def test_written_metadata_wins(blogs: BlogService, taxonomy: Taxonomies) -> None:
    created = await blogs.create(
        draft(
            taxonomy,
            seo=SEOMetadata(
                meta_title="Postgres indexes, explained simply",
                meta_robots="noindex, nofollow",
            ),
        )
    )

    seo = BlogRead.from_model(created).seo

    assert seo.meta_title == "Postgres indexes, explained simply"
    assert seo.is_indexable is False


async def test_a_partial_metadata_update_keeps_the_rest(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    created = await blogs.create(
        draft(
            taxonomy,
            seo=SEOMetadata(meta_title="Kept", meta_keywords="postgres, indexes"),
        )
    )

    updated = await blogs.update(
        created.id, BlogUpdate(seo=SEOMetadata(meta_description="Changed"))
    )

    assert updated.meta_title == "Kept"
    assert updated.meta_keywords == "postgres, indexes"
    assert updated.meta_description == "Changed"


async def test_clearing_the_robots_box_returns_it_to_the_default(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    """The one SEO column that cannot hold a null, sent as one."""
    created = await blogs.create(
        draft(taxonomy, seo=SEOMetadata(meta_robots="noindex, nofollow"))
    )

    updated = await blogs.update(
        created.id, BlogUpdate(seo=SEOMetadata(meta_robots=None))
    )

    assert updated.meta_robots == "index, follow"


async def test_a_derived_description_is_cut_to_what_is_displayed(
    blogs: BlogService, taxonomy: Taxonomies
) -> None:
    """Falling back to a long excerpt should not produce a truncated snippet."""
    created = await blogs.create(draft(taxonomy, excerpt="sentence. " * 40))

    seo = BlogRead.from_model(created).seo

    assert seo.meta_description is not None
    assert len(seo.meta_description) <= 161
    assert seo.meta_description.endswith("…")


def test_an_unknown_robots_directive_is_rejected() -> None:
    """A misspelled `noindex` fails open, publishing what should be hidden."""
    with pytest.raises(ValidationError):
        SEOMetadata(meta_robots="noindx, nofollow")


def test_a_dangerous_canonical_url_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SEOMetadata(canonical_url="javascript:alert(1)")

    assert SEOMetadata(canonical_url="/blog/indexes").canonical_url == "/blog/indexes"


def test_robots_directives_are_tidied() -> None:
    assert SEOMetadata(meta_robots=" NOINDEX ,nofollow, noindex").meta_robots == (
        "noindex, nofollow"
    )


def test_shorten_prefers_a_word_boundary() -> None:
    assert shorten("one two three four", 12) == "one two…"
    assert shorten("short", 20) == "short"


def test_resolution_falls_back_field_by_field() -> None:
    class Stored:
        meta_title = None
        meta_description = None
        meta_keywords = None
        canonical_url = None
        og_title = None
        og_description = "Written for sharing"
        og_image_url = None
        meta_robots = "index, follow"

    resolved = SEOMetadataRead.resolve(
        Stored(), title="A title", summary="A summary", image_url="/cover.png"
    )

    assert resolved.meta_title == "A title"
    assert resolved.og_title == "A title"
    assert resolved.og_description == "Written for sharing"
    assert resolved.og_image_url == "/cover.png"


# -- Authorization ------------------------------------------------------


@pytest.fixture
async def signed_in(
    client: TestClient, blogs: BlogService, session: AsyncSession
) -> dict[str, dict[str, str]]:
    """A bearer header per role, so the guards can be checked from outside."""
    headers = {}

    for role in ("admin", "content-manager", "editor", "student"):
        email = f"{role}@blogs.example.com"
        await make_user(session, email, role)

        tokens = client.post(
            "/api/v1/auth/login", json={"identifier": email, "password": PASSWORD}
        ).json()["data"]["tokens"]
        headers[role] = {"Authorization": f"Bearer {tokens['access_token']}"}

    return headers


def test_blog_endpoints_need_a_token(client: TestClient) -> None:
    assert client.get("/api/v1/blogs").status_code == 401


def test_a_student_may_read_but_not_write(
    client: TestClient, signed_in: dict[str, dict[str, str]], taxonomy: Taxonomies
) -> None:
    student = signed_in["student"]

    assert client.get("/api/v1/blogs", headers=student).status_code == 200
    created = client.post(
        "/api/v1/blogs",
        headers=student,
        json={
            "title": "Nope",
            "content": "Nope",
            "blog_category_id": str(taxonomy.category.id),
        },
    )

    assert created.status_code == 403
    assert "blog.create" in created.json()["message"]


def test_an_editor_writes_but_does_not_publish(
    client: TestClient, signed_in: dict[str, dict[str, str]], taxonomy: Taxonomies
) -> None:
    """The whole point of the Editor role, applied to blog posts."""
    editor = signed_in["editor"]

    created = client.post(
        "/api/v1/blogs",
        headers=editor,
        json={
            "title": "An editor's post",
            "content": BODY,
            "blog_category_id": str(taxonomy.category.id),
        },
    )
    assert created.status_code == 201, created.text
    blog_id = created.json()["data"]["id"]

    updated = client.patch(
        f"/api/v1/blogs/{blog_id}", headers=editor, json={"title": "Revised"}
    )
    published = client.post(f"/api/v1/blogs/{blog_id}/publish", headers=editor, json={})

    assert updated.status_code == 200
    assert published.status_code == 403
    assert "blog.publish" in published.json()["message"]


def test_a_content_manager_publishes(
    client: TestClient, signed_in: dict[str, dict[str, str]], taxonomy: Taxonomies
) -> None:
    manager = signed_in["content-manager"]

    created = client.post(
        "/api/v1/blogs",
        headers=manager,
        json={
            "title": "Ready to go",
            "content": BODY,
            "blog_category_id": str(taxonomy.category.id),
        },
    ).json()["data"]

    published = client.post(
        f"/api/v1/blogs/{created['id']}/publish", headers=manager, json={}
    )

    assert published.status_code == 200
    assert published.json()["data"]["status"] == "published"
    assert published.json()["data"]["is_live"] is True


# -- Through the API ----------------------------------------------------


def test_the_full_lifecycle_through_the_api(
    client: TestClient, signed_in: dict[str, dict[str, str]], taxonomy: Taxonomies
) -> None:
    admin = signed_in["admin"]

    vocabulary = client.get("/api/v1/blogs/categories", headers=admin)
    tags = client.get("/api/v1/blogs/tags", headers=admin)
    assert [item["name"] for item in vocabulary.json()["data"]] == ["Engineering"]
    assert [item["name"] for item in tags.json()["data"]] == ["postgres"]

    created = client.post(
        "/api/v1/blogs",
        headers=admin,
        json={
            "title": "Indexes, explained",
            "content": BODY,
            "excerpt": "What they cost and what they buy.",
            "blog_category_id": str(taxonomy.category.id),
            "tag_ids": [str(taxonomy.tag.id)],
            "seo": {"meta_keywords": "postgres, indexes"},
        },
    )
    assert created.status_code == 201, created.text
    post = created.json()["data"]

    assert post["status"] == "draft"
    assert post["slug"] == "indexes-explained"
    assert post["category"]["name"] == "Engineering"
    assert [tag["name"] for tag in post["tags"]] == ["postgres"]
    assert post["seo"]["meta_title"] == "Indexes, explained"
    assert post["seo"]["meta_keywords"] == "postgres, indexes"
    assert post["reading_minutes"] == 2

    fetched = client.get(f"/api/v1/blogs/by-slug/{post['slug']}", headers=admin)
    assert fetched.status_code == 200
    assert fetched.json()["data"]["id"] == post["id"]

    published = client.post(
        f"/api/v1/blogs/{post['id']}/publish", headers=admin, json={}
    )
    assert published.status_code == 200
    assert published.json()["data"]["is_live"] is True

    listed = client.get("/api/v1/blogs?live_only=true", headers=admin).json()["data"]
    assert listed["meta"]["total_items"] == 1
    assert [item["title"] for item in listed["items"]] == ["Indexes, explained"]

    archived = client.post(f"/api/v1/blogs/{post['id']}/archive", headers=admin)
    assert archived.status_code == 200

    deleted = client.delete(f"/api/v1/blogs/{post['id']}", headers=admin)
    assert deleted.status_code == 200
    assert client.get(f"/api/v1/blogs/{post['id']}", headers=admin).status_code == 404

    restored = client.post(f"/api/v1/blogs/{post['id']}/restore", headers=admin)
    assert restored.status_code == 200, restored.text
    assert restored.json()["data"]["status"] == "archived"


def test_a_category_from_the_wrong_taxonomy_is_a_400(
    client: TestClient, signed_in: dict[str, dict[str, str]], taxonomy: Taxonomies
) -> None:
    response = client.post(
        "/api/v1/blogs",
        headers=signed_in["admin"],
        json={
            "title": "Wrong vocabulary",
            "content": BODY,
            "blog_category_id": str(taxonomy.tag.id),
        },
    )

    assert response.status_code == 400
    assert BLOG_CATEGORY_TYPE_NAME in response.json()["message"]


def test_too_many_tags_is_a_422(
    client: TestClient, signed_in: dict[str, dict[str, str]], taxonomy: Taxonomies
) -> None:
    response = client.post(
        "/api/v1/blogs",
        headers=signed_in["admin"],
        json={
            "title": "Over-tagged",
            "content": BODY,
            "blog_category_id": str(taxonomy.category.id),
            "tag_ids": [str(uuid.uuid4()) for _ in range(11)],
        },
    )

    assert response.status_code == 422
