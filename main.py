import os
import logging
import asyncio
import threading

# ---------------------------------------------------------
# DENO / JS RUNTIME PATH
# ---------------------------------------------------------

_BIN_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "bin"
)

os.environ["PATH"] = (
    _BIN_DIR
    + os.pathsep
    + os.environ.get("PATH", "")
)

# ---------------------------------------------------------
# IMPORTS
# ---------------------------------------------------------

from flask import Flask

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

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


# ---------------------------------------------------------
# LOGGING
# ---------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# FLASK KEEP ALIVE
# ---------------------------------------------------------

flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Bot is alive!"


@flask_app.route("/health")
def health():
    return "OK"


def run_flask():
    flask_app.run(
        host="0.0.0.0",
        port=config.PORT,
        threaded=True
    )


# ---------------------------------------------------------
# KEYBOARDS
# ---------------------------------------------------------

def join_channel_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 চ্যানেলে জয়েন করুন",
                url=f"https://t.me/{config.CHANNEL_USERNAME}"
            )
        ],
        [
            InlineKeyboardButton(
                "✅ জয়েন করেছি, আবার চেষ্টা করুন",
                callback_data="check_sub"
            )
        ],
    ])


def welcome_keyboard() -> InlineKeyboardMarkup:

    buttons = [
        [
            InlineKeyboardButton(
                "ℹ️ সাপোর্টেড সাইট",
                callback_data="show_help"
            )
        ]
    ]

    if config.FORCE_SUB_ENABLED:
        buttons.append([
            InlineKeyboardButton(
                "📢 আমাদের চ্যানেল",
                url=f"https://t.me/{config.CHANNEL_USERNAME}"
            )
        ])

    return InlineKeyboardMarkup(buttons)


# ---------------------------------------------------------
# TEXT
# ---------------------------------------------------------

WELCOME_TEXT = (
    "👋 *স্বাগতম!*\n\n"
    "আমাকে যেকোনো YouTube লিংক পাঠান, "
    "আমি ভিডিও ডাউনলোড করে দেব।\n\n"
    "শুধু লিংকটা paste করুন, "
    "বাকিটা আমি করে দেব ⬇️"
)


HELP_TEXT_TEMPLATE = (
    "📋 *সাপোর্টেড সাইট:*\n"
    "{sites}\n\n"
    "শুধু নিজের বা download-permitted "
    "কন্টেন্টের জন্য ব্যবহার করুন।"
)


# ---------------------------------------------------------
# FORCE SUBSCRIBE
# ---------------------------------------------------------

