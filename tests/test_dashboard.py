"""Tests for analysis/dashboard.py, using the small hand-checked database from the SQL tests."""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "analysis"))

import dashboard
import storage
from helpers import book, game, outcome
from test_analysis_sql import conn  # noqa: F401  (the fixture: 3 NHL games + 1 NFL game, all finished)

NOW = datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc)      # after the morning pull, before every game


def page(hours=48):
    return dashboard.build(storage.db_path(), hours, now=NOW)


def result_row(text, team):
    """The row of the 'Recent results' table that mentions this team."""
    section = text.split("Recent results")[1].split("Home underdogs")[0]
    return next(row for row in section.split("<tr>") if team in row)


def test_page_shows_counts_results_and_upsets(conn):
    text = page()
    assert "<title>Odds Bot Dashboard</title>" in text
    assert "Upset" in result_row(text, "Rangers")             # the home underdog beat the Kings
    assert "Favorite won" in result_row(text, "Bruins")       # the favorite beat the Sharks
    assert "Favorite won" not in result_row(text, "Rangers")
    assert "Upset" not in result_row(text, "Bruins")
    assert "Tie" in result_row(text, "Flames")                # 3 - 3
    assert "FINAL_OT" in result_row(text, "Bruins")           # a game that went to overtime says so


def test_home_underdog_table_counts(conn):
    text = page()
    section = text.split("<h3>Home underdogs</h3>")[1].split("</section>")[0]
    # NHL: g1 and g3 were home underdogs; g1 won, g3 tied (so 2 underdogs, 1 win).
    # With the margin removed the home chances were 39.6% and 47.8%, so the odds said 44%.
    row = section.split("<td>NHL</td>")[1].split("</tr>")[0]
    assert '<td class="n">3</td><td class="n">2</td><td class="n">1</td><td class="n">44%</td><td class="n">50%</td>' in row
    assert "too few games to trust" in row


def test_coming_up_only_lists_games_inside_the_window(conn):
    assert "Rangers" in page(hours=48)
    soon = dashboard.build(storage.db_path(), 1, now=NOW)       # the first game is 4 hours away
    assert "No games in this window yet" in soon


def test_chart_has_a_bar_and_a_table_alternative(conn):
    text = page()
    assert "<svg" in text and 'class="bar"' in text
    assert "Show as a table" in text


def test_team_names_are_escaped(conn):
    evil = game("<script>alert(1)</script>", "Kings", start="2026-10-27T05:00:00Z", game_id="x1",
                books=[book("A", h2h=[outcome("<script>alert(1)</script>", -150), outcome("Kings", 130)])])
    storage.insert_snapshot(conn, "icehockey_nhl", [evil], "2026-10-26T13:05:00Z")
    text = page()
    assert "<script>alert(1)" not in text
    assert "&lt;script&gt;" in text


def test_empty_database_still_builds():
    storage.connect(storage.db_path()).close()
    text = page()
    assert "Nothing to show until games finish." in text
    assert "No games in this window yet" in text


def test_missing_database_gives_a_clear_message(tmp_path):
    with pytest.raises(SystemExit, match="not found"):
        dashboard.build(tmp_path / "nope.db", 48, now=NOW)


def test_database_is_opened_read_only(conn):
    import sqlite3
    c = dashboard.connect(storage.db_path())
    with pytest.raises(sqlite3.OperationalError):
        c.execute("DELETE FROM events")
    c.close()


def section(text, title):
    return text.split(f"<h3>{title}</h3>")[1].split("</section>")[0]


def test_every_new_section_is_on_the_page(conn):
    text = page()
    for title in ["Do favorites win as often as the odds say?", "Which sportsbooks pay the most?",
                  "What is shopping for the best line worth?", "Home advantage", "Over / under", "Point spreads",
                  "Soccer draws", "Rest and back-to-backs", "Coverage by league", "Games tracked per day"]:
        assert f"<h3>{title}</h3>" in text, title


def test_sections_use_the_fake_games(conn):
    text = page()
    assert "<td>NHL</td>" in section(text, "Over / under")                  # the NHL games had an over/under line
    assert "<td>NFL</td>" in section(text, "Point spreads")                 # the NFL game had a spread
    assert "<td>NHL</td>" in section(text, "What is shopping for the best line worth?")    # g2 was priced by 3 books
    assert "All leagues" in section(text, "Do favorites win as often as the odds say?")
    assert "Needs a team that played two days in a row" in section(text, "Rest and back-to-backs")   # one day of games


def test_health_counts_scores_and_missing_scores(conn):
    c = dashboard.connect(storage.db_path())
    late = datetime(2026, 10, 29, 0, 0, tzinfo=timezone.utc)                # every game started more than 24h ago
    rows = {r["sport_key"]: r for r in dashboard.health(c, late)}
    c.close()
    nhl = rows["icehockey_nhl"]
    assert (nhl["games"], nhl["scored"], nhl["missing"]) == (4, 3, 1)       # g4 never got a score
    assert rows["americanfootball_nfl"]["missing"] == 0
    assert nhl["pulls"] == 2                                                # the morning pull and the live one
    shown = dashboard.health_html([{"sport_key": "icehockey_nhl", "games": 4, "scored": 3, "missing": 1,
                                    "pulls": 1, "last_pull": "2026-10-26T13:00:00Z"}], {})
    assert "check team names" in shown


def test_mma_is_not_reported_as_missing_scores():
    shown = dashboard.health_html([{"sport_key": "mma_mixed_martial_arts", "games": 9, "scored": 0, "missing": 9,
                                    "pulls": 3, "last_pull": None}], {})
    assert "no score source" in shown and "check team names" not in shown


def test_empty_database_shows_a_message_in_every_new_section():
    storage.connect(storage.db_path()).close()
    assert page().count('class="empty"') >= 10
