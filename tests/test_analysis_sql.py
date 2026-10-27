"""Tests for analysis/sql/game_lines.sql, using a small database with hand-checked answers."""

import sqlite3
from pathlib import Path

import pytest

import results
import storage
from helpers import book, game, outcome

SQL = (Path(__file__).parent.parent / "analysis" / "sql" / "game_lines.sql").read_text(encoding="utf-8")
PULL = "2026-10-26T13:00:00Z"            # a morning pull, before every game below
LIVE = "2026-10-27T00:40:00Z"            # after the first game started: live odds


def nhl_game(event_id, home, away, start, home_prices, over_under_line, totals_books=("A", "B")):
    books = []
    for (name, home_price, away_price), line_point in zip(zip(totals_books, *home_prices), over_under_line):
        books.append(book(name, h2h=[outcome(home, home_price), outcome(away, away_price)],
                          totals=[outcome("Over", -110, line_point), outcome("Under", -110, line_point)]))
    return game(home, away, start=start, books=books, game_id=event_id)


@pytest.fixture
def conn():
    connection = storage.connect(storage.db_path())
    sport = "icehockey_nhl"

    # Game 1: the home team is the underdog (+150 / +140). Lines: 6.5, 6.5. Final 4-2 (total 6: under).
    storage.insert_snapshot(connection, sport, [nhl_game("g1", "Rangers", "Kings", "2026-10-27T00:00:00Z",
                            ([150, 140], [-170, -160]), [6.5, 6.5])], PULL)
    # Game 2: the home team is the favorite (-200 / -190). Lines: 5.5, 5.5, then 6.0 from a third book. Final 5-2 (over 5.5).
    g2 = nhl_game("g2", "Bruins", "Sharks", "2026-10-27T01:00:00Z", ([-200, -190], [170, 160]), [5.5, 5.5])
    g2["bookmakers"].append(book("C", h2h=[outcome("Bruins", -195), outcome("Sharks", 165)],
                                 totals=[outcome("Over", -110, 6.0), outcome("Under", -110, 6.0)]))
    storage.insert_snapshot(connection, sport, [g2], PULL)
    # Game 3: line 6.0 and the score lands exactly on it: a push.
    storage.insert_snapshot(connection, sport, [nhl_game("g3", "Flames", "Oilers", "2026-10-27T02:00:00Z",
                            ([100, 100], [-120, -120]), [6.0, 6.0])], PULL)
    # Game 4: no result yet, so it must not appear.
    storage.insert_snapshot(connection, sport, [nhl_game("g4", "Jets", "Wild", "2026-10-27T03:00:00Z",
                            ([100, 100], [-120, -120]), [6.5, 6.5])], PULL)
    # A later LIVE snapshot of game 1 with crazy prices: must be ignored.
    storage.insert_snapshot(connection, sport, [nhl_game("g1", "Rangers", "Kings", "2026-10-27T00:00:00Z",
                            ([-5000, -5000], [2500, 2500]), [1.5, 1.5])], LIVE)
    # An NFL game for the spread.
    nfl = game("Eagles", "Cowboys", start="2026-10-27T00:15:00Z", game_id="n1", books=[
        book(name, h2h=[outcome("Eagles", -130), outcome("Cowboys", 110)],
             spreads=[outcome("Eagles", -110, point), outcome("Cowboys", -110, -point)])
        for name, point in (("A", -2.5), ("B", -2.5), ("C", -3.0))])
    storage.insert_snapshot(connection, "americanfootball_nfl", [nfl], PULL)

    def final(sport_key, home, away, start, h, a, status="FINAL"):
        return {"source_id": home, "start_time": start, "home": home, "away": away,
                "home_score": h, "away_score": a, "status": status}
    results.apply_payload(connection, {"sport_key": sport, "source": "test", "fetched_at": "2026-10-27T12:00:00Z", "games": [
        final(sport, "Rangers", "Kings", "2026-10-27T00:00:00Z", 4, 2),
        final(sport, "Bruins", "Sharks", "2026-10-27T01:00:00Z", 5, 2, "FINAL_OT"),
        final(sport, "Flames", "Oilers", "2026-10-27T02:00:00Z", 3, 3),
    ]})
    results.apply_payload(connection, {"sport_key": "americanfootball_nfl", "source": "test", "fetched_at": "2026-10-27T12:00:00Z",
                          "games": [final("nfl", "Eagles", "Cowboys", "2026-10-27T00:15:00Z", 21, 38)]})
    yield connection
    connection.close()


