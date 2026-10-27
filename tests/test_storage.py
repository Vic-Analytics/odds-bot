"""Tests for odds-history storage. Fake data only: no API calls, no credits."""

import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import odds_api
import storage
from helpers import book, game, outcome

ROOT = Path(__file__).parent.parent

SPORT = "icehockey_nhl"
START = "2026-10-30T00:30:00Z"          # the game starts at 00:30 UTC on Oct 30
PULL1 = "2026-10-28T13:48:55Z"          # pre-game pulls
PULL2 = "2026-10-29T13:50:10Z"
LIVE_PULL = "2026-10-30T01:00:00Z"      # after kickoff, so these are live odds


def response(start=START, dk_home=-170):
    """A fake API response: one game, two sportsbooks, moneyline + totals."""
    return [game("Colorado Avalanche", "Pittsburgh Penguins", start=start, game_id="evt1", books=[
        book("DraftKings",
             h2h=[outcome("Colorado Avalanche", dk_home), outcome("Pittsburgh Penguins", 150)],
             totals=[outcome("Over", -115, 6.5), outcome("Under", -105, 6.5)]),
        book("FanDuel",
             h2h=[outcome("Colorado Avalanche", -165), outcome("Pittsburgh Penguins", 145)],
             totals=[outcome("Over", -112, 6.5), outcome("Under", -108, 6.5)]),
    ])]


def query(sql, *params):
    with closing(sqlite3.connect(storage.db_path())) as conn:
        return conn.execute(sql, params).fetchall()


def count(table):
    return query(f"SELECT COUNT(*) FROM {table}")[0][0]


# ---------- the raw archive ----------

def test_raw_file_is_saved_untouched_with_the_time_in_its_name():
    body = b'[ {"id":"evt1",   "note":"spacing and order are kept"} ]'
    storage.save_snapshot(SPORT, json.loads(body), raw_body=body, pulled_at=PULL1)
    path = storage.data_dir() / "raw" / "2026-10-28" / "icehockey_nhl__134855Z.json"
    assert path.read_bytes() == body


def test_raw_file_falls_back_to_the_parsed_json():
    storage.save_snapshot(SPORT, response(), pulled_at=PULL1)
    path = storage.raw_path_for(SPORT, PULL1)
    assert json.loads(path.read_text(encoding="utf-8")) == response()


def test_a_second_pull_on_the_same_day_gets_its_own_file():
    storage.save_snapshot(SPORT, response(), pulled_at="2026-10-28T13:48:55Z")
    storage.save_snapshot(SPORT, response(), pulled_at="2026-10-28T15:02:01Z")
    names = sorted(p.name for p in (storage.data_dir() / "raw" / "2026-10-28").iterdir())
    assert names == ["icehockey_nhl__134855Z.json", "icehockey_nhl__150201Z.json"]


def test_an_existing_raw_file_is_never_overwritten():
    storage.save_snapshot(SPORT, response(), raw_body=b"[]", pulled_at=PULL1)
    storage.save_snapshot(SPORT, response(), raw_body=b'[{"id":"changed"}]', pulled_at=PULL1)
    assert storage.raw_path_for(SPORT, PULL1).read_bytes() == b"[]"


# ---------- the database ----------

