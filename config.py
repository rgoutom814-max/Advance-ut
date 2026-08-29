import os

# --- Telegram ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# --- Server ---
PORT = int(os.environ.get("PORT", 10000))

# --- Paths ---
DOWNLOAD_DIR = "downloads"
COOKIES_FILE = "cookies.txt"

# --- Limits ---
# Telegram bots can't send files larger than 50MB through the Bot API
MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# --- Download behavior ---
# Simplest possible fallback chain — "best" alone almost always matches
# a pre-merged format, so we don't depend on ffmpeg being installed.
FORMAT_PRIORITY = "best"
SLEEP_BETWEEN_REQUESTS = 2  # seconds, helps avoid YouTube bot-detection
DOWNLOAD_RETRIES = 3

# --- Supported platforms (shown in /help) ---
SUPPORTED_SITES = ["YouTube", "Terabox", "Facebook", "Instagram", "Twitter / X"]

# --- Force Subscribe ---
# Your channel's public username, without the @ symbol
# Example: if your channel is https://t.me/mychannel, set CHANNEL_USERNAME = "mychannel"
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "")
FORCE_SUB_ENABLED = bool(CHANNEL_USERNAME)
