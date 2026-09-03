"""Local-disk storage backend - writes under `settings.upload_dir`.

Files are served back out through the `/media` static mount in
`app/main.py`, so the path this returns is directly fetchable from that
mount without going through the API at all. Unlike S3, this backend has no
domain of its own, so the URL it hands back is relative
(`/media/users/<uuid>.png`) rather than absolute - whoever renders it (the
admin panel) already knows which origin it is talking to and resolves the
path against that, the same way a browser resolves any other relative URL.
Storing an absolute one would bake today's host into the database row.
"""

from pathlib import Path

from app.core.exceptions import BadRequestException
from app.modules.media.constants import MEDIA_MOUNT_PATH
from app.modules.media.storage.base import StorageBackend


class LocalStorageBackend(StorageBackend):
    def __init__(self, *, base_dir: Path) -> None:
        self.base_dir = base_dir.resolve()

    async def save(self, data: bytes, *, key: str, content_type: str | None) -> str:
        destination = self._resolve(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return f"{MEDIA_MOUNT_PATH}/{key}"

    async def delete(self, key: str) -> None:
        self._resolve(key).unlink(missing_ok=True)

    def key_from_url(self, url: str) -> str | None:
        prefix = f"{MEDIA_MOUNT_PATH}/"
        if not url.startswith(prefix):
            return None
        return url.removeprefix(prefix)

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
