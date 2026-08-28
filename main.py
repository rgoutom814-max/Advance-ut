import os
import aiohttp

from pyrogram import Client, filters
from pyrogram.errors import RPCError


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID_TEXT = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

# নিজের Cobalt instance হলে Render Environment Variable-এ
# COBALT_API সেট করতে পারবে।
COBALT_API = os.getenv(
    "COBALT_API",
    "https://api.cobalt.tools"
).rstrip("/")


# ============================================================
# CHECK ENVIRONMENT VARIABLES
# ============================================================

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
# TELEGRAM CLIENT
# ============================================================

app = Client(
    "downloader_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# ============================================================
# /START
# ============================================================

@app.on_message(
    filters.command("start") &
    filters.private
)
async def start_command(client, message):

    text = (
        "👋 হ্যালো!\n\n"
        "একটি public video/media link পাঠান।\n"
        "আমি সেটি প্রসেস করার চেষ্টা করব।"
    )

    await message.reply_text(text)


# ============================================================
# ERROR MESSAGE
# ============================================================

def format_api_error(data):

    error = data.get("error", {})

    if not isinstance(error, dict):
        return "❌ ভিডিওটি প্রসেস করা যায়নি।"

    code = error.get(
        "code",
        "unknown_error"
    )

    context = error.get(
        "context",
        {}
    )

    if not isinstance(context, dict):
        context = {}

    service = context.get("service")
    limit = context.get("limit")

    if code == "error.api.rate_exceeded":
        return (
            "⏳ এখন অনেক বেশি request হয়েছে।\n"
            "কিছুক্ষণ পরে আবার চেষ্টা করুন।"
        )

    if code == "error.api.capacity":
        return (
            "⏳ Downloader server এখন ব্যস্ত।\n"
            "কিছুক্ষণ পরে আবার চেষ্টা করুন।"
        )

    if code == "error.api.service.unsupported":
        return (
            "❌ এই service বর্তমানে supported নয়।"
        )

    if code == "error.api.platform.unsupported":
        return (
            "❌ এই platform বর্তমানে supported নয়।"
        )

    if code == "error.api.auth.key.invalid":
        return (
            "❌ Downloader API authentication সমস্যা হয়েছে।"
        )

    if limit:
        return (
            "❌ এই ভিডিওটি server-এর limit-এর বাইরে।\n"
            f"Limit: {limit}"
        )

    if service:
        return (
            "❌ এই ভিডিওটি প্রসেস করা যায়নি।\n"
            f"Service: {service}\n"
            f"Error: {code}"
        )

    return (
        "❌ ভিডিওটি প্রসেস করা যায়নি।\n"
        f"Error: {code}"
    )


# ============================================================
# COBALT REQUEST
# ============================================================

async def process_with_cobalt(url):

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Telegram-Downloader-Bot"
    }

    payload = {
        "url": url,

        # ফোনের জন্য ভালো compatibility
        "videoQuality": "1080",

        # সাধারণ video + audio
        "downloadMode": "auto",

        # YouTube-এর জন্য ফোন-compatible codec
        "youtubeVideoCodec": "h264",

        # MP4 prefer
        "youtubeVideoContainer": "mp4",

        # metadata রাখবে
        "disableMetadata": False,

        # প্রয়োজন হলে Cobalt tunnel ব্যবহার করবে
        "alwaysProxy": True
    }

    timeout = aiohttp.ClientTimeout(
        total=120,
        connect=20,
        sock_connect=20,
        sock_read=120
    )

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:

        async with session.post(
            f"{COBALT_API}/",
            json=payload,
            headers=headers
        ) as response:

            response_text = await response.text()

            print(
                "Cobalt HTTP status:",
                response.status
            )

            print(
                "Cobalt response:",
                response_text[:3000]
            )

            if response.status != 200:
                return {
                    "status": "error",
                    "error": {
                        "code": f"http_{response.status}"
                    }
                }

            try:
                data = await response.json(
                    content_type=None
                )

            except Exception:
                return {
                    "status": "error",
                    "error": {
                        "code": "invalid_json_response"
                    }
                }

            return data


# ============================================================
# SEND MEDIA TO TELEGRAM
# ============================================================

async def send_to_telegram(
    message,
    media_url,
    filename
):

    # প্রথমে video হিসেবে পাঠানোর চেষ্টা
    try:

        await message.reply_video(
            video=media_url,
            caption=filename[:1024],
            supports_streaming=True
        )

        return True

    except Exception as video_error:

        print(
            "reply_video failed:",
            repr(video_error)
        )


    # video হিসেবে না হলে document হিসেবে চেষ্টা
    try:

        await message.reply_document(
            document=media_url,
            caption=filename[:1024]
        )

        return True

    except Exception as document_error:

        print(
            "reply_document failed:",
            repr(document_error)
        )

        return False


# ============================================================
# PICK VIDEO FROM PICKER
# ============================================================

def choose_video(picker):

    if not isinstance(picker, list):
        return None

    # প্রথমে video খুঁজবে
    for item in picker:

        if not isinstance(item, dict):
            continue

        if (
            item.get("type") == "video"
            and item.get("url")
        ):
            return item


    # video না থাকলে gif গ্রহণ
    for item in picker:

        if not isinstance(item, dict):
            continue

        if (
            item.get("type") == "gif"
            and item.get("url")
        ):
            return item


    return None


# ============================================================
# MAIN DOWNLOAD HANDLER
# ============================================================

@app.on_message(
    filters.text &
    filters.private &
    ~filters.bot
)
async def download_handler(
    client,
    message
):

    url = message.text.strip()

    # URL না হলে কিছু করবে না
    if not (
        url.startswith("http://")
        or url.startswith("https://")
    ):
        return


    status_message = await message.reply_text(
        "🔎 লিংকটি পরীক্ষা করা হচ্ছে..."
    )


    try:

        # ----------------------------------------------------
        # Cobalt API
        # ----------------------------------------------------

        data = await process_with_cobalt(url)

        status = data.get("status")

        print(
            "Cobalt result status:",
            status
        )


        # ====================================================
        # TUNNEL
        # ====================================================

        if status == "tunnel":

            media_url = data.get("url")

            filename = data.get(
                "filename",
                "video.mp4"
            )

            if not media_url:

                await status_message.edit_text(
                    "❌ Download URL পাওয়া যায়নি।"
                )

                return


            await status_message.edit_text(
                "📤 ভিডিও Telegram-এ পাঠানো হচ্ছে..."
            )


            success = await send_to_telegram(
                message,
                media_url,
                filename
            )


            if success:

                await status_message.delete()

            else:

                await status_message.edit_text(
                    "❌
