"""
dashboard.py - turn data/odds.db into one web page you can open in your browser.

    python analysis/dashboard.py              builds analysis/dashboard.html
    python analysis/dashboard.py --open       ...and opens it
    python analysis/dashboard.py --db other.db --hours 72

It only READS the database (opened read-only) and needs nothing beyond what the
bot already uses, so no extra install. The page is a single file with no
internet connection needed. It contains your odds data, so it is listed in
.gitignore: never commit it (the odds are licensed to you, not to the public).
"""

import argparse
import html
import sqlite3
import sys
import webbrowser
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))      # so we can reuse the bot's names and emoji

from names import SPORT_NAME_BY_KEY       # noqa: E402
from team_emoji import team_label         # noqa: E402
import stats                              # noqa: E402
from stats import SMALL_SAMPLE, implied  # noqa: E402

CENTRAL = ZoneInfo("America/Chicago")
DEFAULT_DB = HERE.parent / "data" / "odds.db"
DEFAULT_OUT = HERE / "dashboard.html"


# ---------- reading the database ----------

def connect(db_path):
    path = Path(db_path).resolve()
    if not path.exists():
        raise SystemExit(f"{path} not found. Build it first (see analysis/README.md, step 1).")
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def sport_name(key):
    return SPORT_NAME_BY_KEY.get(key, key)


