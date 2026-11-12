"""Tests for the results recap. Fake odds and fake score sources: no network, no credits."""

import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
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
    assert outcome_["waiting"] is False                               # nothing left to wait for
    assert "3 finished game(s)" in outcome_["reason"]


def test_it_waits_while_any_game_is_still_going(day_of_games):
    unfinished = dict(ALL_FINAL, basketball_nba=[])                    # the Lakers game has no final score yet
    outcome_ = evaluate(scores(**unfinished))
    assert outcome_["messages"] == [] and outcome_["done"] is False
    assert outcome_["waiting"] is True                                # looking again soon will help
    assert "waiting: 1 of 3 game(s) not final yet" in outcome_["reason"] and "09:00 PM CT" in outcome_["reason"]


def test_a_game_that_has_not_started_yet_also_makes_it_wait(day_of_games):
    outcome_ = evaluate(scores(), now=at("2026-11-08T20:00:00"))     # 2 PM CST: nothing has started
    assert outcome_["messages"] == [] and outcome_["done"] is False and "waiting: 3 of 3" in outcome_["reason"]
    assert outcome_["waiting"] is True


def test_no_wait_reports_what_is_final_now_but_does_not_close_the_day(day_of_games):
    unfinished = dict(ALL_FINAL, basketball_nba=[])
    outcome_ = evaluate(scores(**unfinished), no_wait=True)
    assert len(outcome_["messages"]) == 1 and "Lakers" not in outcome_["messages"][0]
    assert outcome_["done"] is False and "1 still going" in outcome_["reason"]
    assert outcome_["waiting"] is False                                # a manual check answers now and never waits


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
    assert during["waiting"] is False                                  # more waiting would change nothing: there are no games
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
    """The command with a fake Telegram and fake score sources, and the clock fixed at 11:30 PM on Nov 8.
    (Without the fixed clock these tests only passed for five hours after the fake games, then "the games
    ended long ago" kicked in: a time bomb that went off on Nov 9.)"""
    class Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW_LATE.astimezone(tz)

    sent = []
    monkeypatch.setattr(recap, "datetime", Now)
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


# ---------- keeping watch: one run stays alive until the last game is final ----------

class Clock:
    """A fake clock: sleeping moves time forward instantly, so a five-hour wait takes no time."""

    def __init__(self):
        self.seconds = 1000.0
        self.sleeps = []

    def __call__(self):
        return self.seconds

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.seconds += seconds

    def elapsed(self):
        return self.seconds - 1000.0


def waiting(reason="waiting: 2 of 3 game(s) not final yet (the latest started 09:00 PM CT)"):
    return {"day": DAY, "messages": [], "done": False, "waiting": True, "too_early": False, "check_from": None,
            "reason": reason}


def finished():
    return {"day": DAY, "messages": ["the recap"], "done": True, "waiting": False, "too_early": False, "check_from": None,
            "reason": "3 finished game(s)"}


@pytest.fixture
def watch(monkeypatch):
    """Scripted looks at the scores. watch(outcome, ...) fills the script; the last item repeats forever.
    An Exception in the script is raised by that look. The result has .looks, .clock and .reports."""
    clock = Clock()
    looks, reports = [], []

    class Now(datetime):                       # "now" follows the fake clock, 8:30 PM CST on Nov 8 to start with
        @classmethod
        def now(cls, tz=None):
            return (NOW_EVENING + timedelta(seconds=clock.elapsed())).astimezone(tz)

    monkeypatch.setattr(recap, "datetime", Now)

    def script(*items, **kwargs):
        def fake(data_dir, day, now, no_wait=False, start_within=None):
            looks.append({"now": now, "no_wait": no_wait, "start_within": start_within})
            item = items[min(len(looks) - 1, len(items) - 1)]
            if isinstance(item, Exception):
                raise item
            return item
        monkeypatch.setattr(recap, "evaluate", fake)
        return recap.check_until_done("data", DAY, reports.append, clock=clock, sleep=clock.sleep, **kwargs)

    script.looks, script.clock, script.reports = looks, clock, reports
    return script


