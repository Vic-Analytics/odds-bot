"""
recap.py - send a results recap to Telegram once a day's LAST game has finished.

For each league: the final score, the favorite according to that morning's consensus
odds, and whether the favorite won, it was an upset, or the game was a draw. (Soccer odds
are for the first 90 minutes, so a soccer game that went to extra time counts as a draw.)

    python recap.py --dry-run                 print today's recap (or yesterday's, in the morning) without sending
    python recap.py --dry-run --date 2026-11-08
    python recap.py --dry-run --no-wait       print what is final right now, even if games are still going
    python recap.py --data-dir ..\\odds-history-data      the folder that holds raw/ (a clone of the private data repo)

How it works (the cloud workflow runs this every 20 minutes through the evening):
  1. Build a small temporary database from the odds files for that day (the morning
     digests saved them in the private data repo).
  2. Ask the FREE score sources (ESPN, MLB, NHL) for the finals of every league that plays
     that day. This never touches the Odds API, so it costs no credits.
  3. If any game is still going, wait: say so and send nothing. The next run looks again.
     A game with no final score 5 hours after its start is treated as postponed (or not
     reported by the source) and no longer holds the recap up.
  4. Once everything is final, send the recap and write the marker file, so the workflow
     does not send it twice.

Games that are missing a score or odds are skipped quietly. No finished games: nothing is sent.
"""

import argparse
import html
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import defaultdict
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "analysis"))        # stats.py: plain Python, no pandas needed

import results  # noqa: E402
import stats  # noqa: E402
import storage  # noqa: E402
import telegram_bot  # noqa: E402
from central_time import CENTRAL, day_bounds, to_central  # noqa: E402
from config import SPORT_EMOJI, SPORTS  # noqa: E402
from format_digest import MAX_MESSAGE_LENGTH, plain_preview  # noqa: E402
from names import SPORT_NAME_BY_KEY  # noqa: E402
from recap_gate import recap_day  # noqa: E402
from team_emoji import team_label  # noqa: E402

GAME_LINES_SQL = (HERE / "analysis" / "sql" / "game_lines.sql").read_text(encoding="utf-8")

# A game with no final score this long after it started is treated as postponed (or not
# reported by the score source). Without this, one postponed game would hold the recap up forever.
GIVE_UP_HOURS = 5

RESULT_NOTES = {"FINAL_OT": "OT", "FINAL_SO": "SO", "FINAL_AET": "after extra time", "FINAL_PEN": "after penalties"}
LEAGUE_ORDER = {key: position for position, key in enumerate(SPORTS.values())}


def log(message):
    print(f"[recap] {message}", file=sys.stderr)


def scrub(text):
    """Hide the Telegram token if an error message happens to contain it."""
    token = telegram_bot.BOT_TOKEN
    return text.replace(token, "***") if token else text


# ---------- the day's games ----------

def copy_raw_days(data_dir, destination, day, before=2, after=1):
    """Copy the raw odds folders around `day` into `destination` (the folders are named by UTC date).

    The morning digest of the day saves every game of that day, so a few days either side is plenty.
    Reading only these keeps each run quick however long the history gets.
    """
    raw = Path(data_dir) / "raw"
    if not raw.is_dir():
        raise SystemExit(f"No odds found in {raw}. Point --data-dir at the folder that holds raw/ "
                         f"(a clone of the private data repo), for example ..\\odds-history-data")
    copied = 0
    for offset in range(-before, after + 1):
        folder = raw / (day + timedelta(days=offset)).isoformat()
        if folder.is_dir():
            shutil.copytree(folder, Path(destination) / folder.name)
            copied += 1
    return copied


def games_on(conn, day):
    """Every game starting on `day` (Central) that has pre-game moneyline odds and a free score source."""
    start, end = day_bounds(day)
    rows = conn.execute(
        "SELECT e.event_id, e.sport_key, e.commence_time, COALESCE(r.completed, 0) "
        "FROM events e LEFT JOIN results r ON r.event_id = e.event_id "
        "WHERE e.commence_time >= ? AND e.commence_time < ? "
        "AND e.event_id IN (SELECT event_id FROM pregame_odds WHERE market = 'h2h') "
        "ORDER BY e.commence_time", (start, end)).fetchall()
    return [{"event_id": event_id, "sport_key": sport, "start": to_central(commence), "completed": bool(completed)}
            for event_id, sport, commence, completed in rows if sport in results.SOURCES]


