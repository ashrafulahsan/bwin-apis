"""Storing and serving files attached to a support ticket.

Uploads are the part of a help desk most worth being paranoid about: the
files arrive from unauthenticated-adjacent users, carry names chosen by the
client, and are handed back to other people. Three rules follow from that and
are enforced here rather than left to callers.

**The name on disk is never the name from the client.** Every stored file is
named after its own row id plus a vetted extension, so a name containing
`../`, a null byte, or a Windows device name cannot reach the filesystem.
The original is kept as a label only.

**The path is checked after resolution, not before.** A path is only accepted
once `resolve()` has collapsed it and it still sits inside the upload root,
which is the check that survives symlinks and traversal both.

**Size is enforced while reading, not from the header.** `Content-Length` is
whatever the client says it is; the stream is what actually arrives.
"""

import shutil
import uuid
from mimetypes import guess_type
from pathlib import Path, PurePosixPath

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import BYTES_PER_MB
from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.modules.activity_logs.models.activity_log import ActivityAction, ActivityModule
from app.modules.settings.services.setting import SettingService
from app.modules.support import policy
from app.modules.support.constants import (
    ATTACHMENT_SUBDIRECTORY,
    DEFAULT_ALLOWED_EXTENSIONS,
    DEFAULT_MAX_ATTACHMENTS_PER_TICKET,
    DEFAULT_MAX_UPLOAD_MB,
    SupportSettingKey,
    TicketActivityType,
)
from app.modules.support.models.support_ticket import SupportTicket
from app.modules.support.models.support_ticket_attachment import (
    SupportTicketAttachment,
)
from app.modules.support.repositories.attachment import (
    SupportTicketAttachmentRepository,
)
from app.modules.support.repositories.ticket import SupportTicketRepository
from app.modules.users.models.user import User
from app.shared.services.activity_log_service import ActivityLogService, snapshot

#: Read in chunks so a large upload never sits in memory in one piece.
CHUNK_SIZE = 64 * 1024


