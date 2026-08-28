import os
import logging
import asyncio
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import yt_dlp


# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")

COOKIES_FILE = "cookies.txt"
DOWNLOAD_DIR = "downloads"

# Render automatically provides PORT
PORT = int(os.environ.get("PORT", 10000))

# Put your Render URL in Environment Variables:
# WEBHOOK_URL=https://advance-ut.onrender.com
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

WEBHOOK_PATH = "/telegram-webhook"

Path(DOWNLOAD_DIR).mkdir(exist_ok=True)


# ---------------------------------------------------------
# LOGGING
# ---------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# DOWNLOAD LOGIC
# ---------------------------------------------------------
def build_ydl_opts(output_path: str) -> dict:
    opts = {
        "format": "best[ext=mp4]/best",
        "outtmpl": output_path,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 3,
    }

    # Use cookies.txt only if it exists
    if os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE

    return opts


def download_video(url: str, file_id: str) -> str:
    """Runs yt-dlp in a separate thread because yt-dlp is synchronous."""

    output_path = os.path.join(
        DOWNLOAD_DIR,
        f"{file_id}.%(ext)s"
    )

    ydl_opts = build_ydl_opts(output_path)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

        return filename


# ---------------------------------------------------------
# TELEGRAM HANDLERS
# ---------------------------------------------------------
async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "👋 হ্যালো!\n\n"
        "আমাকে YouTube বা Terabox লিংক পাঠান, "
        "আমি ভিডিও ডাউনলোড করে দেব।"
    )


async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not update.message or not update.message.text:
        return

    url = update.message.text.strip()

    if not (
        url.startswith("http://")
        or url.startswith("https://")
    ):
        await update.message.reply_text(
            "⚠️ একটা সঠিক লিংক পাঠান।"
        )
        return

    status_msg = await update.message.reply_text(
        "⏳ ডাউনলোড হচ্ছে, একটু অপেক্ষা করুন..."
    )

    file_id = str(update.message.message_id)

    loop = asyncio.get_running_loop()

    filepath = None

    try:
        filepath = await loop.run_in_executor(
            None,
            download_video,
            url,
            file_id
        )

        await status_msg.edit_text(
            "📤 আপলোড হচ্ছে..."
        )

        with open(filepath, "rb") as video_file:
            await update.message.reply_video(
                video=video_file,
                caption="✅ এখানে আপনার ভিডিও"
            )

        await status_msg.delete()

    except yt_dlp.utils.DownloadError as e:

        err_text = str(e)

        if "Sign in to confirm" in err_text:
            await status_msg.edit_text(
                "❌ YouTube বলছে এটা bot request মনে করছে।\n"
                "এটা ঠিক করতে হলে সার্ভারে cookies.txt "
                "ফাইল আপডেট করতে হবে।"
            )
        else:
            await status_msg.edit_text(
                f"❌ ডাউনলোড ব্যর্থ হয়েছে:\n"
                f"{err_text[:300]}"
            )

        logger.error(
            "Download error: %s",
            err_text
        )

    except Exception as e:

        await status_msg.edit_text(
            "❌ একটা সমস্যা হয়েছে, আবার চেষ্টা করুন।"
        )

        logger.exception(
            "Unexpected error: %s",
            e
        )

    finally:
        # Delete downloaded file after sending
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                logger.exception(
                    "Could not delete file: %s",
                    filepath
                )


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN missing! "
            "Render Dashboard → Environment → "
            "add BOT_TOKEN"
        )

    if not WEBHOOK_URL:
        raise RuntimeError(
            "WEBHOOK_URL missing! "
            "Render Dashboard → Environment → "
            "add WEBHOOK_URL"
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Handlers
    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_link
        )
    )

    logger.info("Starting Telegram bot with webhook...")

    # -----------------------------------------------------
    # WEBHOOK
    # -----------------------------------------------------
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=WEBHOOK_URL + WEBHOOK_PATH,
        allowed_updates=Update.ALL_TYPES,
    )


# ---------------------------------------------------------
# START
# ---------------------------------------------------------
if __name__ == "__main__":
    main()
