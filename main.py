import os
import asyncio
import aiohttp

from pyrogram import Client, filters
from pyrogram.errors import RPCError


# ==========================================
# CONFIG
# ==========================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

# নিজের/অনুমোদিত Cobalt instance হলে এখানে তার URL দাও।
# উদাহরণ: https://your-cobalt-instance.example
COBALT_API = os.getenv(
    "COBALT_API",
    "https://api.cobalt.tools"
).rstrip("/")


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

if not API_ID:
    raise RuntimeError("API_ID is missing")

if not API_HASH:
    raise RuntimeError("API_HASH is missing")

try:
    API_ID = int(API_ID)
except ValueError:
    raise RuntimeError("API_ID must be a number")


# ==========================================
# TELEGRAM
# ==========================================

app = Client(
    "downloader_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)


# ==========================================
# START
# ==========================================

@app.on_message(
    filters.command("start") &
    filters.private
)
async def start(client, message):

    await message.reply_text(
        "👋 হ্যালো!\n\n"
        "একটি public video/media link পাঠান।\n"
        "আমি সেটি প্রসেস করার চেষ্টা করব।"
    )


# ==========================================
# ERROR TEXT
# ==========================================

def get_error_text(data):

    error = data.get("error", {})

    if isinstance(error, dict):
        code = error.get("code", "unknown")
        context = error.get("context", {})

        if code == "error.api.rate_exceeded":
            return "⏳ অনেক বেশি request হয়েছে। একটু পরে আবার চেষ্টা করুন।"

        if code == "error.api.service.unsupported":
            return "❌ এই platform বর্তমানে downloader-এ supported নয়।"

        if code == "error.api.platform.unsupported":
            return "❌ এই platform বর্তমানে supported নয়।"

        if code == "error.api.auth.key.invalid":
            return "❌ Downloader API key ভুল।"

        if code == "error.api.capacity":
            return "⏳ Downloader server এখন ব্যস্ত। পরে আবার চেষ্টা করুন।"

        if code == "error.api.generic":
            return "❌ Downloader server-এ সমস্যা হয়েছে।"

        limit = context.get("limit")

        if limit:
            return (
                f"❌ এই ভিডিওটি server limit-এর বাইরে। "
                f"Limit: {limit}"
            )

        return f"❌ Download করা যায়নি।\nCode: {code}"

    return "❌ Download করা যায়নি।"


# ==========================================
# SEND VIDEO
# ==========================================

async def send_media(message, url, filename=None):

    caption = filename or "Downloaded video"

    try:

        await message.reply_video(
            video=url,
            caption=caption[:1024],
            supports_streaming=True
        )

        return True

    except Exception as first_error:

        print(
            "Direct Telegram upload failed:",
            repr(first_error)
        )

        # দ্বিতীয়বার document হিসেবে চেষ্টা
        try:

            await message.reply_document(
                document=url,
                caption=caption[:1024]
            )

            return True

        except Exception as second_error:

            print(
                "Document upload failed:",
                repr(second_error)
            )

            return False


# ==========================================
# COBALT
# ==========================================

async
