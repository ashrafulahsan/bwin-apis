"""Constants for the roles module."""

from enum import StrEnum
from typing import TypedDict

ROLE_NAME_MAX_LENGTH = 100
ROLE_SLUG_MAX_LENGTH = 100

#: Highest and lowest assignable privilege levels.
MIN_ROLE_LEVEL = 0
MAX_ROLE_LEVEL = 100


class SystemRole(StrEnum):
    """Slugs of the roles seeded with the platform.

    Code refers to roles by these slugs rather than by display name, so an
    administrator renaming "Instructor" to "Teacher" does not break
    authorization.
    """

    SUPER_ADMIN = "super-admin"
    ADMIN = "admin"
    CONTENT_MANAGER = "content-manager"
    EDITOR = "editor"
    INSTRUCTOR = "instructor"
    SUPPORT = "support"
    STUDENT = "student"


class SystemRoleDefinition(TypedDict):
    slug: str
    name: str
    description: str
    level: int


#: Seeded by migration, so every environment starts with the same roles.
#:
#: `level` orders privilege for comparisons such as "may this user edit that
#: one". Higher wins; gaps are deliberate, leaving room for custom roles to
#: slot between the built-in ones.
SYSTEM_ROLES: list[SystemRoleDefinition] = [
    {
        "slug": SystemRole.SUPER_ADMIN,
        "name": "Super Admin",
        "description": "Unrestricted access to every part of the platform.",
        "level": 100,
    },
    {
        "slug": SystemRole.ADMIN,
        "name": "Admin",
        "description": "Manages users, roles and platform settings.",
        "level": 90,
    },
    {
        "slug": SystemRole.CONTENT_MANAGER,
        "name": "Content Manager",
        "description": "Owns the content library and publishes CMS pages.",
        "level": 70,
    },
    {
        "slug": SystemRole.EDITOR,
        "name": "Editor",
        "description": "Writes and edits content, but cannot publish it.",
        "level": 60,
    },
    {
        "slug": SystemRole.INSTRUCTOR,
        "name": "Instructor",
        "description": "Creates and teaches courses, and grades learners.",
        "level": 50,
    },
    {
        "slug": SystemRole.SUPPORT,
        "name": "Support",
        "description": "Assists learners and handles support requests.",
        "level": 40,
    },
    {
        "slug": SystemRole.STUDENT,
        "name": "Student",
        "description": "Enrols in courses and tracks personal progress.",
        "level": 10,
    },
]
