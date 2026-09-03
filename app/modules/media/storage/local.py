"""Local-disk storage backend - writes under `settings.upload_dir`.

Files are served back out through the `/media` static mount in
`app/main.py`, so the URL this returns is directly fetchable without going
through the API at all - the same shape a public S3 bucket URL would have.
This is the right tradeoff for the images this module handles (avatars and
similar), which are meant to be publicly viewable; it is deliberately not
the pattern support-ticket attachments use, which are private and are served
through an authenticated download endpoint instead.

Unlike S3, this backend has no address of its own - a file on this disk
isn't reachable at all without knowing which host is serving it. `base_url`
is required on every call for exactly that reason: it comes from the
`app_base_url` setting (see `UserService._app_base_url`), the single place
this application's own public origin is configured, rather than a
second, easily-stale copy of the same value.
"""

from pathlib import Path

from app.core.exceptions import BadRequestException
from app.modules.media.constants import MEDIA_MOUNT_PATH
from app.modules.media.storage.base import StorageBackend


class LocalStorageBackend(StorageBackend):
    def __init__(self, *, base_dir: Path) -> None:
        self.base_dir = base_dir.resolve()

    async def save(
        self,
        data: bytes,
        *,
        key: str,
        content_type: str | None,
        base_url: str | None = None,
    ) -> str:
        if not base_url:
            raise ValueError(
                "LocalStorageBackend.save() requires base_url - the "
                "application's own public origin."
            )

        destination = self._resolve(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return f"{self._media_root(base_url)}/{key}"

    async def delete(self, key: str) -> None:
        self._resolve(key).unlink(missing_ok=True)

    def key_from_url(self, url: str, *, base_url: str | None = None) -> str | None:
        if not base_url:
            return None

        prefix = f"{self._media_root(base_url)}/"
        if not url.startswith(prefix):
            return None
        return url.removeprefix(prefix)

    @staticmethod
    def _media_root(base_url: str) -> str:
        return f"{base_url.rstrip('/')}{MEDIA_MOUNT_PATH}"

    def _resolve(self, key: str) -> Path:
        """Resolve `key` and refuse anything that would escape `base_dir`.

        `resolve()` first, compare second - the check that survives symlinks
        and `../` traversal both, since comparing the unresolved path would
        let `avatars/../../.env` through.
        """
        resolved = (self.base_dir / key).resolve()
        if resolved != self.base_dir and self.base_dir not in resolved.parents:
            raise BadRequestException("That storage key is not permitted.")
        return resolved