def test_it_keeps_looking_every_three_minutes_until_the_last_game_is_final_then_stops(watch):
    one_left = "waiting: 1 of 3 game(s) not final yet (the latest started 09:00 PM CT)"
    last = watch(waiting(), waiting(), waiting(one_left), finished(), keep_waiting=330)
    assert last == finished() and len(watch.looks) == 4
    assert watch.clock.sleeps == [180, 180, 180]                          # nothing after the recap is ready
    assert [r["reason"] for r in watch.reports] == [waiting()["reason"], one_left, "3 finished game(s)"]


def test_every_look_uses_the_current_time_so_the_five_hour_give_up_rule_can_kick_in(watch):
    watch(waiting(), waiting(), finished(), keep_waiting=330)
    first, second, third = (look["now"] for look in watch.looks)
    assert second - first == timedelta(seconds=180) and third - second == timedelta(seconds=180)
    assert first.utcoffset() == timedelta(hours=-6)                          # Central, so "9 PM" means 9 PM there


def test_without_keep_waiting_it_looks_exactly_once_like_before(watch):
    last = watch(waiting())
    assert last["waiting"] is True and len(watch.looks) == 1 and watch.clock.sleeps == []
    assert len(watch.reports) == 1


def test_it_stops_at_the_time_limit_without_sleeping_past_it(watch):
    last = watch(waiting(), keep_waiting=10)                              # ten minutes, looks every 3
    assert last["waiting"] is True
    assert watch.clock.sleeps == [180, 180, 180, 60] and watch.clock.elapsed() == 600
    assert len(watch.looks) == 5                                          # at 0, 3, 6, 9 and 10 minutes
    assert watch.reports[-1] is last                                      # the last look is always reported


def test_a_day_with_no_games_is_not_waited_for(watch):
    quiet = {"day": DAY, "messages": [], "done": False, "waiting": False, "too_early": False, "check_from": None,
             "reason": "no games with odds and a score source on 2026-11-08 (yet), will look again"}
    assert watch(quiet, keep_waiting=330) == quiet
    assert len(watch.looks) == 1 and watch.clock.sleeps == []


def test_a_manual_no_wait_check_is_passed_through_and_never_waits(watch):
    watch(finished(), no_wait=True, keep_waiting=330)
    assert watch.looks[0]["no_wait"] is True


def test_it_only_speaks_when_something_changes_plus_once_an_hour(watch):
    watch(*([waiting()] * 44 + [finished()]), keep_waiting=330)           # 45 looks, 3 minutes apart
    assert len(watch.looks) == 45
    assert len(watch.reports) == 4                                        # look 1, look 20, look 40 and the last one


def test_a_hiccup_in_the_middle_of_a_long_wait_is_logged_and_tried_again(watch, capsys, monkeypatch):
    monkeypatch.setattr(telegram_bot, "BOT_TOKEN", "999:SECRET-TOKEN")
    last = watch(waiting(), RuntimeError("HTTP 503 from https://api.telegram.org/bot999:SECRET-TOKEN/x"), finished(),
                 keep_waiting=330)
    assert last == finished() and len(watch.looks) == 3
    err = capsys.readouterr().err
    assert "look 2 failed, trying again" in err and "RuntimeError" in err
    assert "SECRET-TOKEN" not in err                                      # the token is hidden even in this message


def test_the_very_first_look_failing_is_raised_straight_away_not_retried_for_hours(watch):
    with pytest.raises(RuntimeError, match="no odds"):
        watch(RuntimeError("no odds"), finished(), keep_waiting=330)
    assert len(watch.looks) == 1 and watch.clock.sleeps == []


def test_if_the_last_look_before_the_time_limit_fails_it_says_so_instead_of_guessing(watch):
    last = watch(waiting(), RuntimeError("boom"), keep_waiting=5)
    assert last is None
    assert watch.clock.sleeps == [180, 120] and len(watch.looks) == 3


