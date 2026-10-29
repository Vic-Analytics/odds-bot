"""
stats.py - the numbers behind the dashboard, as plain functions.

Everything here takes plain lists/dicts and returns plain lists/dicts: no database,
no HTML. That keeps each calculation easy to test with a few hand-checked games.

Two ideas used throughout:

  * "What the odds said" is the win chance the odds imply with the sportsbooks'
    margin (the "vig") removed: the home, away and draw chances are scaled so they
    add up to 100%. Without that, every chance would look a few points too high.

  * Soccer odds are for the first 90 minutes, but the score we store can include
    extra time (status FINAL_AET / FINAL_PEN). A game that went to extra time was
    level after 90, so it counts as a draw here, and its score is left out of the
    totals and spread numbers.
"""

from collections import defaultdict
from datetime import datetime
from statistics import median
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
EXTRA_TIME = {"FINAL_AET", "FINAL_PEN"}
SMALL_SAMPLE = 30          # below this many games, a percentage is mostly luck
MIN_BOOKS = 3              # comparing sportsbooks needs at least this many prices

BUCKETS = [(0.0, 0.5, "under 50%"), (0.5, 0.6, "50-60%"), (0.6, 0.7, "60-70%"), (0.7, 1.01, "70% or more")]


# ---------- small helpers ----------

def implied(price):
    """American odds -> the win chance they imply (0 to 1)."""
    return 100.0 / (price + 100.0) if price > 0 else -price / (-price + 100.0)


def payout(price):
    """Dollars won on a $100 bet at this American price (not counting the stake)."""
    return float(price) if price > 0 else 10000.0 / -price


def mean(values):
    values = list(values)
    return sum(values) / len(values) if values else None


def rate(count, total):
    return count / total if total else None


# ---------- finished games ----------

def prepare(rows):
    """Add what the other functions need to each finished game (a dict from game_lines.sql).

    Adds: p_home / p_away / p_draw (the odds with the margin removed), favorite
    ("home" or "away"), fav_prob, winner ("home", "away" or "draw") and regulation
    (False when extra time makes the final score unusable for totals and spreads).
    Games without a usable moneyline are dropped.
    """
    games = []
    for row in rows:
        if row.get("home_prob") is None or row.get("away_prob") is None:
            continue
        total = row["home_prob"] + row["away_prob"] + (row.get("draw_prob") or 0.0)
        g = dict(row)
        g["p_home"], g["p_away"] = row["home_prob"] / total, row["away_prob"] / total
        g["p_draw"] = (row.get("draw_prob") or 0.0) / total
        g["favorite"] = "home" if g["p_home"] >= g["p_away"] else "away"
        g["fav_prob"] = max(g["p_home"], g["p_away"])
        went_long = row.get("status") in EXTRA_TIME
        g["regulation"] = not went_long
        if went_long or row["home_score"] == row["away_score"]:
            g["winner"] = "draw"
        else:
            g["winner"] = "home" if row["home_score"] > row["away_score"] else "away"
        games.append(g)
    return games


def by_sport(games):
    groups = defaultdict(list)
    for g in games:
        groups[g["sport_key"]].append(g)
    return groups


def calibration(games):
    """1. Do favorites win as often as the odds say? One row per (league, strength of favorite).

    sport_key None means "all leagues together".
    """
    groups = defaultdict(list)
    for g in games:
        bucket = next(label for low, high, label in BUCKETS if low <= g["fav_prob"] < high)
        groups[(None, bucket)].append(g)
        groups[(g["sport_key"], bucket)].append(g)
    order = [label for *_, label in BUCKETS]
    rows = [{"sport_key": sport, "bucket": bucket, "n": len(items),
             "said": mean(g["fav_prob"] for g in items),
             "actual": rate(sum(g["winner"] == g["favorite"] for g in items), len(items))}
            for (sport, bucket), items in groups.items()]
    return sorted(rows, key=lambda r: (r["sport_key"] is not None, r["sport_key"] or "", order.index(r["bucket"])))


