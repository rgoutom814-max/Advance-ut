import os
import re
import threading
import tempfile
import shutil
import urllib.parse

import requests
import yt_dlp
from flask import Flask
from pyrogram import Client, filters


# ============================================================
# ENVIRONMENT
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID_TEXT = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

# Optional: needed only for Terabox links. Get this from your own browser's
# cookies after logging into terabox.com (the "ndus" cookie value).
TERABOX_NDUS = os.getenv("TERABOX_NDUS")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")
if not API_ID_TEXT:
    raise RuntimeError("API_ID environment variable is missing")
if not API_HASH:
    raise RuntimeError("API_HASH environment variable is missing")

try:
    API_ID = int(API_ID_TEXT)
except ValueError:
    raise RuntimeError("API_ID must contain only numbers")

# Telegram bot API upload limit (bytes) - 2GB for premium/local bot API, 50MB default for normal bots
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "2000")) * 1024 * 1024

TERABOX_DOMAINS = (
    "terabox.com", "1024tera.com", "terasharelink.com", "nephobox.com",
    "1024terabox.com", "4funbox.com", "mirrobox.com", "momerybox.com",
    "teraboxapp.com", "teraboxlink.com", "freeterabox.com",
)


# ============================================================
# FLASK SERVER (for Render/Railway health checks)
# ============================================================

web = Flask(__name__)


@web.get("/")
def home():
    return "Telegram Downloader Bot is running."


@web.get("/health")
def health():
    return "OK"


def run_web_server():
    port = int(os.getenv("PORT", "8080"))
    web.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# ============================================================
# TELEGRAM CLIENT
# ============================================================

app = Client(
    "downloader_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)


# ============================================================
# START
# ============================================================

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    await message.reply_text(
        "👋 হ্যালো!\n\n"
        "YouTube, Instagram, Facebook, Twitter/X, TikTok ইত্যাদি থেকে "
        "একটি public video link পাঠান, আমি ডাউনলোড করে পাঠিয়ে দেব।"
    )


# ============================================================
# HELPERS
# ============================================================

def safe_filename(name):
    name = str(name or "video.mp4")
    name = re.sub(r"[^\w.\-]+", "_", name)
    return name[:150] or "video.mp4"


def download_with_ytdlp(url, tmp_dir):
    """
    Downloads the video/audio using yt-dlp.
    Returns the local file path on success, or None on failure.
    """
    outtmpl = os.path.join(tmp_dir, "%(title).150s.%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "format": "bv*[height<=720]+ba/b[height<=720]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "max_filesize": MAX_FILE_SIZE,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                return None
            file_path = ydl.prepare_filename(info)

            if not os.path.exists(file_path):
                base, _ = os.path.splitext(file_path)
                candidate = base + ".mp4"
                if os.path.exists(candidate):
                    file_path = candidate

            return file_path if os.path.exists(file_path) else None

    except yt_dlp.utils.DownloadError as e:
        print("yt-dlp DownloadError:", repr(e))
        return None
    except Exception as e:
        print("yt-dlp unexpected error:", repr(e))
        return None


def cleanup_temp(tmp_dir):
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass


def is_terabox_url(url):
    host = urllib.parse.urlparse(url).netloc.lower()
    return any(domain in host for domain in TERABOX_DOMAINS)


def download_terabox(url, tmp_dir):
    """
    Resolves a Terabox share link to a direct download link and downloads it.
    Requires TERABOX_NDUS (the 'ndus' cookie from a logged-in browser session)
    to be set, since Terabox's share API requires an authenticated session.

    NOTE: Terabox does not publish or support this API for third-party use.
    They change their internal endpoints often, so this can break at any time
    and may violate Terabox's Terms of Service - use at your own risk.
    """
    if not TERABOX_NDUS:
        print("Terabox download skipped: TERABOX_NDUS is not set")
        return None

    session = requests.Session()
    session.cookies.set("ndus", TERABOX_NDUS, domain=".terabox.com")
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    })

    try:
        resp = session.get(url, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        final_url = resp.url

        parsed = urllib.parse.urlparse(final_url)
        query = urllib.parse.parse_qs(parsed.query)
        surl = query.get("surl", [None])[0]

        if not surl:
            match = re.search(r"surl=([^&]+)", resp.text)
            if match:
                surl = match.group(1)

        if not surl:
            print("Terabox: could not extract surl")
            return None

        token_match = re.search(r"fn%28%22(.*?)%22%29", resp.text)
        js_token = token_match.group(1) if token_match else None

        if not js_token:
            print("Terabox: could not extract jsToken")
            return None

        list_url = "https://www.terabox.com/share/list"
        params = {
            "app_id": "250528",
            "web": "1",
            "channel": "dubox",
            "clienttype": "0",
            "jsToken": js_token,
            "shorturl": surl,
            "root": "1",
        }

        list_resp = session.get(list_url, params=params, timeout=30)
        data = list_resp.json()

        file_list = data.get("list", [])
        if not file_list:
            print("Terabox: empty file list", data)
            return None

        file_info = file_list[0]
        dlink = file_info.get("dlink")
        filename = safe_filename(file_info.get("server_filename", "terabox_file"))

        if not dlink:
            print("Terabox: no dlink in response")
            return None

        file_path = os.path.join(tmp_dir, filename)
        with session.get(dlink, stream=True, timeout=120) as dl:
            dl.raise_for_status()
            with open(file_path, "wb") as f:
                for chunk in dl.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)

        return file_path if os.path.exists(file_path) else None

    except Exception as e:
        print("Terabox download error:", repr(e))
        return None


# ============================================================
# MAIN DOWNLOAD HANDLER
# ============================================================

@app.on_message(filters.text & filters.private & ~filters.bot)
async def download_handler(client, message):
    url = message.text.strip()

    if not (url.startswith("http://") or url.startswith("https://")):
        return

    status_message = await message.reply_text("🔎 লিংকটি প্রসেস করা হচ্ছে...")

    tmp_dir = tempfile.mkdtemp(prefix="dl_")

    try:
        await status_message.edit_text("⬇️ ভিডিও ডাউনলোড হচ্ছে...")

        if is_terabox_url(url):
            file_path = download_terabox(url, tmp_dir)
        else:
            file_path = download_with_ytdlp(url, tmp_dir)

        if not file_path:
            await status_message.edit_text(
                "❌ ভিডিওটি ডাউনলোড করা যায়নি।\n"
                "লিংকটি public কিনা এবং সঠিক কিনা যাচাই করুন।"
            )
            return

        file_size = os.path.getsize(file_path)
        if file_size > MAX_FILE_SIZE:
            await status_message.edit_text(
                "❌ ফাইলটি খুব বড় (Telegram limit-এর বাইরে)।"
            )
            return

        await status_message.edit_text("📤 Telegram-এ আপলোড হচ্ছে...")

        filename = safe_filename(os.path.basename(file_path))

        try:
            await message.reply_video(
                video=file_path,
                caption=filename,
                supports_streaming=True,
            )
        except Exception as e:
            print("Video send failed, trying as document:", repr(e))
            await message.reply_document(document=file_path, caption=filename)

        try:
            await status_message.delete()
        except Exception:
            pass

    except Exception as e:
        print("Handler error:", repr(e))
        try:
            await status_message.edit_text(
                "❌ একটি সমস্যা হয়েছে।\nকিছুক্ষণ পরে আবার চেষ্টা করুন।"
            )
        except Exception:
            pass

    finally:
        cleanup_temp(tmp_dir)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    print("Starting Telegram bot...")
    app.run()
