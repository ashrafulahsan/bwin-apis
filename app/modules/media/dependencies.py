"""FastAPI dependency aliases for the media module."""

from typing import Annotated

from fastapi import Depends

from app.modules.media.storage import StorageBackend, get_storage_backend

StorageDep = Annotated[StorageBackend, Depends(get_storage_backend)]
