"""Dependencies that resolve the caller of a request.

`CurrentUser` is the one most routes want: it requires a valid access token
and hands back the `User` behind it. The guard factories build on it to
express "this route needs a permission" declaratively, in the signature, so
the check cannot be forgotten inside a handler body.
"""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.dependencies import DbSession
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.modules.auth.schemas.auth import SessionContext
from app.modules.auth.services.auth import AuthService
from app.modules.users.models.user import User

#: `auto_error=False` so a missing header reaches our own handler and comes
#: back in the project's error envelope, rather than Starlette's bare `detail`.
bearer_scheme = HTTPBearer(
    scheme_name="Bearer",
    description="Paste the `access_token` returned by `/auth/login`.",
    auto_error=False,
)

Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


async def get_current_user(db: DbSession, credentials: Credentials) -> User:
    """The signed-in user, or a 401."""
    if credentials is None or not credentials.credentials:
        raise UnauthorizedException("An access token is required for this endpoint.")

    return await AuthService(db).authenticate(credentials.credentials)


async def get_optional_user(db: DbSession, credentials: Credentials) -> User | None:
    """The signed-in user if there is one, otherwise `None`.

    For endpoints that serve anonymous callers but tailor the response when
    they can - a published page that also shows draft controls to an editor.
    An invalid token is still rejected: silently treating a bad token as
    anonymous would hide expiry bugs from clients.
    """
    if credentials is None or not credentials.credentials:
        return None

    return await AuthService(db).authenticate(credentials.credentials)


def get_session_context(request: Request) -> SessionContext:
    """Where the request came from, recorded against the session it opens.

    `X-Forwarded-For` holds a comma-separated chain when proxies are in play;
    the first entry is the client. Only trustworthy behind a proxy that
    rewrites the header - it is used for recognising your own sessions, never
    for an access decision.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip_address = forwarded.split(",")[0].strip()
    else:
        ip_address = request.client.host if request.client else None

    user_agent = request.headers.get("user-agent")

    return SessionContext(
        user_agent=user_agent[:255] if user_agent else None,
        ip_address=ip_address,
    )


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
SessionContextDep = Annotated[SessionContext, Depends(get_session_context)]


# -- Authorization guards -----------------------------------------------

UserDependency = Callable[[User], Coroutine[Any, Any, User]]


def require_permission(*codes: str, require_all: bool = True) -> UserDependency:
    """Build a dependency demanding permissions, e.g. `user.create`.

        @router.post("", dependencies=[Depends(require_permission("user.create"))])

    Defaults to requiring every code listed; pass `require_all=False` when any
    one of them is enough.
    """

    async def guard(user: CurrentUser) -> User:
        held = user.permission_codes
        satisfied = (
            all(code in held for code in codes)
            if require_all
            else any(code in held for code in codes)
        )

        if not satisfied:
            missing = sorted(set(codes) - held)
            if len(missing) == 1:
                raise ForbiddenException(
                    f"This action requires the '{missing[0]}' permission."
                )

            joiner = " and " if require_all else " or "
            listed = joiner.join(f"'{code}'" for code in missing)
            raise ForbiddenException(f"This action requires {listed}.")

        return user

    return guard


def require_role(*slugs: str) -> UserDependency:
    """Build a dependency demanding one of the named roles.

    Prefer `require_permission`: naming a permission says what the endpoint
    does, and stays correct when roles are reorganised. This is for the few
    checks that really are about who someone is rather than what they may do.
    """

    async def guard(user: CurrentUser) -> User:
        if not user.role_slugs & set(slugs):
            raise ForbiddenException(
                f"This action is limited to: {', '.join(sorted(slugs))}."
            )

        return user

    return guard
