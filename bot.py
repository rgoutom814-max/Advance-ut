import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from y2mate_api import Handler
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters


class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def log_message(self, format, *args):
        pass


def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    server.serve_forever()


# ================== সেটিংস ==================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
# =============================================

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable সেট করা নেই।")


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if "youtube.com" not in url and "youtu.be" not in url:
        await update.message.reply_text("একটা বৈধ YouTube লিংক পাঠান।")
        return

    status_msg = await update.message.reply_text("প্রসেস করা হচ্ছে, একটু অপেক্ষা করুন...")

    try:
        h = Handler(query=url, timeout=30)
        found = False
        for result in h.run(format="mp4", quality="auto", limit=1):
            dlink = result.get("dlink")
            title = result.get("title", "video")
            if dlink:
                found = True
                await status_msg.edit_text(f"🎬 {title}\nডাউনলোড লিংক:\n{dlink}")
        if not found:
            await status_msg.edit_text("ডাউনলোড লিংক পাওয়া যায়নি।")
    except Exception as e:
        await status_msg.edit_text(f"সমস্যা হয়েছে: {str(e)[:300]}")


def main():
    threading.Thread(target=run_dummy_server, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    print("বট চালু হয়েছে...")
    app.run_polling()


if __name__ == "__main__":
    main()
