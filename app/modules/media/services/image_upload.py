"""Common image-upload functionality, shared by any module that needs to
let a user attach a picture to a record - user avatars today, potentially
blog cover images or the like later.

Validation (type, size) happens here, once, regardless of which
`StorageBackend` ends up writing the bytes. The whole file is read into
memory rather than streamed to disk in chunks the way support-ticket
attachments are: images this module accepts are small and bounded by
`max_upload_size_mb`, and reading fully first is what lets `StorageBackend`
stay a plain "write these bytes" interface that a local disk write and an S3
`put_object` can implement identically.
"""

import uuid
from pathlib import PurePosixPath

from fastapi import UploadFile

from app.core.config import settings
from app.core.constants import ALLOWED_IMAGE_EXTENSIONS, BYTES_PER_MB
from app.core.exceptions import ValidationException
from app.modules.media.storage.base import StorageBackend

CHUNK_SIZE = 64 * 1024


class ImageUploadService:
    """Validates an upload and hands it to a `StorageBackend`."""

    def __init__(self, backend: StorageBackend) -> None:
        self.backend = backend

    async def upload(
        self, upload: UploadFile, *, subdirectory: str, base_url: str | None = None
    ) -> str:
        """Validate `upload` and store it under `subdirectory`, returning its URL.

        The stored name is always a fresh UUID, never the client-supplied
        filename - collision-free, and it discards anything a crafted
        filename might otherwise smuggle into the storage key. `base_url` is
        only meaningful to a local-disk backend (see `StorageBackend.save`);
        an S3 backend ignores it.
        """
        extension = self._validate_extension(upload.filename)
        data = await self._read_within_limit(upload, settings.max_upload_size_bytes)
        key = f"{subdirectory}/{uuid.uuid4().hex}{extension}"
        return await self.backend.save(
            data, key=key, content_type=upload.content_type, base_url=base_url
        )

    async def delete(self, url: str | None, *, base_url: str | None = None) -> None:
        """Best-effort removal of a previously uploaded image, by its URL.

        Silently does nothing for `None`, or a URL this backend did not
        produce (a hand-entered `avatar_url`, or a leftover from a backend
        this deployment no longer uses) - there is nothing safe to delete in
        either case.
        """
        if not url:
            return
        key = self.backend.key_from_url(url, base_url=base_url)
        if key is None:
            return
        await self.backend.delete(key)

    @staticmethod
    def _validate_extension(filename: str | None) -> str:
        if not filename or not filename.strip():
            raise ValidationException("The uploaded file has no name.")

        extension = PurePosixPath(filename).suffix.lower()
        if extension not in ALLOWED_IMAGE_EXTENSIONS:
            raise ValidationException(
                f"'{extension or filename}' is not an accepted image type. "
                f"Allowed: {', '.join(sorted(ALLOWED_IMAGE_EXTENSIONS))}."
            )
        return extension

    @staticmethod
    async def _read_within_limit(upload: UploadFile, ceiling: int) -> bytes:
        """Read the stream in chunks, stopping the moment it exceeds `ceiling`.

        `Content-Length` is whatever the client claims; this is checked
        against what actually arrives instead.
        """
        chunks: list[bytes] = []
        total = 0

        try:
            while chunk := await upload.read(CHUNK_SIZE):
                total += len(chunk)
                if total > ceiling:
                    raise ValidationException(
                        "That image is larger than the "
                        f"{ceiling // BYTES_PER_MB} MB limit."
                    )
                chunks.append(chunk)
        finally:
            await upload.close()

        if total == 0:
            raise ValidationException("The uploaded file is empty.")

        return b"".join(chunks)
