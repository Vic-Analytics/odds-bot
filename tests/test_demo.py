"""Tests for the fake-data demo page: deterministic, purely synthetic, clearly marked and up to date."""

import ast
import hashlib
import importlib.util
import sqlite3
import sys
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import dashboard
import demo_data
import stats
import storage

spec = importlib.util.spec_from_file_location("make_demo", ROOT / "scripts" / "make_demo.py")
make_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_demo)


def fingerprint(db_file):
    """A hash of every row in the database."""
    with closing(sqlite3.connect(db_file)) as conn:
        return hashlib.sha256("\n".join(conn.iterdump()).encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def demo_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("demo") / "demo.db"
    summary = demo_data.build_database(path)
    return path, summary


@pytest.fixture(scope="module")
def page():
    return make_demo.make_page()


def rows(db_file, sql):
    with closing(sqlite3.connect(db_file)) as conn:
        return conn.execute(sql).fetchall()


# ---------- deterministic ----------

def test_the_same_seed_gives_exactly_the_same_database(demo_db, tmp_path):
    again = tmp_path / "again.db"
    demo_data.build_database(again)
    assert fingerprint(again) == fingerprint(demo_db[0])


def test_a_different_seed_gives_a_different_database(demo_db, tmp_path):
    other = tmp_path / "other.db"
    demo_data.build_database(other, seed=7)
    assert fingerprint(other) != fingerprint(demo_db[0])
    assert rows(other, "SELECT price FROM odds ORDER BY rowid LIMIT 50") != rows(demo_db[0], "SELECT price FROM odds ORDER BY rowid LIMIT 50")


def test_the_random_numbers_are_pinned_so_a_change_to_the_demo_is_noticed():
    """splitmix64 uses only integer math and one division, so these exact values hold on every computer."""
    rng = demo_data.Rng(2026)
    assert [rng.randint(0, 99) for _ in range(8)] == [85, 47, 66, 38, 79, 72, 95, 80]
    rng = demo_data.Rng(1)
    assert [rng.random() for _ in range(2)] == [0.5665615751722809, 0.7457817572627011]
    assert all(0 <= demo_data.Rng(n).random() < 1 for n in range(50))


# ---------- purely synthetic ----------

def test_every_row_is_marked_and_named_as_made_up(demo_db):
    path, summary = demo_db
    ids = [r[0] for r in rows(path, "SELECT event_id FROM events")]
    assert ids and all(i.startswith("demo-") for i in ids)
    assert {r[0] for r in rows(path, "SELECT DISTINCT source FROM results")} == {"demo"}
    assert {r[0] for r in rows(path, "SELECT DISTINCT sport_key FROM events")} == set(demo_data.ROSTERS)
    allowed_teams = {team for teams in demo_data.ROSTERS.values() for team in teams}
    names = {r[0] for r in rows(path, "SELECT home_team FROM events UNION SELECT away_team FROM events")}
    assert names <= allowed_teams and len(names) > 100
    assert {r[0] for r in rows(path, "SELECT DISTINCT bookmaker FROM odds")} <= {key for key, *_ in demo_data.BOOKS}


def test_all_dates_fall_inside_the_fake_calendar(demo_db):
    path, _ = demo_db
    earliest = (demo_data.FIRST_GAME_DAY - timedelta(days=2)).isoformat()
    latest = (demo_data.DEMO_NOW + timedelta(days=4)).strftime("%Y-%m-%d")
    (first_pull, last_pull), = rows(path, "SELECT MIN(pulled_at), MAX(pulled_at) FROM pulls")
    assert first_pull >= earliest and last_pull <= demo_data.DEMO_NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert rows(path, f"SELECT COUNT(*) FROM events WHERE commence_time > '{latest}' OR commence_time < '{earliest}'") == [(0,)]


def test_building_it_never_reads_the_odds_folder_or_the_network(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("the demo generator must not touch real data or the network")
    monkeypatch.setattr(storage, "data_dir", forbidden)
    monkeypatch.setattr(requests, "request", forbidden)
    monkeypatch.setattr(requests, "get", forbidden)
    monkeypatch.setattr(requests, "post", forbidden)
    monkeypatch.setenv("ODDS_DATA_DIR", str(tmp_path / "does-not-exist"))
    demo_data.build_database(tmp_path / "x.db")
    assert not (tmp_path / "does-not-exist").exists()


def test_the_generators_code_has_no_way_to_reach_real_data():
    source = (ROOT / "analysis" / "demo_data.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module.split(".")[0])
    # Only the calendar, the folder of this file, the empty database layout and the bot's league settings.
    assert imported == {"sys", "datetime", "pathlib", "storage", "central_time", "config"}
    for forbidden in ("requests", "urllib", "socket", "dotenv", "data_dir", "results_raw", "raw_path_for", "save_snapshot",
                      "odds-history-data", ".env", "open("):
        assert forbidden not in source, f"demo_data.py mentions {forbidden!r}"


# ---------- it looks like a real season ----------

def test_the_fake_season_looks_like_a_season(demo_db):
    path, summary = demo_db
    assert summary["games"] > 400 and summary["finished"] > 350 and len(summary["teams"]) > 100
    per_league = dict(rows(path, "SELECT e.sport_key, COUNT(*) FROM events e JOIN results r ON r.event_id = e.event_id GROUP BY 1"))
    assert set(per_league) == set(demo_data.ROSTERS) and min(per_league.values()) >= 40
    # every finished game was priced at least twice before it started
    assert rows(path, "SELECT COUNT(*) FROM (SELECT p.event_id FROM pregame_odds p JOIN results r ON r.event_id = p.event_id "
                      "GROUP BY p.event_id HAVING COUNT(DISTINCT p.pulled_at) < 2)") == [(0,)]
    assert rows(path, "SELECT COUNT(*) FROM results WHERE home_score < 0 OR away_score < 0") == [(0,)]


def test_favorites_usually_win_and_upsets_overtime_and_draws_all_happen(demo_db):
    with closing(sqlite3.connect(f"file:{demo_db[0].as_posix()}?mode=ro", uri=True)) as conn:
        games = stats.prepare(dashboard.finished(conn))
    favorite_won = sum(g["winner"] == g["favorite"] for g in games) / len(games)
    assert 0.50 < favorite_won < 0.72
    assert any(g["winner"] not in ("draw", g["favorite"]) for g in games)             # an upset
    assert any(g["status"] == "FINAL_OT" for g in games) and any(g["winner"] == "draw" for g in games)
    soccer_goals = [g["home_score"] + g["away_score"] for g in games if g["sport_key"].startswith("soccer_")]
    assert 2.2 < sum(soccer_goals) / len(soccer_goals) < 3.4                          # a believable number of goals


# ---------- the page ----------

def test_the_page_says_demo_fake_data_at_the_top(page):
    body = page.split("<main>")[1]
    assert body.lstrip().startswith('<div class="banner" role="note"><strong>DEMO: fake data.</strong>')
    assert "<title>Odds Bot Dashboard (DEMO)</title>" in page
    assert "randomly generated" in page and "none of it is real odds or results" in page


def test_the_demo_footer_does_not_claim_the_data_is_licensed_or_private(page):
    assert "Demo page: every number on it is synthetic" in page
    assert "licensed" not in page and "odds-history-data" not in page and "ODDS_API_KEY" not in page


def test_every_section_of_the_demo_is_filled_in(page):
    assert 'class="empty"' not in page
    for title in ("Coming up", "Recent results", "Biggest upsets", "Do favorites win", "Which sportsbooks pay the most",
                  "Line movement", "Home advantage", "Over / under", "Point spreads", "Soccer draws",
                  "Rest and back-to-backs", "Coverage by league"):
        assert title in page, title


def test_a_normal_dashboard_has_no_banner(demo_db):
    plain = dashboard.build(demo_db[0], 48, now=demo_data.DEMO_NOW)
    assert '<div class="banner"' not in plain and "DEMO" not in plain.split("<style>")[0]
    assert "Contains licensed odds data" in plain


def test_making_the_page_prints_nothing(capsys):
    make_demo.make_page()
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_the_command_writes_the_page_with_unix_line_endings_and_a_nojekyll_file(tmp_path):
    out = tmp_path / "site" / "index.html"
    make_demo.main(["--out", str(out)])
    written = out.read_bytes()
    assert b"DEMO: fake data." in written and b"\r\n" not in written
    assert (tmp_path / "site" / ".nojekyll").exists()


# ---------- the committed page ----------

def test_the_committed_demo_page_is_the_one_the_generator_makes(page):
    committed = ROOT / "docs" / "index.html"
    assert committed.exists(), "docs/index.html is missing: run  python scripts/make_demo.py"
    assert committed.read_text(encoding="utf-8") == page, (
        "docs/index.html is out of date: run  python scripts/make_demo.py  and commit the result")
    assert (ROOT / "docs" / ".nojekyll").exists()