@pytest.fixture
def evening(monkeypatch):
    """Like `cli`, but "now" is 11:30 PM on Nov 8 (the Lakers game is still within its five hours) and the
    Lakers game has no final score for the first two looks. Time is faked, so nothing really waits."""
    sent = []
    clock = Clock()
    looks = {"nba": 0}

    class Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return (NOW_LATE + timedelta(seconds=clock.elapsed())).astimezone(tz)

    def collect(key, days):
        if key == "basketball_nba":
            looks["nba"] += 1
            return "test", ALL_FINAL["basketball_nba"] if looks["nba"] >= 3 else []
        return "test", ALL_FINAL.get(key, [])

    monkeypatch.setattr(recap, "datetime", Now)
    monkeypatch.setattr(recap.time, "monotonic", clock)
    monkeypatch.setattr(recap.time, "sleep", clock.sleep)
    monkeypatch.setattr(telegram_bot, "send_message", sent.append)
    monkeypatch.setattr(results, "collect", collect)
    monkeypatch.setattr(telegram_bot, "BOT_TOKEN", "999:SECRET-TOKEN")
    return sent, clock, looks


def test_the_command_waits_for_the_last_game_then_sends_one_recap_once_and_writes_the_marker(
        evening, day_of_games, capsys, tmp_path):
    sent, clock, looks = evening
    marker = tmp_path / "recap.marker"
    assert recap.main(["--date", "2026-11-08", "--marker-file", str(marker), "--keep-waiting", "330"]) == 0
    assert looks["nba"] == 3 and clock.sleeps == [180, 180]
    assert len(sent) == 1 and "Lakers" in sent[0] and marker.exists()
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("Results recap for")]
    assert lines[0].endswith("waiting: 1 of 3 game(s) not final yet (the latest started 09:00 PM CT)")
    assert lines[-1].endswith("3 finished game(s)")


def test_if_the_game_is_still_going_at_the_time_limit_nothing_is_sent_and_no_marker_is_left(
        evening, day_of_games, capsys, tmp_path, monkeypatch):
    sent, clock, looks = evening
    monkeypatch.setattr(results, "collect",
                        lambda key, days: ("test", [] if key == "basketball_nba" else ALL_FINAL.get(key, [])))
    marker = tmp_path / "recap.marker"
    assert recap.main(["--date", "2026-11-08", "--marker-file", str(marker), "--keep-waiting", "10"]) == 0
    assert sent == [] and not marker.exists()                             # the next part (or run) carries on
    assert clock.elapsed() == 600
    assert "stopped waiting after 10 minutes; the next run carries on" in capsys.readouterr().err


def test_without_keep_waiting_the_command_checks_once_as_it_always_did(evening, day_of_games, tmp_path):
    sent, clock, looks = evening
    marker = tmp_path / "recap.marker"
    assert recap.main(["--date", "2026-11-08", "--marker-file", str(marker)]) == 0
    assert looks["nba"] == 1 and clock.sleeps == [] and sent == [] and not marker.exists()


def test_the_waiting_options_reject_nonsense():
    for bad in (["--keep-waiting", "-5"], ["--poll-seconds", "0"]):
        with pytest.raises(SystemExit) as stopped:
            recap.main(["--date", "2026-11-08", *bad])
        assert stopped.value.code == 2


def test_if_every_look_after_the_first_fails_the_command_exits_with_1_and_leaves_no_marker(
        evening, day_of_games, monkeypatch, capsys, tmp_path):
    sent, clock, looks = evening
    real, calls = recap.evaluate, []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("the score source changed its format")
        return real(*args, **kwargs)                                      # the first look works: the game is still going

    monkeypatch.setattr(recap, "evaluate", flaky)
    marker = tmp_path / "recap.marker"
    assert recap.main(["--date", "2026-11-08", "--marker-file", str(marker), "--keep-waiting", "10"]) == 1
    assert sent == [] and not marker.exists()                             # the next part (or run) tries again
    err = capsys.readouterr().err
    assert "look 2 failed, trying again" in err and "FAILED: the last check of the scores failed" in err


