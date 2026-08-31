#!/usr/bin/env python3
# pylint: disable=no-member,method-hidden

import os
import sys
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from aiohttp import web
from aiohttp.web import GracefulExit
from aiohttp.log import access_logger
import ssl
import socket
import socketio
import logging
import json
import pathlib
import re
import time
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from watchfiles import DefaultFilter, Change, awatch

import bg_tasks
from ytdl import DownloadQueueNotifier, DownloadQueue, Download
from subscriptions import SubscriptionManager, SubscriptionNotifier, SubscriptionInfo, coerce_optional_bool
from yt_dlp.version import __version__ as yt_dlp_version

log = logging.getLogger('main')

_NIGHTLY_TIME_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')
_RESTART_FOR_UPDATE = False

def _request_graceful_exit() -> None:
    raise GracefulExit()


def seconds_until_next_daily_time(time_hhmm: str, now: datetime | None = None) -> float:
    """Seconds until the next occurrence of HH:MM in local time."""
    now = now or datetime.now()
    hour, minute = map(int, time_hhmm.split(':'))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()

def parseLogLevel(logLevel):
    if not isinstance(logLevel, str):
        return None
    return getattr(logging, logLevel.upper(), None)

# Configure logging before Config() uses it so early messages are not dropped.
# Only configure if no handlers are set (avoid clobbering hosting app settings).
if not logging.getLogger().hasHandlers():
    logging.basicConfig(level=parseLogLevel(os.environ.get('LOGLEVEL', 'INFO')) or logging.INFO)

