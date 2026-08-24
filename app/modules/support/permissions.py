"""Authorization for the support module.

Two layers, and the split matters. A **permission** says what a role may do
at all - assign a ticket, write an internal note, export the queue. A
**scope** says which tickets those verbs reach: a student's own, a trainer's
assigned queue, or everything. Permissions are checked declaratively in route
signatures; scope is applied in the service, where the ticket is actually in
hand. Neither is sufficient alone - `ticket.reply` held by a student must not
let them reply to somebody else's ticket.
"""

from enum import StrEnum

from fastapi import Depends

from app.modules.auth.dependencies import require_permission


class SupportPermission(StrEnum):
    """Every verb the support desk recognises."""

    #: Read tickets within your scope - own, assigned, or all.
    VIEW = "ticket.view"
    #: Read every ticket regardless of who raised or owns it.
    VIEW_ALL = "ticket.view_all"
    CREATE = "ticket.create"
    REPLY = "ticket.reply"
    ASSIGN = "ticket.assign"
    STATUS = "ticket.status"
    PRIORITY = "ticket.priority"
    CATEGORY = "ticket.category"
    ESCALATE = "ticket.escalate"
    INTERNAL_NOTE = "ticket.internal_note"
    MERGE = "ticket.merge"
    EXPORT = "ticket.export"
    REPORT = "ticket.report"
    DELETE = "ticket.delete"


def can_view() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SupportPermission.VIEW))


def can_view_all() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SupportPermission.VIEW_ALL))


def can_create() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SupportPermission.CREATE))


def can_reply() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SupportPermission.REPLY))


def can_assign() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SupportPermission.ASSIGN))


def can_change_status() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SupportPermission.STATUS))


def can_change_priority() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SupportPermission.PRIORITY))


def can_change_category() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SupportPermission.CATEGORY))


def can_escalate() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SupportPermission.ESCALATE))


def can_write_internal_note() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SupportPermission.INTERNAL_NOTE))


def can_merge() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SupportPermission.MERGE))


def can_export() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SupportPermission.EXPORT))


def can_report() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SupportPermission.REPORT))


def can_delete() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(SupportPermission.DELETE))