def home_advantage(games):
    """7. How often the home team wins, compared with what the odds said."""
    rows = []
    for sport, items in sorted(by_sport(games).items()):
        n = len(items)
        rows.append({"sport_key": sport, "n": n,
                     "said": mean(g["p_home"] for g in items),
                     "home": rate(sum(g["winner"] == "home" for g in items), n),
                     "away": rate(sum(g["winner"] == "away" for g in items), n),
                     "draw": rate(sum(g["winner"] == "draw" for g in items), n)})
    return rows


def home_underdogs(games):
    """How often the home team won when the odds rated it the underdog."""
    rows = []
    for sport, items in sorted(by_sport(games).items(), key=lambda kv: (-len(kv[1]), kv[0])):
        dogs = [g for g in items if g["p_home"] < g["p_away"]]
        wins = sum(g["winner"] == "home" for g in dogs)
        rows.append({"sport_key": sport, "games": len(items), "dogs": len(dogs), "wins": wins,
                     "said": mean(g["p_home"] for g in dogs), "actual": rate(wins, len(dogs))})
    return rows


def totals(games):
    """5. Over/under: how often games go over the line, and how far the score lands from it."""
    rows = []
    for sport, items in sorted(by_sport(games).items()):
        used = [g for g in items if g.get("total_line") is not None and g["regulation"]]
        if not used:
            continue
        scored = [g["home_score"] + g["away_score"] for g in used]
        over = sum(s > g["total_line"] for s, g in zip(scored, used))
        under = sum(s < g["total_line"] for s, g in zip(scored, used))
        rows.append({"sport_key": sport, "n": len(used), "over": over, "under": under,
                     "push": len(used) - over - under, "over_rate": rate(over, over + under),
                     "avg_line": mean(g["total_line"] for g in used), "avg_total": mean(scored)})
    return rows


def spreads(games):
    """8. Point spreads: how often the favorite, the underdog and the home team cover."""
    rows = []
    for sport, items in sorted(by_sport(games).items()):
        used = [g for g in items if g.get("home_spread") is not None and g["regulation"]]
        if not used:
            continue
        fav = dog = push = home = 0
        for g in used:
            margin = g["home_score"] - g["away_score"] + g["home_spread"]     # >0: the home side covers
            if margin == 0:
                push += 1
                continue
            home += margin > 0
            if g["home_spread"] != 0:                                          # a pick'em has no favorite
                favorite_covers = (margin > 0) == (g["home_spread"] < 0)
                fav += favorite_covers
                dog += not favorite_covers
        rows.append({"sport_key": sport, "n": len(used), "push": push, "fav": fav, "dog": dog,
                     "fav_rate": rate(fav, fav + dog), "home_rate": rate(home, len(used) - push)})
    return rows


def draws(games):
    """9. Soccer: how often a game is level after 90 minutes, compared with the odds."""
    rows = []
    for sport, items in sorted(by_sport(games).items()):
        used = [g for g in items if g["p_draw"] > 0]
        if not used:
            continue
        rows.append({"sport_key": sport, "n": len(used), "said": mean(g["p_draw"] for g in used),
                     "actual": rate(sum(g["winner"] == "draw" for g in used), len(used))})
    return rows


# ---------- rest days ----------

def rest_gaps(events):
    """6. Days since each team's previous game in the database (Central calendar days).

    `events` is a list of (event_id, sport_key, commence_time, home_team, away_team).
    Returns {(event_id, "home" or "away"): days or None}. None means we have no earlier
    game for that team, so nothing is known: the first games in the database are never
    counted as rested. A gap of 1 is a back-to-back.
    """
    teams = defaultdict(list)
    for event_id, sport, commence, home, away in events:
        day = datetime.fromisoformat(commence.replace("Z", "+00:00")).astimezone(CENTRAL).date()
        teams[(sport, home)].append((commence, day, event_id, "home"))
        teams[(sport, away)].append((commence, day, event_id, "away"))
    gaps = {}
    for items in teams.values():
        previous = None
        for _, day, event_id, side in sorted(items):
            gaps[(event_id, side)] = (day - previous).days if previous else None
            previous = day
    return gaps


