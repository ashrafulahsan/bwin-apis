"""Authentication endpoints: sign in, refresh, sign out."""

from fastapi import APIRouter

from app.core.dependencies import DbSession
from app.modules.auth.constants import RESET_REQUESTED_MESSAGE
from app.modules.auth.dependencies import CurrentUser, SessionContextDep
from app.modules.auth.schemas.auth import (
    AuthenticatedUser,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    PasswordChanged,
    RefreshRequest,
    ResetPasswordRequest,
    ResetTokenCheck,
    ResetTokenStatus,
    SessionRead,
    TokenPair,
)
from app.modules.auth.services.auth import AuthService
from app.modules.auth.services.password_reset import PasswordResetService
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


# -- Password recovery --------------------------------------------------


@router.post(
    "/forgot-password",
    response_model=APIResponse[None],
    summary="Ask for a password reset link",
    description=(
        "Takes an email address or a phone number, and answers the same way "
        "whether or not an account exists. That is deliberate: a form open to "
        "the internet that behaved differently for a registered address would "
        "be a way to enumerate the platform's users.\n\n"
        "Requests are throttled per account, so this cannot be used to flood "
        "somebody else's inbox. The throttle is invisible in the response, for "
        "the same reason."
    ),
)
async def forgot_password(
    db: DbSession, payload: ForgotPasswordRequest, context: SessionContextDep
) -> APIResponse[None]:
    await PasswordResetService(db).request(payload.identifier, context)

    return success_response(message=RESET_REQUESTED_MESSAGE)


@router.post(
    "/reset-password/verify",
    response_model=APIResponse[ResetTokenStatus],
    summary="Check a reset link before using it",
    description=(
        "For the page behind the link, so it can say the link has expired "
        "before asking someone to think of a new password. Sent as a body "
        "rather than in the path, to keep the token out of access logs."
    ),
)
async def verify_reset_token(
    db: DbSession, payload: ResetTokenCheck
) -> APIResponse[ResetTokenStatus]:
    status_ = await PasswordResetService(db).check(payload.token)

    return success_response(data=status_, message="Reset link checked")


@router.post(
    "/reset-password",
    response_model=APIResponse[None],
    summary="Set a new password with a reset link",
    description=(
        "Each link works exactly once, and asking for a new one retires any "
        "still outstanding.\n\n"
        "A successful reset **ends every session on the account**. A reset "
        "usually follows a compromise, so whoever prompted it should not keep "
        "their access. Signing in again afterwards is expected."
    ),
)
async def reset_password(
    db: DbSession, payload: ResetPasswordRequest
) -> APIResponse[None]:
    await PasswordResetService(db).reset(payload.token, payload.new_password)

    return success_response(message="Password updated. You can now sign in with it.")


@router.post(
    "/change-password",
    response_model=APIResponse[PasswordChanged],
    summary="Change your own password",
    description=(
        "For someone already signed in, which is why no link is involved. "
        "`current_password` is required when the account has one; an account "
        "created through Google can set its first without.\n\n"
        "Every existing token is retired, **including the one that made this "
        "request** - a password change is usually prompted by a suspicion, and "
        "leaving the old access tokens working for the rest of their lifetime "
        "would defeat it. A replacement pair comes back in the response, so "
        "the client making the change stays signed in; swap to it."
    ),
)
async def change_password(
    db: DbSession,
    user: CurrentUser,
    payload: ChangePasswordRequest,
    context: SessionContextDep,
) -> APIResponse[PasswordChanged]:
    ended, tokens = await PasswordResetService(db).change_password(
        user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        sign_out_other_sessions=payload.sign_out_other_sessions,
        context=context,
    )

    return success_response(
        data=PasswordChanged(sessions_ended=ended, tokens=tokens),
        message="Password changed",
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
