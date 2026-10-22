"""Tests for the Telegram message layout."""

from format_digest import format_sport_messages
from helpers import book, game, outcome

# A start time safely in the future (8:00 AM Central in January), so the game
# is never labeled LIVE by accident.
FUTURE = "2099-01-01T14:00:00Z"
PAST = "2020-01-01T15:00:00Z"


def nhl_game(start=FUTURE):
    return game("Colorado Avalanche", "Pittsburgh Penguins", start=start, books=[
        book("DraftKings",
             h2h=[outcome("Colorado Avalanche", -170), outcome("Pittsburgh Penguins", 150)],
             spreads=[outcome("Colorado Avalanche", 110, -1.5), outcome("Pittsburgh Penguins", -130, 1.5)]),
    ])


def test_no_games_means_no_messages():
    assert format_sport_messages("NHL", []) == []


def test_us_sport_layout():
    [message] = format_sport_messages("NHL", [nhl_game()])
    assert "<b>NHL</b>" in message
    assert "<b>8:00 AM · Pittsburgh Penguins @ Colorado Avalanche</b>" in message
    assert "<blockquote>" in message and "</blockquote>" in message
    assert "<i>Moneyline</i>" in message and "<i>Spread</i>" in message
    assert "<b>+150</b>  (DraftKings)" in message
    assert "<b>-1.5</b>" in message
    assert "LIVE" not in message
    assert "Total" not in message


def test_team_emoji_appears_on_the_odds_rows():
    [message] = format_sport_messages("NHL", [nhl_game()])
    assert "\U0001F427 Pittsburgh Penguins" in message   # penguin
    assert "\U0001F3D4️ Colorado Avalanche" in message  # snow-capped mountain


def test_live_game_shows_score_in_matchup_order_and_labels_odds():
    g = nhl_game(start=PAST)
    g["live_scores"] = {"Colorado Avalanche": "2", "Pittsburgh Penguins": "1"}
    [message] = format_sport_messages("NHL", [g])
    assert "LIVE" in message
    assert "Pittsburgh Penguins 1–2 Colorado Avalanche" in message   # away @ home order
    assert "Moneyline (live odds)" in message
    assert "Spread (live odds)" in message


def test_live_game_without_a_score_still_says_live():
    [message] = format_sport_messages("NHL", [nhl_game(start=PAST)])
    assert "LIVE</b> · in progress" in message


def soccer_game(home="Everton", away="Chelsea"):
    return game(home, away, start=FUTURE, books=[
        book("FanDuel",
             h2h=[outcome(home, 310), outcome("Draw", 270), outcome(away, -115)],
             totals=[outcome("Over", -112, 2.5), outcome("Under", -108, 2.5)]),
    ])


def test_soccer_layout_home_first_with_draw_and_total_goals():
    [message] = format_sport_messages("EPL", [soccer_game()])
    assert "Everton vs Chelsea" in message            # home vs away
    assert "Draw  <b>+270</b>" in message
    assert "<i>Total goals</i>" in message
    assert "Over 2.5" in message and "Under 2.5" in message
    assert "Spread" not in message
    assert "\U0001F535 Everton" in message             # soccer kit-color dot (blue)


def test_draw_row_sits_between_the_two_teams():
    [message] = format_sport_messages("EPL", [soccer_game()])
    assert message.index("Everton  ") < message.index("Draw") < message.index("Chelsea  ")


def totals_game(home, away):
    return game(home, away, start=FUTURE, books=[
        book("BetRivers",
             h2h=[outcome(home, -120), outcome(away, 100)],
             totals=[outcome("Over", -112, 6.5), outcome("Under", -103, 6.5)]),
    ])


def test_each_sport_names_its_total_correctly():
    cases = [("NHL", "Total goals"), ("MLB", "Total runs"), ("EPL", "Total goals"), ("NBA", "Total")]
    for sport, label in cases:
        [message] = format_sport_messages(sport, [totals_game("Home Team", "Away Team")])
        assert f"<i>{label}</i>" in message, sport


