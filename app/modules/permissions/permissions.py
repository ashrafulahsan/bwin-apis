"""Permission codes governing the permissions module itself."""

from enum import StrEnum


class PermissionPermission(StrEnum):
    VIEW = "permission.view"
    CREATE = "permission.create"
    UPDATE = "permission.update"
    DELETE = "permission.delete"
    ASSIGN = "permission.assign"
