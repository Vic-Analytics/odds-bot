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

def test_the_window_is_7_am_to_5_pm_central():
    # It used to end at 2 PM. On Nov 12-13 2026 GitHub started almost no scheduled runs (one digest run came at
    # 3:28 PM, the next day's none at all), so a late brief now beats no brief.
    assert (SEND_FROM_HOUR, SEND_UNTIL_HOUR) == (7, 17)


def test_summer_window_edges():
    # In July Central is UTC-5, so 7:00 CDT is 12:00 UTC.
    assert go(utc(2026, 7, 15, 11, 59)) is False    # 6:59 AM
    assert go(utc(2026, 7, 15, 12, 0)) is True      # 7:00 AM
    assert go(utc(2026, 7, 15, 21, 59)) is True     # 4:59 PM
    assert go(utc(2026, 7, 15, 22, 0)) is False     # 5:00 PM


def test_winter_window_edges():
    # In January Central is UTC-6, so 7:00 CST is 13:00 UTC.
    assert go(utc(2026, 1, 15, 12, 59)) is False    # 6:59 AM
    assert go(utc(2026, 1, 15, 13, 0)) is True      # 7:00 AM
    assert go(utc(2026, 1, 15, 22, 59)) is True     # 4:59 PM
    assert go(utc(2026, 1, 15, 23, 0)) is False     # 5:00 PM


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

def scheduled_slots():
    """(minute, UTC hours) the workflow's cron fires at, read from the real file."""
    match = re.search(r'cron:\s*"(\d+) (\d+)-(\d+) \* \* \*"', WORKFLOW.read_text(encoding="utf-8"))
    assert match, "daily-odds.yml no longer has an hourly cron like '15 12-19 * * *'"
    minute, first, last = (int(g) for g in match.groups())
    return minute, range(first, last + 1)


SEASON_DAYS = [(2026, 7, 15), (2026, 1, 15), (2026, 11, 1), (2026, 3, 8), (2026, 10, 26)]


def test_the_schedule_avoids_the_top_of_the_hour():
    # GitHub is busiest at :00 and recommends other minutes; we use :15.
    minute, _ = scheduled_slots()
    assert minute == 15


@pytest.mark.parametrize("year, month, day", SEASON_DAYS)
def test_on_time_runs_first_go_at_exactly_7_15_central(year, month, day):
    minute, hours = scheduled_slots()
    goes = [h for h in hours if go(utc(year, month, day, h, minute))]
    first = utc(year, month, day, goes[0], minute).astimezone(gate.CENTRAL)
    assert (first.hour, first.minute) == (7, 15)
    assert len(goes) >= 5                       # several chances inside the window


@pytest.mark.parametrize("year, month, day", SEASON_DAYS)
def test_even_if_github_starts_every_run_up_to_6_hours_late_some_run_is_in_the_window(year, month, day):
    minute, hours = scheduled_slots()
    for delay_minutes in range(0, 361, 5):
        starts = [utc(year, month, day, h, minute) + timedelta(minutes=delay_minutes) for h in hours]
        assert any(go(when) for when in starts), f"no run inside the window with a {delay_minutes}-minute delay"


def test_the_nov_12_digest_run_that_came_2_hours_13_minutes_late_would_now_send():
    # The 19:15 UTC slot on Nov 12 was started at 21:28 UTC (3:28 PM Central). The old window ended at 2 PM, so the gate
    # turned it away; today's brief was then lost altogether when GitHub started no run at all.
    assert go(utc(2026, 11, 12, 21, 28)) is True
    assert go(utc(2026, 11, 12, 22, 59)) is True                         # 4:59 PM CST
    assert go(utc(2026, 11, 12, 23, 0)) is False                         # 5:00 PM CST: past the window


@pytest.mark.parametrize("year, month, day", SEASON_DAYS)
def test_the_cron_covers_the_whole_window_in_both_seasons(year, month, day):
    minute, hours = scheduled_slots()
    covered = {h for h in range(24) if h in hours}
    for hour in range(24):                                              # every hour of the day, at :15
        if go(utc(year, month, day, hour, minute)):
            assert hour in covered, f"{hour}:{minute:02d} UTC is inside the window but has no cron slot"


def test_no_cron_slot_is_wasted_after_the_window_closes_in_every_season():
    minute, hours = scheduled_slots()
    # The last slot must be useful in at least one season (in the other it may fall just after the window).
    assert any(go(utc(y, m, d, max(hours), minute)) for y, m, d in SEASON_DAYS)
    assert not any(go(utc(y, m, d, max(hours) + 1, minute)) for y, m, d in SEASON_DAYS)      # one more would never be used
