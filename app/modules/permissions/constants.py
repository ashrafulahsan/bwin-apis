"""Constants for the permissions module.

Permission codes are `resource.action`: `user.view`, `course.create`. The
resource and action are stored as separate columns too, so an admin screen can
render the familiar grid of resources down the side and actions across the top.
"""

import re
from enum import StrEnum

PERMISSION_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")

PERMISSION_CODE_MAX_LENGTH = 100
PERMISSION_NAME_MAX_LENGTH = 150
PERMISSION_PART_MAX_LENGTH = 50

CODE_SEPARATOR = "."


class PermissionAction(StrEnum):
    """Verbs a permission can grant."""

    VIEW = "view"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    PUBLISH = "publish"
    ASSIGN = "assign"
    UPLOAD = "upload"
    IMPORT = "import"
    EXPORT = "export"
    GRADE = "grade"
    SEND = "send"


class PermissionResource(StrEnum):
    """Things a permission can apply to."""

    USER = "user"
    ROLE = "role"
    PERMISSION = "permission"
    COURSE = "course"
    CONSULTANCY = "consultancy"
    AUTOMATION = "automation"
    LESSON = "lesson"
    ENROLLMENT = "enrollment"
    PAGE = "page"
    BLOG = "blog"
    MEDIA = "media"
    CATEGORY = "category"
    MENU = "menu"
    MASTER_CRUD = "master_crud"
    MASTER_CRUD_FIELD = "master_crud_field"
    TRANSLATION = "translation"
    SETTING = "setting"
    REPORT = "report"
    NOTIFICATION = "notification"
    ACTIVITY_LOG = "activity_log"


ACTION_LABELS: dict[str, str] = {
    PermissionAction.VIEW: "View",
    PermissionAction.CREATE: "Create",
    PermissionAction.UPDATE: "Update",
    PermissionAction.DELETE: "Delete",
    PermissionAction.PUBLISH: "Publish",
    PermissionAction.ASSIGN: "Assign",
    PermissionAction.UPLOAD: "Upload",
    PermissionAction.IMPORT: "Import",
    PermissionAction.EXPORT: "Export",
    PermissionAction.GRADE: "Grade",
    PermissionAction.SEND: "Send",
}

RESOURCE_LABELS: dict[str, str] = {
    PermissionResource.USER: "users",
    PermissionResource.ROLE: "roles",
    PermissionResource.PERMISSION: "permissions",
    PermissionResource.COURSE: "courses",
    PermissionResource.CONSULTANCY: "consultancies",
    PermissionResource.AUTOMATION: "automations",
    PermissionResource.LESSON: "lessons",
    PermissionResource.ENROLLMENT: "enrolments",
    PermissionResource.PAGE: "pages",
    PermissionResource.BLOG: "blog posts",
    PermissionResource.MEDIA: "media",
    PermissionResource.CATEGORY: "categories",
    PermissionResource.MENU: "menu items",
    PermissionResource.MASTER_CRUD: "master CRUD records",
    PermissionResource.MASTER_CRUD_FIELD: "master CRUD fields",
    PermissionResource.TRANSLATION: "translations",
    PermissionResource.SETTING: "settings",
    PermissionResource.REPORT: "reports",
    PermissionResource.NOTIFICATION: "notifications",
    PermissionResource.ACTIVITY_LOG: "the activity log",
}

#: Which actions exist for each resource. Seeded by migration.
SYSTEM_PERMISSIONS: dict[str, list[str]] = {
    PermissionResource.USER: ["view", "create", "update", "delete"],
    PermissionResource.ROLE: ["view", "create", "update", "delete", "assign"],
    PermissionResource.PERMISSION: ["view", "create", "update", "delete", "assign"],
    PermissionResource.COURSE: ["view", "create", "update", "delete", "publish"],
    PermissionResource.CONSULTANCY: ["view", "create", "update", "delete"],
    PermissionResource.AUTOMATION: [
        "view",
        "create",
        "update",
        "delete",
        "publish",
    ],
    PermissionResource.LESSON: ["view", "create", "update", "delete"],
    PermissionResource.ENROLLMENT: ["view", "create", "delete", "grade"],
    PermissionResource.PAGE: ["view", "create", "update", "delete", "publish"],
    PermissionResource.BLOG: ["view", "create", "update", "delete", "publish"],
    PermissionResource.MEDIA: ["view", "upload", "delete"],
    PermissionResource.CATEGORY: ["view", "create", "update", "delete"],
    PermissionResource.MENU: ["view", "create", "update", "delete"],
    PermissionResource.MASTER_CRUD: ["view", "create", "update", "delete"],
    PermissionResource.MASTER_CRUD_FIELD: ["view", "create", "update", "delete"],
    PermissionResource.TRANSLATION: ["view", "create", "update", "delete", "import"],
    PermissionResource.SETTING: ["view", "update"],
    PermissionResource.REPORT: ["view", "export"],
    PermissionResource.NOTIFICATION: ["view", "send"],
    # No create, update or delete: the platform writes these entries and
    # nothing may edit or remove one, so the codes that would allow it are
    # never defined. A permission that does not exist cannot be granted by
    # mistake.
    PermissionResource.ACTIVITY_LOG: ["view", "export"],
}


def build_code(resource: str, action: str) -> str:
    return f"{resource}{CODE_SEPARATOR}{action}"


