"""
get_chat_id.py - run this ONCE to find your Telegram chat ID.

Why do we need a chat ID?
A bot can't message you until it knows which chat to send to. Every Telegram
chat has a unique number (the chat ID). When you message your bot, Telegram
stores that message, and we can ask Telegram for it to read your chat ID.

Before running: open Telegram, find your bot, and send it any message ("hi").
"""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

# load_dotenv reads the .env file and makes its values available through
# os.environ. We point at the .env that sits next to this script, so it works
# no matter which folder you run the script from.
load_dotenv(Path(__file__).parent / ".env")

token = os.environ.get("TELEGRAM_BOT_TOKEN")
if not token:
    raise SystemExit("TELEGRAM_BOT_TOKEN is missing from your .env file.")

# "getUpdates" is a Telegram Bot API method that returns recent messages
# people sent to your bot. The token is part of the URL - it's how Telegram
# knows which bot we are.
url = f"https://api.telegram.org/bot{token}/getUpdates"

# timeout=15 means "give up after 15 seconds" so the script can never hang forever.
response = requests.get(url, timeout=15)
data = response.json()

# Telegram replies with JSON containing "ok": true/false.
if not data.get("ok"):
    raise SystemExit(f"Telegram said no: {data.get('description')}")

updates = data["result"]
if not updates:
    raise SystemExit(
        "No messages found. Open Telegram, send your bot a message "
        "(like 'hi'), then run this script again."
    )

# Collect the unique chats that have messaged the bot (a dict avoids repeats).
chats = {}
for update in updates:
    message = update.get("message")
    if message:
        chat = message["chat"]
        chats[chat["id"]] = chat.get("first_name") or chat.get("title") or "?"

print("Found these chats:")
for chat_id, name in chats.items():
    print(f"  chat ID: {chat_id}   (name: {name})")
print("\nCopy the number into TELEGRAM_CHAT_ID in your .env file (no spaces).")