class Config:
    _DEFAULTS = {
        'DOWNLOAD_DIR': '.',
        'AUDIO_DOWNLOAD_DIR': '%%DOWNLOAD_DIR',
        'TEMP_DIR': '%%DOWNLOAD_DIR',
        'DOWNLOAD_DIRS_INDEXABLE': 'false',
        'CUSTOM_DIRS': 'true',
        'CREATE_CUSTOM_DIRS': 'true',
        'CUSTOM_DIRS_EXCLUDE_REGEX': r'(^|/)[.@].*$',
        'DEFAULT_FOLDER': '',
        'DELETE_FILE_ON_TRASHCAN': 'false',
        'STATE_DIR': '.',
        'URL_PREFIX': '',
        'PUBLIC_HOST_URL': 'download/',
        'PUBLIC_HOST_AUDIO_URL': 'audio_download/',
        'OUTPUT_TEMPLATE': '%(title)s.%(ext)s',
        'OUTPUT_TEMPLATE_CHAPTER': '%(title)s - %(section_number)02d - %(section_title)s.%(ext)s',
        'OUTPUT_TEMPLATE_PLAYLIST': '%(playlist_title)s/%(title)s.%(ext)s',
        'OUTPUT_TEMPLATE_CHANNEL': '%(channel)s/%(title)s.%(ext)s',
        'DEFAULT_OPTION_PLAYLIST_ITEM_LIMIT' : '0',
        'SUBSCRIPTION_DEFAULT_CHECK_INTERVAL': '60',
        'SUBSCRIPTION_SCAN_PLAYLIST_END': '50',
        'SUBSCRIPTION_MAX_SEEN_IDS': '50000',
        'CLEAR_COMPLETED_AFTER': '0',
        'YTDL_OPTIONS': '{}',
        'YTDL_OPTIONS_FILE': '',
        'YTDL_OPTIONS_PRESETS': '{}',
        'YTDL_OPTIONS_PRESETS_FILE': '',
        'ALLOW_YTDL_OPTIONS_OVERRIDES': 'false',
        'ALLOW_PRIVATE_ADDRESSES': 'false',
        'CORS_ALLOWED_ORIGINS': '',
        'ROBOTS_TXT': '',
        'HOST': '0.0.0.0',
        'PORT': '8081',
        'HTTPS': 'false',
        'CERTFILE': '',
        'KEYFILE': '',
        'BASE_DIR': '',
        'DEFAULT_THEME': 'auto',
        'MAX_CONCURRENT_DOWNLOADS': '3',
        'LOGLEVEL': 'INFO',
        'ENABLE_ACCESSLOG': 'false',
        'YTDL_NIGHTLY_UPDATE_TIME': '',
    }

    _BOOLEAN = ('DOWNLOAD_DIRS_INDEXABLE', 'CUSTOM_DIRS', 'CREATE_CUSTOM_DIRS', 'DELETE_FILE_ON_TRASHCAN', 'HTTPS', 'ENABLE_ACCESSLOG', 'ALLOW_YTDL_OPTIONS_OVERRIDES', 'ALLOW_PRIVATE_ADDRESSES')

    def __init__(self):
        for k, v in self._DEFAULTS.items():
            setattr(self, k, os.environ.get(k, v))

        for k, v in self.__dict__.items():
            if isinstance(v, str) and v.startswith('%%'):
                setattr(self, k, getattr(self, v[2:]))
            if k in self._BOOLEAN:
                if v not in ('true', 'false', 'True', 'False', 'on', 'off', '1', '0'):
                    log.error(f'Environment variable "{k}" is set to a non-boolean value "{v}"')
                    sys.exit(1)
                setattr(self, k, v in ('true', 'True', 'on', '1'))

        # aiohttp hands HOST straight to getaddrinfo, which has no notion of a
        # '*' wildcard: the lookup fails and takes the server down at startup
        # with an opaque DNS error. '*' is nevertheless what people reach for
        # when they want to serve both IP stacks, while the value that actually
        # does it -- an empty string, which asyncio expands to one listening
        # socket per address family -- is undiscoverable. Accept '*' as the
        # spelling for "every interface, both stacks". Note that '::' on its own
        # is IPv6-only regardless of the host's bindv6only setting, because
        # asyncio always sets IPV6_V6ONLY on the sockets it binds.
        if self.HOST.strip() == '*':
            self.HOST = ''

        if not self.URL_PREFIX.endswith('/'):
            self.URL_PREFIX += '/'

        # Strip trailing slashes from the download directories. get_custom_dirs()
        # builds the folder dropdown by removing the base path as a prefix from
        # each subdirectory, and the base directory's own path does not carry the
        # trailing slash — so 'DOWNLOAD_DIR=/downloads/' failed to match itself
        # and leaked 'downloads' into the dropdown as a bogus folder option.
        # Runs after the '%%' indirection above so AUDIO_DOWNLOAD_DIR is resolved.
        for attr in ('DOWNLOAD_DIR', 'AUDIO_DOWNLOAD_DIR', 'TEMP_DIR', 'STATE_DIR'):
            val = getattr(self, attr)
            if isinstance(val, str) and len(val) > 1 and val.endswith('/'):
                setattr(self, attr, val.rstrip('/') or '/')

        # A blank PUBLIC_HOST_AUDIO_URL (e.g. set empty in a compose file) bypasses the
        # default via os.environ.get, which would leave audio links root-relative and 404.
        # Fall back to the 'audio_download/' route that serves AUDIO_DOWNLOAD_DIR. When
        # PUBLIC_HOST_URL is also blank we leave it blank to preserve serving from web root.
        if not self.PUBLIC_HOST_AUDIO_URL and self.PUBLIC_HOST_URL:
            self.PUBLIC_HOST_AUDIO_URL = self._DEFAULTS['PUBLIC_HOST_AUDIO_URL']

        for attr in ('PUBLIC_HOST_URL', 'PUBLIC_HOST_AUDIO_URL'):
            val = getattr(self, attr)
            if val and not val.endswith('/'):
                setattr(self, attr, val + '/')

        # DEFAULT_FOLDER only pre-fills the form's folder field, which the UI
        # does not even show without CUSTOM_DIRS. Sending one anyway would fail
        # every download on the server's own folder check, so drop it and say so
        # rather than leaving the user with a form that cannot submit.
        self.DEFAULT_FOLDER = self.DEFAULT_FOLDER.strip().strip('/')
        if self.DEFAULT_FOLDER and not self.CUSTOM_DIRS:
            log.warning(
                'Ignoring DEFAULT_FOLDER "%s" because CUSTOM_DIRS is not enabled',
                self.DEFAULT_FOLDER,
            )
            self.DEFAULT_FOLDER = ''

        # Convert relative addresses to absolute addresses to prevent the failure of file address comparison
        if self.YTDL_OPTIONS_FILE and self.YTDL_OPTIONS_FILE.startswith('.'):
            self.YTDL_OPTIONS_FILE = str(Path(self.YTDL_OPTIONS_FILE).resolve())
        if self.YTDL_OPTIONS_PRESETS_FILE and self.YTDL_OPTIONS_PRESETS_FILE.startswith('.'):
            self.YTDL_OPTIONS_PRESETS_FILE = str(Path(self.YTDL_OPTIONS_PRESETS_FILE).resolve())

        if self.YTDL_NIGHTLY_UPDATE_TIME and not _NIGHTLY_TIME_RE.match(self.YTDL_NIGHTLY_UPDATE_TIME):
            log.error(
                'Environment variable "YTDL_NIGHTLY_UPDATE_TIME" must be HH:MM (24-hour), got "%s"',
                self.YTDL_NIGHTLY_UPDATE_TIME,
            )
            sys.exit(1)

        self._validate_int('MAX_CONCURRENT_DOWNLOADS', minimum=1)
        self._validate_int('PORT', minimum=1, maximum=65535)
        self._validate_int('CLEAR_COMPLETED_AFTER', minimum=0)
        self._validate_int('DEFAULT_OPTION_PLAYLIST_ITEM_LIMIT', minimum=0)
        self._validate_int('SUBSCRIPTION_DEFAULT_CHECK_INTERVAL', minimum=1)
        self._validate_int('SUBSCRIPTION_SCAN_PLAYLIST_END', minimum=1)
        self._validate_int('SUBSCRIPTION_MAX_SEEN_IDS', minimum=1)

        self._runtime_overrides = {}

        success,_ = self.load_ytdl_options()
        if not success:
            sys.exit(1)
        success,_ = self.load_ytdl_option_presets()
        if not success:
            sys.exit(1)

    def _validate_int(self, key, *, minimum=None, maximum=None):
        raw = getattr(self, key)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            log.error('Environment variable "%s" must be an integer, got "%s"', key, raw)
            sys.exit(1)
        if minimum is not None and value < minimum:
            log.error('Environment variable "%s" must be >= %d, got "%s"', key, minimum, raw)
            sys.exit(1)
        if maximum is not None and value > maximum:
            log.error('Environment variable "%s" must be <= %d, got "%s"', key, maximum, raw)
            sys.exit(1)

    def set_runtime_override(self, key, value):
        self._runtime_overrides[key] = value
        self.YTDL_OPTIONS[key] = value

    def remove_runtime_override(self, key):
        self._runtime_overrides.pop(key, None)
        self.YTDL_OPTIONS.pop(key, None)

    def _apply_runtime_overrides(self):
        self.YTDL_OPTIONS.update(self._runtime_overrides)

    # Keys sent to the browser. Sensitive or server-only keys (YTDL_OPTIONS,
    # paths, TLS config, etc.) are intentionally excluded.
    _FRONTEND_KEYS = (
        'CUSTOM_DIRS',
        'CREATE_CUSTOM_DIRS',
        'DEFAULT_FOLDER',
        'OUTPUT_TEMPLATE_CHAPTER',
        'PUBLIC_HOST_URL',
        'PUBLIC_HOST_AUDIO_URL',
        'DEFAULT_OPTION_PLAYLIST_ITEM_LIMIT',
        'SUBSCRIPTION_DEFAULT_CHECK_INTERVAL',
        'ALLOW_YTDL_OPTIONS_OVERRIDES',
    )

    def frontend_safe(self) -> dict:
        """Return only the config keys that are safe to expose to browser clients.

        Sensitive or server-only keys (YTDL_OPTIONS, file-system paths, TLS
        settings, etc.) are intentionally excluded.
        """
        return {k: getattr(self, k) for k in self._FRONTEND_KEYS}

    def load_ytdl_options(self) -> tuple[bool, str]:
        try:
            self.YTDL_OPTIONS = json.loads(os.environ.get('YTDL_OPTIONS', '{}'))
            assert isinstance(self.YTDL_OPTIONS, dict)
        except (json.decoder.JSONDecodeError, AssertionError):
            msg = 'Environment variable YTDL_OPTIONS is invalid'
            log.error(msg)
            return (False, msg)

        if not self.YTDL_OPTIONS_FILE:
            self._apply_runtime_overrides()
            return (True, '')

        log.info(f'Loading yt-dlp custom options from "{self.YTDL_OPTIONS_FILE}"')
        if not os.path.exists(self.YTDL_OPTIONS_FILE):
            msg = f'File "{self.YTDL_OPTIONS_FILE}" not found'
            log.error(msg)
            return (False, msg)
        try:
            with open(self.YTDL_OPTIONS_FILE) as json_data:
                opts = json.load(json_data)
            assert isinstance(opts, dict)
        except (json.decoder.JSONDecodeError, AssertionError):
            msg = 'YTDL_OPTIONS_FILE contents is invalid'
            log.error(msg)
            return (False, msg)

        self.YTDL_OPTIONS.update(opts)
        self._apply_runtime_overrides()
        return (True, '')

    def load_ytdl_option_presets(self) -> tuple[bool, str]:
        try:
            self.YTDL_OPTIONS_PRESETS = json.loads(os.environ.get('YTDL_OPTIONS_PRESETS', '{}'))
            assert isinstance(self.YTDL_OPTIONS_PRESETS, dict)
            assert all(isinstance(name, str) and isinstance(options, dict) for name, options in self.YTDL_OPTIONS_PRESETS.items())
        except (json.decoder.JSONDecodeError, AssertionError):
            msg = 'Environment variable YTDL_OPTIONS_PRESETS is invalid'
            log.error(msg)
            return (False, msg)

        if not self.YTDL_OPTIONS_PRESETS_FILE:
            return (True, '')

        log.info(f'Loading yt-dlp option presets from "{self.YTDL_OPTIONS_PRESETS_FILE}"')
        if not os.path.exists(self.YTDL_OPTIONS_PRESETS_FILE):
            msg = f'File "{self.YTDL_OPTIONS_PRESETS_FILE}" not found'
            log.error(msg)
            return (False, msg)
        try:
            with open(self.YTDL_OPTIONS_PRESETS_FILE) as json_data:
                opts = json.load(json_data)
            assert isinstance(opts, dict)
            assert all(isinstance(name, str) and isinstance(options, dict) for name, options in opts.items())
        except (json.decoder.JSONDecodeError, AssertionError):
            msg = 'YTDL_OPTIONS_PRESETS_FILE contents is invalid'
            log.error(msg)
            return (False, msg)

        self.YTDL_OPTIONS_PRESETS.update(opts)
        return (True, '')

