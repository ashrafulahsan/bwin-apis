"""Authorization for the categories module.

The platform's permission codes for categories already exist and are granted
to content managers and editors. This module is nevertheless restricted to
**Super Admin and Admin**, as specified: a taxonomy is structural rather than
editorial, and reshaping one moves every piece of content filed under it.

That is why the guards here name roles rather than permissions. It is the
exception the `require_role` docstring describes - a check that really is
about who someone is. When the CMS and LMS modules need content editors to
read categories in order to tag their work, the read endpoints can move to
`require_permission(CategoryPermission.VIEW)`, which those roles already hold.
"""

from enum import StrEnum

from fastapi import Depends

from app.modules.auth.dependencies import require_role
from app.modules.roles.constants import SystemRole


class CategoryPermission(StrEnum):
    """Codes seeded by the permissions migration, kept here for reference."""

    VIEW = "category.view"
    CREATE = "category.create"
    UPDATE = "category.update"
    DELETE = "category.delete"


#: The two roles allowed to manage taxonomies.
CATEGORY_MANAGER_ROLES = (SystemRole.SUPER_ADMIN, SystemRole.ADMIN)


def category_admin() -> Depends:  # type: ignore[valid-type]
    """Dependency admitting only Super Admin and Admin."""
    return Depends(require_role(*CATEGORY_MANAGER_ROLES))
