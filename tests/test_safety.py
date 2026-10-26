"""Tests for the safety rails: secret scrubbing, the 8 AM guard, credits, errors."""

import pytest

import games_today
import main
import telegram_bot
from config import SPORTS, markets_for
from helpers import book, game, outcome

FUTURE = "2099-01-01T14:00:00Z"
PAST = "2020-01-01T15:00:00Z"


# ---------- secrets never reach a message ----------

def test_scrub_hides_both_secrets(monkeypatch):
    monkeypatch.setattr(main, "ODDS_API_KEY", "KEY123")
    monkeypatch.setattr(telegram_bot, "BOT_TOKEN", "999:TOKEN")
    text = "failed: /v4/odds?apiKey=KEY123 and /bot999:TOKEN/sendMessage"
    scrubbed = main.scrub(text)
    assert "KEY123" not in scrubbed and "999:TOKEN" not in scrubbed
    assert scrubbed.count("***") == 2


def test_scrub_copes_with_missing_secrets(monkeypatch):
    monkeypatch.setattr(main, "ODDS_API_KEY", None)
    monkeypatch.setattr(telegram_bot, "BOT_TOKEN", None)
    assert main.scrub("nothing to hide") == "nothing to hide"


# ---------- markets per sport ----------

def test_markets_per_sport():
    # Point spreads for football and basketball...
    for name in ("NFL", "NBA", "WNBA"):
        assert markets_for(name) == "h2h,spreads", name
    # ...totals for baseball and hockey, moneyline only for fights.
    assert markets_for("MLB") == "h2h,totals"
    assert markets_for("NHL") == "h2h,totals"
    assert markets_for("UFC / MMA") == "h2h"
    for name, key in SPORTS.items():
        if key.startswith("soccer_"):
            assert markets_for(name) == "h2h,totals", name


# ---------- credit guard and live scores ----------

@pytest.fixture
def fake_api(monkeypatch):
    """Stand-ins for the three API calls, recording how often each is used."""
    calls = {"events": 0, "odds": 0, "scores": 0}
    state = {"events": [], "odds": [], "odds_remaining": "100", "scores": [], "scores_remaining": "99",
             "scores_error": None}

    def events(key):
        calls["events"] += 1
        return state["events"]

    def odds(key, markets):
        calls["odds"] += 1
        return state["odds"], state["odds_remaining"]

    def scores(key):
        calls["scores"] += 1
        if state["scores_error"]:
            raise state["scores_error"]
        return state["scores"], state["scores_remaining"]

    monkeypatch.setattr(games_today, "fetch_events", events)
    monkeypatch.setattr(games_today, "fetch_odds", odds)
    monkeypatch.setattr(games_today, "fetch_scores", scores)
    # Make "today" not depend on the real clock: every game counts as today.
    monkeypatch.setattr(games_today, "filter_today", lambda games, now=None: list(games))
    return calls, state


def test_no_games_today_spends_no_credits(fake_api):
    calls, state = fake_api
    games, remaining = games_today.fetch_todays_games_with_odds("x", None, "h2h,spreads")
    assert (games, remaining) == ([], None)
    assert calls == {"events": 1, "odds": 0, "scores": 0}


def test_refuses_a_call_it_cannot_afford(fake_api):
    calls, state = fake_api
    state["events"] = [game("H", "A", start=FUTURE)]
    with pytest.raises(RuntimeError, match="Only 1 Odds API credits left"):
        games_today.fetch_todays_games_with_odds("x", 1, "h2h,spreads")
    assert calls["odds"] == 0


def test_one_market_costs_one_credit_so_one_credit_is_enough(fake_api):
    calls, state = fake_api
    state["events"] = state["odds"] = [game("H", "A", start=FUTURE)]
    games_today.fetch_todays_games_with_odds("x", 1, "h2h")
    assert calls["odds"] == 1


def test_live_game_gets_its_score_attached(fake_api):
    calls, state = fake_api
    live = game("Newcastle United", "Aston Villa", start=PAST, game_id="g1")
    later = game("Arsenal", "Fulham", start=FUTURE, game_id="g2")
    state["events"] = state["odds"] = [live, later]
    state["scores"] = [{"id": "g1", "scores": [{"name": "Newcastle United", "score": "0"},
                                               {"name": "Aston Villa", "score": "1"}]}]
    games, remaining = games_today.fetch_todays_games_with_odds("x", None, "h2h,totals")
    assert games[0]["live_scores"] == {"Newcastle United": "0", "Aston Villa": "1"}
    assert "live_scores" not in games[1]
    assert calls["scores"] == 1
    assert remaining == "99"          # the freshest credit count wins


def test_no_scores_call_when_nothing_has_started(fake_api):
    calls, state = fake_api
    state["events"] = state["odds"] = [game("H", "A", start=FUTURE)]
    games_today.fetch_todays_games_with_odds("x", None, "h2h,spreads")
    assert calls["scores"] == 0


def test_no_scores_call_when_no_credits_remain(fake_api):
    calls, state = fake_api
    state["events"] = state["odds"] = [game("H", "A", start=PAST)]
    state["odds_remaining"] = "0"
    games_today.fetch_todays_games_with_odds("x", None, "h2h,spreads")
    assert calls["scores"] == 0


def test_a_failing_scores_call_does_not_break_the_digest(fake_api):
    calls, state = fake_api
    state["events"] = state["odds"] = [game("H", "A", start=PAST)]
    state["scores_error"] = RuntimeError("scores are down")
    games, remaining = games_today.fetch_todays_games_with_odds("x", None, "h2h,spreads")
    assert len(games) == 1 and remaining == "100"


