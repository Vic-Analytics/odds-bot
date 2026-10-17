"""
odds_api.py - everything related to talking to The Odds API.

Run this file directly to fetch and print raw odds for ONE sport:

    python odds_api.py            (defaults to NFL)
    python odds_api.py NHL

Each run costs 2 credits of your free monthly quota (2 markets x 1 region).
"""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from config import MARKETS, SPORTS  # the settings live in config.py

ODDS_API_KEY = os.environ.get("ODDS_API_KEY")


def _raise_if_api_error(response):
    """Turn the most common failures into messages a human can understand."""
    if response.status_code == 401:
        raise RuntimeError("Odds API rejected the key (401). Check ODDS_API_KEY in .env.")
    if response.status_code == 429:
        raise RuntimeError("Odds API rate limit or quota used up (429).")
    if not response.ok:
        raise RuntimeError(f"Odds API error {response.status_code}: {response.text[:200]}")


def fetch_events(sport_key):
    """List upcoming games (teams + start times, NO odds) for one sport.

    This endpoint is FREE: it does not use any of your credits. We use it to
    find out whether a sport has games today BEFORE paying credits for odds.
    """
    if not ODDS_API_KEY:
        raise RuntimeError("ODDS_API_KEY is missing from .env")

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/events"
    response = requests.get(
        url, params={"apiKey": ODDS_API_KEY, "dateFormat": "iso"}, timeout=20
    )
    _raise_if_api_error(response)
    return response.json()


def fetch_scores(sport_key):
    """Get live scores for one sport. Costs 1 credit.

    Because we don't ask for past days (no "daysFrom"), the API returns only
    games that are live or upcoming. Live games include their current score.

    Returns (scores, credits_remaining).
    """
    if not ODDS_API_KEY:
        raise RuntimeError("ODDS_API_KEY is missing from .env")

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores"
    response = requests.get(
        url, params={"apiKey": ODDS_API_KEY, "dateFormat": "iso"}, timeout=20
    )
    _raise_if_api_error(response)
    return response.json(), response.headers.get("x-requests-remaining")


def fetch_odds(sport_key, markets=MARKETS):
    """Ask The Odds API for upcoming games + odds for one sport.

    `markets` is a comma-separated string such as "h2h,spreads". Each market
    costs 1 credit.

    Returns (games, credits_remaining):
      games             - a list of games (each game is a dictionary)
      credits_remaining - how many free credits you have left this month
    """
    if not ODDS_API_KEY:
        raise RuntimeError("ODDS_API_KEY is missing from .env")

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"

    # These become the "?apiKey=...&regions=..." part of the URL.
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",             # US sportsbooks
        "markets": markets,
        "oddsFormat": "american",    # -110, +150 style (not decimal)
        "dateFormat": "iso",         # times like 2026-10-16T23:00:00Z (UTC)
    }

    response = requests.get(url, params=params, timeout=20)

    _raise_if_api_error(response)

    # The API reports your remaining quota in a response "header" (extra info
    # that travels with the data).
    remaining = response.headers.get("x-requests-remaining")
    return response.json(), remaining


# Runs only when you start this file directly, not when imported.
if __name__ == "__main__":
    name = sys.argv[1].upper() if len(sys.argv) > 1 else "NFL"
    if name not in SPORTS:
        raise SystemExit(f"Unknown sport '{name}'. Choose from: {', '.join(SPORTS)}")

    games, remaining = fetch_odds(SPORTS[name])

    print(f"{name}: the API returned {len(games)} upcoming games.")
    print(f"Credits remaining this month: {remaining}")

    # Save the complete raw response so you can open it and look around.
    Path(__file__).with_name("raw_odds.json").write_text(
        json.dumps(games, indent=2), encoding="utf-8"
    )
    print("Full response saved to raw_odds.json")

    if games:
        # indent=2 makes the JSON readable. We only show the first 2500
        # characters of the first game because it's long (many sportsbooks).
        print("\n--- First game (shortened) ---")
        print(json.dumps(games[0], indent=2)[:2500])
    else:
        print("No games right now (the sport may be out of season).")