def split_code(code: str) -> tuple[str, str]:
    """`user.view` -> `("user", "view")`."""
    resource, _, action = code.partition(CODE_SEPARATOR)
    return resource, action


def build_label(resource: str, action: str) -> str:
    """`("user", "view")` -> `View users`."""
    verb = ACTION_LABELS.get(action, action.title())
    noun = RESOURCE_LABELS.get(resource, resource)
    return f"{verb} {noun}"


def all_permission_codes() -> list[str]:
    """Every seeded permission code, in a stable order."""
    return [
        build_code(resource, action)
        for resource, actions in SYSTEM_PERMISSIONS.items()
        for action in actions
    ]


#: Sentinel meaning "every permission", used by Super Admin.
ALL_PERMISSIONS = "*"


def _codes_for(resource: str, *actions: str) -> list[str]:
    return [build_code(resource, action) for action in actions]


#: Default grants applied when the platform is seeded. Administrators can
#: change any of this afterwards; it is a starting point, not a constraint.
DEFAULT_ROLE_PERMISSIONS: dict[str, list[str] | str] = {
    "super-admin": ALL_PERMISSIONS,
    "admin": [
        *_codes_for("user", "view", "create", "update", "delete"),
        *_codes_for("role", "view", "create", "update", "delete", "assign"),
        *_codes_for("permission", "view", "assign"),
        *_codes_for("course", "view", "create", "update", "delete", "publish"),
        *_codes_for("consultancy", "view", "create", "update", "delete"),
        *_codes_for("automation", "view", "create", "update", "delete", "publish"),
        *_codes_for("lesson", "view", "create", "update", "delete"),
        *_codes_for("enrollment", "view", "create", "delete", "grade"),
        *_codes_for("page", "view", "create", "update", "delete", "publish"),
        *_codes_for("blog", "view", "create", "update", "delete", "publish"),
        *_codes_for("media", "view", "upload", "delete"),
        *_codes_for("category", "view", "create", "update", "delete"),
        *_codes_for("menu", "view", "create", "update", "delete"),
        *_codes_for("master_crud", "view", "create", "update", "delete"),
        *_codes_for("master_crud_field", "view", "create", "update", "delete"),
        *_codes_for("translation", "view", "create", "update", "delete", "import"),
        *_codes_for("setting", "view", "update"),
        *_codes_for("report", "view", "export"),
        *_codes_for("notification", "view", "send"),
        *_codes_for("activity_log", "view", "export"),
    ],
    "content-manager": [
        *_codes_for("page", "view", "create", "update", "delete", "publish"),
        *_codes_for("automation", "view", "create", "update", "delete", "publish"),
        *_codes_for("blog", "view", "create", "update", "delete", "publish"),
        *_codes_for("media", "view", "upload", "delete"),
        *_codes_for("category", "view", "create", "update", "delete"),
        *_codes_for("menu", "view", "create", "update", "delete"),
        *_codes_for("master_crud", "view", "create", "update", "delete"),
        # Fills the form in and reads its definition, but designing it
        # changes what every stored answer means - that stays with admins.
        *_codes_for("master_crud_field", "view"),
        *_codes_for("translation", "view", "update"),
        *_codes_for("course", "view"),
        *_codes_for("consultancy", "view"),
        *_codes_for("report", "view"),
        # Reads the trail but cannot take a copy of it out of the system.
        *_codes_for("activity_log", "view"),
    ],
    # Editors write but never publish - that is the point of the role.
    "editor": [
        *_codes_for("page", "view", "create", "update"),
        *_codes_for("automation", "view", "create", "update"),
        # Writes and revises posts but does not decide what goes live: that
        # separation is the whole point of the role, so `blog.publish` is
        # withheld exactly as `page` publishing is.
        *_codes_for("blog", "view", "create", "update"),
        *_codes_for("media", "view", "upload"),
        *_codes_for("category", "view"),
        *_codes_for("menu", "view"),
        *_codes_for("master_crud", "view", "create", "update"),
        *_codes_for("master_crud_field", "view"),
        *_codes_for("translation", "view"),
        *_codes_for("course", "view"),
        *_codes_for("consultancy", "view"),
    ],
    "instructor": [
        *_codes_for("course", "view", "create", "update"),
        *_codes_for("consultancy", "view", "create", "update"),
        *_codes_for("automation", "view"),
        *_codes_for("lesson", "view", "create", "update", "delete"),
        *_codes_for("enrollment", "view", "grade"),
        *_codes_for("media", "view", "upload"),
        *_codes_for("report", "view"),
    ],
    "support": [
        *_codes_for("user", "view"),
        *_codes_for("course", "view"),
        *_codes_for("consultancy", "view"),
        *_codes_for("automation", "view"),
        *_codes_for("enrollment", "view"),
        *_codes_for("page", "view"),
        *_codes_for("blog", "view"),
        *_codes_for("menu", "view"),
        *_codes_for("master_crud", "view"),
        *_codes_for("notification", "view", "send"),
        *_codes_for("report", "view"),
    ],
    "student": [
        *_codes_for("course", "view"),
        *_codes_for("consultancy", "view"),
        *_codes_for("automation", "view"),
        *_codes_for("lesson", "view"),
        *_codes_for("enrollment", "view"),
        *_codes_for("page", "view"),
        *_codes_for("blog", "view"),
        *_codes_for("menu", "view"),
        *_codes_for("master_crud", "view"),
    ],
}
