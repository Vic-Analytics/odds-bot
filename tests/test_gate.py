"""Tests for the send-window gate that decides whether a scheduled run sends."""

import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import gate
from config import EARLY_START_MINUTES, SEND_FROM_HOUR, SEND_UNTIL_HOUR

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


def test_the_early_start_is_330_minutes_so_a_run_from_1_30_am_can_wait_for_7_am():
    assert EARLY_START_MINUTES == 330 and SEND_FROM_HOUR * 60 - EARLY_START_MINUTES == 90      # 1:30 AM


def test_summer_window_edges():
    # In July Central is UTC-5, so 7:00 CDT is 12:00 UTC. Runs from 1:30 AM wait for the window; earlier ones stop.
    assert go(utc(2026, 7, 15, 6, 29)) is False     # 1:29 AM: too early to wait for
    assert go(utc(2026, 7, 15, 6, 30)) is True      # 1:30 AM: waits 5.5 hours
    assert go(utc(2026, 7, 15, 11, 59)) is True     # 6:59 AM: waits 1 minute
    assert go(utc(2026, 7, 15, 12, 0)) is True      # 7:00 AM
    assert go(utc(2026, 7, 15, 21, 59)) is True     # 4:59 PM
    assert go(utc(2026, 7, 15, 22, 0)) is False     # 5:00 PM


def test_winter_window_edges():
    # In January Central is UTC-6, so 7:00 CST is 13:00 UTC.
    assert go(utc(2026, 1, 15, 7, 29)) is False     # 1:29 AM: too early to wait for
    assert go(utc(2026, 1, 15, 7, 30)) is True      # 1:30 AM: waits 5.5 hours
    assert go(utc(2026, 1, 15, 12, 59)) is True     # 6:59 AM: waits 1 minute
    assert go(utc(2026, 1, 15, 13, 0)) is True      # 7:00 AM
    assert go(utc(2026, 1, 15, 22, 59)) is True     # 4:59 PM
    assert go(utc(2026, 1, 15, 23, 0)) is False     # 5:00 PM


# ---------- early start: a run that starts before 7 AM waits for the window ----------

def test_how_long_an_early_run_waits_is_the_real_time_until_7_am_central():
    assert gate.seconds_until_open(utc(2026, 1, 15, 7, 30)) == 330 * 60          # 1:30 AM CST
    assert gate.seconds_until_open(utc(2026, 1, 15, 10, 57)) == 123 * 60         # 4:57 AM CST, a real recap-run time
    assert gate.seconds_until_open(utc(2026, 1, 15, 12, 59)) == 60               # 6:59 AM
    assert gate.seconds_until_open(utc(2026, 1, 15, 13, 0)) == 0                 # the window is open
    assert gate.seconds_until_open(utc(2026, 1, 15, 18, 6)) == 0                 # noon: nothing to wait for
    assert gate.seconds_until_open(utc(2026, 7, 15, 9, 0)) == 3 * 3600           # 4:00 AM CDT


def test_the_wait_is_right_on_the_days_daylight_saving_starts_and_ends():
    # Mar 8 2026: clocks jump from 2:00 to 3:00 AM, so 1:45 AM CST is really 4 h 15 min before 7:00 AM CDT.
    assert gate.seconds_until_open(utc(2026, 3, 8, 7, 45)) == 4 * 3600 + 15 * 60
    # Nov 1 2026: clocks fall back from 2:00 to 1:00 AM. 2:30 AM CST (08:30 UTC) is 4.5 hours before 7:00 AM CST.
    assert gate.seconds_until_open(utc(2026, 11, 1, 8, 30)) == 4 * 3600 + 30 * 60
    # ...and the first 1:45 AM (still CDT, 06:45 UTC) is 6 h 15 min away: more than the 5.5 hours allowed.
    assert gate.seconds_until_open(utc(2026, 11, 1, 6, 45)) == 6 * 3600 + 15 * 60
    assert go(utc(2026, 11, 1, 6, 45)) is False and go(utc(2026, 11, 1, 8, 30)) is True


def test_the_reason_says_how_long_it_will_wait_or_why_it_will_not():
    go_, _, reason = gate.decide("schedule", now=utc(2026, 11, 17, 10, 57))
    assert go_ is True and "will wait 123 minutes" in reason and "then send" in reason
    go_, _, reason = gate.decide("schedule", now=utc(2026, 11, 17, 6, 20))
    assert go_ is False and "too early to wait" in reason and "330 minutes" in reason


