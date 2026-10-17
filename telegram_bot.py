"""
telegram_bot.py - everything related to talking to Telegram.

Other scripts will import send_message() from here. You can also run this
file directly to send yourself a test message:

    python telegram_bot.py
"""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

# Read the secrets from .env (on GitHub Actions there is no .env file, and the
# values come from GitHub Secrets instead - load_dotenv just does nothing then).
load_dotenv(Path(__file__).parent / ".env")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def send_message(text):
    """Send `text` to your Telegram chat. Raises an error if it fails.

    The text can use simple HTML like <b>bold</b> and <i>italic</i>.
    Telegram rejects messages longer than 4096 characters, which is why
    we'll send one message per sport later.
    """
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing from .env")

    # "sendMessage" is the Telegram Bot API method for sending text.
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    # This dictionary is the data we send along with the request.
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",  # lets us use <b>bold</b> in messages
    }

    # POST = "send data to a server". timeout stops us waiting forever.
    response = requests.post(url, json=payload, timeout=15)

    # Telegram explains errors in the response body, so show that if we fail.
    if not response.ok:
        raise RuntimeError(f"Telegram error {response.status_code}: {response.text}")


# This block only runs when you start THIS file directly (python telegram_bot.py),
# not when another script imports it.
if __name__ == "__main__":
    send_message("<b>Test message</b>\nYour odds bot can talk to Telegram. ✅")
    print("Sent! Check Telegram.")
