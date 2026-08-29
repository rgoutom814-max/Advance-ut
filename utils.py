import os
import logging
import time
import threading
import uuid

import yt_dlp
import config

logger = logging.getLogger(__name__)

QUALITY_HEIGHTS = [1080, 720, 480, 360]

# ---------------------------------------------------------
# CACHE
# ---------------------------------------------------------

_file_id_cache = {}
_pending_urls = {}
_metadata_cache = {}

_cache_lock = threading.Lock()

PENDING_TTL = 30 * 60
METADATA_TTL = 5 * 60


# ---------------------------------------------------------
# TELEGRAM CACHE
# ---------------------------------------------------------

def get_cached_file_id(url: str, quality=None):
    key = (url, quality or "default")

    with _cache_lock:
        return _file_id_cache.get(key)


def cache_file_id(url: str, file_id: str, quality=None):
    key = (url, quality or "default")

    with _cache_lock:
        _file_id_cache[key] = file_id


# ---------------------------------------------------------
# PENDING URL
# ---------------------------------------------------------

def store_pending_url(url: str) -> str:
    short_id = uuid.uuid4().hex[:10]

    with _cache_lock:
        _pending_urls[short_id] = (url, time.time())

    return short_id


def get_pending_url(short_id: str):
    with _cache_lock:
        item = _pending_urls.get(short_id)

        if not item:
            return None

        url, created = item

        if time.time() - created > PENDING_TTL:
            del _pending_urls[short_id]
            return None

        return url


# ---------------------------------------------------------
# YT-DLP OPTIONS
# ---------------------------------------------------------

def _base_extractor_opts():

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,

        "retries": max(
            1,
            int(getattr(config, "DOWNLOAD_RETRIES", 2))
        ),

        "fragment_retries": 2,

        "sleep_interval": 0,
        "sleep_interval_requests": 0,

        "extractor_args": {
            "youtube": {
                "player_client": [
                    "android_vr",
                    "web"
                ]
            }
        },

        "geo_bypass": True,
    }

    cookie_file = getattr(
        config,
        "COOKIES_FILE",
        None
    )

    if cookie_file and os.path.exists(cookie_file):
        opts["cookiefile"] = cookie_file

    return opts


# ---------------------------------------------------------
# METADATA CACHE
# ---------------------------------------------------------

def _extract_info(url: str):

    now = time.time()

    with _cache_lock:

        cached = _metadata_cache.get(url)

        if cached:

            created, info = cached

            if now - created < METADATA_TTL:
                return info

    opts = _base_extractor_opts()

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(
            url,
            download=False
        )

    with _cache_lock:
        _metadata_cache[url] = (
            now,
            info
        )

    return info


# ---------------------------------------------------------
# QUALITY LIST
# ---------------------------------------------------------

def list_quality_options(url: str):

    qualities = {
        f"{h}p": False
        for h in QUALITY_HEIGHTS
    }

    qualities["audio"] = False

    info = _extract_info(url)

    formats = info.get(
        "formats",
        []
    )

    for f in formats:

        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        height = f.get("height")

        has_video = (
            vcodec not in
            (None, "none")
        )

        has_audio = (
            acodec not in
            (None, "none")
        )

        # Audio only
        if has_audio and not has_video:
            qualities["audio"] = True

        # Video + Audio
        if (
            has_video
            and has_audio
            and height
        ):

            for target in QUALITY_HEIGHTS:

                if height == target:
                    qualities[f"{target}p"] = True

    return {
        "qualities": qualities,
        "title": info.get(
            "title",
            "ভিডিও"
        ),
        "thumbnail": info.get(
            "thumbnail"
        ),
    }


# ---------------------------------------------------------
# DIRECT MEDIA URL
# ---------------------------------------------------------

def get_direct_url_for_quality(
    url: str,
    quality: str
):

    info = _extract_info(url)

    formats = info.get(
        "formats",
        []
    )

    # -----------------------------------------
    # AUDIO
    # -----------------------------------------

    if quality == "audio":

        candidates = [
            f for f in formats
            if f.get("url")
            and f.get("acodec")
            not in (None, "none")
            and f.get("vcodec")
            in (None, "none")
        ]

        if not candidates:
            return None

        candidates.sort(
            key=lambda x: (
                x.get("abr") or 0,
                x.get("tbr") or 0
            ),
            reverse=True
        )

        return candidates[0].get("url")

    # -----------------------------------------
    # HEIGHT
    # -----------------------------------------

    try:
        target_height = int(
            quality.rstrip("p")
        )
    except Exception:
        return None

    # -----------------------------------------
    # EXACT COMBINED FORMAT
    # -----------------------------------------

    candidates = [
        f for f in formats
        if f.get("url")
        and f.get("height") == target_height
        and f.get("vcodec")
        not in (None, "none")
        and f.get("acodec")
        not in (None, "none")
    ]

    if candidates:

        candidates.sort(
            key=lambda x: (
                x.get("tbr") or 0,
                x.get("filesize") or 0
            ),
            reverse=True
        )

        return candidates[0].get("url")

    # -----------------------------------------
    # NEAREST LOWER COMBINED FORMAT
    # -----------------------------------------

    candidates = [
        f for f in formats
        if f.get("url")
        and f.get("height")
        and f.get("height") <= target_height
        and f.get("vcodec")
        not in (None, "none")
        and f.get("acodec")
        not in (None, "none")
    ]

    if candidates:

        candidates.sort(
            key=lambda x: (
                x.get("height") or 0,
                x.get("tbr") or 0
            ),
            reverse=True
        )

        return candidates[0].get("url")

    return None


# ---------------------------------------------------------
# SUBSCRIPTION
# ---------------------------------------------------------

async def is_subscribed(
    bot,
    user_id: int
) -> bool:

    if not config.FORCE_SUB_ENABLED:
        return True

    try:

        member = await bot.get_chat_member(
            f"@{config.CHANNEL_USERNAME}",
            user_id
        )

        return member.status in (
            "member",
            "administrator",
            "creator"
        )

    except Exception as e:

        logger.error(
            "Subscription check failed: %s",
            e
        )

        return True
