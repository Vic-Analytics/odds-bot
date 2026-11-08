"""Tests for the results recap. Fake odds and fake score sources: no network, no credits."""

import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import recap
import results
import stats
import storage
import telegram_bot
from helpers import book, game, outcome

DAY = date(2026, 11, 8)
PULL = "2026-11-08T14:00:00Z"                         # the morning digest of Nov 8 (8 AM CST)
UTC = timezone.utc

# Start times (UTC) of the day's games; Central is UTC-6 in November.
NHL_1 = "2026-11-09T01:00:00Z"                       # 7:00 PM CST on Nov 8
NHL_2 = "2026-11-09T01:30:00Z"                       # 7:30 PM
NBA_1 = "2026-11-09T03:00:00Z"                       # 9:00 PM


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


NOW_EVENING = at("2026-11-09T02:30:00")              # 8:30 PM CST: the first games are underway
NOW_LATE = at("2026-11-09T05:30:00")                 # 11:30 PM CST: the NBA game started 2.5 hours ago
NOW_MUCH_LATER = at("2026-11-09T09:00:00")           # 3:00 AM CST on Nov 9: every game started 5+ hours ago


def market(home, away, start, home_prices, away_prices, event_id, sport="icehockey_nhl", draw_prices=None):
    books = []
    for i, (home_price, away_price) in enumerate(zip(home_prices, away_prices)):
        prices = [outcome(home, home_price), outcome(away, away_price)]
        if draw_prices:
            prices.append(outcome("Draw", draw_prices[i]))
        books.append(book(f"Book{i}", h2h=prices))
    return game(home, away, start=start, books=books, game_id=event_id)


def save_odds(sport, games, pulled_at=PULL):
    storage.save_snapshot(sport, games, pulled_at=pulled_at)


def final(home, away, start, home_score, away_score, status="FINAL"):
    return {"source_id": f"{home}-{away}", "start_time": start, "home": home, "away": away,
            "home_score": home_score, "away_score": away_score, "status": status}


def scores(**by_sport):
    """A fake score source: scores(icehockey_nhl=[final(...)]). A value that is an Exception is raised."""
    def fetch(key, days):
        value = by_sport.get(key, [])
        if isinstance(value, Exception):
            raise value
        return "test", value
    return fetch


@pytest.fixture
def day_of_games():
    """Two NHL games (Colorado is the home favorite, Boston a slight home favorite) and one NBA game
    (the home Lakers are underdogs). Their odds are saved the way the morning digest saves them."""
    save_odds("icehockey_nhl", [
        market("Colorado Avalanche", "Pittsburgh Penguins", NHL_1, [-170, -165], [150, 145], "n1"),
        market("Boston Bruins", "Toronto Maple Leafs", NHL_2, [-150, -150], [130, 130], "n2")])
    save_odds("basketball_nba", [
        market("Los Angeles Lakers", "Golden State Warriors", NBA_1, [120, 115], [-140, -135], "b1", "basketball_nba")])


ALL_FINAL = dict(
    icehockey_nhl=[final("Colorado Avalanche", "Pittsburgh Penguins", NHL_1, 4, 2),            # the favorite won
                   final("Boston Bruins", "Toronto Maple Leafs", NHL_2, 1, 3, "FINAL_OT")],   # an upset, in overtime
    basketball_nba=[final("Los Angeles Lakers", "Golden State Warriors", NBA_1, 110, 100)])   # the home underdog won


def evaluate(fetch, now=NOW_LATE, day=DAY, **kwargs):
    return recap.evaluate(storage.data_dir(), day, now, fetch=fetch, **kwargs)


# ---------- when to send ----------

def test_it_sends_one_recap_once_every_game_is_final(day_of_games):
    outcome_ = evaluate(scores(**ALL_FINAL))
    assert outcome_["done"] is True and len(outcome_["messages"]) == 1
    assert "3 finished game(s)" in outcome_["reason"]


