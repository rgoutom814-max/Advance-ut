import os
import asyncio
from pyrogram import Client, filters
import yt_dlp

BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_ID = int(os.environ.get("API_ID", "123456"))
API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH")

app = Client("downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("হ্যালো! আমাকে যেকোনো ভিডিও বা ফাইলের লিঙ্ক পাঠান, আমি ডাউনলোড করে দেব।")

@app.on_message(filters.text & filters.private)
async def download_video(client, message):
    url = message.text
    if not url.startswith("http"):
        await message.reply_text("দয়া করে সঠিক লিঙ্ক পাঠান।")
        return

    msg = await message.reply_text("ডাউনলোড শুরু হচ্ছে, একটু অপেক্ষা করুন...")
    
    ydl_opts = {
        'format': 'best',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'max_filesize': 2000000000,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

        await msg.edit_text("টেলিগ্রামে আপলোড করা হচ্ছে...")
        await message.reply_video(video=filename, caption=info.get('title', 'Video'))
        
        if os.path.exists(filename):
            os.remove(filename)
        await msg.delete()

    except Exception as e:
        await msg.edit_text(f"ত্রুটি ঘটেছে: {str(e)}")

if __name__ == "__main__":
    app.run()
    
