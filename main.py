import os
import logging
import threading

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
    buttons = [[InlineKeyboardButton("ℹ️ সাহায্য", callback_data="show_help")]]
    if config.FORCE_SUB_ENABLED:
        buttons.append([InlineKeyboardButton("📢 আমাদের চ্যানেল", url=f"https://t.me/{config.CHANNEL_USERNAME}")])
    return InlineKeyboardMarkup(buttons)


WELCOME_TEXT = (
    "👋 *স্বাগতম!*\n\n"
    "আমাকে যেকোনো YouTube লিংক পাঠান, আমি সেটা এখানে ফরওয়ার্ড করে দেব "
    "যাতে আপনি সরাসরি চ্যাটেই ভিডিও দেখতে পারেন।\n\n"
    "শুধু লিংকটা paste করুন ⬇️"
)

HELP_TEXT = (
    "📋 *কীভাবে কাজ করে:*\n"
    "YouTube লিংক পাঠান, আমি লিংকটা ফরওয়ার্ড করে দেব। "
    "Telegram নিজে থেকেই লিংকের নিচে প্লেয়ার সহ প্রিভিউ দেখাবে।"
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
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


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
        await query.message.edit_text(HELP_TEXT, parse_mode="Markdown")


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    No downloading, no yt-dlp, no direct URL lookups.
    We just send the URL back as plain text — Telegram's own link-preview
    engine takes over from there and renders the playable video card,
    exactly like when a person pastes a YouTube link themselves.
    """
    if not await require_subscription(update, context):
        return

    url = update.message.text.strip()

    if not (url.startswith("http://") or url.startswith("https://")):
        await update.message.reply_text("⚠️ একটা সঠিক লিংক পাঠান।")
        return

    if "youtu.be" not in url and "youtube.com" not in url:
        await update.message.reply_text("⚠️ শুধু YouTube লিংক সাপোর্ট করে।")
        return

    # Just echo the link — Telegram auto-generates the embedded preview.
    await update.message.reply_text(url)


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