# ---------- the whole run ----------

def a_game(start=FUTURE, books=1):
    return game("Home", "Away", start=start, books=[
        book(f"Book{i}", h2h=[outcome("Home", -110), outcome("Away", 100)]) for i in range(books)
    ])


@pytest.fixture
def harness(monkeypatch):
    """Capture Telegram messages, skip waiting, and let each test script the fetcher."""
    sent = []
    monkeypatch.setattr(main, "send_message", sent.append)
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    monkeypatch.setattr(main, "ODDS_API_KEY", "KEY123")

    def script(by_sport_key):
        """by_sport_key: {sport_key: (games, remaining) or an Exception}."""
        def fake_fetch(key, credits_left=None, markets="h2h,spreads"):
            result = by_sport_key.get(key, ([], None))
            if isinstance(result, Exception):
                raise result
            return result
        monkeypatch.setattr(main, "fetch_todays_games_with_odds", fake_fetch)

    return sent, script


def test_sends_one_message_per_sport_with_games(harness):
    sent, script = harness
    script({SPORTS["NFL"]: ([a_game()], "300"), SPORTS["NHL"]: ([a_game()], "296")})
    assert main.run(False) == 0
    assert len(sent) == 2
    assert "NFL" in sent[0] and "NHL" in sent[1]


def test_quiet_day_sends_a_short_note(harness):
    sent, script = harness
    script({})
    assert main.run(False) == 0
    assert sent == ["No games today in your sports."]


def test_one_failing_sport_does_not_stop_the_others_and_leaks_nothing(harness):
    sent, script = harness
    script({
        SPORTS["NBA"]: RuntimeError("timeout calling /odds?apiKey=KEY123&regions=us"),
        SPORTS["NHL"]: ([a_game()], "200"),
    })
    assert main.run(False) == 1                      # failure is reported via exit code
    assert any("NHL" in m for m in sent)             # the other sport still went out
    problem = sent[-1]
    assert "Odds bot problem" in problem and "NBA" in problem
    assert not any("KEY123" in m for m in sent)


def test_low_credit_warning(harness):
    sent, script = harness
    script({SPORTS["NHL"]: ([a_game()], "10")})
    assert main.run(False) == 0
    assert "Only <b>10</b> Odds API credits left" in sent[-1]


def test_no_warning_when_credits_are_healthy(harness):
    sent, script = harness
    script({SPORTS["NHL"]: ([a_game()], "300")})
    main.run(False)
    assert not any("credits left" in m for m in sent)


def test_mma_hides_fights_with_fewer_than_four_sportsbooks(harness):
    sent, script = harness
    thin = game("Nobody A", "Nobody B", start=FUTURE, books=[
        book("Only", h2h=[outcome("Nobody A", -110), outcome("Nobody B", -110)])])
    main_event = game("Alexander Volkanovski", "Movsar Evloev", start=FUTURE, books=[
        book(f"Book{i}", h2h=[outcome("Alexander Volkanovski", -145), outcome("Movsar Evloev", 130)])
        for i in range(4)])
    script({SPORTS["UFC / MMA"]: ([thin, main_event], "100")})
    main.run(False)
    combined = "\n".join(sent)
    assert "Movsar Evloev" in combined
    assert "Nobody A" not in combined


def test_dry_run_sends_nothing(harness, capsys):
    sent, script = harness
    script({SPORTS["NHL"]: ([a_game()], "300")})
    assert main.run(True) == 0
    assert sent == []
    assert "NHL" in capsys.readouterr().out


# ---------- the "digest sent today" marker ----------

def test_marker_is_written_after_a_normal_digest(harness, tmp_path):
    sent, script = harness
    marker = tmp_path / "sent.marker"
    script({SPORTS["NHL"]: ([a_game()], "300")})
    assert main.run(False, str(marker)) == 0
    assert marker.exists()


def test_marker_is_written_on_a_quiet_day_too(harness, tmp_path):
    # "No games today" is a delivered message, so later runs must not repeat it.
    sent, script = harness
    marker = tmp_path / "sent.marker"
    script({})
    main.run(False, str(marker))
    assert sent == ["No games today in your sports."]
    assert marker.exists()


def test_marker_is_written_when_some_sports_fail_but_others_were_delivered(harness, tmp_path):
    sent, script = harness
    marker = tmp_path / "sent.marker"
    script({SPORTS["NBA"]: RuntimeError("boom"), SPORTS["NHL"]: ([a_game()], "300")})
    assert main.run(False, str(marker)) == 1          # the run is still flagged as a problem
    assert marker.exists()                            # ...but today's digest did go out


def test_no_marker_when_every_sport_failed_so_the_next_hour_retries(harness, tmp_path):
    sent, script = harness
    marker = tmp_path / "sent.marker"
    everything_fails = {key: RuntimeError("API down") for key in SPORTS.values()}
    script(everything_fails)
    assert main.run(False, str(marker)) == 1
    assert not marker.exists()
    assert any("Odds bot problem" in m for m in sent)   # you are still told about it


def test_no_marker_in_a_dry_run(harness, tmp_path):
    sent, script = harness
    marker = tmp_path / "sent.marker"
    script({SPORTS["NHL"]: ([a_game()], "300")})
    main.run(True, str(marker))
    assert not marker.exists()


def test_no_marker_path_means_no_file_is_written(harness, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sent, script = harness
    script({SPORTS["NHL"]: ([a_game()], "300")})
    main.run(False)
    assert list(tmp_path.iterdir()) == []
