"""Tests for team emoji, soccer kit colors and UFC flags."""

from collections import Counter

import pytest

import soccer_emoji
import ufc_flags
from team_emoji import MLB, NBA, NFL, NHL, TEAM_EMOJI, WNBA, emoji_for, team_label


# ---------- the dictionaries themselves ----------

@pytest.mark.parametrize("name, table, expected_size", [
    ("NFL", NFL, 32),
    ("NBA", NBA, 30),
    ("MLB", MLB, 30),
    ("NHL", NHL, 33),   # 32 teams + the "Hockey Club" alias for Utah
    ("WNBA", WNBA, 16), # 15 teams + the future Houston team
])
def test_each_league_has_every_team(name, table, expected_size):
    assert len(table) == expected_size
    assert TEAM_EMOJI[name] is table


@pytest.mark.parametrize("name, table", [("NFL", NFL), ("NBA", NBA), ("MLB", MLB), ("NHL", NHL), ("WNBA", WNBA)])
def test_no_two_teams_in_a_league_share_an_emoji(name, table):
    counts = Counter(table.values())
    duplicates = {e for e, c in counts.items() if c > 1}
    # Utah's hockey team has used two names on purpose.
    if name == "NHL":
        duplicates.discard(table["Mammoth"])
    assert not duplicates, f"{name} reuses: {duplicates}"


# ---------- matching names to emoji ----------

def test_matching_works_on_the_nickname():
    assert emoji_for("NFL", "Houston Texans") == NFL["Texans"]
    assert emoji_for("NBA", "Portland Trail Blazers") == NBA["Trail Blazers"]
    assert emoji_for("NHL", "Vegas Golden Knights") == NHL["Golden Knights"]
    assert emoji_for("MLB", "Boston Red Sox") == MLB["Red Sox"]
    assert emoji_for("MLB", "Chicago White Sox") == MLB["White Sox"]


def test_different_spellings_of_the_city_give_the_same_emoji():
    assert emoji_for("NBA", "LA Clippers") == emoji_for("NBA", "Los Angeles Clippers")
    assert emoji_for("NHL", "St. Louis Blues") == emoji_for("NHL", "St Louis Blues")
    assert emoji_for("MLB", "Oakland Athletics") == emoji_for("MLB", "Athletics") == MLB["Athletics"]
    assert emoji_for("NHL", "Utah Mammoth") == emoji_for("NHL", "Utah Hockey Club")


def test_same_nickname_in_different_leagues_does_not_mix():
    assert emoji_for("NFL", "New York Giants") != emoji_for("MLB", "San Francisco Giants")
    assert emoji_for("NFL", "Carolina Panthers") != emoji_for("NHL", "Florida Panthers")


def test_unknown_team_or_league_gives_no_emoji():
    assert emoji_for("NFL", "Made Up Squad") == ""
    assert emoji_for("Boxing", "Anyone") == ""


def test_nickname_must_be_a_whole_word_at_the_end():
    # "Kings" must not match a name that merely ends in the same letters.
    assert emoji_for("NHL", "Bookings") == ""


# ---------- team_label: what actually goes on the odds rows ----------

def test_label_puts_emoji_before_the_name():
    assert team_label("NFL", "Houston Texans") == f"{NFL['Texans']} Houston Texans"


def test_label_for_unmapped_league_is_just_the_name():
    assert team_label("Boxing", "Anyone") == "Anyone"


def test_soccer_draw_gets_two_handshakes_so_it_lines_up_with_the_clubs():
    assert team_label("EPL", "Draw") == "\U0001F91D\U0001F91D Draw"


def test_draw_outside_soccer_stays_plain():
    assert team_label("NFL", "Draw") == "Draw"


def test_soccer_label_uses_kit_colors():
    assert team_label("EPL", "Arsenal") == "\U0001F534⚪ Arsenal"          # two-color kit


def test_one_color_kits_show_the_dot_twice_and_unknown_clubs_two_balls():
    assert team_label("EPL", "Liverpool") == "\U0001F534\U0001F534 Liverpool"
    assert team_label("EPL", "Totally Unknown FC") == "⚽⚽ Totally Unknown FC"


def test_every_soccer_label_starts_with_exactly_two_emoji():
    names = ["Arsenal", "Liverpool", "Chelsea", "Real Madrid", "Draw", "Totally Unknown FC", "Inter Miami CF"]
    for name in names:
        prefix = team_label("EPL", name).split(" ", 1)[0]
        assert len(prefix) == 2, f"{name!r} -> {prefix!r}"


def test_mma_label_uses_flag_or_nothing():
    assert team_label("UFC / MMA", "Merab Dvalishvili") == "\U0001F1EC\U0001F1EA Merab Dvalishvili"
    assert team_label("UFC / MMA", "Nobody Known") == "Nobody Known"


# ---------- soccer name matching ----------

@pytest.mark.parametrize("api_name, canonical", [
    ("Brighton & Hove Albion", "Brighton and Hove Albion"),
    ("CA Osasuna", "Osasuna"),
    ("Atalanta BC", "Atalanta"),
    ("FSV Mainz 05", "Mainz 05"),
    ("Real Racing Club de Santander", "Racing Santander"),
    ("Atletico de Madrid", "Atlético Madrid"),
])
def test_soccer_spelling_variants_map_to_the_same_colors(api_name, canonical):
    assert soccer_emoji.soccer_emoji(api_name) == soccer_emoji.soccer_emoji(canonical)
    assert soccer_emoji.soccer_emoji(api_name) != "⚽"


def test_unmapped_soccer_club_is_reported_in_the_log(capsys):
    assert soccer_emoji.soccer_emoji("Totally Unknown FC") == "⚽"
    assert "unmapped soccer team: Totally Unknown FC" in capsys.readouterr().out


# ---------- UFC flags ----------

def test_ufc_matching_ignores_accents_punctuation_and_jr():
    assert ufc_flags.fighter_flag("Jiří Procházka") == "\U0001F1E8\U0001F1FF"
    assert ufc_flags.fighter_flag("Raul Rosas Jr") == ufc_flags.fighter_flag("Raul Rosas Jr.")
    assert ufc_flags.fighter_flag("sergei pavlovich") != ""


def test_ufc_alternate_spellings():
    assert ufc_flags.fighter_flag("Alex Volkanovski") == ufc_flags.fighter_flag("Alexander Volkanovski")
    assert ufc_flags.fighter_flag("Joseph Pyfer") == ufc_flags.fighter_flag("Joe Pyfer")


def test_unmapped_fighter_gets_no_flag_and_is_logged(capsys):
    assert ufc_flags.fighter_flag("Nobody Known") == ""
    assert "unmapped fighter: Nobody Known" in capsys.readouterr().out