def test_it_waits_while_any_game_is_still_going(day_of_games):
    unfinished = dict(ALL_FINAL, basketball_nba=[])                    # the Lakers game has no final score yet
    outcome_ = evaluate(scores(**unfinished))
    assert outcome_["messages"] == [] and outcome_["done"] is False
    assert "waiting: 1 of 3 game(s) not final yet" in outcome_["reason"] and "09:00 PM CT" in outcome_["reason"]


def test_a_game_that_has_not_started_yet_also_makes_it_wait(day_of_games):
    outcome_ = evaluate(scores(), now=at("2026-11-08T20:00:00"))     # 2 PM CST: nothing has started
    assert outcome_["messages"] == [] and outcome_["done"] is False and "waiting: 3 of 3" in outcome_["reason"]


def test_no_wait_reports_what_is_final_now_but_does_not_close_the_day(day_of_games):
    unfinished = dict(ALL_FINAL, basketball_nba=[])
    outcome_ = evaluate(scores(**unfinished), no_wait=True)
    assert len(outcome_["messages"]) == 1 and "Lakers" not in outcome_["messages"][0]
    assert outcome_["done"] is False and "1 still going" in outcome_["reason"]


def test_a_game_with_no_score_five_hours_after_its_start_stops_holding_the_recap_up(day_of_games):
    unfinished = dict(ALL_FINAL, basketball_nba=[])                    # e.g. postponed
    outcome_ = evaluate(scores(**unfinished), now=at("2026-11-09T08:01:00"))     # 5 hours and a minute after the NBA start
    assert outcome_["done"] is True and len(outcome_["messages"]) == 1
    assert "Lakers" not in outcome_["messages"][0]                     # skipped quietly
    assert "1 with no final score after 5 hours, skipped" in outcome_["reason"]
    held = evaluate(scores(**unfinished), now=at("2026-11-09T07:59:00"))         # 4 hours 59 minutes: still waiting
    assert held["messages"] == []


def test_a_league_whose_score_source_is_down_just_waits_and_never_crashes(day_of_games, capsys):
    down = dict(ALL_FINAL, basketball_nba=RuntimeError("espn returned HTTP 503"))
    outcome_ = evaluate(scores(**down))
    assert outcome_["messages"] == [] and "waiting: 1 of 3" in outcome_["reason"]
    assert "NBA: could not fetch scores" in capsys.readouterr().err
    later = evaluate(scores(**down), now=NOW_MUCH_LATER)               # still down hours later: send the rest
    assert later["done"] is True and "Lakers" not in later["messages"][0] and "Avalanche" in later["messages"][0]


def test_a_day_with_no_games_sends_nothing_and_is_only_closed_once_the_day_is_over(day_of_games):
    quiet = date(2026, 11, 20)
    during = recap.evaluate(storage.data_dir(), quiet, at("2026-11-21T02:00:00"), fetch=scores())    # 8 PM CST on Nov 20
    assert during["messages"] == [] and during["done"] is False
    after = recap.evaluate(storage.data_dir(), quiet, at("2026-11-21T08:00:00"), fetch=scores())     # 2 AM on Nov 21
    assert after["messages"] == [] and after["done"] is True


def test_a_data_folder_without_that_days_odds_says_to_update_it(tmp_path):
    """A stale clone of the data repo has older days only. Saying "no games (yet)" would hide the real problem."""
    (tmp_path / "raw" / "2026-10-28").mkdir(parents=True)
    outcome_ = recap.evaluate(tmp_path, DAY, NOW_LATE, fetch=scores())
    assert "no odds have been saved for 2026-11-08" in outcome_["reason"] and "git pull" in outcome_["reason"]
    assert outcome_["messages"] == [] and outcome_["done"] is False
    closed = recap.evaluate(tmp_path, DAY, at("2026-11-09T20:00:00"), fetch=scores())     # the day is over: stop checking
    assert closed["done"] is True