def progress(games, now):
    """Sort a day's games into finished, still to finish (waiting), and given up on."""
    give_up = timedelta(hours=GIVE_UP_HOURS)
    sorted_games = {"finished": [], "pending": [], "gave_up": []}
    for game in games:
        if game["completed"]:
            sorted_games["finished"].append(game)
        elif now < game["start"] + give_up:
            sorted_games["pending"].append(game)
        else:
            sorted_games["gave_up"].append(game)
    return sorted_games


def fetch_scores(conn, leagues, day, fetch=None):
    """Ask the free score sources for the finals of each league and attach them to the games.

    One league failing is not fatal: its games simply stay unfinished for now. A game that
    starts late in the evening can be listed under the next date, so both dates are asked for.
    """
    fetch = fetch or results.collect
    days = [day, day + timedelta(days=1)]
    fetched_at = storage.utc_now_iso()
    failed = []
    for key in sorted(leagues, key=lambda k: LEAGUE_ORDER.get(k, 99)):
        try:
            source, games = fetch(key, days)
        except Exception as error:
            log(f"{SPORT_NAME_BY_KEY.get(key, key)}: could not fetch scores ({type(error).__name__}: {str(error)[:120]})")
            failed.append(key)
            continue
        if games:
            results.apply_payload(conn, {"sport_key": key, "source": source, "fetched_at": fetched_at, "games": games})
    return failed


def final_games(conn, day):
    """The day's finished games with their odds, ready to report (see stats.prepare)."""
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in conn.execute(GAME_LINES_SQL)]
    finally:
        conn.row_factory = None
    games = [g for g in stats.prepare(rows) if to_central(g["commence_time"]).date() == day]
    return sorted(games, key=lambda g: (LEAGUE_ORDER.get(g["sport_key"], 99), g["commence_time"]))


# ---------- the message ----------

def result_text(game):
    if game["winner"] == "draw":
        if game["status"] in stats.EXTRA_TIME:
            return "\U0001F91D Draw (level after 90 min)"
        return "\U0001F91D Draw" if game["sport_key"].startswith("soccer_") else "\U0001F91D Tie"
    return "✅ Favorite won" if game["winner"] == game["favorite"] else "\U0001F62E Upset"


def game_block(game):
    """Two lines: the score, then who the favorite was and how it turned out."""
    name = SPORT_NAME_BY_KEY.get(game["sport_key"], game["sport_key"])
    home, away = (html.escape(team_label(name, game[side])) for side in ("home_team", "away_team"))
    hs, as_ = game["home_score"], game["away_score"]
    if game["sport_key"].startswith("soccer_"):             # soccer is written "home – away"
        score = f"{home} <b>{hs}</b> – <b>{as_}</b> {away}"
    else:                                                  # US sports are written "away – home"
        score = f"{away} <b>{as_}</b> – <b>{hs}</b> {home}"
    note = RESULT_NOTES.get(game["status"])
    if note:
        score += f" ({note})"
    favorite = game["home_team"] if game["favorite"] == "home" else game["away_team"]
    chance = round(game["fav_prob"] * 100)
    return f"{score}\n<i>Favorite: {html.escape(team_label(name, favorite))} {chance}%</i> · {result_text(game)}"


def summary_line(games):
    favorites = sum(1 for g in games if g["winner"] == g["favorite"])
    draws = sum(1 for g in games if g["winner"] == "draw")
    parts = [f"Favorites won {favorites}", f"Upsets {len(games) - favorites - draws}"]
    if draws:
        parts.append(f"Draws {draws}")
    return "<i>" + " · ".join(parts) + "</i>"


def format_recap(games, day):
    """The recap as a list of Telegram messages (almost always one). Empty if there are no games.

    Several messages only when it would pass Telegram's length limit; they are split between games.
    """
    if not games:
        return []
    title = f"\U0001F4CB <b>Results recap</b> — {day:%a, %b %d}".replace(" 0", " ")
    continued = title.replace("</b>", "</b> (cont.)", 1)
    messages, current = [], title
    by_league = defaultdict(list)
    for game in games:
        by_league[game["sport_key"]].append(game)

    for key in sorted(by_league, key=lambda k: LEAGUE_ORDER.get(k, 99)):
        name = SPORT_NAME_BY_KEY.get(key, key)
        header = f"{SPORT_EMOJI.get(name, chr(0x1F3C6))} <b>{html.escape(name)}</b>"
        needs_header = True
        for game in by_league[key]:
            block = game_block(game)
            piece = ("\n\n" + header + "\n" if needs_header else "\n\n") + block
            if len(current) + len(piece) > MAX_MESSAGE_LENGTH and current not in (title, continued):
                messages.append(current)
                current, needs_header = continued, True
                piece = "\n\n" + header + "\n" + block
            current += piece
            needs_header = False

    ending = "\n\n" + summary_line(games)
    if len(current) + len(ending) > MAX_MESSAGE_LENGTH:
        messages.append(current)
        current = continued
    messages.append(current + ending)
    return messages


