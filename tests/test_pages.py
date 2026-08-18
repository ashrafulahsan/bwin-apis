"""Tests for CMS pages.

Two themes run through these. The first is publication: it is a transition
with its own permission, not a field, and the tests pin the behaviour that
follows from that - a page is born a draft, its date is set by the transition,
and a published slug is frozen.

The second is the search metadata. Every page is served with a complete set
whether or not its author filled any of it in, so the fallback cascade is
tested rather than assumed.
"""

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import PaginationParams
from app.core.exceptions import (
    ConflictException,
    NotFoundException,
)
from app.modules.auth.models.password_reset_token import PasswordResetToken
from app.modules.auth.models.refresh_token import RefreshToken
from app.modules.pages.constants import PageStatus
from app.modules.pages.models.page import Page
from app.modules.pages.schemas.page import PageCreate, PageRead, PageUpdate
from app.modules.pages.services.page import PageService
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
from app.shared.schemas.seo import SEOMetadata
from app.shared.utils.dates import utc_now

PASSWORD = "PageTest#2026"

BODY = "The refund window is fourteen days from delivery."


@pytest.fixture
async def pages(session: AsyncSession) -> AsyncIterator[PageService]:
    async def wipe() -> None:
        await session.execute(delete(Page))
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

    yield PageService(session)

    await wipe()


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


def draft(title: str = "About us", **kwargs) -> PageCreate:
    payload = {"title": title, "content": BODY, **kwargs}
    return PageCreate(**payload)


def page() -> PaginationParams:
    return PaginationParams(page=1, page_size=100)


# -- Creating -----------------------------------------------------------


async def test_a_page_is_born_a_draft(pages: PageService) -> None:
    """Publishing has its own permission, so creating cannot bypass it."""
    created = await pages.create(draft())

    assert created.status == PageStatus.DRAFT
    assert created.published_at is None
    assert created.is_live is False


async def test_the_slug_comes_from_the_title(pages: PageService) -> None:
    created = await pages.create(draft(title="About Us!"))

    assert created.slug == "about-us"


async def test_a_requested_slug_is_honoured(pages: PageService) -> None:
    created = await pages.create(draft(slug="privacy-policy"))

    assert created.slug == "privacy-policy"


async def test_a_taken_slug_is_refused_rather_than_suffixed(
    pages: PageService,
) -> None:
    """An editor who asked for a URL is told it is taken, not handed `-2`."""
    await pages.create(draft(slug="about"))

    with pytest.raises(ConflictException):
        await pages.create(draft(title="Another", slug="about"))


async def test_a_derived_slug_is_quietly_made_unique(pages: PageService) -> None:
    first = await pages.create(draft())
    second = await pages.create(draft())

    assert first.slug == "about-us"
    assert second.slug != first.slug


async def test_the_actor_is_recorded(pages: PageService, session: AsyncSession) -> None:
    admin = await make_user(session, "admin@pages.example.com", "admin")

    created = await pages.create(draft(), actor_id=admin.id)

    assert created.created_by == admin.id
    assert created.updated_by == admin.id


async def test_the_thumbnail_and_summary_are_stored(pages: PageService) -> None:
    created = await pages.create(
        draft(
            description="What we do and why.",
            thumbnail_image="/img/about.png",
            thumbnail_image_alt="The team outside the office",
        )
    )

    assert created.description == "What we do and why."
    assert created.thumbnail_image == "/img/about.png"
    assert created.thumbnail_image_alt == "The team outside the office"


# -- Publication --------------------------------------------------------


async def test_publishing_sets_the_date(pages: PageService) -> None:
    created = await pages.create(draft())

    published = await pages.publish(created.id)

    assert published.status == PageStatus.PUBLISHED
    assert published.published_at is not None
    assert published.is_live is True


async def test_a_future_date_schedules_the_page(pages: PageService) -> None:
    """No job flips it over: every read compares the date against the clock."""
    created = await pages.create(draft())

    scheduled = await pages.publish(
        created.id, published_at=utc_now() + timedelta(days=1)
    )

    assert scheduled.is_published is True
    assert scheduled.is_live is False
    assert scheduled.is_scheduled is True


async def test_publishing_twice_is_refused(pages: PageService) -> None:
    created = await pages.create(draft())
    await pages.publish(created.id)

    with pytest.raises(ConflictException):
        await pages.publish(created.id)


async def test_unpublishing_keeps_the_original_date(pages: PageService) -> None:
    """Republishing should not present an old page as new."""
    created = await pages.create(draft())
    published = await pages.publish(created.id)
    first_date = published.published_at

    drafted = await pages.unpublish(created.id)

    assert drafted.status == PageStatus.DRAFT
    assert drafted.published_at == first_date


