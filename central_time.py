"""
central_time.py - Central time helpers shared by the bot's scripts. Standard library only.

"Central" is a time zone with daylight saving (UTC-5 in summer, UTC-6 in winter), so the
offset is never written in by hand: everything here asks Python's time zone database.
"""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")


def to_central(iso):
    """A stored UTC time such as '2026-11-08T23:30:00Z' as a datetime in Central time."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(CENTRAL)


def day_bounds(day):
    """The UTC start and end of a Central calendar day, as the strings stored in the database.

    A day that daylight saving changes is 23 or 25 hours long, which is why this is
    computed from the time zone database and not as "start + 24 hours".
    """
    def utc(moment):
        return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    start = datetime.combine(day, time.min, tzinfo=CENTRAL)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=CENTRAL)
    return utc(start), utc(end)
