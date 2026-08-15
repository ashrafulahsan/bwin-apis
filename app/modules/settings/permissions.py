"""Permission codes governing the settings module."""

from enum import StrEnum


class SettingPermission(StrEnum):
    VIEW = "setting.view"
    UPDATE = "setting.update"
