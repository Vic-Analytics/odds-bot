"""Tests for final scores: parsing each source, saving files, matching to games.

Fake data and small trimmed copies of real responses only: no network, no credits.
"""

import json
import subprocess
import sys
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
import sqlite3

import names
import results
import storage
from config import SPORTS
from helpers import book, game, outcome

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------- reading each source ----------

def test_espn_nfl_final_game_is_normalized():
    [g] = results.parse_espn(load("espn_nfl.json"))
    assert g == {"source_id": "401873009", "start_time": "2026-10-27T00:15:00Z",   # '00:15Z' gained its seconds
                 "home": "Philadelphia Eagles", "away": "Dallas Cowboys",
                 "home_score": 21, "away_score": 38, "status": "FINAL"}


def test_espn_soccer_status_says_full_time():
    [g] = results.parse_espn(load("espn_soccer.json"))
    assert (g["home"], g["away"], g["home_score"], g["away_score"], g["status"]) == ("Sevilla", "Osasuna", 2, 0, "FULL_TIME")


def test_espn_skips_games_that_are_not_finished_or_not_played():
    payload = load("espn_nhl.json")
    payload["events"][0]["status"]["type"].update(completed=False, name="STATUS_IN_PROGRESS")
    payload["events"][1]["status"]["type"].update(completed=True, name="STATUS_POSTPONED")
    assert [g["source_id"] for g in results.parse_espn(payload)] == ["401892584"]


def test_espn_keeps_extra_time_and_penalty_endings_visible():
    payload = load("espn_soccer.json")
    payload["events"][0]["status"]["type"]["name"] = "STATUS_FINAL_PEN"
    assert results.parse_espn(payload)[0]["status"] == "FINAL_PEN"


def test_espn_skips_missing_scores_and_malformed_events(capsys):
    payload = load("espn_nfl.json")
    payload["events"].append({"id": "x", "status": {"type": {"completed": True, "name": "STATUS_FINAL"}}})   # no competitions
    no_score = json.loads(json.dumps(payload["events"][0]))
    no_score["id"] = "y"
    no_score["competitions"][0]["competitors"][0]["score"] = None
    payload["events"].append(no_score)
    assert [g["source_id"] for g in results.parse_espn(payload)] == ["401873009"]
    assert "[results] skipped one ESPN event" in capsys.readouterr().err


def test_nhl_feed_reports_how_each_game_ended():
    games = results.parse_nhl(load("nhl_score.json"))
    assert [(g["home"], g["away"], g["home_score"], g["away_score"], g["status"]) for g in games] == [
        ("Rangers", "Kings", 3, 6, "FINAL"),
        ("Flames", "Maple Leafs", 5, 2, "FINAL"),
        ("Oilers", "Red Wings", 3, 4, "FINAL_SO"),         # a shootout
    ]


def test_nhl_skips_games_still_in_progress_and_marks_overtime():
    payload = load("nhl_score.json")
    payload["games"][0]["gameState"] = "LIVE"
    payload["games"][1]["gameOutcome"] = {"lastPeriodType": "OT"}
    games = results.parse_nhl(payload)
    assert [g["source_id"] for g in games] == ["2026020186", "2026020187"]
    assert games[0]["status"] == "FINAL_OT"


def test_nhl_uses_the_city_when_the_feed_gives_one():
    payload = {"games": [{"id": 1, "gameState": "OFF", "startTimeUTC": "2026-10-26T23:00:00Z",
                          "homeTeam": {"placeName": {"default": "Utah"}, "name": {"default": "Mammoth"}, "score": 2},
                          "awayTeam": {"name": {"default": "Kings"}, "score": 1}}]}
    [g] = results.parse_nhl(payload)
    assert (g["home"], g["away"]) == ("Utah Mammoth", "Kings")


def test_mlb_final_game_is_normalized():
    [g] = results.parse_mlb(load("mlb_schedule.json"))
    assert (g["home"], g["away"], g["home_score"], g["away_score"], g["status"]) == ("Tampa Bay Rays", "Milwaukee Brewers", 1, 10, "FINAL")