config = Config()
# Align root logger level with Config (keeps a single source of truth).
# This re-applies the log level after Config loads, in case LOGLEVEL was
# overridden by config file settings or differs from the environment variable.
logging.getLogger().setLevel(parseLogLevel(str(config.LOGLEVEL)) or logging.INFO)

class ObjectSerializer(json.JSONEncoder):
    def default(self, obj):
        # Prefer an explicit client-facing view when the object provides one
        # (e.g. DownloadInfo / SubscriptionInfo) so server-only or bulky fields
        # are never broadcast to browser clients.
        to_public = getattr(obj, 'to_public_dict', None)
        if callable(to_public):
            return to_public()
        # Fall back to __dict__ for other custom objects
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        # Convert iterables (generators, dict_items, etc.) to lists
        # Exclude strings and bytes which are also iterable
        elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
            try:
                return list(obj)
            except Exception:
                pass
        # Fall back to default behavior
        return json.JSONEncoder.default(self, obj)

serializer = ObjectSerializer()

_STATE_DIR_REAL = os.path.realpath(config.STATE_DIR)


def _is_within_state_dir(real_target: str) -> bool:
    return real_target == _STATE_DIR_REAL or real_target.startswith(_STATE_DIR_REAL + os.sep)


@web.middleware
async def state_dir_guard(request, handler):
    for prefix, base in (
        (config.URL_PREFIX + 'download/', config.DOWNLOAD_DIR),
        (config.URL_PREFIX + 'audio_download/', config.AUDIO_DOWNLOAD_DIR),
    ):
        if request.path.startswith(prefix):
            # request.path is already percent-decoded by aiohttp; decoding it
            # again would mangle a download whose filename contains a literal
            # '%' (e.g. "%" turning into a truncated escape) into a false 404.
            rel = request.path[len(prefix):]
            target = os.path.realpath(os.path.join(base, rel))
            if _is_within_state_dir(target):
                raise web.HTTPNotFound()
            break
    return await handler(request)


