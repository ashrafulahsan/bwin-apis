"""Request-scoped language state and the middleware that establishes it.

Routers read the language through `LanguageDep`. Layers that have no access
to the request - services, repositories, background helpers - read it through
`get_current_language()`, which is backed by a `ContextVar` the middleware
sets for the duration of each request.
"""

from contextvars import ContextVar, Token
from urllib.parse import parse_qs

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.constants import (
    ACCEPT_LANGUAGE_HEADER,
    CONTENT_LANGUAGE_HEADER,
    DEFAULT_LANGUAGE,
    LANGUAGE_QUERY_PARAM,
    Language,
)
from app.shared.utils.language import resolve_language

_current_language: ContextVar[Language] = ContextVar(
    "current_language", default=DEFAULT_LANGUAGE
)

#: Key under which the resolved language is stashed on the ASGI scope.
SCOPE_LANGUAGE_KEY = "language"


def get_current_language() -> Language:
    """The language for the current request, or the default outside one."""
    return _current_language.get()


def set_current_language(language: Language) -> Token[Language]:
    """Set the current language, returning a token for `reset_language`."""
    return _current_language.set(language)


def reset_language(token: Token[Language]) -> None:
    _current_language.reset(token)


def language_from_scope(scope: Scope) -> Language:
    """Resolve the request language from a raw ASGI scope."""
    headers = {key.decode("latin-1").lower(): value for key, value in scope["headers"]}
    accept_language = headers.get(ACCEPT_LANGUAGE_HEADER)

    return resolve_language(
        requested=_query_language(scope.get("query_string", b"")),
        accept_language=accept_language.decode("latin-1") if accept_language else None,
    )


def _query_language(query_string: bytes) -> str | None:
    """Read `?lang=` out of the raw query string."""
    values = parse_qs(query_string.decode("latin-1")).get(LANGUAGE_QUERY_PARAM)
    return values[0] if values else None


class LanguageMiddleware:
    """Resolve the request language and advertise it on the response.

    Written as raw ASGI rather than `BaseHTTPMiddleware` so the downstream
    application runs in the same task, which is what keeps the `ContextVar`
    visible to the endpoint and everything it calls.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        language = language_from_scope(scope)
        scope[SCOPE_LANGUAGE_KEY] = language
        token = set_current_language(language)

        async def send_with_language(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append(CONTENT_LANGUAGE_HEADER, language.value)
                # Responses differ by language, so a shared cache must key on
                # the header as well as the URL.
                headers.append("vary", "Accept-Language")
            await send(message)

        try:
            await self.app(scope, receive, send_with_language)
        finally:
            reset_language(token)
