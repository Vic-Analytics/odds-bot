"""
ping_healthcheck.py - tell healthchecks.io that today's digest was delivered.

This is the "missed-digest alarm". healthchecks.io expects one ping a day. If the
ping does not arrive by the deadline you set there, it sends you an alert (see the
README for the one-time setup). Because the alert comes from outside GitHub, it
still reaches you when GitHub, the schedule or the Telegram token is what broke.

The ping URL is a secret (anyone who has it can fake a ping), so it lives in the
GitHub secret HEALTHCHECK_PING_URL and is never printed.

This must never get in the way of the digest, so it:
  * is called only AFTER the digest has been sent,
  * gives up after 3 tries of at most 10 seconds each,
  * never raises and always exits 0, whatever happens,
  * does nothing if the secret is not set (so the alarm is optional).

    python scripts/ping_healthcheck.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from http_utils import request_with_retries  # noqa: E402

ENV_NAME = "HEALTHCHECK_PING_URL"


def log(message):
    print(f"[healthcheck] {message}", file=sys.stderr)


def ping(url=None):
    """Send the ping. Returns True if healthchecks.io accepted it. Never raises."""
    url = (os.environ.get(ENV_NAME, "") if url is None else url).strip()
    if not url:
        log(f"{ENV_NAME} is not set, so no ping was sent (the alarm is switched off)")
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


def main():
    ping()
    return 0          # a failed ping must never turn the run red or stop anything after it


if __name__ == "__main__":
    sys.exit(main())
