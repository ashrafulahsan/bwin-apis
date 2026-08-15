"""Permission codes governing the translations module.

Codes follow the platform format `resource.action`, matching the seeded
permissions in `app.modules.permissions.constants`.
"""

from enum import StrEnum


class TranslationPermission(StrEnum):
    VIEW = "translation.view"
    CREATE = "translation.create"
    UPDATE = "translation.update"
    DELETE = "translation.delete"
    IMPORT = "translation.import"
