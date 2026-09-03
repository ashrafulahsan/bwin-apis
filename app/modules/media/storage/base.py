"""Storage backend contract.

Every backend is handed the same thing to write - raw `bytes`, a `key` such
as `avatars/<uuid>.png`, and a content type - and hands back a URL. Callers
never see a filesystem path or an S3 client: swapping `storage_backend` in
settings is the entire migration between "on this application's disk" and
"on S3", because nothing above this layer knows which one it is talking to.

The URL a backend returns is stored as-is in columns like `users.avatar_url`
- which is why `LocalStorageBackend` returns a path relative to this
application's own origin (`/media/...`) rather than a full `http://host/...`
URL: the host this API happens to be reached at today (dev machine, staging
domain, production domain) has no business being baked into a database row.
S3 has no such option - an object's URL always includes its bucket's own
domain - so that backend's URLs are absolute, and that is fine: it is the
bucket's address being stored, not this application's.
"""

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Where uploaded bytes end up, and how they are read back."""

    @abstractmethod
    async def save(self, data: bytes, *, key: str, content_type: str | None) -> str:
        """Write `data` under `key` and return the URL it can be fetched from."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove whatever is stored at `key`. Missing is not an error."""

    @abstractmethod
    def key_from_url(self, url: str) -> str | None:
        """Recover the `key` a URL this backend previously returned was for.

        `None` if the URL was not produced by this backend (a hand-entered
        URL, or one from a different backend after a config change) - the
        caller's cue to leave it alone rather than guess.
        """