app = web.Application(middlewares=[state_dir_guard])
_cors_origins = [o.strip() for o in config.CORS_ALLOWED_ORIGINS.split(',') if o.strip()] if config.CORS_ALLOWED_ORIGINS else []
if '*' in _cors_origins and len(_cors_origins) > 1:
    log.warning(
        "CORS_ALLOWED_ORIGINS mixes '*' with named origins %s. '*' wins, and credentialed "
        "cross-origin requests stay disabled for every origin in the list. Remove '*' if you "
        "need a bookmarklet to reach an authenticated instance.",
        [o for o in _cors_origins if o != '*'])
sio = socketio.AsyncServer(cors_allowed_origins=_cors_origins if _cors_origins else [])
sio.attach(app, socketio_path=config.URL_PREFIX + 'socket.io')
routes = web.RouteTableDef()
VALID_SUBTITLE_FORMATS = {'srt', 'txt', 'vtt', 'ttml', 'sbv', 'scc', 'dfxp'}
VALID_SUBTITLE_MODES = {'auto_only', 'manual_only', 'prefer_manual', 'prefer_auto'}
SUBTITLE_LANGUAGE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9-]{0,34}$')
VALID_DOWNLOAD_TYPES = {'video', 'audio', 'captions', 'thumbnail'}
VALID_VIDEO_CODECS = {'auto', 'h264', 'h265', 'av1', 'vp9'}
VALID_VIDEO_FORMATS = {'any', 'mp4', 'ios'}
VALID_AUDIO_FORMATS = {'m4a', 'mp3', 'opus', 'wav', 'flac'}
VALID_THUMBNAIL_FORMATS = {'jpg'}
def _parse_ytdl_options_overrides(value, *, enabled: bool) -> dict:
    if value is None or value == '':
        return {}

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise web.HTTPBadRequest(reason='ytdl_options_overrides must be valid JSON') from exc

    if not isinstance(value, dict):
        raise web.HTTPBadRequest(reason='ytdl_options_overrides must be a JSON object')

    if value and not enabled:
        raise web.HTTPBadRequest(reason='ytdl_options_overrides are disabled')

    return value


