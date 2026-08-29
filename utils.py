import os
import time
import logging
import yt_dlp

import config

logger = logging.getLogger(__name__)

# Simple in-memory cache: {url: (filepath, timestamp)}
_download_cache = {}
CACHE_TTL_SECONDS = 3600  # 1 hour


def build_ydl_opts(output_path: str) -> dict:
    opts = {
        "format": config.FORMAT_PRIORITY,
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": config.DOWNLOAD_RETRIES,
        "sleep_interval_requests": config.SLEEP_BETWEEN_REQUESTS,
        # Use the "android" player client instead of "web" — this avoids
        # YouTube's newer PO-Token / "page needs to be reloaded" check that
        # the default web client currently triggers.
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
            }
        },
    }
    if os.path.exists(config.COOKIES_FILE):
        opts["cookiefile"] = config.COOKIES_FILE
    return opts


def get_cached_file(url: str):
    """Return a cached filepath if it exists, is still valid, and the file is still on disk."""
    entry = _download_cache.get(url)
    if not entry:
        return None

    filepath, timestamp = entry
    if time.time() - timestamp > CACHE_TTL_SECONDS or not os.path.exists(filepath):
        _download_cache.pop(url, None)
        return None

    return filepath


def cache_file(url: str, filepath: str):
    _download_cache[url] = (filepath, time.time())


def check_file_size(filepath: str) -> bool:
    """Returns True if file is within Telegram's upload limit."""
    size = os.path.getsize(filepath)
    return size <= config.MAX_FILE_SIZE_BYTES


def download_video(url: str, file_id: str) -> str:
    """Blocking download call — run this in a thread executor from async code."""
    output_path = os.path.join(config.DOWNLOAD_DIR, f"{file_id}.%(ext)s")
    ydl_opts = build_ydl_opts(output_path)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        return filename


def friendly_error_message(error_text: str) -> str:
    """Map common yt-dlp errors to short, clear Bengali messages."""
    lowered = error_text.lower()

    if "sign in to confirm" in lowered:
        return (
            "❌ YouTube এই মুহূর্তে এটাকে bot request মনে করছে।\n"
            "সার্ভারে cookies.txt আপডেট করা দরকার হতে পারে।"
        )
    if "private video" in lowered:
        return "❌ এই ভিডিওটা private, ডাউনলোড করা যাবে না।"
    if "video unavailable" in lowered:
        return "❌ ভিডিওটা এখন আর available নেই (মুছে ফেলা হয়েছে বা region-locked)।"
    if "unsupported url" in lowered:
        return "❌ এই লিংকটা এখনো সাপোর্ট করে না।"
    if "no dlink" in lowered or "terabox" in lowered:
        return "❌ Terabox লিংক থেকে ডাউনলোড লিংক পাওয়া যায়নি। লিংকটা আবার চেক করুন।"

    return f"❌ ডাউনলোড ব্যর্থ হয়েছে:\n{error_text[:250]}"


async def is_subscribed(bot, user_id: int) -> bool:
    """Check if a user is a member of the required channel."""
    if not config.FORCE_SUB_ENABLED:
        return True
    try:
        member = await bot.get_chat_member(f"@{config.CHANNEL_USERNAME}", user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.error("Subscription check failed: %s", e)
        # If the check itself fails (e.g. bot not admin in channel),
        # fail safe by allowing access rather than blocking everyone.
        return True