def test_mlb_skips_unfinished_and_postponed_games():
    payload = load("mlb_schedule.json")
    base = payload["dates"][0]["games"][0]
    live = json.loads(json.dumps(base)); live["gamePk"] = 1; live["status"]["abstractGameState"] = "Live"
    postponed = json.loads(json.dumps(base)); postponed["gamePk"] = 2; postponed["status"]["detailedState"] = "Postponed"
    payload["dates"][0]["games"] += [live, postponed]
    assert [g["source_id"] for g in results.parse_mlb(payload)] == ["849804"]


# ---------- fetching ----------

class FakeResponse:
    def __init__(self, payload, ok=True, status_code=200):
        self._payload, self.ok, self.status_code = payload, ok, status_code

    def json(self):
        return self._payload


def test_each_source_is_called_with_the_right_address_and_date(monkeypatch):
    calls = []
    monkeypatch.setattr(results, "request_with_retries",
                        lambda method, url, **kw: calls.append((url, kw.get("params"))) or FakeResponse({}))
    day = date(2026, 10, 26)
    results.fetch_day("espn", "hockey/nhl", day)
    results.fetch_day("nhl", None, day)
    results.fetch_day("mlb", None, day)
    assert calls == [
        ("https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard", {"dates": "20261026"}),
        ("https://api-web.nhle.com/v1/score/2026-10-26", None),
        ("https://statsapi.mlb.com/api/v1/schedule", {"sportId": 1, "date": "2026-10-26"}),
    ]


def test_a_http_error_is_reported_clearly(monkeypatch):
    monkeypatch.setattr(results, "request_with_retries", lambda *a, **k: FakeResponse({}, ok=False, status_code=403))
    with pytest.raises(RuntimeError, match="espn returned HTTP 403"):
        results.fetch_day("espn", "hockey/nhl", date(2026, 10, 26))


def test_no_custom_user_agent_is_sent(monkeypatch):
    # ESPN rejected a custom User-Agent label once; the library default works.
    seen = {}
    monkeypatch.setattr(results, "request_with_retries", lambda method, url, **kw: seen.update(kw) or FakeResponse({}))
    results.fetch_day("espn", "hockey/nhl", date(2026, 10, 26))
    assert "headers" not in seen


def test_collect_removes_a_game_listed_under_two_dates(monkeypatch):
    same_game = load("espn_nfl.json")
    monkeypatch.setattr(results, "fetch_day", lambda *a: results.parse_espn(same_game))
    monkeypatch.setattr(results.time, "sleep", lambda s: None)
    source, games = results.collect("americanfootball_nfl", [date(2026, 10, 25), date(2026, 10, 26)])
    assert source == "espn" and len(games) == 1


def test_every_league_has_a_score_source_except_mma():
    missing = {name for name, key in SPORTS.items() if key not in results.SOURCES}
    assert missing == {"UFC / MMA"}
    assert set(results.SOURCES) <= set(SPORTS.values())


# ---------- saving the files ----------

def test_results_file_is_saved_in_a_compact_dated_file():
    games = results.parse_nhl(load("nhl_score.json"))
    path = results.save_results_file("icehockey_nhl", "nhl", games, "2026-10-27T12:37:05Z")
    assert path == storage.data_dir() / "results_raw" / "2026-10-27" / "icehockey_nhl__123705Z.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["fetched_at"] == "2026-10-27T12:37:05Z" and len(saved["games"]) == 3
    assert not list(path.parent.glob("*.tmp"))
    assert results.save_results_file("icehockey_nhl", "nhl", games, "2026-10-27T12:37:05Z") is None   # never overwritten


# ---------- matching scores to games in the database ----------

def db_with_events(*events):
    """A database holding the given (sport_key, home, away, start) events, as the odds bot would have saved them."""
    conn = storage.connect(storage.db_path())
    for i, (sport_key, home, away, start) in enumerate(events):
        storage.insert_snapshot(conn, sport_key, [game(home, away, start=start, game_id=f"evt{i}", books=[
            book("DraftKings", h2h=[outcome(home, -110), outcome(away, 100)])])], f"2026-10-26T13:00:0{i}Z")
    return conn


def payload(sport_key, source, games, fetched_at="2026-10-27T12:37:05Z"):
    return {"sport_key": sport_key, "source": source, "fetched_at": fetched_at, "games": games}


def result_rows(conn):
    return conn.execute("SELECT event_id, home_score, away_score, completed, source, updated_at, status "
                        "FROM results ORDER BY event_id").fetchall()


