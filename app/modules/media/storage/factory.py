"""Selects the configured storage backend.

One instance for the process's lifetime - `LocalStorageBackend` holds no
state worth discarding, and `S3StorageBackend` should reuse one `boto3`
client rather than reconnect per request.
"""

from functools import lru_cache

from app.core.config import settings
from app.core.constants import StorageBackend as StorageBackendKind
from app.modules.media.storage.base import StorageBackend
from app.modules.media.storage.local import LocalStorageBackend
from app.modules.media.storage.s3 import S3StorageBackend


@lru_cache
def get_storage_backend() -> StorageBackend:
    if settings.storage_backend is StorageBackendKind.S3:
        assert settings.aws_s3_bucket, "enforced by Settings validation"
        return S3StorageBackend(
            bucket=settings.aws_s3_bucket,
            region=settings.aws_region,
            access_key=(
                settings.aws_access_key_id.get_secret_value()
                if settings.aws_access_key_id
                else None
            ),
            secret_key=(
                settings.aws_secret_access_key.get_secret_value()
                if settings.aws_secret_access_key
                else None
            ),
            public_url_base=settings.aws_s3_public_url,
        )

    return LocalStorageBackend(base_dir=settings.upload_dir)
