import os
import logging
import yt_dlp

import config

logger = logging.getLogger(__name__)

# Telegram file_id cache: {url: file_id} — once a video has been sent to
# Telegram once, Telegram keeps its own copy. Reusing the file_id for the
# next request of the same URL means we send a tiny text reference instead
# of re-downloading from YouTube and re-uploading the whole file, which is
# what actually costs Render bandwidth. This cache has no TTL since
# Telegram file_ids for content a bot uploaded remain valid indefinitely.
_file_id_cache = {}


def get_cached_file_id(url: str):
    return _file_id_cache.get(url)


def cache_file_id(url: str, file_id: str):
    _file_id_cache[url] = file_id


# Short-lived mapping so inline-button callback_data (max 64 bytes) can
# reference a full URL without embedding it directly.
_pending_urls = {}


def store_pending_url(url: str) -> str:
    import uuid
    short_id = uuid.uuid4().hex[:10]
    _pending_urls[short_id] = url
    return short_id


def get_pending_url(short_id: str):
    return _pending_urls.get(short_id)


def _base_extractor_opts() -> dict:
    """Shared yt-dlp options (no format restriction) for metadata-only lookups."""
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


def list_quality_options(url: str) -> dict:
    """Metadata-only check (no download) of which qualities have a combined
    video+audio format we could hand to Telegram as a direct URL. Returns
    e.g. {'1080p': False, '720p': True, '480p': True, '360p': True,
    'audio': True} — callers should only offer buttons for True entries.
    """
    result = {f"{h}p": False for h in QUALITY_HEIGHTS}
    result["audio"] = False

    opts = _base_extractor_opts()
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
            result[f"{height}p"] = True
        elif has_audio and not has_video:
            result["audio"] = True

    return result


def get_direct_url_for_quality(url: str, quality: str):
    """Metadata-only lookup of a direct URL for one specific quality
    ('1080p'/'720p'/'480p'/'360p'/'audio'). Returns None if unavailable.
    """
    opts = _base_extractor_opts()
    if quality == "audio":
        opts["format"] = "bestaudio[acodec!=none]"
    else:
        height = quality.rstrip("p")
        opts["format"] = f"best[height={height}][acodec!=none][vcodec!=none]"

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return info.get("url")


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