def test_nhl_nickname_only_names_are_matched_to_full_names():
    conn = db_with_events(("icehockey_nhl", "New York Rangers", "Los Angeles Kings", "2026-10-26T23:00:00Z"))
    outcome_ = results.apply_payload(conn, payload("icehockey_nhl", "nhl", results.parse_nhl(load("nhl_score.json"))))
    assert outcome_["matched"] == 1 and len(outcome_["unmatched"]) == 2     # the other two games were never pulled
    assert result_rows(conn) == [("evt0", 3, 6, 1, "nhl", "2026-10-27T12:37:05Z", "FINAL")]


def test_a_result_listed_with_home_and_away_swapped_keeps_the_scores_with_the_right_team():
    conn = db_with_events(("americanfootball_nfl", "Philadelphia Eagles", "Dallas Cowboys", "2026-10-27T00:15:00Z"))
    swapped = [{"source_id": "1", "start_time": "2026-10-27T00:15:00Z", "home": "Dallas Cowboys", "away": "Philadelphia Eagles",
                "home_score": 38, "away_score": 21, "status": "FINAL"}]
    results.apply_payload(conn, payload("americanfootball_nfl", "espn", swapped))
    assert result_rows(conn)[0][1:3] == (21, 38)          # the Eagles (home in our data) scored 21


def test_soccer_names_match_through_the_aliases():
    conn = db_with_events(("soccer_italy_serie_a", "Inter Milan", "Fiorentina", "2026-10-25T11:30:00Z"),
                          ("soccer_uefa_europa_conference_league", "FC Kairat", "Panathinaikos FC", "2026-10-22T14:30:00Z"))
    games = [
        {"source_id": "1", "start_time": "2026-10-25T11:30:00Z", "home": "Internazionale", "away": "Fiorentina",
         "home_score": 2, "away_score": 1, "status": "FULL_TIME"},
    ]
    assert results.apply_payload(conn, payload("soccer_italy_serie_a", "espn", games))["matched"] == 1
    cup = [{"source_id": "2", "start_time": "2026-10-22T14:30:00Z", "home": "Kairat Almaty", "away": "Panathinaikos",
            "home_score": 1, "away_score": 5, "status": "FULL_TIME"}]
    assert results.apply_payload(conn, payload("soccer_uefa_europa_conference_league", "espn", cup))["matched"] == 1


def test_a_doubleheader_matches_each_game_to_its_own_start_time():
    conn = db_with_events(("baseball_mlb", "Tampa Bay Rays", "Boston Red Sox", "2026-10-26T17:00:00Z"),
                          ("baseball_mlb", "Tampa Bay Rays", "Boston Red Sox", "2026-10-26T23:00:00Z"))
    games = [
        {"source_id": "a", "start_time": "2026-10-26T23:05:00Z", "home": "Tampa Bay Rays", "away": "Boston Red Sox",
         "home_score": 5, "away_score": 4, "status": "FINAL"},
        {"source_id": "b", "start_time": "2026-10-26T17:02:00Z", "home": "Tampa Bay Rays", "away": "Boston Red Sox",
         "home_score": 1, "away_score": 0, "status": "FINAL"},
    ]
    results.apply_payload(conn, payload("baseball_mlb", "mlb", games))
    assert result_rows(conn) == [("evt0", 1, 0, 1, "mlb", "2026-10-27T12:37:05Z", "FINAL"),    # the 17:00 game
                                 ("evt1", 5, 4, 1, "mlb", "2026-10-27T12:37:05Z", "FINAL")]    # the 23:00 game


def test_unknown_teams_wrong_league_and_far_away_start_times_are_not_matched():
    conn = db_with_events(("icehockey_nhl", "New York Rangers", "Los Angeles Kings", "2026-10-26T23:00:00Z"))
    base = {"source_id": "1", "home": "Rangers", "away": "Kings", "home_score": 3, "away_score": 6, "status": "FINAL"}
    cases = [
        ("icehockey_nhl", dict(base, start_time="2026-10-26T23:00:00Z", home="Bruins")),        # unknown team
        ("icehockey_nhl", dict(base, start_time="2026-10-28T23:00:00Z")),                        # two days later
        ("basketball_nba", dict(base, start_time="2026-10-26T23:00:00Z")),                       # a different league
    ]
    for sport_key, g in cases:
        assert results.apply_payload(conn, payload(sport_key, "x", [g]))["matched"] == 0
    assert result_rows(conn) == []


