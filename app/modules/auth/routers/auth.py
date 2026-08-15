"""Authentication endpoints: sign in, refresh, sign out."""

from fastapi import APIRouter

from app.core.dependencies import DbSession
from app.modules.auth.dependencies import CurrentUser, SessionContextDep
from app.modules.auth.schemas.auth import (
    AuthenticatedUser,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    SessionRead,
    TokenPair,
)
from app.modules.auth.services.auth import AuthService
from app.modules.users.schemas.user import SocialLogin, UserRead
from app.shared.schemas.response import APIResponse, success_response

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/login",
    response_model=APIResponse[AuthenticatedUser],
    summary="Sign in with a password",
    description=(
        "`identifier` accepts an email address or a phone number, in any "
        "format - `01712345678` and `+8801712345678` reach the same account. "
        "Returns an access token for calling the API and a refresh token for "
        "keeping the session alive."
    ),
)
async def login(
    db: DbSession, payload: LoginRequest, context: SessionContextDep
) -> APIResponse[AuthenticatedUser]:
    result = await AuthService(db).login(payload, context)

    return success_response(data=result, message="Signed in")


@router.post(
    "/social",
    response_model=APIResponse[AuthenticatedUser],
    summary="Sign in with Google or Facebook",
    description=(
        "Exchanges an identity the caller has already verified with the "
        "provider for a session, creating the account on first sign-in. No "
        "password is involved, so an account created this way has none until "
        "the user sets one."
    ),
)
async def social_login(
    db: DbSession, payload: SocialLogin, context: SessionContextDep
) -> APIResponse[AuthenticatedUser]:
    result, created = await AuthService(db).social_login(payload, context)

    return success_response(
        data=result, message="Account created" if created else "Signed in"
    )


@router.post(
    "/refresh",
    response_model=APIResponse[TokenPair],
    summary="Renew an expiring session",
    description=(
        "Returns a new pair and retires the token presented, so each refresh "
        "token works exactly once. Presenting a retired one ends every "
        "session on the account, on the assumption it was stolen."
    ),
)
async def refresh(
    db: DbSession, payload: RefreshRequest, context: SessionContextDep
) -> APIResponse[TokenPair]:
    tokens = await AuthService(db).refresh(payload.refresh_token, context)

    return success_response(data=tokens, message="Session renewed")


@router.post(
    "/logout",
    response_model=APIResponse[None],
    summary="Sign out of this session",
    description=(
        "Revokes the refresh token supplied. The access token is not "
        "revocable and stays usable until it expires, which is why its "
        "lifetime is short - clients should discard it on sign-out."
    ),
)
async def logout(
    db: DbSession, user: CurrentUser, payload: LogoutRequest
) -> APIResponse[None]:
    await AuthService(db).logout(user.id, payload.refresh_token)

    return success_response(message="Signed out")


@router.post(
    "/logout-all",
    response_model=APIResponse[dict],
    summary="Sign out everywhere",
    description="Ends every session on the account, including this one.",
)
async def logout_all(db: DbSession, user: CurrentUser) -> APIResponse[dict]:
    ended = await AuthService(db).logout_everywhere(user.id)

    return success_response(
        data={"sessions_ended": ended}, message="Signed out of all sessions"
    )


@router.get(
    "/me",
    response_model=APIResponse[UserRead],
    summary="The signed-in user",
    description="Resolves the access token to its account, roles included.",
)
async def read_me(user: CurrentUser) -> APIResponse[UserRead]:
    return success_response(
        data=UserRead.model_validate(user), message="Profile fetched"
    )


@router.get(
    "/sessions",
    response_model=APIResponse[list[SessionRead]],
    summary="List your open sessions",
    description=(
        "One entry per device signed in, newest first. Pass "
        "`active_only=false` to include sessions already ended."
    ),
)
async def list_sessions(
    db: DbSession, user: CurrentUser, active_only: bool = True
) -> APIResponse[list[SessionRead]]:
    sessions = await AuthService(db).list_sessions(user.id, active_only=active_only)

    return success_response(
        data=[SessionRead.model_validate(item) for item in sessions],
        message="Sessions fetched",
    )
