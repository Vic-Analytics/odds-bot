"""
demo_data.py - builds a SYNTHETIC odds database for the public demo page.

Everything here is made up. The league and team names are the real public ones and the
sportsbooks are real brands, but every price, line, score and date is generated from a
seeded random number generator. Nothing is read from the odds history, the private data
repo, the bot's data folder or the internet.

How the fake world works, so the page looks like a real season of data:
  * Every team has a hidden strength. It decides who is likely to win.
  * Each game is priced by 6 to 10 sportsbooks, each with its own margin ("vig") and its
    own small disagreement with the others. One or two books often have stale prices.
  * Every game is priced twice, on the mornings before and of the game. The second price
    has learned a little about the true strength, so the market "moves" like a real one.
  * Scores are drawn from the same hidden strengths, so favorites usually win but upsets,
    overtime games and soccer draws happen.

The generator uses its own tiny random number generator (below) and only adds, multiplies
and divides, so the same seed gives the same database on every computer and Python version.
That is what lets a test check that the committed demo page is up to date.

    from demo_data import build_database
    build_database("demo.db")            # -> a SQLite file shaped exactly like data/odds.db
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import storage  # noqa: E402
from central_time import CENTRAL  # noqa: E402
from config import SPORTS, markets_for  # noqa: E402

DEMO_SEED = 2026
DEMO_NOW = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)       # the "present" of the demo: 9 AM Central on Nov 14
FIRST_GAME_DAY = date(2026, 10, 17)                                  # four weeks of finished games before it
SOURCE_NAME = "demo"
EVENT_PREFIX = "demo-"
UTC = timezone.utc
ISO = "%Y-%m-%dT%H:%M:%SZ"


# ---------- a tiny deterministic random number generator ----------

class Rng:
    """splitmix64: small, fast and identical everywhere. Only integer math, then one division."""

    MASK = (1 << 64) - 1

    def __init__(self, seed):
        self.state = seed & self.MASK

    def _next(self):
        self.state = (self.state + 0x9E3779B97F4A7C15) & self.MASK
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & self.MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & self.MASK
        return z ^ (z >> 31)

    def random(self):
        """A float from 0 up to (not including) 1."""
        return (self._next() >> 11) / (1 << 53)

    def randint(self, low, high):
        return low + int(self.random() * (high - low + 1))

    def choice(self, items):
        return items[int(self.random() * len(items))]

    def shuffle(self, items):
        for i in range(len(items) - 1, 0, -1):
            j = int(self.random() * (i + 1))
            items[i], items[j] = items[j], items[i]

    def normal(self, mean=0.0, spread=1.0):
        """Close enough to a bell curve: the sum of 12 random numbers (no log or cos, so no platform differences)."""
        return mean + spread * (sum(self.random() for _ in range(12)) - 6.0)


# ---------- the leagues: real team names, nothing else real ----------

NBA = ["Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets", "Chicago Bulls", "Cleveland Cavaliers",
       "Dallas Mavericks", "Denver Nuggets", "Detroit Pistons", "Golden State Warriors", "Houston Rockets",
       "Indiana Pacers", "Los Angeles Clippers", "Los Angeles Lakers", "Memphis Grizzlies", "Miami Heat",
       "Milwaukee Bucks", "Minnesota Timberwolves", "New Orleans Pelicans", "New York Knicks",
       "Oklahoma City Thunder", "Orlando Magic", "Philadelphia 76ers", "Phoenix Suns", "Portland Trail Blazers",
       "Sacramento Kings", "San Antonio Spurs", "Toronto Raptors", "Utah Jazz", "Washington Wizards"]

NHL = ["Anaheim Ducks", "Boston Bruins", "Buffalo Sabres", "Calgary Flames", "Carolina Hurricanes", "Chicago Blackhawks",
       "Colorado Avalanche", "Columbus Blue Jackets", "Dallas Stars", "Detroit Red Wings", "Edmonton Oilers",
       "Florida Panthers", "Los Angeles Kings", "Minnesota Wild", "Montréal Canadiens", "Nashville Predators",
       "New Jersey Devils", "New York Islanders", "New York Rangers", "Ottawa Senators", "Philadelphia Flyers",
       "Pittsburgh Penguins", "San Jose Sharks", "Seattle Kraken", "St Louis Blues", "Tampa Bay Lightning",
       "Toronto Maple Leafs", "Utah Mammoth", "Vancouver Canucks", "Vegas Golden Knights", "Washington Capitals",
       "Winnipeg Jets"]

NFL = ["Arizona Cardinals", "Atlanta Falcons", "Baltimore Ravens", "Buffalo Bills", "Carolina Panthers", "Chicago Bears",
       "Cincinnati Bengals", "Cleveland Browns", "Dallas Cowboys", "Denver Broncos", "Detroit Lions",
       "Green Bay Packers", "Houston Texans", "Indianapolis Colts", "Jacksonville Jaguars", "Kansas City Chiefs",
       "Las Vegas Raiders", "Los Angeles Chargers", "Los Angeles Rams", "Miami Dolphins", "Minnesota Vikings",
       "New England Patriots", "New Orleans Saints", "New York Giants", "New York Jets", "Philadelphia Eagles",
       "Pittsburgh Steelers", "San Francisco 49ers", "Seattle Seahawks", "Tampa Bay Buccaneers", "Tennessee Titans",
       "Washington Commanders"]

EPL = ["Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton and Hove Albion", "Burnley", "Chelsea",
       "Crystal Palace", "Everton", "Fulham", "Leeds United", "Liverpool", "Manchester City", "Manchester United",
       "Newcastle United", "Nottingham Forest", "Sunderland", "Tottenham Hotspur", "West Ham United",
       "Wolverhampton Wanderers"]

BUNDESLIGA = ["FC Augsburg", "Bayer Leverkusen", "Bayern Munich", "Borussia Dortmund", "Borussia Monchengladbach",
              "Eintracht Frankfurt", "FC Cologne", "Hamburger SV", "1. FC Heidenheim", "TSG Hoffenheim", "Mainz 05",
              "RB Leipzig", "St. Pauli", "SC Freiburg", "Union Berlin", "VfB Stuttgart", "VfL Wolfsburg", "Werder Bremen"]

# kind: how the sport is scheduled and scored. (The markets come from config.py, exactly like the real bot.)
LEAGUES = [
    {"name": "NFL", "teams": NFL, "kind": "football", "home_edge": 0.025},
    {"name": "NBA", "teams": NBA, "kind": "basketball", "home_edge": 0.035},
    {"name": "NHL", "teams": NHL, "kind": "hockey", "home_edge": 0.030},
    {"name": "EPL", "teams": EPL, "kind": "soccer", "home_edge": 0.060, "totals": (2.5, 2.5, 2.5, 3.0)},
    {"name": "Bundesliga", "teams": BUNDESLIGA, "kind": "soccer", "home_edge": 0.060, "totals": (3.0, 3.0, 3.5, 2.5), "extra_goal": 0.35},
]
for league in LEAGUES:
    league["key"] = SPORTS[league["name"]]
ROSTERS = {league["key"]: league["teams"] for league in LEAGUES}

# (api key, margin it keeps, how much its prices disagree with the others, chance its prices are stale)
BOOKS = [
    ("draftkings", 0.045, 0.008, 0.03), ("fanduel", 0.043, 0.008, 0.03), ("betmgm", 0.048, 0.010, 0.05),
    ("williamhill_us", 0.047, 0.010, 0.05), ("betrivers", 0.050, 0.012, 0.20), ("bovada", 0.062, 0.015, 0.30),
    ("mybookieag", 0.070, 0.020, 0.35), ("betonlineag", 0.052, 0.013, 0.10), ("lowvig", 0.028, 0.006, 0.05),
    ("fanatics", 0.049, 0.011, 0.05),
]
BOOK_TITLES = {key: key for key, *_ in BOOKS}


# ---------- small helpers ----------

def clamp(value, low, high):
    return max(low, min(high, value))


def american(probability):
    """The American price that implies this win chance."""
    p = clamp(probability, 0.04, 0.96)
    return -round(100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def half(value):
    """Round to the nearest half point, the way spreads and totals are quoted."""
    return round(value * 2) / 2


def local_start(day, hour, minute=0):
    """A kickoff given in Central time as a UTC datetime (daylight saving handled by the time zone database)."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=CENTRAL).astimezone(UTC)