async def test_archiving_retires_a_page_without_deleting_it(
    pages: PageService,
) -> None:
    """Its URL still has to resolve for anyone holding a link."""
    created = await pages.create(draft())
    await pages.publish(created.id)

    archived = await pages.archive(created.id)

    assert archived.status == PageStatus.ARCHIVED
    assert await pages.get_by_slug(archived.slug) is not None


async def test_a_published_slug_cannot_be_changed(pages: PageService) -> None:
    """It is already in links, menus and search results."""
    created = await pages.create(draft())
    await pages.publish(created.id)

    with pytest.raises(ConflictException):
        await pages.update(created.id, PageUpdate(slug="something-else"))


async def test_a_draft_slug_can_be_changed(pages: PageService) -> None:
    created = await pages.create(draft())

    updated = await pages.update(created.id, PageUpdate(slug="who-we-are"))

    assert updated.slug == "who-we-are"


def test_status_cannot_be_set_through_the_update_schema() -> None:
    """Publishing is a transition, so the field is not in the payload at all."""
    assert "status" not in PageUpdate.model_fields


# -- Search metadata ----------------------------------------------------


async def test_metadata_falls_back_to_the_page(pages: PageService) -> None:
    created = await pages.create(
        draft(description="What we do and why.", thumbnail_image="/img/about.png")
    )

    rendered = PageRead.from_model(created)

    assert rendered.seo.meta_title == "About us"
    assert rendered.seo.meta_description == "What we do and why."
    assert rendered.seo.og_title == "About us"
    assert rendered.seo.og_image_url == "/img/about.png"
    assert rendered.seo.meta_robots == "index, follow"
    assert rendered.seo.is_indexable is True


async def test_supplied_metadata_wins(pages: PageService) -> None:
    created = await pages.create(
        draft(
            description="What we do and why.",
            seo=SEOMetadata(
                meta_title="About our company",
                meta_keywords="about, company, team",
                meta_robots="noindex, nofollow",
            ),
        )
    )

    rendered = PageRead.from_model(created)

    assert rendered.seo.meta_title == "About our company"
    # The `meta_tag` box in an editor writes here.
    assert rendered.seo.meta_keywords == "about, company, team"
    assert rendered.seo.is_indexable is False


async def test_one_metadata_field_can_be_updated_without_blanking_the_rest(
    pages: PageService,
) -> None:
    created = await pages.create(
        draft(seo=SEOMetadata(meta_title="Kept", meta_keywords="also kept"))
    )

    updated = await pages.update(
        created.id, PageUpdate(seo=SEOMetadata(meta_description="New"))
    )

    assert updated.meta_title == "Kept"
    assert updated.meta_keywords == "also kept"
    assert updated.meta_description == "New"


def test_an_unknown_robots_directive_is_refused() -> None:
    """A misspelled `noindex` fails open, publishing what was meant to hide."""
    with pytest.raises(ValidationError):
        SEOMetadata(meta_robots="nofollw")


def test_a_dangerous_canonical_url_is_refused() -> None:
    with pytest.raises(ValidationError):
        SEOMetadata(canonical_url="javascript:alert(1)")


# -- Listing and search -------------------------------------------------


async def test_the_search_matches_the_body_as_well_as_the_title(
    pages: PageService,
) -> None:
    """ "Which page mentions the refund window?" is the real question."""
    await pages.create(draft(title="Returns", content="The refund window is 14 days."))
    await pages.create(draft(title="Careers", content="We are hiring."))

    found, total = await pages.list_pages(page(), search="refund window")

    assert total == 1
    assert found[0].title == "Returns"


async def test_pages_can_be_filtered_by_status_and_flag(
    pages: PageService,
) -> None:
    live = await pages.create(draft(title="About us"))
    await pages.publish(live.id)
    await pages.create(draft(title="Careers", is_featured=True))

    _, published = await pages.list_pages(page(), status=PageStatus.PUBLISHED)
    assert published == 1

    featured, count = await pages.list_pages(page(), featured_only=True)
    assert count == 1
    assert featured[0].title == "Careers"


async def test_live_only_leaves_out_drafts_and_scheduled_pages(
    pages: PageService,
) -> None:
    """Filtered in SQL, so the total agrees with the rows returned."""
    live = await pages.create(draft(title="About us"))
    await pages.publish(live.id)

    scheduled = await pages.create(draft(title="Launch"))
    await pages.publish(scheduled.id, published_at=utc_now() + timedelta(days=1))

    await pages.create(draft(title="Careers"))

    found, total = await pages.list_pages(page(), live_only=True)

    assert total == 1
    assert [row.title for row in found] == ["About us"]


