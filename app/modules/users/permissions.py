"""Permission codes governing the users module."""

from enum import StrEnum


class UserPermission(StrEnum):
    VIEW = "user.view"
    CREATE = "user.create"
    UPDATE = "user.update"
    DELETE = "user.delete"