# ---------- deciding what to do ----------

def evaluate(data_dir, day, now=None, fetch=None, no_wait=False):
    """Work out what the recap for `day` should do right now. Sends nothing.

    Returns {"day", "messages", "done", "reason"}:
      messages  the recap to send (empty when waiting, or when there is nothing to report)
      done      True when the day needs no more checking (sent, or nothing will ever be sent)
      reason    one line saying what happened, for the log
    """
    now = (now or datetime.now(CENTRAL)).astimezone(CENTRAL)
    outcome = {"day": day, "messages": [], "done": False, "reason": ""}

    with tempfile.TemporaryDirectory() as temp:
        raw = Path(temp) / "raw"
        raw.mkdir()
        copy_raw_days(data_dir, raw, day)
        database = Path(temp) / "recap.db"
        storage.rebuild_from_raw(raw, database, rebuild=True)
        with closing(storage.connect(database)) as conn:
            games = games_on(conn, day)
            if games:
                fetch_scores(conn, {g["sport_key"] for g in games}, day, fetch)
                games = games_on(conn, day)
            state = progress(games, now)
            finals = final_games(conn, day)

    if not games:
        day_over = now.date() > day
        outcome.update(done=day_over, reason=f"no games with odds and a score source on {day}"
                       + ("" if day_over else " (yet), will look again"))
        return outcome
    if state["pending"] and not no_wait:
        latest = max(state["pending"], key=lambda g: g["start"])
        outcome["reason"] = (f"waiting: {len(state['pending'])} of {len(games)} game(s) not final yet "
                             f"(the latest started {latest['start']:%I:%M %p} CT)")
        return outcome
    outcome["done"] = not state["pending"]
    if not finals:
        outcome["reason"] = "no finished games with odds to report"
        return outcome
    extra = []
    if state["pending"]:
        extra.append(f"{len(state['pending'])} still going, not included")
    if state["gave_up"]:
        extra.append(f"{len(state['gave_up'])} with no final score after {GIVE_UP_HOURS} hours, skipped")
    outcome["messages"] = format_recap(finals, day)
    outcome["reason"] = f"{len(finals)} finished game(s)" + (f" ({'; '.join(extra)})" if extra else "")
    return outcome


# ---------- the command line ----------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Send a results recap when a day's last game has finished.")
    parser.add_argument("--date", help="the Central day to recap, YYYY-MM-DD (default: automatic, see recap_gate.py)")
    parser.add_argument("--data-dir", help="folder that holds raw/ (default: data/; in the cloud, the data repo clone)")
    parser.add_argument("--dry-run", action="store_true", help="print the recap instead of sending it")
    parser.add_argument("--no-wait", action="store_true", help="report what is final now even if games are still going")
    parser.add_argument("--marker-file", help="write this file once the day is finished (the workflow uses it)")
    args = parser.parse_args(argv)

    now = datetime.now(CENTRAL)
    try:
        day = date.fromisoformat(args.date) if args.date else recap_day(now)
    except ValueError:
        raise SystemExit(f"--date must look like 2026-11-08, not {args.date!r}")
    data_dir = Path(args.data_dir) if args.data_dir else storage.data_dir()

    outcome = evaluate(data_dir, day, now, no_wait=args.no_wait)
    print(f"Results recap for {day}: {outcome['reason']}")

    try:
        for position, message in enumerate(outcome["messages"]):
            if args.dry_run:
                print("\n" + plain_preview(message) + "\n" + "-" * 40)
            else:
                if position:
                    time.sleep(1)               # Telegram dislikes bursts
                telegram_bot.send_message(message)
    except Exception as error:
        print(f"FAILED to send the recap: {scrub(str(error))}", file=sys.stderr)
        return 1                                # no marker, so the next run tries again

    if args.dry_run:
        if outcome["messages"]:
            print("(dry run: nothing was sent)")
    elif outcome["done"] and args.marker_file:
        Path(args.marker_file).write_text("recap done\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
