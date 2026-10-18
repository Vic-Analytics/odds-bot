"""
http_utils.py - one place for making web requests that retry on hiccups.

Why: at 8 AM the bot makes a handful of web requests. If one of them hits a
momentary problem (a timeout, a dropped connection, a server saying "try again
in a moment"), a single failure used to cost you that day's digest. Now we try
a few times before giving up.

What we retry:
  - network errors and timeouts
  - server errors (HTTP 500, 502, 503, 504)
  - HTTP 429 ("slow down"), but only when asked to (Telegram does this)

What we do NOT retry:
  - 4xx errors like a bad key (401) or a bad request. Trying again won't help.
  - The Odds API's 429, which usually means your monthly credits are used up.
    Retrying that would just waste time.
"""

import time
from urllib.parse import urlparse

import requests

SERVER_ERRORS = {500, 502, 503, 504}


def request_with_retries(method, url, attempts=3, waits=(2, 6), retry_429=False, **kwargs):
    """Like requests.request(), but tries up to `attempts` times.

    `waits` is how many seconds to pause after the 1st and 2nd failures.
    Returns the response (the caller checks the status code as usual). If the
    last attempt still got a server error, that response is returned so the
    caller's normal error message shows the status code.
    Raises RuntimeError if every attempt failed with a network error.
    """
    last_response = None
    last_error_name = None

    for attempt in range(attempts):
        pause = waits[min(attempt, len(waits) - 1)]
        try:
            response = requests.request(method, url, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as error:
            # Remember only the TYPE of error. The full message contains the
            # web address, and that can include your API key or bot token.
            last_error_name = type(error).__name__
            last_response = None
        else:
            if response.status_code in SERVER_ERRORS:
                last_response = response
                last_error_name = None
            elif retry_429 and response.status_code == 429:
                last_response = response
                last_error_name = None
                try:
                    # Telegram says how long to wait; never wait more than 30s.
                    pause = min(int(response.json()["parameters"]["retry_after"]), 30)
                except Exception:
                    pass
            else:
                return response

        if attempt < attempts - 1:
            time.sleep(pause)

    if last_response is not None:
        return last_response
    host = urlparse(url).netloc
    raise RuntimeError(f"Network problem calling {host}: {last_error_name} (tried {attempts} times)")
