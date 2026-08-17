"""Response schemas for the activity log.

Read-only throughout. There is no create or update schema here, and that is
not an omission: entries are written by `ActivityLogService` from inside the
services that made the change, and an endpoint that accepted a hand-written
audit row would make the whole trail deniable.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ActivityLogRead(BaseModel):
    """One entry, in full."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID

    user_id: uuid.UUID | None
    user_name: str | None
    role_name: str | None

    action: str
    module: str
    entity_type: str | None
    entity_id: str | None
    description: str

    old_values: dict[str, Any] | None
    new_values: dict[str, Any] | None

    ip_address: str | None
    user_agent: str | None
    request_method: str | None
    request_url: str | None

    status: str
    created_at: datetime


class ActivityLogSummary(BaseModel):
    """An entry as it appears in a listing: who, what, when.

    The request metadata and the value diffs are left out - they are what the
    detail view is for, and a page of fifty entries carrying two JSONB blobs
    each is a slow response nobody reads.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    user_name: str | None
    role_name: str | None
    action: str
    module: str
    entity_type: str | None
    entity_id: str | None
    description: str
    status: str
    ip_address: str | None
    created_at: datetime
