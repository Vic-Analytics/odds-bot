"""
config.py - the settings you are most likely to change. No secrets here
(those stay in .env).

TO ADD A SPORT: add one line to SPORTS below. Find sport keys with a free call:
    https://api.the-odds-api.com/v4/sports?apiKey=YOUR_KEY
(Keys starting with "soccer_" automatically get the home-vs-away layout and a
Draw row.) Optionally add an emoji for it in SPORT_EMOJI.

TO REMOVE A SPORT: delete its line (or put a # in front of it).
"""

# Friendly name (shown in the Telegram message) -> the "sport key" The Odds
# API uses. The digest sends sports in this order.
SPORTS = {
    "NFL": "americanfootball_nfl",
    "NBA": "basketball_nba",
    "MLB": "baseball_mlb",
    "NHL": "icehockey_nhl",
    "WNBA": "basketball_wnba",
    "UFC / MMA": "mma_mixed_martial_arts",       # the API's MMA feed (see MIN_BOOKMAKERS)
    "EPL": "soccer_epl",                          # English Premier League
    "Champions League": "soccer_uefa_champs_league",
    "Europa League": "soccer_uefa_europa_league",
    "La Liga": "soccer_spain_la_liga",
    "Serie A": "soccer_italy_serie_a",
    "Bundesliga": "soccer_germany_bundesliga",
    "Ligue 1": "soccer_france_ligue_one",
    "MLS": "soccer_usa_mls",
}

# Emoji shown in each message header. Anything not listed gets a trophy.
SPORT_EMOJI = {
    "NFL": "\U0001F3C8", "NBA": "\U0001F3C0", "MLB": "⚾", "NHL": "\U0001F3D2",
    "WNBA": "\U0001F3C0", "UFC / MMA": "\U0001F94A",
    "EPL": "⚽", "Champions League": "⚽", "Europa League": "⚽",
    "La Liga": "⚽", "Serie A": "⚽", "Bundesliga": "⚽",
    "Ligue 1": "⚽", "MLS": "⚽",
}

# Markets we ask for: "h2h" is moneyline, "spreads" is the point spread.
# The message layout can display moneyline, spreads and totals. Adding a
# market here costs 1 more credit per sport that has games that day.
MARKETS = "h2h,spreads"

# Sports that should use different markets than the default above.
# MMA has no point spread, so asking for it would waste a credit every time.
SPORT_MARKETS = {
    "UFC / MMA": "h2h",
}

# The MMA feed mixes UFC with small shows and far-off rumored fights, and the
# API can't tell them apart. Fights offered by only 1-3 sportsbooks are
# usually small shows or placeholders. So for these sports, we hide fights
# with fewer sportsbooks than the number below. (Not perfect: a non-UFC card
# with good coverage can still get through.)
MIN_BOOKMAKERS = {
    "UFC / MMA": 4,
}

# Each odds request costs (number of markets) x (number of regions) credits.
# We use 1 region ("us"), so the cost is just the number of markets.
#
# Soccer leagues use moneyline (with the draw) plus the over/under on total
# goals, instead of a point spread. This costs the same as before.
SOCCER_MARKETS = "h2h,totals"


def markets_for(sport_name):
    """The markets string to request for a sport (its override, or the default)."""
    if sport_name in SPORT_MARKETS:
        return SPORT_MARKETS[sport_name]
    if SPORTS.get(sport_name, "").startswith("soccer_"):
        return SOCCER_MARKETS
    return MARKETS

# If your remaining monthly credits fall below this, the bot adds a warning
# to your Telegram digest.
LOW_CREDITS_WARNING = 50
