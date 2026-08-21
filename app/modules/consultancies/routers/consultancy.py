"""Consultancy CRUD endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.consultancies.constants import ConsultancyStatus, ConsultancyType
from app.modules.consultancies.permissions import (
    can_create,
    can_delete,
    can_update,
    can_view,
)
from app.modules.consultancies.schemas.consultancy import (
    ConsultancyCreate,
    ConsultancyRead,
    ConsultancySummary,
    ConsultancyUpdate,
)
from app.modules.consultancies.services.consultancy import ConsultancyService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    paginated_response,
    success_response,
)

router = APIRouter(
    prefix="/consultancies", tags=["Consultancies"], dependencies=[can_view()]
)
ConsultancyId = Annotated[uuid.UUID, Path(description="Consultancy identifier.")]


@router.get(
    "",
    response_model=APIResponse[Page[ConsultancySummary]],
    summary="List consultancies",
)
async def list_consultancies(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    consultancy_status: Annotated[
        ConsultancyStatus | None, Query(alias="status")
    ] = None,
    consultancy_type: Annotated[ConsultancyType | None, Query()] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    active_only: bool = False,
) -> APIResponse[Page[ConsultancySummary]]:
    items, total = await ConsultancyService(db).list_consultancies(
        pagination,
        search=search.search,
        status=consultancy_status,
        consultancy_type=consultancy_type.value if consultancy_type else None,
        category_id=category_id,
        active_only=active_only,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order,
    )
    return paginated_response(
        [ConsultancySummary.model_validate(item) for item in items],
        total,
        pagination,
        message="Consultancies fetched",
    )


@router.get(
    "/by-slug/{slug}",
    response_model=APIResponse[ConsultancyRead],
    summary="Get a consultancy by slug",
)
async def get_consultancy_by_slug(
    db: DbSession, slug: str
) -> APIResponse[ConsultancyRead]:
    consultancy = await ConsultancyService(db).get_by_slug(slug)
    return success_response(
        data=ConsultancyRead.from_model(consultancy), message="Consultancy fetched"
    )


@router.get(
    "/{consultancy_id}",
    response_model=APIResponse[ConsultancyRead],
    summary="Get a consultancy",
)
async def get_consultancy(
    db: DbSession, consultancy_id: ConsultancyId
) -> APIResponse[ConsultancyRead]:
    consultancy = await ConsultancyService(db).get(consultancy_id)
    return success_response(
        data=ConsultancyRead.from_model(consultancy), message="Consultancy fetched"
    )


@router.post(
    "",
    response_model=APIResponse[ConsultancyRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=[can_create()],
    summary="Create a consultancy",
)
async def create_consultancy(
    db: DbSession, user: CurrentUser, payload: ConsultancyCreate
) -> APIResponse[ConsultancyRead]:
    consultancy = await ConsultancyService(db).create(payload, actor_id=user.id)
    return created_response(
        data=ConsultancyRead.from_model(consultancy), message="Consultancy created"
    )


@router.patch(
    "/{consultancy_id}",
    response_model=APIResponse[ConsultancyRead],
    dependencies=[can_update()],
    summary="Update a consultancy",
)
async def update_consultancy(
    db: DbSession,
    user: CurrentUser,
    consultancy_id: ConsultancyId,
    payload: ConsultancyUpdate,
) -> APIResponse[ConsultancyRead]:
    consultancy = await ConsultancyService(db).update(
        consultancy_id, payload, actor_id=user.id
    )
    return success_response(
        data=ConsultancyRead.from_model(consultancy), message="Consultancy updated"
    )


@router.delete(
    "/{consultancy_id}",
    response_model=APIResponse[None],
    dependencies=[can_delete()],
    summary="Delete a consultancy",
)
async def delete_consultancy(
    db: DbSession, consultancy_id: ConsultancyId
) -> APIResponse[None]:
    await ConsultancyService(db).delete(consultancy_id)
    return deleted_response("Consultancy deleted")


@router.post(
    "/{consultancy_id}/restore",
    response_model=APIResponse[ConsultancyRead],
    dependencies=[can_delete()],
    summary="Restore a consultancy",
)
async def restore_consultancy(
    db: DbSession, consultancy_id: ConsultancyId
) -> APIResponse[ConsultancyRead]:
    consultancy = await ConsultancyService(db).restore(consultancy_id)
    return success_response(
        data=ConsultancyRead.from_model(consultancy), message="Consultancy restored"
    )
