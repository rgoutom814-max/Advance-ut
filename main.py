import os
import logging
import asyncio
import threading
from pathlib import Path

from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import yt_dlp


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")

DOWNLOAD_DIR = "downloads"
COOKIES_FILE = "cookies.txt"

PORT = int(os.environ.get("PORT", 10000))

Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# RENDER WEB SERVER
# =========================================================

flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Advance bot is running!"


def run_flask():
    flask_app.run(
        host="0.0.0.0",
        port=PORT,
        use_reloader=False
    )


# =========================================================
# YT-DLP OPTIONS
# =========================================================

def build_ydl_opts(output_path):
    opts = {
        "format": "best[ext=mp4]/best",

        "outtmpl": output_path,

        "noplaylist": True,

        "quiet": False,

        "no_warnings": False,

        "retries": 10,

        "fragment_retries": 10,

        "file_access_retries": 5,

        "socket_timeout": 30,

        "continuedl": True,

        "overwrites": True,

        # YouTube-এর জন্য browser-এর মতো User-Agent
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 10; K) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 Mobile Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },

        "extractor_retries": 5,

        "ignoreerrors": False,
    }

    # cookies.txt থাকলে ব্যবহার করবে
    if os.path.isfile(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE

    return opts


# =========================================================
# DOWNLOAD
# =========================================================

def download_video(url, file_id):

    output_path = os.path.join(
        DOWNLOAD_DIR,
        f"{file_id}.%(ext)s"
    )

    opts = build_ydl_opts(output_path)

    with yt_dlp.YoutubeDL(opts) as ydl:

        info = ydl.extract_info(
            url,
            download=True
        )

        if not info:
            raise Exception("ভিডিও পাওয়া যায়নি।")

        filename = ydl.prepare_filename(info)

        # কিছু ক্ষেত্রে extension পরিবর্তন হতে পারে
        if os.path.exists(filename):
            return filename

        base = os.path.splitext(filename)[0]

        for ext in ["mp4", "webm", "mkv", "m4a"]:
            test_file = base + "." + ext

            if os.path.exists(test_file):
                return test_file

        raise Exception("ডাউনলোড হয়েছে কিন্তু ফাইল পাওয়া যাচ্ছে না।")


# =========================================================
# /START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "👋 হ্যালো!\n\n"
        "YouTube বা অন্য supported video link পাঠান।\n\n"
        "⏳ আমি ভিডিও ডাউনলোড করে পাঠানোর চেষ্টা করব।"
    )


# =========================================================
# LINK HANDLER
# =========================================================

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.text:
        return

    url = update.message.text.strip()

    if not (
        url.startswith("http://")
        or url.startswith("https://")
    ):
        await update.message.reply_text(
            "⚠️ দয়া করে একটি সঠিক ভিডিও লিংক পাঠান।"
        )
        return

    status = await update.message.reply_text(
        "⏳ ভিডিও চেক করছি..."
    )

    file_id = str(update.message.message_id)

    loop = asyncio.get_running_loop()

    try:

        await status.edit_text(
            "⏳ ভিডিও ডাউনলোড হচ্ছে...\n"
            "একটু অপেক্ষা করুন।"
        )

        filepath = await loop.run_in_executor(
            None,
            download_video,
            url,
            file_id
        )

        if not os.path.exists(filepath):
            raise Exception("ভিডিও ফাইল পাওয়া যায়নি।")

        filesize = os.path.getsize(filepath)

        # Telegram bot-এর সাধারণ upload limit মাথায় রেখে
        if filesize > 49 * 1024 * 1024:

            await status.edit_text(
                "❌ ভিডিওটি Telegram-এ পাঠানোর জন্য অনেক বড়।\n"
                "ছোট ভিডিও দিয়ে চেষ্টা করুন।"
            )

            os.remove(filepath)
            return

        await status.edit_text(
            "📤 ভিডিও Telegram-এ পাঠানো হচ্ছে..."
        )

        with open(filepath, "rb") as video_file:

            await update.message.reply_video(
                video=video_file,
                caption="✅ এখানে আপনার ভিডিও"
            )

        await status.delete()

        # ফাইল delete
        if os.path.exists(filepath):
            os.remove(filepath)

    except yt_dlp.utils.DownloadError as e:

        error = str(e)

        logger.error(
            "yt-dlp error: %s",
            error
        )

        if (
            "Sign in" in error
            or "bot" in error.lower()
            or "reload" in error.lower()
            or "confirm" in error.lower()
        ):

            await status.edit_text(
                "❌ YouTube এই request-টি block করেছে।\n\n"
                "কিছুক্ষণ পরে আবার চেষ্টা করুন।\n"
                "প্রয়োজনে cookies.txt / YouTube authentication "
                "configure করতে হবে।"
            )

        else:

            await status.edit_text(
                "❌ ভিডিও ডাউনলোড করা যায়নি।\n\n"
                f"{error[:500]}"
            )

    except Exception as e:

        logger.exception(
            "Unexpected error"
        )

        await status.edit_text(
            "❌ সমস্যা হয়েছে:\n"
            f"{str(e)[:500]}"
        )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN পাওয়া যায়নি। "
            "Render Environment Variables-এ BOT_TOKEN সেট করুন।"
        )

    # Render-এর জন্য web server
    threading.Thread(
        target=run_flask,
        daemon=True
    ).start()

    # Telegram bot
    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_link
        )
    )

    logger.info(
        "Advance bot started successfully!"
    )

    # WEBHOOK নয় — polling
    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
