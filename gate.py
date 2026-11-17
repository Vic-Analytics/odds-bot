"""
gate.py - decides whether a scheduled run should send the digest right now.

Why this exists: GitHub starts scheduled workflows late, usually by 10-35
minutes and occasionally by hours. So instead of "run at exactly one time", the
workflow starts every hour, and each run asks this script:

    "Is it inside the send window (7 AM to 5 PM Central)?"

The first run inside the window sends the digest and leaves a marker for the
day; later runs see the marker and do nothing. (The marker part lives in the
workflow file.) If one run is delayed or fails, the next hour's run covers it.

Since Nov 12 2026 GitHub starts only about three scheduled runs a day, at times
it picks, and none of them reliably in the morning. So a run that starts EARLY
(after 1:30 AM Central, before the window opens) is not turned away: the script
also says how many seconds to wait, and the workflow sleeps until 7:00 AM and
then sends. A pre-dawn run that GitHub does start therefore still delivers the
brief at 7:00 AM.

This file uses only Python's standard library so it starts instantly.

    python gate.py schedule      -> go=true/false, today=YYYY-MM-DD
    python gate.py workflow_dispatch   (a manual run: always go=true)

When running on GitHub it writes its answers to the file named in the
GITHUB_OUTPUT environment variable, which the workflow reads.
"""

import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from config import EARLY_START_MINUTES, SEND_FROM_HOUR, SEND_UNTIL_HOUR

CENTRAL = ZoneInfo("America/Chicago")


def seconds_until_open(now=None):
    """How many seconds from `now` until the send window opens today (0 once it is open).

    Counted in real elapsed time, so it is right on the days daylight saving starts or ends
    (a wall-clock subtraction would be an hour off).
    """
    now = (now or datetime.now(CENTRAL)).astimezone(CENTRAL)
    opens = now.replace(hour=SEND_FROM_HOUR, minute=0, second=0, microsecond=0)
    if now >= opens:
        return 0
    return int((opens.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds())


def decide(event_name, now=None):
    """Return (go, today, reason).

    `event_name` is how the run started: "schedule" for the timer, anything
    else (such as "workflow_dispatch", the manual button) for a person.
    `now` is for the tests. Normally it is the current time.
    """
    now = (now or datetime.now(CENTRAL)).astimezone(CENTRAL)
    today = now.strftime("%Y-%m-%d")

    if event_name != "schedule":
        return True, today, "manual run: sending right away"
    if now.hour < SEND_FROM_HOUR:
        wait = seconds_until_open(now)
        if wait <= EARLY_START_MINUTES * 60:
            return True, today, (f"{now:%H:%M} Central is before the {SEND_FROM_HOUR}:00 send window: "
                                 f"will wait {wait // 60} minutes for it to open, then send")
        return False, today, (f"{now:%H:%M} Central is too early to wait for the {SEND_FROM_HOUR}:00 send window "
                              f"(the longest wait is {EARLY_START_MINUTES} minutes)")
    if now.hour >= SEND_UNTIL_HOUR:
        return False, today, f"{now:%H:%M} Central is after the {SEND_UNTIL_HOUR}:00 send window"
    return True, today, f"{now:%H:%M} Central is inside the send window"


def evaluate(event_name, now=None):
    """Return (go, today, reason, wait_seconds): decide(), plus how long to wait for the window to open.

    A manual run never waits (wait is 0): the person pressing the button wants it now.
    """
    now = (now or datetime.now(CENTRAL)).astimezone(CENTRAL)
    go, today, reason = decide(event_name, now)
    wait = seconds_until_open(now) if (go and event_name == "schedule") else 0
    return go, today, reason, wait


if __name__ == "__main__":
    event = sys.argv[1] if len(sys.argv) > 1 else "schedule"
    go, today, reason, wait = evaluate(event)
    print(f"{reason} -> go={str(go).lower()} wait={wait}")

    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"go={str(go).lower()}\ntoday={today}\nwait={wait}\n")
