"""Shared image-upload functionality.

`storage/` is the pluggable local-disk-or-S3 backend
(`app.modules.media.storage.get_storage_backend`); `services/` is the
validate-and-store logic every caller goes through
(`app.modules.media.services.ImageUploadService`). Other modules consume
this rather than talking to a storage backend directly - see
`app.modules.users.services.user.UserService.set_avatar` for the first one.
"""
