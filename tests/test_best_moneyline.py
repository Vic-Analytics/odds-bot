"""Tests for the "today's best moneyline" query and its time-zone handling (fake data only)."""

import importlib.util
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest

import storage
from test_storage import PULL1, SPORT, response

SCRIPT = Path(__file__).parent.parent / "scripts" / "best_moneyline_today.py"
spec = importlib.util.spec_from_file_location("best_moneyline_today", SCRIPT)
best = importlib.util.module_from_spec(spec)
spec.loader.exec_module(best)


def lines(day):
    with closing(sqlite3.connect(storage.db_path())) as conn:
        return best.best_lines(conn, day)


# ---------- the Central day, computed rather than written in by hand ----------

@pytest.mark.parametrize("day, start, end", [
    (date(2026, 10, 28), "2026-10-28T05:00:00Z", "2026-10-29T05:00:00Z"),    # summer: Central is UTC-5
    (date(2026, 11, 8),  "2026-11-08T06:00:00Z", "2026-11-09T06:00:00Z"),    # winter: Central is UTC-6
    (date(2026, 11, 1),  "2026-11-01T05:00:00Z", "2026-11-02T06:00:00Z"),    # clocks go back: a 25-hour day
    (date(2026, 3, 8),   "2026-03-08T06:00:00Z", "2026-03-09T05:00:00Z"),    # clocks go forward: a 23-hour day
])
def test_day_bounds_follow_daylight_saving(day, start, end):
    assert best.day_bounds(day) == (start, end)


def test_the_sql_file_contains_no_hand_written_offset():
    sql = (SCRIPT.parent / "best_moneyline_today.sql").read_text(encoding="utf-8")
    assert "-5 hours" not in sql and "-6 hours" not in sql
    assert ":day_start" in sql and ":day_end" in sql


# ---------- the query ----------

def test_picks_the_best_price_per_team_and_ignores_live_odds():
    storage.save_snapshot(SPORT, response(start="2026-10-29T23:30:00Z"), pulled_at=PULL1)
    # A later live snapshot with wild prices must be ignored.
    live = response(start="2026-10-29T23:30:00Z", dk_home=-900)
    live[0]["bookmakers"][1]["markets"][0]["outcomes"][1]["price"] = 5000
    storage.save_snapshot(SPORT, live, pulled_at="2026-10-30T00:00:00Z")

    rows = lines(date(2026, 10, 29))
    assert [(r["team"], r["price"], r["bookmaker"]) for r in rows] == [
        ("Colorado Avalanche", -165, "fanduel"),      # -165 beats -170
        ("Pittsburgh Penguins", 150, "draftkings"),   # +150 beats +145
    ]
    assert rows[0]["start"].strftime("%Y-%m-%d %H:%M") == "2026-10-29 18:30"       # 23:30 UTC is 6:30 PM CDT


def test_a_late_winter_game_belongs_to_the_central_day_it_starts_on():
    # 05:30 UTC on Nov 9 is 11:30 PM on Nov 8 in Central (UTC-6). The old fixed "-5 hours" put it on Nov 9.
    storage.save_snapshot(SPORT, response(start="2026-11-09T05:30:00Z"), pulled_at="2026-11-08T14:00:00Z")
    assert len(lines(date(2026, 11, 8))) == 2
    assert lines(date(2026, 11, 9)) == []


def test_a_late_summer_game_belongs_to_the_central_day_it_starts_on():
    # 05:30 UTC on Oct 28 is 12:30 AM on Oct 28 in Central (UTC-5). A fixed "-6 hours" would put it on Oct 27.
    storage.save_snapshot(SPORT, response(start="2026-10-28T05:30:00Z"), pulled_at="2026-10-27T14:00:00Z")
    assert len(lines(date(2026, 10, 28))) == 2
    assert lines(date(2026, 10, 27)) == []


def test_a_game_starting_exactly_at_midnight_belongs_to_the_new_day():
    storage.save_snapshot(SPORT, response(start="2026-11-09T06:00:00Z"), pulled_at="2026-11-08T14:00:00Z")   # 12:00 AM CST on Nov 9
    assert lines(date(2026, 11, 8)) == []
    assert len(lines(date(2026, 11, 9))) == 2


def test_command_line_prints_the_table_and_an_empty_day_message(capsys):
    storage.save_snapshot(SPORT, response(start="2026-10-29T23:30:00Z"), pulled_at=PULL1)
    best.main(["--date", "2026-10-29"])
    out = capsys.readouterr().out
    assert "Colorado Avalanche" in out and "-165" in out and "06:30 PM" in out
    best.main(["--date", "2026-10-30"])
    assert "No games" in capsys.readouterr().out


def test_missing_database_gives_a_clear_message(tmp_path):
    with pytest.raises(SystemExit, match="not found"):
        best.main(["--db", str(tmp_path / "nope.db")])
