import os
import logging
import asyncio
import threading

_BIN_DIR = os.path.join(
    os.path.dirname(
        os.path.abspath(__file__)
    ),
    "bin"
)

os.environ["PATH"] = (
    _BIN_DIR
    + os.pathsep
    + os.environ.get("PATH", "")
)


from flask import (
    Flask,
    redirect,
    abort,
)

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import config
import utils


# ---------------------------------------------------------
# LOGGING
# ---------------------------------------------------------

logging.basicConfig(
    format=(
        "%(asctime)s - "
        "%(name)s - "
        "%(levelname)s - "
        "%(message)s"
    ),
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# FLASK
# ---------------------------------------------------------

flask_app = Flask(__name__)


@flask_app.route("/")
def home():

    return "⚡ Fast Downloader Bot is running!"


@flask_app.route("/health")
def health():

    return "OK"


# ---------------------------------------------------------
# DIRECT DOWNLOAD ENDPOINT
# ---------------------------------------------------------

@flask_app.route(
    "/download/<short_id>/<quality>"
)
def direct_download(
    short_id,
    quality
):

    allowed = {
        "360p",
        "480p",
        "720p",
        "1080p",
        "audio"
    }

    if quality not in allowed:
        abort(404)

    url = utils.get_pending_url(
        short_id
    )

    if not url:
        return (
            "❌ Link expired. "
            "Please send the YouTube link again.",
            404
        )

    try:

        direct_url = (
            utils.get_direct_url_for_quality(
                url,
                quality
            )
        )

        if not direct_url:
            return (
                "❌ This quality is not available.",
                404
            )

        # -----------------------------------------
        # IMPORTANT:
        # Render DOES NOT download the video.
        #
        # Browser gets redirected directly to
        # YouTube CDN.
        # -----------------------------------------

        return redirect(
            direct_url,
            code=302
        )

    except Exception as e:

        logger.exception(
            "Direct download failed: %s",
            e
        )

        return (
            "❌ Download link তৈরি করা যায়নি।",
            500
        )


def run_flask():

    flask_app.run(
        host="0.0.0.0",
        port=config.PORT,
        threaded=True
    )


# ---------------------------------------------------------
# KEYBOARDS
# ---------------------------------------------------------

def join_channel_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 চ্যানেলে জয়েন করুন",
                url=(
                    f"https://t.me/"
                    f"{config.CHANNEL_USERNAME}"
                )
            )
        ],
        [
            InlineKeyboardButton(
                "✅ জয়েন করেছি",
                callback_data="check_sub"
            )
        ]
    ])


def welcome_keyboard():

    buttons = [
        [
            InlineKeyboardButton(
                "ℹ️ Supported Sites",
                callback_data="show_help"
            )
        ]
    ]

    if config.FORCE_SUB_ENABLED:

        buttons.append([
            InlineKeyboardButton(
                "📢 আমাদের চ্যানেল",
                url=(
                    f"https://t.me/"
                    f"{config.CHANNEL_USERNAME}"
                )
            )
        ])

    return InlineKeyboardMarkup(
        buttons
    )


# ---------------------------------------------------------
# TEXT
# ---------------------------------------------------------

WELCOME_TEXT = (
    "👋 *স্বাগতম!*\n\n"
    "আমাকে YouTube লিংক পাঠান।\n\n"
    "আমি আপনাকে সরাসরি "
    "⚡ Download Link দেব।"
)


HELP_TEXT_TEMPLATE = (
    "📋 *Supported Sites:*\n"
    "{sites}\n\n"
    "শুধু নিজের বা download-permitted "
    "কন্টেন্টের জন্য ব্যবহার করুন।"
)


# ---------------------------------------------------------
# SUBSCRIPTION
# ---------------------------------------------------------

async def require_subscription(
    update,
    context
):

    if not config.FORCE_SUB_ENABLED:
        return True

    user_id = (
        update.effective_user.id
    )

    if await utils.is_subscribed(
        context.bot,
        user_id
    ):
        return True

    text = (
        "🔒 আগে আমাদের চ্যানেলে "
        "জয়েন করুন।\n\n"
        "তারপর আবার চেষ্টা করুন।"
    )

    if update.callback_query:

        await (
            update.callback_query
            .message
            .edit_text(
                text,
                reply_markup=(
                    join_channel_keyboard()
                )
            )
        )

    elif update.message:

        await update.message.reply_text(
            text,
            reply_markup=(
                join_channel_keyboard()
            )
        )

    return False


# ---------------------------------------------------------
# START
# ---------------------------------------------------------

async def start(
    update,
    context
):

    if not await require_subscription(
        update,
        context
    ):
        return

    await update.message.reply_text(
        WELCOME_TEXT,
        reply_markup=welcome_keyboard(),
        parse_mode="Markdown"
    )


# ---------------------------------------------------------
# HELP
# ---------------------------------------------------------

async def help_command(
    update,
    context
):

    if not await require_subscription(
        update,
        context
    ):
        return

    sites = "\n".join(
        f"• {s}"
        for s in config.SUPPORTED_SITES
    )

    await update.message.reply_text(
        HELP_TEXT_TEMPLATE.format(
            sites=sites
        ),
        parse_mode="Markdown"
    )


