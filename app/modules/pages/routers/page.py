"""Page endpoints.

Reading requires `page.view`; each write requires its own code, and taking a
page live requires `page.publish` - see [permissions.py](../permissions.py).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.pages.constants import PageStatus
from app.modules.pages.permissions import (
    can_create,
    can_delete,
    can_publish,
    can_update,
    can_view,
)
from app.modules.pages.schemas.page import (
    PageCreate,
    PagePublish,
    PageRead,
    PageSummary,
    PageUpdate,
)
from app.modules.pages.services.page import PageService
from app.shared.schemas.pagination import Page as PageOf
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    paginated_response,
    success_response,
)

router = APIRouter(prefix="/pages", tags=["Pages"], dependencies=[can_view()])

PageId = Annotated[uuid.UUID, Path(description="Page identifier.")]


@router.get(
    "",
    response_model=APIResponse[PageOf[PageSummary]],
    summary="List pages",
    description=(
        "`search` matches the title, slug, summary and body - the body "
        'included, because "which page mentions the refund window?" is the '
        "question an editor actually has. `live_only` returns what a reader "
        "should see: published, and not still scheduled for a future date."
    ),
)
async def list_pages(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    page_status: Annotated[
        PageStatus | None, Query(alias="status", description="Filter by status.")
    ] = None,
    featured_only: Annotated[
        bool, Query(description="Only pages pinned as featured.")
    ] = False,
    live_only: Annotated[
        bool, Query(description="Only pages a reader should be served.")
    ] = False,
) -> APIResponse[PageOf[PageSummary]]:
    items, total = await PageService(db).list_pages(
        pagination,
        search=search.search,
        status=page_status,
        featured_only=featured_only,
        live_only=live_only,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order,
    )

    return paginated_response(
        [PageSummary.model_validate(item) for item in items],
        total,
        pagination,
        message="Pages fetched",
    )


@router.get(
    "/by-slug/{slug}",
    response_model=APIResponse[PageRead],
    summary="Get a page by slug",
    description="How a front end resolves a URL to its content.",
)
async def get_page_by_slug(
    db: DbSession, slug: Annotated[str, Path(description="Page slug.")]
) -> APIResponse[PageRead]:
    page = await PageService(db).get_by_slug(slug)

    return success_response(data=PageRead.from_model(page), message="Page fetched")


@router.get(
    "/{page_id}",
    response_model=APIResponse[PageRead],
    summary="Get a page",
    description="Carries the resolved search metadata, with every gap filled in.",
)
async def get_page(db: DbSession, page_id: PageId) -> APIResponse[PageRead]:
    page = await PageService(db).get(page_id)

    return success_response(data=PageRead.from_model(page), message="Page fetched")


@router.post(
    "",
    response_model=APIResponse[PageRead],
    status_code=status.HTTP_201_CREATED,
    summary="Create a page",
    description=(
        "Always created as a draft, so creating one cannot bypass the publish "
        "check. Supply `slug` to claim a particular URL; omit it and one is "
        "derived from the title."
    ),
    dependencies=[can_create()],
)
async def create_page(
    db: DbSession, user: CurrentUser, payload: PageCreate
) -> APIResponse[PageRead]:
    page = await PageService(db).create(payload, actor_id=user.id)

    return created_response(data=PageRead.from_model(page), message="Page created")


@router.patch(
    "/{page_id}",
    response_model=APIResponse[PageRead],
    summary="Update a page",
    description=(
        "`status` is not accepted here - publishing runs through its own "
        "endpoint. The slug may only be changed while the page is a draft."
    ),
    dependencies=[can_update()],
)
async def update_page(
    db: DbSession, user: CurrentUser, page_id: PageId, payload: PageUpdate
) -> APIResponse[PageRead]:
    page = await PageService(db).update(page_id, payload, actor_id=user.id)

    return success_response(data=PageRead.from_model(page), message="Page updated")


@router.post(
    "/{page_id}/publish",
    response_model=APIResponse[PageRead],
    summary="Publish a page",
    description=(
        "Takes the page live now, or at `published_at` if that is in the "
        "future - which schedules it, with no background job needed to flip "
        "it over."
    ),
    dependencies=[can_publish()],
)
async def publish_page(
    db: DbSession, user: CurrentUser, page_id: PageId, payload: PagePublish
) -> APIResponse[PageRead]:
    page = await PageService(db).publish(
        page_id, published_at=payload.published_at, actor_id=user.id
    )

    return success_response(
        data=PageRead.from_model(page),
        message="Page scheduled" if page.is_scheduled else "Page published",
    )


@router.post(
    "/{page_id}/unpublish",
    response_model=APIResponse[PageRead],
    summary="Pull a page back to draft",
    description="`published_at` is kept, so republishing restores its date.",
    dependencies=[can_publish()],
)
async def unpublish_page(
    db: DbSession, user: CurrentUser, page_id: PageId
) -> APIResponse[PageRead]:
    page = await PageService(db).unpublish(page_id, actor_id=user.id)

    return success_response(data=PageRead.from_model(page), message="Page unpublished")


@router.post(
    "/{page_id}/archive",
    response_model=APIResponse[PageRead],
    summary="Archive a page",
    description=(
        "Retires the page without deleting it, so its URL still resolves for "
        "anyone holding a link."
    ),
    dependencies=[can_publish()],
)
async def archive_page(
    db: DbSession, user: CurrentUser, page_id: PageId
) -> APIResponse[PageRead]:
    page = await PageService(db).archive(page_id, actor_id=user.id)

    return success_response(data=PageRead.from_model(page), message="Page archived")


@router.delete(
    "/{page_id}",
    response_model=APIResponse[None],
    summary="Delete a page",
    description="Soft delete, so the row survives for audit and restore.",
    dependencies=[can_delete()],
)
async def delete_page(db: DbSession, page_id: PageId) -> APIResponse[None]:
    await PageService(db).delete(page_id)

    return deleted_response("Page deleted")


@router.post(
    "/{page_id}/restore",
    response_model=APIResponse[PageRead],
    summary="Restore a deleted page",
    dependencies=[can_delete()],
)
async def restore_page(db: DbSession, page_id: PageId) -> APIResponse[PageRead]:
    page = await PageService(db).restore(page_id)

    return success_response(data=PageRead.from_model(page), message="Page restored")
