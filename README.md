# Daily Sports Odds Digest (Telegram Bot)

[![Tests](https://github.com/Vic-Analytics/odds-bot/actions/workflows/tests.yml/badge.svg)](https://github.com/Vic-Analytics/odds-bot/actions/workflows/tests.yml)

A Python bot that sends a formatted digest of **today's games and best available betting lines** to Telegram every morning, scheduled for 7:15 AM Central. It runs in the cloud on GitHub Actions, so no computer needs to stay on.

> For information only. This project does not place bets or give betting advice.

## What it looks like

One message per sport. Each game shows the best line across US sportsbooks and the book offering it, with a small emoji beside each team:

```
🏒 NHL — Sat, Oct 17

8:10 PM · Pittsburgh Penguins @ Colorado Avalanche
┃ Moneyline
┃ 🐧 Pittsburgh Penguins  +150  (DraftKings)
┃ 🏔️ Colorado Avalanche  -170  (FanDuel)
┃
┃ Total goals
┃ ⬆️ Over 6.5  -112  (BetRivers)
┃ ⬇️ Under 6.5  -103  (BetOnline.ag)
```

Soccer also shows the over/under on goals, and clubs get kit-color dots:

```
⚽ EPL — Sat, Oct 17

8:00 AM · Bournemouth vs Sunderland
🔴 LIVE · Bournemouth 1–0 Sunderland
┃ Moneyline (live odds)
┃ 🔴⚫ Bournemouth  -150  (FanDuel)
┃ 🤝🤝 Draw  +340  (Bovada)
┃ 🔴⚪ Sunderland  +500  (Bovada)
┃
┃ Total goals (live odds)
┃ ⬆️ Over 2.5  -112  (Bovada)
┃ ⬇️ Under 2.5  -108  (Bovada)
```

*(Illustrative numbers. Real messages use bold headlines and Telegram quote blocks, which is what the vertical bar represents here.)*

## Features

- **Best line across all books.** For each game it finds the highest moneyline price per team. For spreads and totals it takes the most common line, then the best price at that number, so a rare odd alternate line can't look like a bargain.
- **Today only, in Central time.** The API returns UTC. Start times are converted with a named time zone (`America/Chicago`), so daylight saving is handled automatically.
- **15 leagues.** NFL, NBA, MLB, NHL, WNBA, UFC/MMA, EPL, Champions League, Europa League, Conference League, La Liga, Serie A, Bundesliga, Ligue 1 and MLS. Adding a league is one line in `config.py`.
- **Market per sport.** The NFL, NBA and WNBA show moneyline and point spread. MLB and the NHL show moneyline and total runs/goals. Soccer shows moneyline (with the draw) and total goals. MMA shows moneyline only.
- **Live game awareness.** A game that has already started when the digest runs is marked 🔴 LIVE with its current score, and its odds are labeled as live.
- **Team emoji.** NFL, NBA, NHL, MLB and WNBA teams get an emoji matched by nickname, so "LA Clippers" and "Los Angeles Clippers" both work. Soccer clubs get two kit-color dots (a one-color kit shows its dot twice, and the Draw row gets 🤝🤝) so every row lines up. UFC fighters get a country flag from a hand-kept list, because the API doesn't provide nationality.
- **Telegram-friendly output.** HTML formatting, one message per sport, and automatic splitting when a long slate would pass Telegram's 4096-character limit.
- **Failure alerts.** If a sport fails, the others still send, and a short error message arrives on Telegram. The run also exits with an error code, so GitHub marks it failed.
- **Retries.** Timeouts, dropped connections and temporary server errors are retried up to 3 times. Client errors (a bad key) and exhausted API credits are not, because trying again can't help.
- **Tested.** Around 200 automated tests run on every push (see below).
- **Secrets stay secret.** Keys live in `.env` locally and in GitHub Secrets in the cloud. Error text is scrubbed of keys and tokens before it is shown anywhere, because Python network errors can include the full request URL.

## Built to stay inside a free API tier

The Odds API's free tier gives 500 credits a month, and each market in each request costs 1 credit. Calling every sport daily would cost about 15 credits a day. The bot avoids that:

1. It first calls the API's **free** events endpoint to see whether a sport has any game today.
2. It only spends credits on sports that do, with one request per sport and never in a loop.
3. Sports use only the markets they need. MMA has no point spread, so it requests moneyline only (1 credit, not 2).
4. If a game has already started, it spends 1 extra credit on that sport to fetch the live score. This only happens when a game is underway at digest time.
5. It reads the remaining quota from the response headers. It warns you when credits run low and refuses a call it can't afford.

A busy month with all 15 leagues comes to roughly 315 credits by my estimate.

## How it works

```
GitHub Actions (cron: every hour at :15, 12:15-19:15 UTC)
        │
        ▼
   gate.py  ── inside the 7 AM-2 PM Central window? already sent today? (else stop)
        │
        ▼
   main.py  ── fetch, format, send, and leave a "sent today" marker
        │
        ├─ games_today.py ── free events check → filter to today (Central)
        │        └─ odds_api.py ── paid odds request, only if games exist
        │                          (+ scores request if a game is already live)
        ├─ format_digest.py ── best lines → Telegram HTML messages
        │        └─ team_emoji.py ── emoji per team
        │                 ├─ soccer_emoji.py ── kit colors
        │                 └─ ufc_flags.py ── fighter flags
        └─ telegram_bot.py ── sendMessage via the Telegram Bot API
```

### Why it runs every hour

GitHub's cron runs on UTC, which doesn't follow daylight saving, and GitHub starts scheduled runs **late**: often 30 to 50 minutes, and sometimes hours. My first version ran twice a day and only sent if the clock said exactly 8 AM Central. One day GitHub started both runs over an hour late, both correctly decided it was too late, and no digest was sent.

The fix is to stop depending on one moment:

1. The workflow starts every hour at 15 minutes past, from 12:15 to 19:15 UTC. That covers 7:15 AM to 2 PM Central in both summer and winter. GitHub is busiest at the top of the hour and recommends avoiding :00, so the schedule uses :15.
2. `gate.py` lets a run through only if it is inside that window. The first run inside it sends the digest.
3. `main.py` then writes a small marker, which the workflow saves in GitHub's cache under today's date. Later runs find the marker and do nothing, so you get one digest a day.
4. If a run is late or fails completely, the next hour's run covers it. A concurrency lock stops two runs from sending at once.

The tests simulate GitHub starting every run up to four hours late, in both seasons and on the days daylight saving starts and ends, and check that a run always lands inside the window.

## Tech

- Python 3.12, `requests` (calls the Telegram Bot API and The Odds API directly, with no bot framework)
- `python-dotenv` for local configuration, `zoneinfo`/`tzdata` for time zones
- GitHub Actions for scheduling and hosting
- [The Odds API](https://the-odds-api.com) for odds and scores

## Project structure

| File | Purpose |
|---|---|
| `main.py` | Entry point: runs the whole digest and handles errors |
| `gate.py` | Decides whether a scheduled run is inside the send window |
| `config.py` | Sports list, sport emoji, markets per sport, MMA filter, credit warning level |
| `odds_api.py` | Odds API requests: events (free), odds, and live scores |
| `games_today.py` | Converts to Central time, keeps today's games, attaches live scores |
| `format_digest.py` | Best-line logic and message formatting |
| `team_emoji.py` | Emoji for NFL, NBA, NHL, MLB and WNBA teams (matched by nickname) |
| `soccer_emoji.py` | Kit-color dots for soccer clubs, with spelling aliases |
| `ufc_flags.py` | Country flags for UFC fighters (hand-kept list) |
| `check_emoji.py` | Free tool: lists teams in the schedule that have no emoji yet |
| `telegram_bot.py` | Sends messages to Telegram |
| `http_utils.py` | Web requests that retry on temporary failures |
| `storage.py` | Saves every odds response: raw JSON archive + SQLite database |
| `results.py` | Fetches final scores from free sources, saves them, and attaches them to games |
| `names.py` | Decides whether two team names from different sources are the same team |
| `scripts/` | `backfill_from_raw.py` (rebuild the database), `publish_data.py` (save raw files to the private data repo) and an example SQL query |
| `get_chat_id.py` | One-time helper to find your Telegram chat ID |
| `tests/` | Automated tests (fake data only, no network) |
| `.github/workflows/daily-odds.yml` | The schedule and cloud job |
| `.github/workflows/results.yml` | Daily job that saves final scores to the private data repo |
| `.github/workflows/tests.yml` | Runs the tests on every push and pull request |
| `analysis/` | Read-only analysis tools: SQL, a loader and a starter notebook (own requirements) |

## Run it locally

You need Python 3.10+, a Telegram bot token from [@BotFather](https://t.me/BotFather), your chat ID, and a free [Odds API](https://the-odds-api.com) key.

```powershell
git clone https://github.com/YOUR-USERNAME/YOUR-REPO.git
cd YOUR-REPO
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # then fill in your three values
```

```powershell
python get_chat_id.py            # after messaging your bot, to find your chat ID
python games_today.py            # free: lists today's games for every sport
python check_emoji.py            # free: which teams have no emoji yet
python main.py --dry-run         # prints the digest (uses API credits)
python main.py                   # sends the digest to Telegram
python results.py --files-only   # saves yesterday's final scores (free, no credits)
```

## Odds history

Every time the bot pulls odds from The Odds API, `storage.py` keeps a copy. It reads the response the bot already paid for, so it makes no extra API calls and costs no credits.

- **Raw archive:** the untouched response, saved as `data/raw/YYYY-MM-DD/<sport_key>__HHMMSSZ.json` (UTC).
- **Database:** `data/odds.db` (SQLite) with `events`, `odds`, `results` and `pulls` tables, plus a `pregame_odds` view that hides prices pulled after kickoff (those are live odds). Every price is stored with its sportsbook, market, line and the time it was pulled, so line movement and sportsbook comparisons are one query away. Re-saving the same pull never creates duplicates.
- **Rebuildable:** the raw files are the source of truth. `python scripts/backfill_from_raw.py --rebuild` recreates the database from them, so the tables can change later without losing history.
- **Safe:** a storage problem is logged and never stops the Telegram digest.
- **Example:** `scripts/best_moneyline_today.sql` lists today's best moneyline per team across sportsbooks (`sqlite3 data/odds.db < scripts/best_moneyline_today.sql`).

The `data/` folder is not committed to this repository. A bot run on GitHub's temporary machines would lose it, so after the digest is sent, `scripts/publish_data.py` copies the new raw files into a separate **private** repository (`odds-history-data`) using a deploy key that can write to that one repo only (stored as the secret `ODDS_DATA_DEPLOY_KEY`). Files are only ever added, never overwritten. To analyze the data on your own computer, clone that repo and run `python scripts/backfill_from_raw.py --raw-dir <path to the clone>/raw --rebuild`. Raw odds files are not the only thing kept there: final scores are too (see below).

### Final scores

A second job, `results.py`, runs every morning (`.github/workflows/results.yml`) and saves the previous days' final scores from free sources that need no key and use no Odds API credits: ESPN's public scoreboard (NFL, NBA, WNBA and the soccer leagues), `statsapi.mlb.com` (MLB) and `api-web.nhle.com` (NHL). MMA has no free source and is skipped. Because the sources' own pages are large, only a compact record of the **final** games is saved, as `results_raw/YYYY-MM-DD/<sport_key>__HHMMSSZ.json` in the same private repo.

Scores are attached to games when the database is built, not when they are fetched. `names.py` matches them by league, team name (reusing the nickname and alias rules from the emoji files) and start time, so a name that does not match can be fixed with one alias and a rebuild, without fetching anything again. Rebuild everything with:

```powershell
python scripts/backfill_from_raw.py --rebuild --raw-dir ..\odds-history-data\raw --results-dir ..\odds-history-data\results_raw
```

`results.status` records how each game ended (`FINAL`, `FINAL_OT`, `FINAL_SO`, `FULL_TIME`, `FINAL_AET`, `FINAL_PEN`), so overtime and extra time can be filtered out.

### Analysis

`analysis/` has its own requirements (pandas, Jupyter) and only **reads** the database. `analysis/sql/game_lines.sql` builds one row per finished game with the consensus pre-game lines and the result, and `analysis/starter_questions.ipynb` answers example questions such as how often home underdogs win and whether NBA totals go over more on back-to-backs. See `analysis/README.md`.

## Tests

```powershell
pip install -r requirements-dev.txt
pytest
```

The tests use small fake games, so they make no API calls, spend no credits and need no secrets. They cover:

- the best-line logic for moneylines, spreads and totals, including tie-breaks and outlier books
- Central-time conversion and the "starts today" window, including the days daylight saving starts and ends
- message layout: live games, the soccer Draw row and total goals, MMA, HTML escaping, and splitting long slates under Telegram's limit
- team emoji, soccer kit colors and UFC flags (matching rules, no duplicates within a league, every league complete)
- the safety rails: secret scrubbing, the send window (including late GitHub starts), the sent-today marker, the credit guard, retries, and how one failing sport is reported
- the full `main.run()` flow with Telegram and the API replaced by fakes

I also checked that the tests are able to fail: breaking the code on purpose in a throwaway copy (for example shifting the send window or turning off secret scrubbing) made them fail every time.

GitHub runs the same tests on every push using `.github/workflows/tests.yml`. The daily digest job does not install the test tools.

## Deploy on GitHub Actions

1. Push this repo to GitHub.
2. Go to **Settings → Secrets and variables → Actions** and add three repository secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and `ODDS_API_KEY`.
3. Open the **Actions** tab, choose **Daily odds digest**, and click **Run workflow** to test. After that it runs by itself every day, sending at the first scheduled run after 7 AM Central (the first slot is 7:15 AM; GitHub's late starts push it later, and a run can send any time up to 2 PM). A manual run always sends immediately.

## Configuration

Everything you're likely to change is in `config.py`:

- `SPORTS` adds or removes leagues. Find sport keys at `https://api.the-odds-api.com/v4/sports?apiKey=YOUR_KEY`.
- `MARKETS`, `SOCCER_MARKETS` and `SPORT_MARKETS` set which markets each sport requests, and `TOTAL_LABELS` names the over/under section ("Total goals", "Total runs").
- `MIN_BOOKMAKERS` hides fights that few sportsbooks offer (used for MMA).
- `LOW_CREDITS_WARNING` sets when the bot warns you about your remaining quota.
- `SEND_FROM_HOUR` and `SEND_UNTIL_HOUR` set the send window (Central time). If you change the window, adjust the hourly cron in `.github/workflows/daily-odds.yml` to cover it in UTC; a test checks the two stay consistent.

## Keeping the emoji up to date

Emoji are matched by team name, so most things need no changes. A few events need a small update:

- **Promotion and relegation (soccer).** A newly promoted club has no entry yet and shows a plain ⚽ until you add its colors to `soccer_emoji.py`. Relegated clubs can stay, since they still appear in cups. The run log also prints `[emoji] unmapped soccer team: <name>`.
- **New fighters.** A fighter missing from `ufc_flags.py` shows without a flag, and the run log prints `[flag] unmapped fighter: <name>`.
- **Expansion, relocation or renames** in the other leagues (for example a team changing its name) need one line in `team_emoji.py`.
- Run `python check_emoji.py` at the start of each season. It is free and lists exactly what is missing.

## Limitations

- The API's MMA feed mixes UFC with other promotions and offers no promotion field. `MIN_BOOKMAKERS` trims low-coverage fights but can't isolate UFC perfectly, and the fighter flags are a hand-kept list that will always lag behind new fighters.
- A live score is a snapshot taken when the digest runs. The Telegram message does not update itself.
- Kit colors can clash (two red teams in one game), and some newer emoji may not render on older phones.
- GitHub may start scheduled runs late, so the digest usually arrives some 30 to 50 minutes after the 7:15 AM slot (around 8 AM Central), and in rare cases later (any time before 2 PM). If GitHub skipped every scheduled run in the window, nothing would be sent. On public repositories GitHub also pauses schedules after about 60 days without repository activity.
- The "sent today" marker lives in GitHub's cache, which can be evicted. In the unlikely event that happens mid-morning, a second digest could be sent.
- Each sport shows spread or total, not both. Showing both for a sport would cost 1 more credit per sport per day.

## License

MIT. See [LICENSE](LICENSE).
