"""Authorization for the users module.

User management is restricted to **Super Admin and Admin**: creating,
editing or removing an account is an administrative act, not something any
permission holder should be granted piecemeal. That is why the guard here
names roles rather than a `user.*` permission - the exception the
`require_role` docstring describes, for a check that really is about who
someone is.
"""

import uuid
from enum import StrEnum

from fastapi import Depends

from app.core.exceptions import ForbiddenException
from app.modules.auth.dependencies import CurrentUser, require_role
from app.modules.roles.constants import SystemRole
from app.modules.users.models.user import User


class UserPermission(StrEnum):
    VIEW = "user.view"
    CREATE = "user.create"
    UPDATE = "user.update"
    DELETE = "user.delete"


#: The two roles allowed to manage user accounts.
USER_MANAGER_ROLES = (SystemRole.SUPER_ADMIN, SystemRole.ADMIN)


def user_admin() -> Depends:  # type: ignore[valid-type]
    """Dependency admitting only Super Admin and Admin."""
    return Depends(require_role(*USER_MANAGER_ROLES))


def self_or_admin() -> Depends:  # type: ignore[valid-type]
    """Dependency admitting the account holder themself, or Super Admin/Admin.

    For the avatar endpoints: every signed-in user manages their own profile
    picture (mirroring `PATCH /auth/me`, which is open to every role), while
    Super Admin/Admin retain the ability to manage anyone's, same as the rest
    of this router.
    """

    async def guard(user: CurrentUser, user_id: uuid.UUID) -> User:
        if user.id == user_id or user.role_slugs & set(USER_MANAGER_ROLES):
            return user

        raise ForbiddenException(
            "You can only manage your own avatar unless you are a Super Admin or Admin."
        )

    return Depends(guard)
