"""Tests for the settings module."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.modules.settings.constants import (
    SECRET_MASK,
    SYSTEM_SETTINGS,
    SettingGroup,
    SettingKey,
    SettingType,
)
from app.modules.settings.models.setting import Setting
from app.modules.settings.schemas.setting import (
    SettingBulkUpdate,
    SettingCreate,
    SettingRead,
    SettingUpdate,
)
from app.modules.settings.services.setting import SettingService


@pytest.fixture
async def settings_service(session: AsyncSession) -> AsyncIterator[SettingService]:
    async def wipe() -> None:
        await session.execute(delete(Setting))
        await session.commit()

    await wipe()
    await SettingService(session).seed_system_settings()

    yield SettingService(session)

    await wipe()


# -- Seeding ------------------------------------------------------------


async def test_seeding_creates_every_system_setting(
    settings_service: SettingService,
) -> None:
    assert len(await settings_service.list_all()) == len(SYSTEM_SETTINGS)


async def test_seeding_twice_creates_nothing(
    settings_service: SettingService,
) -> None:
    assert await settings_service.seed_system_settings() == 0


async def test_seeding_never_overwrites_a_configured_credential(
    settings_service: SettingService,
    session: AsyncSession,
) -> None:
    """Re-running the seed must not wipe out real credentials."""
    await settings_service.set(SettingKey.GOOGLE_CLIENT_ID, "real-client-id")

    await SettingService(session).seed_system_settings()

    assert await settings_service.value(SettingKey.GOOGLE_CLIENT_ID) == "real-client-id"


async def test_credentials_ship_blank(settings_service: SettingService) -> None:
    """Real ones belong to whoever runs the platform, not to the repository."""
    assert await settings_service.value(SettingKey.GOOGLE_CLIENT_SECRET) is None
    assert await settings_service.value(SettingKey.FACEBOOK_APP_SECRET) is None


async def test_providers_ship_switched_off(settings_service: SettingService) -> None:
    assert await settings_service.flag(SettingKey.GOOGLE_AUTH_ENABLED) is False
    assert await settings_service.flag(SettingKey.FACEBOOK_AUTH_ENABLED) is False


# -- Typed reads --------------------------------------------------------


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("", False),
        ("nonsense", False),
    ],
)
async def test_boolean_settings_default_to_off(
    settings_service: SettingService, stored: str, expected: bool
) -> None:
    """Anything unrecognised leaves a feature off rather than switching it on."""
    await settings_service.set(SettingKey.GOOGLE_AUTH_ENABLED, stored)

    assert await settings_service.flag(SettingKey.GOOGLE_AUTH_ENABLED) is expected


async def test_an_absent_setting_reads_as_its_default(
    settings_service: SettingService,
) -> None:
    """A missing setting must not break the request that happened to read it."""
    assert await settings_service.value("no_such_setting", "fallback") == "fallback"
    assert await settings_service.flag("no_such_setting") is False


async def test_a_blank_value_counts_as_unset(
    settings_service: SettingService,
) -> None:
    await settings_service.set(SettingKey.GOOGLE_CLIENT_ID, "   ")
    setting = await settings_service.get(SettingKey.GOOGLE_CLIENT_ID)

    assert setting.is_set is False
    assert await settings_service.value(SettingKey.GOOGLE_CLIENT_ID) is None


async def test_require_refuses_an_unconfigured_setting(
    settings_service: SettingService,
) -> None:
    with pytest.raises(BadRequestException) as failure:
        await settings_service.require(SettingKey.GOOGLE_CLIENT_ID)

    assert SettingKey.GOOGLE_CLIENT_ID in failure.value.message


async def test_values_are_trimmed(settings_service: SettingService) -> None:
    """A pasted credential often carries a trailing newline."""
    await settings_service.set(SettingKey.GOOGLE_CLIENT_ID, "  abc123  \n")

    assert await settings_service.value(SettingKey.GOOGLE_CLIENT_ID) == "abc123"


# -- Writes -------------------------------------------------------------


async def test_setting_many_at_once(settings_service: SettingService) -> None:
    await settings_service.set_many(
        {
            SettingKey.GOOGLE_AUTH_ENABLED.value: "true",
            SettingKey.GOOGLE_CLIENT_ID.value: "id-1",
            SettingKey.GOOGLE_CLIENT_SECRET.value: "secret-1",
        }
    )

    assert await settings_service.flag(SettingKey.GOOGLE_AUTH_ENABLED) is True
    assert await settings_service.value(SettingKey.GOOGLE_CLIENT_ID) == "id-1"


async def test_a_bulk_update_returns_rows_that_can_be_rendered(
    settings_service: SettingService,
) -> None:
    """The UPDATE expires `updated_at`, and reading it lazily would raise.

    Not hypothetical: this was a 500 on `PATCH /settings` until the service
    refreshed each row before handing it back.
    """
    updated = await settings_service.set_many(
        {SettingKey.GOOGLE_CLIENT_ID.value: "id-render"}
    )

    rendered = [SettingRead.from_model(item) for item in updated]

    assert rendered[0].value == "id-render"
    assert rendered[0].updated_at is not None


async def test_one_unknown_key_rejects_the_whole_request(
    settings_service: SettingService,
) -> None:
    """A typo must not leave half a settings form applied."""
    with pytest.raises(NotFoundException):
        await settings_service.set_many(
            {
                SettingKey.GOOGLE_CLIENT_ID.value: "id-2",
                "gooogle_client_secret": "secret-2",
            }
        )

    assert await settings_service.value(SettingKey.GOOGLE_CLIENT_ID) is None


async def test_a_value_can_be_cleared(settings_service: SettingService) -> None:
    await settings_service.set(SettingKey.GOOGLE_CLIENT_ID, "id-3")

    await settings_service.set(SettingKey.GOOGLE_CLIENT_ID, None)

    assert await settings_service.value(SettingKey.GOOGLE_CLIENT_ID) is None


async def test_a_custom_setting_can_be_added_and_removed(
    settings_service: SettingService,
) -> None:
    created = await settings_service.create(
        SettingCreate(key="support_email", label="Support email", value="a@b.example")
    )

    assert created.is_system is False

    await settings_service.delete("support_email")

    with pytest.raises(NotFoundException):
        await settings_service.get("support_email")


async def test_a_duplicate_key_is_refused(settings_service: SettingService) -> None:
    with pytest.raises(ConflictException):
        await settings_service.create(
            SettingCreate(key=SettingKey.FRONTEND_URL.value, label="Duplicate")
        )


async def test_a_system_setting_cannot_be_deleted(
    settings_service: SettingService,
) -> None:
    """The application reads these by name; a missing row would break it."""
    with pytest.raises(ForbiddenException):
        await settings_service.delete(SettingKey.GOOGLE_CLIENT_ID)


# -- Secrets ------------------------------------------------------------


async def test_a_secret_is_masked_on_the_way_out(
    settings_service: SettingService,
) -> None:
    await settings_service.set(SettingKey.GOOGLE_CLIENT_SECRET, "top-secret-value")
    setting = await settings_service.get(SettingKey.GOOGLE_CLIENT_SECRET)

    rendered = SettingRead.from_model(setting)

    assert rendered.value == SECRET_MASK
    assert rendered.is_set is True
    assert "top-secret-value" not in rendered.model_dump_json()


async def test_an_unset_secret_reads_as_null_not_a_mask(
    settings_service: SettingService,
) -> None:
    """So an admin screen can tell 'not configured' from 'configured'."""
    rendered = SettingRead.from_model(
        await settings_service.get(SettingKey.GOOGLE_CLIENT_SECRET)
    )

    assert rendered.value is None
    assert rendered.is_set is False


async def test_a_non_secret_value_is_shown_in_full(
    settings_service: SettingService,
) -> None:
    rendered = SettingRead.from_model(
        await settings_service.get(SettingKey.FRONTEND_URL)
    )

    assert rendered.value == "http://localhost:3000"


def test_saving_the_mask_back_is_refused() -> None:
    """An admin form shows `********`; saving it unchanged must not store it."""
    with pytest.raises(ValueError, match="placeholder"):
        SettingUpdate(value=SECRET_MASK)


def test_saving_the_mask_in_a_bulk_update_is_refused() -> None:
    with pytest.raises(ValueError, match="placeholder"):
        SettingBulkUpdate(values={"google_client_secret": SECRET_MASK})


def test_only_credentials_are_marked_secret() -> None:
    """A URL is not a secret; publishing one as masked would just be noise."""
    secrets = {row["key"] for row in SYSTEM_SETTINGS if row["is_secret"]}

    assert secrets == {"google_client_secret", "facebook_app_secret"}


def test_every_setting_key_has_a_definition() -> None:
    """A key the code reads but the migration never seeds would read as unset."""
    seeded = {row["key"] for row in SYSTEM_SETTINGS}

    assert {key.value for key in SettingKey} == seeded


def test_every_definition_declares_a_known_type_and_group() -> None:
    for row in SYSTEM_SETTINGS:
        assert row["value_type"] in set(SettingType)
        assert row["group"] in set(SettingGroup)
        assert row["label"]
