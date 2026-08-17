"""The one place activity is recorded.

Every module writes its audit trail through this service and no other route,
which is what makes the trail uniform enough to query: one vocabulary of
actions, one shape for `old_values` and `new_values`, one set of redaction
rules, and one decision about where the caller's address comes from.

The service lives under `shared` because every module calls it; the table it
writes lives in its own module, like every other table in the schema.

**Where it is called from.** The service layer, always. A router knows the
request but not what the operation meant; a service knows what changed, what
it changed from, and whether it worked. Logging from a router also means
every future caller of that service - a job, a seeder, another service - goes
unlogged, which is the failure mode this rule exists to prevent.

**When it is written.** In the caller's session and inside the caller's
transaction, so the log row and the change it describes commit together or
not at all. An audit trail that survives a rolled-back transaction is worse
than none, because it describes something that never happened.

Failures are the exception: a rejected login has to leave a record precisely
because the request is about to raise and take its transaction with it, so
`record_detached` writes those on a session of their own.
"""

import logging
import uuid
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext, get_request_context
from app.modules.activity_logs.models.activity_log import (
    ENTITY_ID_MAX_LENGTH,
    ActivityAction,
    ActivityLog,
    ActivityModule,
    ActivityStatus,
)

if TYPE_CHECKING:
    from app.modules.users.models.user import User

logger = logging.getLogger(__name__)

#: What a redacted value is replaced with. A constant so a reader can tell
#: "this was hidden" from "this was empty", and so tests can assert on it.
REDACTED = "[redacted]"

#: Any field whose name contains one of these is never written to the log.
#: Substring matching rather than an exact list: `password`, `password_hash`,
#: `new_password` and `password_confirmation` all have to be caught, and a
#: column added next year should be caught without anyone remembering to come
#: back here.
SENSITIVE_FRAGMENTS: frozenset[str] = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "private_key",
        "credential",
        "authorization",
        "otp",
        "pin",
    }
)

#: Columns that say nothing an audit reader wants: surrogate keys and the
#: timestamps the log already carries itself.
NOISE_FIELDS: frozenset[str] = frozenset({"id", "created_at", "updated_at"})


def is_sensitive(field: str) -> bool:
    """Whether a field name must never have its value recorded."""
    lowered = field.lower()
    return any(fragment in lowered for fragment in SENSITIVE_FRAGMENTS)


def jsonable(value: Any) -> Any:
    """Convert a value into something JSONB can hold.

    UUIDs, datetimes and enums are the three that turn up in nearly every
    model and none of them survive a JSON encoder untouched.
    """
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [jsonable(item) for item in value]

    return str(value)


def snapshot(
    source: Any,
    *,
    fields: Iterable[str] | None = None,
    exclude: Iterable[str] = (),
) -> dict[str, Any]:
    """A JSON-safe picture of a model or mapping, with secrets removed.

    Given a model, its mapped columns are read; given a mapping, its keys
    are. Relationships are never followed - a snapshot is of one row, and
    walking `user.roles` here would load half the database into an audit
    record.
    """
    if source is None:
        return {}

    skip = set(exclude) | NOISE_FIELDS

    if isinstance(source, Mapping):
        available = dict(source)
    else:
        columns = source.__table__.columns.keys()
        available = {name: getattr(source, name, None) for name in columns}

    chosen = list(fields) if fields is not None else list(available)

    return {
        field: REDACTED if is_sensitive(field) else jsonable(available.get(field))
        for field in chosen
        if field in available and field not in skip
    }


