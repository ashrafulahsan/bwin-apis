"""S3 storage backend.

`boto3` is a synchronous library with no async client, so every call goes
through `asyncio.to_thread` rather than blocking the event loop - the same
reason the rest of this codebase keeps blocking I/O off the request path.

Credentials are only passed to `boto3.client` when explicitly configured;
left unset, boto3 falls back to its own default credential chain (env vars,
shared config file, or an EC2/ECS instance role), which is the normal setup
for a deployed environment.
"""

import asyncio
from functools import cached_property
from typing import Any

from app.modules.media.storage.base import StorageBackend


class S3StorageBackend(StorageBackend):
    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        access_key: str | None,
        secret_key: str | None,
        public_url_base: str | None,
    ) -> None:
        self.bucket = bucket
        self.region = region
        self._access_key = access_key
        self._secret_key = secret_key
        self.base_url = (
            public_url_base or f"https://{bucket}.s3.{region}.amazonaws.com"
        ).rstrip("/")

    @cached_property
    def _client(self) -> Any:
        # Imported lazily so a `local`-only deployment never needs boto3
        # installed at all - only constructing this backend does.
        import boto3

        kwargs: dict[str, str] = {"region_name": self.region}
        if self._access_key and self._secret_key:
            kwargs["aws_access_key_id"] = self._access_key
            kwargs["aws_secret_access_key"] = self._secret_key
        return boto3.client("s3", **kwargs)

    async def save(
        self,
        data: bytes,
        *,
        key: str,
        content_type: str | None,
        base_url: str | None = None,
    ) -> str:
        # base_url is irrelevant here - S3 always serves from its own
        # bucket/CDN domain, never the application's own origin.
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type or "application/octet-stream",
        )
        return f"{self.base_url}/{key}"

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)

    def key_from_url(self, url: str, *, base_url: str | None = None) -> str | None:
        prefix = f"{self.base_url}/"
        if not url.startswith(prefix):
            return None
        return url.removeprefix(prefix)
