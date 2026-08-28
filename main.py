import os
import re
import asyncio
import threading
import tempfile

import aiohttp
from flask import Flask
from pyrogram import Client, filters


# ============================================================
# ENVIRONMENT
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID_TEXT = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

COBALT_API = os.getenv(
    "COBALT_API",
    "https://api.cobalt.tools"
).rstrip("/")

COBALT_API_KEY = os.getenv("COBALT_API_KEY")


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


# ============================================================
# FLASK SERVER FOR RENDER
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
    web.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )


# ============================================================
# TELEGRAM CLIENT
# ============================================================

app = Client(
    "downloader_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# ============================================================
# START
# ============================================================

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    await message.reply_text(
        "👋 হ্যালো!\n\n"
        "একটি public video/media link পাঠান।\n"
        "আমি সেটি প্রসেস করার চেষ্টা করব।"
    )


# ============================================================
# COBALT ERROR
# ============================================================

def format_api_error(data):
    error = data.get("error", {})

    if not isinstance(error, dict):
        return "❌ ভিডিওটি প্রসেস করা যায়নি।"

    code = error.get("code", "unknown_error")
    context = error.get("context", {})

    if not isinstance(context, dict):
        context = {}

    service = context.get("service")
    limit = context.get("limit")

    if code == "error.api.rate_exceeded":
        return "⏳ এখন অনেক বেশি request হয়েছে।\nকিছুক্ষণ পরে আবার চেষ্টা করুন।"

    if code == "error.api.capacity":
        return "⏳ Downloader server এখন ব্যস্ত।\nকিছুক্ষণ পরে আবার চেষ্টা করুন।"

    if code == "error.api.service.unsupported":
        return "❌ এই service বর্তমানে supported নয়।"

    if code == "error.api.platform.unsupported":
        return "❌ এই platform বর্তমানে supported নয়।"

    if code.startswith("error.api.auth"):
        return "❌ Cobalt API authentication সমস্যা হয়েছে।"

    if limit:
        return f"❌ ফাইলটি server-এর limit-এর বাইরে।\nLimit: {limit}"

    if service:
        return f"❌ ভিডিওটি প্রসেস করা যায়নি।\nService: {service}\nError: {code}"

    return f"❌ ভিডিওটি প্রসেস করা যায়নি।\nError: {code}"


# ============================================================
# COBALT REQUEST
# ============================================================

async def process_with_cobalt(url):
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Telegram-Downloader-Bot"
    }

    if COBALT_API_KEY:
        headers["Authorization"] = f"Api-Key {COBALT_API_KEY}"

    payload = {
        "url": url,
        "videoQuality": "720",
        "audioFormat": "best",
        "downloadMode": "auto",
        "youtubeVideoCodec": "h264",
        "youtubeVideoContainer": "mp4",
        "disableMetadata": False,
        "alwaysProxy": True,
        "filenameStyle": "pretty"
    }

    timeout = aiohttp.ClientTimeout(
        total=120, connect=20, sock_connect=20, sock_read=120
    )

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{COBALT_API}/", json=payload, headers=headers
            ) as response:
                text = await response.text()
                print("Cobalt HTTP:", response.status)
                print("Cobalt response:", text[:2000])

                if response.status != 200:
                    return {"status": "error", "error": {"code": f"http_{response.status}"}}

                try:
                    return await response.json(content_type=None)
                except Exception:
                    return {"status": "error", "error": {"code": "invalid_json_response"}}

    except asyncio.TimeoutError:
        return {"status": "error", "error": {"code": "request_timeout"}}

    except aiohttp.ClientError as e:
        print("Cobalt connection error:", repr(e))
        return {"status": "error", "error": {"code": "connection_error"}}

    except Exception as e:
        print("Cobalt unexpected error:", repr(e))
        return {"status": "error", "error": {"code": "unexpected_error"}}


# ============================================================
# PICK VIDEO
# ============================================================

def choose_media(picker):
    if not isinstance(picker, list):
        return None

    for item in picker:
        if isinstance(item, dict) and item.get("type") == "video" and item.get("url"):
            return item

    for item in picker:
        if isinstance(item, dict) and item.get("type") == "gif" and item.get("url"):
            return item

    return None