async def require_subscription(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> bool:

    if not config.FORCE_SUB_ENABLED:
        return True

    user_id = update.effective_user.id

    if await utils.is_subscribed(
        context.bot,
        user_id
    ):
        return True

    text = (
        "🔒 বট ব্যবহার করতে হলে আগে আমাদের "
        "চ্যানেলে জয়েন করতে হবে।\n\n"
        "নিচের বাটনে চ্যানেলে জয়েন করে, "
        "তারপর *\"জয়েন করেছি\"* বাটনে চাপুন।"
    )

    if update.callback_query:

        await update.callback_query.message.edit_text(
            text,
            reply_markup=join_channel_keyboard(),
            parse_mode="Markdown"
        )

    elif update.message:

        await update.message.reply_text(
            text,
            reply_markup=join_channel_keyboard(),
            parse_mode="Markdown"
        )

    return False


# ---------------------------------------------------------
# START
# ---------------------------------------------------------

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
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
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
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
# NORMAL BUTTON HANDLER
# ---------------------------------------------------------

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    # -----------------------------------------
    # CHECK SUBSCRIPTION
    # -----------------------------------------

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

    # -----------------------------------------
    # HELP
    # -----------------------------------------

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
# YOUTUBE LINK HANDLER
# ---------------------------------------------------------

async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not await require_subscription(
        update,
        context
    ):
        return

    if not update.message or not update.message.text:
        return

    url = update.message.text.strip()

    # -----------------------------------------
    # URL CHECK
    # -----------------------------------------

    if not (
        url.startswith("http://")
        or
        url.startswith("https://")
    ):

        await update.message.reply_text(
            "⚠️ একটা সঠিক লিংক পাঠান।"
        )

        return

    # -----------------------------------------
    # STATUS
    # -----------------------------------------

    status_msg = await update.message.reply_text(
        "⚡ ভিডিওর তথ্য নেওয়া হচ্ছে..."
    )

    loop = asyncio.get_running_loop()

    try:

        # yt-dlp metadata lookup
        info = await loop.run_in_executor(
            None,
            utils.list_quality_options,
            url
        )

    except Exception as e:

        logger.exception(
            "Metadata lookup failed: %s",
            e
        )

        try:
            await status_msg.edit_text(
                "❌ এই লিংক থেকে তথ্য আনা যায়নি।\n"
                "লিংকটা সঠিক কিনা দেখুন।"
            )
        except Exception:
            pass

        return

    # -----------------------------------------
    # GET DATA
    # -----------------------------------------

    qualities = info.get(
        "qualities",
        {}
    )

    title = info.get(
        "title",
        "ভিডিও"
    )

    thumbnail = info.get(
        "thumbnail"
    )

    # -----------------------------------------
    # AVAILABLE QUALITIES
    # -----------------------------------------

    available = [
        q
        for q, ok in qualities.items()
        if ok
    ]

    if not available:

        try:
            await status_msg.edit_text(
                "❌ এই ভিডিওর কোনো compatible "
                "quality পাওয়া যায়নি।"
            )
        except Exception:
            pass

        return

    # -----------------------------------------
    # SAVE URL
    # -----------------------------------------

    short_id = utils.store_pending_url(
        url
    )

    # -----------------------------------------
    # BUTTON ORDER
    # -----------------------------------------

    ordered = []

    for height in utils.QUALITY_HEIGHTS:

        quality = f"{height}p"

        if quality in available:
            ordered.append(quality)

    if "audio" in available:
        ordered.append("audio")

    # -----------------------------------------
    # BUTTONS
    # -----------------------------------------

    labels = {}

    for quality in ordered:

        if quality == "audio":

            labels[quality] = "🎵 Audio"

        else:

            labels[quality] = f"🎬 {quality}"

    buttons = [
        InlineKeyboardButton(
            labels[q],
            callback_data=f"dl:{short_id}:{q}"
        )
        for q in ordered
    ]

    rows = [
        buttons[i:i + 2]
        for i in range(
            0,
            len(buttons),
            2
        )
    ]

    keyboard = InlineKeyboardMarkup(
        rows
    )

    # -----------------------------------------
    # DELETE STATUS
    # -----------------------------------------

    try:
        await status_msg.delete()
    except Exception:
        pass

    # -----------------------------------------
    # CAPTION
    # -----------------------------------------

    caption_text = (
        f"🎬 {title}\n\n"
        "⬇️ কোয়ালিটি বেছে নিন:"
    )

    # -----------------------------------------
    # SEND THUMBNAIL
    # -----------------------------------------

    if thumbnail:

        try:

            await update.message.reply_photo(
                photo=thumbnail,
                caption=caption_text[:1024],
                reply_markup=keyboard
            )

            return

        except Exception as e:

            logger.info(
                "Thumbnail failed: %s",
                e
            )

    # -----------------------------------------
    # FALLBACK TEXT
    # -----------------------------------------

    await update.message.reply_text(
        caption_text,
        reply_markup=keyboard
    )


# ---------------------------------------------------------
# QUALITY BUTTON
# ---------------------------------------------------------

async def quality_button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    # -----------------------------------------
    # CALLBACK DATA
    # dl:SHORT_ID:QUALITY
    # -----------------------------------------

    try:

        _,
        short_id,
        quality = query.data.split(
            ":",
            2
        )

    except Exception:

        await query.answer(
            "❌ ভুল request",
            show_alert=True
        )

        return

    # -----------------------------------------
    # GET URL
    # -----------------------------------------

    url = utils.get_pending_url(
        short_id
    )

    # -----------------------------------------
    # STATUS EDIT
    # -----------------------------------------

    async def update_status(
        text: str
    ):

        try:

            await query.message.edit_caption(
                caption=text
            )

        except Exception:

            try:

                await query.message.edit_text(
                    text
                )

            except Exception:
                pass

    # -----------------------------------------
    # URL EXPIRED
    # -----------------------------------------

    if not url:

        await update_status(
            "❌ লিংকটা মেয়াদোত্তীর্ণ হয়ে গেছে।\n"
            "আবার YouTube লিংক পাঠান।"
        )

        return

    # -----------------------------------------
    # TELEGRAM CACHE CHECK
    # -----------------------------------------

    cached_id = utils.get_cached_file_id(
        url,
        quality
    )

    if cached_id:

        try:

            if quality == "audio":

                await query.message.reply_audio(
                    audio=cached_id,
                    caption="⚡ Cached Audio"
                )

            else:

                await query.message.reply_video(
                    video=cached_id,
                    caption="⚡ Cached Video",
                    supports_streaming=True
                )

            try:
                await query.message.delete()
            except Exception:
                pass

            return

        except Exception as e:

            logger.info(
                "Cached file failed: %s",
                e
            )

    # -----------------------------------------
    # SHOW STATUS
    # -----------------------------------------

    await update_status(
        f"⚡ {quality} প্রস্তুত করা হচ্ছে..."
    )

    loop = asyncio.get_running_loop()

    try:

        # -------------------------------------
        # GET DIRECT YOUTUBE URL
        # -------------------------------------

        direct_url = await loop.run_in_executor(
            None,
            utils.get_direct_url_for_quality,
            url,
            quality
        )

        if not direct_url:

            await update_status(
                f"❌ {quality} পাওয়া যাচ্ছে না।"
            )

            return

        # -------------------------------------
        # AUDIO
        # -------------------------------------

        if quality == "audio":

            sent = await query.message.reply_audio(
                audio=direct_url,
                caption="✅ এখানে আপনার অডিও"
            )

            utils.cache_file_id(
                url,
                sent.audio.file_id,
                quality
            )

        # -------------------------------------
        # VIDEO
        # -------------------------------------

        else:

            sent = await query.message.reply_video(
                video=direct_url,
                caption="✅ এখানে আপনার ভিডিও",
                supports_streaming=True
            )

            utils.cache_file_id(
                url,
                sent.video.file_id,
                quality
            )

        # -------------------------------------
        # DELETE QUALITY MESSAGE
        # -------------------------------------

        try:
            await query.message.delete()
        except Exception:
            pass

    except Exception as e:

        logger.exception(
            "Video sending failed: %s",
            e
        )

        await update_status(
            "❌ ভিডিও পাঠানো যায়নি।\n"
            "আবার চেষ্টা করুন।"
        )


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main():

    # -----------------------------------------
    # BOT TOKEN CHECK
    # -----------------------------------------

    if not config.BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN missing! "
            "Render Dashboard → Environment → "
            "BOT_TOKEN যোগ করুন।"
        )

    # -----------------------------------------
    # START FLASK
    # -----------------------------------------

    threading.Thread(
        target=run_flask,
        daemon=True
    ).start()

    # -----------------------------------------
    # TELEGRAM APPLICATION
    # -----------------------------------------

    application = (
        Application
        .builder()
        .token(config.BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    # -----------------------------------------
    # HANDLERS
    # -----------------------------------------

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
        CallbackQueryHandler(
            quality_button_handler,
            pattern=r"^dl:"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_link
        )
    )

    # -----------------------------------------
    # START
    # -----------------------------------------

    logger.info(
        "⚡ Fast YouTube Downloader Bot starting..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ---------------------------------------------------------
# RUN
# ---------------------------------------------------------

if __name__ == "__main__":
    main()
