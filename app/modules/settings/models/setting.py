"""Setting model: runtime configuration held in the database."""

import json

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.settings.constants import (
    SETTING_GROUP_MAX_LENGTH,
    SETTING_KEY_MAX_LENGTH,
    SETTING_LABEL_MAX_LENGTH,
    TRUE_VALUES,
    SettingType,
)


class Setting(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One configurable value.

    Everything is stored as text and read back through the typed accessors
    below. One column rather than one per type keeps the table readable and
    means adding a new kind of setting never needs a migration.
    """

    key: Mapped[str] = mapped_column(
        String(SETTING_KEY_MAX_LENGTH),
        unique=True,
        index=True,
        nullable=False,
        doc="Stable identifier, e.g. `google_client_id`.",
    )
    value: Mapped[str | None] = mapped_column(
        Text, default=None, doc="Null means unset, which is not the same as blank."
    )
    value_type: Mapped[str] = mapped_column(
        String(20), default=SettingType.STRING.value, nullable=False
    )
    group: Mapped[str] = mapped_column(
        String(SETTING_GROUP_MAX_LENGTH),
        default="general",
        nullable=False,
        index=True,
        doc="Which admin screen this belongs on.",
    )

    label: Mapped[str] = mapped_column(String(SETTING_LABEL_MAX_LENGTH), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)

    is_secret: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Masked whenever it leaves the application.",
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Shipped with the platform; the key cannot be renamed or deleted.",
    )

    # -- Typed access ---------------------------------------------------

    @property
    def is_set(self) -> bool:
        """Whether a usable value has been filled in."""
        return self.value is not None and self.value.strip() != ""

    def as_str(self) -> str | None:
        return self.value.strip() if self.is_set else None

    def as_bool(self) -> bool:
        """Anything unrecognised reads as false.

        A feature guarded by a setting should stay off when its value is
        blank or malformed, rather than switch itself on.
        """
        return self.value.strip().lower() in TRUE_VALUES if self.is_set else False

    def as_int(self, default: int = 0) -> int:
        if not self.is_set:
            return default
        try:
            return int(self.value.strip())  # type: ignore[union-attr]
        except ValueError:
            return default

    def as_json(self) -> object:
        if not self.is_set:
            return None
        try:
            return json.loads(self.value)  # type: ignore[arg-type]
        except json.JSONDecodeError:
            return None

    def __repr__(self) -> str:
        return f"<Setting {self.key}>"
