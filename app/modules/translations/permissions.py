"""Permissions for the translations module.

Declared now so routers can reference stable names; enforcement arrives with
the roles and permissions module.
"""

from enum import StrEnum


class TranslationPermission(StrEnum):
    READ = "translation:read"
    CREATE = "translation:create"
    UPDATE = "translation:update"
    DELETE = "translation:delete"
    IMPORT = "translation:import"