def rest_effect(games, gaps):
    """Do teams on a back-to-back win less than the odds expect? One row per (league, situation)."""
    groups = defaultdict(list)
    for g in games:
        for side in ("home", "away"):
            gap = gaps.get((g["event_id"], side))
            if gap is None or gap == 0:                     # unknown, or the second game of a doubleheader
                continue
            situation = "On a back-to-back" if gap == 1 else "Had a day or more off"
            groups[(g["sport_key"], situation)].append((g["p_" + side], g["winner"] == side))
    leagues_with_b2b = {sport for sport, situation in groups if situation == "On a back-to-back"}
    return [{"sport_key": sport, "situation": situation, "n": len(items),
             "said": mean(p for p, _ in items), "actual": rate(sum(w for _, w in items), len(items))}
            for (sport, situation), items in sorted(groups.items()) if sport in leagues_with_b2b]


def rest_totals(games, gaps):
    """Do totals go over more when a team is on a back-to-back? "Neither team is" needs both teams' rest to be known."""
    groups = defaultdict(list)
    for g in games:
        if g.get("total_line") is None or not g["regulation"]:
            continue
        home_gap, away_gap = gaps.get((g["event_id"], "home")), gaps.get((g["event_id"], "away"))
        if 1 in (home_gap, away_gap):
            situation = "A team is on a back-to-back"
        elif home_gap is None or away_gap is None:       # we can't tell whether the other team was rested
            continue
        else:
            situation = "Neither team is"
        groups[(g["sport_key"], situation)].append(g)
    leagues_with_b2b = {sport for sport, situation in groups if situation.startswith("A team")}
    rows = []
    for (sport, situation), items in sorted(groups.items()):
        if sport not in leagues_with_b2b:
            continue
        scored = [g["home_score"] + g["away_score"] for g in items]
        over = sum(s > g["total_line"] for s, g in zip(scored, items))
        under = sum(s < g["total_line"] for s, g in zip(scored, items))
        rows.append({"sport_key": sport, "situation": situation, "n": len(items),
                     "over_rate": rate(over, over + under),
                     "avg_vs_line": mean(s - g["total_line"] for s, g in zip(scored, items))})
    return rows


# ---------- sportsbooks ----------