# ---------------------------------------------------------
# NORMAL BUTTONS
# ---------------------------------------------------------

async def button_handler(
    update,
    context
):

    query = update.callback_query

    await query.answer()

    if query.data == "check_sub":

        if await utils.is_subscribed(
            context.bot,
            update.effective_user.id
        ):

            await query.message.edit_text(
                WELCOME_TEXT,
                reply_markup=welcome_keyboard(),
                parse_mode="Markdown"
            )

        else:

            await query.answer(
                "❌ এখনো জয়েন করেননি!",
                show_alert=True
            )

        return

    if query.data == "show_help":

        if not await require_subscription(
            update,
            context
        ):
            return

        sites = "\n".join(
            f"• {s}"
            for s in config.SUPPORTED_SITES
        )

        await query.message.edit_text(
            HELP_TEXT_TEMPLATE.format(
                sites=sites
            ),
            parse_mode="Markdown"
        )


# ---------------------------------------------------------
# YOUTUBE LINK
# ---------------------------------------------------------

async def handle_link(
    update,
    context
):

    if not await require_subscription(
        update,
        context
    ):
        return

    if not update.message:
        return

    url = update.message.text.strip()

    if not (
        url.startswith("http://")
        or url.startswith("https://")
    ):

        await update.message.reply_text(
            "⚠️ সঠিক YouTube লিংক পাঠান।"
        )

        return

    status = await update.message.reply_text(
        "⚡ ভিডিওর তথ্য নেওয়া হচ্ছে..."
    )

    loop = asyncio.get_running_loop()

    try:

        info = await loop.run_in_executor(
            None,
            utils.list_quality_options,
            url
        )

    except Exception as e:

        logger.exception(
            "Metadata error: %s",
            e
        )

        await status.edit_text(
            "❌ ভিডিওর তথ্য পাওয়া যায়নি।"
        )

        return

    qualities = info["qualities"]

    title = info["title"]

    thumbnail = info["thumbnail"]

    available = [
        q
        for q, ok in qualities.items()
        if ok
    ]

    if not available:

        await status.edit_text(
            "❌ কোনো compatible quality পাওয়া যায়নি।"
        )

        return

    # -----------------------------------------------------
    # CREATE SHORT ID
    # -----------------------------------------------------

    short_id = utils.store_pending_url(
        url
    )

    # -----------------------------------------------------
    # GET PUBLIC BASE URL
    # -----------------------------------------------------

    base_url = os.environ.get(
        "RENDER_EXTERNAL_URL"
    )

    if not base_url:

        base_url = getattr(
            config,
            "BASE_URL",
            ""
        )

    base_url = base_url.rstrip("/")

    if not base_url:

        await status.edit_text(
            "❌ Server BASE_URL সেট করা নেই।"
        )

        logger.error(
            "RENDER_EXTERNAL_URL / BASE_URL missing"
        )

        return

    # -----------------------------------------------------
    # BUTTONS
    # -----------------------------------------------------

    rows = []

    current_row = []

    for height in utils.QUALITY_HEIGHTS:

        quality = f"{height}p"

        if quality not in available:
            continue

        download_url = (
            f"{base_url}/download/"
            f"{short_id}/{quality}"
        )

        current_row.append(
            InlineKeyboardButton(
                f"⚡ {quality} Download",
                url=download_url
            )
        )

        if len(current_row) == 2:

            rows.append(
                current_row
            )

            current_row = []

    if "audio" in available:

        audio_url = (
            f"{base_url}/download/"
            f"{short_id}/audio"
        )

        current_row.append(
            InlineKeyboardButton(
                "🎵 Audio Download",
                url=audio_url
            )
        )

    if current_row:
        rows.append(
            current_row
        )

    keyboard = InlineKeyboardMarkup(
        rows
    )

    # -----------------------------------------------------
    # DELETE STATUS
    # -----------------------------------------------------

    try:
        await status.delete()
    except Exception:
        pass

    # -----------------------------------------------------
    # CAPTION
    # -----------------------------------------------------

    caption = (
        f"🎬 {title}\n\n"
        "⚡ নিচের quality বেছে নিন:\n\n"
        "📥 Download চাপলে সরাসরি "
        "download শুরু হবে।"
    )

    # -----------------------------------------------------
    # SEND THUMBNAIL
    # -----------------------------------------------------

    if thumbnail:

        try:

            await update.message.reply_photo(
                photo=thumbnail,
                caption=caption[:1024],
                reply_markup=keyboard
            )

            return

        except Exception as e:

            logger.info(
                "Thumbnail failed: %s",
                e
            )

    # -----------------------------------------------------
    # TEXT FALLBACK
    # -----------------------------------------------------

    await update.message.reply_text(
        caption,
        reply_markup=keyboard
    )


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main():

    if not config.BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN missing!"
        )

    # Flask
    threading.Thread(
        target=run_flask,
        daemon=True
    ).start()

    # Telegram
    application = (
        Application
        .builder()
        .token(config.BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_link
        )
    )

    application.add_handler(
        __import__(
            "telegram.ext",
            fromlist=[
                "CallbackQueryHandler"
            ]
        ).CallbackQueryHandler(
            button_handler
        )
    )

    logger.info(
        "⚡ FAST DIRECT DOWNLOAD BOT STARTED"
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
