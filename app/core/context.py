"""Request-scoped context: who is calling, and from where.

The activity log records the caller's address, agent, method and URL, and the
logging policy puts every log write in the service layer - which has no access
to the request object. A `ContextVar` bridges that gap, exactly as
`app.core.i18n` already does for the request language: the middleware
establishes it, the auth dependency fills in who the caller turned out to be,
and anything running inside that request reads it without being handed a
`Request` it has no other use for.

Outside a request - a seeder, a scheduled job, a test calling a service
directly - the context is simply empty, and the log records what it knows.
"""

import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from starlette.types import ASGIApp, Receive, Scope, Send

if TYPE_CHECKING:
    from app.modules.users.models.user import User

#: Header a reverse proxy uses to preserve the original client address.
FORWARDED_FOR_HEADER = "x-forwarded-for"

#: Lengths the activity log columns can hold. Values are clipped on the way
#: in rather than at the database, which would raise instead of truncating.
IP_ADDRESS_MAX_LENGTH = 45
USER_AGENT_MAX_LENGTH = 512
REQUEST_URL_MAX_LENGTH = 512
ROLE_NAME_MAX_LENGTH = 255


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Everything an audit record needs that is not part of the domain.

    Frozen: a request's origin does not change halfway through one. The
    caller's identity does become known partway - the token is decoded by a
    dependency, after the middleware has run - so `with_actor` returns a new
    context rather than mutating this one.
    """

    ip_address: str | None = None
    user_agent: str | None = None
    request_method: str | None = None
    request_url: str | None = None

    user_id: uuid.UUID | None = None
    user_name: str | None = None
    #: Every role the caller holds, comma separated. Accounts can hold more
    #: than one, and an audit trail that names only the first would be wrong
    #: about which authority the action was taken under.
    role_name: str | None = None

    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None

    def with_actor(self, user: "User") -> "RequestContext":
        """A copy of this context naming `user` as the caller."""
        roles = ", ".join(sorted(role.name for role in user.roles))

        return replace(
            self,
            user_id=user.id,
            user_name=user.full_name,
            role_name=roles[:ROLE_NAME_MAX_LENGTH] or None,
        )


EMPTY_CONTEXT = RequestContext()


@dataclass(slots=True)
class _Holder:
    """A mutable box around the immutable context.

    The `ContextVar` holds this rather than the context itself, and that
    indirection is load-bearing. The caller's identity is only known once the
    authentication dependency has decoded their token, and FastAPI resolves
    dependencies in a child context - so a dependency that *rebinds* the
    variable is writing into a copy that is discarded before the endpoint
    runs. Mutating an object the outer context already points at reaches
    everyone, because they are all looking at the same box.
    """

    context: RequestContext


#: Defaults to `None` rather than to a holder: a holder created here would be
#: one object shared by every request that never had a middleware run, and
#: binding an actor to it would leak that actor into the next one.
_current_context: ContextVar[_Holder | None] = ContextVar(
    "request_context", default=None
)


def get_request_context() -> RequestContext:
    """The context for the current request, or an empty one outside a request."""
    holder = _current_context.get()

    return holder.context if holder is not None else EMPTY_CONTEXT


def set_request_context(context: RequestContext) -> Token[_Holder | None]:
    """Start a new context, returning a token for `reset_request_context`."""
    return _current_context.set(_Holder(context))


def reset_request_context(token: Token[_Holder | None]) -> None:
    _current_context.reset(token)


def bind_actor(user: "User") -> RequestContext:
    """Record who the caller turned out to be, once their token is decoded.

    Called from the authentication dependency, and written as a mutation for
    the reason `_Holder` exists: rebinding the variable here would not be
    visible to the endpoint, or to any service it calls.
    """
    holder = _current_context.get()

    if holder is None:
        # No middleware ran - a background job, or a test driving a service
        # directly. The actor is still worth recording, so start a context.
        holder = _Holder(EMPTY_CONTEXT)
        _current_context.set(holder)

    holder.context = holder.context.with_actor(user)

    return holder.context


def client_ip(headers: dict[str, str], fallback: str | None = None) -> str | None:
    """The caller's address, preferring what a proxy says it was.

    `X-Forwarded-For` holds a comma-separated chain when proxies are in play
    and the first entry is the client. Only trustworthy behind a proxy that
    rewrites the header, which is why this feeds an audit record and never an
    access decision.
    """
    forwarded = headers.get(FORWARDED_FOR_HEADER)

    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first[:IP_ADDRESS_MAX_LENGTH]

    return fallback[:IP_ADDRESS_MAX_LENGTH] if fallback else None


def context_from_scope(scope: Scope) -> RequestContext:
    """Build the request half of the context from a raw ASGI scope."""
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }

    client = scope.get("client")
    user_agent = headers.get("user-agent")

    return RequestContext(
        ip_address=client_ip(headers, client[0] if client else None),
        user_agent=user_agent[:USER_AGENT_MAX_LENGTH] if user_agent else None,
        request_method=scope.get("method"),
        request_url=_url_from_scope(scope, headers)[:REQUEST_URL_MAX_LENGTH],
    )


def _url_from_scope(scope: Scope, headers: dict[str, str]) -> str:
    """Reassemble the URL the client asked for, host included when it sent one."""
    path = scope.get("root_path", "") + scope.get("path", "")
    query = scope.get("query_string", b"").decode("latin-1")

    target = f"{path}?{query}" if query else path
    host = headers.get("host")

    return f"{scope.get('scheme', 'http')}://{host}{target}" if host else target


class RequestContextMiddleware:
    """Establish the request context for the duration of each request.

    Raw ASGI rather than `BaseHTTPMiddleware`, for the same reason
    `LanguageMiddleware` is: the downstream application then runs in this same
    task, which is what keeps the `ContextVar` visible to the endpoint and to
    everything the endpoint calls.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        token = set_request_context(context_from_scope(scope))

        try:
            await self.app(scope, receive, send)
        finally:
            reset_request_context(token)
