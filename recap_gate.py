"""
recap_gate.py - decides whether a scheduled recap run should do anything right now.

The results recap is sent when the LAST game of a day has finished. Games run from
the afternoon to after midnight Central, so the recap workflow wakes up every 20
minutes through the evening and night, and each run asks this script two questions:

  1. Is it inside the recap window? (6 PM to 10 AM Central.) Outside it, do nothing.
  2. Which day is this recap for? A "recap day" runs from 10 AM to 10 AM, so a game
     that starts at 9 PM and finishes at 12:30 AM still belongs to the day it started on.

(Whether the day's games are all finished is recap.py's job, because that needs the
scores. Whether the recap was already sent is the workflow's job, via a marker.)

Standard library only, so it starts instantly:

    python recap_gate.py schedule                  -> go=true/false, day=YYYY-MM-DD
    python recap_gate.py workflow_dispatch 2026-11-08   (a manual run: always go, for that day)

On GitHub it writes its answers to the file named in GITHUB_OUTPUT.
"""

import os
import sys
from datetime import date, datetime, timedelta

from central_time import CENTRAL

WINDOW_START_HOUR = 18        # 6 PM Central: games are underway, start checking
DAY_ROLLOVER_HOUR = 10        # 10 AM Central: yesterday's recap day ends, a new one begins


def recap_day(now=None):
    """The Central calendar day a recap sent at `now` is about.

    10 AM to 10 AM Central: at 12:30 AM on Nov 9 this is still Nov 8, and at 8 AM on Nov 9
    it is still Nov 8 (last night's games), but from 10 AM on Nov 9 it is Nov 9.
    """
    now = (now or datetime.now(CENTRAL)).astimezone(CENTRAL)
    return (now - timedelta(hours=DAY_ROLLOVER_HOUR)).date()


def in_window(now=None):
    now = (now or datetime.now(CENTRAL)).astimezone(CENTRAL)
    return now.hour >= WINDOW_START_HOUR or now.hour < DAY_ROLLOVER_HOUR


def decide(event_name, requested_day="", now=None):
    """Return (go, day, reason).

    `event_name` is "schedule" for the timer; anything else (the manual button) always goes.
    `requested_day` is an optional YYYY-MM-DD for a manual run. A bad date raises ValueError.
    """
    now = (now or datetime.now(CENTRAL)).astimezone(CENTRAL)
    if event_name != "schedule":
        day = date.fromisoformat(requested_day) if requested_day else recap_day(now)
        return True, day, "manual run: checking right away"
    day = recap_day(now)
    if not in_window(now):
        return False, day, f"{now:%H:%M} Central is outside the recap window"
    return True, day, f"{now:%H:%M} Central is inside the recap window, recap day {day}"


if __name__ == "__main__":
    event = sys.argv[1] if len(sys.argv) > 1 else "schedule"
    requested = sys.argv[2] if len(sys.argv) > 2 else ""
    try:
        go, day, reason = decide(event, requested.strip())
    except ValueError:
        sys.exit(f"The date must look like 2026-11-08, not {requested!r}.")
    print(f"{reason} -> go={str(go).lower()}")

    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"go={str(go).lower()}\nday={day.isoformat()}\n")
