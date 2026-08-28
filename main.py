import os
import asyncio
import aiohttp
from pyrogram import Client, filters

BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_ID = int(os.environ.get("API_ID", "123456"))
API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH")

app = Client("downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("হ্যালো! আমাকে YouTube, Instagram বা যেকোনো লিঙ্ক পাঠান, আমি ভিডিও নামিয়ে দেব।")

@app.on_message(filters.text & filters.private)
async def download_video(client, message):
    url = message.text.strip()
    if not url.startswith("http"):
        await message.reply_text("দয়া করে সঠিক লিঙ্ক পাঠান।")
        return

    msg = await message.reply_text("ডাউনলোড প্রসেস হচ্ছে, একটু অপেক্ষা করুন...")
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {
        "url": url,
        "videoQuality": "720"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.cobalt.tools/api/json", json=payload, headers=headers) as response:
                res_data = await response.json()
                
                if res_data.get("status") in ["stream", "redirect"]:
                    video_url = res_data.get("url")
                    await msg.edit_text("টেলিগ্রামে আপলোড করা হচ্ছে...")
                    await message.reply_video(video=video_url)
                    await msg.delete()
                elif res_data.get("status") == "picker":
                    video_url = res_data.get("picker")[0].get("url")
                    await msg.edit_text("টেলিগ্রামে আপলোড করা হচ্ছে...")
                    await message.reply_video(video=video_url)
                    await msg.delete()
                else:
                    await msg.edit_text("ভিডিওটি প্রসেস করা যায়নি, আবার চেষ্টা করুন।")

    except Exception as e:
        await msg.edit_text(f"ত্রুটি ঘটেছে: {str(e)}")

if __name__ == "__main__":
    app.run()
    
