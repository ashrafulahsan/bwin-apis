"""Storage backend contract.

Every backend is handed the same thing to write - raw `bytes`, a `key` such
as `avatars/<uuid>.png`, and a content type - and hands back a URL. Callers
never see a filesystem path or an S3 client: swapping `storage_backend` in
settings is the entire migration between "on this application's disk" and
"on S3", because nothing above this layer knows which one it is talking to.

`base_url` is the one thing that is backend-specific rather than generic:
the local backend has no origin of its own and must be told the running
application's public address (the `app_base_url` setting - see
`UserService._app_base_url`) to build a fetchable URL; S3 always serves from
its own bucket/CDN domain regardless and ignores it.
"""

from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Where uploaded bytes end up, and how they are read back."""

    @abstractmethod
    async def save(
        self,
        data: bytes,
        *,
        key: str,
        content_type: str | None,
        base_url: str | None = None,
    ) -> str:
        """Write `data` under `key` and return the URL it can be fetched from."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove whatever is stored at `key`. Missing is not an error."""

    @abstractmethod
    def key_from_url(self, url: str, *, base_url: str | None = None) -> str | None:
        """Recover the `key` a URL this backend previously returned was for.

        `None` if the URL was not produced by this backend (a hand-entered
        URL, or one from a different backend after a config change) - the
        caller's cue to leave it alone rather than guess.
        """