def diff(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The fields that actually changed, as a `(old, new)` pair.

    An update that touched one column should not record forty unchanged ones:
    it buries the change, and it makes every audit row a full copy of the
    table. Fields present in only one of the two are treated as changed.
    """
    keys = [key for key in {**before, **after} if before.get(key) != after.get(key)]

    return (
        {key: before[key] for key in keys if key in before},
        {key: after[key] for key in keys if key in after},
    )


class ActivityLogService:
    """Records what happened, for one module.

    The module is bound once at construction, so a service that logs a dozen
    actions names it once:

        self.activity = ActivityLogService(session, ActivityModule.USERS)
        ...
        await self.activity.record(
            ActivityAction.CREATE,
            entity=user,
            description=f"Created user {user.email}",
            new_values=snapshot(user),
        )

    The row is added to the caller's session and flushed, not committed: the
    service that made the change owns the transaction and commits both
    together.
    """

    def __init__(
        self,
        session: AsyncSession,
        module: ActivityModule | str = ActivityModule.SYSTEM,
    ) -> None:
        self.session = session
        self.module = module

    async def record(
        self,
        action: ActivityAction | str,
        *,
        description: str,
        entity: Any = None,
        entity_type: str | None = None,
        entity_id: Any = None,
        old_values: Mapping[str, Any] | None = None,
        new_values: Mapping[str, Any] | None = None,
        actor: "User | None" = None,
        status: ActivityStatus = ActivityStatus.SUCCESS,
        module: ActivityModule | str | None = None,
        context: RequestContext | None = None,
    ) -> ActivityLog:
        """Write one entry.

        `entity` is a shortcut: passing the model fills in `entity_type` and
        `entity_id` from it, which is what nearly every call site wants.
        Either can still be given explicitly for the actions that are not
        about a row at all.

        `actor` overrides the caller taken from the request context. Sign-in
        is why it exists: the account is established by the very operation
        being logged, so at that moment the context does not yet know it.
        """
        resolved = context or get_request_context()

        if actor is not None:
            resolved = resolved.with_actor(actor)

        entry = ActivityLog(
            user_id=resolved.user_id,
            user_name=resolved.user_name,
            role_name=resolved.role_name,
            action=str(action),
            module=str(module or self.module),
            entity_type=entity_type or _type_of(entity),
            entity_id=_identify(entity_id if entity_id is not None else entity),
            description=description,
            old_values=dict(old_values) if old_values else None,
            new_values=dict(new_values) if new_values else None,
            ip_address=resolved.ip_address,
            user_agent=resolved.user_agent,
            request_method=resolved.request_method,
            request_url=resolved.request_url,
            status=status.value,
        )

        self.session.add(entry)
        await self.session.flush()

        return entry

    async def record_failure(
        self,
        action: ActivityAction | str,
        *,
        description: str,
        **kwargs: Any,
    ) -> ActivityLog:
        """Record an attempt that was refused, in the caller's transaction."""
        return await self.record(
            action, description=description, status=ActivityStatus.FAILURE, **kwargs
        )

    @classmethod
    async def record_detached(
        cls,
        action: ActivityAction | str,
        *,
        module: ActivityModule | str,
        description: str,
        status: ActivityStatus = ActivityStatus.FAILURE,
        **kwargs: Any,
    ) -> None:
        """Write an entry on a session of its own, and commit it immediately.

        For the actions that are about to raise. A rejected sign-in has to
        leave a trace, and anything written into the request's session would
        be rolled back by the exception that follows.

        A failure to write the trace is logged and swallowed. Everywhere else
        a failed audit write should fail the operation with it; here the
        operation has already failed, and replacing "invalid credentials"
        with a database error would tell the caller something untrue.
        """
        # Imported here rather than at module scope: `app.core.database`
        # builds the engine on import, and the seeding scripts rely on being
        # able to import services before that happens.
        from app.core.database import AsyncSessionFactory

        try:
            async with AsyncSessionFactory() as session:
                service = cls(session, module)
                await service.record(
                    action, description=description, status=status, **kwargs
                )
                await session.commit()
        except SQLAlchemyError:
            logger.exception("Could not write the activity log entry for %s", action)


def _type_of(entity: Any) -> str | None:
    """The entity's model name, which is what an audit reader recognises."""
    if entity is None:
        return None

    return type(entity).__name__


def _identify(entity: Any) -> str | None:
    """The entity's identifier as text, whatever kind of key it uses."""
    if entity is None:
        return None

    if isinstance(entity, str | uuid.UUID | int):
        return str(entity)[:ENTITY_ID_MAX_LENGTH]

    identifier = getattr(entity, "id", None)

    return str(identifier)[:ENTITY_ID_MAX_LENGTH] if identifier is not None else None