class SupportAttachmentService:
    """Validates, stores, serves and removes ticket attachments."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = SupportTicketAttachmentRepository(session)
        self.tickets = SupportTicketRepository(session)
        self.settings = SettingService(session)
        self.activity = ActivityLogService(session, ActivityModule.SUPPORT)

        from app.modules.support.services.timeline import TicketTimeline

        self.timeline = TicketTimeline(session)

    # -- Configuration ----------------------------------------------------

    @property
    def root(self) -> Path:
        """The directory every attachment must resolve inside."""
        return (settings.upload_dir / ATTACHMENT_SUBDIRECTORY).resolve()

    async def max_upload_bytes(self) -> int:
        """The per-file ceiling, from the settings table.

        Falls back to the deployment's `max_upload_size_mb` when the row is
        missing, so an environment that has not been seeded still enforces a
        limit rather than none.
        """
        megabytes = await self.settings.number(
            SupportSettingKey.MAX_UPLOAD_MB,
            settings.max_upload_size_mb or DEFAULT_MAX_UPLOAD_MB,
        )
        return max(megabytes, 1) * BYTES_PER_MB

    async def allowed_extensions(self) -> frozenset[str]:
        raw = await self.settings.value(
            SupportSettingKey.ALLOWED_EXTENSIONS, DEFAULT_ALLOWED_EXTENSIONS
        )
        return frozenset(
            item.strip().lower()
            for item in (raw or DEFAULT_ALLOWED_EXTENSIONS).split(",")
            if item.strip()
        )

    async def max_per_ticket(self) -> int:
        return await self.settings.number(
            SupportSettingKey.MAX_ATTACHMENTS_PER_TICKET,
            DEFAULT_MAX_ATTACHMENTS_PER_TICKET,
        )

    # -- Upload -----------------------------------------------------------

    async def upload(
        self,
        ticket: SupportTicket,
        upload: UploadFile,
        *,
        actor: User,
        message_id: uuid.UUID | None = None,
    ) -> SupportTicketAttachment:
        """Validate and store one file against a ticket.

        The row is inserted before the bytes are written, because the row's
        id is what the file is named - that is what makes the name
        unguessable and collision-free without a second source of randomness.
        If writing then fails, the transaction is rolled back and no row
        survives pointing at a file that does not exist.
        """
        if not policy.can_view_ticket(actor, ticket):
            raise NotFoundException("SupportTicket")
        if not policy.can_reply_to(actor, ticket) and not policy.is_staff(actor):
            raise ForbiddenException("You may not attach files to this ticket.")
        if ticket.is_closed:
            raise BadRequestException(
                "This ticket is closed. Reopen it before attaching files."
            )

        original_name = self._safe_original_name(upload.filename)
        extension = PurePosixPath(original_name).suffix.lower()

        allowed = await self.allowed_extensions()
        if extension not in allowed:
            raise ValidationException(
                f"'{extension or original_name}' is not an accepted file type. "
                f"Allowed: {', '.join(sorted(allowed))}."
            )

        ceiling = await self.max_per_ticket()
        if await self.repository.count_for_ticket(ticket.id) >= ceiling:
            raise BadRequestException(
                f"This ticket already has the maximum of {ceiling} attachments."
            )

        attachment = await self.repository.create(
            ticket_id=ticket.id,
            message_id=message_id,
            file_name="",
            original_name=original_name,
            file_path="",
            file_size=0,
            mime_type=upload.content_type or guess_type(original_name)[0],
            uploaded_by=actor.id,
        )

        stored_name = f"{attachment.id}{extension}"
        relative_path = (
            PurePosixPath(ATTACHMENT_SUBDIRECTORY) / str(ticket.id) / stored_name
        )
        destination = self._resolve_within_root(
            self.root / str(ticket.id) / stored_name
        )
        destination.parent.mkdir(parents=True, exist_ok=True)

        written = await self._write(upload, destination, await self.max_upload_bytes())

        await self.repository.update(
            attachment,
            file_name=stored_name,
            file_path=str(relative_path),
            file_size=written,
        )
        await self.tickets.bump_counters(ticket, attachments=1)

        await self.timeline.activity(
            ticket,
            TicketActivityType.ATTACHMENT_UPLOADED,
            f"{actor.full_name} attached {original_name}.",
            actor_id=actor.id,
            metadata={
                "attachment_id": attachment.id,
                "file_size": written,
                "original_name": original_name,
            },
        )
        await self.activity.record(
            ActivityAction.UPLOAD,
            entity=ticket,
            description=(
                f"Attached {original_name} to support ticket {ticket.ticket_no}"
            ),
            new_values={
                "attachment_id": str(attachment.id),
                "original_name": original_name,
                "file_size": written,
            },
        )

        await self.session.commit()
        return attachment

    async def _write(self, upload: UploadFile, destination: Path, ceiling: int) -> int:
        """Stream the upload to disk, stopping the moment it exceeds `ceiling`.

        The partial file is removed on failure. Checking after the write
        would mean a caller could fill the disk with a file we then delete,
        which is a denial of service with extra steps.
        """
        written = 0

        try:
            with destination.open("wb") as target:
                while chunk := await upload.read(CHUNK_SIZE):
                    written += len(chunk)
                    if written > ceiling:
                        raise ValidationException(
                            "That file is larger than the "
                            f"{ceiling // BYTES_PER_MB} MB limit."
                        )
                    target.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

        if written == 0:
            destination.unlink(missing_ok=True)
            raise ValidationException("The uploaded file is empty.")

        return written

    # -- Download ---------------------------------------------------------

    async def open_for_download(
        self, attachment_id: uuid.UUID, *, actor: User
    ) -> tuple[SupportTicketAttachment, Path]:
        """Resolve an attachment to a path on disk, if the caller may have it.

        Serving through this method rather than mounting the upload directory
        is the whole point: a static mount would make every attachment
        readable by anyone who could guess a URL, and support attachments are
        exactly the files that must not be.
        """
        attachment = await self.repository.get_or_raise(attachment_id)
        ticket = await self.tickets.get_or_raise(attachment.ticket_id)

        if not policy.can_download_attachment(actor, ticket):
            raise NotFoundException("Attachment")

        path = self._resolve_within_root(settings.upload_dir / attachment.file_path)
        if not path.is_file():
            raise NotFoundException(
                message="The stored file for this attachment is missing."
            )

        return attachment, path

    # -- Removal ----------------------------------------------------------

    async def delete(self, attachment_id: uuid.UUID, *, actor: User) -> None:
        """Soft delete the row and remove the bytes.

        The row is kept so the ticket's history still shows that a file was
        attached and withdrawn; the file itself is not, because "delete this
        attachment" has to actually delete it.
        """
        attachment = await self.repository.get_or_raise(attachment_id)
        ticket = await self.tickets.get_or_raise(attachment.ticket_id)

        may_delete = policy.is_staff(actor) or (
            attachment.uploaded_by == actor.id and policy.is_owner(actor, ticket)
        )
        if not may_delete:
            raise ForbiddenException("You may not remove this attachment.")

        before = snapshot(attachment)
        await self.repository.soft_delete(attachment)
        await self.tickets.bump_counters(ticket, attachments=-1)

        path = self._resolve_within_root(settings.upload_dir / attachment.file_path)
        path.unlink(missing_ok=True)

        await self.activity.record(
            ActivityAction.DELETE,
            entity=ticket,
            description=(
                f"Removed attachment {attachment.original_name} from "
                f"ticket {ticket.ticket_no}"
            ),
            old_values=before,
        )
        await self.session.commit()

    async def purge_ticket_files(self, ticket_id: uuid.UUID) -> None:
        """Remove a ticket's whole attachment directory, ignoring absence."""
        directory = self._resolve_within_root(self.root / str(ticket_id))
        shutil.rmtree(directory, ignore_errors=True)

    # -- Path safety ------------------------------------------------------

    def _resolve_within_root(self, candidate: Path) -> Path:
        """Resolve a path and refuse anything that escapes the upload root.

        `resolve()` first, compare second. Comparing the unresolved path
        would be satisfied by `uploads/support_tickets/../../etc/passwd`,
        which is precisely the string this exists to reject.
        """
        resolved = Path(candidate).resolve()
        root = self.root

        if resolved != root and root not in resolved.parents:
            raise BadRequestException("That attachment path is not permitted.")

        return resolved

    @staticmethod
    def _safe_original_name(filename: str | None) -> str:
        """Reduce a client-supplied name to a bare label.

        Any directory component is discarded rather than sanitized: there is
        no legitimate upload whose name contains a path, so the safe reading
        of one is that somebody is trying something.
        """
        if not filename or not filename.strip():
            raise ValidationException("The uploaded file has no name.")

        # Both separators, because the name comes from the client's operating
        # system rather than ours.
        name = filename.replace("\\", "/").split("/")[-1].strip()
        name = name.replace("\x00", "")

        if not name or name in {".", ".."}:
            raise ValidationException("The uploaded file has no usable name.")

        return name[:255]