def book_stats(rows):
    """2 and 3. Who has the best and worst prices, how far apart books are, and what shopping is worth.

    `rows` is (sport_key, event_id, bookmaker, outcome, price) for the newest pre-game
    moneyline of each game. A game-outcome is only compared when at least MIN_BOOKS books price it.

    Returns (books, leagues):
      books   - per sportsbook: prices quoted, how often it had the best / worst price (when
                prices differed), and its average gap from the all-books average in
                win-chance points (negative = it pays more than most).
      leagues - per league: outcomes compared, average and biggest gap between the best and
                worst book (win-chance points), and the average and biggest extra win per $100
                from taking the best price instead of an average book.
    """
    groups = defaultdict(list)
    for sport, event, book, outcome, price in rows:
        groups[(sport, event, outcome)].append((book, price))

    books = defaultdict(lambda: {"quotes": 0, "compared": 0, "best": 0, "worst": 0, "gap": 0.0})
    leagues = defaultdict(lambda: {"n": 0, "range_sum": 0.0, "range_max": 0.0, "gain_sum": 0.0, "gain_max": 0.0})
    for (sport, _, _), quotes in groups.items():
        if len(quotes) < MIN_BOOKS:
            continue
        probs = [implied(price) for _, price in quotes]
        pays = [payout(price) for _, price in quotes]
        best, worst, avg_prob = max(pays), min(pays), mean(probs)
        for (book, _), prob, pay in zip(quotes, probs, pays):
            entry = books[book]
            entry["quotes"] += 1
            entry["gap"] += (prob - avg_prob) * 100
            if best > worst:
                entry["compared"] += 1
                entry["best"] += pay == best
                entry["worst"] += pay == worst
        league = leagues[sport]
        spread = (max(probs) - min(probs)) * 100
        gain = max(0.0, best - mean(pays))                # (guards against floating-point dust)
        league["n"] += 1
        league["range_sum"] += spread
        league["range_max"] = max(league["range_max"], spread)
        league["gain_sum"] += gain
        league["gain_max"] = max(league["gain_max"], gain)

    book_rows = [{"book": book, "quotes": v["quotes"],
                  "best": rate(v["best"], v["compared"]), "worst": rate(v["worst"], v["compared"]),
                  "gap": v["gap"] / v["quotes"]} for book, v in books.items()]
    book_rows.sort(key=lambda r: (-(r["best"] or 0), r["book"]))
    league_rows = [{"sport_key": sport, "n": v["n"], "avg_range": v["range_sum"] / v["n"],
                    "max_range": v["range_max"], "avg_gain": v["gain_sum"] / v["n"], "max_gain": v["gain_max"]}
                   for sport, v in sorted(leagues.items())]
    return book_rows, league_rows


def book_margins(rows):
    """Which sportsbook charges the least margin (the "vig")?

    A sportsbook's margin on a game is how far its win chances add up past 100%: if the
    chances on every outcome sum to 104%, it keeps about 4%. Lower is better for you.
    Uses the same rows as book_stats. A book only counts for a game when it priced every
    outcome, and the game needs at least MIN_BOOKS such books.
    """
    games = defaultdict(lambda: defaultdict(dict))
    for sport, event, book, outcome, price in rows:
        games[(sport, event)][book][outcome] = price
    totals = defaultdict(lambda: {"games": 0, "margin": 0.0, "lowest": 0})
    for books in games.values():
        width = max(len(prices) for prices in books.values())
        full = {book: sum(implied(p) for p in prices.values()) for book, prices in books.items() if len(prices) == width}
        if len(full) < MIN_BOOKS:
            continue
        lowest = min(full.values())
        for book, total in full.items():
            entry = totals[book]
            entry["games"] += 1
            entry["margin"] += (total - 1) * 100
            entry["lowest"] += total - lowest < 1e-9
    rows = [{"book": book, "games": v["games"], "avg_margin": v["margin"] / v["games"],
             "lowest": v["lowest"] / v["games"]} for book, v in totals.items()]
    return sorted(rows, key=lambda r: (r["avg_margin"], r["book"]))


# ---------- how old the prices are ----------

STALE_MINUTES = 60


