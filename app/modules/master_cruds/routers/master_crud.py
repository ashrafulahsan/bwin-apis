"""Master CRUD record endpoints.

Reading requires `master_crud.view`; each write requires its own code - see
[permissions.py](../permissions.py). Field values are written through these
endpoints rather than endpoints of their own: an answer has no life apart from
the record it belongs to, and validating a submission means seeing the whole
of it at once.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.master_cruds.constants import MasterCrudStatus
from app.modules.master_cruds.permissions import (
    can_create,
    can_delete,
    can_update,
    can_view,
)
from app.modules.master_cruds.schemas.master_crud import (
    MasterCrudCreate,
    MasterCrudRead,
    MasterCrudSummary,
    MasterCrudUpdate,
)
from app.modules.master_cruds.schemas.master_crud_field import MasterCrudFieldSummary
from app.modules.master_cruds.services.master_crud import MasterCrudService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    paginated_response,
    success_response,
)

router = APIRouter(
    prefix="/master-cruds", tags=["Master CRUDs"], dependencies=[can_view()]
)

MasterCrudId = Annotated[uuid.UUID, Path(description="Master CRUD identifier.")]


@router.get(
    "",
    response_model=APIResponse[Page[MasterCrudSummary]],
    summary="List records",
    description=(
        "Search matches the title, slug, description and link. Results read "
        "in `order`, ascending, unless `sort_by` names another column - which "
        "puts the caller in charge of `sort_order` too."
    ),
)
async def list_records(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    category_id: Annotated[
        uuid.UUID | None, Query(description="Filter by category.")
    ] = None,
    record_status: Annotated[
        MasterCrudStatus | None,
        Query(alias="status", description="Filter by status."),
    ] = None,
) -> APIResponse[Page[MasterCrudSummary]]:
    items, total = await MasterCrudService(db).list_records(
        pagination,
        search=search.search,
        category_id=category_id,
        status=record_status,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order,
    )

    return paginated_response(
        [MasterCrudSummary.model_validate(item) for item in items],
        total,
        pagination,
        message="Master CRUD records fetched",
    )


@router.get(
    "/form",
    response_model=APIResponse[list[MasterCrudFieldSummary]],
    summary="Get the fields a category's records must answer",
    description=(
        "The active field definitions for one category - what a client needs "
        "to build the form before posting a record. Exposed here so filling a "
        "form in does not require the field-management permission."
    ),
)
async def get_form(
    db: DbSession,
    category_id: Annotated[uuid.UUID, Query(description="Which category's form.")],
) -> APIResponse[list[MasterCrudFieldSummary]]:
    fields = await MasterCrudService(db).form_for(category_id)

    return success_response(
        data=[MasterCrudFieldSummary.model_validate(field) for field in fields],
        message="Master CRUD form fetched",
    )


@router.get(
    "/by-slug/{slug}",
    response_model=APIResponse[MasterCrudRead],
    summary="Get a record by slug",
)
async def get_record_by_slug(
    db: DbSession, slug: Annotated[str, Path(description="Record slug.")]
) -> APIResponse[MasterCrudRead]:
    record = await MasterCrudService(db).get_by_slug(slug)

    return success_response(
        data=MasterCrudRead.from_model(record), message="Master CRUD record fetched"
    )


@router.get(
    "/{record_id}",
    response_model=APIResponse[MasterCrudRead],
    summary="Get a record",
    description="Carries every stored answer, each with the field it belongs to.",
)
async def get_record(
    db: DbSession, record_id: MasterCrudId
) -> APIResponse[MasterCrudRead]:
    record = await MasterCrudService(db).get(record_id)

    return success_response(
        data=MasterCrudRead.from_model(record), message="Master CRUD record fetched"
    )


@router.post(
    "",
    response_model=APIResponse[MasterCrudRead],
    status_code=status.HTTP_201_CREATED,
    summary="Create a record",
    description=(
        "`field_values` answers the fields defined on `category_id`. Every "
        "active required field must appear, a field from another category is "
        "refused, and each answer is validated against its field's type. "
        "Omitting `order` puts the record last in its category."
    ),
    dependencies=[can_create()],
)
async def create_record(
    db: DbSession, user: CurrentUser, payload: MasterCrudCreate
) -> APIResponse[MasterCrudRead]:
    record = await MasterCrudService(db).create(payload, actor_id=user.id)

    return created_response(
        data=MasterCrudRead.from_model(record), message="Master CRUD record created"
    )


@router.patch(
    "/{record_id}",
    response_model=APIResponse[MasterCrudRead],
    summary="Update a record",
    description=(
        "Sending `field_values` replaces the whole set of answers, which is "
        "what a form submission means; omitting it leaves them untouched. "
        "Moving a record to another category requires `field_values` for the "
        "new category's fields in the same request."
    ),
    dependencies=[can_update()],
)
async def update_record(
    db: DbSession,
    user: CurrentUser,
    record_id: MasterCrudId,
    payload: MasterCrudUpdate,
) -> APIResponse[MasterCrudRead]:
    record = await MasterCrudService(db).update(record_id, payload, actor_id=user.id)

    return success_response(
        data=MasterCrudRead.from_model(record), message="Master CRUD record updated"
    )


@router.delete(
    "/{record_id}",
    response_model=APIResponse[None],
    summary="Delete a record",
    description=(
        "Soft delete. The stored answers are kept - they are what a restore "
        "brings back."
    ),
    dependencies=[can_delete()],
)
async def delete_record(db: DbSession, record_id: MasterCrudId) -> APIResponse[None]:
    await MasterCrudService(db).delete(record_id)

    return deleted_response("Master CRUD record deleted")


@router.post(
    "/{record_id}/restore",
    response_model=APIResponse[MasterCrudRead],
    summary="Restore a deleted record",
    dependencies=[can_delete()],
)
async def restore_record(
    db: DbSession, record_id: MasterCrudId
) -> APIResponse[MasterCrudRead]:
    record = await MasterCrudService(db).restore(record_id)

    return success_response(
        data=MasterCrudRead.from_model(record), message="Master CRUD record restored"
    )