def test_applying_twice_gives_one_row_and_a_later_file_wins():
    conn = db_with_events(("icehockey_nhl", "New York Rangers", "Los Angeles Kings", "2026-10-26T23:00:00Z"))
    g = {"source_id": "1", "start_time": "2026-10-26T23:00:00Z", "home": "Rangers", "away": "Kings",
         "home_score": 3, "away_score": 5, "status": "FINAL"}
    results.apply_payload(conn, payload("icehockey_nhl", "nhl", [g]))
    results.apply_payload(conn, payload("icehockey_nhl", "nhl", [g]))
    assert len(result_rows(conn)) == 1
    corrected = dict(g, away_score=6, status="FINAL_OT")
    results.apply_payload(conn, payload("icehockey_nhl", "nhl", [corrected], fetched_at="2026-10-28T12:37:00Z"))
    [row] = result_rows(conn)
    assert row[1:3] == (3, 6) and row[5:] == ("2026-10-28T12:37:00Z", "FINAL_OT")


# ---------- same-team rules ----------

def test_us_league_names_match_on_the_nickname():
    assert names.same_team("icehockey_nhl", "Kings", "Los Angeles Kings")
    assert names.same_team("basketball_nba", "LA Clippers", "Los Angeles Clippers")
    assert names.same_team("baseball_mlb", "Athletics", "Oakland Athletics")
    assert not names.same_team("icehockey_nhl", "Kings", "Los Angeles Rams")
    assert not names.same_team("americanfootball_nfl", "New York Giants", "New York Jets")
    assert not names.same_team("basketball_nba", "Kings", "")


def test_soccer_names_match_through_aliases_and_shortened_forms():
    assert names.same_team("soccer_epl", "Brighton & Hove Albion", "Brighton and Hove Albion")
    assert names.same_team("soccer_germany_bundesliga", "FC Cologne", "1. FC Köln")
    assert names.same_team("soccer_uefa_champs_league", "Sporting CP", "Sporting Lisbon")
    assert names.same_team("soccer_spain_la_liga", "Mainz", "Mainz 05") is True
    assert not names.same_team("soccer_epl", "Manchester City", "Manchester United")
    assert not names.same_team("soccer_usa_mls", "New York City FC", "New York Red Bulls")
    assert not names.same_team("soccer_epl", "Ajax", "Ajax Amsterdam FC Reserves")


# ---------- rebuilding from the saved files ----------

def write_results_file(sport_key, fetched_at, games, source="nhl"):
    path = storage.raw_path_for(sport_key, fetched_at, folder="results_raw")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload(sport_key, source, games, fetched_at)), encoding="utf-8")
    return path


def test_rebuild_attaches_every_saved_file_and_skips_broken_ones():
    conn = db_with_events(("icehockey_nhl", "New York Rangers", "Los Angeles Kings", "2026-10-26T23:00:00Z"))
    conn.close()
    games = results.parse_nhl(load("nhl_score.json"))
    write_results_file("icehockey_nhl", "2026-10-27T12:37:05Z", games)
    bad = storage.results_dir() / "2026-10-27" / "icehockey_nhl__999999Z.json"
    bad.write_text("not json")
    summary = results.rebuild_results(storage.db_path(), storage.results_dir())
    assert summary == {"files": 1, "matched": 1, "unmatched": 2, "skipped_files": 1}


def test_rebuild_with_no_results_folder_does_nothing(tmp_path):
    assert results.rebuild_results(tmp_path / "x.db", tmp_path / "missing") == \
        {"files": 0, "matched": 0, "unmatched": 0, "skipped_files": 0}