# ---------- smart start: do not even look until the last game could be final ----------
# The fake day's latest game (the Lakers) starts at 9:00 PM CST, so the recap cannot be ready before 10:30 PM CST.

CHECK_FROM = at("2026-11-09T04:30:00")               # 10:30 PM CST on Nov 8 = 9:00 PM + 90 minutes


def counting(by_sport):
    """A fake score source that remembers which leagues it was asked about."""
    asked = []

    def fetch(key, days):
        asked.append(key)
        return "test", by_sport.get(key, [])
    fetch.asked = asked
    return fetch


def early(minutes_away):
    """What evaluate() reports when the last game cannot be final for another `minutes_away` minutes (from 8:30 PM)."""
    return {"day": DAY, "messages": [], "done": False, "waiting": True, "too_early": True,
            "check_from": NOW_EVENING + timedelta(minutes=minutes_away), "reason": "too early to ask for scores: test"}


def test_smart_start_asks_nobody_for_scores_before_the_last_game_could_be_final(day_of_games):
    fetch = counting(ALL_FINAL)
    outcome_ = evaluate(fetch, now=NOW_EVENING, start_within=30)          # 8:30 PM: two hours too early
    assert fetch.asked == []                                              # no requests, no work
    assert outcome_["too_early"] is True and outcome_["waiting"] is True and outcome_["done"] is False
    assert outcome_["messages"] == [] and outcome_["check_from"].astimezone(UTC) == CHECK_FROM
    assert "too early to ask for scores" in outcome_["reason"]
    assert "starts at 09:00 PM CT" in outcome_["reason"] and "10:30 PM CT" in outcome_["reason"]


def test_the_reason_says_started_once_the_last_game_is_underway(day_of_games):
    outcome_ = evaluate(counting(ALL_FINAL), now=at("2026-11-09T04:00:00"), start_within=30)      # 10:00 PM CST
    assert outcome_["too_early"] is True and "started at 09:00 PM CT" in outcome_["reason"]


def test_it_starts_asking_at_the_exact_moment_the_last_game_could_be_final(day_of_games):
    just_before = counting(ALL_FINAL)
    assert evaluate(just_before, now=CHECK_FROM - timedelta(seconds=1), start_within=30)["too_early"] is True
    assert just_before.asked == []
    on_time = counting(ALL_FINAL)
    outcome_ = evaluate(on_time, now=CHECK_FROM, start_within=30)
    assert outcome_["too_early"] is False and outcome_["check_from"] is None
    assert sorted(on_time.asked) == ["basketball_nba", "icehockey_nhl"]  # now it asks, once per league
    assert outcome_["done"] is True and len(outcome_["messages"]) == 1


def test_without_smart_start_it_asks_every_time_like_before(day_of_games):
    fetch = counting(ALL_FINAL)
    outcome_ = evaluate(fetch, now=NOW_EVENING)                           # same early hour, no start_within
    assert fetch.asked and outcome_["too_early"] is False
    assert "waiting:" in outcome_["reason"] or "finished game" in outcome_["reason"]


def test_a_manual_check_is_never_held_back_by_smart_start(day_of_games):
    fetch = counting(ALL_FINAL)
    outcome_ = evaluate(fetch, now=NOW_EVENING, no_wait=True, start_within=30)
    assert fetch.asked and outcome_["too_early"] is False and len(outcome_["messages"]) == 1


def test_games_already_given_up_on_do_not_hold_back_the_recap(day_of_games):
    fetch = counting(dict(ALL_FINAL, basketball_nba=[]))
    outcome_ = evaluate(fetch, now=NOW_MUCH_LATER, start_within=30)       # 3 AM: every game started 5+ hours ago
    assert outcome_["too_early"] is False and fetch.asked and outcome_["done"] is True


def test_a_day_with_no_games_is_not_called_too_early(day_of_games):
    outcome_ = recap.evaluate(storage.data_dir(), date(2026, 11, 20), at("2026-11-21T02:00:00"),
                              fetch=counting({}), start_within=30)
    assert outcome_["too_early"] is False and outcome_["waiting"] is False


