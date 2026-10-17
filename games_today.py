"""
games_today.py - keep only the games that start TODAY in Central time.

The Odds API gives start times in UTC (e.g. 2026-10-17T00:30:00Z). A game at
7:30 PM Central on Oct 16 is already "Oct 17" in UTC, so we can't just compare
dates. We convert each start time to Central first, then check the date.

Usage (these are safe for your quota, see notes):

    python games_today.py            FREE: lists today's games for every sport
    python games_today.py NHL        fetches NHL odds (2 credits, only if the
                                     NHL has a game today) and shows a summary
"""

import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import MARKETS, SPORTS, markets_for
from odds_api import fetch_events, fetch_odds

# "America/Chicago" is the official name for US Central time. Using the name
# (instead of "UTC-6") means daylight saving time is handled automatically.
CENTRAL = ZoneInfo("America/Chicago")


def start_time_central(game):
    """Convert a game's UTC start time to a datetime in Central time."""
    # fromisoformat understands the "...Z" format the API uses.
    return datetime.fromisoformat(game["commence_time"]).astimezone(CENTRAL)


def filter_today(games):
    """Return only the games that start today (Central), earliest first."""
    now = datetime.now(CENTRAL)
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_tomorrow = start_of_today + timedelta(days=1)

    todays = [
        game for game in games
        if start_of_today <= start_time_central(game) < start_of_tomorrow
    ]
    return sorted(todays, key=start_time_central)


def fetch_todays_games_with_odds(sport_key, credits_left=None, markets=MARKETS):
    """Get today's games WITH odds for one sport, spending credits only if needed.

    1. Ask the FREE events endpoint what's scheduled.
    2. If nothing starts today, stop. Zero credits spent.
    3. Otherwise make ONE odds call and keep today's games.

    `credits_left` is what we last knew about your monthly quota. If it's too
    low to pay for the call, we refuse instead of making a call that fails.

    Returns (games_today, credits_remaining). credits_remaining is None if we
    skipped the odds call.
    """
    if not filter_today(fetch_events(sport_key)):
        return [], None

    # Each market in the request costs 1 credit.
    cost = len(markets.split(","))
    if credits_left is not None and credits_left < cost:
        raise RuntimeError(
            f"Only {credits_left} Odds API credits left (a call costs "
            f"{cost}), so I skipped it."
        )

    games, remaining = fetch_odds(sport_key, markets)
    return filter_today(games), remaining


def describe(game):
    """One readable line, e.g. '7:00 PM  Dallas Stars vs Utah Hockey Club'."""
    time_text = start_time_central(game).strftime("%I:%M %p").lstrip("0")
    return f"{time_text} CT  {game['away_team']} @ {game['home_team']}"


# Runs only when you start this file directly, not when imported.
if __name__ == "__main__":
    if len(sys.argv) > 1:
        # --- One sport: spend credits (only if there are games today) ---
        name = next((n for n in SPORTS if n.lower() == " ".join(sys.argv[1:]).lower()), None)
        if name is None:
            raise SystemExit(f"Unknown sport. Choose from: {', '.join(SPORTS)}")

        games, remaining = fetch_todays_games_with_odds(SPORTS[name], None, markets_for(name))
        if remaining is None:
            print(f"{name}: no games today, so no credits were spent.")
        else:
            print(f"{name}: {len(games)} game(s) today. Credits remaining: {remaining}")
            for game in games:
                print(f"  {describe(game)}   ({len(game['bookmakers'])} sportsbooks)")
    else:
        # --- All sports: only the FREE events endpoint, costs 0 credits ---
        print("Today's games in Central time (free check, 0 credits):\n")
        for name, key in SPORTS.items():
            todays = filter_today(fetch_events(key))
            print(f"{name}: {len(todays)} game(s)")
            for game in todays:
                print(f"  {describe(game)}")
