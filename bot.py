import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import yt_dlp
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters


class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def log_message(self, format, *args):
        pass  # সার্ভার লগ চুপ রাখতে


def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    server.serve_forever()

# ================== সেটিংস ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN")   # Render-এর Environment Variable থেকে আসবে
DOWNLOAD_DIR = "downloads"
# =============================================

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable সেট করা নেই। Render Dashboard -> Environment এ গিয়ে যোগ করুন।")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if "youtube.com" not in url and "youtu.be" not in url:
        await update.message.reply_text("একটা বৈধ YouTube লিংক পাঠান।")
        return

    status_msg = await update.message.reply_text("ডাউনলোড হচ্ছে, একটু অপেক্ষা করুন...")

    ydl_opts = {
        "format": "best[ext=mp4]/best",
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "max_filesize": 50 * 1024 * 1024,  # Telegram Bot API লিমিট ৫০MB
    }

    filename = None
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            title = info.get("title", "video")

        await status_msg.edit_text(f"পাঠানো হচ্ছে: {title}")

        with open(filename, "rb") as video_file:
            await update.message.reply_video(video=video_file, caption=title)

    except yt_dlp.utils.DownloadError as e:
        await status_msg.edit_text(f"ডাউনলোড করা যায়নি: {str(e)[:200]}")
    except Exception as e:
        await status_msg.edit_text(f"সমস্যা হয়েছে: {str(e)[:200]}")
    finally:
        if filename and os.path.exists(filename):
            os.remove(filename)


def main():
    threading.Thread(target=run_dummy_server, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    print("বট চালু হয়েছে...")
    app.run_polling()


if __name__ == "__main__":
    main()
