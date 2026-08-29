import os
import uuid
import logging
import yt_dlp

import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# Telegram file_id cache: {url: file_id}
# Once a video has been uploaded to Telegram once, Telegram keeps its own
# copy forever. Reusing the file_id for a repeat request of the same URL
# means we send a tiny text reference instead of re-downloading and
# re-uploading the whole file — this is what actually saves bandwidth.
# ---------------------------------------------------------
_file_id_cache = {}


def get_cached_file_id(url: str):
    return _file_id_cache.get(url)


def cache_file_id(url: str, file_id: str):
    _file_id_cache[url] = file_id


# ---------------------------------------------------------
# Short-lived mapping so inline-button callback_data (max 64 bytes) can
# reference a full URL without embedding it directly.
# ---------------------------------------------------------
_pending_urls = {}


def store_pending_url(url: str) -> str:
    short_id = uuid.uuid4().hex[:10]
    _pending_urls[short_id] = url
    return short_id


def get_pending_url(short_id: str):
    return _pending_urls.get(short_id)


# ---------------------------------------------------------
# yt-dlp options
# ---------------------------------------------------------
def _base_opts() -> dict:
    """Shared yt-dlp options. Works for YouTube, Facebook, Instagram,
    Twitter/X — yt-dlp auto-detects the site from the URL, no per-site code
    needed. Cookies (if present) help avoid YouTube's bot-detection wall.
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": config.DOWNLOAD_RETRIES,
        "sleep_interval_requests": config.SLEEP_BETWEEN_REQUESTS,
        "extractor_args": {
            "youtube": {
                "player_client": ["web"],
            }
        },
    }
    if os.path.exists(config.COOKIES_FILE):
        opts["cookiefile"] = config.COOKIES_FILE
    return opts


QUALITY_HEIGHTS = [1080, 720, 480, 360]

# Telegram Bot API hard limit for bot-uploaded files.
MAX_TELEGRAM_FILE_BYTES = 50 * 1024 * 1024  # 50 MB

# Where downloaded files are temporarily stored before upload + deletion.
_DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(_DOWNLOAD_DIR, exist_ok=True)


def list_quality_options(url: str) -> dict:
    """Metadata-only check (no download) of which qualities are available
    as a single combined video+audio stream (no ffmpeg merge needed later).
    Returns {'qualities': {'1080p': False, ...}, 'title': str,
    'thumbnail': str or None}.
    """
    qualities = {f"{h}p": False for h in QUALITY_HEIGHTS}
    qualities["audio"] = False

    opts = _base_opts()
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    formats = info.get("formats", [info]) if isinstance(info, dict) else []

    for f in formats:
        acodec = f.get("acodec")
        vcodec = f.get("vcodec")
        height = f.get("height")
        has_audio = acodec not in (None, "none")
        has_video = vcodec not in (None, "none")

        if has_audio and has_video and height in QUALITY_HEIGHTS:
            qualities[f"{height}p"] = True
        elif has_audio and not has_video:
            qualities["audio"] = True

    return {
        "qualities": qualities,
        "title": info.get("title", "ভিডিও"),
        "thumbnail": info.get("thumbnail"),
    }


def download_media(url: str, quality: str):
    """
    Actually downloads the video/audio to local disk (so we don't depend on
    Telegram being able to fetch a YouTube-issued direct URL, which fails
    because those URLs are IP-locked to whichever server requested them).

    Returns a dict: {"path": str, "is_audio": bool, "size": int} on success,
    or None if the download failed or the file exceeds Telegram's 50MB
    bot-upload limit.

    Caller is responsible for deleting the file after uploading it —
    see delete_file().
    """
    opts = _base_opts()
    file_id = uuid.uuid4().hex
    is_audio = quality == "audio"

    if is_audio:
        opts["format"] = "bestaudio[acodec!=none]"
        outtmpl = os.path.join(_DOWNLOAD_DIR, f"{file_id}.%(ext)s")
    else:
        height = quality.rstrip("p")
        opts["format"] = f"best[height={height}][acodec!=none][vcodec!=none]"
        outtmpl = os.path.join(_DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    opts["outtmpl"] = outtmpl

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
    except Exception as e:
        logger.info("Download failed: %s", e)
        return None

    if not os.path.exists(filepath):
        return None

    size = os.path.getsize(filepath)
    if size > MAX_TELEGRAM_FILE_BYTES:
        # Too big for a bot to upload via the standard Bot API — clean up
        # and report failure so the caller can tell the user.
        try:
            os.remove(filepath)
        except OSError:
            pass
        return None

    return {"path": filepath, "is_audio": is_audio, "size": size}


def delete_file(path: str):
    try:
        os.remove(path)
    except OSError as e:
        logger.warning("Could not delete temp file %s: %s", path, e)


# ---------------------------------------------------------
# Force-subscribe check
# ---------------------------------------------------------
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
