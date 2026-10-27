"""
names.py - decide whether two team names mean the same team.

Different sources spell teams differently: The Odds API says "Los Angeles
Kings", the NHL's own feed says just "Kings", ESPN says "Internazionale" where
the Odds API says "Inter Milan". Final scores come from those other sources, so
before a score can be attached to a game, the names have to be matched.

This reuses the rules already built for the emoji:
  * US leagues (NFL, NBA, MLB, NHL, WNBA): both names must end in the same
    team nickname from team_emoji.py ("Kings" == "Los Angeles Kings").
  * Soccer: soccer_emoji.py's aliases and cleaning (accents, "&", "FC", "CF"...
    are ignored), then one name may be a shortened form of the other
    ("Kairat Almaty" == "FC Kairat").
"""

import soccer_emoji
from config import SPORTS
from team_emoji import nickname_for

# sport_key -> the friendly name used in config.py and team_emoji.py ("icehockey_nhl" -> "NHL")
SPORT_NAME_BY_KEY = {key: name for name, key in SPORTS.items()}


# Spellings used by the free score sources (mostly ESPN) that differ from The
# Odds API's. Left side: the score source's name. Right side: the Odds API's.
RESULT_ALIASES = {
    "FC Cologne": "1. FC Köln",
    "Hamburg SV": "Hamburger SV",
    "Lens": "RC Lens",
    "Stade Rennais": "Rennes",
    "Red Bull New York": "New York Red Bulls",
    # European cups
    "Bodo/Glimt": "Bodø/Glimt",
    "LASK Linz": "LASK",
    "Slavia Prague": "Slavia Praha",
    "Sporting CP": "Sporting Lisbon",
    "Jagiellonia Bialystok": "Jagiellonia Białystok",
    "Olympiacos": "Olympiakos Piraeus",
    "Omonia Nicosia": "Omonoia FC",
    "Union St.-Gilloise": "Union Saint-Gilloise",
    "AGF": "AGF Aarhus",
    "Ajax Amsterdam": "Ajax",
    "CSU Craiova": "Universitatea Craiova",
    "F.C. København": "FC Copenhagen",
    "FC Nordsjælland": "FC Nordsjaelland",
    "Heart of Midlothian": "Hearts",
    "KAA Gent": "Gent",
    "Sint-Truidense": "Sint Truiden",
}


def _soccer_words(name):
    """The meaningful words of a club name, after applying the known aliases."""
    canonical = RESULT_ALIASES.get(name, name)
    canonical = soccer_emoji.SOCCER_ALIASES.get(canonical, canonical)
    return soccer_emoji._norm(canonical).split()


def _soccer_same(a, b):
    words_a, words_b = _soccer_words(a), _soccer_words(b)
    if not words_a or not words_b:
        return False
    if words_a == words_b:
        return True
    # One name is a shortened form of the other: every word of the shorter
    # name appears in the longer one. Very short names must match exactly.
    shorter, longer = sorted((words_a, words_b), key=len)
    return len(" ".join(shorter)) >= 5 and set(shorter) <= set(longer)


def same_team(sport_key, name_a, name_b):
    """True if the two names are the same team in this league (sport_key)."""
    if not name_a or not name_b:
        return False
    if sport_key.startswith("soccer_"):
        return _soccer_same(name_a, name_b)

    sport_name = SPORT_NAME_BY_KEY.get(sport_key)
    nick_a, nick_b = nickname_for(sport_name, name_a), nickname_for(sport_name, name_b)
    if nick_a and nick_b:
        return nick_a == nick_b
    # A league without a nickname list: fall back to the cleaned-up full names.
    return soccer_emoji._norm(name_a) == soccer_emoji._norm(name_b)