# ---- the loop: hours too early means exit, close to the time means wait here ----

def test_when_the_last_game_is_hours_from_possible_it_exits_at_once_instead_of_idling(watch):
    last = watch(early(180), finished(), keep_waiting=300, start_within=30)
    assert last["too_early"] is True and len(watch.looks) == 1 and watch.clock.sleeps == []
    assert watch.looks[0]["start_within"] == 30
    assert watch.reports == [last]


def test_when_the_time_is_close_it_waits_here_so_it_is_already_running_when_the_time_comes(watch):
    last = watch(early(20), early(20), early(20), waiting(), finished(), keep_waiting=300, start_within=30)
    assert last == finished() and len(watch.looks) == 5 and watch.clock.sleeps == [180, 180, 180, 180]


def test_exactly_the_start_within_margin_still_waits_but_one_minute_more_exits(watch):
    assert watch(early(30), finished(), keep_waiting=300, start_within=30) == finished()
    assert len(watch.looks) == 2 and watch.clock.sleeps == [180]


def test_one_minute_beyond_the_margin_exits(watch):
    assert watch(early(31), finished(), keep_waiting=300, start_within=30)["too_early"] is True
    assert len(watch.looks) == 1 and watch.clock.sleeps == []


@pytest.fixture
def smart(monkeypatch, day_of_games):
    """The command with fake time (starting at `base`), a fake Telegram and a fake score source that remembers when
    it was asked. Returns (start, sent, asked): call start(base_time) before running the command."""
    sent, asked, clock = [], [], Clock()
    state = {"base": NOW_EVENING}

    class Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return (state["base"] + timedelta(seconds=clock.elapsed())).astimezone(tz)

    def collect(key, days):
        asked.append((key, clock.elapsed()))
        return "test", ALL_FINAL.get(key, [])

    monkeypatch.setattr(recap, "datetime", Now)
    monkeypatch.setattr(recap.time, "monotonic", clock)
    monkeypatch.setattr(recap.time, "sleep", clock.sleep)
    monkeypatch.setattr(telegram_bot, "send_message", sent.append)
    monkeypatch.setattr(results, "collect", collect)
    monkeypatch.setattr(telegram_bot, "BOT_TOKEN", "999:SECRET-TOKEN")

    def start(base):
        state["base"] = base
        return clock
    return start, sent, asked


def test_the_command_exits_at_once_two_hours_before_the_last_game_could_be_final(smart, capsys, tmp_path):
    start, sent, asked = smart
    clock = start(NOW_EVENING)                                            # 8:30 PM
    marker = tmp_path / "recap.marker"
    args = ["--date", "2026-11-08", "--marker-file", str(marker), "--keep-waiting", "300", "--start-within", "30"]
    assert recap.main(args) == 0
    assert asked == [] and sent == [] and not marker.exists() and clock.sleeps == []
    captured = capsys.readouterr()
    assert "too early to ask for scores" in captured.out
    assert "not time to start yet; a later run begins checking at about 10:30 PM CT" in captured.err


def test_fifteen_minutes_before_the_time_it_waits_then_asks_then_sends_once(smart, capsys, tmp_path):
    start, sent, asked = smart
    clock = start(at("2026-11-09T04:15:00"))                              # 10:15 PM, check from 10:30 PM
    marker = tmp_path / "recap.marker"
    args = ["--date", "2026-11-08", "--marker-file", str(marker), "--keep-waiting", "300", "--start-within", "30"]
    assert recap.main(args) == 0
    assert clock.sleeps == [180] * 5                                      # 15 minutes of waiting, nothing asked meanwhile
    assert min(elapsed for _, elapsed in asked) == 900                    # the first request is at exactly 10:30 PM
    assert len(sent) == 1 and marker.exists()


def test_smart_start_rejects_a_negative_margin():
    with pytest.raises(SystemExit) as stopped:
        recap.main(["--date", "2026-11-08", "--start-within", "-1"])
    assert stopped.value.code == 2
