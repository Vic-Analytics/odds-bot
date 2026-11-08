"""
best_moneyline_today.py - today's best moneyline for each team, across sportsbooks.

    python scripts/best_moneyline_today.py                 games starting today (Central time)
    python scripts/best_moneyline_today.py --date 2026-11-08
    python scripts/best_moneyline_today.py --db other.db

"Today" is a Central calendar day. The offset from UTC changes with daylight
saving (UTC-5 in summer, UTC-6 in winter), so it is never written in by hand:
this script asks Python's time zone database for the exact start and end of the
day and hands them to scripts/best_moneyline_today.sql. It only READS the database.
"""

import argparse
import sqlite3
import sys
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import storage  # noqa: E402
from names import SPORT_NAME_BY_KEY  # noqa: E402

CENTRAL = ZoneInfo("America/Chicago")
SQL = (ROOT / "scripts" / "best_moneyline_today.sql").read_text(encoding="utf-8")


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


def best_lines(conn, day):
    """One row per team per game starting on `day` (Central): the best price and who has it."""
    day_start, day_end = day_bounds(day)
    rows = conn.execute(SQL, {"day_start": day_start, "day_end": day_end}).fetchall()
    return [{"sport_key": sport, "start": datetime.fromisoformat(commence.replace("Z", "+00:00")).astimezone(CENTRAL),
             "home": home, "away": away, "team": team, "price": price, "bookmaker": book}
            for sport, commence, home, away, team, price, book in rows]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Today's best moneyline per team across sportsbooks.")
    parser.add_argument("--date", help="Central calendar day, YYYY-MM-DD (default: today)")
    parser.add_argument("--db", default=str(storage.db_path()), help="database file (default: data/odds.db)")
    args = parser.parse_args(argv)

    day = date.fromisoformat(args.date) if args.date else datetime.now(CENTRAL).date()
    db_file = Path(args.db).resolve()
    if not db_file.exists():
        raise SystemExit(f"{db_file} not found. Build it first (see analysis/README.md, step 1).")

    with closing(sqlite3.connect(f"file:{db_file.as_posix()}?mode=ro", uri=True)) as conn:
        rows = best_lines(conn, day)
    if not rows:
        print(f"No games with pre-game odds starting on {day:%A, %b %d} (Central).")
        return
    print(f"Best moneyline for each team, games starting {day:%A, %b %d} (Central):\n")
    for r in rows:
        league = SPORT_NAME_BY_KEY.get(r["sport_key"], r["sport_key"])
        matchup = f"{r['away']} @ {r['home']}"
        print(f"{league:<18}{r['start']:%I:%M %p}  {matchup:<50}{r['team']:<26}{r['price']:>+6}  {r['bookmaker']}")


if __name__ == "__main__":
    main()