def parse_utc(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def price_ages(rows):
    """6. How old were each sportsbook's prices when we pulled them?

    `rows` is (bookmaker, pulled_at, last_update). Age is the minutes between the
    sportsbook last changing the price and our pull. Stalest books first.
    """
    ages = defaultdict(list)
    for book, pulled, updated in rows:
        if pulled and updated:
            ages[book].append(max(0.0, (parse_utc(pulled) - parse_utc(updated)).total_seconds() / 60))
    result = [{"book": book, "n": len(values), "median": median(values), "oldest": max(values),
               "stale": rate(sum(v > STALE_MINUTES for v in values), len(values))} for book, values in ages.items()]
    return sorted(result, key=lambda r: (-r["median"], r["book"]))


# ---------- line movement ----------

MIN_MOVE_HOURS = 2         # two pulls closer together than this are not a real movement
MOVE_THRESHOLD = 0.01      # a side "gained" only if its chance rose by at least 1 point


def _chances(by_outcome, home, away):
    """Home and away chances of one snapshot with the margin removed (None if a side is missing)."""
    if home not in by_outcome or away not in by_outcome:
        return None
    total = by_outcome[home] + by_outcome[away] + by_outcome.get("Draw", 0.0)
    return {"home": by_outcome[home] / total, "away": by_outcome[away] / total}


def line_moves(rows):
    """1. How did each game's moneyline move between its first and its last pre-game pull?

    `rows` is (sport_key, event_id, commence_time, pulled_at, home_team, away_team, outcome, prob),
    one per outcome of every pre-game snapshot. Only games pulled at least MIN_MOVE_HOURS apart
    count. Returns one dict per game: the side whose chance rose the most (`mover`), how much
    (`rise`, as a fraction), the biggest change either side had (`size`), and `toward` = that
    side when it rose by at least MOVE_THRESHOLD, else None.
    """
    snapshots = defaultdict(lambda: defaultdict(dict))
    meta = {}
    for sport, event, commence, pulled, home, away, outcome, prob in rows:
        snapshots[event][pulled][outcome] = prob
        meta[event] = (sport, commence, home, away)
    moves = []
    for event, by_time in snapshots.items():
        times = sorted(by_time)
        if len(times) < 2 or (parse_utc(times[-1]) - parse_utc(times[0])).total_seconds() < MIN_MOVE_HOURS * 3600:
            continue
        sport, commence, home, away = meta[event]
        first, last = _chances(by_time[times[0]], home, away), _chances(by_time[times[-1]], home, away)
        if not first or not last:
            continue
        rises = {side: last[side] - first[side] for side in ("home", "away")}
        mover = max(rises, key=rises.get)
        moves.append({"event_id": event, "sport_key": sport, "commence_time": commence, "home_team": home,
                      "away_team": away, "mover": mover, "mover_team": home if mover == "home" else away,
                      "rise": rises[mover], "size": max(abs(v) for v in rises.values()),
                      "toward": mover if rises[mover] >= MOVE_THRESHOLD else None,
                      "first": first[mover], "last": last[mover], "last_chances": last})
    return moves


def move_summary(moves, games):
    """Per league: how far lines move, and whether the side the market moved toward won more than the odds said."""
    finished = {g["event_id"]: g for g in games}
    per_league = defaultdict(list)
    for move in moves:
        per_league[move["sport_key"]].append(move)
    rows = []
    for sport, items in sorted(per_league.items()):
        decided = [(m, finished[m["event_id"]]) for m in items if m["toward"] and m["event_id"] in finished]
        rows.append({"sport_key": sport, "n": len(items),
                     "avg_move": mean(m["size"] for m in items) * 100, "biggest": max(m["size"] for m in items) * 100,
                     "moved": sum(1 for m in items if m["toward"]), "decided": len(decided),
                     "said": mean(m["last_chances"][m["toward"]] for m, _ in decided),
                     "actual": rate(sum(g["winner"] == m["toward"] for m, g in decided), len(decided))})
    return rows


def biggest_moves(moves, limit=8):
    return sorted(moves, key=lambda m: -m["size"])[:limit]


# ---------- upsets ----------

def biggest_upsets(games, limit=10):
    """3. The finished games where the side the odds gave the smallest chance won."""
    upsets = []
    for g in games:
        if g["winner"] in ("home", "away") and g["winner"] != g["favorite"]:
            upsets.append(dict(g, chance=g["p_" + g["winner"]]))
    return sorted(upsets, key=lambda u: (u["chance"], u["commence_time"]))[:limit]


def books_per_game(rows):
    """Average number of sportsbooks pricing a game, per league."""
    seen = defaultdict(set)
    for sport, event, book, _, _ in rows:
        seen[(sport, event)].add(book)
    per_league = defaultdict(list)
    for (sport, _), books in seen.items():
        per_league[sport].append(len(books))
    return {sport: mean(counts) for sport, counts in per_league.items()}
