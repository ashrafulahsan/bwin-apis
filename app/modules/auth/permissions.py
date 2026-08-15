"""Permission codes governing the authentication module.

There are none, deliberately. Every endpoint here acts on the caller's own
account: you sign yourself in, list your own sessions, and sign yourself out.
Holding a valid access token is the whole authorization check, so a permission
code would only be a second name for the same thing.

Administrative session management - ending someone else's sessions after a
support call - belongs to the users module, under `user.update`.
"""

from app.modules.auth.dependencies import require_permission, require_role

__all__ = ["require_permission", "require_role"]
