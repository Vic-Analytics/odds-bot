"""Tests for the recap window and the "recap day" (10 AM to 10 AM Central)."""

import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import recap_gate

ROOT = Path(__file__).parent.parent
UTC = timezone.utc


def at(text):
    """A UTC moment from '2026-11-09T06:30' (the winter offset from UTC to Central is -6)."""
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.mark.parametrize("utc_time, day", [
    ("2026-11-09T00:00", date(2026, 11, 8)),     # 6:00 PM CST on Nov 8: the evening of Nov 8
    ("2026-11-09T06:30", date(2026, 11, 8)),     # 12:30 AM on Nov 9: still Nov 8's games
    ("2026-11-09T15:59", date(2026, 11, 8)),     # 9:59 AM on Nov 9: still Nov 8's games
    ("2026-11-09T16:00", date(2026, 11, 9)),     # 10:00 AM on Nov 9: a new recap day starts
    ("2026-11-09T20:00", date(2026, 11, 9)),     # 2:00 PM: today's games have not started
])
def test_recap_day_runs_from_10_am_to_10_am_central(utc_time, day):
    assert recap_gate.recap_day(at(utc_time)) == day


def test_recap_day_is_right_in_summer_and_on_the_days_the_clocks_change():
    assert recap_gate.recap_day(at("2026-10-29T05:30")) == date(2026, 10, 28)    # 12:30 AM CDT on Oct 29
    assert recap_gate.recap_day(at("2026-11-02T05:30")) == date(2026, 11, 1)     # 11:30 PM CST on Nov 1 (a 25-hour day)
    assert recap_gate.recap_day(at("2026-03-09T04:30")) == date(2026, 3, 8)      # 11:30 PM CDT on Mar 8 (a 23-hour day)
    assert recap_gate.recap_day(at("2026-03-09T15:00")) == date(2026, 3, 9)      # 10:00 AM CDT on Mar 9


@pytest.mark.parametrize("utc_time, inside", [
    ("2026-11-08T23:59", False),     # 5:59 PM CST
    ("2026-11-09T00:00", True),      # 6:00 PM
    ("2026-11-09T09:00", True),      # 3:00 AM
    ("2026-11-09T15:59", True),      # 9:59 AM
    ("2026-11-09T16:00", False),     # 10:00 AM
    ("2026-11-09T19:00", False),     # 1:00 PM
])
def test_the_window_is_6_pm_to_10_am_central(utc_time, inside):
    assert recap_gate.in_window(at(utc_time)) is inside


def test_the_window_follows_daylight_saving():
    assert recap_gate.in_window(at("2026-10-28T23:00")) is True      # 6:00 PM CDT
    assert recap_gate.in_window(at("2026-10-28T22:59")) is False     # 5:59 PM CDT


def test_scheduled_runs_go_only_inside_the_window():
    go, day, reason = recap_gate.decide("schedule", now=at("2026-11-09T02:00"))
    assert (go, day) == (True, date(2026, 11, 8)) and "inside" in reason
    go, day, reason = recap_gate.decide("schedule", now=at("2026-11-09T19:00"))
    assert (go, day) == (False, date(2026, 11, 9)) and "outside" in reason


def test_manual_runs_always_go_and_can_pick_the_day():
    assert recap_gate.decide("workflow_dispatch", now=at("2026-11-09T19:00"))[:2] == (True, date(2026, 11, 9))
    assert recap_gate.decide("workflow_dispatch", "2026-11-05", now=at("2026-11-09T19:00"))[:2] == (True, date(2026, 11, 5))


def test_a_bad_manual_date_is_rejected():
    with pytest.raises(ValueError):
        recap_gate.decide("workflow_dispatch", "next tuesday")


def run_script(*args, tmp_path):
    output = tmp_path / "out.txt"
    result = subprocess.run([sys.executable, str(ROOT / "recap_gate.py"), *args], capture_output=True, text=True,
                            cwd=ROOT, env=dict(os.environ, GITHUB_OUTPUT=str(output)))
    return result, (output.read_text(encoding="utf-8") if output.exists() else "")


def test_the_script_writes_the_workflow_outputs(tmp_path):
    result, written = run_script("workflow_dispatch", "2026-11-08", tmp_path=tmp_path)
    assert result.returncode == 0
    assert written.splitlines() == ["go=true", "day=2026-11-08"]


def test_the_script_rejects_a_bad_date_with_a_readable_message(tmp_path):
    result, written = run_script("workflow_dispatch", "11/08/2026", tmp_path=tmp_path)
    assert result.returncode != 0 and "2026-11-08" in result.stderr and written == ""
