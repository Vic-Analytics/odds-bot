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

CENTRAL = ZoneInfo("America/Chicago")
DEFAULT_DB = HERE.parent / "data" / "odds.db"
DEFAULT_OUT = HERE / "dashboard.html"
SMALL_SAMPLE = 30      # below this many games, a percentage is mostly luck


# ---------- reading the database ----------

def connect(db_path):
    path = Path(db_path).resolve()
    if not path.exists():
        raise SystemExit(f"{path} not found. Build it first (see analysis/README.md, step 1).")
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def implied(price):
    """American odds -> the win chance they imply (0 to 1)."""
    return 100.0 / (price + 100.0) if price > 0 else -price / (-price + 100.0)


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


def outcome_text(g):
    hs, as_ = g["home_score"], g["away_score"]
    if hs == as_:
        return "Tie"
    home_won = hs > as_
    p_home, p_away = g["home_prob"], g["away_prob"]
    favorite_home = p_home >= p_away
    return "Favorite won" if home_won == favorite_home else "Upset"


def results_table(rows, limit=20):
    rows = sorted(rows, key=lambda r: r["commence_time"], reverse=True)[:limit]
    if not rows:
        return '<p class="empty">No finished games matched yet. Scores arrive the morning after each game.</p>'
    body = []
    for g in rows:
        key = g["sport_key"]
        favorite_home = g["home_prob"] >= g["away_prob"]
        fav = g["home_team"] if favorite_home else g["away_team"]
        fav_prob = g["home_prob"] if favorite_home else g["away_prob"]
        plain = g["status"] in (None, "FINAL", "FULL_TIME")
        status_note = "" if plain else " <span class='muted'>(" + esc(g["status"]) + ")</span>"
        body.append(
            f'<tr><td>{esc(to_central(g["commence_time"]).strftime("%b %d"))}</td>'
            f'<td>{esc(sport_name(key))}</td>'
            f'<td>{label(key, g["away_team"])} {g["away_score"]} – {g["home_score"]} {label(key, g["home_team"])}'
            f'{status_note}</td>'
            f'<td>{label(key, fav)} {pct(fav_prob)}</td><td>{outcome_text(g)}</td></tr>')
    return ('<div class="scroll"><table><thead><tr><th>Date</th><th>League</th><th>Final score</th>'
            '<th>Favorite (by the odds)</th><th>Result</th></tr></thead><tbody>' + "".join(body) + "</tbody></table></div>")


def home_dog_table(rows):
    by_sport = defaultdict(list)
    for g in rows:
        by_sport[g["sport_key"]].append(g)
    if not by_sport:
        return '<p class="empty">Nothing to show until games finish.</p>'
    body = []
    for key, games in sorted(by_sport.items(), key=lambda kv: -len(kv[1])):
        dogs = [g for g in games if g["home_underdog"] == 1]
        wins = sum(g["home_won"] for g in dogs)
        expected = sum(g["home_prob"] for g in dogs) / len(dogs) if dogs else None
        actual = wins / len(dogs) if dogs else None
        note = "too few games to trust" if len(dogs) < SMALL_SAMPLE else ""
        body.append(f'<tr><td>{esc(sport_name(key))}</td><td class="n">{len(games)}</td><td class="n">{len(dogs)}</td>'
                    f'<td class="n">{wins}</td><td class="n">{pct(expected)}</td><td class="n">{pct(actual)}</td>'
                    f'<td class="muted">{note}</td></tr>')
    return ('<div class="scroll"><table><thead><tr><th>League</th><th class="n">Finished games</th>'
            '<th class="n">Home underdogs</th><th class="n">Won</th><th class="n">Odds said</th>'
            '<th class="n">Actually won</th><th></th></tr></thead><tbody>' + "".join(body) + "</tbody></table></div>")


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
h1{font-size:24px;margin:0 0 2px}h2{font-size:17px;margin:0 0 4px}.sub{color:var(--ink2);margin:0 0 20px}
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
        done = finished(conn)
        chart = bar_chart(games_per_day(conn, today))
    first = to_central(c["first"]).strftime("%b %d") if c["first"] else "–"
    last = to_central(c["last"]).strftime("%b %d, %I:%M %p").replace(" 0", " ") if c["last"] else "–"
    tiles = "".join([tile(c["games"], "games tracked"), tile(c["with_results"], "with a final score"),
                     tile(c["pulls"], "odds pulls saved"), tile(first, "first day of data")])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Odds Bot Dashboard</title><style>{CSS}</style></head><body><main>
<h1>Odds Bot dashboard</h1>
<p class="sub">Latest odds pull: {esc(last)} Central. Built {esc(now.astimezone(CENTRAL).strftime("%b %d, %I:%M %p").replace(" 0", " "))} Central.</p>
<div class="tiles">{tiles}</div>
<section><h2>Coming up (next {hours} hours)</h2>
<p class="note">Morning prices from the newest pre-game pull, averaged across sportsbooks. “Win chance” still includes the sportsbooks' margin.</p>
{upcoming_table(coming)}</section>
<section><h2>Recent results</h2>
<p class="note">The last 20 finished games, compared with what the morning odds expected.</p>
{results_table(done)}</section>
<section><h2>Home underdogs</h2>
<p class="note">How often the home team won when the odds rated it the underdog. With fewer than {SMALL_SAMPLE} games, a percentage is mostly luck.</p>
{home_dog_table(done)}</section>
<section><h2>Games tracked per day</h2>
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
