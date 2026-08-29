import os


# =========================================================
# TELEGRAM BOT
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")


# =========================================================
# RENDER
# =========================================================

PORT = int(os.getenv("PORT", "10000"))

BASE_URL = os.getenv(
    "BASE_URL",
    os.getenv("RENDER_EXTERNAL_URL", "")
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
    in ("true", "1", "yes", "on")
)


# =========================================================
# YT-DLP
# =========================================================

DOWNLOAD_RETRIES = int(
    os.getenv("DOWNLOAD_RETRIES", "2")
)

SLEEP_BETWEEN_REQUESTS = float(
    os.getenv("SLEEP_BETWEEN_REQUESTS", "0")
)


# =========================================================
# COOKIES
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
        "DEBUG",
        "false"
    ).lower()
    in ("true", "1", "yes", "on")
)
