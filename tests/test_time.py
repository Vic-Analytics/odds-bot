"""Tests for Central-time conversion and the "starts today" filter."""

from datetime import datetime, timezone

from games_today import CENTRAL, filter_today, has_started, start_time_central
from helpers import game


def at(iso_utc):
    return game("H", "A", start=iso_utc)


def central(year, month, day, hour=12):
    return datetime(year, month, day, hour, tzinfo=CENTRAL)


def test_utc_converts_to_central_daylight_time():
    # 00:30 UTC on Oct 17 is 7:30 PM on Oct 16 in Chicago (CDT, UTC-5).
    t = start_time_central(at("2026-10-17T00:30:00Z"))
    assert (t.month, t.day, t.hour, t.minute) == (10, 16, 19, 30)


def test_utc_converts_to_central_standard_time_in_winter():
    # 14:00 UTC in January is 8:00 AM (CST, UTC-6).
    t = start_time_central(at("2026-01-15T14:00:00Z"))
    assert (t.day, t.hour) == (15, 8)


def test_today_window_edges_in_daylight_time():
    now = central(2026, 10, 16, 8)
    games = [
        at("2026-10-16T04:59:00Z"),  # 11:59 PM on Oct 15 -> yesterday
        at("2026-10-16T05:00:00Z"),  # midnight Oct 16 -> today
        at("2026-10-17T00:30:00Z"),  # 7:30 PM Oct 16 -> today
        at("2026-10-17T04:59:00Z"),  # 11:59 PM Oct 16 -> today
        at("2026-10-17T05:00:00Z"),  # midnight Oct 17 -> tomorrow
    ]
    kept = [g["commence_time"] for g in filter_today(games, now=now)]
    assert kept == ["2026-10-16T05:00:00Z", "2026-10-17T00:30:00Z", "2026-10-17T04:59:00Z"]


def test_today_is_sorted_earliest_first():
    now = central(2026, 10, 16)
    games = [at("2026-10-17T02:00:00Z"), at("2026-10-16T15:00:00Z"), at("2026-10-16T20:00:00Z")]
    kept = [g["commence_time"] for g in filter_today(games, now=now)]
    assert kept == sorted(kept)


def test_day_when_daylight_saving_ends_is_25_hours_long():
    # Nov 1, 2026: clocks fall back, so this Central day runs 05:00Z to 06:00Z next day.
    now = central(2026, 11, 1)
    games = [
        at("2026-11-01T04:59:00Z"),  # still Oct 31 -> not today
        at("2026-11-01T05:00:00Z"),  # midnight Nov 1 -> today
        at("2026-11-02T05:30:00Z"),  # 11:30 PM CST Nov 1 -> today (the extra hour)
        at("2026-11-02T06:00:00Z"),  # midnight Nov 2 -> not today
    ]
    kept = [g["commence_time"] for g in filter_today(games, now=now)]
    assert kept == ["2026-11-01T05:00:00Z", "2026-11-02T05:30:00Z"]


def test_day_when_daylight_saving_starts_is_23_hours_long():
    # Mar 8, 2026: clocks spring forward, so this Central day runs 06:00Z to 05:00Z next day.
    now = central(2026, 3, 8)
    games = [
        at("2026-03-08T05:59:00Z"),  # still Mar 7 -> not today
        at("2026-03-08T06:00:00Z"),  # midnight Mar 8 -> today
        at("2026-03-09T04:30:00Z"),  # 11:30 PM CDT Mar 8 -> today
        at("2026-03-09T05:00:00Z"),  # midnight Mar 9 -> not today
    ]
    kept = [g["commence_time"] for g in filter_today(games, now=now)]
    assert kept == ["2026-03-08T06:00:00Z", "2026-03-09T04:30:00Z"]


def test_has_started():
    now = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
    assert has_started(at("2026-10-17T11:30:00Z"), now=now) is True
    assert has_started(at("2026-10-17T12:00:00Z"), now=now) is True   # exactly kickoff
    assert has_started(at("2026-10-17T12:00:01Z"), now=now) is False