def test_a_day_that_has_a_folder_but_no_games_keeps_the_ordinary_message(tmp_path):
    folder = tmp_path / "raw" / "2026-11-08"
    folder.mkdir(parents=True)
    (folder / "icehockey_nhl__140000Z.json").write_text("[]", encoding="utf-8")       # the digest ran: just no games
    outcome_ = recap.evaluate(tmp_path, DAY, NOW_LATE, fetch=scores())
    assert "no games with odds and a score source on 2026-11-08" in outcome_["reason"]
    assert "git pull" not in outcome_["reason"]


def test_fighting_games_have_no_free_score_source_and_never_hold_the_recap_up(day_of_games):
    save_odds("mma_mixed_martial_arts", [market("Islam Makhachev", "Charles Oliveira", NBA_1, [-300, -290], [250, 240],
                                                "f1", "mma_mixed_martial_arts")])
    outcome_ = evaluate(scores(**ALL_FINAL))
    assert outcome_["done"] is True and "3 finished game(s)" in outcome_["reason"]
    assert "Makhachev" not in outcome_["messages"][0]


def test_a_final_from_the_source_with_no_odds_in_the_data_is_skipped_quietly(day_of_games):
    extra = dict(ALL_FINAL)
    extra["icehockey_nhl"] = extra["icehockey_nhl"] + [final("Dallas Stars", "Utah Hockey Club", NHL_1, 5, 1)]
    outcome_ = evaluate(scores(**extra))
    assert "Dallas" not in outcome_["messages"][0] and "3 finished game(s)" in outcome_["reason"]


def test_a_late_game_belongs_to_the_day_it_started_on(day_of_games):
    save_odds("icehockey_nhl", [
        market("Vegas Golden Knights", "San Jose Sharks", "2026-11-09T05:30:00Z", [-150, -150], [130, 130], "n3"),    # 11:30 PM CST Nov 8
        market("Seattle Kraken", "Calgary Flames", "2026-11-09T06:30:00Z", [-150, -150], [130, 130], "n4")],          # 12:30 AM CST Nov 9
        pulled_at="2026-11-08T14:00:05Z")
    nov8 = evaluate(scores(icehockey_nhl=[final("Vegas Golden Knights", "San Jose Sharks", "2026-11-09T05:30:00Z", 3, 1),
                                          final("Seattle Kraken", "Calgary Flames", "2026-11-09T06:30:00Z", 2, 1)]),
                    now=at("2026-11-09T10:30:00"))
    assert "Golden Knights" in nov8["messages"][0] and "Kraken" not in nov8["messages"][0]


def test_only_the_leagues_playing_that_day_are_asked_and_the_next_date_is_included_for_late_games(day_of_games):
    asked = []

    def fetch(key, days):
        asked.append((key, list(days)))
        return "test", []

    save_odds("soccer_epl", [market("Arsenal", "Liverpool", "2026-11-12T12:30:00Z", [150], [180], "s9", "soccer_epl", [240])])  # another day
    evaluate(fetch)
    assert {key for key, _ in asked} == {"icehockey_nhl", "basketball_nba"}
    assert all(days == [DAY, date(2026, 11, 9)] for _, days in asked)


def test_missing_odds_folder_gives_a_clear_message(tmp_path):
    with pytest.raises(SystemExit, match="No odds found"):
        recap.evaluate(tmp_path, DAY, NOW_LATE, fetch=scores())


def test_only_the_days_around_the_recap_day_are_read(tmp_path):
    raw = tmp_path / "raw"
    for name in ("2026-10-01", "2026-11-05", "2026-11-06", "2026-11-08", "2026-11-09", "2026-11-12"):
        (raw / name).mkdir(parents=True)
        (raw / name / "icehockey_nhl__140000Z.json").write_text("[]", encoding="utf-8")
    destination = tmp_path / "copy"
    destination.mkdir()
    assert recap.copy_raw_days(tmp_path, destination, DAY) == 3
    assert sorted(p.name for p in destination.iterdir()) == ["2026-11-06", "2026-11-08", "2026-11-09"]


