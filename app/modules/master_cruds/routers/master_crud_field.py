"""Master CRUD field endpoints.

Reading requires `master_crud_field.view`; each write requires its own code -
see [permissions.py](../permissions.py).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.master_cruds.constants import FieldType, MasterCrudStatus
from app.modules.master_cruds.permissions import (
    can_create_fields,
    can_delete_fields,
    can_update_fields,
    can_view_fields,
)
from app.modules.master_cruds.schemas.master_crud_field import (
    MasterCrudFieldCreate,
    MasterCrudFieldRead,
    MasterCrudFieldSummary,
    MasterCrudFieldUpdate,
)
from app.modules.master_cruds.services.master_crud_field import MasterCrudFieldService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    paginated_response,
    success_response,
)

router = APIRouter(
    prefix="/master-crud-fields",
    tags=["Master CRUD Fields"],
    dependencies=[can_view_fields()],
)

FieldId = Annotated[uuid.UUID, Path(description="Master CRUD field identifier.")]


@router.get(
    "",
    response_model=APIResponse[Page[MasterCrudFieldRead]],
    summary="List field definitions",
    description=(
        "Search matches the field name. `category_id` narrows to one "
        "category's form, which is what an editing screen asks for."
    ),
)
async def list_fields(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    category_id: Annotated[
        uuid.UUID | None, Query(description="Filter by category.")
    ] = None,
    field_type: Annotated[
        FieldType | None, Query(description="Filter by input type.")
    ] = None,
    field_status: Annotated[
        MasterCrudStatus | None,
        Query(alias="status", description="Filter by status."),
    ] = None,
    required_only: Annotated[
        bool, Query(description="Only fields a record must answer.")
    ] = False,
) -> APIResponse[Page[MasterCrudFieldRead]]:
    items, total = await MasterCrudFieldService(db).list_fields(
        pagination,
        search=search.search,
        category_id=category_id,
        field_type=field_type,
        status=field_status,
        required_only=required_only,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order,
    )

    return paginated_response(
        [MasterCrudFieldRead.model_validate(item) for item in items],
        total,
        pagination,
        message="Master CRUD fields fetched",
    )


@router.get(
    "/by-category/{category_id}",
    response_model=APIResponse[list[MasterCrudFieldSummary]],
    summary="List one category's whole form",
    description=(
        "Every field defined on a category. `active_only` leaves out the ones "
        "no longer asked of new records."
    ),
)
async def list_fields_for_category(
    db: DbSession,
    category_id: Annotated[uuid.UUID, Path(description="Category identifier.")],
    active_only: Annotated[bool, Query(description="Leave retired fields out.")] = True,
) -> APIResponse[list[MasterCrudFieldSummary]]:
    fields = await MasterCrudFieldService(db).for_category(
        category_id, active_only=active_only
    )

    return success_response(
        data=[MasterCrudFieldSummary.model_validate(item) for item in fields],
        message="Master CRUD fields fetched",
    )


@router.get(
    "/{field_id}",
    response_model=APIResponse[MasterCrudFieldRead],
    summary="Get a field definition",
)
async def get_field(
    db: DbSession, field_id: FieldId
) -> APIResponse[MasterCrudFieldRead]:
    field = await MasterCrudFieldService(db).get(field_id)

    return success_response(
        data=MasterCrudFieldRead.model_validate(field),
        message="Master CRUD field fetched",
    )


@router.post(
    "",
    response_model=APIResponse[MasterCrudFieldRead],
    status_code=status.HTTP_201_CREATED,
    summary="Define a field",
    description=(
        "Adds one input to a category's form. Field names are unique within a "
        "category, so a stored answer always resolves to one question."
    ),
    dependencies=[can_create_fields()],
)
async def create_field(
    db: DbSession, user: CurrentUser, payload: MasterCrudFieldCreate
) -> APIResponse[MasterCrudFieldRead]:
    field = await MasterCrudFieldService(db).create(payload, actor_id=user.id)

    return created_response(
        data=MasterCrudFieldRead.model_validate(field),
        message="Master CRUD field created",
    )


@router.patch(
    "/{field_id}",
    response_model=APIResponse[MasterCrudFieldRead],
    summary="Update a field definition",
    description=(
        "Renaming and switching a field between active and inactive are "
        "always allowed. Changing its category or its type is refused once "
        "records have answered it - the stored answers could not survive "
        "either change."
    ),
    dependencies=[can_update_fields()],
)
async def update_field(
    db: DbSession,
    user: CurrentUser,
    field_id: FieldId,
    payload: MasterCrudFieldUpdate,
) -> APIResponse[MasterCrudFieldRead]:
    field = await MasterCrudFieldService(db).update(field_id, payload, actor_id=user.id)

    return success_response(
        data=MasterCrudFieldRead.model_validate(field),
        message="Master CRUD field updated",
    )


@router.delete(
    "/{field_id}",
    response_model=APIResponse[None],
    summary="Delete a field definition",
    description=(
        "Soft delete, refused while any record has answered the field - "
        "deleting it would leave those answers describing nothing. Set it "
        "inactive to stop asking it of new records."
    ),
    dependencies=[can_delete_fields()],
)
async def delete_field(db: DbSession, field_id: FieldId) -> APIResponse[None]:
    await MasterCrudFieldService(db).delete(field_id)

    return deleted_response("Master CRUD field deleted")


@router.post(
    "/{field_id}/restore",
    response_model=APIResponse[MasterCrudFieldRead],
    summary="Restore a deleted field definition",
    dependencies=[can_delete_fields()],
)
async def restore_field(
    db: DbSession, field_id: FieldId
) -> APIResponse[MasterCrudFieldRead]:
    field = await MasterCrudFieldService(db).restore(field_id)

    return success_response(
        data=MasterCrudFieldRead.model_validate(field),
        message="Master CRUD field restored",
    )
