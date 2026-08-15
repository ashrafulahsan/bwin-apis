"""Tests for the date and time helpers."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.shared.utils.dates import (
    add_days,
    days_between,
    end_of_day,
    ensure_utc,
    is_expired,
    is_future,
    parse_iso,
    start_of_day,
    time_ago,
    to_iso,
    truncate_to_second,
    utc_now,
)

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def test_utc_now_is_timezone_aware() -> None:
    moment = utc_now()

    assert moment.tzinfo is not None
    assert moment.utcoffset() == timedelta(0)


def test_ensure_utc_treats_naive_input_as_utc() -> None:
    naive = datetime(2026, 8, 15, 12, 0, 0)

    assert ensure_utc(naive) == NOW


def test_ensure_utc_converts_other_offsets() -> None:
    in_dhaka = datetime(2026, 8, 15, 18, 0, 0, tzinfo=timezone(timedelta(hours=6)))

    assert ensure_utc(in_dhaka) == NOW


def test_start_and_end_of_day() -> None:
    assert start_of_day(NOW) == datetime(2026, 8, 15, 0, 0, 0, tzinfo=UTC)
    assert end_of_day(NOW) == datetime(2026, 8, 15, 23, 59, 59, 999999, tzinfo=UTC)


def test_day_boundaries_default_to_today() -> None:
    assert start_of_day().date() == utc_now().date()


def test_add_days_and_days_between() -> None:
    later = add_days(NOW, 10)

    assert later == datetime(2026, 8, 25, 12, 0, 0, tzinfo=UTC)
    assert days_between(NOW, later) == 10
    assert days_between(later, NOW) == -10


def test_iso_round_trip() -> None:
    assert to_iso(NOW) == "2026-08-15T12:00:00+00:00"
    assert parse_iso("2026-08-15T12:00:00+00:00") == NOW


def test_parse_iso_normalizes_a_non_utc_offset() -> None:
    assert parse_iso("2026-08-15T18:00:00+06:00") == NOW


def test_parse_iso_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="Invalid isoformat"):
        parse_iso("not-a-date")


def test_expiry_checks() -> None:
    past = NOW - timedelta(seconds=1)
    future = NOW + timedelta(seconds=1)

    assert is_expired(past, now=NOW) is True
    assert is_expired(future, now=NOW) is False
    assert is_future(future, now=NOW) is True
    assert is_future(past, now=NOW) is False


def test_expiry_is_inclusive_at_the_exact_moment() -> None:
    """A token expiring exactly now is expired, not still valid."""
    assert is_expired(NOW, now=NOW) is True


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=5), "just now"),
        (timedelta(minutes=1), "1 minute ago"),
        (timedelta(minutes=45), "45 minutes ago"),
        (timedelta(hours=1), "1 hour ago"),
        (timedelta(hours=5), "5 hours ago"),
        (timedelta(days=1), "1 day ago"),
        (timedelta(days=3), "3 days ago"),
        (timedelta(days=10), "1 week ago"),
        (timedelta(days=20), "2 weeks ago"),
        (timedelta(days=60), "2 months ago"),
        (timedelta(days=400), "1 year ago"),
        (timedelta(days=800), "2 years ago"),
    ],
)
def test_time_ago_for_past_moments(delta: timedelta, expected: str) -> None:
    assert time_ago(NOW - delta, now=NOW) == expected


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(hours=2), "in 2 hours"),
        (timedelta(days=2), "in 2 days"),
    ],
)
def test_time_ago_for_future_moments(delta: timedelta, expected: str) -> None:
    assert time_ago(NOW + delta, now=NOW) == expected


def test_truncate_to_second_drops_microseconds() -> None:
    """JWT `iat` is whole seconds; comparing against more precision misleads."""
    moment = datetime(2026, 8, 15, 12, 30, 45, 987654, tzinfo=UTC)

    truncated = truncate_to_second(moment)

    assert truncated == datetime(2026, 8, 15, 12, 30, 45, tzinfo=UTC)
    assert truncated <= moment


def test_truncating_keeps_the_timezone() -> None:
    moment = datetime(2026, 8, 15, 12, 30, 45, 1, tzinfo=UTC)

    assert truncate_to_second(moment).tzinfo is UTC
