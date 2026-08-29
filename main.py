import os
import logging
import asyncio
import threading
from pathlib import Path

# Make the Deno JS runtime (installed into ./bin by the Render build
# command) visible to yt-dlp — YouTube now requires a JS runtime to
# decode video signatures, and Render's sandbox won't let us apt-get
# install one system-wide, so we install it into the project folder
# and add that folder to PATH here, before yt-dlp is ever used.
_BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
os.environ["PATH"] = _BIN_DIR + os.pathsep + os.environ.get("PATH", "")

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import yt_dlp

import config
import utils

Path(config.DOWNLOAD_DIR).mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# KEEP-ALIVE WEB SERVER (Render Web Service needs an open port)
# ---------------------------------------------------------
flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Bot is alive!"


def run_flask():
    flask_app.run(host="0.0.0.0", port=config.PORT)


# ---------------------------------------------------------
# UI HELPERS
# ---------------------------------------------------------
def join_channel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 চ্যানেলে জয়েন করুন", url=f"https://t.me/{config.CHANNEL_USERNAME}")],
        [InlineKeyboardButton("✅ জয়েন করেছি, আবার চেষ্টা করুন", callback_data="check_sub")],
    ])


def welcome_keyboard() -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton("ℹ️ সাপোর্টেড সাইট", callback_data="show_help")]]
    if config.FORCE_SUB_ENABLED:
        buttons.append([InlineKeyboardButton("📢 আমাদের চ্যানেল", url=f"https://t.me/{config.CHANNEL_USERNAME}")])
    return InlineKeyboardMarkup(buttons)


WELCOME_TEXT = (
    "👋 *স্বাগতম!*\n\n"
    "আমাকে যেকোনো YouTube লিংক পাঠান, আমি ভিডিও ডাউনলোড করে দেব।\n\n"
    "শুধু লিংকটা paste করুন, বাকিটা আমি করে দেব ⬇️"
)

HELP_TEXT_TEMPLATE = (
    "📋 *সাপোর্টেড সাইট:*\n{sites}\n\n"
    "⚠️ সর্বোচ্চ ফাইল সাইজ: {size}MB (Telegram-এর নিয়ম)\n"
    "শুধু নিজের বা download-permitted কন্টেন্টের জন্য ব্যবহার করুন।"
)


