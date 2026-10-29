# Analysis

Tools for asking questions of the odds history, for example "how often do home
underdogs win in the NHL?" or "do NBA totals go over more on back-to-backs?".

Everything here is **separate from the bot**: it has its own requirements file and only
**reads** `data/odds.db` (the database is opened read-only, so an analysis can never
damage the history).

## 1. Get the data onto your computer

The bot saves its data in a private repo, `odds-history-data`, because GitHub's
temporary machines are wiped after every run. Clone it next to this project and
build the database from it:

```powershell
cd C:\OddsBot
git clone https://github.com/Vic-Analytics/odds-history-data.git ..\odds-history-data
.\.venv\Scripts\python.exe scripts\backfill_from_raw.py --rebuild `
    --raw-dir ..\odds-history-data\raw --results-dir ..\odds-history-data\results_raw
```

Run `git pull` in that folder and the same command again whenever you want fresher
data. It is safe to repeat: nothing is duplicated.

## The dashboard (quickest way to look)

After step 1, one command builds a web page and opens it in your browser. It needs no
extra install:

```powershell
.\.venv\Scripts\python.exe analysis\dashboard.py --open
```

It has four parts. Every table shows a "too few games to trust" note until a row has 30 games,
and tables fill in on their own as the history grows.

- **Overview:** games coming up in the next 48 hours with the win chances the odds imply, and the last 20 results (favorite won or upset).
- **Market quality:** do favorites win as often as the odds say (grouped by how strong the favorite was), which sportsbooks have the best and worst prices, and how much more a winning $100 bet pays at the best line than at an average book.
- **League trends:** home advantage, home underdogs, over/under rates, point-spread coverage, soccer draw rate versus the draw odds, and back-to-back effects on winning and on totals.
- **Data health:** per league, games stored, pulls, books per game, scores matched, and games that started 24+ hours ago with no score (a sign a team name needs an alias in `names.py`). Plus games tracked per day.

"Odds said" always means the win chance the odds imply with the sportsbooks' margin removed, so the
chances add up to 100%. Soccer odds cover the first 90 minutes, so a game that went to extra time counts
as a draw and is left out of the totals and spread tables.

Run it again after refreshing the data. The page contains your odds data, so it is ignored by git: never
commit or share it.

## 2. Set up the notebook tools (once)

```powershell
python -m venv analysis\.venv
analysis\.venv\Scripts\Activate.ps1
pip install -r analysis\requirements-analysis.txt
jupyter lab analysis
```

Open `starter_questions.ipynb` and run the cells.

## What is in here

| File | What it is |
|---|---|
| `sql/game_lines.sql` | One row per finished game: consensus pre-game lines (moneyline probabilities, spread, total) plus the result and flags like `home_underdog` and `went_over`. Works in any SQLite tool too. |
| `dashboard.py` | Builds `dashboard.html`, a one-page summary of the database (see above). |
| `stats.py` | The calculations behind the dashboard, as plain functions (no database or HTML), each covered by tests with hand-checked numbers. |
| `sql/book_prices.sql` | Every sportsbook's moneyline price from the newest pre-game snapshot of each game. |
| `load.py` | Opens the database read-only and returns pandas tables: `game_lines()`, `rest_days()`, `with_rest_days()`. |
| `starter_questions.ipynb` | The two example questions above, answered step by step. |

## Know the limits of the data

- **Morning lines, not closing lines.** The bot pulls odds around 7:45 to 8 AM, to stay inside the free API credits. A line can move a lot before the game.
- **Not every game has a line history.** A sport is only pulled on days it has a game, so a game usually has one or two snapshots, not a continuous record.
- **Scores come from other sites.** They are matched to games by team name and start time. `python scripts/backfill_from_raw.py` prints how many did not match; add an alias in `names.py` and rebuild to fix those. MMA has no score source.
- **Overtime and extra time** are included in the score. The `status` column says how a game ended (`FINAL_OT`, `FINAL_SO`, `FINAL_AET`, `FINAL_PEN`).
- **The sample grows slowly.** A season's worth of questions needs a season's worth of data.
