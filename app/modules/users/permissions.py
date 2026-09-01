"""Authorization for the users module.

User management is restricted to **Super Admin and Admin**: creating,
editing or removing an account is an administrative act, not something any
permission holder should be granted piecemeal. That is why the guard here
names roles rather than a `user.*` permission - the exception the
`require_role` docstring describes, for a check that really is about who
someone is.
"""

from enum import StrEnum

from fastapi import Depends

from app.modules.auth.dependencies import require_role
from app.modules.roles.constants import SystemRole


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
