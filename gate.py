"""
gate.py - decides whether a scheduled run should send the digest right now.

Why this exists: GitHub starts scheduled workflows late, usually by 10-35
minutes and occasionally by hours. So instead of "run at exactly one time", the
workflow starts every hour, and each run asks this script:

    "Is it inside the send window (7 AM to 2 PM Central)?"

The first run inside the window sends the digest and leaves a marker for the
day; later runs see the marker and do nothing. (The marker part lives in the
workflow file.) If one run is delayed or fails, the next hour's run covers it.

This file uses only Python's standard library so it starts instantly.

    python gate.py schedule      -> go=true/false, today=YYYY-MM-DD
    python gate.py workflow_dispatch   (a manual run: always go=true)

When running on GitHub it writes its answers to the file named in the
GITHUB_OUTPUT environment variable, which the workflow reads.
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from config import SEND_FROM_HOUR, SEND_UNTIL_HOUR

CENTRAL = ZoneInfo("America/Chicago")


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
        return False, today, f"{now:%H:%M} Central is before the {SEND_FROM_HOUR}:00 send window"
    if now.hour >= SEND_UNTIL_HOUR:
        return False, today, f"{now:%H:%M} Central is after the {SEND_UNTIL_HOUR}:00 send window"
    return True, today, f"{now:%H:%M} Central is inside the send window"


if __name__ == "__main__":
    event = sys.argv[1] if len(sys.argv) > 1 else "schedule"
    go, today, reason = decide(event)
    print(f"{reason} -> go={str(go).lower()}")

    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"go={str(go).lower()}\ntoday={today}\n")