_YOUTUBE_T_COMPACT_RE = re.compile(
    r'^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)(?:s)?)?$',
    re.IGNORECASE,
)


def _parse_youtube_t_compact(value: str) -> float | None:
    """Parse YouTube-style ``t`` values: ``885``, ``885s``, ``14m45s``, ``1h2m3s``."""
    v = value.strip()
    if not v:
        return None
    if re.fullmatch(r'-?\d+(\.\d+)?', v):
        sec = float(v)
        return sec if sec >= 0 else None
    m = _YOUTUBE_T_COMPACT_RE.match(v)
    if m and any(m.groups()):
        hours = int(m.group(1) or 0)
        minutes = int(m.group(2) or 0)
        seconds = int(m.group(3) or 0)
        total = hours * 3600 + minutes * 60 + seconds
        return float(total) if total >= 0 else None
    return None


def _parse_clock_timestamp(s: str) -> float:
    """Parse ``MM:SS``, ``H:MM:SS``, or single segment as seconds (with optional decimals)."""
    part = s.strip()
    if not part:
        raise ValueError('empty timestamp')
    segments = part.split(':')
    if len(segments) > 3:
        raise ValueError('too many segments')
    try:
        nums = [float(x) for x in segments]
    except ValueError as exc:
        raise ValueError('invalid number') from exc
    if any(x < 0 for x in nums):
        raise ValueError('negative segment')
    if len(segments) == 1:
        return nums[0]
    if len(segments) == 2:
        return nums[0] * 60 + nums[1]
    return nums[0] * 3600 + nums[1] * 60 + nums[2]


def _parse_clip_timestamp_value(value) -> float:
    """Coerce a clip boundary from JSON to seconds (non-negative)."""
    if isinstance(value, bool):
        raise web.HTTPBadRequest(reason='clip timestamp must be a number or string')
    if isinstance(value, (int, float)):
        if value < 0:
            raise web.HTTPBadRequest(reason='clip timestamp must be non-negative')
        return float(value)
    s = str(value).strip()
    if not s:
        raise web.HTTPBadRequest(reason='clip timestamp cannot be empty')
    if ':' in s:
        try:
            return _parse_clock_timestamp(s)
        except ValueError as exc:
            raise web.HTTPBadRequest(reason='invalid clip timestamp format') from exc
    compact = _parse_youtube_t_compact(s)
    if compact is not None:
        return compact
    raise web.HTTPBadRequest(reason='invalid clip timestamp format')


def _optional_clip_field(raw) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    return _parse_clip_timestamp_value(raw)


def _clip_field_provided_in_post(raw) -> bool:
    if raw is None:
        return False
    if isinstance(raw, str) and not raw.strip():
        return False
    return True


def _extract_t_query_from_url(url: str) -> tuple[str, float | None]:
    """If ``t=`` i
