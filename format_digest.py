"""
format_digest.py - turn raw game data into nice Telegram messages.

For each game we show the BEST available line across all sportsbooks:
  - Moneyline: the highest price for each team (+150 beats +130, -105 beats -110)
  - Spread:    the most common point spread, then the best price at that spread

Test it for FREE (no credits) using the raw_odds.json file saved in Step 3:

    python format_digest.py          prints a preview in the terminal
    python format_digest.py send     also sends the preview to Telegram
"""

import html
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from config import SPORT_EMOJI, SPORTS
from games_today import CENTRAL, start_time_central

# Telegram rejects messages over 4096 characters. We stay well under that and,
# if one sport has a LOT of games, split it into several messages.
MAX_MESSAGE_LENGTH = 3800


def _collect_offers(game, market_key):
    """Gather every sportsbook's offer for one market.

    Returns a dictionary like:
        {"Colorado Avalanche": [(point, price, "DraftKings"), (point, price, "FanDuel"), ...]}
    `point` is the spread number (None for moneyline).
    """
    offers = {}
    for book in game["bookmakers"]:
        for market in book["markets"]:
            if market["key"] != market_key:
                continue
            for outcome in market["outcomes"]:
                offers.setdefault(outcome["name"], []).append(
                    (outcome.get("point"), outcome["price"], book["title"])
                )
    return offers


def best_moneylines(game):
    """For each outcome (team, or 'Draw' in soccer): (best_price, book)."""
    best = {}
    for name, offers in _collect_offers(game, "h2h").items():
        price, book = max(((price, book) for _, price, book in offers), key=lambda x: x[0])
        best[name] = (price, book)
    return best


def best_spreads(game):
    """For each team: (point, best_price_at_that_point, book)."""
    best = {}
    for name, offers in _collect_offers(game, "spreads").items():
        # How many books use each spread number? Pick the most common one
        # (if tied, the number closest to zero).
        counts = Counter(point for point, _, _ in offers)
        common_point = max(counts, key=lambda p: (counts[p], -abs(p)))
        # Among books offering that number, take the best price.
        price, book = max(
            ((price, book) for point, price, book in offers if point == common_point),
            key=lambda x: x[0],
        )
        best[name] = (common_point, price, book)
    return best


def _format_game(game, is_soccer, is_fight=False):
    """Build the text block for one game."""
    e = html.escape  # makes names like "Brighton & Hove" safe inside HTML

    time_text = start_time_central(game).strftime("%I:%M %p").lstrip("0")
    away, home = game["away_team"], game["home_team"]

    # US sports are written "away @ home". Soccer is written "home vs away".
    # Fights have no home/away, so they are written "fighter vs fighter".
    if is_soccer:
        matchup = f"{e(home)} vs {e(away)}"
    elif is_fight:
        matchup = f"{e(away)} vs {e(home)}"
    else:
        matchup = f"{e(away)} @ {e(home)}"

    # The headline: one bold line with the time and the matchup, so each
    # game's start is easy to spot while scrolling.
    headline = f"<b>{time_text} · {matchup}</b>"

    moneylines = best_moneylines(game)
    spreads = best_spreads(game)
    if not moneylines and not spreads:
        return f"{headline}\n<i>Odds not available yet</i>"

    # Teams in the same order as the headline (with "Draw" in the middle for soccer).
    order = [home, "Draw", away] if is_soccer else [away, home]

    # Build each section (Moneyline, Spread) as a label plus one line per team.
    sections = []

    ml_lines = []
    for name in order:
        if name in moneylines:
            price, book = moneylines[name]
            ml_lines.append(f"{e(name)}  <b>{int(price):+d}</b>  ({e(book)})")
    if ml_lines:
        sections.append("<i>Moneyline</i>\n" + "\n".join(ml_lines))

    sp_lines = []
    for name in order:
        if name in spreads:
            point, price, book = spreads[name]
            sp_lines.append(
                f"{e(name)}  <b>{point:+g}</b>  ({int(price):+d}, {e(book)})"
            )
    if sp_lines:
        sections.append("<i>Spread</i>\n" + "\n".join(sp_lines))

    # A blank line between sections gives the odds room to breathe.
    # <blockquote> makes Telegram draw a vertical bar beside them, which
    # groups the odds under their headline.
    return f"{headline}\n<blockquote>" + "\n\n".join(sections) + "</blockquote>"


def format_sport_messages(sport_name, games):
    """Turn one sport's games into a LIST of message strings (usually just one).

    Returns an empty list if there are no games, so nothing gets sent.
    """
    if not games:
        return []

    # Any sport whose key starts with "soccer_" gets the soccer layout.
    is_soccer = SPORTS.get(sport_name, "").startswith("soccer_")
    emoji = SPORT_EMOJI.get(sport_name, "\U0001F3C6")
    date_text = datetime.now(CENTRAL).strftime("%a, %b %d").replace(" 0", " ")

    header = f"{emoji} <b>{html.escape(sport_name)}</b> — {date_text}"
    is_fight = SPORTS.get(sport_name, "").startswith("mma_")
    blocks = [_format_game(game, is_soccer, is_fight) for game in games]

    # Pack games into messages, starting a new message when one gets too long.
    continued_header = header.replace("</b>", "</b> (cont.)", 1)
    messages = []
    current = header
    games_in_current = 0
    for block in blocks:
        if len(current) + len(block) + 2 > MAX_MESSAGE_LENGTH and games_in_current > 0:
            messages.append(current)
            current = continued_header
            games_in_current = 0
        current += "\n\n" + block
        games_in_current += 1
    messages.append(current)
    return messages


def plain_preview(message):
    """Strip the HTML tags so the terminal preview is readable."""
    return html.unescape(re.sub(r"<[^>]+>", "", message))


# Runs only when you start this file directly, not when imported.
if __name__ == "__main__":
    # Use the raw NFL data saved in Step 3. No API call, no credits.
    raw_file = Path(__file__).with_name("raw_odds.json")
    if not raw_file.exists():
        raise SystemExit("raw_odds.json not found. Run: python odds_api.py NFL")

    # (These upcoming games aren't necessarily today's, which is fine for a
    # formatting test. We just show the first 3.)
    sample_games = json.loads(raw_file.read_text(encoding="utf-8"))[:3]
    messages = format_sport_messages("NFL", sample_games)

    for message in messages:
        print(plain_preview(message))
        print("\n" + "-" * 40 + "\n")

    if len(sys.argv) > 1 and sys.argv[1] == "send":
        from telegram_bot import send_message
        for message in messages:
            send_message(message)
        print("Sent to Telegram!")
