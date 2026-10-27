"""Small builders for fake games, so tests never touch the real APIs."""

import copy


def outcome(name, price, point=None):
    result = {"name": name, "price": price}
    if point is not None:
        result["point"] = point
    return result


def book(title, **markets):
    """book("FanDuel", h2h=[outcome(...), ...], spreads=[...], totals=[...])"""
    return {
        "key": title.lower().replace(" ", "").replace(".", ""),   # like the API's "draftkings"
        "title": title,
        "last_update": "2026-10-28T13:40:00Z",
        "markets": [
            {"key": key, "last_update": "2026-10-28T13:40:00Z", "outcomes": outcomes}
            for key, outcomes in markets.items()
        ],
    }


def game(home, away, start="2026-10-17T18:00:00Z", books=None, game_id=None):
    return {
        "id": game_id or f"{home}-{away}",
        "home_team": home,
        "away_team": away,
        "commence_time": start,
        "bookmakers": copy.deepcopy(books or []),
    }
