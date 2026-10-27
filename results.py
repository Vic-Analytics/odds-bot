"""
results.py - save yesterday's final scores and attach them to the games in the odds database.

Scores come from FREE sources that need no key and cost no Odds API credits:
  * ESPN's public scoreboard: NFL, NBA, WNBA and the soccer leagues
  * statsapi.mlb.com:         MLB
  * api-web.nhle.com:         NHL
(MMA is not covered: none of these sources lists those fights.)

    python results.py                       yesterday and the day before (Central), saved to data/results_raw/
                                            and added to data/odds.db
    python results.py --files-only          only save the files (the cloud job uses this)
    python results.py --date 2026-10-20     the days ending on that date
    python results.py --days 7              look back further, to catch up
    python results.py --sports NHL,NBA      only some leagues

How it fits together:
  1. Each run saves a small file per league: data/results_raw/YYYY-MM-DD/<sport_key>__HHMMSSZ.json.
     It holds only the FINAL games in a compact form (the sources' own pages are huge).
  2. Matching a score to a game in the odds database (by league, team names and start
     time) happens when the database is built, from those files. So if a team name
     doesn't match, add an alias in names.py and rebuild: nothing has to be fetched again.
     scripts/backfill_from_raw.py does this rebuild.

Scores are stored as the source reports them. The `status` column says how the game
ended: FINAL, FINAL_OT, FINAL_SO (NHL shootout), FULL_TIME, FINAL_AET (after extra time),
FINAL_PEN (penalties). Soccer bets usually settle on the 90 minutes, so filter on status
when analyzing cup games.
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import storage
from config import SPORTS
from http_utils import request_with_retries
from names import same_team

CENTRAL = ZoneInfo("America/Chicago")

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
NHL_URL = "https://api-web.nhle.com/v1/score/{day}"
MLB_URL = "https://statsapi.mlb.com/api/v1/schedule"

# Odds API sport key -> (which source, that source's name for the league)
SOURCES = {
    "americanfootball_nfl": ("espn", "football/nfl"),
    "basketball_nba": ("espn", "basketball/nba"),
    "basketball_wnba": ("espn", "basketball/wnba"),
    "baseball_mlb": ("mlb", None),
    "icehockey_nhl": ("nhl", None),
    "soccer_epl": ("espn", "soccer/eng.1"),
    "soccer_uefa_champs_league": ("espn", "soccer/uefa.champions"),
    "soccer_uefa_europa_league": ("espn", "soccer/uefa.europa"),
    "soccer_uefa_europa_conference_league": ("espn", "soccer/uefa.europa.conf"),
    "soccer_spain_la_liga": ("espn", "soccer/esp.1"),
    "soccer_italy_serie_a": ("espn", "soccer/ita.1"),
    "soccer_germany_bundesliga": ("espn", "soccer/ger.1"),
    "soccer_france_ligue_one": ("espn", "soccer/fra.1"),
    "soccer_usa_mls": ("espn", "soccer/usa.1"),
}

# Games that did not actually finish normally.
NOT_PLAYED = {"STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_CANCELLED", "STATUS_ABANDONED",
              "STATUS_SUSPENDED", "STATUS_FORFEIT"}

# A score is matched to a game whose start time is within this many hours. The
# sources agree on start times to within about 10 minutes, and the two games of
# a baseball doubleheader are more than 2 hours apart, so 2 keeps them separate.
MATCH_WINDOW_HOURS = 2


def log(message):
    print(f"[results] {message}", file=sys.stderr)


# ---------- turning each source's data into one common shape ----------
# Every parser returns a list of FINAL games like:
#   {"source_id": "401", "start_time": "2026-10-27T00:15:00Z", "home": "Philadelphia Eagles",
#    "away": "Dallas Cowboys", "home_score": 21, "away_score": 38, "status": "FINAL"}

def _iso(value):
    """'2026-10-27T00:15Z' or '...T00:15:00Z' -> '2026-10-27T00:15:00Z'."""
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _score(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_espn(payload):
    games = []
    for event in payload.get("events") or []:
        try:
            status = event["status"]["type"]
            if not status.get("completed") or status.get("name") in NOT_PLAYED:
                continue
            sides = {c["homeAway"]: c for c in event["competitions"][0]["competitors"]}
            home, away = sides["home"], sides["away"]
            home_score, away_score = _score(home.get("score")), _score(away.get("score"))
            if home_score is None or away_score is None:
                continue
            games.append({
                "source_id": str(event["id"]), "start_time": _iso(event["date"]),
                "home": home["team"]["displayName"], "away": away["team"]["displayName"],
                "home_score": home_score, "away_score": away_score,
                "status": (status.get("name") or "STATUS_FINAL").removeprefix("STATUS_"),
            })
        except (KeyError, IndexError, TypeError, ValueError):
            log("skipped one ESPN event that did not have the expected shape")
    return games


def _nhl_name(team):
    place = (team.get("placeName") or {}).get("default")
    nickname = (team.get("name") or {}).get("default")
    return f"{place} {nickname}" if place else nickname


def parse_nhl(payload):
    games = []
    for game in payload.get("games") or []:
        try:
            if game.get("gameState") not in ("OFF", "FINAL"):
                continue
            home_score, away_score = _score(game["homeTeam"].get("score")), _score(game["awayTeam"].get("score"))
            if home_score is None or away_score is None:
                continue
            ended_in = (game.get("gameOutcome") or {}).get("lastPeriodType", "REG")   # REG, OT or SO
            games.append({
                "source_id": str(game["id"]), "start_time": _iso(game["startTimeUTC"]),
                "home": _nhl_name(game["homeTeam"]), "away": _nhl_name(game["awayTeam"]),
                "home_score": home_score, "away_score": away_score,
                "status": "FINAL" if ended_in == "REG" else f"FINAL_{ended_in}",
            })
        except (KeyError, TypeError, ValueError):
            log("skipped one NHL game that did not have the expected shape")
    return games


def parse_mlb(payload):
    games = []
    for day in payload.get("dates") or []:
        for game in day.get("games") or []:
            try:
                status = game.get("status") or {}
                if status.get("abstractGameState") != "Final" or status.get("detailedState") in ("Postponed", "Cancelled"):
                    continue
                home_score, away_score = _score(game["teams"]["home"].get("score")), _score(game["teams"]["away"].get("score"))
                if home_score is None or away_score is None:
                    continue
                games.append({
                    "source_id": str(game["gamePk"]), "start_time": _iso(game["gameDate"]),
                    "home": game["teams"]["home"]["team"]["name"], "away": game["teams"]["away"]["team"]["name"],
                    "home_score": home_score, "away_score": away_score, "status": "FINAL",
                })
            except (KeyError, TypeError, ValueError):
                log("skipped one MLB game that did not have the expected shape")
    return games


PARSERS = {"espn": parse_espn, "nhl": parse_nhl, "mlb": parse_mlb}


# ---------- fetching ----------

def fetch_day(source, league, day):
    """The FINAL games one source lists for one date. (No headers are changed:
    ESPN rejects some custom User-Agent labels, so the library default is used.)"""
    if source == "espn":
        response = request_with_retries("GET", ESPN_URL.format(path=league),
                                        params={"dates": day.strftime("%Y%m%d")}, timeout=20)
    elif source == "nhl":
        response = request_with_retries("GET", NHL_URL.format(day=day.isoformat()), timeout=20)
    else:
        response = request_with_retries("GET", MLB_URL, params={"sportId": 1, "date": day.isoformat()}, timeout=20)
    if not response.ok:
        raise RuntimeError(f"{source} returned HTTP {response.status_code} for {day}")
    return PARSERS[source](response.json())


def collect(sport_key, days, pause=0.25):
    """Final games for a league over several dates, with duplicates removed.
    Returns (source name, games)."""
    source, league = SOURCES[sport_key]
    games, seen = [], set()
    for day in days:
        for game in fetch_day(source, league, day):
            if game["source_id"] not in seen:
                seen.add(game["source_id"])
                games.append(game)
        time.sleep(pause)        # be polite to free services
    return source, games


# ---------- saving the files ----------

def save_results_file(sport_key, source, games, fetched_at):
    """Write data/results_raw/YYYY-MM-DD/<sport_key>__HHMMSSZ.json. Returns the path
    (None if a file with that name already exists)."""
    payload = {"sport_key": sport_key, "source": source, "fetched_at": fetched_at, "games": games}
    path = storage.raw_path_for(sport_key, fetched_at, folder="results_raw")
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)
    return path


# ---------- attaching scores to games in the database ----------

def apply_payload(conn, payload):
    """Match one results file's games to events and store the scores.

    A score is matched to the event in the same league whose teams match (either
    way round, since neutral-site games can list home and away differently) and
    whose start time is within 2 hours. When several pairings are possible, the
    closest start times are assigned first, so the order the games arrive in can
    never put a score on the wrong game. Safe to run again.
    Returns {"matched": n, "unmatched": [descriptions]}.
    """
    sport_key, source = payload["sport_key"], payload.get("source")
    updated_at = payload.get("fetched_at")
    games = payload["games"]

    # Every possible (game, event) pairing, with how far apart the start times are.
    pairings = []
    for index, g in enumerate(games):
        start = datetime.fromisoformat(g["start_time"].replace("Z", "+00:00"))
        low = (start - timedelta(hours=MATCH_WINDOW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        high = (start + timedelta(hours=MATCH_WINDOW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for event_id, commence_time, event_home, event_away in conn.execute(
                "SELECT event_id, commence_time, home_team, away_team FROM events "
                "WHERE sport_key = ? AND commence_time BETWEEN ? AND ?", (sport_key, low, high)):
            if same_team(sport_key, g["home"], event_home) and same_team(sport_key, g["away"], event_away):
                swapped = False
            elif same_team(sport_key, g["home"], event_away) and same_team(sport_key, g["away"], event_home):
                swapped = True
            else:
                continue
            gap = abs((datetime.fromisoformat(commence_time.replace("Z", "+00:00")) - start).total_seconds())
            pairings.append((gap, index, event_id, swapped))

    # Closest first; each game and each event is used once.
    chosen, used_games, used_events = [], set(), set()
    for gap, index, event_id, swapped in sorted(pairings):
        if index in used_games or event_id in used_events:
            continue
        used_games.add(index)
        used_events.add(event_id)
        chosen.append((index, event_id, swapped))

    with conn:
        for index, event_id, swapped in chosen:
            g = games[index]
            home_score, away_score = ((g["away_score"], g["home_score"]) if swapped
                                      else (g["home_score"], g["away_score"]))
            conn.execute(
                """INSERT INTO results (event_id, home_score, away_score, completed, source, updated_at, status)
                   VALUES (?, ?, ?, 1, ?, ?, ?)
                   ON CONFLICT(event_id) DO UPDATE SET
                       home_score = excluded.home_score, away_score = excluded.away_score,
                       completed = 1, source = excluded.source,
                       updated_at = excluded.updated_at, status = excluded.status""",
                (event_id, home_score, away_score, source, updated_at, g.get("status")))

    unmatched = [f"{g['away']} @ {g['home']} ({g['start_time']})"
                 for index, g in enumerate(games) if index not in used_games]
    return {"matched": len(chosen), "unmatched": unmatched}


def rebuild_results(db_file, results_folder):
    """Re-attach every saved score file to the database (oldest first, so a later
    file wins). Safe to run again. Returns a summary."""
    summary = {"files": 0, "matched": 0, "unmatched": 0, "skipped_files": 0}
    results_folder = Path(results_folder)
    if not results_folder.is_dir():
        return summary
    conn = storage.connect(db_file)
    try:
        for path in sorted(results_folder.glob("*/*.json")):
            try:
                outcome = apply_payload(conn, json.loads(path.read_text(encoding="utf-8")))
            except Exception as error:
                log(f"skipping {path}: {error}")
                summary["skipped_files"] += 1
                continue
            summary["files"] += 1
            summary["matched"] += outcome["matched"]
            summary["unmatched"] += len(outcome["unmatched"])
    finally:
        conn.close()
    return summary


# ---------- the command line ----------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Save final scores and attach them to games.")
    parser.add_argument("--date", help="last day to fetch, YYYY-MM-DD (default: yesterday, Central time)")
    parser.add_argument("--days", type=int, default=2, help="how many days to fetch, ending on --date (default 2)")
    parser.add_argument("--sports", help="comma-separated league names from config.py, e.g. NHL,NBA (default: all)")
    parser.add_argument("--files-only", action="store_true", help="save the files but do not touch the database")
    args = parser.parse_args(argv)

    last_day = date.fromisoformat(args.date) if args.date else (datetime.now(CENTRAL) - timedelta(days=1)).date()
    days = [last_day - timedelta(days=i) for i in range(args.days - 1, -1, -1)]

    wanted = list(SPORTS)
    if args.sports:
        by_lower = {name.lower(): name for name in SPORTS}
        wanted = []
        for item in args.sports.split(","):
            if item.strip().lower() not in by_lower:
                raise SystemExit(f"Unknown league '{item.strip()}'. Choose from: {', '.join(SPORTS)}")
            wanted.append(by_lower[item.strip().lower()])

    fetched_at = storage.utc_now_iso()
    conn = None if args.files_only else storage.connect(storage.db_path())
    failures = []
    print(f"Final scores for {days[0]} to {days[-1]}:")
    try:
        for name in wanted:
            key = SPORTS[name]
            if key not in SOURCES:
                print(f"  {name}: no free score source, skipped")
                continue
            try:
                source, games = collect(key, days)
            except Exception as error:
                failures.append(f"{name}: {error}")
                print(f"  {name}: FAILED ({error})")
                continue
            if not games:
                print(f"  {name}: no final games")
                continue
            save_results_file(key, source, games, fetched_at)
            line = f"  {name}: {len(games)} final game(s) saved"
            if conn:
                outcome = apply_payload(conn, {"sport_key": key, "source": source, "fetched_at": fetched_at, "games": games})
                line += f", {outcome['matched']} matched to games in the database"
                if outcome["unmatched"]:
                    line += f", {len(outcome['unmatched'])} not matched (e.g. {outcome['unmatched'][0]})"
            print(line)
    finally:
        if conn:
            conn.close()

    if failures:
        print(f"{len(failures)} league(s) failed; run again later or with --date to retry.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