# ---------- the message ----------

def prepared(**fields):
    row = {"event_id": "e1", "sport_key": "icehockey_nhl", "home_team": "Colorado Avalanche",
           "away_team": "Pittsburgh Penguins", "home_prob": 0.60, "away_prob": 0.42, "draw_prob": None,
           "home_score": 4, "away_score": 2, "status": "FINAL", "commence_time": NHL_1}
    row.update(fields)
    return stats.prepare([row])[0]


def test_favorite_won_upset_and_draw_each_have_their_own_wording():
    favorite_won = recap.game_block(prepared())
    upset = recap.game_block(prepared(home_score=1, away_score=2))
    tie = recap.game_block(prepared(sport_key="americanfootball_nfl", home_score=20, away_score=20))
    assert "Favorite won" in favorite_won and "Upset" not in favorite_won
    assert "Upset" in upset and "Favorite won" not in upset
    assert "Tie" in tie and "Upset" not in tie


def test_the_favorite_and_its_chance_are_shown_with_the_margin_removed():
    block = recap.game_block(prepared())
    assert "Favorite: " in block and "Colorado Avalanche 59%" in block        # 0.60 / 1.02 = 58.8%


def test_us_sports_are_written_away_then_home_and_soccer_home_then_away():
    us = recap.game_block(prepared())
    assert us.index("Pittsburgh Penguins") < us.index("Colorado Avalanche")
    assert "<b>2</b> – <b>4</b>" in us
    soccer = recap.game_block(prepared(sport_key="soccer_epl", home_team="Arsenal", away_team="Liverpool",
                                       home_score=2, away_score=1, draw_prob=0.28, status="FULL_TIME"))
    assert soccer.index("Arsenal") < soccer.index("Liverpool") and "<b>2</b> – <b>1</b>" in soccer


def test_soccer_after_extra_time_counts_as_a_draw_and_says_so():
    block = recap.game_block(prepared(sport_key="soccer_uefa_champs_league", home_team="Real Madrid", away_team="Bayern Munich",
                                      home_score=3, away_score=2, draw_prob=0.25, status="FINAL_AET"))
    assert "Draw (level after 90 min)" in block and "(after extra time)" in block
    assert "Favorite won" not in block and "Upset" not in block


def test_overtime_and_shootouts_are_noted():
    assert "(OT)" in recap.game_block(prepared(status="FINAL_OT"))
    assert "(SO)" in recap.game_block(prepared(status="FINAL_SO"))


def test_the_full_message(day_of_games):
    message = evaluate(scores(**ALL_FINAL))["messages"][0]
    text = recap.plain_preview(message)
    assert text.startswith("📋 Results recap — Sun, Nov 8")
    assert "🏒 NHL" in text and "🏀 NBA" in text and text.index("NBA") < text.index("NHL")        # the digest's league order
    assert "Favorite: 🏔️ Colorado Avalanche 61%" in text and "✅ Favorite won" in text        # 0.6261 / 1.0302 with the margin removed
    assert "Toronto Maple Leafs" in text and "(OT)" in text and "Upset" in text
    assert "Favorites won 1 · Upsets 2" in text                                                  # Lakers and the Leafs
    assert "Golden State Warriors" in text and "Los Angeles Lakers" in text


def test_team_names_are_escaped_for_telegram():
    block = recap.game_block(prepared(home_team="Brighton & Hove <Albion>"))
    assert "Brighton &amp; Hove &lt;Albion&gt;" in block and "<Albion>" not in block


def test_no_games_means_no_message():
    assert recap.format_recap([], DAY) == []


