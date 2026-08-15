"""Permissions for the roles module.

Declared now so routers can reference stable names; enforcement arrives with
the authentication and permissions work.
"""

from enum import StrEnum


class RolePermission(StrEnum):
    READ = "role:read"
    CREATE = "role:create"
    UPDATE = "role:update"
    DELETE = "role:delete"
    ASSIGN = "role:assign"
