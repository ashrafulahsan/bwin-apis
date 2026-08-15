"""Constants for the settings module.

Settings are runtime configuration an administrator can change without a
deployment: which social providers are switched on, the OAuth credentials they
use, where the frontend lives. Everything that must be known *before* the
application can boot - the database DSN, the JWT secret - stays in `.env`,
because it cannot be read from a table the application has not connected to
yet.
"""

from enum import StrEnum
from typing import TypedDict

SETTING_KEY_MAX_LENGTH = 100
SETTING_LABEL_MAX_LENGTH = 150
SETTING_GROUP_MAX_LENGTH = 50

#: Shown in place of a secret's value whenever it leaves the application.
SECRET_MASK = "********"


class SettingType(StrEnum):
    """How a stored string should be read back."""

    STRING = "string"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    JSON = "json"


class SettingGroup(StrEnum):
    """Which screen a setting belongs on."""

    GENERAL = "general"
    GOOGLE_AUTH = "google_auth"
    FACEBOOK_AUTH = "facebook_auth"


class SettingKey(StrEnum):
    """Every setting the platform reads by name.

    Referring to these rather than to bare strings means a typo is an
    `AttributeError` at import time instead of a silently missing value at
    runtime.
    """

    # -- General --------------------------------------------------------
    #: Public origin of the API itself, used to build callback URLs.
    APP_BASE_URL = "app_base_url"
    #: Where a browser is sent once a social sign-in completes.
    FRONTEND_URL = "frontend_url"
    #: Path appended to the frontend URL after a social sign-in.
    SOCIAL_LOGIN_REDIRECT_PATH = "social_login_redirect_path"
    #: Frontend page that takes a reset token and asks for a new password.
    PASSWORD_RESET_PATH = "password_reset_path"

    # -- Google ---------------------------------------------------------
    GOOGLE_AUTH_ENABLED = "google_auth_enabled"
    GOOGLE_CLIENT_ID = "google_client_id"
    GOOGLE_CLIENT_SECRET = "google_client_secret"
    GOOGLE_CALLBACK_URL = "google_callback_url"

    # -- Facebook -------------------------------------------------------
    FACEBOOK_AUTH_ENABLED = "facebook_auth_enabled"
    FACEBOOK_APP_ID = "facebook_app_id"
    FACEBOOK_APP_SECRET = "facebook_app_secret"
    FACEBOOK_CALLBACK_URL = "facebook_callback_url"


class SettingDefinition(TypedDict):
    key: str
    value: str | None
    value_type: str
    group: str
    label: str
    description: str
    is_secret: bool


def _definition(
    key: SettingKey,
    *,
    value: str | None,
    value_type: SettingType,
    group: SettingGroup,
    label: str,
    description: str,
    is_secret: bool = False,
) -> SettingDefinition:
    return {
        "key": key.value,
        "value": value,
        "value_type": value_type.value,
        "group": group.value,
        "label": label,
        "description": description,
        "is_secret": is_secret,
    }


#: Seeded by migration so every environment starts with the same rows. Values
#: are blank on purpose: real credentials belong to whoever runs the platform,
#: never to the repository.
SYSTEM_SETTINGS: list[SettingDefinition] = [
    _definition(
        SettingKey.APP_BASE_URL,
        value="http://127.0.0.1:8000",
        value_type=SettingType.STRING,
        group=SettingGroup.GENERAL,
        label="API base URL",
        description="Public origin of this API, used to build OAuth callbacks.",
    ),
    _definition(
        SettingKey.FRONTEND_URL,
        value="http://localhost:3000",
        value_type=SettingType.STRING,
        group=SettingGroup.GENERAL,
        label="Frontend URL",
        description="Where a browser is sent once a social sign-in completes.",
    ),
    _definition(
        SettingKey.SOCIAL_LOGIN_REDIRECT_PATH,
        value="/auth/callback",
        value_type=SettingType.STRING,
        group=SettingGroup.GENERAL,
        label="Social sign-in redirect path",
        description="Appended to the frontend URL after a social sign-in.",
    ),
    _definition(
        SettingKey.PASSWORD_RESET_PATH,
        value="/reset-password",
        value_type=SettingType.STRING,
        group=SettingGroup.GENERAL,
        label="Password reset page",
        description=(
            "Frontend page a reset link points at. The token is appended as "
            "`?token=`."
        ),
    ),
    _definition(
        SettingKey.GOOGLE_AUTH_ENABLED,
        value="false",
        value_type=SettingType.BOOLEAN,
        group=SettingGroup.GOOGLE_AUTH,
        label="Enable Google sign-in",
        description="Off until a client ID and secret have been filled in.",
    ),
    _definition(
        SettingKey.GOOGLE_CLIENT_ID,
        value=None,
        value_type=SettingType.STRING,
        group=SettingGroup.GOOGLE_AUTH,
        label="Google client ID",
        description="From the Google Cloud console, OAuth 2.0 Client IDs.",
    ),
    _definition(
        SettingKey.GOOGLE_CLIENT_SECRET,
        value=None,
        value_type=SettingType.STRING,
        group=SettingGroup.GOOGLE_AUTH,
        label="Google client secret",
        description="Issued alongside the client ID. Never leaves the server.",
        is_secret=True,
    ),
    _definition(
        SettingKey.GOOGLE_CALLBACK_URL,
        value=None,
        value_type=SettingType.STRING,
        group=SettingGroup.GOOGLE_AUTH,
        label="Google callback URL",
        description=(
            "Must match an authorized redirect URI exactly. Left blank, it is "
            "derived from the API base URL."
        ),
    ),
    _definition(
        SettingKey.FACEBOOK_AUTH_ENABLED,
        value="false",
        value_type=SettingType.BOOLEAN,
        group=SettingGroup.FACEBOOK_AUTH,
        label="Enable Facebook sign-in",
        description="Off until an app ID and secret have been filled in.",
    ),
    _definition(
        SettingKey.FACEBOOK_APP_ID,
        value=None,
        value_type=SettingType.STRING,
        group=SettingGroup.FACEBOOK_AUTH,
        label="Facebook app ID",
        description="From the Meta for Developers dashboard.",
    ),
    _definition(
        SettingKey.FACEBOOK_APP_SECRET,
        value=None,
        value_type=SettingType.STRING,
        group=SettingGroup.FACEBOOK_AUTH,
        label="Facebook app secret",
        description="Issued alongside the app ID. Never leaves the server.",
        is_secret=True,
    ),
    _definition(
        SettingKey.FACEBOOK_CALLBACK_URL,
        value=None,
        value_type=SettingType.STRING,
        group=SettingGroup.FACEBOOK_AUTH,
        label="Facebook callback URL",
        description=(
            "Must match a valid OAuth redirect URI exactly. Left blank, it is "
            "derived from the API base URL."
        ),
    ),
]

#: Values accepted as true when reading a boolean setting. Anything else is
#: false, so a blank or malformed value disables a feature rather than
#: enabling it by accident.
TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
