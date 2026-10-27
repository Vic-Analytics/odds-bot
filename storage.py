"""
storage.py - save every odds response the bot pulls, so it can be analyzed later.

This module only SAVES data the bot already fetched. It never calls the Odds
API, so it costs no credits.

What gets saved each time odds are pulled (see save_snapshot):

  1. The raw archive: the untouched API response, written to
         data/raw/YYYY-MM-DD/<sport_key>__HHMMSSZ.json
     (the date and time are UTC; the time is in the name because a retry or
     manual run can pull the same sport twice in one day).
  2. A SQLite database, data/odds.db, with these tables:
         events   one row per game
         odds     one row per price, per sportsbook, per pull
         results  final scores (created now, filled in later)
         pulls    one row per pull, for checking coverage
     plus a view, pregame_odds, that hides prices pulled after a game started
     (those are live odds, which are not comparable to pre-game lines).

The raw archive is the source of truth. The database can always be rebuilt
from it with scripts/backfill_from_raw.py, so changing the tables later never
loses history.

Everything is stored in UTC. Convert to America/Chicago only for display.

Only the Python standard library is used.
"""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Bump this when the tables change. It is stored in the database
# (PRAGMA user_version) so a later version can tell what it is looking at.
SCHEMA_VERSION = 1

DEFAULT_DATA_DIR = Path(__file__).parent / "data"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id      TEXT PRIMARY KEY,
    sport_key     TEXT,
    commence_time TEXT,            -- UTC, e.g. 2026-10-17T00:30:00Z
    home_team     TEXT,
    away_team     TEXT
);

CREATE TABLE IF NOT EXISTS odds (
    event_id    TEXT NOT NULL,
    pulled_at   TEXT NOT NULL,     -- UTC time of the pull
    bookmaker   TEXT NOT NULL,     -- the API's stable key, e.g. draftkings
    market      TEXT NOT NULL,     -- h2h, spreads or totals
    outcome     TEXT NOT NULL,     -- team name, Draw, Over or Under
    price       INTEGER NOT NULL,  -- American odds, e.g. -110 or +150
    point       REAL,              -- spread or total line; NULL for h2h
    last_update TEXT,              -- when the sportsbook last changed this price
    PRIMARY KEY (event_id, pulled_at, bookmaker, market, outcome)
);