# -- Deleting -----------------------------------------------------------


async def test_a_page_can_be_deleted_and_restored(pages: PageService) -> None:
    created = await pages.create(draft())

    await pages.delete(created.id)

    with pytest.raises(NotFoundException):
        await pages.get(created.id)

    restored = await pages.restore(created.id)
    assert restored.deleted_at is None


async def test_an_unknown_slug_is_a_not_found(pages: PageService) -> None:
    with pytest.raises(NotFoundException):
        await pages.get_by_slug("nothing-here")


# -- Authorization ------------------------------------------------------


@pytest.fixture
async def signed_in(
    client: TestClient, pages: PageService, session: AsyncSession
) -> dict[str, dict[str, str]]:
    """A bearer header per role, so the guards can be checked from outside."""
    headers = {}

    for role in ("admin", "content-manager", "editor", "student"):
        email = f"{role}@pages.example.com"
        await make_user(session, email, role)

        tokens = client.post(
            "/api/v1/auth/login", json={"identifier": email, "password": PASSWORD}
        ).json()["data"]["tokens"]
        headers[role] = {"Authorization": f"Bearer {tokens['access_token']}"}

    return headers


def test_page_endpoints_need_a_token(client: TestClient) -> None:
    assert client.get("/api/v1/pages").status_code == 401


def test_an_editor_writes_but_does_not_publish(
    client: TestClient, signed_in: dict[str, dict[str, str]]
) -> None:
    """The whole point of the Editor role, applied to pages."""
    editor = signed_in["editor"]

    created = client.post(
        "/api/v1/pages",
        headers=editor,
        json={"title": "An editor's page", "content": BODY},
    )
    assert created.status_code == 201, created.text
    page_id = created.json()["data"]["id"]

    updated = client.patch(
        f"/api/v1/pages/{page_id}", headers=editor, json={"title": "Revised"}
    )
    published = client.post(f"/api/v1/pages/{page_id}/publish", headers=editor, json={})

    assert updated.status_code == 200
    assert published.status_code == 403
    assert "page.publish" in published.json()["message"]


def test_a_student_may_read_but_not_write(
    client: TestClient, signed_in: dict[str, dict[str, str]]
) -> None:
    student = signed_in["student"]

    assert client.get("/api/v1/pages", headers=student).status_code == 200

    created = client.post(
        "/api/v1/pages", headers=student, json={"title": "Nope", "content": "Nope"}
    )
    assert created.status_code == 403
    assert "page.create" in created.json()["message"]


def test_a_content_manager_walks_the_whole_lifecycle(
    client: TestClient, signed_in: dict[str, dict[str, str]]
) -> None:
    manager = signed_in["content-manager"]

    created = client.post(
        "/api/v1/pages",
        headers=manager,
        json={
            "title": "About us",
            "content": BODY,
            "description": "What we do and why.",
            "thumbnail_image": "/img/about.png",
            "seo": {"meta_keywords": "about, company"},
        },
    )
    assert created.status_code == 201, created.text
    page_data = created.json()["data"]
    assert page_data["seo"]["meta_title"] == "About us"
    assert page_data["seo"]["meta_keywords"] == "about, company"

    fetched = client.get(f"/api/v1/pages/by-slug/{page_data['slug']}", headers=manager)
    assert fetched.status_code == 200

    published = client.post(
        f"/api/v1/pages/{page_data['id']}/publish", headers=manager, json={}
    )
    assert published.status_code == 200
    assert published.json()["data"]["is_live"] is True

    listed = client.get("/api/v1/pages?live_only=true", headers=manager).json()["data"]
    assert listed["meta"]["total_items"] == 1

    searched = client.get("/api/v1/pages?search=refund", headers=manager).json()["data"]
    assert searched["meta"]["total_items"] == 1
    assert searched["items"][0]["slug"] == page_data["slug"]

    archived = client.post(f"/api/v1/pages/{page_data['id']}/archive", headers=manager)
    assert archived.status_code == 200

    deleted = client.delete(f"/api/v1/pages/{page_data['id']}", headers=manager)
    assert deleted.status_code == 200
    assert (
        client.get(f"/api/v1/pages/{page_data['id']}", headers=manager).status_code
        == 404
    )

    restored = client.post(f"/api/v1/pages/{page_data['id']}/restore", headers=manager)
    assert restored.status_code == 200
