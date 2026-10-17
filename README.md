# Daily Sports Odds Digest (Telegram Bot)

A Python bot that sends a formatted digest of **today's games and best available betting lines** to Telegram every morning at 8 AM Central. It runs in the cloud on GitHub Actions, so no computer needs to stay on.

> For information only. This project does not place bets or give betting advice.

## What it looks like

One message per sport, with the best moneyline and spread across all US sportsbooks and the book offering each price:

```
🏒 NHL — Fri, Oct 16

8:10 PM · Pittsburgh Penguins @ Colorado Avalanche
  Moneyline
  Pittsburgh Penguins  +150  (DraftKings)
  Colorado Avalanche   -170  (FanDuel)

  Spread
  Pittsburgh Penguins  +1.5  (-130, BetMGM)
  Colorado Avalanche   -1.5  (+110, Caesars)
```

*(Illustrative numbers. Real messages use bold headlines and Telegram quote blocks.)*

## Features

- **Best line across all books.** For each game it finds the highest moneyline price per team. For spreads it takes the most common point spread, then the best price at that number, so a rare odd alternate line can't look like a bargain.
- **Totals for soccer.** Soccer leagues show the over/under on total goals instead of a point spread, using the same "most common line, then best price" logic.
- **Today only, in Central time.** The API returns UTC. Start times are converted with a named time zone (`America/Chicago`), so daylight saving is handled automatically.
- **14 leagues.** NFL, NBA, MLB, NHL, WNBA, UFC/MMA, EPL, Champions League, Europa League, La Liga, Serie A, Bundesliga, Ligue 1 and MLS. Soccer gets a Draw row, and fights get a moneyline-only layout. Adding a league is one line in `config.py`.
- **Telegram-friendly output.** HTML formatting, one message per sport, and automatic splitting when a long slate would pass Telegram's 4096-character limit.
- **Failure alerts.** If a sport fails, the others still send, and a short error message arrives on Telegram. The run also exits with an error code, so GitHub marks it failed.
- **Secrets stay secret.** Keys live in `.env` locally and in GitHub Secrets in the cloud. Error text is scrubbed of keys and tokens before it is shown anywhere, because Python network errors can include the full request URL.

## Built to stay inside a free API tier

The Odds API's free tier gives 500 credits a month, and each market in each request costs 1 credit. Calling every sport daily would cost about 15 credits a day. The bot avoids that:

1. It first calls the API's **free** events endpoint to see whether a sport has any game today.
2. It only spends credits on sports that do, with one request per sport and never in a loop.
3. Sports use only the markets they need. MMA has no point spread, so it requests moneyline only (1 credit, not 2).
4. It reads the remaining quota from the response headers. It warns you when credits run low and refuses a call it can't afford.

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
        ├─ format_digest.py ── best lines → Telegram HTML messages
        └─ telegram_bot.py ── sendMessage via the Telegram Bot API
```

GitHub's cron runs on UTC, which doesn't follow daylight saving. The workflow schedules both 13:00 and 14:00 UTC, and `main.py --only-at-hour 8` makes sure exactly one of them sends.

## Tech

- Python 3.12, `requests` (calls the Telegram Bot API and The Odds API directly, with no bot framework)
- `python-dotenv` for local configuration, `zoneinfo`/`tzdata` for time zones
- GitHub Actions for scheduling and hosting
- [The Odds API](https://the-odds-api.com) for odds data

## Project structure

| File | Purpose |
|---|---|
| `main.py` | Entry point: runs the whole digest and handles errors |
| `config.py` | Sports list, emoji, markets, per-sport rules, credit warning level |
| `odds_api.py` | Odds API requests (events and odds) |
| `games_today.py` | Converts to Central time and keeps today's games |
| `format_digest.py` | Best-line logic and message formatting |
| `telegram_bot.py` | Sends messages to Telegram |
| `get_chat_id.py` | One-time helper to find your Telegram chat ID |
| `.github/workflows/daily-odds.yml` | The schedule and cloud job |

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
python main.py --dry-run         # prints the digest (uses API credits)
python main.py                   # sends the digest to Telegram
```

## Deploy on GitHub Actions

1. Push this repo to GitHub.
2. Go to **Settings → Secrets and variables → Actions** and add three repository secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` and `ODDS_API_KEY`.
3. Open the **Actions** tab, choose **Daily odds digest**, and click **Run workflow** to test. After that it runs by itself every day at 8 AM Central.

## Configuration

Everything you're likely to change is in `config.py`:

- `SPORTS` adds or removes leagues. Find sport keys at `https://api.the-odds-api.com/v4/sports?apiKey=YOUR_KEY`.
- `SPORT_MARKETS` and `MIN_BOOKMAKERS` set per-sport rules, such as moneyline-only MMA.
- `LOW_CREDITS_WARNING` sets when the bot warns you about your remaining quota.

## Limitations

- The API's MMA feed mixes UFC with other promotions and offers no promotion field. `MIN_BOOKMAKERS` trims low-coverage fights but can't isolate UFC perfectly.
- GitHub may start scheduled runs a few minutes late, and on public repositories it pauses schedules after about 60 days without repository activity.
- Totals (over/under) are shown for soccer only. Adding them to other sports would cost 1 more credit per sport per day.
