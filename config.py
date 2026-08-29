import os


# =========================================================
# TELEGRAM BOT
# =========================================================

BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    ""
)


# =========================================================
# RENDER PORT
# =========================================================

PORT = int(
    os.getenv(
        "PORT",
        "10000"
    )
)


# =========================================================
# PUBLIC SERVER URL
# =========================================================
# Render সাধারণত RENDER_EXTERNAL_URL নিজে দেয়।
# চাইলে Render Environment Variables-এ BASE_URL-ও দিতে পারো।
#
# Example:
# https://your-bot-name.onrender.com
# =========================================================

BASE_URL = os.getenv(
    "BASE_URL",
    os.getenv(
        "RENDER_EXTERNAL_URL",
        ""
    )
).rstrip("/")


# =========================================================
# FORCE SUBSCRIBE
# =========================================================

CHANNEL_USERNAME = os.getenv(
    "CHANNEL_USERNAME",
    ""
).lstrip("@").strip()


FORCE_SUB_ENABLED = (
    os.getenv(
        "FORCE_SUB_ENABLED",
        "false"
    ).lower()
    in (
        "true",
        "1",
        "yes",
        "on"
    )
)


# =========================================================
# YOUTUBE / YT-DLP
# =========================================================

DOWNLOAD_RETRIES = int(
    os.getenv(
        "DOWNLOAD_RETRIES",
        "2"
    )
)


SLEEP_BETWEEN_REQUESTS = float(
    os.getenv(
        "SLEEP_BETWEEN_REQUESTS",
        "0"
    )
)


# =========================================================
# COOKIES
# =========================================================
# যদি cookies.txt ব্যবহার করো:
#
# COOKIES_FILE = "cookies.txt"
#
# না হলে খালি থাকবে।
# =========================================================

COOKIES_FILE = os.getenv(
    "COOKIES_FILE",
    ""
)


# =========================================================
# SUPPORTED SITES
# =========================================================

SUPPORTED_SITES = [
    "YouTube",
]


# =========================================================
# DEBUG
# =========================================================

DEBUG = (
    os.getenv(
        "