def rows(conn):
    conn.row_factory = sqlite3.Row
    return {r["event_id"]: dict(r) for r in conn.execute(SQL)}


def test_only_finished_games_with_pregame_odds_appear(conn):
    assert sorted(rows(conn)) == ["g1", "g2", "g3", "n1"]          # g4 has no result


def test_home_underdog_and_win_flags(conn):
    r = rows(conn)
    assert (r["g1"]["home_underdog"], r["g1"]["home_won"]) == (1, 1)     # an upset
    assert (r["g2"]["home_underdog"], r["g2"]["home_won"]) == (0, 1)     # the favorite won
    assert (r["n1"]["home_underdog"], r["n1"]["home_won"]) == (0, 0)     # Eagles favored, lost 21-38


def test_consensus_probability_is_the_average_across_books(conn):
    g1 = rows(conn)["g1"]
    assert g1["home_prob"] == pytest.approx((100 / 250 + 100 / 240) / 2)     # +150 and +140
    assert g1["away_prob"] == pytest.approx((170 / 270 + 160 / 260) / 2)     # -170 and -160
    assert g1["moneyline_books"] == 2


def test_live_odds_taken_after_kickoff_are_ignored(conn):
    g1 = rows(conn)["g1"]
    assert g1["moneyline_pulled_at"] == PULL
    assert g1["total_line"] == 6.5                    # not the 1.5 from the live snapshot


def test_total_line_is_the_most_common_one(conn):
    assert rows(conn)["g2"]["total_line"] == 5.5      # two books at 5.5 beat one at 6.0


def test_over_under_and_push(conn):
    r = rows(conn)
    assert (r["g1"]["total_points"], r["g1"]["went_over"]) == (6, 0)        # 6 < 6.5
    assert (r["g2"]["total_points"], r["g2"]["went_over"]) == (7, 1)        # 7 > 5.5
    assert (r["g3"]["total_points"], r["g3"]["went_over"]) == (6, None)     # exactly 6.0: a push


def test_home_spread_and_how_the_game_ended(conn):
    r = rows(conn)
    assert r["n1"]["home_spread"] == -2.5                                   # two books beat one at -3.0
    assert r["g1"]["home_spread"] is None and r["n1"]["total_line"] is None  # markets that were not offered
    assert r["g2"]["status"] == "FINAL_OT"


def test_the_example_question_can_be_answered_with_plain_sql(conn):
    # "How often do home underdogs win?" for the NHL, using the query's output.
    # Home underdogs: game 1 (won 4-2) and game 3 (+100 vs -120, ended 3-3, so not a win).
    answer = conn.execute(f"SELECT COUNT(*), SUM(home_won) FROM ({SQL.rstrip().rstrip(';')}) "
                          "WHERE sport_key = 'icehockey_nhl' AND home_underdog = 1").fetchone()
    assert tuple(answer) == (2, 1)


# ---------- the pandas helpers (only run where the analysis tools are installed) ----------

def test_load_opens_the_database_read_only(tmp_path, conn):
    pytest.importorskip("pandas")
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "analysis"))
    import load
    conn.commit()
    reader = load.connect(storage.db_path())
    with pytest.raises(sqlite3.OperationalError):
        reader.execute("DELETE FROM odds")
    reader.close()
    games = load.game_lines(storage.db_path())
    assert len(games) == 4 and {"game_date", "home_underdog", "went_over"} <= set(games.columns)