def to_central(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(CENTRAL)


def counts(conn):
    one = lambda sql: conn.execute(sql).fetchone()[0]
    return {
        "games": one("SELECT COUNT(*) FROM events"),
        "with_results": one("SELECT COUNT(*) FROM results WHERE completed = 1"),
        "pulls": one("SELECT COUNT(*) FROM pulls"),
        "first": conn.execute("SELECT MIN(pulled_at) FROM pulls").fetchone()[0],
        "last": conn.execute("SELECT MAX(pulled_at) FROM pulls").fetchone()[0],
    }


def upcoming(conn, now, hours):
    """Games starting in the next `hours` hours with the consensus of the newest pre-game prices."""
    start = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (now + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    events = conn.execute(
        "SELECT event_id, sport_key, commence_time, home_team, away_team FROM events "
        "WHERE commence_time >= ? AND commence_time < ? ORDER BY commence_time, sport_key", (start, end)).fetchall()
    newest = {}                  # (event, market) -> latest pull time
    rows = defaultdict(list)
    for r in conn.execute(
            "SELECT event_id, market, outcome, price, point, bookmaker, pulled_at FROM pregame_odds "
            "WHERE commence_time >= ? AND commence_time < ?", (start, end)):
        key = (r[0], r[1])
        if r[6] > newest.get(key, ""):
            newest[key] = r[6]
            rows[key] = []
        if r[6] == newest[key]:
            rows[key].append(r)

    out = []
    for event_id, sport_key, commence, home, away in events:
        h2h = rows.get((event_id, "h2h"), [])
        probs = defaultdict(list)
        for r in h2h:
            probs[r[2]].append(implied(r[3]))
        avg = {name: sum(v) / len(v) for name, v in probs.items()}
        totals = [r[4] for r in rows.get((event_id, "totals"), []) if r[4] is not None]
        spreads = [r[4] for r in rows.get((event_id, "spreads"), []) if r[2] == home and r[4] is not None]
        most_common = lambda values: max(set(values), key=lambda v: (values.count(v), -abs(v))) if values else None
        out.append({"sport_key": sport_key, "start": to_central(commence), "home": home, "away": away,
                    "home_prob": avg.get(home), "away_prob": avg.get(away), "draw_prob": avg.get("Draw"),
                    "total": most_common(totals), "spread": most_common(spreads),
                    "books": len({r[5] for r in h2h})})
    return out


def finished(conn):
    """One row per finished game with consensus pre-game moneyline (the analysis SQL, reused)."""
    sql = (HERE / "sql" / "game_lines.sql").read_text(encoding="utf-8")
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.row_factory = None


def book_prices(conn):
    """(sport_key, event_id, bookmaker, outcome, price) from the newest pre-game moneyline of every game."""
    return conn.execute((HERE / "sql" / "book_prices.sql").read_text(encoding="utf-8")).fetchall()


def all_events(conn):
    return conn.execute("SELECT event_id, sport_key, commence_time, home_team, away_team FROM events").fetchall()


def health(conn, now):
    """Per league: games stored, scores matched, games that started 24h+ ago with no score, pulls, last pull."""
    cutoff = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    pulls = {key: (n, last) for key, n, last in conn.execute(
        "SELECT sport_key, COUNT(*), MAX(pulled_at) FROM pulls GROUP BY sport_key")}
    rows = []
    for key, games, scored, missing in conn.execute(
            "SELECT e.sport_key, COUNT(*), COALESCE(SUM(r.completed = 1), 0), "
            "COALESCE(SUM(e.commence_time < ? AND COALESCE(r.completed, 0) = 0), 0) "
            "FROM events e LEFT JOIN results r ON r.event_id = e.event_id GROUP BY e.sport_key ORDER BY e.sport_key",
            (cutoff,)):
        n_pulls, last = pulls.get(key, (0, None))
        rows.append({"sport_key": key, "games": games, "scored": scored, "missing": missing,
                     "pulls": n_pulls, "last_pull": last})
    return rows


def games_per_day(conn, today, days=14):
    first = today - timedelta(days=days - 1)
    per_day = defaultdict(int)
    for (commence,) in conn.execute("SELECT commence_time FROM events"):
        d = to_central(commence).date()
        if first <= d <= today:
            per_day[d] += 1
    return [(first + timedelta(days=i), per_day[first + timedelta(days=i)]) for i in range(days)]


# ---------- turning numbers into page pieces ----------

def esc(value):
    return html.escape(str(value))


def pct(p):
    return "–" if p is None else f"{p * 100:.0f}%"


def num(value):
    if value is None:
        return "–"
    return f"{value:+g}" if value else "0"


def label(key, team):
    return esc(team_label(sport_name(key), team) or team)


def tile(value, caption):
    return f'<div class="tile"><div class="big">{esc(value)}</div><div class="cap">{esc(caption)}</div></div>'


def upcoming_table(games):
    if not games:
        return '<p class="empty">No games in this window yet. The bot only stores a league on days it has games.</p>'
    body = []
    for g in games:
        soccer = g["sport_key"].startswith("soccer_")
        chances = f'{label(g["sport_key"], g["away"])} {pct(g["away_prob"])}'
        chances += f' · Draw {pct(g["draw_prob"])}' if soccer else ""
        chances += f' · {label(g["sport_key"], g["home"])} {pct(g["home_prob"])}'
        total_text = "–" if g["total"] is None else format(g["total"], "g")
        body.append(
            f'<tr><td>{esc(g["start"].strftime("%a %I:%M %p").replace(" 0", " "))}</td>'
            f'<td>{esc(sport_name(g["sport_key"]))}</td>'
            f'<td>{label(g["sport_key"], g["away"])} @ {label(g["sport_key"], g["home"])}</td>'
            f'<td>{chances}</td>'
            f'<td class="n">{num(g["spread"])}</td>'
            f'<td class="n">{total_text}</td>'
            f'<td class="n">{g["books"]}</td></tr>')
    return ('<div class="scroll"><table><thead><tr><th>Start (Central)</th><th>League</th><th>Game</th>'
            '<th>Win chance the odds imply</th><th class="n">Home spread</th><th class="n">Total</th>'
            '<th class="n">Books</th></tr></thead><tbody>' + "".join(body) + "</tbody></table></div>")


def table(columns, rows, empty="Nothing to show yet."):
    """columns: [(heading, is_number)]; rows: lists of ready-made HTML cells."""
    if not rows:
        return '<p class="empty">' + esc(empty) + "</p>"
    head = "".join(f'<th class="n">{esc(h)}</th>' if is_num else f"<th>{esc(h)}</th>" for h, is_num in columns)
    body = []
    for cells in rows:
        body.append("<tr>" + "".join(
            f'<td class="n">{cell}</td>' if is_num else f"<td>{cell}</td>"
            for (_, is_num), cell in zip(columns, cells)) + "</tr>")
    return '<div class="scroll"><table><thead><tr>' + head + "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>"


def small(n):
    """A reminder next to any percentage built from too few games."""
    return '<span class="muted">too few games to trust</span>' if n < SMALL_SAMPLE else ""


def league(key):
    return "All leagues" if key is None else esc(sport_name(key))


def points(value):
    """A signed gap in win-chance points, e.g. +1.5 or -0.8."""
    return "–" if value is None else f"{value:+.1f}"


def dollars(value):
    return "–" if value is None else f"${value:.2f}"


def decimals(value):
    return "–" if value is None else f"{value:.1f}"


BOOK_NAMES = {
    "draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM", "williamhill_us": "Caesars",
    "betrivers": "BetRivers", "bovada": "Bovada", "mybookieag": "MyBookie.ag", "betonlineag": "BetOnline.ag",
    "lowvig": "LowVig.ag", "fanatics": "Fanatics", "espnbet": "ESPN BET", "hardrockbet": "Hard Rock Bet",
    "ballybet": "Bally Bet", "betparx": "betPARX", "pointsbetus": "PointsBet", "wynnbet": "WynnBET",
    "unibet_us": "Unibet", "superbook": "SuperBook", "fliff": "Fliff", "betus": "BetUS",
}


def book_name(key):
    return esc(BOOK_NAMES.get(key, key.replace("_", " ").title()))


# ---------- recent results ----------

def result_text(g):
    if g["winner"] == "draw":
        return "Draw" if g["sport_key"].startswith("soccer_") else "Tie"
    return "Favorite won" if g["winner"] == g["favorite"] else "Upset"


def results_table(games, limit=20):
    recent = sorted(games, key=lambda g: g["commence_time"], reverse=True)[:limit]
    rows = []
    for g in recent:
        key = g["sport_key"]
        favorite = g["home_team"] if g["favorite"] == "home" else g["away_team"]
        plain = g["status"] in (None, "FINAL", "FULL_TIME")
        status_note = "" if plain else " <span class='muted'>(" + esc(g["status"]) + ")</span>"
        rows.append([
            esc(to_central(g["commence_time"]).strftime("%b %d")), esc(sport_name(key)),
            f'{label(key, g["away_team"])} {g["away_score"]} – {g["home_score"]} {label(key, g["home_team"])}{status_note}',
            f'{label(key, favorite)} {pct(g["fav_prob"])}', result_text(g)])
    return table([("Date", False), ("League", False), ("Final score", False),
                  ("Favorite (by the odds)", False), ("Result", False)], rows,
                 "No finished games matched yet. Scores arrive the morning after each game.")


# ---------- market quality ----------

def calibration_html(rows):
    pooled = [r for r in rows if r["sport_key"] is None]
    per_league = [r for r in rows if r["sport_key"] is not None]
    head = [("Favorite's chance", False), ("Games", True), ("Odds said", True), ("Favorite won", True), ("", False)]
    html_out = "<h4>All leagues together</h4>" + table(head, [[esc(r["bucket"]), r["n"], pct(r["said"]), pct(r["actual"]), small(r["n"])] for r in pooled],
                     "Nothing to show until games finish.")
    if per_league:
        html_out += ("<details><summary>By league</summary>" + table(
            [("League", False)] + head,
            [[league(r["sport_key"]), esc(r["bucket"]), r["n"], pct(r["said"]), pct(r["actual"]), small(r["n"])]
             for r in per_league]) + "</details>")
    return html_out


def books_html(rows):
    return table(
        [("Sportsbook", False), ("Prices compared", True), ("Had the best price", True),
         ("Had the worst price", True), ("Average vs other books", True), ("", False)],
        [[book_name(r["book"]), r["quotes"], pct(r["best"]), pct(r["worst"]), points(r["gap"]) + " pts", small(r["quotes"])]
         for r in rows],
        "Needs a game priced by at least 3 sportsbooks.")


def shopping_html(rows):
    return table(
        [("League", False), ("Prices compared", True), ("Avg gap, best to worst book", True),
         ("Biggest gap", True), ("Extra win per $100, best vs average book", True), ("Biggest extra win", True), ("", False)],
        [[league(r["sport_key"]), r["n"], decimals(r["avg_range"]) + " pts", decimals(r["max_range"]) + " pts",
          dollars(r["avg_gain"]), dollars(r["max_gain"]), small(r["n"])] for r in rows],
        "Needs a game priced by at least 3 sportsbooks.")


def health_html(rows, books_per):
    body = []
    for r in rows:
        key = r["sport_key"]
        no_source = key.startswith("mma_")
        if no_source:
            missing = '<span class="muted">no score source</span>'
        elif r["missing"]:
            missing = f'{r["missing"]} <span class="muted">check team names (names.py)</span>'
        else:
            missing = "0"
        last = to_central(r["last_pull"]).strftime("%b %d %I:%M %p").replace(" 0", " ") if r["last_pull"] else "–"
        body.append([esc(sport_name(key)), r["games"], r["pulls"], esc(last), decimals(books_per.get(key)),
                     r["scored"], missing])
    return table([("League", False), ("Games stored", True), ("Pulls", True), ("Last pull (Central)", True),
                  ("Books per game", True), ("Scores matched", True), ("Started 24h+ ago, no score", True)],
                 body, "No data yet.")


# ---------- league trends ----------

def home_advantage_html(rows):
    return table(
        [("League", False), ("Games", True), ("Odds said: home wins", True), ("Home won", True), ("Away won", True),
         ("Draw or tie", True), ("", False)],
        [[league(r["sport_key"]), r["n"], pct(r["said"]), pct(r["home"]), pct(r["away"]), pct(r["draw"]), small(r["n"])]
         for r in rows], "Nothing to show until games finish.")


def home_dog_table(rows):
    return table(
        [("League", False), ("Finished games", True), ("Home underdogs", True), ("Won", True),
         ("Odds said", True), ("Actually won", True), ("", False)],
        [[league(r["sport_key"]), r["games"], r["dogs"], r["wins"], pct(r["said"]), pct(r["actual"]), small(r["dogs"])]
         for r in rows], "Nothing to show until games finish.")


def totals_html(rows):
    return table(
        [("League", False), ("Games", True), ("Average line", True), ("Average real total", True), ("Went over", True),
         ("Went under", True), ("Pushed", True), ("Over rate", True), ("", False)],
        [[league(r["sport_key"]), r["n"], decimals(r["avg_line"]), decimals(r["avg_total"]), r["over"], r["under"],
          r["push"], pct(r["over_rate"]), small(r["n"])] for r in rows],
        "Needs finished games that had an over/under line.")


def spreads_html(rows):
    return table(
        [("League", False), ("Games", True), ("Favorite covered", True), ("Underdog covered", True), ("Pushed", True),
         ("Favorite cover rate", True), ("Home cover rate", True), ("", False)],
        [[league(r["sport_key"]), r["n"], r["fav"], r["dog"], r["push"], pct(r["fav_rate"]), pct(r["home_rate"]),
          small(r["n"])] for r in rows],
        "Needs finished games that had a point spread (NFL, NBA, WNBA).")


def draws_html(rows):
    def gap(r):
        return "–" if r["said"] is None or r["actual"] is None else f'{(r["actual"] - r["said"]) * 100:+.1f} pts'
    return table(
        [("League", False), ("Games", True), ("Odds said: draw", True), ("Actually drew", True), ("Difference", True), ("", False)],
        [[league(r["sport_key"]), r["n"], pct(r["said"]), pct(r["actual"]), gap(r), small(r["n"])] for r in rows],
        "Needs finished soccer games.")


def rest_html(effect_rows, totals_rows):
    out = "<h4>Do teams on a back-to-back win less than the odds expect?</h4>" + table(
        [("League", False), ("Situation", False), ("Team games", True), ("Odds said", True), ("Actually won", True), ("", False)],
        [[league(r["sport_key"]), esc(r["situation"]), r["n"], pct(r["said"]), pct(r["actual"]), small(r["n"])]
         for r in effect_rows],
        "Needs a team that played two days in a row inside the data.")
    out += "<h4>Do totals go over more when a team is on a back-to-back?</h4>" + table(
        [("League", False), ("Situation", False), ("Games", True), ("Over rate", True), ("Real total minus line", True), ("", False)],
        [[league(r["sport_key"]), esc(r["situation"]), r["n"], pct(r["over_rate"]),
          "–" if r["avg_vs_line"] is None else f'{r["avg_vs_line"]:+.1f}', small(r["n"])] for r in totals_rows],
        "Needs a team that played two days in a row inside the data.")
    return out


def bar_chart(series):
    """One series, so one colour. Native hover tooltips via <title>; the numbers are also in the table below."""
    width, height, left, bottom, top = 720, 220, 34, 28, 14
    peak = max([n for _, n in series] + [1])
    step = max(1, -(-peak // 4))                       # about 4 gridlines
    top_value = step * (-(-peak // step))
    plot_h = height - bottom - top
    slot = (width - left) / len(series)
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Games tracked per day, last {len(series)} days">']
    for v in range(0, top_value + 1, step):
        y = top + plot_h * (1 - v / top_value)
        parts.append(f'<line x1="{left}" x2="{width}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                     f'<text x="{left - 6}" y="{y + 4:.1f}" class="axis" text-anchor="end">{v}</text>')
    for i, (day, n) in enumerate(series):
        x = left + i * slot + 2
        h = plot_h * n / top_value
        if n:
            parts.append(f'<rect x="{x:.1f}" y="{top + plot_h - h:.1f}" width="{slot - 4:.1f}" height="{h:.1f}" rx="3" class="bar">'
                         f'<title>{day.strftime("%a %b %d")}: {n} games</title></rect>')
        parts.append(f'<text x="{x + (slot - 4) / 2:.1f}" y="{height - 8}" class="axis" text-anchor="middle">{day.month}/{day.day}</text>')
    parts.append("</svg>")
    rows = "".join(f"<tr><td>{d.strftime('%a %b %d')}</td><td class='n'>{n}</td></tr>" for d, n in series)
    return ("".join(parts) +
            f"<details><summary>Show as a table</summary><table class='small'><thead><tr><th>Day</th><th class='n'>Games</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></details>")


CSS = """
:root{color-scheme:light;--bg:#f6f6f4;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#6f6e69;--line:#e3e2dd;--accent:#2a78d6}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#121211;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#a09f96;--line:#33332f;--accent:#3987e5}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:24px;margin:0 0 2px}h2.group{font-size:20px;margin:32px 0 0}h3{font-size:17px;margin:0 0 4px}h4{font-size:14px;margin:16px 0 6px;color:var(--ink2)}
.sub{color:var(--ink2);margin:0 0 12px}.lead{color:var(--ink2);font-size:14px;margin:4px 0 0}
.nav{display:flex;gap:16px;flex-wrap:wrap;margin:0 0 16px;font-size:14px}a{color:var(--accent)}
section{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px;margin:16px 0}
section p.note{color:var(--ink2);font-size:13px;margin:0 0 12px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:0}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.big{font-size:28px;font-weight:650;line-height:1.1}.cap{color:var(--ink2);font-size:13px}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}
th{font-size:12px;font-weight:600;color:var(--ink2);text-align:left;padding:6px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}tr:last-child td{border-bottom:0}
.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.muted,.empty{color:var(--muted)}
svg{width:100%;height:auto}.grid{stroke:var(--line);stroke-width:1}.axis{fill:var(--ink2);font-size:11px}.bar{fill:var(--accent)}.bar:hover{opacity:.8}
details{margin-top:8px;color:var(--ink2);font-size:13px}table.small{width:auto;margin-top:6px}
footer{color:var(--muted);font-size:12px;margin-top:20px}
"""


def build(db_path, hours, now=None):
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(CENTRAL).date()
    with closing(connect(db_path)) as conn:
        c = counts(conn)
        coming = upcoming(conn, now, hours)
        done = stats.prepare(finished(conn))
        prices = book_prices(conn)
        events = all_events(conn)
        health_rows = health(conn, now)
        chart = bar_chart(games_per_day(conn, today))

    gaps = stats.rest_gaps(events)
    book_rows, shopping_rows = stats.book_stats(prices)
    first = to_central(c["first"]).strftime("%b %d") if c["first"] else "–"
    last = to_central(c["last"]).strftime("%b %d, %I:%M %p").replace(" 0", " ") if c["last"] else "–"
    tiles = "".join([tile(c["games"], "games tracked"), tile(c["with_results"], "with a final score"),
                     tile(c["pulls"], "odds pulls saved"), tile(first, "first day of data")])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Odds Bot Dashboard</title><style>{CSS}</style></head><body><main>
<h1>Odds Bot dashboard</h1>
<p class="sub">Latest odds pull: {esc(last)} Central. Built {esc(now.astimezone(CENTRAL).strftime("%b %d, %I:%M %p").replace(" 0", " "))} Central.</p>
<nav class="nav"><a href="#market">Market quality</a><a href="#trends">League trends</a><a href="#health">Data health</a></nav>
<div class="tiles">{tiles}</div>
<section><h3>Coming up (next {hours} hours)</h3>
<p class="note">Morning prices from the newest pre-game pull, averaged across sportsbooks. “Win chance” still includes the sportsbooks' margin.</p>
{upcoming_table(coming)}</section>
<section><h3>Recent results</h3>
<p class="note">The last 20 finished games, compared with what the morning odds expected.</p>
{results_table(done)}</section>

<h2 class="group" id="market">Market quality</h2>
<p class="lead">“Odds said” is the win chance the odds imply with the sportsbooks' margin taken out, so the chances add up to 100%. If the odds are good, what happened should land close to what they said, once there are enough games.</p>
<section><h3>Do favorites win as often as the odds say?</h3>
<p class="note">Games grouped by how strong the favorite was. A draw counts as the favorite not winning.</p>
{calibration_html(stats.calibration(done))}</section>
<section><h3>Which sportsbooks pay the most?</h3>
<p class="note">On each game's moneyline, who had the best and worst price (only when prices differed and at least 3 books quoted it). “Average vs other books” is in win-chance points: negative means it pays more than the typical book, positive means less.</p>
{books_html(book_rows)}</section>
<section><h3>What is shopping for the best line worth?</h3>
<p class="note">How far apart the books were, and how much more a winning $100 bet pays at the best price than at the average book.</p>
{shopping_html(shopping_rows)}</section>

<h2 class="group" id="trends">League trends</h2>
<p class="lead">Each table needs a lot of games before it means anything, so it shows a warning until a row has {SMALL_SAMPLE}.</p>
<section><h3>Home advantage</h3>
<p class="note">How often the home team wins, compared with what the odds said.</p>
{home_advantage_html(stats.home_advantage(done))}</section>
<section><h3>Home underdogs</h3>
<p class="note">How often the home team won when the odds rated it the underdog.</p>
{home_dog_table(stats.home_underdogs(done))}</section>
<section><h3>Over / under</h3>
<p class="note">How often games go over the line, and how close the real total lands to it. Soccer games that went to extra time are left out, because the line covers 90 minutes.</p>
{totals_html(stats.totals(done))}</section>
<section><h3>Point spreads</h3>
<p class="note">How often the favorite, the underdog and the home team beat the spread. A push means the margin landed exactly on it.</p>
{spreads_html(stats.spreads(done))}</section>
<section><h3>Soccer draws</h3>
<p class="note">How often a game was level after 90 minutes, compared with the draw chance in the odds.</p>
{draws_html(stats.draws(done))}</section>
<section><h3>Rest and back-to-backs</h3>
<p class="note">“Back-to-back” means the team's previous game in the database was the day before (Central time). The first games in the database have no earlier game to compare with, so they are left out.</p>
{rest_html(stats.rest_effect(done, gaps), stats.rest_totals(done, gaps))}</section>

<h2 class="group" id="health">Data health</h2>
<p class="lead">Checks that the bot is collecting everything it should.</p>
<section><h3>Coverage by league</h3>
<p class="note">A game that started more than 24 hours ago with no score usually means a team name needs an alias in names.py, then rebuild the database.</p>
{health_html(health_rows, stats.books_per_game(prices))}</section>
<section><h3>Games tracked per day</h3>
<p class="note">By start date (Central), last 14 days. This shows how fast your history is growing.</p>
{chart}</section>
<footer>Generated by analysis/dashboard.py from data/odds.db. Contains licensed odds data: do not publish.</footer>
</main></body></html>"""


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build a one-page dashboard from odds.db.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="database file (default: data/odds.db)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="page to write (default: analysis/dashboard.html)")
    parser.add_argument("--hours", type=int, default=48, help="how far ahead 'Coming up' looks (default 48)")
    parser.add_argument("--open", action="store_true", help="open the page in your browser")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.write_text(build(args.db, args.hours), encoding="utf-8")
    print(f"Wrote {out}")
    if args.open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == "__main__":
    main()
