"""
ping_healthcheck.py - tell healthchecks.io that today's digest (or recap) was delivered.

This is the "missed-message alarm". healthchecks.io expects one ping a day. If the
ping does not arrive by the deadline you set there, it sends you an alert (see the
README for the one-time setup). Because the alert comes from outside GitHub, it
still reaches you when GitHub, the schedule or the Telegram token is what broke.

There are two checks, each with its own URL: the morning digest (HEALTHCHECK_PING_URL,
the default) and the evening results recap (HEALTHCHECK_RECAP_PING_URL, chosen with
--url-env). Each URL is a secret (anyone who has it can fake a ping), so it lives in a
GitHub secret and is never printed.

This must never get in the way of the digest, so it:
  * is called only AFTER the digest has been sent,
  * gives up after 3 tries of at most 10 seconds each,
  * never raises and always exits 0, whatever happens,
  * does nothing if the secret is not set (so the alarm is optional).

    python scripts/ping_healthcheck.py                                       the digest check
    python scripts/ping_healthcheck.py --url-env HEALTHCHECK_RECAP_PING_URL  the recap check
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from http_utils import request_with_retries  # noqa: E402

ENV_NAME = "HEALTHCHECK_PING_URL"


def log(message):
    print(f"[healthcheck] {message}", file=sys.stderr)


def ping(url=None, env_name=ENV_NAME):
    """Send the ping. Returns True if healthchecks.io accepted it. Never raises."""
    url = (os.environ.get(env_name, "") if url is None else url).strip()
    if not url:
        log(f"{env_name} is not set, so no ping was sent (the alarm is switched off)")
        return False
    if not url.startswith("https://"):
        log("the ping URL must start with https://, so no ping was sent")
        return False
    try:
        response = request_with_retries("GET", url, attempts=3, waits=(2, 4), timeout=10)
    except Exception as error:
        # Only the TYPE of the error: its text can contain the web address.
        log(f"the ping could not be sent ({type(error).__name__})")
        return False
    if not response.ok:
        log(f"healthchecks.io answered HTTP {response.status_code}, so check the URL in the secret")
        return False
    print("[healthcheck] pinged healthchecks.io")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tell healthchecks.io that a message was delivered.")
    parser.add_argument("--url-env", default=ENV_NAME, metavar="NAME",
                        help="the environment variable that holds the ping URL (default %(default)s)")
    args, _ignored = parser.parse_known_args(argv)       # unknown extras are ignored: this must never fail the run
    ping(env_name=args.url_env)
    return 0          # a failed ping must never turn the run red or stop anything after it


if __name__ == "__main__":
    sys.exit(main())
