"""
load.py - helpers for the analysis notebooks.

Everything here only READS data/odds.db: the database is opened read-only, so
an analysis can never change or damage the history.

    import load
    games = load.game_lines()            # one row per finished game (see sql/game_lines.sql)
    rest = load.rest_days()              # days since each team's previous game
    games = load.with_rest_days(games)   # adds home_b2b / away_b2b columns
"""

import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
DEFAULT_DB = HERE.parent / "data" / "odds.db"
CENTRAL = "America/Chicago"


def connect(db_path=DEFAULT_DB):
    """Open the database READ-ONLY."""
    path = Path(db_path).resolve()
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build it with: python scripts/backfill_from_raw.py --rebuild "
            "(see analysis/README.md)")
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def query(sql, db_path=DEFAULT_DB, **kwargs):
    """Run any SQL and return a DataFrame."""
    with closing(connect(db_path)) as conn:
        return pd.read_sql_query(sql, conn, **kwargs)


def game_lines(db_path=DEFAULT_DB):
    """One row per finished game with consensus pre-game lines and the result."""
    df = query((HERE / "sql" / "game_lines.sql").read_text(encoding="utf-8"), db_path)
    df["commence_time"] = pd.to_datetime(df["commence_time"], utc=True)
    df["game_date"] = df["commence_time"].dt.tz_convert(CENTRAL).dt.date      # the Central calendar date
    return df


def rest_days(db_path=DEFAULT_DB):
    """For every game in the database and each of its two teams: how many calendar days
    (Central time) since that team's previous game in the database. NaN for the first
    game seen, so only trust this once the database covers a stretch of the season."""
    events = query("SELECT event_id, sport_key, commence_time, home_team, away_team FROM events", db_path)
    events["commence_time"] = pd.to_datetime(events["commence_time"], utc=True)
    home = events.assign(team=events["home_team"], is_home=True)
    away = events.assign(team=events["away_team"], is_home=False)
    long = pd.concat([home, away], ignore_index=True)[["event_id", "sport_key", "team", "is_home", "commence_time"]]
    long["game_day"] = long["commence_time"].dt.tz_convert(CENTRAL).dt.normalize().dt.tz_localize(None)
    long = long.sort_values(["sport_key", "team", "commence_time"])
    long["days_since_last_game"] = long.groupby(["sport_key", "team"])["game_day"].diff().dt.days
    long["back_to_back"] = long["days_since_last_game"] == 1
    return long[["event_id", "team", "is_home", "days_since_last_game", "back_to_back"]]


def with_rest_days(games, db_path=DEFAULT_DB):
    """Add home_b2b and away_b2b columns (True when that team played the day before)."""
    rest = rest_days(db_path)
    home = rest[rest["is_home"]].set_index("event_id")["back_to_back"].rename("home_b2b")
    away = rest[~rest["is_home"]].set_index("event_id")["back_to_back"].rename("away_b2b")
    return games.join(home, on="event_id").join(away, on="event_id")