def test_an_early_run_still_belongs_to_todays_digest_and_marker():
    _, today, _ = gate.decide("schedule", now=utc(2026, 11, 17, 10, 57))        # 4:57 AM CST on Nov 17
    assert today == "2026-11-17"


def test_runs_like_the_recaps_pre_dawn_ones_would_now_deliver_the_digest_at_7_am():
    # Real start times of the recap workflow's pre-dawn runs (UTC): Nov 14 10:05, Nov 15 09:49, Nov 16 10:57.
    for hour, minute in [(10, 5), (9, 49), (10, 57)]:
        when = utc(2026, 11, 17, hour, minute)
        assert go(when) is True and gate.seconds_until_open(when) > 0
        assert when + timedelta(seconds=gate.seconds_until_open(when)) == utc(2026, 11, 17, 13, 0)      # 7:00 AM CST exactly


def test_a_manual_run_never_waits_even_at_4_am_and_a_timer_run_at_4_am_waits_until_7():
    early = utc(2026, 11, 17, 10, 0)                                           # 4:00 AM CST
    assert gate.evaluate("workflow_dispatch", now=early)[0::3] == (True, 0)     # (go, wait)
    go_, today, reason, wait = gate.evaluate("schedule", now=early)
    assert (go_, wait, today) == (True, 3 * 3600, "2026-11-17")


def test_a_run_inside_the_window_or_turned_away_has_nothing_to_wait_for():
    assert gate.evaluate("schedule", now=utc(2026, 11, 17, 18, 6))[0::3] == (True, 0)       # noon: sends at once
    assert gate.evaluate("schedule", now=utc(2026, 11, 17, 6, 20))[0::3] == (False, 0)      # 12:20 AM: too early, stops
    assert gate.evaluate("schedule", now=utc(2026, 11, 17, 23, 30))[0::3] == (False, 0)     # 5:30 PM: too late, stops


def test_the_script_writes_wait_zero_for_a_manual_run(tmp_path):
    output = tmp_path / "out.txt"
    result = subprocess.run([sys.executable, str(Path(gate.__file__)), "workflow_dispatch"], capture_output=True, text=True,
                            cwd=Path(gate.__file__).parent, env={"GITHUB_OUTPUT": str(output), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
    assert result.returncode == 0, result.stderr
    lines = output.read_text(encoding="utf-8").splitlines()
    assert "go=true" in lines and "wait=0" in lines


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
    assert match, "daily-odds.yml no longer has an hourly cron like '15 7-22 * * *'"
    minute, first, last = (int(g) for g in match.groups())
    return minute, range(first, last + 1)


SEASON_DAYS = [(2026, 7, 15), (2026, 1, 15), (2026, 11, 1), (2026, 3, 8), (2026, 10, 26)]


def test_the_schedule_avoids_the_top_of_the_hour():
    # GitHub is busiest at :00 and recommends other minutes; we use :15.
    minute, _ = scheduled_slots()
    assert minute == 15


@pytest.mark.parametrize("year, month, day", SEASON_DAYS)
def test_on_time_runs_first_send_at_exactly_7_15_central_and_early_runs_wait_for_7_00(year, month, day):
    minute, hours = scheduled_slots()
    slots = [utc(year, month, day, h, minute) for h in hours]
    goes = [when for when in slots if go(when)]
    immediate = [when for when in goes if gate.seconds_until_open(when) == 0]
    waiting = [when for when in goes if gate.seconds_until_open(when) > 0]
    first = immediate[0].astimezone(gate.CENTRAL)
    assert (first.hour, first.minute) == (7, 15)
    assert len(immediate) >= 5                   # several chances inside the window
    assert len(waiting) >= 4                     # and the early hours have slots too (an early run waits and sends at 7:00)


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


def test_no_cron_slot_is_wasted_before_the_early_window_opens():
    minute, hours = scheduled_slots()
    assert any(go(utc(y, m, d, min(hours), minute)) for y, m, d in SEASON_DAYS)              # the first slot helps in some season
    assert not any(go(utc(y, m, d, min(hours) - 1, minute)) for y, m, d in SEASON_DAYS)      # one earlier would never be used
