"""Blog post endpoints.

Reading requires `blog.view`; each write requires its own code, and taking a
post live requires `blog.publish` - see [permissions.py](../permissions.py).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.blogs.constants import BlogStatus
from app.modules.blogs.permissions import (
    can_create,
    can_delete,
    can_publish,
    can_update,
    can_view,
)
from app.modules.blogs.schemas.blog import (
    BlogCreate,
    BlogPublish,
    BlogRead,
    BlogSummary,
    BlogUpdate,
)
from app.modules.blogs.services.blog import BlogService
from app.modules.categories.schemas.category import CategorySummary
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    paginated_response,
    success_response,
)

router = APIRouter(prefix="/blogs", tags=["Blogs"], dependencies=[can_view()])

BlogId = Annotated[uuid.UUID, Path(description="Blog post identifier.")]


@router.get(
    "",
    response_model=APIResponse[Page[BlogSummary]],
    summary="List blog posts",
    description=(
        "Search matches the title, slug, excerpt and body. `live_only` "
        "returns what a reader should see: published, and not still "
        "scheduled for a future date."
    ),
)
async def list_blogs(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    blog_status: Annotated[
        BlogStatus | None, Query(alias="status", description="Filter by status.")
    ] = None,
    category_id: Annotated[
        uuid.UUID | None, Query(description="Filter by blog category.")
    ] = None,
    tag_id: Annotated[uuid.UUID | None, Query(description="Filter by tag.")] = None,
    author_id: Annotated[
        uuid.UUID | None, Query(description="Filter by author.")
    ] = None,
    featured_only: Annotated[
        bool, Query(description="Only posts pinned as featured.")
    ] = False,
    live_only: Annotated[
        bool, Query(description="Only posts a reader should be served.")
    ] = False,
) -> APIResponse[Page[BlogSummary]]:
    items, total = await BlogService(db).list_blogs(
        pagination,
        search=search.search,
        status=blog_status,
        category_id=category_id,
        tag_id=tag_id,
        author_id=author_id,
        featured_only=featured_only,
        live_only=live_only,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order,
    )

    return paginated_response(
        [BlogSummary.model_validate(item) for item in items],
        total,
        pagination,
        message="Blog posts fetched",
    )


@router.get(
    "/categories",
    response_model=APIResponse[list[CategorySummary]],
    summary="List the categories a post may be filed under",
    description=(
        "The active categories in the `blog_category` taxonomy. Exposed here "
        "because writing a post needs this list, while the category "
        "management endpoints are restricted to administrators."
    ),
)
async def list_blog_categories(db: DbSession) -> APIResponse[list[CategorySummary]]:
    categories = await BlogService(db).available_categories()

    return success_response(
        data=[CategorySummary.model_validate(item) for item in categories],
        message="Blog categories fetched",
    )


@router.get(
    "/tags",
    response_model=APIResponse[list[CategorySummary]],
    summary="List the tags a post may carry",
    description="The active categories in the `blog_tag` taxonomy.",
)
async def list_blog_tags(db: DbSession) -> APIResponse[list[CategorySummary]]:
    tags = await BlogService(db).available_tags()

    return success_response(
        data=[CategorySummary.model_validate(item) for item in tags],
        message="Blog tags fetched",
    )


@router.get(
    "/by-slug/{slug}",
    response_model=APIResponse[BlogRead],
    summary="Get a blog post by slug",
)
async def get_blog_by_slug(
    db: DbSession, slug: Annotated[str, Path(description="Blog post slug.")]
) -> APIResponse[BlogRead]:
    blog = await BlogService(db).get_by_slug(slug)

    return success_response(data=BlogRead.from_model(blog), message="Blog post fetched")


@router.get(
    "/{blog_id}",
    response_model=APIResponse[BlogRead],
    summary="Get a blog post",
)
async def get_blog(db: DbSession, blog_id: BlogId) -> APIResponse[BlogRead]:
    blog = await BlogService(db).get(blog_id)

    return success_response(data=BlogRead.from_model(blog), message="Blog post fetched")


@router.post(
    "",
    response_model=APIResponse[BlogRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=[can_create()],
    summary="Create a blog post",
    description=(
        "The post is created as a draft. `blog_category_id` must name a "
        "category from the `blog_category` taxonomy, and every id in "
        "`tag_ids` one from `blog_tag`."
    ),
)
async def create_blog(
    db: DbSession, user: CurrentUser, payload: BlogCreate
) -> APIResponse[BlogRead]:
    blog = await BlogService(db).create(payload, actor_id=user.id)

    return created_response(data=BlogRead.from_model(blog), message="Blog post created")


@router.patch(
    "/{blog_id}",
    response_model=APIResponse[BlogRead],
    dependencies=[can_update()],
    summary="Update a blog post",
    description=(
        "Sending `tag_ids` replaces the whole set. The status is not settable "
        "here - use the publish, unpublish and archive endpoints."
    ),
)
async def update_blog(
    db: DbSession, user: CurrentUser, blog_id: BlogId, payload: BlogUpdate
) -> APIResponse[BlogRead]:
    blog = await BlogService(db).update(blog_id, payload, actor_id=user.id)

    return success_response(data=BlogRead.from_model(blog), message="Blog post updated")


@router.post(
    "/{blog_id}/publish",
    response_model=APIResponse[BlogRead],
    dependencies=[can_publish()],
    summary="Publish a blog post",
    description=(
        "Takes the post live. A future `published_at` schedules it: no job is "
        "needed, because every read compares the date against the clock."
    ),
)
async def publish_blog(
    db: DbSession, user: CurrentUser, blog_id: BlogId, payload: BlogPublish
) -> APIResponse[BlogRead]:
    blog = await BlogService(db).publish(
        blog_id, published_at=payload.published_at, actor_id=user.id
    )

    return success_response(
        data=BlogRead.from_model(blog), message="Blog post published"
    )


@router.post(
    "/{blog_id}/unpublish",
    response_model=APIResponse[BlogRead],
    dependencies=[can_publish()],
    summary="Return a blog post to draft",
)
async def unpublish_blog(
    db: DbSession, user: CurrentUser, blog_id: BlogId
) -> APIResponse[BlogRead]:
    blog = await BlogService(db).unpublish(blog_id, actor_id=user.id)

    return success_response(
        data=BlogRead.from_model(blog), message="Blog post returned to draft"
    )


@router.post(
    "/{blog_id}/archive",
    response_model=APIResponse[BlogRead],
    dependencies=[can_publish()],
    summary="Archive a blog post",
    description="Retires the post without deleting it, so its URL still resolves.",
)
async def archive_blog(
    db: DbSession, user: CurrentUser, blog_id: BlogId
) -> APIResponse[BlogRead]:
    blog = await BlogService(db).archive(blog_id, actor_id=user.id)

    return success_response(
        data=BlogRead.from_model(blog), message="Blog post archived"
    )


@router.delete(
    "/{blog_id}",
    response_model=APIResponse[None],
    dependencies=[can_delete()],
    summary="Delete a blog post",
    description="Soft delete: the row is kept for audit and can be restored.",
)
async def delete_blog(db: DbSession, blog_id: BlogId) -> APIResponse[None]:
    await BlogService(db).delete(blog_id)

    return deleted_response("Blog post deleted")


@router.post(
    "/{blog_id}/restore",
    response_model=APIResponse[BlogRead],
    dependencies=[can_delete()],
    summary="Restore a deleted blog post",
)
async def restore_blog(db: DbSession, blog_id: BlogId) -> APIResponse[BlogRead]:
    blog = await BlogService(db).restore(blog_id)

    return success_response(
        data=BlogRead.from_model(blog), message="Blog post restored"
    )