def test_a_long_recap_is_split_between_games_below_telegrams_limit():
    games = [prepared(event_id=f"e{i}", home_team=f"Home Team Number {i}", away_team=f"Away Team Number {i}") for i in range(80)]
    messages = recap.format_recap(games, DAY)
    assert len(messages) > 1
    assert all(len(m) <= recap.MAX_MESSAGE_LENGTH for m in messages)
    assert messages[0].startswith("📋 <b>Results recap</b> — Sun, Nov 8")
    assert all(m.startswith("📋 <b>Results recap</b> (cont.)") for m in messages[1:])
    assert all("<b>NHL</b>" in m for m in messages)                       # the league header is repeated
    text = "".join(messages)
    assert all(text.count(f"Home Team Number {i}<") + text.count(f"Home Team Number {i}\n") + text.count(f"Home Team Number {i} ") >= 1
               for i in range(80))
    assert text.count("Favorites won") == 1 and messages[-1].rstrip().endswith("</i>")


# ---------- the command line ----------

@pytest.fixture
def cli(monkeypatch, day_of_games):
    sent = []
    monkeypatch.setattr(telegram_bot, "send_message", sent.append)
    monkeypatch.setattr(recap.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(results, "collect", lambda key, days: ("test", ALL_FINAL.get(key, [])))
    monkeypatch.setattr(telegram_bot, "BOT_TOKEN", "999:SECRET-TOKEN")
    return sent


def test_a_dry_run_prints_the_recap_and_sends_nothing(cli, capsys, tmp_path):
    marker = tmp_path / "recap.marker"
    assert recap.main(["--date", "2026-11-08", "--dry-run", "--marker-file", str(marker)]) == 0
    out = capsys.readouterr().out
    assert "Results recap — Sun, Nov 8" in out and "Favorite won" in out and "dry run: nothing was sent" in out
    assert cli == [] and not marker.exists()


def test_a_real_run_sends_and_writes_the_marker(cli, capsys, tmp_path):
    marker = tmp_path / "recap.marker"
    assert recap.main(["--date", "2026-11-08", "--marker-file", str(marker)]) == 0
    assert len(cli) == 1 and "Results recap" in cli[0] and marker.exists()


def test_no_marker_while_games_are_still_going(cli, monkeypatch, tmp_path):
    monkeypatch.setitem(ALL_FINAL, "basketball_nba", [])
    marker = tmp_path / "recap.marker"
    assert recap.main(["--date", "2026-11-08", "--marker-file", str(marker), "--no-wait"]) == 0      # partial recap
    assert len(cli) == 1 and not marker.exists()


def test_a_telegram_failure_exits_with_1_hides_the_token_and_leaves_no_marker(cli, monkeypatch, capsys, tmp_path):
    def broken(text):
        raise RuntimeError("Telegram error 400: https://api.telegram.org/bot999:SECRET-TOKEN/sendMessage")
    monkeypatch.setattr(telegram_bot, "send_message", broken)
    marker = tmp_path / "recap.marker"
    assert recap.main(["--date", "2026-11-08", "--marker-file", str(marker)]) == 1
    err = capsys.readouterr().err
    assert "SECRET-TOKEN" not in err and "***" in err and not marker.exists()


def test_a_bad_date_is_rejected():
    with pytest.raises(SystemExit, match="2026-11-08"):
        recap.main(["--date", "yesterday"])


def test_the_wrong_python_gives_a_friendly_message_instead_of_a_traceback():
    """Running with a Python that lacks the project's libraries (not the .venv one) is an easy mistake."""
    code = ("import sys, runpy; sys.modules['dotenv'] = None; sys.argv = ['recap.py', '--dry-run']; "
            "runpy.run_path('recap.py', run_name='__main__')")
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).parent.parent, capture_output=True, text=True)
    assert result.returncode != 0 and "Traceback" not in result.stderr
    assert "'dotenv' is missing" in result.stderr
    assert r".\.venv\Scripts\python.exe recap.py --dry-run" in result.stderr
