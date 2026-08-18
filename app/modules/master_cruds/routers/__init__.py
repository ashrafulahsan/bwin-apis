from app.modules.master_cruds.routers.master_crud import router
from app.modules.master_cruds.routers.master_crud_field import (
    router as master_crud_field_router,
)

__all__ = ["master_crud_field_router", "router"]