def test_tables_view_and_version_exist_and_results_is_empty():
    storage.save_snapshot(SPORT, response(), pulled_at=PULL1)
    names = {r[0] for r in query("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    assert {"events", "odds", "results", "pulls", "pregame_odds"} <= names
    assert query("PRAGMA user_version")[0][0] == storage.SCHEMA_VERSION
    assert count("results") == 0


def test_rows_land_correctly():
    storage.save_snapshot(SPORT, response(), pulled_at=PULL1)
    assert query("SELECT * FROM events") == [
        ("evt1", "icehockey_nhl", START, "Colorado Avalanche", "Pittsburgh Penguins")]
    assert count("odds") == 8          # 2 books x (2 moneyline + 2 totals)

    ml = query("SELECT price, point, last_update, typeof(price) FROM odds "
               "WHERE bookmaker='draftkings' AND market='h2h' AND outcome='Pittsburgh Penguins'")
    assert ml == [(150, None, "2026-10-28T13:40:00Z", "integer")]      # moneyline has no point

    over = query("SELECT price, point FROM odds "
                 "WHERE bookmaker='fanduel' AND market='totals' AND outcome='Over'")
    assert over == [(-112, 6.5)]

    assert query("SELECT * FROM pulls") == [(PULL1, SPORT, "h2h,totals", 1, 8)]


def test_running_the_same_pull_twice_creates_no_duplicates(capsys):
    storage.save_snapshot(SPORT, response(), pulled_at=PULL1)
    second = storage.save_snapshot(SPORT, response(), pulled_at=PULL1)
    assert (count("events"), count("odds"), count("pulls")) == (1, 8, 1)
    # The rerun must succeed quietly, not fail and get swallowed by the safety net.
    assert second is not None
    assert "[storage]" not in capsys.readouterr().err


def test_a_new_pull_adds_a_snapshot_but_not_a_second_game():
    storage.save_snapshot(SPORT, response(dk_home=-170), pulled_at=PULL1)
    storage.save_snapshot(SPORT, response(dk_home=-180), pulled_at=PULL2)   # the line moved
    assert (count("events"), count("odds"), count("pulls")) == (1, 16, 2)
    history = query("SELECT pulled_at, price FROM odds WHERE bookmaker='draftkings' "
                    "AND market='h2h' AND outcome='Colorado Avalanche' ORDER BY pulled_at")
    assert history == [(PULL1, -170), (PULL2, -180)]


def test_a_rescheduled_game_updates_its_start_time():
    storage.save_snapshot(SPORT, response(start="2026-10-30T00:30:00Z"), pulled_at=PULL1)
    storage.save_snapshot(SPORT, response(start="2026-10-30T02:00:00Z"), pulled_at=PULL2)
    assert query("SELECT commence_time FROM events") == [("2026-10-30T02:00:00Z",)]


def test_pregame_view_hides_prices_pulled_after_kickoff():
    for pulled_at in (PULL1, PULL2, LIVE_PULL):
        storage.save_snapshot(SPORT, response(), pulled_at=pulled_at)
    assert query("SELECT DISTINCT pulled_at FROM odds ORDER BY 1") == [(PULL1,), (PULL2,), (LIVE_PULL,)]
    assert query("SELECT DISTINCT pulled_at FROM pregame_odds ORDER BY 1") == [(PULL1,), (PULL2,)]


def test_bad_pieces_are_skipped_without_failing():
    messy = response()
    messy.append({"home_team": "No Id", "away_team": "Nobody"})                 # no event id
    messy[0]["bookmakers"][0]["markets"][0]["outcomes"].append(outcome("Bad", None))   # no price
    messy[0]["bookmakers"][0]["markets"][0]["outcomes"].append({"name": "Text", "price": "n/a"})
    messy[0]["bookmakers"][1]["key"] = None                                       # no bookmaker
    result = storage.save_snapshot(SPORT, messy, pulled_at=PULL1)
    assert result["skipped"] >= 4
    assert count("events") == 1
    assert count("odds") == 4          # only the first sportsbook's 4 good rows survive


def test_float_prices_are_stored_as_whole_numbers():
    data = response()
    data[0]["bookmakers"][0]["markets"][0]["outcomes"][0]["price"] = -170.0
    storage.save_snapshot(SPORT, data, pulled_at=PULL1)
    assert query("SELECT price, typeof(price) FROM odds WHERE bookmaker='draftkings' "
                 "AND market='h2h' AND outcome='Colorado Avalanche'") == [(-170, "integer")]


# ---------- storage can never break the bot ----------

def test_a_response_that_is_not_a_list_does_not_raise(capsys):
    assert storage.save_snapshot(SPORT, {"message": "oops"}, pulled_at=PULL1) is None
    assert "[storage]" in capsys.readouterr().err


def test_an_unwritable_location_does_not_raise(tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "a_file_not_a_folder"
    blocker.write_text("x")
    monkeypatch.setenv("ODDS_DATA_DIR", str(blocker / "data"))
    assert storage.save_snapshot(SPORT, response(), pulled_at=PULL1) is None
    assert capsys.readouterr().err.count("[storage]") == 2       # raw file + database both reported


def test_fetch_odds_returns_the_same_data_and_saves_a_copy(monkeypatch):
    body = json.dumps(response(), separators=(",", ":")).encode()

    class FakeResponse:
        status_code, ok, content = 200, True, body
        headers = {"x-requests-remaining": "321"}

        def json(self):
            return json.loads(body)

    monkeypatch.setattr(odds_api, "ODDS_API_KEY", "test-key")
    monkeypatch.setattr(odds_api, "request_with_retries", lambda *a, **k: FakeResponse())
    games, remaining = odds_api.fetch_odds(SPORT, "h2h,totals")

    assert (games, remaining) == (response(), "321")                  # behavior unchanged
    assert count("odds") == 8
    [raw_file] = list((storage.data_dir() / "raw").glob("*/*.json"))
    assert raw_file.read_bytes() == body                               # exact bytes kept


def test_fetch_odds_still_works_when_storage_is_broken(monkeypatch):
    class FakeResponse:
        status_code, ok, content = 200, True, b"[]"
        headers = {"x-requests-remaining": "5"}

        def json(self):
            return []

    def boom(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(odds_api, "ODDS_API_KEY", "test-key")
    monkeypatch.setattr(odds_api, "request_with_retries", lambda *a, **k: FakeResponse())
    monkeypatch.setattr(storage, "connect", boom)
    assert odds_api.fetch_odds(SPORT) == ([], "5")


# ---------- rebuilding from the raw archive ----------

def snapshot_of_tables():
    return {t: query(f"SELECT * FROM {t} ORDER BY 1, 2, 3, 4, 5") for t in ("events", "odds", "pulls")}


def test_rebuilding_from_raw_gives_the_same_database_as_saving_live():
    storage.save_snapshot(SPORT, response(dk_home=-170), raw_body=json.dumps(response(dk_home=-170)).encode(),
                          pulled_at=PULL1)
    storage.save_snapshot(SPORT, response(dk_home=-180), raw_body=json.dumps(response(dk_home=-180)).encode(),
                          pulled_at=PULL2)
    live = snapshot_of_tables()

    raw_dir = storage.data_dir() / "raw"
    rebuilt_db = storage.data_dir() / "rebuilt.db"
    summary = storage.rebuild_from_raw(raw_dir, rebuilt_db)
    assert summary["files"] == 2

    with closing(sqlite3.connect(rebuilt_db)) as conn:
        rebuilt = {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2, 3, 4, 5").fetchall()
                   for t in ("events", "odds", "pulls")}
    assert rebuilt == live


def test_backfill_is_safe_to_repeat_and_rebuild_starts_fresh():
    for pulled_at in (PULL1, PULL2):
        storage.save_snapshot(SPORT, response(), raw_body=json.dumps(response()).encode(), pulled_at=pulled_at)
    before = snapshot_of_tables()

    storage.rebuild_from_raw(storage.data_dir() / "raw", storage.db_path())                 # again, on top
    assert snapshot_of_tables() == before
    storage.rebuild_from_raw(storage.data_dir() / "raw", storage.db_path(), rebuild=True)   # from scratch
    assert snapshot_of_tables() == before


def test_backfill_skips_files_it_cannot_read():
    storage.save_snapshot(SPORT, response(), raw_body=json.dumps(response()).encode(), pulled_at=PULL1)
    day = storage.data_dir() / "raw" / "2026-10-28"
    (day / "notes.json").write_text("{}")                                  # wrong name
    (day / "icehockey_nhl__999999Z.json").write_text("not json at all")    # right name, broken contents
    summary = storage.rebuild_from_raw(storage.data_dir() / "raw", storage.db_path(), rebuild=True)
    assert summary["files"] == 1 and summary["skipped_files"] == 2
    assert count("odds") == 8


def test_backfill_script_runs_from_any_folder(tmp_path):
    storage.save_snapshot(SPORT, response(), raw_body=json.dumps(response()).encode(), pulled_at=PULL1)
    db = tmp_path / "elsewhere" / "odds.db"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "backfill_from_raw.py"),
         "--raw-dir", str(storage.data_dir() / "raw"), "--db", str(db), "--rebuild"],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "Read 1 raw file(s)" in result.stdout
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM odds").fetchone()[0] == 8


# ---------- the example query ----------

def test_best_moneyline_query_picks_the_best_price_per_team_and_ignores_live_odds():
    sql_file = ROOT / "scripts" / "best_moneyline_today.sql"
    sql = sql_file.read_text(encoding="utf-8")

    # "Today" is Oct 29 Central: the game starts 23:30 UTC = 6:30 PM CDT.
    assert "date('now', '-5 hours')" in sql
    sql = sql.replace("date('now', '-5 hours')", "'2026-10-29'")

    storage.save_snapshot(SPORT, response(start="2026-10-29T23:30:00Z"), pulled_at=PULL1)
    # A later live snapshot with wild prices must be ignored.
    live = response(start="2026-10-29T23:30:00Z", dk_home=-900)
    live[0]["bookmakers"][1]["markets"][0]["outcomes"][1]["price"] = 5000
    storage.save_snapshot(SPORT, live, pulled_at="2026-10-30T00:00:00Z")

    with closing(sqlite3.connect(storage.db_path())) as conn:
        rows = conn.execute(sql).fetchall()
    assert [(r[4], r[5], r[6]) for r in rows] == [
        ("Colorado Avalanche", -165, "fanduel"),      # -165 beats -170
        ("Pittsburgh Penguins", 150, "draftkings"),   # +150 beats +145
    ]
    assert rows[0][1] == "2026-10-29 18:30:00"        # shown in Central time


# ---------- upgrading an older database ----------

def test_a_version_1_database_gains_the_results_status_column():
    db = storage.db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as old:       # how the results table looked in version 1
        old.execute("CREATE TABLE results (event_id TEXT PRIMARY KEY, home_score INTEGER, away_score INTEGER, "
                    "completed INTEGER, source TEXT, updated_at TEXT)")
        old.execute("INSERT INTO results VALUES ('evt1', 3, 2, 1, 'old', '2026-10-01T00:00:00Z')")
        old.execute("PRAGMA user_version = 1")
        old.commit()
    storage.save_snapshot(SPORT, response(), pulled_at=PULL1)           # opens it with the current code
    columns = [row[1] for row in query("PRAGMA table_info(results)")]
    assert "status" in columns
    assert query("SELECT event_id, home_score, status FROM results") == [("evt1", 3, None)]   # old rows kept
    assert query("PRAGMA user_version")[0][0] == storage.SCHEMA_VERSION
