"""Tests for analysis/stats.py. Every expected number was worked out by hand."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "analysis"))

import stats


def game(event_id="e", sport="icehockey_nhl", home_prob=0.55, away_prob=0.55, draw_prob=None,
         score=(3, 1), status="FINAL", total_line=None, home_spread=None):
    return {"event_id": event_id, "sport_key": sport, "home_prob": home_prob, "away_prob": away_prob,
            "draw_prob": draw_prob, "home_score": score[0], "away_score": score[1], "status": status,
            "total_line": total_line, "home_spread": home_spread, "commence_time": "2026-10-27T00:00:00Z"}


def prep(*rows):
    return stats.prepare(list(rows))


# ---------- prepare ----------

def test_the_margin_is_removed_so_chances_add_up_to_100():
    g = prep(game(home_prob=0.4, away_prob=0.4, draw_prob=0.3))[0]          # adds up to 1.1
    assert g["p_home"] == pytest.approx(0.4 / 1.1)
    assert g["p_draw"] == pytest.approx(0.3 / 1.1)
    assert g["p_home"] + g["p_away"] + g["p_draw"] == pytest.approx(1.0)


def test_winner_and_extra_time():
    won, tie, long_game, away = prep(game(score=(3, 1)), game(score=(2, 2)),
                                     game(score=(2, 1), status="FINAL_AET"), game(score=(0, 1)))
    assert [g["winner"] for g in (won, tie, long_game, away)] == ["home", "draw", "draw", "away"]
    assert [g["regulation"] for g in (won, tie, long_game, away)] == [True, True, False, True]


def test_games_without_a_moneyline_are_dropped():
    assert prep(game(home_prob=None)) == []


# ---------- 1. favorites versus the odds ----------

def test_calibration_buckets():
    rows = stats.calibration(prep(
        game(home_prob=0.55, away_prob=0.45, score=(3, 1)),       # favorite = home 55%, won
        game(home_prob=0.35, away_prob=0.65, score=(3, 1)),       # favorite = away 65%, lost
        game(home_prob=0.55, away_prob=0.45, score=(1, 3))))      # favorite = home 55%, lost
    assert rows[0]["sport_key"] is None                           # "all leagues" comes first
    pooled = {r["bucket"]: r for r in rows if r["sport_key"] is None}
    assert (pooled["50-60%"]["n"], pooled["50-60%"]["actual"]) == (2, 0.5)
    assert pooled["50-60%"]["said"] == pytest.approx(0.55)
    assert (pooled["60-70%"]["n"], pooled["60-70%"]["actual"]) == (1, 0.0)
    assert len([r for r in rows if r["sport_key"] == "icehockey_nhl"]) == 2


def test_a_draw_means_the_favorite_did_not_win():
    rows = stats.calibration(prep(game(home_prob=0.5, away_prob=0.3, draw_prob=0.2, score=(1, 1))))
    assert [r for r in rows if r["sport_key"] is None][0]["actual"] == 0.0


# ---------- 7. home advantage and home underdogs ----------

def test_home_advantage_rates():
    row = stats.home_advantage(prep(game(score=(3, 1)), game(score=(1, 3)), game(score=(2, 2)), game(score=(4, 0))))[0]
    assert (row["n"], row["home"], row["away"], row["draw"]) == (4, 0.5, 0.25, 0.25)


def test_home_underdogs():
    games = prep(game(home_prob=0.40, away_prob=0.60, score=(3, 1)),     # underdog won
                 game(home_prob=0.40, away_prob=0.60, score=(0, 1)),     # underdog lost
                 game(home_prob=0.70, away_prob=0.30, score=(0, 1)))     # home favorite: not counted
    row = stats.home_underdogs(games)[0]
    assert (row["games"], row["dogs"], row["wins"], row["actual"]) == (3, 2, 1, 0.5)
    assert row["said"] == pytest.approx(0.40)


# ---------- 5. totals ----------

def test_totals_over_under_push_and_extra_time_excluded():
    row = stats.totals(prep(
        game(score=(4, 3), total_line=6.5),                       # 7: over
        game(score=(3, 3), total_line=6.0),                       # 6: push
        game(score=(1, 2), total_line=6.5),                       # 3: under
        game(score=(5, 5), total_line=6.5, status="FINAL_AET")))[0]   # extra time: left out
    assert (row["n"], row["over"], row["under"], row["push"]) == (3, 1, 1, 1)
    assert row["over_rate"] == 0.5
    assert row["avg_line"] == pytest.approx(19 / 3)
    assert row["avg_total"] == pytest.approx(16 / 3)


# ---------- 8. spreads ----------

def test_spread_cover_counts():
    row = stats.spreads(prep(
        game(score=(10, 3), home_spread=-3.5),      # home favorite wins by 7: covers
        game(score=(2, 3), home_spread=2.5),        # home underdog loses by 1: covers (+2.5)
        game(score=(6, 3), home_spread=-3.0),       # exactly 3: push
        game(score=(1, 3), home_spread=0.0),        # pick'em, away wins: no favorite, home does not cover
        game(score=(7, 0), home_spread=-2.5)))[0]   # home favorite wins by 7: covers
    assert (row["n"], row["fav"], row["dog"], row["push"]) == (5, 2, 1, 1)     # two favorites covered, one underdog
    assert row["fav_rate"] == pytest.approx(2 / 3)
    assert row["home_rate"] == pytest.approx(3 / 4)                           # home covered 3 of the 4 non-pushes


# ---------- 9. soccer draws ----------

def test_draw_rate_counts_extra_time_as_a_draw_after_90():
    soccer = dict(sport="soccer_epl", home_prob=0.4, away_prob=0.3, draw_prob=0.3)
    rows = stats.draws(prep(game(score=(1, 1), **soccer),
                            game(score=(2, 1), status="FINAL_AET", **soccer),
                            game(score=(2, 0), **soccer),
                            game(score=(0, 1), **soccer)))
    assert rows[0]["n"] == 4 and rows[0]["actual"] == 0.5
    assert rows[0]["said"] == pytest.approx(0.3)                  # these chances already add up to 1.0
    assert stats.draws(prep(game())) == []                        # a sport without draws is not listed


# ---------- 6. rest days ----------

def test_rest_gaps_use_central_calendar_days():
    events = [("a", "basketball_nba", "2026-10-26T23:00:00Z", "Lakers", "Suns"),     # Oct 26, 6 PM Central
              ("b", "basketball_nba", "2026-10-28T03:00:00Z", "Lakers", "Jazz"),     # Oct 27, 10 PM Central: UTC says 2 days, Central says 1
              ("c", "basketball_nba", "2026-10-30T01:00:00Z", "Heat", "Lakers"),     # Oct 29, 8 PM Central: 2 days after b
              ("d", "basketball_nba", "2026-10-30T02:00:00Z", "Bulls", "Nets")]
    gaps = stats.rest_gaps(events)
    assert gaps[("a", "home")] is None                            # first game seen: unknown, never "rested"
    assert gaps[("b", "home")] == 1                               # a back-to-back, by the Central calendar
    assert gaps[("c", "away")] == 2
    assert gaps[("d", "home")] is None


def test_a_doubleheader_is_not_a_back_to_back():
    events = [("a", "baseball_mlb", "2026-10-26T17:00:00Z", "Mets", "Braves"),
              ("b", "baseball_mlb", "2026-10-26T23:00:00Z", "Mets", "Braves")]
    assert stats.rest_gaps(events)[("b", "home")] == 0


def test_rest_effect_and_totals_only_for_leagues_with_a_back_to_back():
    events = [("a", "basketball_nba", "2026-10-26T23:00:00Z", "Lakers", "Suns"),
              ("b", "basketball_nba", "2026-10-27T23:00:00Z", "Lakers", "Jazz"),     # Lakers on a back-to-back
              ("x", "icehockey_nhl", "2026-10-26T23:00:00Z", "Rangers", "Kings")]
    gaps = stats.rest_gaps(events)
    games = prep(game(event_id="a", sport="basketball_nba", score=(100, 90), total_line=190.5),
                 game(event_id="b", sport="basketball_nba", home_prob=0.60, away_prob=0.60, score=(90, 100), total_line=185.5),
                 game(event_id="x", sport="icehockey_nhl"))
    effect = {(r["sport_key"], r["situation"]): r for r in stats.rest_effect(games, gaps)}
    tired = effect[("basketball_nba", "On a back-to-back")]
    assert (tired["n"], tired["actual"]) == (1, 0.0)              # the tired Lakers lost
    assert tired["said"] == pytest.approx(0.5)
    assert not [k for k in effect if k[0] == "icehockey_nhl"]     # a league with no back-to-back is not shown
    totals = {r["situation"]: r for r in stats.rest_totals(games, gaps)}
    assert totals["A team is on a back-to-back"]["n"] == 1
    assert totals["A team is on a back-to-back"]["over_rate"] == 1.0           # 190 > 185.5


# ---------- 2 and 3. sportsbooks ----------

def rows_for(prices, sport="icehockey_nhl", event="e1", outcome="Rangers"):
    return [(sport, event, book, outcome, price) for book, price in prices.items()]


def test_best_and_worst_book_and_the_value_of_shopping():
    books, leagues = stats.book_stats(rows_for({"a": 150, "b": 140, "c": 130}))
    by_book = {b["book"]: b for b in books}
    assert (by_book["a"]["best"], by_book["a"]["worst"]) == (1.0, 0.0)
    assert (by_book["c"]["best"], by_book["c"]["worst"]) == (0.0, 1.0)
    assert books[0]["book"] == "a"                                # the best book is listed first
    # win chances: +150 -> 40.00%, +140 -> 41.67%, +130 -> 43.48%
    assert by_book["a"]["gap"] == pytest.approx((0.4 - (0.4 + 100 / 240 + 100 / 230) / 3) * 100)
    league = leagues[0]
    assert league["n"] == 1
    assert league["avg_range"] == pytest.approx((100 / 230 - 0.4) * 100)
    assert league["avg_gain"] == pytest.approx(10.0)              # best pays 150, the average book pays 140


def test_negative_prices_are_converted_to_payouts():
    _, leagues = stats.book_stats(rows_for({"a": -110, "b": -120, "c": -105}))
    # a winning $100 bet pays 10000/105 = 95.24 at -105, and the three books average (90.91 + 83.33 + 95.24) / 3
    assert leagues[0]["avg_gain"] == pytest.approx(10000 / 105 - (10000 / 110 + 10000 / 120 + 10000 / 105) / 3)


def test_identical_prices_have_no_best_or_worst_book():
    books, leagues = stats.book_stats(rows_for({"a": -110, "b": -110, "c": -110}))
    assert all(b["best"] is None and b["worst"] is None for b in books)
    assert leagues[0]["avg_gain"] == 0 and leagues[0]["avg_range"] == 0


def test_fewer_than_three_books_are_not_compared():
    assert stats.book_stats(rows_for({"a": 150, "b": 100})) == ([], [])


def test_books_per_game():
    rows = rows_for({"a": 1, "b": 2, "c": 3}, event="e1") + rows_for({"a": 1}, event="e2")
    assert stats.books_per_game(rows) == {"icehockey_nhl": 2.0}


# ---------- margin (vig) ----------

def two_sided(book, home, away, event="e1", sport="icehockey_nhl"):
    return [(sport, event, book, "Rangers", home), (sport, event, book, "Kings", away)]


def test_margin_is_how_far_the_chances_add_up_past_100():
    rows = (two_sided("a", 150, -170) + two_sided("b", 140, -160) + two_sided("c", 130, -150))
    result = stats.book_margins(rows)
    # a: +150 is 40.00% and -170 is 62.96%, which add up to 102.96%: a margin of 2.96%
    assert result[0]["book"] == "a"
    assert result[0]["avg_margin"] == pytest.approx((0.4 + 170 / 270 - 1) * 100)
    assert [r["book"] for r in result] == ["a", "b", "c"]          # lowest margin first
    assert (result[0]["lowest"], result[1]["lowest"]) == (1.0, 0.0)


def test_a_book_that_skipped_an_outcome_is_not_compared():
    rows = (two_sided("a", 150, -170) + two_sided("b", 140, -160) + two_sided("c", 130, -150)
            + [("icehockey_nhl", "e1", "d", "Rangers", 500)])      # d only priced one side: its "margin" would be nonsense
    assert "d" not in [r["book"] for r in stats.book_margins(rows)]


def test_margins_need_three_books_per_game():
    assert stats.book_margins(two_sided("a", 150, -170) + two_sided("b", 140, -160)) == []


# ---------- price age ----------

def test_price_age_median_oldest_and_stale_share():
    pulled = "2026-10-28T13:00:00Z"
    rows = [("a", pulled, "2026-10-28T12:50:00Z"),      # 10 minutes old
            ("a", pulled, "2026-10-28T10:00:00Z"),      # 180 minutes old
            ("b", pulled, "2026-10-28T12:59:00Z"),      # 1 minute old
            ("b", pulled, "2026-10-28T13:30:00Z"),      # "updated" after our pull (clock skew): age 0, not negative
            ("c", pulled, None)]                        # no update time: ignored
    result = stats.price_ages(rows)
    assert [r["book"] for r in result] == ["a", "b"]    # the stalest book first, c has nothing to show
    assert (result[0]["median"], result[0]["oldest"], result[0]["stale"]) == (95.0, 180.0, 0.5)
    assert (result[1]["median"], result[1]["oldest"], result[1]["stale"]) == (0.5, 1.0, 0.0)


# ---------- line movement ----------

def snapshot(pulled, home, away, event="e1", sport="icehockey_nhl", draw=None, start="2026-10-27T00:00:00Z"):
    rows = [(sport, event, start, pulled, "Rangers", "Kings", "Rangers", home),
            (sport, event, start, pulled, "Rangers", "Kings", "Kings", away)]
    if draw is not None:
        rows.append((sport, event, start, pulled, "Rangers", "Kings", "Draw", draw))
    return rows


def test_line_move_removes_the_margin_and_finds_the_side_that_gained():
    rows = snapshot("2026-10-26T13:00:00Z", 0.40, 0.62) + snapshot("2026-10-26T20:00:00Z", 0.45, 0.58)
    move = stats.line_moves(rows)[0]
    first, last = 0.40 / 1.02, 0.45 / 1.03                          # the first pull adds up to 102%, the last to 103%
    assert (move["mover"], move["mover_team"], move["toward"]) == ("home", "Rangers", "home")
    assert move["first"] == pytest.approx(first) and move["last"] == pytest.approx(last)
    assert move["rise"] == pytest.approx(last - first)
    assert move["size"] == pytest.approx(last - first)              # the other side fell by the same amount


def test_line_move_with_a_draw_in_the_market():
    rows = snapshot("2026-10-26T13:00:00Z", 0.40, 0.35, draw=0.30) + snapshot("2026-10-26T20:00:00Z", 0.45, 0.35, draw=0.30)
    move = stats.line_moves(rows)[0]
    assert move["first"] == pytest.approx(0.40 / 1.05) and move["last"] == pytest.approx(0.45 / 1.10)
    assert move["size"] == pytest.approx(0.45 / 1.10 - 0.40 / 1.05)


def test_pulls_too_close_together_or_a_single_pull_are_not_movement():
    assert stats.line_moves(snapshot("2026-10-26T13:00:00Z", 0.4, 0.62)) == []
    assert stats.line_moves(snapshot("2026-10-26T13:00:00Z", 0.4, 0.62) + snapshot("2026-10-26T14:30:00Z", 0.5, 0.52)) == []


def test_a_small_wobble_does_not_count_as_moving_toward_a_side():
    rows = snapshot("2026-10-26T13:00:00Z", 0.500, 0.520) + snapshot("2026-10-26T20:00:00Z", 0.505, 0.515)
    move = stats.line_moves(rows)[0]
    assert move["toward"] is None and move["rise"] < stats.MOVE_THRESHOLD


def test_move_summary_checks_whether_the_side_moved_toward_won():
    moves = stats.line_moves(snapshot("2026-10-26T13:00:00Z", 0.40, 0.62) + snapshot("2026-10-26T20:00:00Z", 0.45, 0.58))
    won = stats.move_summary(moves, prep(game(event_id="e1", score=(3, 1))))[0]
    assert (won["n"], won["moved"], won["decided"], won["actual"]) == (1, 1, 1, 1.0)
    assert won["said"] == pytest.approx(0.45 / 1.03)                # the final odds' chance for the side that gained
    assert won["avg_move"] == pytest.approx((0.45 / 1.03 - 0.40 / 1.02) * 100)
    lost = stats.move_summary(moves, prep(game(event_id="e1", score=(0, 2))))[0]
    assert lost["actual"] == 0.0
    unfinished = stats.move_summary(moves, [])[0]
    assert (unfinished["decided"], unfinished["actual"]) == (0, None)


def test_biggest_moves_are_sorted_by_size():
    rows = (snapshot("2026-10-26T13:00:00Z", 0.40, 0.62, event="small") + snapshot("2026-10-26T20:00:00Z", 0.42, 0.60, event="small")
            + snapshot("2026-10-26T13:00:00Z", 0.40, 0.62, event="big") + snapshot("2026-10-26T20:00:00Z", 0.55, 0.47, event="big"))
    assert [m["event_id"] for m in stats.biggest_moves(stats.line_moves(rows))] == ["big", "small"]


# ---------- upsets ----------

def test_biggest_upsets_sorted_by_the_winners_chance():
    games = prep(
        game(event_id="a", home_prob=0.60, away_prob=0.40, score=(1, 2)),     # the 40% side won
        game(event_id="b", home_prob=0.30, away_prob=0.70, score=(3, 2)),     # the 30% side won: a bigger upset
        game(event_id="c", home_prob=0.60, away_prob=0.40, score=(3, 2)),     # the favorite won: not an upset
        game(event_id="d", home_prob=0.60, away_prob=0.40, score=(2, 2)))     # a draw: not an upset
    upsets = stats.biggest_upsets(games)
    assert [(u["event_id"], round(u["chance"], 2)) for u in upsets] == [("b", 0.30), ("a", 0.40)]
    assert stats.biggest_upsets(games, limit=1)[0]["event_id"] == "b"
