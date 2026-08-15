"""Social sign-in endpoints: the browser-facing OAuth 2.0 flow.

Two steps per provider. `/login` sends the browser to Google or Facebook;
`/callback` is where the provider sends it back, with a one-time code this
server trades for a profile - the client secret never touches the browser.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.config import settings
from app.core.constants import ErrorCode
from app.core.dependencies import DbSession
from app.core.exceptions import AppException
from app.modules.auth.dependencies import SessionContextDep
from app.modules.auth.oauth import state as oauth_state
from app.modules.auth.schemas.auth import AuthenticatedUser
from app.modules.auth.services.oauth import OAuthService
from app.modules.settings.schemas.setting import ProviderStatus
from app.modules.users.constants import SocialProvider
from app.shared.schemas.response import (
    APIResponse,
    error_response,
    success_response,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Social Login"])

ProviderPath = Annotated[SocialProvider, Path(description="`google` or `facebook`.")]

RedirectQuery = Annotated[
    str | None,
    Query(
        description=(
            "Where to send the browser afterwards. Honoured only when it is "
            "on the configured frontend's origin."
        )
    ),
]


@router.get(
    "/providers",
    response_model=APIResponse[list[ProviderStatus]],
    summary="Which social providers are usable",
    description=(
        "What a sign-in page needs to decide which buttons to show. Reports "
        "whether each provider is switched on and configured, and never "
        "returns a credential."
    ),
)
async def list_providers(db: DbSession) -> APIResponse[list[ProviderStatus]]:
    return success_response(
        data=await OAuthService(db).statuses(), message="Providers fetched"
    )


@router.get(
    "/{provider}/login",
    summary="Start a social sign-in",
    description=(
        "Redirects the browser to the provider's consent screen. Sets a "
        "short-lived HttpOnly cookie holding the nonce that ties the callback "
        "to this browser, which is what stops an attacker completing a "
        "sign-in inside someone else's session.\n\n"
        "Reachable as `/auth/google/login` and `/auth/facebook/login`."
    ),
    responses={
        307: {"description": "Redirect to the provider's consent screen."},
        403: {"description": "The provider is switched off."},
    },
)
async def social_login(
    db: DbSession, provider: ProviderPath, redirect_to: RedirectQuery = None
) -> RedirectResponse:
    nonce = oauth_state.new_nonce()
    state = oauth_state.issue(provider.value, nonce, redirect_to)

    destination = await OAuthService(db).authorization_url(
        provider.as_auth_provider(), state
    )

    response = RedirectResponse(destination)
    _set_state_cookie(response, provider, nonce)
    return response


@router.get(
    "/{provider}/callback",
    summary="Finish a social sign-in",
    description=(
        "Where the provider sends the browser back. Exchanges the code, "
        "creates or links the account, and redirects to the frontend with the "
        "tokens in the URL **fragment** - a fragment never reaches a server, "
        "so it stays out of access logs and `Referer` headers.\n\n"
        "With no frontend URL configured the tokens come back as JSON "
        "instead, which is what makes the flow usable without a frontend.\n\n"
        "Reachable as `/auth/google/callback` and `/auth/facebook/callback`."
    ),
    response_model=None,
)
async def social_callback(
    db: DbSession,
    request: Request,
    provider: ProviderPath,
    context: SessionContextDep,
    code: Annotated[
        str | None, Query(description="One-time authorization code.")
    ] = None,
    state: Annotated[str | None, Query(description="Value issued by `/login`.")] = None,
    error: Annotated[
        str | None, Query(description="Set when the user declined, or it failed.")
    ] = None,
) -> Response:
    service = OAuthService(db)
    nonce = request.cookies.get(oauth_state.cookie_name(provider.value))

    # A refusal is reported in the query string rather than by failing the
    # request, so a cancelled sign-in arrives here looking like a success.
    if error:
        logger.info("%s sign-in was not completed: %s", provider.value, error)
        return await _fail(
            service, provider, "The sign-in was cancelled or refused.", None
        )

    if not code:
        return await _fail(service, provider, "The sign-in is missing its code.", None)

    try:
        verified = oauth_state.verify(state or "", provider.value, nonce)
    except oauth_state.InvalidStateError as exc:
        logger.warning("Rejected %s callback: %s", provider.value, exc)
        return await _fail(service, provider, str(exc), None)

    try:
        result, created = await service.complete(
            provider.as_auth_provider(), code, context
        )
    except AppException as exc:
        # Everything from here on happens mid-redirect, where the browser
        # cannot show a JSON error body - so failures go back to the frontend.
        return await _fail(service, provider, exc.message, verified.redirect_to)

    destination = await service.success_redirect(result, verified.redirect_to)
    response: Response = (
        RedirectResponse(destination)
        if destination
        else _tokens_as_json(result, created)
    )

    _clear_state_cookie(response, provider)
    return response


# -- Helpers ------------------------------------------------------------


def _tokens_as_json(result: AuthenticatedUser, created: bool) -> Response:
    """Fallback when no frontend URL is configured."""
    envelope = success_response(
        data=result, message="Account created" if created else "Signed in"
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


async def _fail(
    service: OAuthService,
    provider: SocialProvider,
    message: str,
    requested: str | None,
) -> Response:
    """Send the browser back to the frontend with the reason it failed."""
    destination = await service.failure_redirect(message, requested)

    response: Response = (
        RedirectResponse(destination)
        if destination
        else JSONResponse(
            status_code=400,
            content=error_response(message=message, error_code=ErrorCode.BAD_REQUEST),
        )
    )

    _clear_state_cookie(response, provider)
    return response


def _set_state_cookie(response: Response, provider: SocialProvider, nonce: str) -> None:
    response.set_cookie(
        key=oauth_state.cookie_name(provider.value),
        value=nonce,
        max_age=int(oauth_state.STATE_TTL.total_seconds()),
        # Unreadable to JavaScript, so an XSS bug cannot lift the nonce.
        httponly=True,
        # `lax` rather than `strict`: the callback is a top-level navigation
        # from the provider's domain, and `strict` would withhold the cookie
        # exactly when it is needed. `none` would defeat the purpose.
        samesite="lax",
        # HTTPS only, except in local development where there is no
        # certificate to be had.
        secure=not settings.debug,
        path="/",
    )


def _clear_state_cookie(response: Response, provider: SocialProvider) -> None:
    """One sign-in, one nonce - spent either way, success or failure."""
    response.delete_cookie(
        key=oauth_state.cookie_name(provider.value),
        httponly=True,
        samesite="lax",
        secure=not settings.debug,
        path="/",
    )