# ============================================================
# DOWNLOAD FILE LOCALLY (fixes unreliable remote-URL upload)
# ============================================================

def safe_filename(name):
    name = str(name or "video.mp4")
    name = re.sub(r"[^\w.\-]+", "_", name)
    return name[:150] or "video.mp4"


async def download_to_temp(media_url, filename):
    filename = safe_filename(filename)
    tmp_dir = tempfile.mkdtemp(prefix="dl_")
    file_path = os.path.join(tmp_dir, filename)

    timeout = aiohttp.ClientTimeout(total=600, sock_read=120)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(media_url) as resp:
                if resp.status != 200:
                    print("Download failed, HTTP:", resp.status)
                    return None

                with open(file_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(1024 * 256):
                        f.write(chunk)

        return file_path

    except Exception as e:
        print("download_to_temp error:", repr(e))
        return None


def cleanup_temp(file_path):
    if not file_path:
        return
    try:
        os.remove(file_path)
        os.rmdir(os.path.dirname(file_path))
    except Exception:
        pass


# ============================================================
# SEND MEDIA
# ============================================================

async def send_media(message, media_url, filename):
    filename = safe_filename(filename)

    local_path = await download_to_temp(media_url, filename)

    if not local_path:
        return False

    try:
        try:
            await message.reply_video(
                video=local_path,
                caption=filename,
                supports_streaming=True
            )
            return True

        except Exception as e:
            print("Video send failed:", repr(e))

        try:
            await message.reply_document(
                document=local_path,
                caption=filename
            )
            return True

        except Exception as e:
            print("Document send failed:", repr(e))
            return False

    finally:
        cleanup_temp(local_path)


# ============================================================
# MAIN DOWNLOAD HANDLER
# ============================================================

@app.on_message(filters.text & filters.private & ~filters.bot)
async def download_handler(client, message):
    url = message.text.strip()

    if not (url.startswith("http://") or url.startswith("https://")):
        return

    status_message = await message.reply_text("🔎 লিংকটি পরীক্ষা করা হচ্ছে...")

    try:
        data = await process_with_cobalt(url)

        if not isinstance(data, dict):
            await status_message.edit_text("❌ Downloader থেকে সঠিক response পাওয়া যায়নি।")
            return

        status = data.get("status")
        print("Cobalt status:", status)

        # ERROR
        if status == "error":
            await status_message.edit_text(format_api_error(data))
            return

        # TUNNEL / REDIRECT
        if status in ("tunnel", "redirect"):
            media_url = data.get("url")
            filename = data.get("filename", "video.mp4")

            if not media_url:
                await status_message.edit_text("❌ Download URL পাওয়া যায়নি।")
                return

            await status_message.edit_text("⬇️ ভিডিও ডাউনলোড হচ্ছে...")
            success = await send_media(message, media_url, filename)

            if success:
                try:
                    await status_message.delete()
                except Exception:
                    pass
            else:
                await status_message.edit_text("❌ Telegram-এ ফাইল পাঠানো যায়নি।")
            return

        # PICKER
        if status == "picker":
            picker = data.get("picker", [])
            media = choose_media(picker)

            if not media:
                await status_message.edit_text("❌ কোনো ভিডিও পাওয়া যায়নি।")
                return

            media_url = media.get("url")

            if not media_url:
                await status_message.edit_text("❌ Media URL পাওয়া যায়নি।")
                return

            await status_message.edit_text("⬇️ ভিডিও ডাউনলোড হচ্ছে...")
            success = await send_media(message, media_url, "video.mp4")

            if success:
                try:
                    await status_message.delete()
                except Exception:
                    pass
            else:
                await status_message.edit_text("❌ Telegram-এ ফাইল পাঠানো যায়নি।")
            return

        # UNKNOWN
        await status_message.edit_text("❌ Downloader থেকে অজানা response এসেছে।")

    except Exception as e:
        print("Handler error:", repr(e))
        try:
            await status_message.edit_text(
                "❌ একটি সমস্যা হয়েছে।\nকিছুক্ষণ পরে আবার চেষ্টা করুন।"
            )
        except Exception:
            pass


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    print("Starting Telegram bot...")
    app.run()
