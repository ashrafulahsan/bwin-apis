"""Date and time helpers.

Every datetime crossing an application boundary is timezone-aware and in UTC.
Naive values are treated as UTC rather than as local time, so behaviour does
not change with the server's timezone.
"""

from datetime import UTC, datetime, time, timedelta

_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600
_SECONDS_PER_DAY = 86400
_DAYS_PER_WEEK = 7
_DAYS_PER_MONTH = 30
_DAYS_PER_YEAR = 365


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def truncate_to_second(value: datetime) -> datetime:
    """Drop the microseconds.

    For comparing against values that only ever carry whole seconds - a JWT's
    `iat` and `exp` claims, most obviously. Comparing those against a
    microsecond-precise timestamp makes anything issued in the same second
    look older than it is.
    """
    return value.replace(microsecond=0)


def ensure_utc(value: datetime) -> datetime:
    """Return `value` in UTC, assuming naive input is already UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def start_of_day(value: datetime | None = None) -> datetime:
    """Midnight UTC at the start of `value`'s day."""
    moment = ensure_utc(value) if value else utc_now()
    return datetime.combine(moment.date(), time.min, tzinfo=UTC)


def end_of_day(value: datetime | None = None) -> datetime:
    """The last representable instant of `value`'s day, in UTC."""
    moment = ensure_utc(value) if value else utc_now()
    return datetime.combine(moment.date(), time.max, tzinfo=UTC)


def add_days(value: datetime, days: int) -> datetime:
    return ensure_utc(value) + timedelta(days=days)


def days_between(start: datetime, end: datetime) -> int:
    """Whole days from `start` to `end`; negative when `end` is earlier."""
    return (ensure_utc(end) - ensure_utc(start)).days


def to_iso(value: datetime) -> str:
    """ISO 8601 in UTC, e.g. `2026-08-15T10:24:09+00:00`."""
    return ensure_utc(value).isoformat()


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 string into an aware UTC datetime.

    Raises `ValueError` on malformed input.
    """
    return ensure_utc(datetime.fromisoformat(value))


def is_expired(expires_at: datetime, *, now: datetime | None = None) -> bool:
    """True once `expires_at` has passed. Used for tokens and scheduled content."""
    return ensure_utc(expires_at) <= (now or utc_now())


def is_future(value: datetime, *, now: datetime | None = None) -> bool:
    return ensure_utc(value) > (now or utc_now())


def time_ago(value: datetime, *, now: datetime | None = None) -> str:
    """Coarse human readable delta, e.g. `3 hours ago` or `in 2 days`."""
    reference = now or utc_now()
    delta = reference - ensure_utc(value)
    seconds = int(abs(delta.total_seconds()))
    future = delta.total_seconds() < 0

    if seconds < _SECONDS_PER_MINUTE:
        return "just now"

    phrase = _coarse_phrase(seconds)
    return f"in {phrase}" if future else f"{phrase} ago"


def _coarse_phrase(seconds: int) -> str:
    """Largest sensible unit for a positive number of seconds."""
    if seconds < _SECONDS_PER_HOUR:
        return _plural(seconds // _SECONDS_PER_MINUTE, "minute")
    if seconds < _SECONDS_PER_DAY:
        return _plural(seconds // _SECONDS_PER_HOUR, "hour")

    days = seconds // _SECONDS_PER_DAY
    if days < _DAYS_PER_WEEK:
        return _plural(days, "day")
    if days < _DAYS_PER_MONTH:
        return _plural(days // _DAYS_PER_WEEK, "week")
    if days < _DAYS_PER_YEAR:
        return _plural(days // _DAYS_PER_MONTH, "month")
    return _plural(days // _DAYS_PER_YEAR, "year")


def _plural(count: int, unit: str) -> str:
    return f"{count} {unit}" if count == 1 else f"{count} {unit}s"