CREATE TABLE IF NOT EXISTS results (
    event_id   TEXT PRIMARY KEY,
    home_score INTEGER,
    away_score INTEGER,
    completed  INTEGER,            -- 1 when the game is final
    source     TEXT,               -- where the score came from
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS pulls (
    pulled_at   TEXT NOT NULL,
    sport_key   TEXT NOT NULL,
    markets     TEXT,              -- e.g. h2h,totals
    event_count INTEGER,
    odds_rows   INTEGER,
    PRIMARY KEY (pulled_at, sport_key)
);

CREATE INDEX IF NOT EXISTS idx_odds_event  ON odds(event_id);
CREATE INDEX IF NOT EXISTS idx_odds_market ON odds(market, bookmaker);
CREATE INDEX IF NOT EXISTS idx_events_sport_time ON events(sport_key, commence_time);

-- Prices pulled BEFORE the game started. After kickoff the API returns live
-- (in-play) odds, which are not comparable, so analysis should use this view.
CREATE VIEW IF NOT EXISTS pregame_odds AS
SELECT o.event_id, o.pulled_at, o.bookmaker, o.market, o.outcome, o.price, o.point,
       o.last_update, e.sport_key, e.commence_time, e.home_team, e.away_team
FROM odds o
JOIN events e ON e.event_id = o.event_id
WHERE o.pulled_at < e.commence_time;
"""


# ---------- small helpers ----------

def data_dir():
    """Where data is kept. Set ODDS_DATA_DIR to use a different folder
    (the tests do this so they never touch the real data/)."""
    return Path(os.environ.get("ODDS_DATA_DIR") or DEFAULT_DATA_DIR)


def db_path():
    return data_dir() / "odds.db"


def utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(message):
    """Storage problems are reported here and never raised to the bot."""
    print(f"[storage] {message}", file=sys.stderr)


def _to_int(value):
    """American odds as a whole number, or None if it isn't a usable number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(round(value))


def _to_float(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


# ---------- the database ----------

def connect(db_file):
    """Open (creating if needed) the database and make sure the tables exist."""
    db_file = Path(db_file)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file, timeout=10)
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    return conn


def insert_snapshot(conn, sport_key, response_json, pulled_at):
    """Add one pull to the database. Safe to run again: nothing is duplicated.

    Malformed pieces (an event with no id, a price that isn't a number) are
    skipped and counted, not fatal. Returns a small dictionary of counts.
    """
    if not isinstance(response_json, list):
        raise ValueError(f"expected a list of games, got {type(response_json).__name__}")

    events, odds, markets_seen, skipped = [], [], set(), 0

    for game in response_json:
        event_id = game.get("id") if isinstance(game, dict) else None
        if not event_id:
            skipped += 1
            continue
        events.append((
            event_id, game.get("sport_key") or sport_key, game.get("commence_time"),
            game.get("home_team"), game.get("away_team"),
        ))
        for book in game.get("bookmakers") or []:
            book_key = book.get("key")
            for market in book.get("markets") or []:
                market_key = market.get("key")
                last_update = market.get("last_update") or book.get("last_update")
                for outcome in market.get("outcomes") or []:
                    price = _to_int(outcome.get("price"))
                    if not (book_key and market_key and outcome.get("name")) or price is None:
                        skipped += 1
                        continue
                    markets_seen.add(market_key)
                    odds.append((
                        event_id, pulled_at, book_key, market_key, outcome["name"],
                        price, _to_float(outcome.get("point")), last_update,
                    ))

    with conn:  # one transaction: either the whole pull is saved, or none of it
        # A game can be rescheduled, so events are updated; everything else is
        # insert-or-ignore, so a rerun never creates duplicates.
        conn.executemany(
            """INSERT INTO events (event_id, sport_key, commence_time, home_team, away_team)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(event_id) DO UPDATE SET
                   sport_key = excluded.sport_key, commence_time = excluded.commence_time,
                   home_team = excluded.home_team, away_team = excluded.away_team""",
            events,
        )
        conn.executemany(
            """INSERT OR IGNORE INTO odds
               (event_id, pulled_at, bookmaker, market, outcome, price, point, last_update)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            odds,
        )
        conn.execute(
            """INSERT OR IGNORE INTO pulls (pulled_at, sport_key, markets, event_count, odds_rows)
               VALUES (?, ?, ?, ?, ?)""",
            (pulled_at, sport_key, ",".join(sorted(markets_seen)), len(events), len(odds)),
        )
    return {"events": len(events), "odds": len(odds), "skipped": skipped}


# ---------- the raw archive ----------

def raw_path_for(sport_key, pulled_at):
    """data/raw/2026-10-28/icehockey_nhl__134855Z.json for a pull at 13:48:55 UTC."""
    day, time_part = pulled_at.rstrip("Z").split("T")
    return data_dir() / "raw" / day / f"{sport_key}__{time_part.replace(':', '')}Z.json"


def _write_raw(sport_key, response_json, raw_body, pulled_at):
    """Save the untouched response. Returns the path, or None if it already existed."""
    path = raw_path_for(sport_key, pulled_at)
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)

    # Prefer the exact bytes the API sent. Fall back to re-encoding the parsed JSON.
    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")
    if not isinstance(raw_body, (bytes, bytearray)):
        raw_body = json.dumps(response_json, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    # Write to a temporary file first, so a crash can never leave half a file.
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(raw_body)
    os.replace(temp, path)
    return path


# ---------- the one call the bot makes ----------

def save_snapshot(sport_key, response_json, raw_body=None, pulled_at=None):
    """Save one Odds API response. NEVER raises: storage must not break the digest.

    sport_key      e.g. "icehockey_nhl"
    response_json  the parsed response (a list of games)
    raw_body       optional: the exact bytes the API sent, saved as-is
    pulled_at      optional UTC time like "2026-10-28T13:48:55Z" (default: now)

    Returns a dictionary describing what was saved, or None if the database
    step failed. Problems are printed to stderr with a "[storage]" prefix.
    """
    try:
        pulled_at = pulled_at or utc_now_iso()
    except Exception as error:  # pragma: no cover - the clock failing is not realistic
        log(f"could not read the clock: {error}")
        return None

    # The raw file matters most, so write it first; a database problem must
    # not stop it, and a file problem must not stop the database.
    try:
        _write_raw(sport_key, response_json, raw_body, pulled_at)
    except Exception as error:
        log(f"could not save the raw file for {sport_key}: {error}")

    try:
        conn = connect(db_path())
        try:
            return insert_snapshot(conn, sport_key, response_json, pulled_at)
        finally:
            conn.close()
    except Exception as error:
        log(f"could not save {sport_key} to the database: {error}")
        return None


# ---------- rebuilding the database from the raw archive ----------

RAW_NAME = re.compile(r"^(?P<sport_key>.+)__(?P<h>\d{2})(?P<m>\d{2})(?P<s>\d{2})Z\.json$")


def rebuild_from_raw(raw_dir, db_file, rebuild=False):
    """Fill the database from every file in the raw archive.

    With rebuild=True the existing database is deleted first (use this after
    changing the tables). Without it, existing rows are kept and nothing is
    duplicated, so it is safe to run again after adding new raw files.
    Returns a summary dictionary.
    """
    raw_dir, db_file = Path(raw_dir), Path(db_file)
    if rebuild:
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(db_file) + suffix).unlink(missing_ok=True)

    summary = {"files": 0, "events": 0, "odds": 0, "skipped_files": 0}
    conn = connect(db_file)
    try:
        # Oldest first, so a game's latest start time is the one that is kept.
        for path in sorted(raw_dir.glob("*/*.json")):
            match = RAW_NAME.match(path.name)
            if not match:
                log(f"skipping {path}: the name is not <sport_key>__HHMMSSZ.json")
                summary["skipped_files"] += 1
                continue
            pulled_at = f"{path.parent.name}T{match['h']}:{match['m']}:{match['s']}Z"
            try:
                response_json = json.loads(path.read_text(encoding="utf-8"))
                stats = insert_snapshot(conn, match["sport_key"], response_json, pulled_at)
            except Exception as error:
                log(f"skipping {path}: {error}")
                summary["skipped_files"] += 1
                continue
            summary["files"] += 1
            summary["events"] += stats["events"]
            summary["odds"] += stats["odds"]
    finally:
        conn.close()
    return summary