def test_the_backfill_script_rebuilds_odds_and_scores_together(tmp_path):
    storage.save_snapshot("icehockey_nhl", [game("New York Rangers", "Los Angeles Kings", start="2026-10-26T23:00:00Z", game_id="evt0",
                          books=[book("DraftKings", h2h=[outcome("New York Rangers", -110), outcome("Los Angeles Kings", 100)])])],
                          pulled_at="2026-10-26T13:00:00Z")
    write_results_file("icehockey_nhl", "2026-10-27T12:37:05Z", results.parse_nhl(load("nhl_score.json")))
    db = tmp_path / "rebuilt.db"
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "backfill_from_raw.py"), "--rebuild", "--db", str(db),
                          "--raw-dir", str(storage.data_dir() / "raw"), "--results-dir", str(storage.results_dir())],
                         capture_output=True, text=True, cwd=tmp_path)
    assert run.returncode == 0, run.stderr
    assert "1 matched to games" in run.stdout
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("SELECT home_score, away_score, status FROM results").fetchall() == [(3, 6, "FINAL")]


# ---------- the command line ----------

@pytest.fixture
def fake_sources(monkeypatch):
    """results.fetch_day returns canned games per league; one league can be made to fail."""
    monkeypatch.setattr(results.time, "sleep", lambda s: None)
    state = {"fail": set()}

    def fetch(source, league, day):
        if league in state["fail"] or source in state["fail"]:
            raise RuntimeError(f"{source} returned HTTP 500 for {day}")
        parsers = {"nhl": ("nhl_score.json", results.parse_nhl), "mlb": ("mlb_schedule.json", results.parse_mlb)}
        if source in parsers:
            name, parser = parsers[source]
            return parser(load(name))
        return results.parse_espn(load("espn_nfl.json" if league.startswith("football") else "espn_soccer.json"))

    monkeypatch.setattr(results, "fetch_day", fetch)
    return state


def test_files_only_saves_files_and_never_creates_the_database(fake_sources, capsys):
    assert results.main(["--files-only", "--date", "2026-10-26", "--sports", "NHL,NFL"]) == 0
    assert not storage.db_path().exists()
    saved = sorted(p.name.split("__")[0] for p in storage.results_dir().glob("*/*.json"))
    assert saved == ["americanfootball_nfl", "icehockey_nhl"]
    assert "NHL: 3 final game(s) saved" in capsys.readouterr().out


def test_normal_run_also_attaches_scores_to_the_database(fake_sources, capsys):
    db_with_events(("icehockey_nhl", "New York Rangers", "Los Angeles Kings", "2026-10-26T23:00:00Z")).close()
    assert results.main(["--date", "2026-10-26", "--sports", "NHL"]) == 0
    assert "1 matched to games in the database" in capsys.readouterr().out
    with closing(sqlite3.connect(storage.db_path())) as conn:
        assert conn.execute("SELECT home_score, away_score FROM results").fetchall() == [(3, 6)]


def test_one_failing_league_does_not_stop_the_others_but_the_run_reports_failure(fake_sources, capsys):
    fake_sources["fail"].add("hockey/nhl")
    fake_sources["fail"].add("nhl")
    code = results.main(["--files-only", "--date", "2026-10-26", "--sports", "NHL,NFL,MLB"])
    out = capsys.readouterr()
    assert code == 1
    assert "NHL: FAILED" in out.out and "NFL: 1 final game(s) saved" in out.out and "MLB: 1 final game(s) saved" in out.out
    assert "1 league(s) failed" in out.err


def test_mma_is_skipped_with_a_message_and_unknown_leagues_are_refused(fake_sources, capsys):
    assert results.main(["--files-only", "--sports", "UFC / MMA"]) == 0
    assert "no free score source" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="Unknown league"):
        results.main(["--sports", "Quidditch"])


def test_days_option_covers_a_range_ending_on_the_chosen_date(fake_sources, monkeypatch):
    asked = []
    monkeypatch.setattr(results, "fetch_day", lambda source, league, day: asked.append(day) or [])
    results.main(["--files-only", "--date", "2026-10-26", "--days", "3", "--sports", "NHL"])
    assert asked == [date(2026, 10, 24), date(2026, 10, 25), date(2026, 10, 26)]