def iso(moment):
    return moment.astimezone(UTC).strftime(ISO)


# ---------- the calendar ----------

def pair_up(rng, teams, count):
    """`count` games between different teams, each team at most once."""
    pool = list(teams)
    rng.shuffle(pool)
    return [(pool[2 * i], pool[2 * i + 1]) for i in range(count)]


def build_schedule(rng, league, first_day, last_day):
    """[(start as a UTC datetime, home team, away team)] for the whole calendar, in time order."""
    games, kind, teams = [], league["kind"], league["teams"]
    day = first_day
    while day <= last_day:
        weekday = day.weekday()                       # Monday is 0
        if kind in ("basketball", "hockey"):
            if rng.random() < 0.92:
                low, high = (4, 9) if kind == "basketball" else (3, 8)
                slots = [(18, 0), (18, 30), (19, 0), (19, 30), (20, 0), (21, 0), (21, 30)] if kind == "basketball" \
                    else [(18, 0), (18, 30), (19, 0), (19, 30), (20, 0), (21, 0)]
                for home, away in pair_up(rng, teams, rng.randint(low, high)):
                    hour, minute = rng.choice(slots)
                    games.append((local_start(day, hour, minute), home, away))
        elif kind == "football" and weekday == 3:     # a Thursday starts an NFL week: Thursday, Sunday and Monday games
            count = rng.randint(14, 15)
            matches = pair_up(rng, teams, count)
            plan = [(day, 19, 15)] + [(day + timedelta(days=3), *rng.choice([(12, 0), (12, 0), (12, 0), (15, 5), (15, 25), (19, 20)]))
                                      for _ in range(count - 2)] + [(day + timedelta(days=4), 19, 15)]
            for (home, away), (when, hour, minute) in zip(matches, plan):
                games.append((local_start(when, hour, minute), home, away))
        elif kind == "soccer" and weekday == 5:       # a Saturday starts a round: Saturday, Sunday (and a Monday game)
            count = len(teams) // 2
            matches = pair_up(rng, teams, count)
            slots = [(0, 6, 30), (0, 9, 0), (0, 11, 30), (0, 11, 30), (1, 7, 30), (1, 9, 0), (1, 10, 0), (1, 11, 30), (0, 9, 0), (2, 13, 0)]
            for i, (home, away) in enumerate(matches):
                offset, hour, minute = slots[i % len(slots)]
                games.append((local_start(day + timedelta(days=offset), hour, minute), home, away))
            if (day.toordinal() // 7) % 2 == 0:       # a midweek round every other week
                for home, away in pair_up(rng, teams, count):
                    games.append((local_start(day + timedelta(days=4), 13, rng.choice([0, 45])), home, away))
        day += timedelta(days=1)
    games.sort(key=lambda g: (g[0], g[1]))
    return games


# ---------- who is likely to win, and the real result ----------

def win_chances(league, strengths, home, away):
    """(home, draw, away) chances from the hidden strengths. draw is 0 for sports without draws."""
    gap = strengths[home] - strengths[away]
    if league["kind"] == "soccer":
        draw = clamp(0.28 - 0.03 * abs(gap), 0.16, 0.30)
        home_win = clamp(0.40 + 0.09 * gap + league["home_edge"], 0.08, 0.80 - draw)
        return home_win, draw, 1 - home_win - draw
    home_win = clamp(0.5 + 0.075 * gap + league["home_edge"], 0.12, 0.88)
    return home_win, 0.0, 1 - home_win


def play_game(rng, league, chances):
    """(home score, away score, status) for one finished game."""
    home_win, draw, _ = chances
    roll = rng.random()
    outcome = "home" if roll < home_win else ("draw" if roll < home_win + draw else "away")
    kind = league["kind"]
    if kind == "soccer":
        if outcome == "draw":
            goals = rng.choice([0, 0, 1, 1, 1, 1, 2, 2, 3])
            return goals, goals, "FULL_TIME"
        winner = 1 + (rng.random() < 0.55) + (rng.random() < 0.30) + (rng.random() < 0.12) + (rng.random() < 0.05)
        winner += rng.random() < league.get("extra_goal", 0.0)         # some leagues score more
        loser = min(winner - 1, rng.choice([0, 0, 0, 1, 1, 1, 2, 2, 3]))
        return (winner, loser, "FULL_TIME") if outcome == "home" else (loser, winner, "FULL_TIME")
    if kind == "basketball":
        winner = int(rng.normal(117, 8))
        loser = winner - (1 + int(rng.random() ** 1.6 * 26))
        status = "FINAL"
    elif kind == "hockey":
        winner = rng.choice([2, 3, 3, 4, 4, 5, 6])
        if rng.random() < 0.26:                                        # overtime or a shootout
            loser, status = winner - 1, "FINAL_OT" if rng.random() < 0.75 else "FINAL_SO"
        else:
            loser, status = rng.randint(0, winner - 1), "FINAL"
    else:
        winner = rng.randint(17, 38)
        loser = max(3, winner - rng.choice([1, 2, 3, 3, 4, 5, 6, 7, 7, 8, 10, 13, 14, 17, 21]))
        status = "FINAL"
    return (winner, loser, status) if outcome == "home" else (loser, winner, status)


# ---------- the prices ----------

def book_quotes(rng, league, home, away, hidden, spread_line, total_line, book_keys, pull_time):
    """The sportsbooks' prices for one game at one pull, in the shape The Odds API returns."""
    markets = markets_for(league["name"]).split(",")
    home_chance, draw_chance, away_chance = hidden
    books = []
    for key, margin, bias, stale in BOOKS:
        if key not in book_keys:
            continue
        age = rng.randint(40, 400) if rng.random() < stale else rng.randint(1, 14)
        updated = iso(pull_time - timedelta(minutes=age))
        outcomes_by_market = []
        if "h2h" in markets:
            chances = [max(0.02, home_chance + rng.normal(0, bias)), max(0.02, away_chance + rng.normal(0, bias))]
            names = [home, away]
            if draw_chance:
                chances.insert(1, max(0.02, draw_chance + rng.normal(0, bias)))
                names.insert(1, "Draw")
            total = sum(chances)
            outcomes_by_market.append(("h2h", [{"name": name, "price": american(c / total * (1 + margin))}
                                               for name, c in zip(names, chances)]))
        if "spreads" in markets:
            line = spread_line + rng.choice([0, 0, 0, 0, 0.5, -0.5])
            prices = [american(0.5 * (1 + margin) + rng.normal(0, 0.01)) for _ in range(2)]
            outcomes_by_market.append(("spreads", [{"name": home, "price": prices[0], "point": line},
                                                   {"name": away, "price": prices[1], "point": -line}]))
        if "totals" in markets:
            line = total_line + rng.choice([0, 0, 0, 0, 0.5, -0.5])
            prices = [american(0.5 * (1 + margin) + rng.normal(0, 0.01)) for _ in range(2)]
            outcomes_by_market.append(("totals", [{"name": "Over", "price": prices[0], "point": line},
                                                  {"name": "Under", "price": prices[1], "point": line}]))
        books.append({"key": key, "title": BOOK_TITLES[key], "last_update": updated,
                      "markets": [{"key": market, "last_update": updated, "outcomes": outcomes}
                                  for market, outcomes in outcomes_by_market]})
    return books


# ---------- putting it all together ----------

def build_database(db_file, seed=DEMO_SEED, now=DEMO_NOW):
    """Write a complete synthetic database to `db_file` (replacing any file there). Returns a summary.

    Layout: four weeks of finished games with scores, then the next two days of scheduled games with
    only odds. Every game is priced on the morning before it and on the morning of the game.
    """
    db_file = Path(db_file)
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(str(db_file) + suffix).unlink(missing_ok=True)
    conn = storage.connect(db_file)
    summary = {"games": 0, "finished": 0, "pulls": 0, "teams": set()}
    last_day = (now + timedelta(days=3)).date()
    now_day = now.astimezone(UTC).date()

    try:
        for index, league in enumerate(LEAGUES):
            rng = Rng(seed * 1000 + index)
            strengths = {team: clamp(rng.normal(0, 0.9), -2.2, 2.2) for team in league["teams"]}
            schedule = build_schedule(rng, league, FIRST_GAME_DAY, last_day)

            # Everything about each game is decided once, so both pulls describe the same game.
            games = []
            for number, (start, home, away) in enumerate(schedule, 1):
                true = win_chances(league, strengths, home, away)
                game = {"id": f"{EVENT_PREFIX}{index}-{number:04d}", "start": start, "home": home, "away": away, "true": true}
                if league["kind"] in ("basketball", "football"):
                    scale = 32 if league["kind"] == "basketball" else 26
                    game["spread"] = half(-(true[0] - 0.5) * scale)
                if league["kind"] == "hockey":
                    game["total"] = rng.choice([5.5, 5.5, 5.5, 5.5, 5.5, 6.0, 6.0, 6.5])
                elif league["kind"] == "soccer":
                    game["total"] = rng.choice(league["totals"])
                game["market_error"] = (rng.normal(0, 0.03), rng.normal(0, 0.008))
                game["books"] = [key for key, *_ in BOOKS if rng.random() < 0.85]
                while len(game["books"]) < 6:
                    game["books"].append(rng.choice([key for key, *_ in BOOKS if key not in game["books"]]))
                if start < now - timedelta(hours=3):
                    game["score"] = play_game(rng, league, true)
                games.append(game)
                summary["teams"].update((home, away))
            summary["games"] += len(games)

            # One pull each morning (8 AM Central is about 14:00 UTC): the games in the next 52 hours, so every
            # game is priced at least twice. The closer a pull is to kickoff, the more the market has learned.
            pull_day = FIRST_GAME_DAY - timedelta(days=2)
            while pull_day <= now_day:
                pulled = datetime(pull_day.year, pull_day.month, pull_day.day, 14, rng.randint(0, 9), rng.randint(0, 59), tzinfo=UTC)
                if pulled <= now:
                    response = []
                    for game in games:
                        hours_ahead = (game["start"] - pulled).total_seconds() / 3600
                        if 0 < hours_ahead <= 52:
                            home_true, draw_true, away_true = game["true"]
                            share_true = home_true / (home_true + away_true)      # the home side's share of the non-draw chance
                            first_error, drift = game["market_error"]
                            learned = 0.9 * clamp(1 - hours_ahead / 48, 0.0, 1.0)
                            share = clamp(share_true + first_error * (1 - learned) + drift * learned, 0.06, 0.94)
                            hidden = (share * (1 - draw_true), draw_true, (1 - share) * (1 - draw_true))
                            response.append({
                                "id": game["id"], "sport_key": league["key"], "commence_time": iso(game["start"]),
                                "home_team": game["home"], "away_team": game["away"],
                                "bookmakers": book_quotes(rng, league, game["home"], game["away"], hidden,
                                                          game.get("spread", 0.0), game.get("total", 0.0),
                                                          set(game["books"]), pulled)})
                    if response:
                        storage.insert_snapshot(conn, league["key"], response, iso(pulled))
                        summary["pulls"] += 1
                pull_day += timedelta(days=1)

            with conn:
                for game in games:
                    if "score" in game:
                        home_score, away_score, status = game["score"]
                        conn.execute(
                            "INSERT INTO results (event_id, home_score, away_score, completed, source, updated_at, status) "
                            "VALUES (?, ?, ?, 1, ?, ?, ?)",
                            (game["id"], home_score, away_score, SOURCE_NAME, iso(game["start"] + timedelta(hours=4)), status))
                        summary["finished"] += 1
    finally:
        conn.close()
    summary["teams"] = sorted(summary["teams"])
    return summary