def test_hockey_and_baseball_show_over_under_instead_of_a_spread():
    for sport, home, away in [("NHL", "Colorado Avalanche", "Pittsburgh Penguins"),
                              ("MLB", "Milwaukee Brewers", "Tampa Bay Rays")]:
        [message] = format_sport_messages(sport, [totals_game(home, away)])
        assert "Over 6.5  <b>-112</b>  (BetRivers)" in message
        assert "Under 6.5  <b>-103</b>  (BetRivers)" in message
        assert "Spread" not in message
        # The home team's moneyline row (its last mention) comes before the total.
        assert message.index("Moneyline") < message.rindex(home) < message.index("Total")


def test_a_whole_number_total_prints_without_a_decimal():
    g = game("H", "A", start=FUTURE, books=[
        book("X", totals=[outcome("Over", 105, 6.0), outcome("Under", -125, 6.0)])])
    [message] = format_sport_messages("NHL", [g])
    assert "Over 6  " in message and "Under 6  " in message


def test_soccer_moneyline_rows_all_start_with_the_same_emoji_width():
    # Everton and Chelsea are both one-color kits; Brighton has a two-color kit.
    for home, away in [("Everton", "Chelsea"), ("Brighton and Hove Albion", "Everton")]:
        [message] = format_sport_messages("EPL", [soccer_game(home=home, away=away)])
        lines = message.split("<i>Moneyline</i>\n")[1].split("\n\n")[0].split("\n")
        assert len(lines) == 3                                   # home, draw, away
        assert [len(line.split(" ", 1)[0]) for line in lines] == [2, 2, 2]


def test_team_names_are_html_escaped():
    [message] = format_sport_messages("EPL", [soccer_game(home="Brighton & Hove Albion")])
    assert "Brighton &amp; Hove Albion" in message
    assert "Brighton & Hove" not in message


def test_mma_is_moneyline_only_with_vs_and_flags():
    g = game("Alexander Volkanovski", "Movsar Evloev", start=FUTURE, books=[
        book("FanDuel", h2h=[outcome("Alexander Volkanovski", -145), outcome("Movsar Evloev", 130)]),
    ])
    [message] = format_sport_messages("UFC / MMA", [g])
    assert "Movsar Evloev vs Alexander Volkanovski" in message
    assert "\U0001F1F7\U0001F1FA Movsar Evloev" in message          # Russian flag
    assert "\U0001F1E6\U0001F1FA Alexander Volkanovski" in message  # Australian flag
    assert "Spread" not in message and "Total" not in message


def test_pickem_spread_shows_a_plain_zero():
    g = game("Home", "Away", start=FUTURE, books=[
        book("FanDuel", spreads=[outcome("Home", -105, 0.0), outcome("Away", -115, -0.0)]),
    ])
    [message] = format_sport_messages("NFL", [g])
    assert "<b>0</b>" in message
    assert "+0" not in message and "-0<" not in message


def test_game_without_odds_says_so():
    [message] = format_sport_messages("NHL", [game("Home", "Away", start=FUTURE)])
    assert "Odds not available yet" in message


def test_long_slates_split_into_messages_under_the_telegram_limit():
    games = [
        game(f"Home Team Number {i}", f"Away Team Number {i}", start=FUTURE, books=[
            book("FanDuel",
                 h2h=[outcome(f"Home Team Number {i}", -110), outcome(f"Away Team Number {i}", 100)],
                 spreads=[outcome(f"Home Team Number {i}", -110, -1.5), outcome(f"Away Team Number {i}", -110, 1.5)]),
        ])
        for i in range(60)
    ]
    messages = format_sport_messages("NFL", games)
    assert len(messages) > 1
    assert all(len(m) < 4096 for m in messages)
    assert all("(cont.)" in m for m in messages[1:])
    assert "(cont.)" not in messages[0]


def test_every_game_appears_exactly_once_across_split_messages():
    games = [
        game(f"Zed{i}", f"Yan{i}", start=FUTURE, books=[
            book("FanDuel", h2h=[outcome(f"Zed{i}", -110), outcome(f"Yan{i}", 100)]),
        ])
        for i in range(80)
    ]
    messages = format_sport_messages("NFL", games)
    combined = "\n".join(messages)
    for i in range(80):
        assert combined.count(f"Yan{i} @ Zed{i}") == 1
