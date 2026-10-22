# Daily Sports Odds Digest (Telegram Bot)

[![Tests](https://github.com/Vic-Analytics/odds-bot/actions/workflows/tests.yml/badge.svg)](https://github.com/Vic-Analytics/odds-bot/actions/workflows/tests.yml)

A Python bot that sends a formatted digest of **today's games and best available betting lines** to Telegram every morning at 8 AM Central. It runs in the cloud on GitHub Actions, so no computer needs to stay on.

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
┃ Spread
┃ 🐧 Pittsburgh Penguins  +1.5  (-130, BetMGM)
┃ 🏔️ Colorado Avalanche  -1.5  (+110, Caesars)
```

Soccer swaps the spread for the over/under on goals, and clubs get kit-color dots:

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
- **14 leagues.** NFL, NBA, MLB, NHL, WNBA, UFC/MMA, EPL, Champions League, Europa League, La Liga, Serie A, Bundesliga, Ligue 1 and MLS. Adding a league is one line in `config.py`.
- **Market per sport.** US leagues show moneyline and spread. Soccer shows moneyline (with the draw) and total goals. MMA shows moneyline only.
- **Live game awareness.** A game that has already started when the digest runs is marked 🔴 LIVE with its current score, and its odds are labeled as live.
- **Team emoji.** NFL, NBA, NHL, MLB and WNBA teams get an emoji matched by nickname, so "LA Clippers" and "Los Angeles Clippers" both work. Soccer clubs get two kit-color dots (a one-color kit shows its dot twice, and the Draw row gets 🤝🤝) so every row lines up. UFC fighters get a country flag from a hand-kept list, because the API doesn't provide nationality.
- **Telegram-friendly output.** HTML formatting, one message per sport, and automatic splitting when a long slate would pass Telegram's 4096-character limit.
- **Failure alerts.** If a sport fails, the others still send, and a short error message arrives on Telegram. The run also exits with an error code, so GitHub marks it failed.
- **Retries.** Timeouts, dropped connections and temporary server errors are retried up to 3 times. Client errors (a bad key) and exhausted API credits are not, because trying again can't help.
- **Tested.** About 90 automated tests run on every push (see below).
- **Secrets stay secret.** Keys live in `.env` locally and in GitHub Secrets in the cloud. Error text is scrubbed of keys and tokens before it is shown anywhere, because Python network errors can include the full request URL.

## Built to stay inside a free API tier

The Odds API's free tier gives 500 credits a month, and each market in each request costs 1 credit. Calling every sport daily would cost about 15 credits a day. The bot avoids that:

1. It first calls the API's **free** events endpoint to see whether a sport has any game today.
2. It only spends credits on sports that do, with one request per sport and never in a loop.
3. Sports use only the markets they need. MMA has no point spread, so it requests moneyline only (1 credit, not 2).
4. If a game has already started, it spends 1 extra credit on that sport to fetch the live score. This only happens when a game is underway at digest time.
5. It reads the remaining quota from the response headers. It warns you when credits run low and refuses a call it can't afford.

A busy month with all 14 leagues comes to roughly 300 credits by my estimate.

## How it works

```
GitHub Actions (cron: 13:00 and 14:00 UTC)
        │
        ▼
   main.py  ── skips unless it is really 8 AM Central (daylight saving guard)
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

GitHub's cron runs on UTC, which doesn't follow daylight saving. The workflow schedules both 13:00 and 14:00 UTC, and `main.py --only-at-hour 8` makes sure exactly one of them sends.

## Tech

- Python 3.12, `requests` (calls the Telegram Bot API and The Odds API directly, with no bot framework)
- `python-dotenv` for local configuration, `zoneinfo`/`tzdata` for time zones
- GitHub Actions for scheduling and hosting
- [The Odds API](https://the-odds-api.com) for odds and scores

## Project structure

| File | Purpose |
|---|---|
| `main.py` | Entry point: runs the whole digest and handles errors |
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
| `get_chat_id.py` | One-time helper to find your Telegram chat ID |
| `tests/` | Automated tests (fake data only, no network) |
| `.github/workflows/daily-odds.yml` | The schedule and cloud job |
| `.github/workflows/tests.yml` | Runs the tests on every push and pull request |

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
```

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
- the safety rails: secret scrubbing, the 8 AM guard in both daylight-saving seasons, the credit guard, retries, and how one failing sport is reported
- the full `main.run()` flow with Telegram and the API replaced by fakes

I also checked that the tests are able to fail: breaking the code on purpose in a throwaway copy (for example flipping the 8 AM check or turning off secret scrubbing) made them fail every time.

GitHub runs the same tests on every push using `.github/workflows/tests.yml`. The daily digest job does not install the test tools.

## Deploy on GitHub Actions

1. Push this repo to GitHub.
2. Go to **Settings → Secrets and variables → Actions** and add three repository secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and `ODDS_API_KEY`.
3. Open the **Actions** tab, choose **Daily odds digest**, and click **Run workflow** to test. After that it runs by itself every day at 8 AM Central.

## Configuration

Everything you're likely to change is in `config.py`:

- `SPORTS` adds or removes leagues. Find sport keys at `https://api.the-odds-api.com/v4/sports?apiKey=YOUR_KEY`.
- `MARKETS`, `SOCCER_MARKETS` and `SPORT_MARKETS` set which markets each sport requests.
- `MIN_BOOKMAKERS` hides fights that few sportsbooks offer (used for MMA).
- `LOW_CREDITS_WARNING` sets when the bot warns you about your remaining quota.

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
- GitHub may start scheduled runs a few minutes late, and on public repositories it pauses schedules after about 60 days without repository activity.
- Totals (over/under) are shown for soccer only. Adding them to other sports would cost 1 more credit per sport per day.