# ---------------------------------------------------------
# FORCE-SUBSCRIBE GATE
# ---------------------------------------------------------
async def require_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Returns True if user can proceed, otherwise shows the join-channel prompt."""
    if not config.FORCE_SUB_ENABLED:
        return True

    user_id = update.effective_user.id
    if await utils.is_subscribed(context.bot, user_id):
        return True

    text = (
        "🔒 বট ব্যবহার করতে হলে আগে আমাদের চ্যানেলে জয়েন করতে হবে।\n\n"
        "নিচের বাটনে চ্যানেলে জয়েন করে, তারপর *\"জয়েন করেছি\"* বাটনে চাপুন।"
    )
    if update.callback_query:
        await update.callback_query.message.edit_text(
            text, reply_markup=join_channel_keyboard(), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=join_channel_keyboard(), parse_mode="Markdown"
        )
    return False


# ---------------------------------------------------------
# TELEGRAM HANDLERS
# ---------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_subscription(update, context):
        return
    await update.message.reply_text(
        WELCOME_TEXT, reply_markup=welcome_keyboard(), parse_mode="Markdown"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_subscription(update, context):
        return
    sites = "\n".join(f"• {s}" for s in config.SUPPORTED_SITES)
    await update.message.reply_text(
        HELP_TEXT_TEMPLATE.format(sites=sites, size=config.MAX_FILE_SIZE_MB),
        parse_mode="Markdown",
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles inline button taps."""
    query = update.callback_query
    await query.answer()

    if query.data == "check_sub":
        if await utils.is_subscribed(context.bot, update.effective_user.id):
            await query.message.edit_text(
                WELCOME_TEXT, reply_markup=welcome_keyboard(), parse_mode="Markdown"
            )
        else:
            await query.answer("❌ এখনো জয়েন করেননি!", show_alert=True)

    elif query.data == "show_help":
        if not await require_subscription(update, context):
            return
        sites = "\n".join(f"• {s}" for s in config.SUPPORTED_SITES)
        await query.message.edit_text(
            HELP_TEXT_TEMPLATE.format(sites=sites, size=config.MAX_FILE_SIZE_MB),
            parse_mode="Markdown",
        )


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_subscription(update, context):
        return

    url = update.message.text.strip()

    if not (url.startswith("http://") or url.startswith("https://")):
        await update.message.reply_text("⚠️ একটা সঠিক লিংক পাঠান।")
        return

    # Best case: we've already sent this exact video to Telegram before.
    # Reuse Telegram's own file_id — this sends a tiny reference instead of
    # re-downloading from YouTube and re-uploading the whole file, which is
    # what actually costs Render bandwidth.
    tg_file_id = utils.get_cached_file_id(url)
    if tg_file_id:
        try:
            await update.message.reply_video(video=tg_file_id, caption="✅ এখানে আপনার ভিডিও")
            return
        except Exception as e:
            # file_id can occasionally go stale — fall through to a normal
            # download instead of failing the request.
            logger.warning("Cached file_id failed, re-downloading: %s", e)

    cached = utils.get_cached_file(url)
    if cached:
        await update.message.reply_text("⚡ আগে থেকেই আছে, পাঠাচ্ছি...")
        with open(cached, "rb") as video_file:
            sent = await update.message.reply_video(video=video_file, caption="✅ এখানে আপনার ভিডিও")
        utils.cache_file_id(url, sent.video.file_id)
        return

    status_msg = await update.message.reply_text("⏳ ডাউনলোড হচ্ছে, একটু অপেক্ষা করুন...")

    dl_id = str(update.message.message_id)
    loop = asyncio.get_running_loop()

    # Bandwidth-saving attempt: ask Telegram to fetch the video directly
    # from YouTube's own CDN URL instead of us downloading + re-uploading.
    # This only works when a combined video+audio format exists and when
    # YouTube's URL isn't IP-locked to our server — so we try it first and
    # silently fall back to the normal flow on any failure.
    try:
        direct_url = await loop.run_in_executor(None, utils.get_direct_stream_url, url)
        if direct_url:
            sent = await update.message.reply_video(video=direct_url, caption="✅ এখানে আপনার ভিডিও")
            utils.cache_file_id(url, sent.video.file_id)
            await status_msg.delete()
            return
    except Exception as e:
        logger.info("Direct-URL send failed, falling back to normal download: %s", e)

    try:
        filepath = await loop.run_in_executor(None, utils.download_video, url, dl_id)

        if not utils.check_file_size(filepath):
            await status_msg.edit_text(
                f"❌ ভিডিওটা {config.MAX_FILE_SIZE_MB}MB এর চেয়ে বড়, "
                "Telegram-এর নিয়মে এত বড় ফাইল বট দিয়ে পাঠানো যায় না।"
            )
            os.remove(filepath)
            return

        await status_msg.edit_text("📤 আপলোড হচ্ছে...")

        with open(filepath, "rb") as video_file:
            sent = await update.message.reply_video(video=video_file, caption="✅ এখানে আপনার ভিডিও")

        utils.cache_file(url, filepath)
        utils.cache_file_id(url, sent.video.file_id)
        await status_msg.delete()

    except yt_dlp.utils.DownloadError as e:
        err_text = str(e)
        await status_msg.edit_text(utils.friendly_error_message(err_text))
        logger.error("Download error: %s", err_text)

    except Exception as e:
        await status_msg.edit_text("❌ একটা অপ্রত্যাশিত সমস্যা হয়েছে, আবার চেষ্টা করুন।")
        logger.exception("Unexpected error: %s", e)


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():
    if not config.BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN missing! Render dashboard -> Environment -> add BOT_TOKEN"
        )

    threading.Thread(target=run_flask, daemon=True).start()

    application = Application.builder().token(config.BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
