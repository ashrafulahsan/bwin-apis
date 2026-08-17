"""The demo accounts.

One per role, so no role is left without someone to test with, plus a few
that exercise states the single-role accounts do not: several roles at once,
social-only sign-in, and the pending and suspended lifecycle states.

Addresses use `bwin.example.com` - `example.com` is reserved by RFC 2606, so
nothing here can ever be delivered to.
"""

from typing import TypedDict

from app.core.constants import Language
from app.modules.users.constants import AuthProvider, UserStatus


class DemoUser(TypedDict, total=False):
    email: str
    phone: str
    first_name: str
    last_name: str
    roles: list[str]
    status: UserStatus
    language: Language
    verified: bool
    with_password: bool
    social: tuple[AuthProvider, str]


#: One account per role, plus a few that exercise states the single-role
#: accounts do not: several roles at once, social-only sign-in, and the
#: pending and suspended lifecycle states.
DEMO_USERS: list[DemoUser] = [
    {
        "email": "superadmin@bwin.example.com",
        "phone": "+8801700000001",
        "first_name": "Nusrat",
        "last_name": "Jahan",
        "roles": ["super-admin"],
        "status": UserStatus.ACTIVE,
        "verified": True,
    },
    {
        "email": "admin@bwin.example.com",
        "phone": "+8801700000002",
        "first_name": "Rafiqul",
        "last_name": "Islam",
        "roles": ["admin"],
        "status": UserStatus.ACTIVE,
        "verified": True,
    },
    {
        "email": "content@bwin.example.com",
        "phone": "+8801700000003",
        "first_name": "Sadia",
        "last_name": "Rahman",
        "roles": ["content-manager"],
        "status": UserStatus.ACTIVE,
        "verified": True,
        "language": Language.BN,
    },
    {
        "email": "editor@bwin.example.com",
        "phone": "+8801700000004",
        "first_name": "Tanvir",
        "last_name": "Hasan",
        "roles": ["editor"],
        "status": UserStatus.ACTIVE,
        "verified": True,
    },
    {
        "email": "instructor@bwin.example.com",
        "phone": "+8801700000005",
        "first_name": "Mahmuda",
        "last_name": "Akter",
        "roles": ["instructor"],
        "status": UserStatus.ACTIVE,
        "verified": True,
    },
    {
        "email": "support@bwin.example.com",
        "phone": "+8801700000006",
        "first_name": "Imran",
        "last_name": "Kabir",
        "roles": ["support"],
        "status": UserStatus.ACTIVE,
        "verified": True,
        "language": Language.BN,
    },
    {
        "email": "student@bwin.example.com",
        "phone": "+8801700000007",
        "first_name": "Arif",
        "last_name": "Chowdhury",
        "roles": ["student"],
        "status": UserStatus.ACTIVE,
        "verified": True,
    },
    # Two roles at once - the case a single `role_id` column could not model.
    {
        "email": "lead.instructor@bwin.example.com",
        "phone": "+8801700000008",
        "first_name": "Farhana",
        "last_name": "Siddique",
        "roles": ["instructor", "content-manager"],
        "status": UserStatus.ACTIVE,
        "verified": True,
    },
    # Signed up through Google, so no password and no phone.
    {
        "email": "google.user@bwin.example.com",
        "first_name": "Shahriar",
        "last_name": "Alam",
        "roles": ["student"],
        "status": UserStatus.ACTIVE,
        "verified": True,
        "with_password": False,
        "social": (AuthProvider.GOOGLE, "google-demo-1001"),
    },
    # Registered but not yet verified.
    {
        "email": "pending@bwin.example.com",
        "phone": "+8801700000010",
        "first_name": "Rumana",
        "last_name": "Parvin",
        "roles": ["student"],
        "status": UserStatus.PENDING,
        "verified": False,
    },
    # Blocked by an administrator.
    {
        "email": "suspended@bwin.example.com",
        "phone": "+8801700000011",
        "first_name": "Jamal",
        "last_name": "Uddin",
        "roles": ["student"],
        "status": UserStatus.SUSPENDED,
        "verified": True,
    },
]
