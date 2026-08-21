"""Authorization for the courses module."""

from enum import StrEnum

from fastapi import Depends

from app.modules.auth.dependencies import require_permission


class CoursePermission(StrEnum):
    VIEW = "course.view"
    CREATE = "course.create"
    UPDATE = "course.update"
    DELETE = "course.delete"
    PUBLISH = "course.publish"


def can_view() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(CoursePermission.VIEW))


def can_create() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(CoursePermission.CREATE))


def can_update() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(CoursePermission.UPDATE))


def can_delete() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(CoursePermission.DELETE))


def can_publish() -> Depends:  # type: ignore[valid-type]
    return Depends(require_permission(CoursePermission.PUBLISH))
