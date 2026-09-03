"""Constants for the media module."""

#: Key prefix user profile pictures are stored under, regardless of backend -
#: named after the owning entity rather than the file type, matching
#: ATTACHMENT_SUBDIRECTORY ("support_tickets") in app.modules.support.
AVATAR_SUBDIRECTORY = "users"

#: Where `app/main.py` mounts the local storage directory for HTTP access.
#: `LocalStorageBackend` uses this same constant to build the URLs it
#: returns, so the two can never drift apart.
MEDIA_MOUNT_PATH = "/media"
