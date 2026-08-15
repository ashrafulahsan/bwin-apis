"""Permission codes governing the roles module.

Codes follow the platform format `resource.action`, matching the seeded
permissions in `app.modules.permissions.constants`.
"""

from enum import StrEnum


class RolePermission(StrEnum):
    VIEW = "role.view"
    CREATE = "role.create"
    UPDATE = "role.update"
    DELETE = "role.delete"
    ASSIGN = "role.assign"
