"""
main.py - the daily odds digest. This is the file that gets scheduled.

    python main.py             fetch today's games and send them to Telegram
    python main.py --dry-run   same, but only PRINT the messages (nothing sent)
    python main.py --marker-file sent.marker
                               same as the first, and also write that file once
                               the digest is delivered (used by the scheduled
                               GitHub run to avoid sending twice in one day)

Note: a dry run still calls the Odds API, so it still uses credits for any
sport that has a game today.

What happens, in order:
  1. For each sport in config.py, check (for free) if any game starts today.
  2. If yes, fetch odds (costs credits), format them, send one message per sport.
  3. If nothing is on today, send a short "no games" note.
  4. If credits are running low, add a warning.
  5. If anything went wrong, send a short error message and exit with an
     error code (GitHub Actions uses that to mark the run as failed).
"""

import html
import sys
import time
from pathlib import Path

import telegram_bot
from config import LOW_CREDITS_WARNING, MIN_BOOKMAKERS, SPORTS, markets_for
from format_digest import format_sport_messages, plain_preview
from games_today import fetch_todays_games_with_odds
from odds_api import ODDS_API_KEY
from telegram_bot import send_message


def scrub(text):
    """Hide secrets before showing an error anywhere.

    Python's network errors can include the full web address that failed, and
    that address contains your API key or bot token. We swap them for ***.
    """
    for secret in (ODDS_API_KEY, telegram_bot.BOT_TOKEN):
        if secret:
            text = text.replace(secret, "***")
    return text


def deliver(message, dry_run):
    """Send one message to Telegram (or just print it in a dry run)."""
    if dry_run:
        print(plain_preview(message))
        print("\n" + "-" * 40 + "\n")
        return
    send_message(message)
    time.sleep(1)  # Telegram dislikes bursts; one message per second is safe


def run(dry_run, marker_path=None):
    """Do the whole digest. Returns 0 if all went well, 1 if anything failed.

    `marker_path` is used by the scheduled GitHub run. When the digest was
    delivered, we write a small file there. The workflow saves it, so the
    next hourly run knows today's digest is already done and does nothing.
    We do NOT write it if every sport failed, so the next run can try again.
    """
    errors = []
    credits_left = None   # we learn this from the Odds API as we go
    sent_any = False

    for name, key in SPORTS.items():
        # One sport failing should not stop the other sports, so each gets
        # its own try/except. We collect the problems and report them at the end.
        try:
            games, remaining = fetch_todays_games_with_odds(
                key, credits_left, markets_for(name)
            )
            if remaining is not None:
                credits_left = int(float(remaining))

            # Some sports (MMA) hide games that few sportsbooks offer.
            minimum = MIN_BOOKMAKERS.get(name, 0)
            games = [g for g in games if len(g["bookmakers"]) >= minimum]

            for message in format_sport_messages(name, games):
                deliver(message, dry_run)
                sent_any = True
        except Exception as error:
            errors.append(f"{name}: {scrub(str(error))}")

    if not sent_any and not errors:
        deliver("No games today in your sports.", dry_run)

    if credits_left is not None and credits_left < LOW_CREDITS_WARNING:
        deliver(f"⚠️ Only <b>{credits_left}</b> Odds API credits left this month.", dry_run)

    if errors:
        # Keep the error short: first 1000 characters, escaped for Telegram HTML.
        details = html.escape("\n".join(errors)[:1000])
        deliver(f"⚠️ <b>Odds bot problem</b>\n{details}", dry_run)

    # "Delivered" = at least one real digest message went out, or there was
    # simply nothing to report. If every sport failed, we leave no marker, so
    # the next hourly run tries again.
    delivered = sent_any or not errors
    if marker_path and delivered and not dry_run:
        Path(marker_path).write_text("digest sent\n", encoding="utf-8")

    return 1 if errors else 0


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv

    # The scheduled GitHub run passes "--marker-file sent.marker" (see
    # .github/workflows/daily-odds.yml). Deciding WHEN to run is gate.py's job.
    marker_path = None
    if "--marker-file" in sys.argv:
        marker_path = sys.argv[sys.argv.index("--marker-file") + 1]

    try:
        exit_code = run(dry_run, marker_path)
    except Exception as error:
        # Something unexpected (for example Telegram itself being down).
        message = scrub(str(error))
        print(f"FAILED: {message}", file=sys.stderr)
        if not dry_run:
            try:
                send_message("⚠️ <b>Odds bot crashed</b>\n" + html.escape(message[:500]))
            except Exception:
                pass  # we can't reach Telegram; the failed run is the signal
        exit_code = 1

    # A non-zero exit code tells GitHub Actions the run failed, and GitHub
    # emails you about failed runs.
    sys.exit(exit_code)