def test_a_doubleheaders_second_game_never_overwrites_the_first_when_it_was_not_pulled():
    # Only the 17:00 game is in the database; the 23:00 game was never pulled.
    conn = db_with_events(("baseball_mlb", "Tampa Bay Rays", "Boston Red Sox", "2026-10-26T17:00:00Z"))
    games = [
        {"source_id": "b", "start_time": "2026-10-26T23:05:00Z", "home": "Tampa Bay Rays", "away": "Boston Red Sox",
         "home_score": 5, "away_score": 4, "status": "FINAL"},          # listed FIRST on purpose
        {"source_id": "a", "start_time": "2026-10-26T17:02:00Z", "home": "Tampa Bay Rays", "away": "Boston Red Sox",
         "home_score": 1, "away_score": 0, "status": "FINAL"},
    ]
    outcome_ = results.apply_payload(conn, payload("baseball_mlb", "mlb", games))
    assert outcome_["matched"] == 1 and len(outcome_["unmatched"]) == 1
    assert result_rows(conn)[0][1:3] == (1, 0)                          # the 17:00 game's own score


def test_the_closest_start_time_wins_whatever_order_the_games_arrive_in():
    conn = db_with_events(("baseball_mlb", "Tampa Bay Rays", "Boston Red Sox", "2026-10-26T17:00:00Z"),
                          ("baseball_mlb", "Tampa Bay Rays", "Boston Red Sox", "2026-10-26T20:30:00Z"))
    late = {"source_id": "b", "start_time": "2026-10-26T20:32:00Z", "home": "Tampa Bay Rays", "away": "Boston Red Sox",
            "home_score": 7, "away_score": 2, "status": "FINAL"}
    early = {"source_id": "a", "start_time": "2026-10-26T17:01:00Z", "home": "Tampa Bay Rays", "away": "Boston Red Sox",
             "home_score": 3, "away_score": 3, "status": "FINAL"}
    for order in ([late, early], [early, late]):
        conn.execute("DELETE FROM results")
        results.apply_payload(conn, payload("baseball_mlb", "mlb", order))
        assert [(r[0], r[1], r[2]) for r in result_rows(conn)] == [("evt0", 3, 3), ("evt1", 7, 2)]


def test_a_start_time_three_hours_off_is_not_a_match():
    conn = db_with_events(("icehockey_nhl", "New York Rangers", "Los Angeles Kings", "2026-10-26T23:00:00Z"))
    g = {"source_id": "1", "start_time": "2026-10-27T02:10:00Z", "home": "Rangers", "away": "Kings",
         "home_score": 3, "away_score": 6, "status": "FINAL"}
    assert results.apply_payload(conn, payload("icehockey_nhl", "nhl", [g]))["matched"] == 0


def test_one_game_listed_twice_by_the_source_only_fills_one_event():
    conn = db_with_events(("icehockey_nhl", "New York Rangers", "Los Angeles Kings", "2026-10-26T23:00:00Z"))
    exact = {"source_id": "1", "start_time": "2026-10-26T23:02:00Z", "home": "Rangers", "away": "Kings",
             "home_score": 3, "away_score": 6, "status": "FINAL"}
    duplicate = dict(exact, source_id="2", start_time="2026-10-26T23:45:00Z", home_score=9, away_score=9)
    outcome_ = results.apply_payload(conn, payload("icehockey_nhl", "nhl", [duplicate, exact]))
    assert outcome_["matched"] == 1 and len(outcome_["unmatched"]) == 1
    assert result_rows(conn)[0][1:3] == (3, 6)                      # the closer listing won


def test_overlapping_candidates_are_resolved_by_closest_start_time_first():
    # Two events 90 minutes apart, so each score is a possible match for both.
    conn = db_with_events(("baseball_mlb", "Tampa Bay Rays", "Boston Red Sox", "2026-10-26T17:00:00Z"),
                          ("baseball_mlb", "Tampa Bay Rays", "Boston Red Sox", "2026-10-26T18:30:00Z"))
    x = {"source_id": "x", "start_time": "2026-10-26T17:05:00Z", "home": "Tampa Bay Rays", "away": "Boston Red Sox",
         "home_score": 1, "away_score": 0, "status": "FINAL"}
    y = {"source_id": "y", "start_time": "2026-10-26T18:20:00Z", "home": "Tampa Bay Rays", "away": "Boston Red Sox",
         "home_score": 8, "away_score": 7, "status": "FINAL"}
    for order in ([x, y], [y, x]):
        conn.execute("DELETE FROM results")
        results.apply_payload(conn, payload("baseball_mlb", "mlb", order))
        assert [(r[0], r[1], r[2]) for r in result_rows(conn)] == [("evt0", 1, 0), ("evt1", 8, 7)]
