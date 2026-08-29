import os

# --- Telegram ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# --- Server ---
PORT = int(os.environ.get("PORT", 10000))

# --- Paths ---
COOKIES_FILE = "cookies.txt"

# --- yt-dlp behavior ---
SLEEP_BETWEEN_REQUESTS = 2  # seconds, helps avoid YouTube bot-detection
DOWNLOAD_RETRIES = 3

# --- Supported platforms (shown in /help) ---
SUPPORTED_SITES = ["YouTube", "Facebook", "Instagram", "Twitter / X"]

# --- Force Subscribe ---
# Your channel's public username, without the @ symbol
# Example: if your channel is https://t.me/mychannel, set CHANNEL_USERNAME = "mychannel"
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "")
FORCE_SUB_ENABLED = bool(CHANNEL_USERNAME)
