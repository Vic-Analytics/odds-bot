"""Tests for the send-window gate that decides whether a scheduled run sends."""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import gate
from config import SEND_FROM_HOUR, SEND_UNTIL_HOUR

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "daily-odds.yml"


def utc(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def go(when, event="schedule"):
    return gate.decide(event, now=when)[0]


# ---------- the window itself ----------

def test_the_window_is_8_am_to_2_pm_central():
    assert (SEND_FROM_HOUR, SEND_UNTIL_HOUR) == (8, 14)


def test_summer_window_edges():
    # In July Central is UTC-5, so 8:00 CDT is 13:00 UTC.
    assert go(utc(2026, 7, 15, 12, 59)) is False    # 7:59 AM
    assert go(utc(2026, 7, 15, 13, 0)) is True      # 8:00 AM
    assert go(utc(2026, 7, 15, 18, 59)) is True     # 1:59 PM
    assert go(utc(2026, 7, 15, 19, 0)) is False     # 2:00 PM


def test_winter_window_edges():
    # In January Central is UTC-6, so 8:00 CST is 14:00 UTC.
    assert go(utc(2026, 1, 15, 13, 59)) is False    # 7:59 AM
    assert go(utc(2026, 1, 15, 14, 0)) is True      # 8:00 AM
    assert go(utc(2026, 1, 15, 19, 59)) is True     # 1:59 PM
    assert go(utc(2026, 1, 15, 20, 0)) is False     # 2:00 PM


def test_a_manual_run_always_goes_at_any_hour():
    assert go(utc(2026, 7, 15, 3, 0), event="workflow_dispatch") is True
    assert go(utc(2026, 7, 15, 23, 0), event="workflow_dispatch") is True


def test_it_reports_todays_date_in_central_time():
    # 03:00 UTC on Jul 16 is still the evening of Jul 15 in Chicago.
    _, today, _ = gate.decide("schedule", now=utc(2026, 7, 16, 3, 0))
    assert today == "2026-07-15"


def test_the_oct_26_incident_would_now_send():
    # GitHub started the runs at 15:06 UTC (10:06 AM Central). The old
    # "exactly 8 AM" rule skipped them and no digest was sent that day.
    assert go(utc(2026, 10, 26, 15, 6)) is True
    assert go(utc(2026, 10, 26, 15, 24)) is True


# ---------- the schedule in the workflow file ----------

def scheduled_utc_hours():
    """The UTC hours the workflow's cron fires at, read from the real file."""
    match = re.search(r'cron:\s*"0 (\d+)-(\d+) \* \* \*"', WORKFLOW.read_text(encoding="utf-8"))
    assert match, "daily-odds.yml no longer has an hourly cron like '0 13-20 * * *'"
    return range(int(match.group(1)), int(match.group(2)) + 1)


SEASON_DAYS = [(2026, 7, 15), (2026, 1, 15), (2026, 11, 1), (2026, 3, 8), (2026, 10, 26)]


@pytest.mark.parametrize("year, month, day", SEASON_DAYS)
def test_on_time_runs_first_go_at_exactly_8_central(year, month, day):
    hours = scheduled_utc_hours()
    goes = [h for h in hours if go(utc(year, month, day, h))]
    first = utc(year, month, day, goes[0]).astimezone(gate.CENTRAL)
    assert first.hour == SEND_FROM_HOUR and first.minute == 0
    assert len(goes) >= 5                       # several chances inside the window


@pytest.mark.parametrize("year, month, day", SEASON_DAYS)
def test_even_if_github_starts_every_run_up_to_4_hours_late_some_run_is_in_the_window(year, month, day):
    hours = scheduled_utc_hours()
    for delay_minutes in range(0, 241, 5):
        starts = [utc(year, month, day, h) + timedelta(minutes=delay_minutes) for h in hours]
        assert any(go(when) for when in starts), f"no run inside the window with a {delay_minutes}-minute delay"
