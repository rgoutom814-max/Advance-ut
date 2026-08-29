import os
import logging
import asyncio
import threading

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

import config
import utils

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
    "আমাকে YouTube, Facebook, Instagram বা Twitter/X-এর যেকোনো লিংক পাঠান, "
    "আমি কোয়ালিটি অপশন দেখাব।\n\n"
    "শুধু লিংকটা paste করুন, বাকিটা আমি করে দেব ⬇️"
)

HELP_TEXT_TEMPLATE = (
    "📋 *সাপোর্টেড সাইট:*\n{sites}\n\n"
    "শুধু নিজের বা download-permitted কন্টেন্টের জন্য ব্যবহার করুন।\n\n"
    "⚠️ Telegram বটের নিয়ম অনুযায়ী ৫০MB-র বেশি সাইজের ফাইল পাঠানো যায় না — "
    "বড় ভিডিওর ক্ষেত্রে কম কোয়ালিটি বেছে নিন।"
)


# ---------------------------------------------------------
# FORCE-SUBSCRIBE GATE
# ---------------------------------------------------------
async def require_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
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
        HELP_TEXT_TEMPLATE.format(sites=sites),
        parse_mode="Markdown",
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            HELP_TEXT_TEMPLATE.format(sites=sites),
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
    # Reuse Telegram's own file_id instead of downloading again.
    tg_file_id = utils.get_cached_file_id(url)
    if tg_file_id:
        try:
            await update.message.reply_video(video=tg_file_id, caption="✅ এখানে আপনার ভিডিও")
            return
        except Exception as e:
            logger.warning("Cached file_id failed, continuing normally: %s", e)

    status_msg = await update.message.reply_text("🔍 কোয়ালিটি খুঁজছি...")
    loop = asyncio.get_running_loop()

    try:
        info = await loop.run_in_executor(None, utils.list_quality_options, url)
    except Exception as e:
        logger.info("Quality lookup failed: %s", e)
        await status_msg.edit_text(
            "❌ এই লিংকটা থেকে তথ্য আনা যায়নি, লিংকটা সঠিক কিনা দেখুন।"
        )
        return

    qualities = info["qualities"]
    title = info["title"]
    thumbnail = info["thumbnail"]

    available = [q for q, ok in qualities.items() if ok]
    if not available:
        await status_msg.edit_text(
            "❌ এই ভিডিওটা এই মুহূর্তে পাঠানো যাচ্ছে না, একটু পরে আবার চেষ্টা করুন।"
        )
        return

    short_id = utils.store_pending_url(url)

    # Order: video qualities high-to-low, then audio, two per row.
    ordered = [f"{h}p" for h in utils.QUALITY_HEIGHTS if f"{h}p" in available]
    if "audio" in available:
        ordered.append("audio")

    labels = {q: ("🎵 Audio" if q == "audio" else f"🎬 {q}") for q in ordered}
    buttons = [
        InlineKeyboardButton(labels[q], callback_data=f"dl:{short_id}:{q}")
        for q in ordered
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]

    await status_msg.delete()

    caption_text = f"🎬 {title}\n\nকোয়ালিটি বেছে নিন:"
    if thumbnail:
        try:
            await update.message.reply_photo(
                photo=thumbnail,
                caption=caption_text[:1024],  # Telegram caption length limit
                reply_markup=InlineKeyboardMarkup(rows),
            )
            return
        except Exception as e:
            logger.info("Thumbnail send failed, falling back to text: %s", e)

    await update.message.reply_text(caption_text, reply_markup=InlineKeyboardMarkup(rows))


async def quality_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, short_id, quality = query.data.split(":", 2)
    url = utils.get_pending_url(short_id)

    async def update_status(text: str):
        try:
            await query.message.edit_caption(caption=text)
        except Exception:
            await query.message.edit_text(text)

    if not url:
        await update_status("❌ লিংকটা মেয়াদোত্তীর্ণ হয়ে গেছে, আবার পাঠান।")
        return

    await update_status(f"⏳ {quality} ডাউনলোড হচ্ছে...")

    loop = asyncio.get_running_loop()

    # Actually download to local disk, then upload the local file. This
    # avoids the "Failed to get http url content" error Telegram hits when
    # given a YouTube-issued direct URL — those URLs are locked to the IP
    # that requested them (our server), so Telegram's own servers can't
    # fetch them directly.
    result = await loop.run_in_executor(None, utils.download_media, url, quality)

    if not result:
        await update_status(
            f"❌ {quality}-তে পাঠানো যাচ্ছে না (ফাইল অনেক বড় হতে পারে, বা এই মুহূর্তে সমস্যা হচ্ছে)। "
            "একটু পরে বা অন্য কোয়ালিটি দিয়ে আবার চেষ্টা করুন।"
        )
        return

    await update_status("📤 আপলোড হচ্ছে...")

    filepath = result["path"]
    try:
        with open(filepath, "rb") as media_file:
            if result["is_audio"]:
                sent = await query.message.reply_audio(audio=media_file, caption="✅ এখানে আপনার অডিও")
                utils.cache_file_id(url, sent.audio.file_id)
            else:
                sent = await query.message.reply_video(video=media_file, caption="✅ এখানে আপনার ভিডিও")
                utils.cache_file_id(url, sent.video.file_id)

        await query.message.delete()

    except Exception as e:
        logger.info("Upload failed: %s", e)
        await update_status("❌ আপলোড করার সময় সমস্যা হয়েছে, একটু পরে আবার চেষ্টা করুন।")

    finally:
        # Always clean up the local file, whether upload succeeded or not —
        # this is what keeps disk usage from growing over time.
        utils.delete_file(filepath)


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
    application.add_handler(CallbackQueryHandler(quality_button_handler, pattern=r"^dl:"))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
